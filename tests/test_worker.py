"""Worker tests -- exercise the QThread + signals path without any display.

Uses QApplication (not just QCoreApplication) so the process-wide app
singleton is compatible with other test modules in this suite that build
actual widgets (QApplication is a QCoreApplication subclass, so this is a
strict superset and still runs fine headless via QT_QPA_PLATFORM=offscreen).
"""

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtCore import QThread, QTimer  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from emeas.gui.worker import MeasurementWorker  # noqa: E402


#: module-level reference -- keeps the QApplication singleton's Python
#: wrapper alive between calls (otherwise PyQt6 can garbage-collect the
#: underlying C++ object and crash the next Qt object construction).
_qapp = None


def _app():
    global _qapp
    _qapp = QApplication.instance() or QApplication([])
    return _qapp


def _run_worker(gen, stop_after=None):
    """Run a worker to completion on a real QThread; return collected points."""
    app = _app()
    points = []
    result = {}

    worker = MeasurementWorker(gen)
    thread = QThread()
    worker.moveToThread(thread)

    def on_point(pt):
        points.append(pt)
        if stop_after is not None and len(points) >= stop_after:
            worker.stop()

    def on_finished(summary):
        result.update(summary)
        thread.quit()

    worker.point.connect(on_point)
    worker.finished.connect(on_finished)
    worker.error.connect(lambda m: (result.update(error=m), thread.quit()))
    thread.started.connect(worker.run)

    # safety timeout so a hang fails the test instead of blocking forever
    QTimer.singleShot(5000, thread.quit)
    thread.start()
    while thread.isRunning():
        app.processEvents()
        thread.wait(10)
    return points, result


def test_worker_delivers_all_points():
    gen = ({"i": i, "v": float(i)} for i in range(10))
    points, result = _run_worker(gen)
    assert len(points) == 10
    assert result["count"] == 10
    assert result["cancelled"] is False


def test_worker_cooperative_stop():
    # A small per-point sleep gives the main thread time to deliver the queued
    # `point` signal and call stop() before the worker emits the next point --
    # this mirrors real hardware, where settle/read latency dominates.
    import time

    def slow():
        for i in range(1000):
            time.sleep(0.005)
            yield {"i": i}

    points, result = _run_worker(slow(), stop_after=5)
    assert result["cancelled"] is True
    # stopped well before exhausting the 1000-point generator
    assert len(points) < 50


def test_worker_surfaces_errors():
    def boom():
        yield {"i": 0}
        raise RuntimeError("kaboom")

    points, result = _run_worker(boom())
    assert len(points) == 1
    assert "kaboom" in result.get("error", "")
