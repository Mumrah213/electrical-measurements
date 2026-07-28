from emeas import DummyTransport
from emeas.dummy import ResistorModel
from emeas.transport import list_gpib_resources


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


def test_list_gpib_resources_filters_to_gpib():
    class FakeRM:
        def list_resources(self):
            return ("GPIB0::3::INSTR", "GPIB0::12::INSTR", "ASRL1::INSTR", "USB0::1234::5678::INSTR")

    assert list_gpib_resources(resource_manager=FakeRM()) == ["GPIB0::3::INSTR", "GPIB0::12::INSTR"]


def test_list_gpib_resources_empty_when_none_connected():
    class FakeRM:
        def list_resources(self):
            return ()

    assert list_gpib_resources(resource_manager=FakeRM()) == []


def test_list_gpib_resources_returns_empty_on_failure():
    class BoomRM:
        def list_resources(self):
            raise RuntimeError("no backend")

    assert list_gpib_resources(resource_manager=BoomRM()) == []
