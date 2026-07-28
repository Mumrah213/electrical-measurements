# emeas — self-contained electrical measurement toolkit

Control a benchtop electrical measurement setup (Yokogawa GS200 source meters and
HP/Agilent 34401A multimeters) over GPIB. Each instrument is represented by its
own named object, so measurement scripts stay easy to read:

```python
Y1.get_name()   # -> "source-drain bias"
HP1.read()      # -> gain-corrected reading
```

emeas has been **validated against real Yokogawa GS200 and HP 34401A instruments
in a live lab environment** over the course of several years. 

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

## Live GUI and HDF5 storage

A PyQt6 + pyqtgraph GUI streams measurements into a live plot while saving every
point to an HDF5 database together with the instrument settings used for that
run.

```bash
uv sync --extra gui          # or: pip install -e .[gui]
emeas-gui                    # writes ./emeas_data.h5
emeas-gui my_fridge.h5       # custom database path
```

The GUI has three tabs:
- **Instruments** — Used to keep track of instruments. Can be discovered
  automatically by sweeping the network for GPIB devices, or by manually
  defining them.

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

The generators used by the GUI can also be used directly:

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


## Using real hardware

```python
from emeas import VisaTransport

Y1 = YokogawaGS200(
    VisaTransport("GPIB0::3::INSTR"),
    name="source-drain bias",
)
```

Command syntax, operating ranges, and data accuracy have been validated
against real instruments on a live GPIB bus — Yokogawa GS200
 and HP 34401A.

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

```bash
QT_QPA_PLATFORM=offscreen pytest
```

## Docker - not for PyQt based GUI

```bash
docker build -t emeas .
docker run --rm emeas
```

To use GPIB hardware inside a container, the host's VISA backend and
USB-GPIB device need to be made available to the container. 
