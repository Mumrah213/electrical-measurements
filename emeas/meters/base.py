"""Multimeter base class.

A :class:`Multimeter` reads a signal and applies the per-instrument corrections
needed to recover the *physical* quantity at the device:

  * ``gain``             -- gain of any amplifier between DUT and meter. The raw
                            reading is divided by this to get the real signal.
  * ``series_resistance``-- known series/shunt resistance (ohm). For current
                            sensing a voltage is read across a shunt; with
                            ``series_resistance`` set, :meth:`read_current`
                            converts a voltage reading to amps.
  * ``input_impedance``  -- meter input impedance (ohm); recorded so the
                            measurement layer can account for loading of high-
                            impedance sources.

:meth:`read_raw` is exactly what the instrument reports; :meth:`read` is the
gain-corrected physical value. Concrete drivers implement :meth:`_measure`.
"""

from __future__ import annotations

from emeas.instrument import Instrument
from emeas.transport import Transport


class Multimeter(Instrument):
    #: Allowed measurement ranges (V). Subclasses override with datasheet values.
    RANGES: tuple[float, ...] = (10.0,)

    def __init__(
        self,
        transport: Transport,
        *,
        name: str | None = None,
        address: str | None = None,
        gain: float = 1.0,
        series_resistance: float = 0.0,
        input_impedance: float = 1.0e10,
        voltage_range: float | None = None,
    ):
        super().__init__(transport, name=name, address=address)
        if gain == 0:
            raise ValueError("gain must be non-zero")
        self.gain = float(gain)
        self.series_resistance = float(series_resistance)
        self.input_impedance = float(input_impedance)
        self.voltage_range = float(voltage_range) if voltage_range is not None else self.RANGES[-1]

    # -- public API --------------------------------------------------------
    def read_raw(self) -> float:
        """Raw value reported by the instrument (no corrections)."""
        return self._measure()

    def read(self) -> float:
        """Physical signal at the DUT: raw reading divided by amplifier gain."""
        return self.read_raw() / self.gain

    def read_current(self) -> float:
        """Interpret the (gain-corrected) voltage reading as a shunt current.

        Requires ``series_resistance`` (the shunt) to be set and non-zero.
        """
        if not self.series_resistance:
            raise ValueError(
                f"{self.name}: series_resistance (shunt) must be set to read current"
            )
        return self.read() / self.series_resistance

    def settings(self) -> dict:
        s = super().settings()
        s.update(
            role="meter",
            gain=self.gain,
            series_resistance=self.series_resistance,
            input_impedance=self.input_impedance,
            voltage_range=self.voltage_range,
        )
        return s

    # -- hook for concrete drivers ----------------------------------------
    def _measure(self) -> float:  # pragma: no cover - abstract
        raise NotImplementedError
