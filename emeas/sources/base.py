"""Voltage source base class.

A :class:`VoltageSource` exposes ``set_voltage`` / ``get_voltage`` and carries
the per-instrument physical configuration we need to model the real setup:

  * ``voltage_range``    -- max |output| the instrument is configured for (V).
  * ``series_resistance``-- output / line resistance in series with the DUT (ohm).

The *requested* device-under-test voltage and the *applied* source voltage can
differ once series resistance is taken into account; for a pure source we apply
the setpoint at the instrument terminals and expose ``series_resistance`` so the
measurement layer (or the user) can correct for the IR drop when a current is
known. Setpoints outside ``voltage_range`` are rejected.
"""

from __future__ import annotations

from emeas.instrument import Instrument
from emeas.transport import Transport


class VoltageSource(Instrument):
    #: Allowed range presets (V). Subclasses override with datasheet values.
    RANGES: tuple[float, ...] = (30.0,)

    def __init__(
        self,
        transport: Transport,
        *,
        name: str | None = None,
        address: str | None = None,
        voltage_range: float | None = None,
        series_resistance: float = 0.0,
    ):
        super().__init__(transport, name=name, address=address)
        self.voltage_range = float(voltage_range) if voltage_range is not None else self.RANGES[-1]
        self.series_resistance = float(series_resistance)
        self._setpoint = 0.0

    # -- public API --------------------------------------------------------
    def set_voltage(self, volts: float) -> None:
        """Apply ``volts`` at the source terminals (validated against range)."""
        if abs(volts) > self.voltage_range:
            raise ValueError(
                f"{self.name}: {volts} V exceeds configured range "
                f"+/-{self.voltage_range} V"
            )
        self._setpoint = float(volts)
        self._write_voltage(volts)

    def get_voltage(self) -> float:
        """Return the source setpoint (V), read back from the instrument."""
        return self._read_voltage()

    def settings(self) -> dict:
        s = super().settings()
        s.update(
            role="source",
            voltage_range=self.voltage_range,
            series_resistance=self.series_resistance,
        )
        return s

    # -- hooks for concrete drivers ---------------------------------------
    def _write_voltage(self, volts: float) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def _read_voltage(self) -> float:  # pragma: no cover - abstract
        raise NotImplementedError
