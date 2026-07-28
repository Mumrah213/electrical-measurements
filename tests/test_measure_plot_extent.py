"""Live plot-extent scaling as Sweep A/B are edited (before Start is clicked)."""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from emeas.gui.app import build_instruments  # noqa: E402
from emeas.gui.instruments import InstrumentRegistry  # noqa: E402
from emeas.gui.measure import MeasureTab  # noqa: E402
from emeas.storage import H5Store  # noqa: E402

#: module-level reference -- keeps the QApplication singleton's Python
#: wrapper alive between calls (otherwise PyQt6 can garbage-collect the
#: underlying C++ object and crash the next Qt object construction).
_qapp = None


def _app():
    global _qapp
    _qapp = QApplication.instance() or QApplication([])
    return _qapp


def _measure_tab(tmp_path):
    _app()
    store = H5Store(str(tmp_path / "data.h5"))
    instruments, dut = build_instruments()
    registry = InstrumentRegistry(instruments, dut=dut)
    return MeasureTab(registry, store), store


def test_1d_extent_follows_sweep_a_bounds(tmp_path):
    mt, store = _measure_tab(tmp_path)
    try:
        row = mt.axis_a._rows[0]
        row.source_combo.setCurrentText("source")
        row.start.setValue(-3.0)
        row.stop.setValue(3.0)

        x_range, _ = mt.plot1d.getViewBox().viewRange()
        assert x_range[0] < -3.0 < 3.0 < x_range[1]  # padded but centered on [-3, 3]
    finally:
        store.close()


def test_1d_extent_ignores_degenerate_bounds(tmp_path):
    mt, store = _measure_tab(tmp_path)
    try:
        row = mt.axis_a._rows[0]
        row.source_combo.setCurrentText("source")
        row.start.setValue(-3.0)
        row.stop.setValue(3.0)
        before, _ = mt.plot1d.getViewBox().viewRange()

        row.stop.setValue(-3.0)  # start == stop: degenerate, should be ignored
        after, _ = mt.plot1d.getViewBox().viewRange()

        assert after == before
    finally:
        store.close()


def test_2d_extent_follows_sweep_a_and_b_bounds(tmp_path):
    mt, store = _measure_tab(tmp_path)
    try:
        mt.axis_a._rows[0].source_combo.setCurrentText("source")
        mt.axis_a._rows[0].start.setValue(-3.0)
        mt.axis_a._rows[0].stop.setValue(3.0)
        mt.enable_b.setChecked(True)
        mt.axis_b._rows[0].source_combo.setCurrentText("gate")
        mt.axis_b._rows[0].start.setValue(-1.0)
        mt.axis_b._rows[0].stop.setValue(1.0)

        x_range, y_range = mt.image.view.getViewBox().viewRange()
        assert x_range == pytest.approx([-3.0, 3.0])
        assert y_range == pytest.approx([-1.0, 1.0])
    finally:
        store.close()


def test_2d_extent_ignores_degenerate_sweep_b_bounds(tmp_path):
    mt, store = _measure_tab(tmp_path)
    try:
        mt.axis_a._rows[0].source_combo.setCurrentText("source")
        mt.axis_a._rows[0].start.setValue(-3.0)
        mt.axis_a._rows[0].stop.setValue(3.0)
        mt.enable_b.setChecked(True)
        mt.axis_b._rows[0].source_combo.setCurrentText("gate")
        mt.axis_b._rows[0].start.setValue(-1.0)
        mt.axis_b._rows[0].stop.setValue(1.0)
        before = mt.image.view.getViewBox().viewRange()

        mt.axis_b._rows[0].stop.setValue(-1.0)  # start == stop: degenerate, should be ignored
        after = mt.image.view.getViewBox().viewRange()

        assert after == before
    finally:
        store.close()
