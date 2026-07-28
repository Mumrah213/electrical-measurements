"""Row-cut helpers used by the synchronized line-plot/2D-map panes."""

import numpy as np
import pytest

from emeas.gui.plotting import row_cut, row_index_at

EXTENT = (-10.0, 10.0, -2.2, -0.8)  # (x_lo, x_hi, y_lo, y_hi)


def test_row_index_at_maps_and_clamps():
    assert row_index_at(EXTENT, 141, -2.2) == 0
    assert row_index_at(EXTENT, 141, -0.8) == 140
    assert row_index_at(EXTENT, 141, -1.5) == 70
    # outside the extent clamps to the nearest edge row
    assert row_index_at(EXTENT, 141, -5.0) == 0
    assert row_index_at(EXTENT, 141, 3.0) == 140
    # degenerate grids don't divide by zero
    assert row_index_at(EXTENT, 1, -1.5) == 0
    assert row_index_at((-1, 1, 0, 0), 5, 0.3) == 0


def test_row_cut_returns_axis_and_row():
    grid = np.arange(12, dtype="f8").reshape(3, 4)  # rows = Sweep B
    x, values, y_value = row_cut(grid, (-10, 10, 0, 2), 1)
    assert x.tolist() == [-10.0, -10 + 20 / 3, -10 + 40 / 3, 10.0]
    assert values.tolist() == [4.0, 5.0, 6.0, 7.0]
    assert y_value == pytest.approx(1.0)
    # out-of-range row index clamps
    _, values, y_value = row_cut(grid, (-10, 10, 0, 2), 99)
    assert values.tolist() == [8.0, 9.0, 10.0, 11.0]
    assert y_value == pytest.approx(2.0)
