import numpy as np
import pytest

from emeas import (
    DummyTransport,
    HP34401A,
    YokogawaGS200,
    iter_linear_sweep,
    iter_map_2d,
    linear_sweep,
    map_2d,
)
from emeas.dummy import ResistorModel
from emeas.measure import iter_linear_sweep_group, iter_map_2d_group


def _rig(gain=1.0):
    dut = ResistorModel(resistance=1e6)
    src = YokogawaGS200(DummyTransport(dut), name="bias")
    meter = HP34401A(DummyTransport(dut), name="reading", gain=gain)
    return dut, src, meter


def test_iter_linear_sweep_points():
    _, src, meter = _rig()
    pts = list(iter_linear_sweep(src, meter, -1, 1, 5))
    assert len(pts) == 5
    assert set(pts[0]) == {"set_voltage", "reading"}
    assert pts[0]["set_voltage"] == pytest.approx(-1.0)
    assert pts[-1]["reading"] == pytest.approx(1.0)


def test_iter_matches_wrapper_dataframe():
    _, src, meter = _rig()
    df = linear_sweep(src, meter, -1, 1, 7)
    pts = list(iter_linear_sweep(src, meter, -1, 1, 7))
    assert list(df.columns) == ["set_voltage", "reading"]
    assert df["reading"].tolist() == pytest.approx([p["reading"] for p in pts])


def test_iter_map_2d_indices_and_count():
    _, src, meter = _rig()
    sy = YokogawaGS200(DummyTransport(), name="gate")
    x = np.linspace(-1, 1, 3)
    y = np.linspace(0, 1, 2)
    pts = list(iter_map_2d(src, sy, meter, x, y))
    assert len(pts) == 6
    assert pts[0]["ix"] == 0 and pts[0]["iy"] == 0
    assert pts[-1]["ix"] == 2 and pts[-1]["iy"] == 1
    assert {"ix", "iy", "bias", "gate", "reading"} == set(pts[0])


def test_map_2d_wrapper_drops_indices():
    _, src, meter = _rig()
    sy = YokogawaGS200(DummyTransport(), name="gate")
    df = map_2d(src, sy, meter, np.linspace(-1, 1, 3), np.linspace(0, 1, 2))
    assert list(df.columns) == ["bias", "gate", "reading"]
    assert "ix" not in df.columns


def test_iter_linear_sweep_group_lockstep():
    _, src, meter = _rig()
    src2 = YokogawaGS200(DummyTransport(), name="gate")
    pts = list(iter_linear_sweep_group([src, src2], [(-1, 1), (-0.5, 0.5)], meter, 5))
    assert len(pts) == 5
    assert set(pts[0]) == {"bias", "gate", "reading"}
    assert pts[0]["bias"] == pytest.approx(-1.0)
    assert pts[0]["gate"] == pytest.approx(-0.5)
    assert pts[-1]["bias"] == pytest.approx(1.0)
    assert pts[-1]["gate"] == pytest.approx(0.5)


def test_iter_map_2d_group_indices_and_lockstep():
    _, src, meter = _rig()
    src2 = YokogawaGS200(DummyTransport(), name="bias2")
    sy = YokogawaGS200(DummyTransport(), name="gate")
    pts = list(iter_map_2d_group([src, src2], [(-1, 1), (-0.5, 0.5)], 3, [sy], [(0, 1)], 2, meter))
    assert len(pts) == 6
    assert pts[0]["ix"] == 0 and pts[0]["iy"] == 0
    assert pts[-1]["ix"] == 2 and pts[-1]["iy"] == 1
    assert {"ix", "iy", "bias", "bias2", "gate", "reading"} == set(pts[0])
    assert pts[0]["bias"] == pytest.approx(-1.0)
    assert pts[0]["bias2"] == pytest.approx(-0.5)


def test_settings_shapes():
    _, src, meter = _rig(gain=10.0)
    s = src.settings()
    assert s["role"] == "source" and s["class"] == "YokogawaGS200"
    m = meter.settings()
    assert m["role"] == "meter" and m["gain"] == 10.0
    assert "input_impedance" in m
