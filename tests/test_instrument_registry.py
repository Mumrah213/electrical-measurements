"""InstrumentRegistry.search_gpib(): dummy-rig fallback + discovered-resource path."""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QApplication  # noqa: E402

from emeas.gui import instruments as instruments_mod  # noqa: E402
from emeas.gui.instruments import InstrumentRegistry  # noqa: E402

_qapp = None


def _app():
    global _qapp
    _qapp = QApplication.instance() or QApplication([])
    return _qapp


def test_search_gpib_falls_back_to_dummy_rig_when_none_found(monkeypatch):
    _app()
    monkeypatch.setattr(instruments_mod, "list_gpib_resources", lambda: [])
    registry = InstrumentRegistry({})

    added, errors = registry.search_gpib()

    assert errors == []
    assert set(added) == {"yoko1", "yoko2", "yoko3", "yoko4", "meter1", "meter2"}
    assert set(registry.instruments) == set(added)
    roles_by_class = {role: type(inst).__name__ for role, inst in registry.instruments.items()}
    assert sum(cls == "YokogawaGS200" for cls in roles_by_class.values()) == 4
    assert sum(cls == "HP34401A" for cls in roles_by_class.values()) == 2
    # each dummy instrument is on its own channel, not sharing one
    channels = {inst.transport.channel for inst in registry.instruments.values()}
    assert len(channels) == 6


def test_search_gpib_adds_discovered_resources_with_guessed_driver(monkeypatch):
    _app()
    monkeypatch.setattr(instruments_mod, "list_gpib_resources",
                         lambda: ["GPIB0::3::INSTR", "GPIB0::5::INSTR"])

    class FakeVisaTransport:
        def __init__(self, resource):
            self.resource = resource

        def query(self, cmd):
            return "YOKOGAWA,GS200,0,1.0" if self.resource == "GPIB0::3::INSTR" else "HEWLETT-PACKARD,34401A,0,1.0"

        def write(self, cmd):
            pass

        def close(self):
            pass

    monkeypatch.setattr(instruments_mod, "VisaTransport", FakeVisaTransport)
    registry = InstrumentRegistry({})

    added, errors = registry.search_gpib()

    assert errors == []
    assert added == ["gpib0", "gpib1"]
    assert type(registry.instruments["gpib0"]).__name__ == "YokogawaGS200"
    assert type(registry.instruments["gpib1"]).__name__ == "HP34401A"


def test_search_gpib_collects_errors_without_aborting(monkeypatch):
    _app()
    monkeypatch.setattr(instruments_mod, "list_gpib_resources",
                         lambda: ["GPIB0::3::INSTR", "GPIB0::5::INSTR"])

    class FlakyVisaTransport:
        def __init__(self, resource):
            if resource == "GPIB0::3::INSTR":
                raise RuntimeError("timeout")
            self.resource = resource

        def query(self, cmd):
            return "SOME,OTHER,DEVICE"

        def write(self, cmd):
            pass

        def close(self):
            pass

    monkeypatch.setattr(instruments_mod, "VisaTransport", FlakyVisaTransport)
    registry = InstrumentRegistry({})

    added, errors = registry.search_gpib()

    assert added == ["gpib1"]
    assert len(errors) == 1
    assert "GPIB0::3::INSTR" in errors[0]
