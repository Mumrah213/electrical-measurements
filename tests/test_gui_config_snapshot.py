"""Config snapshot round-trip through the actual widgets.

Requires PyQt6 widgets (not just QCoreApplication); run headless via
QT_QPA_PLATFORM=offscreen (set in CI / by the test runner), matching the rest
of the offscreen GUI smoke-testing used in this project.
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from emeas.gui.app import build_instruments  # noqa: E402
from emeas.gui.instruments import InstrumentRegistry  # noqa: E402
from emeas.gui.main_window import MainWindow  # noqa: E402
from emeas.storage import H5Store  # noqa: E402


#: module-level reference -- without this, nothing keeps the QApplication
#: singleton's Python wrapper alive between calls and PyQt6 garbage-collects
#: the underlying C++ object, crashing the next widget construction.
_qapp = None


def _app():
    global _qapp
    _qapp = QApplication.instance() or QApplication([])
    return _qapp


def _build_window(db_path):
    _app()
    store = H5Store(str(db_path))
    instruments, dut = build_instruments()
    registry = InstrumentRegistry(instruments, dut=dut)
    window = MainWindow(registry, store, db_path=str(db_path))
    return window, store


def test_default_rig_instruments_are_snapshotable(tmp_path):
    window, store = _build_window(tmp_path / "data.h5")
    try:
        snapshot = window.to_snapshot()
        assert {i["role"] for i in snapshot["instruments"]} == {"source", "gate", "meter"}
    finally:
        store.close()


def test_instrument_and_sweep_round_trip(tmp_path):
    db_path = tmp_path / "data.h5"
    window, store = _build_window(db_path)
    try:
        window._registry.build_and_set({
            "role": "yoko2", "driver_label": "YokogawaGS200 (source)", "name": "yoko2",
            "use_visa": False, "visa_resource": "", "channel": "yoko2",
            "voltage_range": 10.0, "gain": 1.0,
        })
        row = window.measure_tab.axis_a._rows[0]
        window.measure_tab.axis_a._set_role_on_combo(row.source_combo, "source")
        row.start.setValue(-2.0)
        row.stop.setValue(2.0)
        window.measure_tab.axis_a.points_spin.setValue(33)
        window.measure_tab._select_meter_role("meter")
        window.measure_tab.label.setText("my label")
        window.measure_tab.tags.setText("tagA,tagB")

        snapshot = window.to_snapshot()
    finally:
        store.close()

    # restore into a fresh window/registry, as would happen on next launch
    window2, store2 = _build_window(db_path)
    try:
        window2.load_snapshot(snapshot)
        assert list(window2._registry.instruments) == ["source", "gate", "meter", "yoko2"]
        assert window2.measure_tab.axis_a.selected_roles() == ["source"]
        assert window2.measure_tab.axis_a.bounds() == [(-2.0, 2.0)]
        assert window2.measure_tab.axis_a.point_count() == 33
        assert window2.measure_tab._selected_meter_role() == "meter"
        assert window2.measure_tab.label.text() == "my label"
        assert window2.measure_tab.tags.text() == "tagA,tagB"
    finally:
        store2.close()


def test_fixed_sweep_c_round_trip(tmp_path):
    db_path = tmp_path / "data.h5"
    window, store = _build_window(db_path)
    try:
        window._registry.build_and_set({
            "role": "yoko3", "driver_label": "YokogawaGS200 (source)", "name": "yoko3",
            "use_visa": False, "visa_resource": "", "channel": "yoko3",
            "voltage_range": 10.0, "gain": 1.0,
        })
        window.measure_tab.axis_c._add_row()
        window.measure_tab.axis_c._set_role_on_combo(window.measure_tab.axis_c._rows[0].source_combo, "yoko3")
        window.measure_tab.axis_c._rows[0].value.setValue(1.23)

        snapshot = window.to_snapshot()
        assert snapshot["measure"]["axis_c"] == {"roles": ["yoko3"], "values": [1.23]}
    finally:
        store.close()

    window2, store2 = _build_window(db_path)
    try:
        window2.load_snapshot(snapshot)
        assert window2.measure_tab.axis_c.selected_roles() == ["yoko3"]
        assert window2.measure_tab.axis_c.values() == pytest.approx([1.23])
    finally:
        store2.close()


def test_close_event_autosaves(tmp_path):
    from emeas.gui import config_store

    db_path = tmp_path / "data.h5"
    window, store = _build_window(db_path)
    try:
        window.measure_tab.label.setText("closed-label")
        window.close()
    finally:
        store.close()

    loaded = config_store.load_autosave(config_store.autosave_path(db_path))
    assert loaded is not None
    assert loaded["measure"]["label"] == "closed-label"
