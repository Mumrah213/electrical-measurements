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
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from emeas.gui import plotting

_COLUMNS = ["#", "label", "kind", "created", "tags", "points"]


class BrowserTab(QWidget):
    def __init__(self, store):
        super().__init__()
        self._store = store
        self._summaries: list[dict] = []
        self._current: dict | None = None  # full read_run() of the selected run
        self._build_ui()
        self.refresh()

    def set_store(self, store) -> None:
        self._store = store
        self._current = None

    # -- UI ----------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)

        # left: filter + table
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

        # center: plot + 1D options
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
        self.img_opts, self.quantity, self.colormap = plotting.make_image_2d_options()
        self.quantity.currentTextChanged.connect(self._replot)
        self.colormap.currentTextChanged.connect(self._replot)

        self.plot1d = pg.PlotWidget()
        self.image = pg.ImageView(view=pg.PlotItem())
        self.image.view.setLabel("bottom", "gate")
        self.image.view.setLabel("left", "source-drain bias")
        self.image.view.invertY(False)
        center.addWidget(self.opts_bar)
        center.addWidget(self.trace_box)
        center.addWidget(self.img_opts)
        center.addWidget(self.plot1d, stretch=1)
        center.addWidget(self.image, stretch=1)
        center_box = QWidget(); center_box.setLayout(center)

        # right: detail + actions
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

        root.addWidget(left_box)
        root.addWidget(center_box, stretch=1)
        root.addWidget(right_box)

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
        self.plot1d.setVisible(not is_2d)
        self.opts_bar.setVisible(not is_2d)
        self.trace_box.setVisible(not is_2d)
        self.img_opts.setVisible(is_2d)
        self.image.setVisible(is_2d)
        if is_2d:
            self._replot_2d()
        else:
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
        nx = int(params["x"][2]) if "x" in params else int(np.max(data["ix"]) + 1)
        ny = int(params["y"][2]) if "y" in params else int(np.max(data["iy"]) + 1)
        # bias span from params (inner/x sweep = bias) for dI/dV scaling
        bias_span = abs(params["x"][1] - params["x"][0]) if "x" in params else 1.0
        quantity = self.quantity.currentText()
        # grid is [gate, bias]; displayed without transpose -> gate on x, bias on y
        grid = plotting.diamond_grid(data, value_name, nx, ny,
                                     quantity=quantity, bias_span=bias_span)
        plotting.set_image(self.image, grid, transpose=False,
                           colormap=self.colormap.currentText(),
                           diverging=(quantity == "dI/dV"))

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
