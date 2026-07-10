"""Basic display stats for an ohlcv window.

These are plain descriptive numbers (last price, change, high/low, realized vol)
— context, not signals (Principle 2). Realized vol here is close-to-close, from
the bars in the window; it is historical, never a forecast. The real vol metrics
(IVR/IVP/VRP/regime) belong to the derive layer once options data flows.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Approx 1h RTH bars per year: 6.5 trading hours × 252 sessions.
_BARS_PER_YEAR = {"1h": 6.5 * 252, "1d": 252.0}


def realized_vol(close: pd.Series, interval: str) -> float:
    """Annualized close-to-close realized volatility (%), or NaN if too few bars."""
    logret = np.log(close / close.shift(1)).dropna()
    if len(logret) < 2:
        return float("nan")
    ann = np.sqrt(_BARS_PER_YEAR.get(interval, 252.0))
    return float(logret.std(ddof=1) * ann * 100)


def summarize(df: pd.DataFrame) -> dict:
    """One-row summary of an ohlcv frame ordered oldest→newest."""
    if df is None or df.empty:
        return {}

    close = df["close"]
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else last
    first = float(close.iloc[0])

    return {
        "symbol": df["symbol"].iloc[-1],
        "interval": df["interval"].iloc[-1],
        "bars": int(len(df)),
        "last": last,
        "change_abs": last - prev,
        "change_pct": (last / prev - 1) * 100 if prev else float("nan"),
        "window_change_pct": (last / first - 1) * 100 if first else float("nan"),
        "high": float(df["high"].max()),
        "low": float(df["low"].min()),
        "rv_annualized_pct": realized_vol(close, df["interval"].iloc[-1]),
        "first_ts": df["ts"].iloc[0],
        "last_ts": df["ts"].iloc[-1],
    }
