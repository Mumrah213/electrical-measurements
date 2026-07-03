import numpy as np
import pytest

from emeas import DummyTransport, HP34401A, YokogawaGS200, linear_sweep, map_2d
from emeas.dummy import ResistorModel


def _rig(resistance=1e6, gain=1.0):
    dut = ResistorModel(resistance=resistance)
    src = YokogawaGS200(DummyTransport(dut), name="bias")
    meter = HP34401A(DummyTransport(dut), name="reading", gain=gain)
    return dut, src, meter


def test_linear_sweep_shape_and_columns():
    _, src, meter = _rig()
    df = linear_sweep(src, meter, -1.0, 1.0, 51)
    assert list(df.columns) == ["set_voltage", "reading"]
    assert len(df) == 51
    # voltage-mode dummy returns node voltage -> reading tracks setpoint
    assert df["reading"].iloc[0] == pytest.approx(-1.0)
    assert df["reading"].iloc[-1] == pytest.approx(1.0)
    assert np.all(np.diff(df["reading"].to_numpy()) > 0)  # monotonic


def test_linear_sweep_fixed_source():
    _, src, meter = _rig()
    gate = YokogawaGS200(DummyTransport(), name="gate")
    linear_sweep(src, meter, 0.0, 1.0, 3, fixed={gate: 0.7})
    assert gate.get_voltage() == pytest.approx(0.7)


def test_map_2d_grid():
    _, sx, meter = _rig()
    sy = YokogawaGS200(DummyTransport(), name="gate")
    x = np.linspace(-1, 1, 5)
    y = np.linspace(0, 1, 4)
    df = map_2d(sx, sy, meter, x, y)
    assert list(df.columns) == ["bias", "gate", "reading"]
    assert len(df) == 5 * 4
    grid = df.pivot(index="gate", columns="bias", values="reading")
    assert grid.shape == (4, 5)
