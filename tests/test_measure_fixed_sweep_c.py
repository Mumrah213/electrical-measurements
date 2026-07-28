"""Sweep C ("fixed") end-to-end: held-constant instruments through a real run."""

import time

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
    return MeasureTab(registry, store), store, registry


def _run_to_completion(app, mt, timeout_s=5.0):
    deadline = time.time() + timeout_s
    while mt._thread is not None and time.time() < deadline:
        app.processEvents()
        time.sleep(0.01)


def test_fixed_instrument_held_constant_through_1d_run(tmp_path):
    app = _app()
    mt, store, registry = _measure_tab(tmp_path)
    try:
        registry.build_and_set({
            "role": "yoko3", "driver_label": "YokogawaGS200 (source)", "name": "yoko3",
            "use_visa": False, "visa_resource": "", "channel": "yoko3",
            "voltage_range": 10.0, "gain": 1.0,
        })
        mt.axis_a._set_role_on_combo(mt.axis_a._rows[0].source_combo, "source")
        mt.axis_a._rows[0].start.setValue(-0.3)
        mt.axis_a._rows[0].stop.setValue(0.3)
        mt.axis_a.points_spin.setValue(5)
        mt.meter_combo.setCurrentText("meter")

        mt.axis_c._add_row()
        mt.axis_c._set_role_on_combo(mt.axis_c._rows[0].source_combo, "yoko3")
        mt.axis_c._rows[0].value.setValue(1.23)

        mt.start_run()
        _run_to_completion(app, mt)

        yoko3 = registry.instruments["yoko3"]
        assert yoko3.get_voltage() == pytest.approx(1.23)
        assert len(mt._x) == 5

        run = store.read_run(1)
        assert run["params"]["sweep_c"] == {"instruments": ["yoko3"], "values": [1.23]}
        assert "c0" in run["settings"]
    finally:
        store.close()
