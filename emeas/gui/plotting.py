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


#: default high percentile for dI/dV level clipping -- the full max is usually
#: one or two sharp conducting-edge pixels that wash out the blockaded
#: background, so clip a bit below it.
DIDV_HIGH_PERCENTILE = 98.0
#: low percentile for dI/dV clipping, expressed as a fraction of the clipped
#: high value -- dI/dV noise floor is legitimately near/below zero, but a
#: symmetric range (equal to the diverging default) buries the positive
#: features we actually care about, so only allow a little below zero.
DIDV_LOW_FRACTION = -0.08


def didv_levels(grid: np.ndarray) -> tuple[float, float]:
    """Sensible default (lo, hi) for a dI/dV grid: mostly-positive, outlier-robust.

    dI/dV is dominated by a near-zero blockaded background with a handful of
    sharp positive conducting-edge spikes; a plain min/max (or a symmetric
    ``diverging`` range) stretches the color scale to those spikes and washes
    out everything else. Percentile clipping is robust to that -- unlike
    mean+-std, a couple of extreme pixels can't drag the whole range with them.
    ``hi`` is the :data:`DIDV_HIGH_PERCENTILE` percentile of the finite,
    positive values; ``lo`` is a small negative fraction of ``hi`` (allows the
    noise floor to show as slightly-below-zero without devoting half the scale
    to negative values that aren't the interesting feature).
    """
    finite = grid[np.isfinite(grid)]
    if finite.size == 0:
        return (0.0, 1.0)
    positive = finite[finite > 0]
    hi = float(np.percentile(positive, DIDV_HIGH_PERCENTILE)) if positive.size else float(finite.max())
    if hi <= 0:
        hi = float(finite.max()) if finite.max() > 0 else 1.0
    lo = hi * DIDV_LOW_FRACTION
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


def compensate_series_resistance(grid: np.ndarray, bias_lo: float, bias_hi: float,
                                 r_series: float) -> np.ndarray:
    """Re-grid a raw-current map onto the voltage actually across the DUT.

    Each cell of ``grid`` (rows = gate/Sweep B, columns = the applied bias
    sweep spanning ``bias_lo..bias_hi`` uniformly) was measured with the
    applied voltage dropping over ``r_series`` (ohm) *plus* the device, so the
    device only saw ``V_qd = V_applied - I * r_series``. Per row, the currents
    are re-interpolated onto the original uniform bias axis interpreted as
    ``V_qd`` -- afterwards the column coordinate *is* the device voltage.
    Cells outside the compensated range (the sweep never reached that ``V_qd``)
    are NaN. Must be applied to the **raw current** grid, before any dI/dV.
    """
    grid = np.asarray(grid, dtype="f8")
    if r_series == 0.0 or grid.shape[1] < 2:
        return grid.copy()
    bias = np.linspace(bias_lo, bias_hi, grid.shape[1])
    out = np.full_like(grid, np.nan)
    for i, row in enumerate(grid):
        finite = np.isfinite(row)
        if finite.sum() < 2:
            continue
        v_qd = bias[finite] - row[finite] * r_series
        order = np.argsort(v_qd)
        out[i] = np.interp(bias, v_qd[order], row[finite][order],
                           left=np.nan, right=np.nan)
    return out


def set_image(image_view, grid: np.ndarray, *, transpose: bool = False,
              colormap: str | None = None, diverging: bool = False,
              levels: tuple[float, float] | None = None,
              extent: tuple[float, float, float, float] | None = None) -> None:
    """Show ``grid`` (possibly NaN) in a pyqtgraph ImageView.

    By default ``grid`` is displayed with axis-0 horizontal and axis-1 vertical.
    For a ``[gate, bias]`` diamond grid this puts **gate on x, bias on y** with
    no transpose. ``transpose=True`` swaps the axes. Unfilled cells render at the
    level minimum so the displayed array is all-finite.

    ``levels``, if given, is used as-is (e.g. from :func:`didv_levels`) --
    callers recompute it themselves rather than every redraw, so the color
    scale doesn't jitter as a run streams in. Without it, levels come from
    :func:`image_levels` (full min/max), made symmetric about zero when
    ``diverging`` (legacy behavior, still used for raw/non-dI/dV views).

    ``extent`` is ``(x_lo, x_hi, y_lo, y_hi)`` in *data* coordinates (the sweep
    voltages). Without it the image sits at pixel coordinates (0..nx, 0..ny),
    which do not line up with a view whose axes show sweep voltages -- so any
    caller that ranges its axes to the sweep extent must pass it.
    """
    import pyqtgraph as pg
    from pyqtgraph.Qt import QtCore

    arr = grid.T if transpose else grid
    if levels is not None:
        lo, hi = levels
    else:
        lo, hi = image_levels(arr)
        if diverging:
            m = max(abs(lo), abs(hi))
            lo, hi = -m, m
    display = np.where(np.isfinite(arr), arr, lo)
    image_view.setImage(display, levels=(lo, hi), autoLevels=False, autoRange=False)
    if extent is not None:
        x_lo, x_hi, y_lo, y_hi = extent
        image_view.imageItem.setRect(QtCore.QRectF(x_lo, y_lo, x_hi - x_lo, y_hi - y_lo))
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


def row_index_at(extent: tuple[float, float, float, float], nrows: int, y: float) -> int:
    """Row index of the displayed grid nearest data-coordinate ``y``.

    ``extent`` is the ``set_image`` extent ``(x_lo, x_hi, y_lo, y_hi)``; rows
    span ``y_lo..y_hi``. The result is clamped into ``[0, nrows-1]`` so a click
    slightly outside the image still picks the nearest edge row.
    """
    _, _, y_lo, y_hi = extent
    if nrows < 2 or y_hi == y_lo:
        return 0
    frac = (y - y_lo) / (y_hi - y_lo)
    return int(np.clip(round(frac * (nrows - 1)), 0, nrows - 1))


def row_cut(grid: np.ndarray, extent: tuple[float, float, float, float], iy: int
            ) -> tuple[np.ndarray, np.ndarray, float]:
    """Horizontal cut through a displayed grid: ``(x, values, y_value)``.

    ``x`` spans the extent's x-range with one entry per column; ``y_value`` is
    the data coordinate of row ``iy`` (for labelling the cut).
    """
    x_lo, x_hi, y_lo, y_hi = extent
    iy = int(np.clip(iy, 0, grid.shape[0] - 1))
    x = np.linspace(x_lo, x_hi, grid.shape[1])
    y_value = y_lo if grid.shape[0] < 2 else y_lo + iy * (y_hi - y_lo) / (grid.shape[0] - 1)
    return x, grid[iy], y_value


#: how many historical row-cut traces a line plot keeps before dropping the oldest
MAX_HISTORY_TRACES = 100

#: colormap for coloring successive row cuts; distinct from the image maps in
#: COLORMAPS so history traces don't blend into the 2D view
HISTORY_COLORMAP = "plasma"


def progression_color(fraction: float):
    """Color for a trace at ``fraction`` (0..1) through a progression.

    Used to color successive row cuts so their order (position along Sweep B)
    is visible at a glance.
    """
    import pyqtgraph as pg

    cmap = pg.colormap.get(HISTORY_COLORMAP)
    return cmap.map(float(np.clip(fraction, 0.0, 1.0)), mode="qcolor")


def image_click_coords(image_view, event) -> tuple[float, float] | None:
    """Data coordinates of a scene mouse click on ``image_view``, or None.

    Callers connect a *bound method* of their QWidget to
    ``image_view.view.scene().sigMouseClicked`` and map the event through this.
    (Do not connect a closure: a non-QObject receiver is never auto-disconnected
    and the resulting reference cycle segfaults in GC teardown.)
    """
    view_box = image_view.view.getViewBox()
    if not view_box.sceneBoundingRect().contains(event.scenePos()):
        return None
    point = view_box.mapSceneToView(event.scenePos())
    return point.x(), point.y()


# Quantities offered for the 2D view. dI/dV is the default for diamond plots.
QUANTITIES = ["dI/dV", "raw I"]


def make_image_2d_options(parent=None):
    """Build the shared 2D option bar (quantity, colormap, R_s compensation).

    Returns ``(widget, quantity_combo, colormap_combo, comp_check, r_series_spin)``.
    Callers connect the controls' change signals to their replot. The
    compensation checkbox defaults *off*; when on, callers re-grid the raw
    current with :func:`compensate_series_resistance` using the spinbox's ohms
    (prefilled from the run's source ``series_resistance`` setting).
    """
    from PyQt6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QWidget

    widget = QWidget(parent)
    row = QHBoxLayout(widget)
    row.setContentsMargins(0, 0, 0, 0)

    quantity = QComboBox()
    quantity.addItems(QUANTITIES)  # "dI/dV" is index 0 -> default
    colormap = QComboBox()
    colormap.addItems(COLORMAPS)   # "viridis" default
    comp = QCheckBox("compensate R_s")
    comp.setToolTip("Re-grid the bias axis to the voltage actually across the device:\n"
                    "V_QD = V_applied − I · R_series")
    r_series = QDoubleSpinBox()
    r_series.setRange(0.0, 1e12)
    r_series.setDecimals(1)
    r_series.setSuffix(" Ω")
    r_series.setToolTip("Total series resistance (line + instrument + anything extra in the circuit)")

    row.addWidget(QLabel("quantity:"))
    row.addWidget(quantity)
    row.addSpacing(12)
    row.addWidget(QLabel("colormap:"))
    row.addWidget(colormap)
    row.addSpacing(12)
    row.addWidget(comp)
    row.addWidget(r_series)
    row.addStretch(1)
    return widget, quantity, colormap, comp, r_series


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
