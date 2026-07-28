"""HDF5 storage for measurement runs.

Each run is saved to its own group under ``/runs`` with:

  * **rich, findable metadata** -- an auto-incrementing ``run_number`` that
    persists across sessions (a counter lives in the file root), a user-editable
    ``label``, ISO timestamp, measurement ``kind`` and ``params``, and free-text
    ``notes``;
  * **streamed data** in resizable datasets, appended one point at a time so a
    crash mid-run keeps everything written so far;
  * a **settings snapshot** of every instrument involved (from
    :meth:`Instrument.settings`), so a run is self-describing and reproducible.

The storage layer is Qt-free and usable from plain scripts::

    with H5Store("data.h5") as store:
        run = store.new_run("1d", "first cooldown",
                            params={"start": -1, "stop": 1, "points": 51},
                            instruments={"source": Y1, "meter": HP1})
        for point in iter_linear_sweep(Y1, HP1, -1, 1, 51):
            run.append(point)
        run.close()
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import h5py
import numpy as np

EMEAS_VERSION = "0.1.0"
# Keys that are streaming-only positioning hints, never stored as data columns.
_INDEX_KEYS = ("ix", "iy")


def _iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class RunWriter:
    """Handle to a single run's group; appends streamed points to HDF5."""

    #: minimum seconds between flushes while streaming; a flush per point makes
    #: appends dominated by disk syncs and stalls the GUI thread at high rates
    _FLUSH_INTERVAL_S = 1.0

    def __init__(self, group: h5py.Group, file: h5py.File):
        self._g = group
        self._file = file
        self._data = group["data"]
        self._columns: list[str] | None = None
        self._last_flush = 0.0

    @property
    def run_number(self) -> int:
        return int(self._g.attrs["run_number"])

    @property
    def label(self) -> str:
        return str(self._g.attrs["label"])

    def set_label(self, label: str) -> None:
        """Rename the run; takes effect immediately in the file."""
        self._g.attrs["label"] = str(label)
        self._file.flush()

    def _ensure_columns(self, point: dict) -> None:
        if self._columns is not None:
            return
        cols = [k for k in point if k not in _INDEX_KEYS]
        for name in cols:
            self._data.create_dataset(
                name, shape=(0,), maxshape=(None,), dtype="f8", chunks=(256,)
            )
        # Preserve grid index columns for 2D maps so the image can be rebuilt.
        for name in _INDEX_KEYS:
            if name in point:
                self._data.create_dataset(
                    name, shape=(0,), maxshape=(None,), dtype="i8", chunks=(256,)
                )
        self._columns = list(self._data.keys())

    def append(self, point: dict) -> None:
        """Append one streamed point; datasets grow by one row.

        Flushes to disk at most every :attr:`_FLUSH_INTERVAL_S` (a crash loses
        at most that last window of points); :meth:`close` flushes the rest.
        """
        self._ensure_columns(point)
        for name in self._columns:
            ds = self._data[name]
            n = ds.shape[0]
            ds.resize((n + 1,))
            ds[n] = point.get(name, np.nan)
        now = time.monotonic()
        if now - self._last_flush >= self._FLUSH_INTERVAL_S:
            self._file.flush()
            self._last_flush = now

    def close(self) -> None:
        self._g.attrs["finished_iso"] = _iso_now()
        self._file.flush()


class H5Store:
    """Open or create an HDF5 measurement database."""

    def __init__(self, path: str):
        self.path = path
        self._file = h5py.File(path, "a")
        if "emeas_version" not in self._file.attrs:
            self._file.attrs["emeas_version"] = EMEAS_VERSION
        if "next_run_number" not in self._file.attrs:
            self._file.attrs["next_run_number"] = 1
        self._file.require_group("runs")
        self._file.flush()

    # -- writing -----------------------------------------------------------
    def _allocate_run_number(self) -> int:
        n = int(self._file.attrs["next_run_number"])
        self._file.attrs["next_run_number"] = n + 1
        self._file.flush()
        return n

    def new_run(
        self,
        kind: str,
        label: str | None = None,
        *,
        params: dict | None = None,
        instruments: dict | None = None,
        notes: str = "",
        tags: str = "",
    ) -> RunWriter:
        """Start a new run group and write its metadata + settings snapshot.

        ``instruments`` maps a role name (e.g. ``"source"``, ``"meter"``,
        ``"gate"``) to an instrument; each instrument's ``settings()`` dict is
        stored as attributes under ``settings/<role>``. ``tags`` is free-text
        (e.g. a project name) used for filtering in the browser.
        """
        number = self._allocate_run_number()
        created = _iso_now()
        if not label:
            label = f"run_{number:05d} {created}"

        g = self._file["runs"].create_group(f"run_{number:05d}")
        g.attrs["run_number"] = number
        g.attrs["label"] = label
        g.attrs["kind"] = kind
        g.attrs["created_iso"] = created
        g.attrs["params"] = json.dumps(params or {})
        g.attrs["notes"] = notes
        g.attrs["tags"] = tags
        g.create_group("data")

        settings = g.create_group("settings")
        for role, inst in (instruments or {}).items():
            sub = settings.create_group(role)
            for key, value in inst.settings().items():
                sub.attrs[key] = value

        self._file.flush()
        return RunWriter(g, self._file)

    # -- reading -----------------------------------------------------------
    def list_runs(self) -> list[dict]:
        """Summaries of stored runs, sorted by run number."""
        out = []
        for name in self._file["runs"]:
            g = self._file["runs"][name]
            data = g["data"]
            points = int(next(iter(data.values())).shape[0]) if len(data) else 0
            out.append(
                {
                    "run_number": int(g.attrs["run_number"]),
                    "label": str(g.attrs["label"]),
                    "kind": str(g.attrs["kind"]),
                    "created_iso": str(g.attrs["created_iso"]),
                    "tags": str(g.attrs.get("tags", "")),
                    "points": points,
                }
            )
        return sorted(out, key=lambda r: r["run_number"])

    def read_run(self, run_number: int) -> dict:
        """Read a run back: metadata, data columns (as arrays), and settings."""
        g = self._file["runs"][f"run_{run_number:05d}"]
        data = {name: g["data"][name][:] for name in g["data"]}
        settings = {
            role: dict(g["settings"][role].attrs) for role in g.get("settings", {})
        }
        return {
            "run_number": int(g.attrs["run_number"]),
            "label": str(g.attrs["label"]),
            "kind": str(g.attrs["kind"]),
            "created_iso": str(g.attrs["created_iso"]),
            "params": json.loads(g.attrs["params"]),
            "notes": str(g.attrs.get("notes", "")),
            "tags": str(g.attrs.get("tags", "")),
            "data": data,
            "settings": settings,
        }

    # -- editing -----------------------------------------------------------
    def _run_group(self, run_number: int):
        return self._file["runs"][f"run_{run_number:05d}"]

    def set_label(self, run_number: int, label: str) -> None:
        """Rename a stored run (usable for runs this store didn't create)."""
        self._run_group(run_number).attrs["label"] = str(label)
        self._file.flush()

    def set_tags(self, run_number: int, tags: str) -> None:
        """Set the free-text tags on a stored run."""
        self._run_group(run_number).attrs["tags"] = str(tags)
        self._file.flush()

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        self._file.close()

    def __enter__(self) -> "H5Store":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
