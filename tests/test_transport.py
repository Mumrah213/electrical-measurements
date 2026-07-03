from emeas import DummyTransport
from emeas.dummy import ResistorModel


def test_dummy_records_history_and_idn():
    t = DummyTransport(idn="ACME,X,1,2")
    t.write("SOUR:VOLT 0.5")
    assert t.history == ["SOUR:VOLT 0.5"]
    assert t.query("*IDN?") == "ACME,X,1,2"


def test_dummy_routes_to_model():
    dut = ResistorModel(resistance=1000.0)
    t = DummyTransport(dut)
    t.write("SOUR:VOLT 2.0")
    assert float(t.query("MEAS:VOLT?")) == 2.0
    assert float(t.query("MEAS:CURR?")) == 2.0 / 1000.0
