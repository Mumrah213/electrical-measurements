"""Dummy DUT backed by a previously *measured* 2D map.

:func:`load_sweep_grid` parses the tab-separated export format used by the lab
sweep software (see ``experimental_data_examples/coulomb_diamonds.txt``):

* line 1: ``NA``, ``Step V(V)->``, then one stepped (gate) voltage per column
* line 2: per-column headers (``Time(s):``, ``Sweep V(V):``, ``Ch1 I(A) ...``) -- skipped
* lines 3+: one row per swept (bias) point: time, bias voltage, then one
  measured current per gate column

:class:`MeasuredDataModel` exposes that grid through the same interface as the
synthetic models in :mod:`emeas.dummy.models`: sources write ``gate``/``bias``
setpoints, the meter reads back the current measured at the *nearest* grid
point (no interpolation -- a sweep literally re-streams the recorded data).
"""

from __future__ import annotations

import numpy as np

from emeas.dummy.models import DeviceModel, _DEFAULT_CHANNEL


def load_sweep_grid(path: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Parse a stepped-sweep TSV export into ``(gate, bias, current)`` arrays.

    ``gate`` has one entry per stepped column, ``bias`` one per data row, and
    ``current`` is shaped ``(len(bias), len(gate))`` in amps. Raises
    ``ValueError`` on a malformed file (wrong header, ragged rows, or
    non-monotonic axes).
    """
    with open(path) as fh:
        lines = [line.rstrip("\n") for line in fh if line.strip()]
    if len(lines) < 3:
        raise ValueError(f"{path}: expected a step header, a column header, and data rows")

    step_cells = lines[0].split("\t")
    if len(step_cells) < 3 or "step" not in step_cells[1].lower():
        raise ValueError(f"{path}: line 1 should be 'NA<TAB>Step V(V)-><TAB><gate values...>'")
    try:
        gate = np.array([float(v) for v in step_cells[2:]], dtype="f8")
    except ValueError as exc:
        raise ValueError(f"{path}: non-numeric gate value in step header: {exc}") from None

    ncols = len(step_cells)
    bias_list: list[float] = []
    rows: list[list[float]] = []
    for lineno, line in enumerate(lines[2:], start=3):
        cells = line.split("\t")
        if len(cells) != ncols:
            raise ValueError(f"{path}: line {lineno} has {len(cells)} columns, expected {ncols}")
        try:
            values = [float(v) for v in cells]
        except ValueError as exc:
            raise ValueError(f"{path}: non-numeric value on line {lineno}: {exc}") from None
        bias_list.append(values[1])  # values[0] is the timestamp -- ignored
        rows.append(values[2:])

    bias = np.array(bias_list, dtype="f8")
    current = np.array(rows, dtype="f8")
    for name, axis in (("gate", gate), ("bias", bias)):
        diffs = np.diff(axis)
        if not (np.all(diffs > 0) or np.all(diffs < 0)):
            raise ValueError(f"{path}: {name} axis is not monotonic")
    return gate, bias, current


def _nearest_index(axis: np.ndarray, value: float) -> int:
    """Index of the ``axis`` entry closest to ``value`` (axis may run either way)."""
    return int(np.argmin(np.abs(axis - value)))


class MeasuredDataModel(DeviceModel):
    """DUT that replays a measured ``(gate, bias) -> current`` map.

    Same channel convention as
    :class:`~emeas.dummy.models.CoulombDiamondModel`: writes on the ``gate``
    channel move the gate setpoint, writes on ``bias`` (or an unchanneled
    source) move the bias; any other named channel only tracks its own
    setpoint. Readings return the current (amps) recorded at the grid point
    nearest the current setpoints -- values outside the measured window clamp
    to the nearest edge.
    """

    def __init__(self, gate: np.ndarray, bias: np.ndarray, current: np.ndarray,
                 noise: float = 0.0, seed: int | None = None, path: str | None = None):
        super().__init__(resistance=1.0, noise=noise, seed=seed)
        gate = np.asarray(gate, dtype="f8")
        bias = np.asarray(bias, dtype="f8")
        current = np.asarray(current, dtype="f8")
        if current.shape != (bias.size, gate.size):
            raise ValueError(
                f"current grid shape {current.shape} does not match (len(bias), len(gate)) = "
                f"({bias.size}, {gate.size})"
            )
        self.gate_axis = gate
        self.bias_axis = bias
        self.current_grid = current
        self.path = path
        self.v_bias = 0.0
        self.v_gate = 0.0

    @classmethod
    def from_file(cls, path: str, noise: float = 0.0, seed: int | None = None) -> "MeasuredDataModel":
        gate, bias, current = load_sweep_grid(path)
        return cls(gate, bias, current, noise=noise, seed=seed, path=path)

    def handle_write(self, command: str, channel: str | None = None) -> None:
        cmd = command.strip()
        upper = cmd.upper()
        if (upper.startswith("SOUR:LEV") or upper.startswith("SOUR:VOLT")) and " " in cmd:
            value = float(cmd.split()[-1])
            self.channel_voltages[channel or _DEFAULT_CHANNEL] = value
            self.node_voltage = value
            if channel == "gate":
                self.v_gate = value
            elif channel in (None, "bias"):
                self.v_bias = value

    def voltage(self) -> float:
        """Measured current (amps) at the grid point nearest (v_gate, v_bias)."""
        iy = _nearest_index(self.bias_axis, self.v_bias)
        ix = _nearest_index(self.gate_axis, self.v_gate)
        return float(self.current_grid[iy, ix])

    def current(self) -> float:
        return self.voltage()
