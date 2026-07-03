"""Base class shared by every instrument.

An :class:`Instrument` is a thin, named handle over a
:class:`~emeas.transport.Transport`. The display name is the human-facing label
used in scripts and data columns -- e.g. ``Y1.get_name() -> "source-drain
bias"`` -- and can be changed at any time.
"""

from __future__ import annotations

from emeas.transport import Transport


class Instrument:
    def __init__(self, transport: Transport, *, name: str | None = None, address: str | None = None):
        self.transport = transport
        self.address = address
        self._name = name or self.__class__.__name__

    # -- display name ------------------------------------------------------
    def get_name(self) -> str:
        return self._name

    def set_name(self, name: str) -> None:
        self._name = str(name)

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str) -> None:
        self.set_name(value)

    # -- common SCPI -------------------------------------------------------
    def idn(self) -> str:
        """Return the instrument identification string (``*IDN?``)."""
        return self.transport.query("*IDN?")

    def close(self) -> None:
        self.transport.close()

    # -- settings snapshot -------------------------------------------------
    def settings(self) -> dict:
        """Serializable snapshot of this instrument's configuration.

        Used to record the full experimental settings alongside each saved run.
        Subclasses extend this with their device-specific knobs.
        """
        return {
            "class": self.__class__.__name__,
            "name": self._name,
            "address": self.address if self.address is not None else "",
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self._name!r}>"
