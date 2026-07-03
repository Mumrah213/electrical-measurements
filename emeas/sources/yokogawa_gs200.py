"""Yokogawa GS200 DC voltage/current source driver.

Command strings verified against the GS200 User's Manual, IM GS210-01EN (9th
ed.), Chapter 13. Key references: source level is ``:SOURce:LEVel`` (13-11),
range is ``:SOURce:RANGe`` (13-11), function is ``:SOURce:FUNCtion`` (13-11),
output is ``:OUTPut[:STATe]`` (13-10). Voltage-range presets are 1 V / 10 V /
30 V (13-11); the finer 10 mV / 100 mV presets are current ranges, not voltage.
"""

from __future__ import annotations

from emeas.sources.base import VoltageSource
from emeas.transport import Transport


class YokogawaGS200(VoltageSource):
    #: Voltage-range presets, in volts (IM GS210-01EN, 13-11).
    RANGES = (1.0, 10.0, 30.0)

    def __init__(
        self,
        transport: Transport,
        *,
        name: str | None = None,
        address: str | None = None,
        voltage_range: float | None = None,
        series_resistance: float = 0.0,
    ):
        super().__init__(
            transport,
            name=name,
            address=address,
            voltage_range=voltage_range,
            series_resistance=series_resistance,
        )
        # Put the instrument into DC-voltage source mode. FUNC must precede
        # RANGe/LEVel (13-11: "set the source function to voltage before...").
        self.transport.write("SOUR:FUNC VOLT")
        self.transport.write(f"SOUR:RANG {self.voltage_range}")

    def _write_voltage(self, volts: float) -> None:
        # Source level is :SOUR:LEV, not :SOUR:VOLT (IM GS210-01EN, 13-11).
        self.transport.write(f"SOUR:LEV {volts:.6e}")

    def _read_voltage(self) -> float:
        return float(self.transport.query("SOUR:LEV?"))

    def output_on(self) -> None:
        self.transport.write("OUTP ON")

    def output_off(self) -> None:
        self.transport.write("OUTP OFF")
