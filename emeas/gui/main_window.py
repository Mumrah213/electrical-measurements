"""Application shell: a tabbed window with a live **Measure** tab and a
saved-run **Browse** tab.

``MeasureTab`` runs a measurement and streams it into a plot + the HDF5 store
(via a :class:`~emeas.gui.worker.MeasurementWorker` on a ``QThread``).
``BrowserTab`` (in :mod:`emeas.gui.browser`) reopens and replots saved runs from
the same store. When a run finishes, the window refreshes the browser so new
data shows up immediately.

v1 uses preconfigured dummy instruments; swapping to real GPIB later is a
transport change in :func:`emeas.gui.app.build_instruments`, not here.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from emeas.gui import plotting
from emeas.gui.browser import BrowserTab
from emeas.gui.worker import MeasurementWorker
from emeas.measure import iter_linear_sweep, iter_map_2d


class MeasureTab(QWidget):
    """Live measurement view: controls + plot, streaming to plot and store."""

    #: emitted (run_number) when a run finishes, so the browser can refresh
    runFinished = pyqtSignal(int)

    def __init__(self, instruments: dict, store):
        super().__init__()
        self._inst = instruments  # {"source", "gate", "meter"}
        self._store = store

        self._thread: QThread | None = None
        self._worker: MeasurementWorker | None = None
        self._run = None  # RunWriter for the active run
        self._x: list[float] = []
        self._y: list[float] = []
        self._grid: np.ndarray | None = None

        self._build_ui()

    def set_store(self, store) -> None:
        self._store = store

    # -- UI ----------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)

        controls = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItems(["1D sweep", "2D map"])
        self.kind.currentTextChanged.connect(self._on_kind_changed)

        self.start = QDoubleSpinBox(); self.start.setRange(-100, 100); self.start.setSingleStep(0.1); self.start.setValue(-0.5)
        self.stop = QDoubleSpinBox(); self.stop.setRange(-100, 100); self.stop.setSingleStep(0.1); self.stop.setValue(0.5)
        self.points = QSpinBox(); self.points.setRange(2, 100000); self.points.setValue(61)
        self.ystart = QDoubleSpinBox(); self.ystart.setRange(-100, 100); self.ystart.setSingleStep(0.1); self.ystart.setValue(-0.6)
        self.ystop = QDoubleSpinBox(); self.ystop.setRange(-100, 100); self.ystop.setSingleStep(0.1); self.ystop.setValue(0.6)
        self.ypoints = QSpinBox(); self.ypoints.setRange(2, 100000); self.ypoints.setValue(61)
        self.settle_ms = QSpinBox(); self.settle_ms.setRange(0, 5000); self.settle_ms.setValue(50)
        self.settle_ms.setSuffix(" ms")
        self.label = QLineEdit(); self.label.setPlaceholderText("optional run label")
        self.tags = QLineEdit(); self.tags.setPlaceholderText("tags / project (comma-separated)")

        self.run_info = QLabel("no run yet")
        self.start_btn = QPushButton("Start"); self.start_btn.clicked.connect(self.start_run)
        self.stop_btn = QPushButton("Stop"); self.stop_btn.clicked.connect(self.stop_run)
        self.stop_btn.setEnabled(False)

        controls.addRow("Measurement", self.kind)
        controls.addRow("X start", self.start)
        controls.addRow("X stop", self.stop)
        controls.addRow("X points", self.points)
        controls.addRow("Y start", self.ystart)
        controls.addRow("Y stop", self.ystop)
        controls.addRow("Y points", self.ypoints)
        controls.addRow("Settle", self.settle_ms)
        controls.addRow("Label", self.label)
        controls.addRow("Tags", self.tags)
        controls.addRow(self.start_btn, self.stop_btn)
        controls.addRow("Run", self.run_info)

        controls_box = QWidget(); controls_box.setLayout(controls)
        controls_box.setMaximumWidth(320)

        plot_col = QVBoxLayout()
        self.plot1d = pg.PlotWidget()
        self.plot1d.setLabel("bottom", "set voltage", units="V")
        self.plot1d.setLabel("left", self._inst["meter"].get_name())
        self.curve = self.plot1d.plot([], [], pen=pg.mkPen(width=2))

        # 2D option bar: dI/dV vs raw + colormap (shared widget builder)
        self.img_opts, self.quantity, self.colormap = plotting.make_image_2d_options()
        self.quantity.currentTextChanged.connect(self._redraw_image)
        self.colormap.currentTextChanged.connect(self._redraw_image)
        # ImageView on a PlotItem so we get labelled axes; gate on x, bias on y
        self.image = pg.ImageView(view=pg.PlotItem())
        self.image.view.setLabel("bottom", "gate")
        self.image.view.setLabel("left", "source-drain bias")
        self.image.view.invertY(False)

        plot_col.addWidget(self.plot1d)
        plot_col.addWidget(self.img_opts)
        plot_col.addWidget(self.image)
        plot_box = QWidget(); plot_box.setLayout(plot_col)

        root.addWidget(controls_box)
        root.addWidget(plot_box, stretch=1)
        self._on_kind_changed(self.kind.currentText())

    def _on_kind_changed(self, text: str) -> None:
        is_2d = text == "2D map"
        self.image.setVisible(is_2d)
        self.img_opts.setVisible(is_2d)
        self.plot1d.setVisible(not is_2d)
        for w in (self.ystart, self.ystop, self.ypoints):
            w.setEnabled(is_2d)

    # -- run lifecycle -----------------------------------------------------
    def start_run(self) -> None:
        if self._thread is not None:
            return
        is_2d = self.kind.currentText() == "2D map"
        source = self._inst["source"]
        meter = self._inst["meter"]
        settle = self.settle_ms.value() / 1000.0  # ms -> s

        if is_2d:
            gate = self._inst["gate"]
            x_vals = np.linspace(self.start.value(), self.stop.value(), self.points.value())
            y_vals = np.linspace(self.ystart.value(), self.ystop.value(), self.ypoints.value())
            params = {
                "x": [self.start.value(), self.stop.value(), self.points.value()],
                "y": [self.ystart.value(), self.ystop.value(), self.ypoints.value()],
            }
            gen = iter_map_2d(source, gate, meter, x_vals, y_vals, settle=settle)
            instruments = {"x": source, "y": gate, "meter": meter}
            # grid is [gate, bias] (outer=gate=iy, inner=bias=ix)
            self._grid = np.full((len(y_vals), len(x_vals)), np.nan)
            self._bias_span = abs(self.stop.value() - self.start.value())
            self._redraw_image()
            kind = "2d"
        else:
            params = {"start": self.start.value(), "stop": self.stop.value(), "points": self.points.value()}
            gen = iter_linear_sweep(source, meter, self.start.value(), self.stop.value(), self.points.value(), settle=settle)
            instruments = {"source": source, "meter": meter}
            self._x, self._y = [], []
            self.curve.setData([], [])
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

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

    def stop_run(self) -> None:
        if self._worker is not None:
            self._worker.stop()

    def _on_point(self, point: dict) -> None:
        if self._run is not None:
            self._run.append(point)
        meter_name = self._inst["meter"].get_name()
        if self.kind.currentText() == "2D map":
            self._grid[point["iy"], point["ix"]] = point[meter_name]
            self._redraw_image()
        else:
            self._x.append(point["set_voltage"])
            self._y.append(point[meter_name])
            self.curve.setData(self._x, self._y)

    def _redraw_image(self) -> None:
        """Render the [gate, bias] grid as raw I or dI/dV with the chosen map."""
        if self._grid is None:
            return
        quantity = self.quantity.currentText()
        span = getattr(self, "_bias_span", 1.0)
        if quantity == "dI/dV":
            grid = plotting.differentiate_bias(self._grid, bias_axis=span)
            diverging = True
        else:
            grid = self._grid
            diverging = False
        plotting.set_image(self.image, grid, transpose=False,
                           colormap=self.colormap.currentText(), diverging=diverging)

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
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
        self._thread = None
        self._worker = None
        self._run = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)


class MainWindow(QMainWindow):
    def __init__(self, instruments: dict, store):
        super().__init__()
        self.setWindowTitle("emeas — measurement & browser")
        self._store = store

        self.measure_tab = MeasureTab(instruments, store)
        self.browser_tab = BrowserTab(store)
        self.measure_tab.runFinished.connect(lambda _n: self.browser_tab.refresh())

        tabs = QTabWidget()
        tabs.addTab(self.measure_tab, "Measure")
        tabs.addTab(self.browser_tab, "Browse")
        self.setCentralWidget(tabs)
        self._tabs = tabs

        self._build_menu()

    def _build_menu(self) -> None:
        open_act = self.menuBar().addMenu("&File").addAction("Open database…")
        open_act.triggered.connect(self._open_database)

    def _open_database(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Open HDF5 database", "", "HDF5 (*.h5 *.hdf5);;All files (*)")
        if not path:
            return
        from emeas.storage import H5Store

        new_store = H5Store(path)
        old = self._store
        self._store = new_store
        self.measure_tab.set_store(new_store)
        self.browser_tab.set_store(new_store)
        self.browser_tab.refresh()
        try:
            old.close()
        except Exception:
            pass
