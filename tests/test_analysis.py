import numpy as np
import pandas as pd
import pytest

from emeas import butter_filter, diff, remove_noise


def test_diff_smooths_and_shortens():
    df = pd.DataFrame({"a": np.arange(20, dtype=float)})
    out = diff(df, rolling_mean=5)
    # rolling(5) + diff() drop 5 leading rows
    assert len(out) == len(df) - 5
    # derivative of a linear ramp is a constant 1
    assert out["a"].to_numpy() == pytest.approx(np.ones(len(out)))


def test_remove_noise_replaces_spike():
    df = pd.DataFrame({"a": [1.0, 1.0, 100.0, 1.0, 1.0]})
    out = remove_noise(df, cutoff=10)
    # the spike is the mean of its neighbours (both 1.0)
    assert out["a"].iloc[2] == pytest.approx(1.0)
    # untouched points stay put
    assert out["a"].iloc[0] == 1.0 and out["a"].iloc[-1] == 1.0


def test_remove_noise_leaves_clean_signal():
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0]})
    out = remove_noise(df, cutoff=10)
    assert out["a"].tolist() == df["a"].tolist()


def test_remove_noise_survives_zero_neighbour():
    # a zero neighbour must not raise ZeroDivisionError
    df = pd.DataFrame({"a": [0.0, 5.0, 0.0]})
    out = remove_noise(df, cutoff=2)
    assert out["a"].iloc[1] == 5.0


def test_butter_filter_shape_and_phase():
    n = 200
    t = np.linspace(0, 1, n)
    clean = np.sin(2 * np.pi * 2 * t)
    noisy = clean + 0.5 * np.random.default_rng(0).standard_normal(n)
    df = pd.DataFrame({"sig": noisy})
    out = butter_filter(df, order=1, cutoff=0.2)
    assert out.shape == df.shape
    assert list(out.columns) == ["sig"]
    # filtered signal is closer to the clean signal than the noisy input
    assert np.mean((out["sig"] - clean) ** 2) < np.mean((noisy - clean) ** 2)
