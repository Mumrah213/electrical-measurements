# emeas — self-contained electrical measurement toolkit

Control a benchtop electrical measurement setup (Yokogawa GS200 source meters and
HP/Agilent 34401A multimeters) over GPIB. Each instrument is represented by its
own named object, so measurement scripts stay easy to read:

```python
Y1.get_name()   # -> "source-drain bias"
HP1.read()      # -> gain-corrected reading
```

You don't need lab hardware to develop or test code. The same instrument classes
work with a dummy backend that simulates a device under test, and switching to
real hardware is just a one-line transport change—your measurement code stays
the same.

## Quickstart (dummy mode)

```python
from emeas import YokogawaGS200, HP34401A, DummyTransport, linear_sweep
from emeas.dummy import ResistorModel

dut = ResistorModel(resistance=1e6)
Y1 = YokogawaGS200(DummyTransport(dut), name="source-drain bias")
HP1 = HP34401A(DummyTransport(dut), name="drain reading", gain=1.0)

df = linear_sweep(Y1, HP1, start=-1, stop=1, points=51)
print(df.head())
```

A 2D current map with the side gate held fixed:

```python
from emeas import map_2d
import numpy as np

df = map_2d(
    Y_bias,
    Y_gate,
    HP1,
    x_vals=np.linspace(-1, 1, 51),
    y_vals=np.linspace(-2, 2, 41),
    fixed={Y_sidegate: 0.5},
)

grid = df.pivot(
    index=Y_gate.get_name(),
    columns=Y_bias.get_name(),
    values=HP1.get_name(),
)
```

If you prefer, you can just write your own nested `for` loops over the instrument
objects. The measurement helpers are there for convenience, not because you're
expected to use a framework.

## Live GUI and HDF5 storage

A PyQt6 + pyqtgraph GUI streams measurements into a live plot while saving every
point to an HDF5 database together with the instrument settings used for that
run.

```bash
uv sync --extra gui          # or: pip install -e .[gui]
emeas-gui                    # writes ./emeas_data.h5
emeas-gui my_fridge.h5       # custom database path
```

By default, the dummy backend is connected to a simple Coulomb-diamond
quantum-dot model. A 2D bias-versus-gate scan produces the familiar
Coulomb-blockade diamond pattern, while a 1D bias sweep shows the conductance
turn-on. The **Settle (ms)** control slows down acquisition (50 ms by default)
so you can watch the data arrive in real time.

The 2D view uses the standard convention of gate voltage on the x-axis and
source-drain bias on the y-axis. You can display either **dI/dV** (the default,
calculated numerically along the bias axis) or the raw current, and choose from
several built-in colormaps. dI/dV is shown with a zero-centred diverging colour
scale.

The GUI has two tabs:

- **Measure** — Run either a 1D sweep or a 2D map, configure the sweep
  parameters, add an optional label and tags, then start or stop the measurement.
  Acquisition runs in a background `QThread`, keeping the interface responsive,
  while each point is written to the HDF5 file as soon as it's collected.

- **Browse** — View saved runs in a sortable, filterable table. Selecting a run
  replots the data and displays the complete instrument settings snapshot. You
  can filter by label, measurement type, or tags, rename runs, edit tags, export
  data to CSV, or switch databases via **File ▸ Open database...**. For 1D data,
  the viewer also supports x-axis selection, per-trace visibility toggles, and a
  rolling-average overlay.

## Streaming measurements from scripts

The same generators used by the GUI can also be used directly:

```python
from emeas import iter_linear_sweep
from emeas.storage import H5Store

with H5Store("data.h5") as store:
    run = store.new_run(
        "1d",
        "first cooldown",
        params={"start": -1, "stop": 1, "points": 51},
        instruments={"source": Y1, "meter": HP1},
    )

    for point in iter_linear_sweep(Y1, HP1, -1, 1, 51):
        run.append(point)

    run.close()
```

## HDF5 layout

```
/                       attrs: emeas_version, next_run_number
/runs/run_00001/        attrs: run_number, label, kind, created_iso,
                                params(JSON), notes, tags
        data/           resizable datasets, appended one point at a time
        settings/<role>/ attrs: instrument settings() snapshots
```

Run numbers are persistent and continue across sessions. Labels and tags can be
edited later. You can inspect the file with `h5ls -r data.h5` or access it
programmatically with `store.read_run()` and `store.list_runs()`.

## Using real hardware

Switching from the simulator to a real GPIB instrument only requires replacing
the transport:

```python
from emeas import VisaTransport

Y1 = YokogawaGS200(
    VisaTransport("GPIB0::3::INSTR"),
    name="source-drain bias",
)
```

Command syntax and operating ranges have been checked against the manufacturer
manuals for the Yokogawa GS200 (IM GS210-01EN, Chapter 13) and the
HP/Agilent 34401A (User's Guide, Chapter 4).

The 34401A defaults to a 10 MΩ DC-voltage input impedance. For measurements on
the 100 mV, 1 V, or 10 V ranges, pass `high_impedance=True` to enable the
instrument's >10 GΩ input mode.

## Per-instrument corrections

Calibration and measurement corrections belong to the instrument objects and are
applied automatically.

| Instrument | Parameters |
|------------|------------|
| `VoltageSource` | `voltage_range`, `series_resistance` |
| `Multimeter` | `gain`, `series_resistance`, `input_impedance`, `voltage_range` |

- `meter.read_raw()` returns the instrument reading.
- `meter.read()` removes the configured amplifier gain.
- `meter.read_current()` converts a shunt voltage into current.

## Development

```bash
uv sync --extra dev      # or: pip install -e .[dev]
uv run pytest            # or: pytest
```

The backend, storage layer, and GUI worker are all tested headlessly, including
tests that exercise a real `QThread`. Qt tests can be run without a display:

```bash
QT_QPA_PLATFORM=offscreen pytest
```

## Docker

```bash
docker build -t emeas .
docker run --rm emeas
```

To use real GPIB hardware inside a container, the host's VISA backend and
USB-GPIB device need to be made available to the container. The dummy backend
requires no additional setup.
