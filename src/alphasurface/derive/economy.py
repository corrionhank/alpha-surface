"""Rates and macro series math: curve snapshots, spreads, changes. Pure, no I/O.

Yield series are percent levels indexed by date (Yahoo's ^IRX, ^FVX, ^TNX, ^TYX); macro series
are FRED observations indexed by date.
"""

from __future__ import annotations

import math

import pandas as pd


def value_on(series: pd.Series, when) -> float:
    """The last value at or before `when`, NaN when the series starts after it."""
    s = series.dropna()
    if s.empty:
        return math.nan
    s = s[pd.to_datetime(s.index) <= pd.Timestamp(when)]
    return float(s.iloc[-1]) if len(s) else math.nan


def curve_at(yields: dict[str, pd.Series], when) -> dict[str, float]:
    """Each tenor's yield as of a date."""
    return {tenor: value_on(s, when) for tenor, s in yields.items()}


def spread(long: pd.Series, short: pd.Series) -> pd.Series:
    """long minus short on the dates both have, in percentage points."""
    both = pd.concat([long, short], axis=1, join="inner").dropna()
    return (both.iloc[:, 0] - both.iloc[:, 1]).rename("spread")


def change_bp(series: pd.Series, days: int) -> float:
    """Change in basis points over the last `days` calendar days."""
    s = series.dropna()
    if s.empty:
        return math.nan
    end = pd.Timestamp(pd.to_datetime(s.index).max())
    return (float(s.iloc[-1]) - value_on(s, end - pd.Timedelta(days=days))) * 100


def yoy(series: pd.Series, periods: int = 12) -> pd.Series:
    """Percent change against the observation `periods` back (12 for monthly index levels)."""
    s = series.dropna()
    return (s / s.shift(periods) - 1) * 100
