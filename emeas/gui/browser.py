"""Saved-run browser tab.

Lists runs from an :class:`~emeas.storage.H5Store` in a sortable, filterable
table; replots a selected run (1D line / 2D image) using the same helpers as the
live view (:mod:`emeas.gui.plotting`); shows the full instrument-settings
snapshot; and supports rename, tag editing, and CSV export.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyqtgraph as pg
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from emeas.gui import plotting
from emeas.gui.theme import apply_plot_theme

_COLUMNS = ["#", "label", "kind", "created", "tags", "points"]


class BrowserTab(QWidget):
    def __init__(self, store, theme_watcher=None):
        super().__init__()
        self._store = store
        self._summaries: list[dict] = []
        self._current: dict | None = None  # full read_run() of the selected run
        self._cut_row: int | None = None   # pinned cut row for 2D runs
        self._cut_curves: list = []        # accumulated clicked cuts (capped)
        self._build_ui()
        self.refresh()
        if theme_watcher is not None:
            theme_watcher.changed.connect(self._apply_theme)

    def set_store(self, store) -> None:
        self._store = store
        self._current = None

    # -- UI ----------------------------------------------------------------
    def _build_ui(self) -> None:
        # plots on top (full width -- they're the two side-by-side panes and
        # want the horizontal room); run list + details as a strip below
        root = QVBoxLayout(self)

        # bottom-left: filter + table
        left = QVBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("filter by label / kind / tags…")
        self.filter.textChanged.connect(self._apply_filter)
        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table.itemSelectionChanged.connect(self._load_selected)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        left.addWidget(self.filter)
        left.addWidget(self.table, stretch=1)
        left.addWidget(refresh_btn)
        left_box = QWidget(); left_box.setLayout(left); left_box.setMaximumWidth(420)
        left_box.setMinimumHeight(180)

        # top: plot + 1D options
        center = QVBoxLayout()
        opts = QHBoxLayout()
        opts.addWidget(QLabel("x:"))
        self.xcombo = QComboBox(); self.xcombo.currentTextChanged.connect(self._replot)
        opts.addWidget(self.xcombo)
        self.smooth = QCheckBox("rolling avg"); self.smooth.stateChanged.connect(self._replot)
        opts.addWidget(self.smooth)
        self.window = QSpinBox(); self.window.setRange(2, 999); self.window.setValue(5)
        self.window.valueChanged.connect(self._replot)
        opts.addWidget(self.window)
        opts.addStretch(1)
        self.opts_bar = QWidget(); self.opts_bar.setLayout(opts)

        # per-column trace toggles live in their own row
        self.trace_row = QHBoxLayout()
        self.trace_row.addWidget(QLabel("traces:"))
        self._trace_checks: dict[str, QCheckBox] = {}
        self.trace_box = QWidget(); self.trace_box.setLayout(self.trace_row)

        # 2D option bar: dI/dV vs raw + colormap (shared builder)
        (self.img_opts, self.quantity, self.colormap,
         self.compensate, self.r_series) = plotting.make_image_2d_options()
        self.quantity.currentTextChanged.connect(self._replot)
        self.colormap.currentTextChanged.connect(self._replot)
        self.compensate.toggled.connect(self._replot)
        self.r_series.valueChanged.connect(self._replot)

        self.plot1d = pg.PlotWidget()
        self.image = pg.ImageView(view=pg.PlotItem())
        self.image.view.setLabel("bottom", "Sweep A")
        self.image.view.setLabel("left", "Sweep B")
        self.image.view.invertY(False)
        # Sweep A/B are independent physical quantities; a 1:1 aspect lock
        # would fight ranging each axis to its own sweep extent
        self.image.view.getViewBox().setAspectLocked(False)
        # keep the cut plot's x-axis following the map's (not setXLink: its
        # internal lambdas segfault on half-destroyed ViewBoxes during GC)
        self.image.view.getViewBox().sigXRangeChanged.connect(self._sync_cut_xrange)
        # clicking a row of a 2D map pins that row's cut into the line plot
        self.image.view.scene().sigMouseClicked.connect(self._on_scene_clicked)

        center.addWidget(self.opts_bar)
        center.addWidget(self.trace_box)
        center.addWidget(self.img_opts)
        # two synchronized panes for 2D runs: cuts left, map right
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.plot1d)
        splitter.addWidget(self.image)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([300, 400])  # map pane a bit wider (it includes the histogram)
        center.addWidget(splitter, stretch=1)
        center_box = QWidget(); center_box.setLayout(center)

        # bottom-right: detail + actions
        right = QVBoxLayout()
        self.detail = QTextEdit(); self.detail.setReadOnly(True)
        self.rename_btn = QPushButton("Rename…"); self.rename_btn.clicked.connect(self._rename)
        self.tags_btn = QPushButton("Edit tags…"); self.tags_btn.clicked.connect(self._edit_tags)
        self.export_btn = QPushButton("Export CSV…"); self.export_btn.clicked.connect(self._export_csv)
        for b in (self.rename_btn, self.tags_btn, self.export_btn):
            b.setEnabled(False)
        right.addWidget(QLabel("Run details"))
        right.addWidget(self.detail, stretch=1)
        right.addWidget(self.rename_btn)
        right.addWidget(self.tags_btn)
        right.addWidget(self.export_btn)
        right_box = QWidget(); right_box.setLayout(right); right_box.setMaximumWidth(340)
        right_box.setMinimumHeight(180)

        bottom = QHBoxLayout()
        bottom.addWidget(left_box)
        bottom.addWidget(right_box)
        bottom_box = QWidget(); bottom_box.setLayout(bottom)

        root.addWidget(center_box, stretch=1)
        root.addWidget(bottom_box)
        self._apply_theme()

    def _apply_theme(self) -> None:
        apply_plot_theme(self.plot1d, self.image)

    # -- table population --------------------------------------------------
    def refresh(self) -> None:
        """Reload the run list from the store, preserving the filter."""
        self._summaries = self._store.list_runs()
        self._apply_filter()

    def _apply_filter(self) -> None:
        text = self.filter.text().strip().lower()

        def matches(s: dict) -> bool:
            if not text:
                return True
            hay = f"{s['label']} {s['kind']} {s.get('tags', '')}".lower()
            return text in hay

        rows = [s for s in self._summaries if matches(s)]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for r, s in enumerate(rows):
            values = [s["run_number"], s["label"], s["kind"], s["created_iso"],
                      s.get("tags", ""), s.get("points", 0)]
            for c, val in enumerate(values):
                item = QTableWidgetItem()
                # numeric columns sort numerically
                if c in (0, 5):
                    item.setData(Qt.ItemDataRole.DisplayRole, int(val))
                else:
                    item.setText(str(val))
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, int(s["run_number"]))
                self.table.setItem(r, c, item)
        self.table.setSortingEnabled(True)

    def _selected_run_number(self) -> int | None:
        items = self.table.selectedItems()
        if not items:
            return None
        row = items[0].row()
        cell = self.table.item(row, 0)
        return None if cell is None else int(cell.data(Qt.ItemDataRole.UserRole))

    # -- load + plot -------------------------------------------------------
    def _load_selected(self) -> None:
        n = self._selected_run_number()
        if n is None:
            return
        self._current = self._store.read_run(n)
        self._cut_row = None  # new run -> back to the default middle cut
        # prefill R_s from the run's recorded bias-source setting (a0); the
        # field stays editable for anything extra that was in the circuit
        a0 = self._current.get("settings", {}).get("a0", {})
        self.r_series.blockSignals(True)
        self.r_series.setValue(float(a0.get("series_resistance", 0.0)))
        self.r_series.blockSignals(False)
        self._populate_detail()
        self._rebuild_1d_options()
        self._replot()
        for b in (self.rename_btn, self.tags_btn, self.export_btn):
            b.setEnabled(True)

    def _numeric_columns(self) -> list[str]:
        data = self._current["data"]
        # index columns are positioning hints, not plottable signals
        return [k for k in data if k not in ("ix", "iy")]

    def _rebuild_1d_options(self) -> None:
        cols = self._numeric_columns()
        # x-axis options
        self.xcombo.blockSignals(True)
        self.xcombo.clear()
        self.xcombo.addItems(cols)
        # default x: set_voltage if present, else first column
        default_x = "set_voltage" if "set_voltage" in cols else (cols[0] if cols else "")
        if default_x:
            self.xcombo.setCurrentText(default_x)
        self.xcombo.blockSignals(False)
        # trace checkboxes (one per non-x column)
        for name, cb in list(self._trace_checks.items()):
            self.trace_row.removeWidget(cb); cb.deleteLater()
        self._trace_checks.clear()
        for name in cols:
            if name == self.xcombo.currentText():
                continue
            cb = QCheckBox(name); cb.setChecked(True)
            cb.stateChanged.connect(self._replot)
            self.trace_row.addWidget(cb)
            self._trace_checks[name] = cb

    def _replot(self) -> None:
        if self._current is None:
            return
        is_2d = self._current["kind"] == "2d"
        # the line plot stays up for 2D runs too: it shows a row cut of the map
        self.opts_bar.setVisible(not is_2d)
        self.trace_box.setVisible(not is_2d)
        self.img_opts.setVisible(is_2d)
        self.image.setVisible(is_2d)
        if is_2d:
            self._replot_2d()
        else:
            self.plot1d.setTitle(None)
            self._cut_curves.clear()  # plot_1d clears the widget; drop stale refs
            self._replot_1d()

    def _replot_1d(self) -> None:
        data = self._current["data"]
        x_name = self.xcombo.currentText()
        if not x_name or x_name not in data:
            return
        x = np.asarray(data[x_name], dtype="f8")
        series = {
            name: np.asarray(data[name], dtype="f8")
            for name, cb in self._trace_checks.items()
            if cb.isChecked()
        }
        window = self.window.value() if self.smooth.isChecked() else 1
        plotting.plot_1d(self.plot1d, x, series, smooth_window=window)
        self.plot1d.setLabel("bottom", x_name)

    def _replot_2d(self) -> None:
        data = self._current["data"]
        params = self._current.get("params", {})
        value_name = self._meter_column()
        def axis_info(key, legacy):
            """(lo, hi, n) for a sweep axis from either params format, or None."""
            sweep = params.get(key)
            if sweep and sweep.get("bounds"):
                bounds = sweep["bounds"]
                return (min(b[0] for b in bounds), max(b[1] for b in bounds), int(sweep["points"]))
            if legacy in params:
                start, stop, n = params[legacy]
                return (float(start), float(stop), int(n))
            return None

        info_a = axis_info("sweep_a", "x")
        info_b = axis_info("sweep_b", "y")
        nx = info_a[2] if info_a else int(np.max(data["ix"]) + 1)
        ny = info_b[2] if info_b else int(np.max(data["iy"]) + 1)
        # bias span from params (inner/A sweep = bias) for dI/dV scaling
        bias_span = abs(info_a[1] - info_a[0]) if info_a else 1.0
        extent = (info_a[0], info_a[1], info_b[0], info_b[1]) if (info_a and info_b) else None
        quantity = self.quantity.currentText()
        # grid is [gate, bias]; displayed without transpose -> gate on x, bias on y
        raw = plotting.grid_from_long(data["ix"], data["iy"], data[value_name], nx, ny)
        compensated = self.compensate.isChecked() and self.r_series.value() > 0.0
        if compensated and extent is not None:
            raw = plotting.compensate_series_resistance(
                raw, extent[0], extent[1], self.r_series.value())
        grid = plotting.differentiate_bias(raw, bias_axis=bias_span) if quantity == "dI/dV" else raw
        levels = plotting.didv_levels(grid) if quantity == "dI/dV" else plotting.image_levels(grid)
        self.image.view.setTitle("bias axis: V_QD = V − I·R_s" if compensated else None)
        plotting.set_image(self.image, grid, transpose=False,
                           colormap=self.colormap.currentText(), levels=levels, extent=extent)
        if extent is not None:
            self.image.view.setRange(xRange=extent[:2], yRange=extent[2:], padding=0)
        # label axes with the swept instruments when the run recorded them
        a_names = params.get("sweep_a", {}).get("instruments")
        b_names = params.get("sweep_b", {}).get("instruments")
        self.image.view.setLabel("bottom", ", ".join(a_names) if a_names else "Sweep A")
        self.image.view.setLabel("left", ", ".join(b_names) if b_names else "Sweep B")
        self._grid2d = grid
        self._extent2d = extent
        self._update_cut()

    def _update_cut(self) -> None:
        """Reset the cut plot to a single row (clicked row, default: middle).

        Called whenever the displayed grid is rebuilt (run/quantity/colormap
        change) -- accumulated cuts from the old grid wouldn't match it.
        """
        grid = getattr(self, "_grid2d", None)
        extent = getattr(self, "_extent2d", None)
        if grid is None or extent is None:
            return
        self.plot1d.clear()
        self._cut_curves.clear()
        self._add_cut(self._cut_row if self._cut_row is not None else grid.shape[0] // 2)

    def _add_cut(self, iy: int) -> None:
        """Overlay one more row cut, colored by its Sweep B position (capped)."""
        grid = getattr(self, "_grid2d", None)
        extent = getattr(self, "_extent2d", None)
        if grid is None or extent is None:
            return
        x, values, y_value = plotting.row_cut(grid, extent, iy)
        fraction = iy / max(grid.shape[0] - 1, 1)
        pen = pg.mkPen(plotting.progression_color(fraction), width=2)
        self._cut_curves.append(self.plot1d.plot(x, values, pen=pen))
        while len(self._cut_curves) > plotting.MAX_HISTORY_TRACES:
            self.plot1d.removeItem(self._cut_curves.pop(0))
        self.plot1d.setTitle(f"cut @ Sweep B = {y_value:.4g}")

    def _sync_cut_xrange(self, _viewbox, xrange) -> None:
        if self._current is not None and self._current.get("kind") == "2d":
            self.plot1d.setXRange(*xrange, padding=0)

    def _on_scene_clicked(self, event) -> None:
        coords = plotting.image_click_coords(self.image, event)
        if coords is not None:
            self._on_image_clicked(*coords)

    def _on_image_clicked(self, _x: float, y: float) -> None:
        if self._current is None or self._current.get("kind") != "2d":
            return
        grid = getattr(self, "_grid2d", None)
        extent = getattr(self, "_extent2d", None)
        if grid is None or extent is None:
            return
        self._cut_row = plotting.row_index_at(extent, grid.shape[0], y)
        self._add_cut(self._cut_row)  # clicks accumulate; grid changes reset

    def _meter_column(self) -> str:
        """Name of the measured-value column (the meter), via settings if known."""
        data = self._current["data"]
        settings = self._current.get("settings", {})
        meter_name = settings.get("meter", {}).get("name")
        if meter_name and meter_name in data:
            return meter_name
        # fall back: last non-index column
        cols = [k for k in data if k not in ("ix", "iy")]
        return cols[-1]

    # -- detail panel ------------------------------------------------------
    def _populate_detail(self) -> None:
        c = self._current
        lines = [
            f"run #{c['run_number']}  [{c['kind']}]",
            f"label: {c['label']}",
            f"tags:  {c.get('tags', '')}",
            f"created: {c['created_iso']}",
            f"params: {c['params']}",
        ]
        if c.get("notes"):
            lines.append(f"notes: {c['notes']}")
        lines.append("")
        lines.append("settings:")
        for role, s in c["settings"].items():
            lines.append(f"  [{role}]")
            for k, v in s.items():
                lines.append(f"    {k}: {v}")
        self.detail.setPlainText("\n".join(lines))

    # -- actions -----------------------------------------------------------
    def _rename(self) -> None:
        if self._current is None:
            return
        text, ok = QInputDialog.getText(self, "Rename run", "New label:", text=self._current["label"])
        if ok and text:
            self._store.set_label(self._current["run_number"], text)
            self.refresh()

    def _edit_tags(self) -> None:
        if self._current is None:
            return
        text, ok = QInputDialog.getText(self, "Edit tags", "Tags:", text=self._current.get("tags", ""))
        if ok:
            self._store.set_tags(self._current["run_number"], text)
            self.refresh()

    def _export_csv(self) -> None:
        if self._current is None:
            return
        default = f"run_{self._current['run_number']:05d}.csv"
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", default, "CSV (*.csv)")
        if not path:
            return
        self.export_run_csv(self._current, path)

    @staticmethod
    def export_run_csv(run: dict, path: str) -> None:
        """Write a run's data columns to ``path`` as CSV (also used in tests)."""
        df = pd.DataFrame({k: np.asarray(v) for k, v in run["data"].items()})
        df.to_csv(path, index=False)
