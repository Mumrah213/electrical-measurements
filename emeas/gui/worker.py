"""Background measurement worker.

A :class:`MeasurementWorker` runs a point-yielding generator (e.g.
``iter_linear_sweep``) on a worker thread and emits one Qt signal per point, so
the GUI thread stays responsive. It supports cooperative cancellation via
:meth:`stop` -- the flag is checked once per point.

This module imports only ``PyQt6.QtCore`` (no widgets), so the worker can be
exercised in tests with a ``QCoreApplication`` and no display.
"""

from __future__ import annotations

from collections.abc import Iterable

from PyQt6.QtCore import QObject, pyqtSignal


class MeasurementWorker(QObject):
    #: emitted once per measured point, carrying the point dict
    point = pyqtSignal(dict)
    #: emitted when the run ends; carries a small summary dict
    finished = pyqtSignal(dict)
    #: emitted if the generator raises; carries the error text
    error = pyqtSignal(str)

    def __init__(self, generator: Iterable[dict]):
        super().__init__()
        self._generator = generator
        self._stop = False

    def stop(self) -> None:
        """Request cooperative cancellation before the next point."""
        self._stop = True

    def run(self) -> None:
        """Slot to connect to ``QThread.started``. Drives the generator."""
        count = 0
        cancelled = False
        try:
            for pt in self._generator:
                if self._stop:
                    cancelled = True
                    break
                count += 1
                self.point.emit(pt)
        except Exception as exc:  # surface to the GUI rather than crash the thread
            self.error.emit(f"{type(exc).__name__}: {exc}")
            return
        self.finished.emit({"count": count, "cancelled": cancelled})
