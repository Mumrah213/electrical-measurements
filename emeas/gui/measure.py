"""Live measurement tab: controls + plot, streaming to plot and store.

Sweep A (always active) and Sweep B (enabled for a 2D map) each hold one or
more instrument rows picked by dropdown from the current
:class:`~emeas.gui.instruments.InstrumentRegistry` -- see
:mod:`emeas.gui.sweep_axis`. Multiple rows in one axis are driven in lockstep
(same step index, independent start/stop), e.g. "Sweep A: yoko1 (start, end),
yoko2 (start, end) synchronized with yoko1". Sweep C holds any number of other
instruments at one constant value for the duration of a run (a fixed sidegate,
say), via :func:`emeas.measure.iter_linear_sweep_group`'s /
:func:`emeas.measure.iter_map_2d_group`'s ``fixed=`` parameter. An instrument
can only be claimed by one of A/B/C at a time -- see
:mod:`emeas.gui.sweep_axis` for how that's enforced across the three.

Runs stream via a :class:`~emeas.gui.worker.MeasurementWorker` on a
``QThread`` into a plot and the HDF5 store. Instrument choices re-read the
registry each time a run starts, so edits made in the Instruments tab take
effect immediately.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QThread, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from emeas.gui import plotting
from emeas.gui.sweep_axis import FixedValueWidget, SweepAxisWidget
from emeas.gui.theme import apply_plot_theme
from emeas.gui.worker import MeasurementWorker
from emeas.measure import iter_linear_sweep_group, iter_map_2d_group


def _is_source(role: str, inst) -> bool:
    from emeas.sources.base import VoltageSource
    return isinstance(inst, VoltageSource)


def _is_meter(role: str, inst) -> bool:
    from emeas.meters.base import Multimeter
    return isinstance(inst, Multimeter)


class MeasureTab(QWidget):
    #: emitted (run_number) when a run finishes, so the browser can refresh
    runFinished = pyqtSignal(int)

    def __init__(self, registry, store, theme_watcher=None):
        super().__init__()
        self._registry = registry
        self._store = store
        self._registry.changed.connect(self._on_registry_changed)
        if theme_watcher is not None:
            theme_watcher.changed.connect(self._apply_theme)

        self._thread: QThread | None = None
        self._worker: MeasurementWorker | None = None
        self._run = None  # RunWriter for the active run
        self._x: list[float] = []
        self._y: list[float] = []
        self._grid: np.ndarray | None = None
        self._display_grid: np.ndarray | None = None  # grid as currently shown (post-quantity)
        self._current_iy = 0        # row being streamed right now
        self._cut_row: int | None = None  # user-pinned cut row (click on the map)
        self._history_curves: list = []   # completed rows kept as colored traces
        self._completed_upto = 0          # rows below this index are already in history

        # Streamed points only mark the plot dirty; this timer repaints at a
        # bounded rate. Redrawing per point (full-grid dI/dV + image + histogram
        # on every signal) floods the event loop at dummy-source rates and
        # freezes the rest of the UI for the whole run.
        self._plot_dirty = False
        self._plot_timer = QTimer(self)
        self._plot_timer.setInterval(66)  # ~15 fps
        self._plot_timer.timeout.connect(self._flush_plot)

        self._build_ui()

    def set_store(self, store) -> None:
        self._store = store

    # -- UI ----------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)

        controls = QVBoxLayout()

        # A/B/C can each see what the *other two* have claimed (an instrument
        # can only usefully be driven/held by one of them at a time), via a
        # lazy per-axis lookup since the peers don't all exist yet while the
        # first one is constructed.
        self.axis_a = SweepAxisWidget(
            "Sweep A", self._registry, role_filter=_is_source, axis_label="A",
            usage_provider=lambda: self._claims_from("axis_b", "axis_c"),
        )
        self.axis_a.changed.connect(self._update_meter_label)
        self.axis_a.changed.connect(self._update_plot_extent)
        controls.addWidget(self.axis_a)

        self.enable_b = QCheckBox("Sweep B (2D map)")
        self.enable_b.stateChanged.connect(self._on_kind_changed)
        controls.addWidget(self.enable_b)

        self.axis_b = SweepAxisWidget(
            "Sweep B", self._registry, role_filter=_is_source, default_points=61, axis_label="B",
            usage_provider=lambda: self._claims_from("axis_a", "axis_c"),
        )
        self.axis_b.changed.connect(self._update_plot_extent)
        controls.addWidget(self.axis_b)

        self.axis_c = FixedValueWidget(
            "Sweep C (fixed)", self._registry, role_filter=_is_source, axis_label="C",
            usage_provider=lambda: self._claims_from("axis_a", "axis_b"),
        )
        controls.addWidget(self.axis_c)

        self._exclusive_groups = [self.axis_a, self.axis_b, self.axis_c]
        for group in self._exclusive_groups:
            group.changed.connect(self._reconcile_exclusive_groups)
        self._reconcile_exclusive_groups(winner=self.axis_a)  # resolve any overlap in the just-built defaults

        meter_form = QFormLayout()
        self.meter_combo = QComboBox()
        self.meter_combo.currentIndexChanged.connect(self._update_meter_label)
        meter_form.addRow("Meter", self.meter_combo)

        self.settle_ms = QSpinBox(); self.settle_ms.setRange(0, 5000); self.settle_ms.setValue(50)
        self.settle_ms.setSuffix(" ms")
        meter_form.addRow("Settle", self.settle_ms)

        self.label = QLineEdit(); self.label.setPlaceholderText("optional run label")
        meter_form.addRow("Label", self.label)
        self.tags = QLineEdit(); self.tags.setPlaceholderText("tags / project (comma-separated)")
        meter_form.addRow("Tags", self.tags)

        self.run_info = QLabel("no run yet")
        self.start_btn = QPushButton("Start"); self.start_btn.clicked.connect(self.start_run)
        self.stop_btn = QPushButton("Stop"); self.stop_btn.clicked.connect(self.stop_run)
        self.stop_btn.setEnabled(False)
        meter_form.addRow(self.start_btn, self.stop_btn)
        meter_form.addRow("Run", self.run_info)

        controls.addLayout(meter_form)
        controls.addStretch(1)

        controls_box = QWidget(); controls_box.setLayout(controls)
        controls_box.setMaximumWidth(420)

        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QSplitter

        self.plot1d = pg.PlotWidget()
        self.plot1d.setLabel("bottom", "set voltage", units="V")
        self.curve = self.plot1d.plot([], [], pen=pg.mkPen("#1f77b4", width=2))
        self.curve.setZValue(10)  # live/pinned cut always drawn over history traces

        # 2D option bar: dI/dV vs raw + colormap (shared widget builder)
        (self.img_opts, self.quantity, self.colormap,
         self.compensate, self.r_series) = plotting.make_image_2d_options()
        self.quantity.currentTextChanged.connect(self._recompute_levels_and_redraw)
        self.colormap.currentTextChanged.connect(self._redraw_image)
        self.compensate.toggled.connect(self._recompute_levels_and_redraw)
        self.r_series.valueChanged.connect(self._recompute_levels_and_redraw)
        # ImageView on a PlotItem so we get labelled axes
        self.image = pg.ImageView(view=pg.PlotItem())
        self.image.view.setLabel("bottom", "Sweep A")
        self.image.view.setLabel("left", "Sweep B")
        self.image.view.invertY(False)
        # Sweep A/B are independent physical quantities (e.g. gate vs bias
        # voltage), not pixel-square data, so a 1:1 aspect lock would fight
        # scaling each axis to its own configured extent.
        self.image.view.getViewBox().setAspectLocked(False)
        # clicking a row of the 2D map pins that row's cut into the line plot
        self.image.view.scene().sigMouseClicked.connect(self._on_scene_clicked)
        # keep the line plot's x-axis following the map's Sweep A axis. Not
        # pyqtgraph's setXLink: its internal lambda connections fire on
        # half-destroyed ViewBoxes during garbage collection and segfault; a
        # bound-method connection is auto-disconnected when this tab dies.
        self.image.view.getViewBox().sigXRangeChanged.connect(self._sync_cut_xrange)

        # two synchronized panes: line plot on top (live row / pinned cut during
        # a 2D run), 2D map below; a splitter lets the user rebalance them
        image_col = QVBoxLayout()
        image_col.setContentsMargins(0, 0, 0, 0)
        image_col.addWidget(self.img_opts)
        image_col.addWidget(self.image)
        image_box = QWidget(); image_box.setLayout(image_col)
        plot_box = QSplitter(Qt.Orientation.Horizontal)
        plot_box.addWidget(self.plot1d)
        plot_box.addWidget(image_box)
        plot_box.setStretchFactor(0, 1)
        plot_box.setStretchFactor(1, 1)
        plot_box.setSizes([420, 580])  # map pane a bit wider (it includes the histogram)

        root.addWidget(controls_box)
        root.addWidget(plot_box, stretch=1)
        self._refresh_meter_choices()
        self._on_kind_changed(self.enable_b.checkState().value)
        self._update_meter_label()
        self._update_plot_extent()
        self._apply_theme()

    def _apply_theme(self) -> None:
        apply_plot_theme(self.plot1d, self.image)
        for group in (self.axis_a, self.axis_b, self.axis_c):
            group.apply_tint()

    # -- Sweep A/B/C mutual exclusion --------------------------------------
    def _claims_from(self, *attr_names: str) -> dict:
        """Roles claimed by the named peer groups, tagged with that group's label.

        Used as each group's ``usage_provider``. Attribute access is guarded
        because this can be called while a peer group named here hasn't been
        constructed yet (each group populates its dropdowns, and therefore
        calls its own ``usage_provider``, as soon as it's built).
        """
        claims: dict = {}
        for name in attr_names:
            group = getattr(self, name, None)
            if group is None:
                continue
            claims.update({role: group._axis_label for role in group.selected_roles() if role})
        return claims

    def _reconcile_exclusive_groups(self, winner=None) -> None:
        """Re-check the *other* groups' dropdowns against whichever group just changed.

        Connected to each group's ``changed`` signal (``winner`` is filled in
        via :meth:`sender` there), so a pick in any one of Sweep A/B/C that
        collides with another is resolved immediately -- the group that just
        changed keeps its pick, any other group still holding the same role
        is bumped off it -- rather than only being caught at Start. The
        winner itself is never reconciled here (it would otherwise be bumped
        right back off the role it just claimed, before its peers have had a
        chance to react).
        """
        winner = winner or self.sender()
        for group in getattr(self, "_exclusive_groups", []):
            if group is not winner:
                group.refresh_instrument_choices(reconcile=True)

    def _update_plot_extent(self) -> None:
        """Live-scale the plot to Sweep A/B's configured extent as it's edited.

        Runs on every Sweep A/B change, not just at Start -- so the axes
        already show the range a run *will* cover before it's started. A
        degenerate range (start == stop, or fewer than 2 points) is left
        alone rather than applied, since that's a transient mid-edit state,
        not a real target range.
        """
        bounds_a = self.axis_a.bounds()
        if not bounds_a:
            return
        a_lo, a_hi = min(b[0] for b in bounds_a), max(b[1] for b in bounds_a)
        if a_lo == a_hi or self.axis_a.point_count() < 2:
            return

        if self.enable_b.isChecked():
            bounds_b = self.axis_b.bounds()
            if not bounds_b:
                return
            b_lo, b_hi = min(b[0] for b in bounds_b), max(b[1] for b in bounds_b)
            if b_lo == b_hi or self.axis_b.point_count() < 2:
                return
            self.image.view.setRange(xRange=(a_lo, a_hi), yRange=(b_lo, b_hi), padding=0)
        else:
            self.plot1d.setRange(xRange=(a_lo, a_hi), padding=0.05)

    def _on_registry_changed(self) -> None:
        self.axis_a.refresh_instrument_choices()
        self.axis_b.refresh_instrument_choices()
        self.axis_c.refresh_instrument_choices()
        self._refresh_meter_choices()
        self._update_meter_label()

    def _refresh_meter_choices(self) -> None:
        roles = [role for role, inst in self._registry.instruments.items() if _is_meter(role, inst)]
        current = self._selected_meter_role()
        self.meter_combo.blockSignals(True)
        self.meter_combo.clear()
        for role in roles:
            self.meter_combo.addItem(self._registry.instruments[role].get_name() or role, role)
        if current in roles:
            self.meter_combo.setCurrentIndex(roles.index(current))
        self.meter_combo.blockSignals(False)

    def _selected_meter_role(self) -> str:
        return self.meter_combo.currentData() or ""

    def _select_meter_role(self, role: str) -> None:
        for i in range(self.meter_combo.count()):
            if self.meter_combo.itemData(i) == role:
                self.meter_combo.setCurrentIndex(i)
                return

    def _update_meter_label(self) -> None:
        meter = self._registry.instruments.get(self._selected_meter_role())
        self.plot1d.setLabel("left", meter.get_name() if meter is not None else "meter")

    def _on_kind_changed(self, _state) -> None:
        is_2d = self.enable_b.isChecked()
        self.axis_b.setEnabled(is_2d)
        self.image.setVisible(is_2d)
        self.img_opts.setVisible(is_2d)
        if not is_2d:
            self.plot1d.setTitle(None)
        self._update_plot_extent()

    # -- config snapshot -----------------------------------------------------
    def to_snapshot(self) -> dict:
        """Serializable form of the current sweep setup, for autosave/history."""
        return {
            "axis_a": {"roles": self.axis_a.selected_roles(), "bounds": self.axis_a.bounds(),
                       "points": self.axis_a.point_count()},
            "axis_b": {"roles": self.axis_b.selected_roles(), "bounds": self.axis_b.bounds(),
                       "points": self.axis_b.point_count()},
            "axis_c": {"roles": self.axis_c.selected_roles(), "values": self.axis_c.values()},
            "enable_b": self.enable_b.isChecked(),
            "meter": self._selected_meter_role(),
            "settle_ms": self.settle_ms.value(),
            "label": self.label.text(),
            "tags": self.tags.text(),
        }

    def load_snapshot(self, measure: dict) -> None:
        """Restore sweep setup from :meth:`to_snapshot`'s output.

        Instruments must already be loaded into the registry (so the axis/
        meter dropdowns have the right choices) before calling this.
        """
        a = measure.get("axis_a", {})
        b = measure.get("axis_b", {})
        c = measure.get("axis_c", {})
        self.axis_a.load_rows(a.get("roles", []), [tuple(v) for v in a.get("bounds", [])], a.get("points", 61))
        self.axis_b.load_rows(b.get("roles", []), [tuple(v) for v in b.get("bounds", [])], b.get("points", 61))
        self.axis_c.load_rows(c.get("roles", []), c.get("values", []))
        self.enable_b.setChecked(measure.get("enable_b", False))
        self._select_meter_role(measure.get("meter", ""))
        self.settle_ms.setValue(measure.get("settle_ms", 50))
        self.label.setText(measure.get("label", ""))
        self.tags.setText(measure.get("tags", ""))

    # -- run lifecycle -----------------------------------------------------
    def start_run(self) -> None:
        if self._thread is not None:
            return
        is_2d = self.enable_b.isChecked()
        insts = self._registry.instruments

        a_roles = self.axis_a.selected_roles()
        b_roles = self.axis_b.selected_roles() if is_2d else []
        meter_role = self._selected_meter_role()
        missing_axis = not a_roles or any(not r for r in a_roles) or (is_2d and (not b_roles or any(not r for r in b_roles)))
        if missing_axis or not meter_role:
            QMessageBox.warning(self, "Missing instruments",
                                 "Pick an instrument for every sweep row and the meter "
                                 "(add instruments in the Instruments tab if the lists are empty).")
            return

        sources_a = [insts[r] for r in a_roles]
        meter = insts[meter_role]
        self._meter_name = meter.get_name()
        if self.r_series.value() == 0.0:
            # prefill from the bias source's configured line resistance; a
            # value the user already typed (extra circuit resistance) wins
            self.r_series.setValue(getattr(sources_a[0], "series_resistance", 0.0))
        settle = self.settle_ms.value() / 1000.0  # ms -> s
        self._update_meter_label()

        c_roles = self.axis_c.selected_roles()
        c_values = self.axis_c.values()
        sources_c = [insts[r] for r in c_roles]
        fixed = dict(zip(sources_c, c_values))
        fixed_instruments = {f"c{i}": s for i, s in enumerate(sources_c)}
        fixed_params = {"instruments": c_roles, "values": c_values}

        if is_2d:
            sources_b = [insts[r] for r in b_roles]
            bounds_a = self.axis_a.bounds()
            bounds_b = self.axis_b.bounds()
            points_a = self.axis_a.point_count()
            points_b = self.axis_b.point_count()
            params = {
                "sweep_a": {"instruments": a_roles, "bounds": bounds_a, "points": points_a},
                "sweep_b": {"instruments": b_roles, "bounds": bounds_b, "points": points_b},
                "sweep_c": fixed_params,
            }
            gen = iter_map_2d_group(sources_a, bounds_a, points_a, sources_b, bounds_b, points_b, meter,
                                     settle=settle, fixed=fixed)
            instruments = {f"a{i}": s for i, s in enumerate(sources_a)}
            instruments.update({f"b{i}": s for i, s in enumerate(sources_b)})
            instruments.update(fixed_instruments)
            instruments["meter"] = meter
            self._grid = np.full((points_b, points_a), np.nan)
            self._current_iy = 0
            self._cut_row = None  # new run -> back to following the live row
            self._levels = None  # new run -> recompute once data streams in, not stale
            self._clear_history()
            self._bias_span = abs(bounds_a[0][1] - bounds_a[0][0]) if bounds_a else 1.0
            # data-coordinate extent so the image lines up with the voltage axes
            self._extent = (min(b[0] for b in bounds_a), max(b[1] for b in bounds_a),
                            min(b[0] for b in bounds_b), max(b[1] for b in bounds_b))
            self.image.view.setLabel("bottom", ", ".join(a_roles))
            self.image.view.setLabel("left", ", ".join(b_roles))
            self._redraw_image()
            kind = "2d"
        else:
            bounds_a = self.axis_a.bounds()
            points_a = self.axis_a.point_count()
            params = {"sweep_a": {"instruments": a_roles, "bounds": bounds_a, "points": points_a},
                      "sweep_c": fixed_params}
            gen = iter_linear_sweep_group(sources_a, bounds_a, meter, points_a, settle=settle, fixed=fixed)
            instruments = {f"a{i}": s for i, s in enumerate(sources_a)}
            instruments.update(fixed_instruments)
            instruments["meter"] = meter
            self._x, self._y = [], []
            self.curve.setData([], [])
            self._clear_history()  # drop any traces left from a previous 2D run
            self._plot_x_name = sources_a[0].get_name()
            self.plot1d.setLabel("bottom", self._plot_x_name)
            kind = "1d"

        self._run = self._store.new_run(
            kind, self.label.text() or None, params=params,
            instruments=instruments, tags=self.tags.text(),
        )
        self.run_info.setText(f"run #{self._run.run_number}: {self._run.label}")

        self._worker = MeasurementWorker(gen)
        self._thread = QThread()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.point.connect(self._on_point)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._thread.start()
        self._plot_dirty = False
        self._plot_timer.start()

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def stop_run(self) -> None:
        if self._worker is not None:
            self._worker.stop()

    def _on_point(self, point: dict) -> None:
        if self._run is not None:
            self._run.append(point)
        meter_name = self._meter_name
        if self.enable_b.isChecked():
            self._grid[point["iy"], point["ix"]] = point[meter_name]
            self._current_iy = point["iy"]
        else:
            self._x.append(point[self._plot_x_name])
            self._y.append(point[meter_name])
        self._plot_dirty = True

    def _flush_plot(self) -> None:
        """Repaint from the streamed data if anything arrived since last time."""
        if not self._plot_dirty:
            return
        self._plot_dirty = False
        if self.enable_b.isChecked():
            self._redraw_image()
        else:
            self.curve.setData(self._x, self._y)

    def _compute_grid(self) -> tuple[np.ndarray, bool]:
        """Current display grid (raw I or dI/dV, R_s-compensated if enabled)."""
        raw = self._grid
        extent = getattr(self, "_extent", None)
        compensated = self.compensate.isChecked() and self.r_series.value() > 0.0
        if compensated and extent is not None:
            # bias axis becomes the voltage actually across the device
            raw = plotting.compensate_series_resistance(
                raw, extent[0], extent[1], self.r_series.value())
        quantity = self.quantity.currentText()
        span = getattr(self, "_bias_span", 1.0)
        if quantity == "dI/dV":
            grid = plotting.differentiate_bias(raw, bias_axis=span)
        else:
            grid = raw
        return grid, compensated

    def _recompute_levels_and_redraw(self) -> None:
        """Refresh the color-scale levels, then redraw.

        Only called from user-initiated changes (quantity/compensation) and at
        run completion -- *not* every streaming tick, so the color scale
        doesn't jitter/rescale while a run is still filling in.
        """
        if self._grid is None:
            return
        grid, _ = self._compute_grid()
        self._levels = (plotting.didv_levels(grid) if self.quantity.currentText() == "dI/dV"
                        else plotting.image_levels(grid))
        self._redraw_image()

    def _redraw_image(self) -> None:
        """Render the [B, A] grid as raw I or dI/dV with the chosen map."""
        if self._grid is None:
            return
        grid, compensated = self._compute_grid()
        quantity = self.quantity.currentText()
        levels = getattr(self, "_levels", None)
        if levels is None:
            levels = (plotting.didv_levels(grid) if quantity == "dI/dV"
                     else plotting.image_levels(grid))
            self._levels = levels
        self.image.view.setTitle("bias axis: V_QD = V − I·R_s" if compensated else None)
        plotting.set_image(self.image, grid, transpose=False,
                           colormap=self.colormap.currentText(),
                           levels=levels, extent=getattr(self, "_extent", None))
        self._display_grid = grid
        # switching dI/dV <-> raw or (un)compensating changes what every trace
        # means: rebuild the history rather than mixing meanings on one plot
        history_key = (quantity, compensated, self.r_series.value() if compensated else 0.0)
        if getattr(self, "_history_key", None) != history_key:
            self._history_key = history_key
            self._clear_history()
        self._update_history()
        self._update_cut()

    def _clear_history(self) -> None:
        for curve in self._history_curves:
            self.plot1d.removeItem(curve)
        self._history_curves.clear()
        self._completed_upto = 0

    def _update_history(self) -> None:
        """Keep each completed row as a trace, colored by its Sweep B position.

        Capped at :data:`plotting.MAX_HISTORY_TRACES` (oldest dropped) so a
        tall map can't overload the line plot.
        """
        grid = self._display_grid
        extent = getattr(self, "_extent", None)
        if grid is None or extent is None:
            return
        completed = min(self._current_iy, grid.shape[0])
        for iy in range(self._completed_upto, completed):
            x, values, _ = plotting.row_cut(grid, extent, iy)
            fraction = iy / max(grid.shape[0] - 1, 1)
            pen = pg.mkPen(plotting.progression_color(fraction), width=1)
            self._history_curves.append(self.plot1d.plot(x, values, pen=pen))
            while len(self._history_curves) > plotting.MAX_HISTORY_TRACES:
                self.plot1d.removeItem(self._history_curves.pop(0))
        self._completed_upto = completed

    def _update_cut(self) -> None:
        """Line plot <- one row of the 2D map: pinned by click, else the live row."""
        grid = self._display_grid
        extent = getattr(self, "_extent", None)
        if grid is None or extent is None:
            return
        iy = self._cut_row if self._cut_row is not None else self._current_iy
        x, values, y_value = plotting.row_cut(grid, extent, iy)
        self.curve.setData(x, values)
        pinned = " (pinned)" if self._cut_row is not None else ""
        self.plot1d.setTitle(f"cut @ Sweep B = {y_value:.4g}{pinned}")

    def _sync_cut_xrange(self, _viewbox, xrange) -> None:
        if self.enable_b.isChecked():
            self.plot1d.setXRange(*xrange, padding=0)

    def _on_scene_clicked(self, event) -> None:
        coords = plotting.image_click_coords(self.image, event)
        if coords is not None:
            self._on_image_clicked(*coords)

    def _on_image_clicked(self, _x: float, y: float) -> None:
        if not self.enable_b.isChecked() or self._display_grid is None:
            return
        extent = getattr(self, "_extent", None)
        if extent is None:
            return
        self._cut_row = plotting.row_index_at(extent, self._display_grid.shape[0], y)
        self._update_cut()

    def _on_finished(self, summary: dict) -> None:
        number = self._run.run_number if self._run is not None else -1
        if self._run is not None:
            self._run.close()
        self._teardown_thread()
        status = "cancelled" if summary.get("cancelled") else "done"
        self.run_info.setText(self.run_info.text() + f" — {status} ({summary['count']} pts)")
        if number > 0:
            self.runFinished.emit(number)

    def _on_error(self, message: str) -> None:
        if self._run is not None:
            self._run.close()
        self._teardown_thread()
        self.run_info.setText(f"error: {message}")

    def _teardown_thread(self) -> None:
        self._plot_timer.stop()
        if self.enable_b.isChecked() and self._grid is not None:
            # final redraw: levels reflect the complete grid, not whatever
            # partial data they were last computed from mid-stream
            self._recompute_levels_and_redraw()
        self._flush_plot()  # paint whatever streamed since the last tick
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self._run = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
