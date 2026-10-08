"""Fear and greed, as our own lens on stored daily data. Not CNN's index and not a verdict.

Six components, each read as a percentile of its own history up to that day (expanding, so no
look-ahead), oriented so that a high score means greed, then averaged with equal weight:

  VIX vs its 50-day average      high VIX against its own trend is fear       (inverted)
  SPY vs its 125-day average     price above its half-year trend is greed
  VIX term structure, VIX3M/VIX  contango is calm, backwardation is fear
  Safe-haven demand              SPY minus TLT 20-day return; stocks over bonds is greed
  Junk-bond demand               HYG minus IEF 20-day return; credit over Treasuries is greed
  Realized vol                   SPY 21-day realized vol; high is fear         (inverted)

A component with too little history is left out and the rest are averaged. Bands: below 25
extreme fear, 25 to 45 fear, 45 to 55 neutral, 55 to 75 greed, 75 and up extreme greed.
docs/dashboard.md.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from derive.market_state import rolling_vol

BANDS = ((25, "extreme fear"), (45, "fear"), (55, "neutral"), (75, "greed"), (101, "extreme greed"))
MIN_HISTORY = 252


@dataclass
class FearGreed:
    score: float
    label: str
    components: pd.DataFrame  # name, reads, value, score
    history: pd.Series  # daily score, PIT


def label(score: float) -> str:
    if score != score:
        return "n/a"
    return next(name for edge, name in BANDS if score < edge)


def expanding_score(series: pd.Series, invert: bool = False, min_history: int = MIN_HISTORY) -> pd.Series:
    """0 to 100: where each day sits within the series' history up to and including that day."""
    s = series.dropna()
    pct = s.expanding(min_periods=min_history).rank(pct=True) * 100
    return 100 - pct if invert else pct


def components(spy: pd.Series, vix: pd.Series, vix3m: pd.Series, tlt: pd.Series,
               hyg: pd.Series, ief: pd.Series) -> dict[str, tuple[str, pd.Series, bool]]:
    """name -> (what it reads, raw value series, inverted). Inputs are daily closes by date."""
    out = {
        "VIX vs 50-day": ("VIX over its 50-day average, minus 1", vix / vix.rolling(50).mean() - 1, True),
        "SPY vs 125-day": ("SPY over its 125-day average, minus 1", spy / spy.rolling(125).mean() - 1, False),
        "Term structure": ("VIX3M over VIX", (vix3m / vix).dropna(), False),
        "Safe-haven demand": ("SPY minus TLT, 20-day return",
                              (spy.pct_change(20) - tlt.pct_change(20)).dropna(), False),
        "Junk-bond demand": ("HYG minus IEF, 20-day return",
                             (hyg.pct_change(20) - ief.pct_change(20)).dropna(), False),
        "Realized vol": ("SPY 21-day realized vol, %", rolling_vol(spy), True),
    }
    return {k: v for k, v in out.items() if v[1].dropna().size > 0}


def fear_greed(spy, vix, vix3m, tlt, hyg, ief, min_history: int = MIN_HISTORY) -> FearGreed:
    parts = components(spy, vix, vix3m, tlt, hyg, ief)
    scores, rows = {}, []
    for name, (reads, raw, invert) in parts.items():
        sc = expanding_score(raw, invert, min_history)
        if sc.dropna().empty:
            continue
        scores[name] = sc
        rows.append({"name": name, "reads": reads, "value": float(raw.dropna().iloc[-1]),
                     "score": float(sc.dropna().iloc[-1]), "inverted": invert})
    if not scores:
        return FearGreed(float("nan"), "n/a", pd.DataFrame(rows), pd.Series(dtype=float))
    # Each day's score averages whichever components have a reading that day.
    history = pd.concat(scores, axis=1).sort_index().ffill(limit=3).mean(axis=1, skipna=True).dropna()
    table = pd.DataFrame(rows)
    score = float(np.mean(table["score"]))
    return FearGreed(score, label(score), table, history)
