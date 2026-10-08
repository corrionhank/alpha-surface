"""Descriptive stats for an ohlcv window: last, change, high/low, realized vol."""

from __future__ import annotations

import pandas as pd

from derive.market_state import rolling_vol

# 1h RTH bars per year: 6.5 trading hours * 252 sessions.
_BARS_PER_YEAR = {"1h": 6.5 * 252, "1d": 252.0}


def realized_vol(close: pd.Series, interval: str) -> float:
    """Annualized close-to-close volatility in percent, or NaN if too few bars."""
    if len(close) < 3:
        return float("nan")
    ann = _BARS_PER_YEAR.get(interval, 252.0)
    return float(rolling_vol(close, window=len(close) - 1, periods_per_year=ann).iloc[-1])


def summarize(df: pd.DataFrame) -> dict:
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
