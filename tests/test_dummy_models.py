"""Tests for the synthetic demo dummy models."""

import numpy as np
import pytest

from emeas import DummyTransport, HP34401A, YokogawaGS200, iter_linear_sweep, iter_map_2d
from emeas.dummy import CoulombDiamondModel, SineModel


def test_sine_model_traces_a_sinusoid():
    dut = SineModel(amplitude=1.0, frequency=1.0, phase=0.0, noise=0.0)
    src = YokogawaGS200(DummyTransport(dut), name="V")
    meter = HP34401A(DummyTransport(dut), name="signal", gain=1.0)
    pts = list(iter_linear_sweep(src, meter, 0.0, 1.0, 5))
    ys = [p["signal"] for p in pts]
    # sin(2*pi*f*V): 0 at V=0, ~0 at V=0.5, 0 at V=1.0; peak near V=0.25
    assert ys[0] == pytest.approx(0.0, abs=1e-9)
    assert ys[2] == pytest.approx(0.0, abs=1e-9)   # V=0.5
    assert ys[1] > 0.9                               # V=0.25 near +1


def test_diamond_channels_are_independent():
    """bias and gate must not clobber each other (separate channels)."""
    dut = CoulombDiamondModel(noise=0.0)
    bias = YokogawaGS200(DummyTransport(dut, channel="bias"), name="Vsd")
    gate = YokogawaGS200(DummyTransport(dut, channel="gate"), name="Vg")
    bias.set_voltage(0.2)
    gate.set_voltage(0.5)
    assert dut.v_bias == 0.2
    assert dut.v_gate == 0.5


def test_diamond_blockade_at_centre_conduction_at_edge():
    dut = CoulombDiamondModel(period=0.4, ec=0.3, gamma=0.03, noise=0.0)
    meter = HP34401A(DummyTransport(dut, channel="meter"), name="G", gain=1.0)
    # at a diamond centre (gate on a degeneracy-free point, Vsd=0): blockaded
    dut.v_gate = 0.0
    dut.v_bias = 0.0
    assert meter.read() < 0.1
    # large bias breaks blockade: conducting
    dut.v_bias = 0.5
    assert meter.read() > 0.9
    # at a charge-degeneracy point (gate = half period) conduction survives Vsd=0
    dut.v_gate = 0.2  # period/2
    dut.v_bias = 0.0
    assert meter.read() > 0.4


def test_extra_channel_on_shared_dut_keeps_independent_setpoint():
    """A 3rd instrument sharing a DUT (e.g. a fixed sidegate) must not clobber
    or be clobbered by bias/gate's setpoint -- regression test for the bug
    where DeviceModel.node_voltage was a single shared field regardless of
    channel."""
    dut = CoulombDiamondModel(noise=0.0)
    bias = YokogawaGS200(DummyTransport(dut, channel="bias"), name="Vsd")
    extra = YokogawaGS200(DummyTransport(dut, channel="yoko3"), name="yoko3")

    extra.set_voltage(1.23)
    bias.set_voltage(0.3)

    assert extra.get_voltage() == pytest.approx(1.23)
    assert bias.get_voltage() == pytest.approx(0.3)
    assert dut.v_bias == pytest.approx(0.3)


def test_resistor_model_default_channel_readback():
    """A lone unchanneled instrument keeps its setpoint readback (no channel= given)."""
    from emeas.dummy import ResistorModel

    dut = ResistorModel(resistance=1e3)
    src = YokogawaGS200(DummyTransport(dut), name="V")
    src.set_voltage(0.75)
    assert src.get_voltage() == pytest.approx(0.75)


def test_diamond_map_is_periodic_in_gate():
    dut = CoulombDiamondModel(period=0.4, ec=0.3, gamma=0.03, noise=0.0)
    bias = YokogawaGS200(DummyTransport(dut, channel="bias"), name="Vsd")
    gate = YokogawaGS200(DummyTransport(dut, channel="gate"), name="Vg")
    meter = HP34401A(DummyTransport(dut, channel="meter"), name="G", gain=1.0)
    Vsd = np.linspace(-0.5, 0.5, 11)
    Vg = np.linspace(-0.6, 0.6, 13)
    grid = np.zeros((len(Vg), len(Vsd)))
    for p in iter_map_2d(bias, gate, meter, Vsd, Vg):
        grid[p["iy"], p["ix"]] = p["G"]
    # rows one gate-period apart should be ~equal (periodicity)
    # Vg step = 1.2/12 = 0.1; period 0.4 -> 4 steps apart
    assert np.allclose(grid[0], grid[4], atol=1e-6)
    assert np.allclose(grid[4], grid[8], atol=1e-6)
