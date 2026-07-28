"""Persist GUI configuration (instruments + measure setup) as plain JSON.

A "snapshot" is the JSON-serializable dict produced by
:meth:`~emeas.gui.main_window.MainWindow.to_snapshot` -- the instrument
registry contents plus the Measure tab's sweep setup. Two files live next to
the HDF5 database:

* the **autosave** file, always overwritten with the latest snapshot (loaded
  automatically on the next launch so the app reopens where it left off);
* the **history** log, an append-only list of named snapshots the user saved
  explicitly, for quick reload later.

Both are plain JSON so they're human-readable/diffable; no new dependency is
introduced (:mod:`emeas.storage` already uses stdlib ``json`` for per-run
params).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

#: history entries beyond this count are dropped, oldest first
MAX_HISTORY = 50


def autosave_path(db_path: str | os.PathLike) -> Path:
    return Path(db_path).resolve().parent / ".emeas_autosave.json"


def history_path(db_path: str | os.PathLike) -> Path:
    return Path(db_path).resolve().parent / ".emeas_history.json"


def _atomic_write(path: Path, data: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def save_autosave(snapshot: dict, path: str | os.PathLike) -> None:
    """Overwrite the autosave file at ``path`` with ``snapshot``."""
    _atomic_write(Path(path), snapshot)


def load_autosave(path: str | os.PathLike) -> dict | None:
    """Return the last autosaved snapshot, or ``None`` if missing/corrupt."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def append_history(snapshot: dict, path: str | os.PathLike, *, name: str | None = None) -> None:
    """Append ``snapshot`` to the history log at ``path``, capped at :data:`MAX_HISTORY`."""
    entries = load_history(path)
    entries.append({
        "name": name or f"config {len(entries) + 1}",
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "config": snapshot,
    })
    entries = entries[-MAX_HISTORY:]
    _atomic_write(Path(path), entries)


def load_history(path: str | os.PathLike) -> list[dict]:
    """Return the history log at ``path``, or ``[]`` if missing/corrupt."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []
