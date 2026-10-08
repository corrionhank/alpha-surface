"""The implied vol panel: index levels with day, week and month changes, the VIX term curve, and
what today's move is priced at. Changes are in index points over 1, 5 and 21 sessions; the
percentile is of today's level within the last 252 sessions. docs/dashboard.md.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from derive.market_state import percentile_rank, rolling_vol

WINDOWS = {"1d": 1, "1w": 5, "1m": 21}

# The VIX term curve: label, stored symbol, tenor in calendar days.
TERM = [("VIX1D", "^VIX1D", 1), ("VIX9D", "^VIX9D", 9), ("VIX", "^VIX", 30),
        ("VIX3M", "^VIX3M", 93), ("VIX6M", "^VIX6M", 186)]


def changes(series: pd.Series) -> dict[str, float]:
    """Level, point changes over 1/5/21 sessions, and the 1y percentile of the level."""
    s = series.dropna()
    if s.empty:
        return {"level": math.nan, **{k: math.nan for k in WINDOWS}, "pct_1y": math.nan}
    last = float(s.iloc[-1])
    out = {"level": last}
    for key, n in WINDOWS.items():
        out[key] = last - float(s.iloc[-1 - n]) if len(s) > n else math.nan
    out["pct_1y"] = percentile_rank(s.tail(252), last)
    return out


def panel(series: dict[str, pd.Series]) -> pd.DataFrame:
    """One row per index name, columns level, 1d, 1w, 1m, pct_1y. Empty series are skipped."""
    rows = {name: changes(s) for name, s in series.items() if s.dropna().size}
    return pd.DataFrame(rows).T


def iv_minus_rv(iv: pd.Series, close: pd.Series, window: int = 21) -> pd.Series:
    """Implied (index points) minus trailing close-to-close realized vol, on dates both have."""
    both = pd.concat({"iv": iv, "rv": rolling_vol(close, window)}, axis=1).dropna()
    return both["iv"] - both["rv"]


def term_curve(series: dict[str, pd.Series], lags: dict[str, int] | None = None) -> pd.DataFrame:
    """The curve today and a week and a month ago, on the last date every tenor printed.

    series maps stored symbol -> closes. Rows are tenors (label, days), columns the lags.
    """
    lags = lags or {"Today": 0, "A week ago": 5, "A month ago": 21}
    have = [(lab, sym, d) for lab, sym, d in TERM if sym in series and series[sym].dropna().size]
    if not have:
        return pd.DataFrame()
    frame = pd.concat({lab: series[sym] for lab, sym, _ in have}, axis=1).dropna()
    out = pd.DataFrame(index=[lab for lab, _, _ in have])
    out["days"] = [d for _, _, d in have]
    for name, lag in lags.items():
        out[name] = frame.iloc[-1 - lag].to_numpy() if len(frame) > lag else np.nan
    out.attrs["asof"] = frame.index[-1] if len(frame) else None
    return out


def priced_move_today(vix1d: pd.Series, vix: pd.Series) -> tuple[float, str]:
    """One-day 1 SD move in percent: VIX1D / sqrt(252) when stored, VIX / sqrt(252) otherwise."""
    for s, name in ((vix1d, "VIX1D"), (vix, "VIX")):
        s = s.dropna()
        if len(s):
            return float(s.iloc[-1]) / math.sqrt(252), name
    return math.nan, ""
