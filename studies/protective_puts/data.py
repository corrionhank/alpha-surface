"""Aligned daily inputs: SPY as the underlying, VIX as the implied-vol input, IRX as the rate.

There is no free 21-year history of actual SPX option prices, so the puts have to be modeled.
VIX supplies the vol, ^IRX (13-week bill) the discount rate, and both are real observations
rather than assumptions. What stays an assumption is skew, which engine.py handles explicitly.
"""

from __future__ import annotations

import pandas as pd

from config import load_config
from storage import reader, schema

SPOT, VOL, RATE = "SPY", "^VIX", "^IRX"
VOL_3M = "^VIX3M"  # 3-month implied vol. Only exists from 2006-07, so term-structure signals
# are simply off before then rather than guessed at.

SEED = (
    "python -m collector.yfinance_collector --interval 1d --period 25y "
    "--symbols 'SPY,^VIX,^IRX'"
)


def load(years: float = 21.0) -> pd.DataFrame:
    """Daily frame indexed by date: spot, vix, rate. Vol and rate are decimals, not points.

    Inner-joined on date, so every row can be priced. Holidays and the odd missing VIX print
    drop out rather than being carried forward into a fake quote.
    """
    config = load_config()
    conn = schema.connect(config, persistent=False)

    series = {}
    for symbol in (SPOT, VOL, RATE):
        df = reader.get_ohlcv(conn, symbol, "1d")
        if df.empty:
            raise SystemExit(f"No daily bars for {symbol}. Seed them first:\n  {SEED}")
        series[symbol] = df.set_index(df["ts"].dt.normalize())["close"]

    out = pd.DataFrame(
        {
            "spot": series[SPOT],
            "vix": series[VOL] / 100,  # quoted in vol points
            "rate": series[RATE] / 100,  # quoted in percent
        }
    ).dropna()

    # Left-joined, not inner: a missing VIX3M must not delete the first year of the study.
    df3m = reader.get_ohlcv(conn, VOL_3M, "1d")
    if not df3m.empty:
        out["vix3m"] = df3m.set_index(df3m["ts"].dt.normalize())["close"] / 100

    out["rate"] = out["rate"].clip(lower=0.0)  # the bill printed slightly negative in 2015 and 2020
    if years:
        out = out[out.index >= out.index[-1] - pd.DateOffset(years=int(years))]
    return out.sort_index()
