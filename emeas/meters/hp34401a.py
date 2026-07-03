"""HP/Agilent 34401A 6.5-digit multimeter driver.

Command strings and ranges verified against the HP 34401A User's Guide,
Chapter 4 (Remote Interface Reference). References: ``CONFigure:VOLTage:DC``
(p.119, configures only -- does not initiate), ``READ?`` (p.113, initiates and
returns), DC-volts ranges 100 mV / 1 V / 10 V / 100 V / 1000 V (p.18), and DC
input resistance (p.53).
"""

from __future__ import annotations

from emeas.meters.base import Multimeter
from emeas.transport import Transport


class HP34401A(Multimeter):
    #: DC-volts range presets, in volts (34401A User's Guide, p.18).
    RANGES = (0.1, 1.0, 10.0, 100.0, 1000.0)

    #: High-impedance (>10 GOhm) is only available on these low ranges (p.53).
    HIGH_Z_RANGES = (0.1, 1.0, 10.0)

    def __init__(
        self,
        transport: Transport,
        *,
        name: str | None = None,
        address: str | None = None,
        gain: float = 1.0,
        series_resistance: float = 0.0,
        # Default DC-volt input resistance is 10 MOhm on every range (p.53).
        # Pass high_impedance=True to switch the three lowest ranges to >10 GOhm.
        input_impedance: float | None = None,
        high_impedance: bool = False,
        voltage_range: float | None = None,
    ):
        self.high_impedance = bool(high_impedance)
        if input_impedance is None:
            input_impedance = 1.0e10 if self.high_impedance else 1.0e7
        super().__init__(
            transport,
            name=name,
            address=address,
            gain=gain,
            series_resistance=series_resistance,
            input_impedance=input_impedance,
            voltage_range=voltage_range,
        )
        # Configure for DC voltage on the chosen range. CONF resets input
        # impedance to 10 MOhm (p.53), so enable high-Z *after* it if requested.
        self.transport.write(f"CONF:VOLT:DC {self.voltage_range}")
        if self.high_impedance:
            if self.voltage_range not in self.HIGH_Z_RANGES:
                raise ValueError(
                    f"high_impedance is only available on the {self.HIGH_Z_RANGES} V "
                    f"ranges (34401A User's Guide p.53); got {self.voltage_range} V"
                )
            self.transport.write("INP:IMP:AUTO ON")

    def _measure(self) -> float:
        return float(self.transport.query("READ?"))
