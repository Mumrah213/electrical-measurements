"""Post-processing for measured sweeps and maps.

Plain functions over pandas DataFrames -- the columns are whatever the
measurement produced (set_voltage plus one column per meter). Nothing here
knows about instruments; you hand it the DataFrame a sweep returned and get a
DataFrame back.

    df = linear_sweep(Y1, HP1, -1, 1, 201)
    clean = butter_filter(df)          # smooth
    didv  = diff(clean)                # numerical derivative

For a 2D map, pivot to an image first (rows = one sweep each) and pass that; the
filters run down each column, i.e. along the fast (bias) axis.
"""

import numpy as np
import pandas as pd
from scipy.signal import butter, filtfilt


def diff(df, rolling_mean=5):
    """Numerical derivative of every column, after a rolling-mean smooth.

    Returns a DataFrame the same width as ``df`` with the leading NaN rows (from
    the rolling window and the diff) dropped. This is the dI/dV-style transform
    the old analysis used, minus the no-op filter call it used to carry.
    """
    out = df.rolling(rolling_mean).mean()
    out = out.diff()
    out = out.dropna()
    return out


def remove_noise(df, cutoff=10):
    """Replace lone spikes with the mean of their neighbours.

    A point is a spike when it exceeds *both* neighbours by more than ``cutoff``
    times; it's overwritten with ``(prev + next) / 2``. Runs per column and
    skips the first/last row (no neighbour). Zero-valued neighbours are left
    alone rather than dividing by them.
    """
    out = df.copy()
    for col in out.columns:
        vals = out[col].to_numpy(dtype=float)
        for i in range(1, len(vals) - 1):
            prev, curr, nxt = vals[i - 1], vals[i], vals[i + 1]
            if prev == 0 or nxt == 0:
                continue
            if abs(curr / prev) > cutoff and abs(curr / nxt) > cutoff:
                out.iloc[i, out.columns.get_loc(col)] = (prev + nxt) / 2
    return out


def butter_filter(df, order=1, cutoff=0.2):
    """Zero-phase low-pass (Butterworth + filtfilt) down each column.

    ``cutoff`` is the normalised frequency (0 < cutoff < 1, i.e. fraction of
    Nyquist), matching scipy's convention. filtfilt keeps the result in phase,
    so peak positions don't shift. Returns a DataFrame with the original index
    and columns.
    """
    b, a = butter(order, cutoff)
    filtered = filtfilt(b, a, df.to_numpy(), axis=0)
    return pd.DataFrame(filtered, index=df.index, columns=df.columns)
