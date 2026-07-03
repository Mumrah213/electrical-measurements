"""Pure-helper tests for emeas.gui.plotting (no Qt needed)."""

import numpy as np
import pytest

from emeas.gui import plotting


def test_rolling_average_passthrough():
    y = np.array([1.0, 2.0, 3.0])
    assert plotting.rolling_average(y, 1).tolist() == y.tolist()
    assert plotting.rolling_average(np.array([]), 5).tolist() == []


def test_rolling_average_centered_mean():
    y = np.array([0.0, 0.0, 9.0, 0.0, 0.0])
    out = plotting.rolling_average(y, 3)
    # window of 3, normalised by actual count at edges
    assert out[2] == pytest.approx(3.0)        # (0+9+0)/3
    assert len(out) == len(y)


def test_rolling_average_window_clamped_to_length():
    # window larger than the array is clamped; centered 'same' convolution uses
    # a shrinking window at the edges (normalised by actual sample count).
    y = np.array([2.0, 4.0])
    out = plotting.rolling_average(y, 10)
    assert len(out) == 2
    assert out.tolist() == pytest.approx([2.0, 3.0])


def test_grid_from_long_places_values_and_nans():
    grid = plotting.grid_from_long([0, 1, 2], [0, 0, 1], [10, 20, 30], nx=3, ny=2)
    assert grid.shape == (2, 3)
    assert grid[0, 0] == 10 and grid[0, 1] == 20 and grid[1, 2] == 30
    assert np.isnan(grid[1, 0])  # unfilled


def test_grid_from_long_ignores_out_of_range():
    grid = plotting.grid_from_long([5], [5], [99], nx=2, ny=2)
    assert np.isnan(grid).all()


def test_image_levels():
    assert plotting.image_levels(np.array([[np.nan, np.nan]])) == (0.0, 1.0)
    lo, hi = plotting.image_levels(np.array([[3.0, np.nan]]))
    assert lo == 3.0 and hi > lo  # single value -> non-degenerate range
    assert plotting.image_levels(np.array([[1.0, 5.0]])) == (1.0, 5.0)


def test_differentiate_bias_along_columns():
    # grid is [gate, bias]; a linear ramp in bias -> constant derivative
    grid = np.array([[0.0, 1.0, 2.0, 3.0]])  # 1 gate row, 4 bias cols
    d = plotting.differentiate_bias(grid, bias_axis=3.0)  # span 3 over 4 pts -> spacing 1
    assert d.shape == grid.shape
    assert np.allclose(d, 1.0)  # d(value)/d(bias) = 1


def test_differentiate_bias_preserves_nan_and_short_grids():
    grid = np.array([[0.0, np.nan, 2.0]])
    d = plotting.differentiate_bias(grid, bias_axis=2.0)
    assert np.isnan(d[0, 1])
    # single bias column -> can't differentiate, returns a copy
    one = np.array([[5.0], [6.0]])
    assert plotting.differentiate_bias(one).shape == one.shape


def test_diamond_grid_raw_vs_didv():
    data = {
        "ix": [0, 1, 2, 0, 1, 2],   # bias index
        "iy": [0, 0, 0, 1, 1, 1],   # gate index
        "G":  [0.0, 1.0, 2.0, 0.0, 2.0, 4.0],
    }
    raw = plotting.diamond_grid(data, "G", nx=3, ny=2, quantity="raw I")
    assert raw.shape == (2, 3)            # [gate, bias]
    assert raw[1, 2] == 4.0
    didv = plotting.diamond_grid(data, "G", nx=3, ny=2, quantity="dI/dV", bias_span=2.0)
    # gate row 1 ramps 0,2,4 over bias span 2 (spacing 1) -> derivative 2
    assert np.allclose(didv[1], 2.0)


def test_quantity_default_is_didv():
    assert plotting.QUANTITIES[0] == "dI/dV"
    assert plotting.COLORMAPS[0] == "viridis"
