"""Measured-data dummy DUT: file parsing, nearest-point readback, DUT swapping."""

import os

import numpy as np
import pytest

from emeas.dummy import CoulombDiamondModel, MeasuredDataModel, load_sweep_grid

EXAMPLE = os.path.join(os.path.dirname(__file__), "..", "experimental_data_examples", "coulomb_diamonds.txt")


def _write_fixture(path, *, gate=(-1.0, 0.0, 1.0), bias=(-2.0, 0.0, 2.0, 4.0)):
    """A tiny file in the same export format: current = bias*10 + gate."""
    lines = ["NA\tStep V(V)->\t" + "\t".join(str(g) for g in gate)]
    lines.append("Time(s):\tSweep V(V):\t" + "\t".join("Ch1 I(A) 0.1K" for _ in gate))
    for i, b in enumerate(bias):
        row = [str(0.1 * i), str(b)] + [str(b * 10 + g) for g in gate]
        lines.append("\t".join(row))
    path.write_text("\n".join(lines) + "\n")
    return path


def test_parse_fixture(tmp_path):
    path = _write_fixture(tmp_path / "map.txt")
    gate, bias, current = load_sweep_grid(str(path))
    assert gate.tolist() == [-1.0, 0.0, 1.0]
    assert bias.tolist() == [-2.0, 0.0, 2.0, 4.0]
    assert current.shape == (4, 3)
    assert current[2, 0] == pytest.approx(2 * 10 + (-1))


def test_parse_rejects_ragged_and_bad_header(tmp_path):
    bad = tmp_path / "bad.txt"
    bad.write_text("nonsense\nheader\n1\t2\t3\n")
    with pytest.raises(ValueError):
        load_sweep_grid(str(bad))

    ragged = _write_fixture(tmp_path / "ragged.txt")
    ragged.write_text(ragged.read_text() + "0.5\t9.0\n")  # row with too few columns
    with pytest.raises(ValueError, match="columns"):
        load_sweep_grid(str(ragged))


def test_parse_real_example_file():
    gate, bias, current = load_sweep_grid(EXAMPLE)
    assert gate.shape == (281,)
    assert bias.shape == (801,)
    assert current.shape == (801, 281)
    assert gate[0] == pytest.approx(-2.2)
    assert gate[-1] == pytest.approx(-0.8)
    assert bias[0] == pytest.approx(-10.0)
    assert bias[-1] == pytest.approx(10.0)
    # first data cell from the file: -5.820320E-9
    assert current[0, 0] == pytest.approx(-5.820320e-9)


def test_nearest_point_readback(tmp_path):
    model = MeasuredDataModel.from_file(str(_write_fixture(tmp_path / "map.txt")))
    # between grid points -> snaps to nearest cell, no interpolation
    model.handle_write("SOUR:LEV 0.4", channel="gate")    # nearest gate = 0.0
    model.handle_write("SOUR:LEV 1.9", channel="bias")    # nearest bias = 2.0
    assert model.handle_query("MEAS:CURR?") == f"{2 * 10 + 0:.6e}"
    # out of range -> clamps to the nearest edge cell
    model.handle_write("SOUR:LEV -99", channel="gate")
    model.handle_write("SOUR:LEV 99", channel="bias")
    assert float(model.handle_query("READ?")) == pytest.approx(4 * 10 + (-1))
    # an unrelated channel tracks its setpoint but doesn't move gate/bias
    model.handle_write("SOUR:LEV 3.3", channel="sidegate")
    assert float(model.handle_query("SOUR:LEV?", channel="sidegate")) == pytest.approx(3.3)
    assert float(model.handle_query("READ?")) == pytest.approx(4 * 10 + (-1))


def test_registry_set_dut_rewires_dummy_instruments(tmp_path):
    pytest.importorskip("PyQt6")
    from emeas.gui.instruments import InstrumentRegistry, default_dut

    registry = InstrumentRegistry({}, dut=default_dut())
    registry.build_and_set({
        "role": "source", "driver_label": "YokogawaGS200 (source)", "name": "bias",
        "use_visa": False, "visa_resource": "", "channel": "bias",
        "voltage_range": 10.0, "gain": 1.0,
    })
    registry.build_and_set({
        "role": "meter", "driver_label": "HP34401A (meter)", "name": "current",
        "use_visa": False, "visa_resource": "", "channel": "meter",
        "voltage_range": 10.0, "gain": 1.0,
    })

    model = MeasuredDataModel.from_file(str(_write_fixture(tmp_path / "map.txt")))
    registry.set_dut(model)
    assert registry.dut is model
    for inst in registry.instruments.values():
        assert inst.transport.model is model

    # snapshot round-trips the choice, and falls back cleanly if the file is gone
    snap = registry.dut_snapshot()
    assert snap == {"kind": "measured", "path": str(tmp_path / "map.txt")}
    registry.load_dut_snapshot({"kind": "measured", "path": "/nonexistent/file.txt"})
    assert isinstance(registry.dut, CoulombDiamondModel)
    registry.load_dut_snapshot(snap)
    assert isinstance(registry.dut, MeasuredDataModel)
