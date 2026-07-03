import pytest

from emeas import DummyTransport, HP34401A, YokogawaGS200
from emeas.dummy import ResistorModel


def test_name_roundtrip():
    src = YokogawaGS200(DummyTransport(), name="source-drain bias")
    assert src.get_name() == "source-drain bias"
    src.set_name("gate")
    assert src.get_name() == "gate"
    src.name = "back-gate"
    assert src.name == "back-gate"


def test_source_set_get_voltage():
    dut = ResistorModel(resistance=1e6)
    src = YokogawaGS200(DummyTransport(dut), name="bias")
    src.set_voltage(0.5)
    assert src.get_voltage() == pytest.approx(0.5)
    # the GS200 level command SOUR:LEV was emitted to the transport (13-11)
    assert any(cmd.startswith("SOUR:LEV ") for cmd in src.transport.history)


def test_range_clamping_rejects_out_of_range():
    src = YokogawaGS200(DummyTransport(), voltage_range=1.0)
    src.set_voltage(0.9)  # ok
    with pytest.raises(ValueError):
        src.set_voltage(1.5)


def test_meter_gain_correction():
    dut = ResistorModel(resistance=1e6)
    t = DummyTransport(dut)
    meter = HP34401A(t, name="drain", gain=1000.0)
    dut.node_voltage = 2.0  # raw signal at meter
    assert meter.read_raw() == pytest.approx(2.0)
    assert meter.read() == pytest.approx(2.0 / 1000.0)


def test_meter_current_via_shunt():
    dut = ResistorModel()
    meter = HP34401A(DummyTransport(dut), gain=1.0, series_resistance=100.0)
    dut.node_voltage = 1.0  # 1 V across a 100 ohm shunt -> 10 mA
    assert meter.read_current() == pytest.approx(0.01)


def test_meter_current_requires_shunt():
    meter = HP34401A(DummyTransport(), series_resistance=0.0)
    with pytest.raises(ValueError):
        meter.read_current()


def test_idn():
    src = YokogawaGS200(DummyTransport(idn="YOKOGAWA,GS200,0,1.0"))
    assert "GS200" in src.idn()


def test_meter_default_input_impedance_is_10meg():
    # Default DC-volt input resistance is 10 MOhm, not 10 GOhm (User's Guide p.53).
    meter = HP34401A(DummyTransport(), voltage_range=1.0)
    assert meter.input_impedance == pytest.approx(1.0e7)
    # CONF configures but must not enable high-Z on its own.
    assert not any(c.startswith("INP:IMP:AUTO") for c in meter.transport.history)


def test_meter_high_impedance_emits_auto_on_after_conf():
    meter = HP34401A(DummyTransport(), voltage_range=1.0, high_impedance=True)
    assert meter.input_impedance == pytest.approx(1.0e10)
    hist = meter.transport.history
    # INP:IMP:AUTO ON must come *after* CONF, which would otherwise reset it.
    conf_i = next(i for i, c in enumerate(hist) if c.startswith("CONF:VOLT:DC"))
    auto_i = next(i for i, c in enumerate(hist) if c == "INP:IMP:AUTO ON")
    assert auto_i > conf_i


def test_meter_high_impedance_rejected_on_high_range():
    with pytest.raises(ValueError):
        HP34401A(DummyTransport(), voltage_range=100.0, high_impedance=True)
