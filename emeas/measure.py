"""Reusable measurement routines.

These are thin orchestration helpers over the instrument objects -- nothing
here is privileged. A 2D map written as a hand-rolled nested ``for`` loop using
the same instruments is perfectly valid; ``map_2d`` just packages the common
case and returns a tidy :class:`pandas.DataFrame`.

The ``iter_*`` generators yield one point at a time, which is what lets the GUI
plot live and the HDF5 writer append as data arrives. The ``linear_sweep`` /
``map_2d`` functions are thin wrappers that collect a generator into a
DataFrame, so scripted use is unchanged.

A ``fixed`` mapping lets you hold other sources at constant setpoints for the
duration of a measurement (e.g. a sidegate)::

    linear_sweep(Y1, HP1, -1, 1, 51, fixed={Ygate: 0.5})
"""

from __future__ import annotations

import time
from collections.abc import Iterator, Mapping, Sequence

import numpy as np
import pandas as pd

from emeas.meters.base import Multimeter
from emeas.sources.base import VoltageSource


def _apply_fixed(fixed: Mapping[VoltageSource, float] | None) -> None:
    if fixed:
        for src, value in fixed.items():
            src.set_voltage(value)


def iter_linear_sweep(
    source: VoltageSource,
    meter: Multimeter,
    start: float,
    stop: float,
    points: int,
    *,
    settle: float = 0.0,
    fixed: Mapping[VoltageSource, float] | None = None,
) -> Iterator[dict]:
    """Yield one point at a time while sweeping ``source`` and reading ``meter``.

    Each point is a dict ``{"set_voltage": v, <meter.name>: reading}``.
    """
    _apply_fixed(fixed)
    setpoints = np.linspace(start, stop, points)
    for v in setpoints:
        source.set_voltage(float(v))
        if settle:
            time.sleep(settle)
        yield {"set_voltage": float(v), meter.get_name(): meter.read()}


def iter_map_2d(
    source_x: VoltageSource,
    source_y: VoltageSource,
    meter: Multimeter,
    x_vals: Sequence[float],
    y_vals: Sequence[float],
    *,
    settle: float = 0.0,
    fixed: Mapping[VoltageSource, float] | None = None,
) -> Iterator[dict]:
    """Yield one point at a time while rastering ``source_x`` x ``source_y``.

    Each point includes integer grid indices ``ix``/``iy`` (so a streaming
    consumer can place it in an image without tracking position itself) plus the
    setpoints and reading, keyed by the instrument display names.
    """
    _apply_fixed(fixed)
    x_name = source_x.get_name()
    y_name = source_y.get_name()
    m_name = meter.get_name()

    for iy, y in enumerate(y_vals):
        source_y.set_voltage(float(y))
        for ix, x in enumerate(x_vals):
            source_x.set_voltage(float(x))
            if settle:
                time.sleep(settle)
            yield {
                "ix": ix,
                "iy": iy,
                x_name: float(x),
                y_name: float(y),
                m_name: meter.read(),
            }


def linear_sweep(
    source: VoltageSource,
    meter: Multimeter,
    start: float,
    stop: float,
    points: int,
    *,
    settle: float = 0.0,
    fixed: Mapping[VoltageSource, float] | None = None,
) -> pd.DataFrame:
    """Sweep ``source`` from ``start`` to ``stop`` and read ``meter``.

    Returns a DataFrame with a ``set_voltage`` column and one column named after
    ``meter.get_name()`` holding the corrected readings.
    """
    return pd.DataFrame(
        iter_linear_sweep(
            source, meter, start, stop, points, settle=settle, fixed=fixed
        )
    )


def map_2d(
    source_x: VoltageSource,
    source_y: VoltageSource,
    meter: Multimeter,
    x_vals: Sequence[float],
    y_vals: Sequence[float],
    *,
    settle: float = 0.0,
    fixed: Mapping[VoltageSource, float] | None = None,
) -> pd.DataFrame:
    """Raster ``source_x`` x ``source_y`` and read ``meter`` at each point.

    Returns a tidy (long-form) DataFrame with columns named after the two
    sources and the meter, one row per grid point. Reshape/pivot as needed for
    plotting, e.g. ``df.pivot(index=y_name, columns=x_name, values=meter_name)``.
    """
    points = iter_map_2d(
        source_x, source_y, meter, x_vals, y_vals, settle=settle, fixed=fixed
    )
    # Drop the streaming-only grid indices for the tidy DataFrame form.
    rows = [{k: v for k, v in p.items() if k not in ("ix", "iy")} for p in points]
    return pd.DataFrame(rows, columns=[source_x.get_name(), source_y.get_name(), meter.get_name()])
