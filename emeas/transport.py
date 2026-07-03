"""Communication transports for instruments.

Every instrument talks to the world through a :class:`Transport`. The real lab
uses :class:`VisaTransport` (PyVISA over GPIB); away from the lab we use
:class:`DummyTransport`, which forwards commands to a simulated device model so
the whole stack runs end-to-end with no hardware.

Swapping one for the other is the *only* change needed to go from simulation to
real hardware -- instrument and measurement code is identical either way.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from emeas.dummy.models import DeviceModel


class Transport(ABC):
    """Minimal SCPI-style transport: write a command, query a response."""

    @abstractmethod
    def write(self, command: str) -> None:
        """Send a command that expects no reply."""

    @abstractmethod
    def query(self, command: str) -> str:
        """Send a command and return its (string) reply."""

    def close(self) -> None:  # pragma: no cover - default no-op
        """Release the underlying resource. Safe to call more than once."""


class VisaTransport(Transport):
    """Real GPIB transport backed by PyVISA.

    ``resource`` is a VISA resource string, e.g. ``"GPIB0::3::INSTR"``. This
    path is exercised only in the lab; it is intentionally a thin wrapper.
    """

    def __init__(self, resource: str, *, timeout_ms: int = 5000, resource_manager=None):
        import pyvisa  # imported lazily so dummy-only use needs no VISA backend

        self.resource = resource
        self._rm = resource_manager or pyvisa.ResourceManager()
        self._inst = self._rm.open_resource(resource)
        self._inst.timeout = timeout_ms

    def write(self, command: str) -> None:
        self._inst.write(command)

    def query(self, command: str) -> str:
        return self._inst.query(command).strip()

    def close(self) -> None:
        try:
            self._inst.close()
        except Exception:  # pragma: no cover - best effort cleanup
            pass


class DummyTransport(Transport):
    """In-memory transport that drives a simulated :class:`DeviceModel`.

    All commands are recorded in :attr:`history` so tests can assert exactly
    what an instrument emitted. Commands are dispatched to ``model`` for state
    changes and readings; multiple instruments may share one ``model`` to
    simulate a single device under test wired to several instruments.
    """

    def __init__(
        self,
        model: "DeviceModel" | None = None,
        *,
        idn: str = "DUMMY,MODEL,0,0.1",
        channel: str | None = None,
    ):
        from emeas.dummy.models import DeviceModel

        self.model = model if model is not None else DeviceModel()
        self.idn_string = idn
        # Optional channel label (e.g. "bias"/"gate") so a shared multi-knob
        # model can tell which instrument sent a command.
        self.channel = channel
        self.history: list[str] = []

    def write(self, command: str) -> None:
        self.history.append(command)
        self.model.handle_write(command, channel=self.channel)

    def query(self, command: str) -> str:
        self.history.append(command)
        if command.strip().upper().startswith("*IDN?"):
            return self.idn_string
        return self.model.handle_query(command, channel=self.channel)
