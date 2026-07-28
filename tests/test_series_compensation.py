"""Series-resistance compensation: V_QD = V_applied - I*R_s re-gridding."""

import numpy as np
import pytest

from emeas.gui.plotting import compensate_series_resistance


def test_linear_device_recovers_device_only_iv():
    """For an ohmic DUT, compensation must recover I = V_qd / R_dut exactly.

    Measured: I = V_applied / (R_s + R_dut). After re-gridding onto V_qd the
    same column voltage should read I = V / R_dut (interpolation is exact for
    a linear relation).
    """
    r_s, r_dut = 6.7e3, 20e3
    bias = np.linspace(-1.0, 1.0, 101)
    row = bias / (r_s + r_dut)
    grid = np.tile(row, (3, 1))  # a few identical gate rows

    out = compensate_series_resistance(grid, -1.0, 1.0, r_s)

    v_qd_span = 1.0 * r_dut / (r_s + r_dut)  # max |V_qd| actually reached
    inside = np.abs(bias) < v_qd_span - 1e-9
    assert np.allclose(out[0][inside], bias[inside] / r_dut)
    # columns beyond the reached V_qd range are NaN, not extrapolated
    assert np.isnan(out[0][np.abs(bias) > v_qd_span + 1e-9]).all()


def test_zero_resistance_is_identity_and_nan_rows_stay_nan():
    grid = np.array([[1.0, 2.0, 3.0], [np.nan, np.nan, np.nan]])
    out = compensate_series_resistance(grid, 0.0, 1.0, 0.0)
    assert np.array_equal(out[0], grid[0])
    out = compensate_series_resistance(grid, 0.0, 1.0, 100.0)
    assert np.isnan(out[1]).all()  # a row with <2 finite points stays empty


def test_partial_row_uses_only_finite_points():
    bias = np.linspace(0.0, 1.0, 11)
    row = bias.copy()  # I numerically equals V_applied; R_s=0.1 -> V_qd = 0.9*V
    row[7:] = np.nan   # streaming: row not finished yet
    grid = row[None, :]
    out = compensate_series_resistance(grid, 0.0, 1.0, 0.1)
    # V_qd of the last finite point = 0.9*0.6 = 0.54; columns above that are NaN
    finite = np.isfinite(out[0])
    assert finite[:6].all() and not finite[7:].any()
