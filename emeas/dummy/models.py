"""Simulated device models used by :class:`~emeas.transport.DummyTransport`.

A model holds the simulated circuit state. A voltage source writes its setpoint
into the model (``SOUR:LEV <v>``, the GS200 level command); a multimeter reads
back a quantity from the
model (``READ?`` / ``MEAS?``). Several instruments can share one model instance
to represent a single device-under-test wired to multiple instruments.

The command vocabulary here is deliberately small and SCPI-flavoured; the real
instrument drivers are written to emit these same commands so the dummy and the
hardware paths stay symmetric.
"""

from __future__ import annotations

import numpy as np


class DeviceModel:
    """Base model: ohmic resistor between the sourced node and ground.

    State:
      * ``node_voltage`` -- last voltage written by a source (volts).
      * ``resistance``   -- DUT resistance (ohms); current = V / R.

    Queries understood:
      * ``MEAS:VOLT?`` / ``READ?`` (when in volt mode) -> node voltage
      * ``MEAS:CURR?``                                 -> current through DUT
      * ``SOUR:LEV?``                                  -> last setpoint
    """

    def __init__(self, resistance: float = 1.0e6, noise: float = 0.0, seed: int | None = None):
        self.resistance = float(resistance)
        self.noise = float(noise)
        self.node_voltage = 0.0
        self._rng = np.random.default_rng(seed)

    # -- source side -------------------------------------------------------
    def handle_write(self, command: str, channel: str | None = None) -> None:
        cmd = command.strip()
        upper = cmd.upper()
        # Accept the GS200 level command SOUR:LEV (and the older SOUR:VOLT alias).
        if (upper.startswith("SOUR:LEV") or upper.startswith("SOUR:VOLT")) and " " in cmd:
            # e.g. "SOUR:LEV 0.5"
            self.node_voltage = float(cmd.split()[-1])

    # -- meter side --------------------------------------------------------
    def handle_query(self, command: str, channel: str | None = None) -> str:
        upper = command.strip().upper()
        if upper.startswith("SOUR:LEV?") or upper.startswith("SOUR:VOLT?"):
            return f"{self.node_voltage:.6e}"
        if upper.startswith("MEAS:CURR?") or "CURR" in upper:
            return f"{self._noisy(self.current()):.6e}"
        # default: a voltage measurement (MEAS:VOLT?, READ?, FETCH?)
        return f"{self._noisy(self.voltage()):.6e}"

    # -- physics -----------------------------------------------------------
    def voltage(self) -> float:
        """Voltage the meter sees across the DUT (volts)."""
        return self.node_voltage

    def current(self) -> float:
        """Current through the DUT (amps), Ohm's law."""
        if self.resistance == 0:
            return 0.0
        return self.node_voltage / self.resistance

    def _noisy(self, value: float) -> float:
        if self.noise:
            return value + self._rng.normal(0.0, self.noise)
        return value


class ResistorModel(DeviceModel):
    """Explicit linear resistor DUT (clearer name for scripts/tests)."""

    def __init__(self, resistance: float = 1.0e6, noise: float = 0.0, seed: int | None = None):
        super().__init__(resistance=resistance, noise=noise, seed=seed)


class SineModel(DeviceModel):
    """1D demo DUT: the meter reads a (damped) sinusoid of the swept voltage.

    ``reading(V) = amplitude * sin(2*pi*frequency*V + phase) * exp(-|V|/decay)``

    Purely for visualising a streaming sweep -- a clear wave that decays toward
    the sweep edges. ``node_voltage`` is the swept setpoint.
    """

    def __init__(
        self,
        amplitude: float = 1.0,
        frequency: float = 1.0,
        phase: float = 0.0,
        decay: float = 1e9,
        noise: float = 0.02,
        seed: int | None = None,
    ):
        super().__init__(resistance=1.0, noise=noise, seed=seed)
        self.amplitude = float(amplitude)
        self.frequency = float(frequency)
        self.phase = float(phase)
        self.decay = float(decay)

    def voltage(self) -> float:
        v = self.node_voltage
        return self.amplitude * np.sin(2 * np.pi * self.frequency * v + self.phase) * np.exp(-abs(v) / self.decay)


class CoulombDiamondModel(DeviceModel):
    """2D demo DUT: Coulomb-blockade diamonds in the (gate, bias) plane.

    Tracks two channels independently -- ``bias`` (source-drain ``Vsd``) and
    ``gate`` (``Vg``) -- so a 2D map of bias vs gate reproduces the iconic
    diamond pattern. This is a fast, closed-form caricature (no master-equation
    solver); a qmeq-backed model can replace it behind an optional extra later.

    Physics caricature: charge-degeneracy points sit at gate spacing ``period``.
    Inside a diamond the dot is blockaded (~zero conductance); transport turns on
    once ``|Vsd|`` exceeds the bias needed to reach a charge transition, with the
    diamond half-width set by the charging energy ``ec`` and gate lever arm.
    The meter returns a differential-conductance-like value in [0, ~1].
    """

    def __init__(
        self,
        period: float = 0.4,      # gate spacing between Coulomb peaks (V)
        ec: float = 0.3,          # charging energy -> diamond height in Vsd (V)
        lever_arm: float = 1.0,   # gate-to-dot coupling (dimensionless)
        gamma: float = 0.04,      # edge sharpness (V); smaller = crisper edges
        noise: float = 0.01,
        seed: int | None = None,
    ):
        super().__init__(resistance=1.0, noise=noise, seed=seed)
        self.period = float(period)
        self.ec = float(ec)
        self.lever_arm = float(lever_arm)
        self.gamma = float(gamma)
        self.v_bias = 0.0
        self.v_gate = 0.0

    def handle_write(self, command: str, channel: str | None = None) -> None:
        cmd = command.strip()
        upper = cmd.upper()
        if (upper.startswith("SOUR:LEV") or upper.startswith("SOUR:VOLT")) and " " in cmd:
            value = float(cmd.split()[-1])
            self.node_voltage = value
            if channel == "gate":
                self.v_gate = value
            else:  # default / "bias"
                self.v_bias = value

    def voltage(self) -> float:
        """Differential-conductance-like reading at (v_gate, v_bias)."""
        # distance from the nearest charge-degeneracy gate position
        detune = self.v_gate - self.period * round(self.v_gate / self.period)
        # half-height of the diamond at this detuning: zero at a degeneracy
        # point (peak conducts at Vsd=0), max = ec at diamond centre
        half = self.ec * (1.0 - 2.0 * abs(detune) / self.period)  # in [-ec, ec]
        half = max(half, 0.0)
        # conducting when |Vsd| is outside the blockaded diamond (|Vsd| > half)
        edge = (abs(self.v_bias) - half) / self.gamma
        conductance = 1.0 / (1.0 + np.exp(-edge))  # smooth 0->1 across the edge
        return float(conductance)

    def current(self) -> float:
        return self.voltage()
