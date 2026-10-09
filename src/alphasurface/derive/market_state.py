"""Market-state metrics: stretch, vol context, and the regime flag.

Everything here is descriptive and shown with its own percentile (Principle 2). Inputs
are daily close series; vol figures are annualized percent, VIX units. Formulas:
docs/formulas.md sections 2, 4, 6, 7, 12.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252

REGIMES = ("low_vol", "normal", "elevated", "stress")
_LEVELS = (14.0, 20.0, 28.0)  # VIX bucket edges: low_vol / normal / elevated / stress


def percentile_rank(series: pd.Series, value: float) -> float:
    """Fraction of the series strictly below value. NaN if either side is empty."""
    s = series.dropna()
    if s.empty or pd.isna(value):
        return float("nan")
    return float((s < value).mean())


def rolling_vol(
    close: pd.Series, window: int = 21, periods_per_year: float = TRADING_DAYS
) -> pd.Series:
    """Rolling close-to-close realized vol, annualized percent. The app's one RV estimator."""
    logret = np.log(close / close.shift(1))
    return logret.rolling(window).std(ddof=1) * np.sqrt(periods_per_year) * 100


def sma_distance(close: pd.Series, n: int) -> pd.Series:
    """Percent distance of price from its n-day simple moving average."""
    return (close / close.rolling(n).mean() - 1) * 100


def drawdown(close: pd.Series, window: int = TRADING_DAYS) -> pd.Series:
    """Percent below the trailing window high. Zero at a new high, negative below it."""
    return (close / close.rolling(window, min_periods=1).max() - 1) * 100


def term_slope(vix: float, vix3m: float) -> float:
    """VIX3M / VIX - 1. Positive is contango (calm); negative, the front is bid (fear)."""
    return vix3m / vix - 1


def regime(vix: float, slope: float = float("nan"), vrp_now: float = float("nan")) -> str:
    """Regime flag from VIX level, escalated by backwardation and negative VRP.

    The VIX level picks the base bucket (edges 14 / 20 / 28). An inverted term structure
    (slope < 0) and realized vol running above implied (vrp < 0) each escalate one
    bucket, capped at stress. NaN inputs do not escalate.
    """
    if pd.isna(vix):
        raise ValueError("regime needs a VIX level")
    base = sum(vix >= lvl for lvl in _LEVELS)
    bump = int(slope < 0) + int(vrp_now < 0)
    return REGIMES[min(base + bump, len(REGIMES) - 1)]
