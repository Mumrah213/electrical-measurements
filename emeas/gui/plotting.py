"""Shared plotting helpers used by both the live view and the browser.

The pure-numpy helpers (:func:`rolling_average`, :func:`grid_from_long`,
:func:`image_levels`) carry no Qt dependency and are unit-tested headlessly. The
``pyqtgraph``-touching helpers draw consistently so a replotted saved run looks
exactly like it did live.
"""

from __future__ import annotations

import numpy as np

# A small, colour-blind-friendly cycle for multiple 1D traces.
_TRACE_COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf"]


def rolling_average(y: np.ndarray, window: int) -> np.ndarray:
    """Centered moving average of ``y`` over ``window`` samples.

    ``window <= 1`` returns ``y`` unchanged. The output has the same length as
    the input (edges use a shrinking window via convolution normalisation).
    """
    y = np.asarray(y, dtype="f8")
    if window <= 1 or y.size == 0:
        return y
    window = min(window, y.size)
    kernel = np.ones(window, dtype="f8")
    sums = np.convolve(y, kernel, mode="same")
    counts = np.convolve(np.ones_like(y), kernel, mode="same")
    return sums / counts


def grid_from_long(
    ix: np.ndarray, iy: np.ndarray, values: np.ndarray, nx: int, ny: int
) -> np.ndarray:
    """Rebuild a ``(ny, nx)`` image grid from long-form streamed columns.

    Mirrors how the live view fills its grid from per-point ``ix``/``iy``.
    Unfilled cells are ``nan``.
    """
    grid = np.full((ny, nx), np.nan, dtype="f8")
    ix = np.asarray(ix, dtype=int)
    iy = np.asarray(iy, dtype=int)
    values = np.asarray(values, dtype="f8")
    for xi, yi, v in zip(ix, iy, values):
        if 0 <= yi < ny and 0 <= xi < nx:
            grid[yi, xi] = v
    return grid


def image_levels(grid: np.ndarray) -> tuple[float, float]:
    """Finite (lo, hi) levels for an image that may contain NaNs.

    Returns a non-degenerate range even when only one cell is filled, so
    ``pyqtgraph.ImageView`` (which autoscales its histogram from the data) never
    sees an all-NaN slice.
    """
    finite = grid[np.isfinite(grid)]
    if finite.size == 0:
        return (0.0, 1.0)
    lo, hi = float(finite.min()), float(finite.max())
    if lo == hi:
        hi = lo + 1e-12
    return lo, hi


# Colormaps offered in the 2D view (all ship with pyqtgraph's matplotlib set).
COLORMAPS = ["viridis", "inferno", "magma", "plasma", "cividis", "gray"]


def differentiate_bias(grid: np.ndarray, bias_axis: float = 1.0) -> np.ndarray:
    """Numerical dI/dV: derivative of ``grid`` along the bias axis.

    ``grid`` is ``[gate, bias]`` (gate = rows, bias = columns), so the
    differentiation is along ``axis=1``. ``bias_axis`` is the total bias span (V)
    used to scale the gradient; pass the (stop-start) range, defaulting to 1.0
    (unit spacing) when unknown. NaNs are preserved where the input was NaN.
    """
    grid = np.asarray(grid, dtype="f8")
    if grid.shape[1] < 2:
        return grid.copy()
    spacing = bias_axis / (grid.shape[1] - 1) if bias_axis else 1.0
    deriv = np.gradient(grid, spacing, axis=1)
    deriv[~np.isfinite(grid)] = np.nan
    return deriv


def set_image(image_view, grid: np.ndarray, *, transpose: bool = False,
              colormap: str | None = None, diverging: bool = False) -> None:
    """Show ``grid`` (possibly NaN) in a pyqtgraph ImageView.

    By default ``grid`` is displayed with axis-0 horizontal and axis-1 vertical.
    For a ``[gate, bias]`` diamond grid this puts **gate on x, bias on y** with
    no transpose. ``transpose=True`` swaps the axes. Unfilled cells render at the
    level minimum so the displayed array is all-finite. When ``diverging`` the
    levels are symmetric about zero (good for signed dI/dV).
    """
    import pyqtgraph as pg

    arr = grid.T if transpose else grid
    lo, hi = image_levels(arr)
    if diverging:
        m = max(abs(lo), abs(hi))
        lo, hi = -m, m
    display = np.where(np.isfinite(arr), arr, lo)
    image_view.setImage(display, levels=(lo, hi), autoLevels=False, autoRange=False)
    if colormap:
        try:
            image_view.setColorMap(pg.colormap.get(colormap))
        except Exception:
            pass


def plot_1d(plot_widget, x: np.ndarray, series: dict, *, smooth_window: int = 1) -> None:
    """Draw named traces against ``x`` on a pyqtgraph PlotWidget.

    ``series`` maps a trace name to its y-array. Existing items are cleared
    first. When ``smooth_window > 1`` a rolling average is drawn for each trace.
    """
    import pyqtgraph as pg

    plot_widget.clear()
    if len(series) > 1:
        plot_widget.addLegend()
    for i, (name, y) in enumerate(series.items()):
        color = _TRACE_COLORS[i % len(_TRACE_COLORS)]
        y = np.asarray(y, dtype="f8")
        if smooth_window > 1:
            # raw trace faint, smoothed trace bold
            plot_widget.plot(x, y, pen=pg.mkPen(color, width=1, style=pg.QtCore.Qt.PenStyle.DotLine))
            plot_widget.plot(x, rolling_average(y, smooth_window), pen=pg.mkPen(color, width=2), name=name)
        else:
            plot_widget.plot(x, y, pen=pg.mkPen(color, width=2), name=name)


# Quantities offered for the 2D view. dI/dV is the default for diamond plots.
QUANTITIES = ["dI/dV", "raw I"]


def make_image_2d_options(parent=None):
    """Build the shared 2D option bar (quantity + colormap dropdowns).

    Returns ``(widget, quantity_combo, colormap_combo)``. Callers connect the
    combos' ``currentTextChanged`` to their replot, and read the current text to
    decide dI/dV vs raw and which colormap to apply.
    """
    from PyQt6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

    widget = QWidget(parent)
    row = QHBoxLayout(widget)
    row.setContentsMargins(0, 0, 0, 0)

    quantity = QComboBox()
    quantity.addItems(QUANTITIES)  # "dI/dV" is index 0 -> default
    colormap = QComboBox()
    colormap.addItems(COLORMAPS)   # "viridis" default

    row.addWidget(QLabel("quantity:"))
    row.addWidget(quantity)
    row.addSpacing(12)
    row.addWidget(QLabel("colormap:"))
    row.addWidget(colormap)
    row.addStretch(1)
    return widget, quantity, colormap


def diamond_grid(data: dict, value_name: str, nx: int, ny: int, *, quantity: str,
                 bias_span: float = 1.0) -> np.ndarray:
    """Build the ``[gate, bias]`` display grid for a 2D run.

    ``quantity`` is ``"dI/dV"`` (numerically differentiate the value along the
    bias axis) or ``"raw I"`` (the stored value as-is).
    """
    grid = grid_from_long(data["ix"], data["iy"], data[value_name], nx, ny)
    if quantity == "dI/dV":
        return differentiate_bias(grid, bias_axis=bias_span)
    return grid
