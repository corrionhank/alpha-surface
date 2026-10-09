"""The forward implied by an expiry's own quotes, and Black-76 on it.

Put-call parity, C - P = e^(-rT) (F - K), holds for European options whatever the dividends,
borrow or rate assumptions, so solving it at the strikes nearest the money gives the forward the
market is actually pricing. Implied vol taken from Black-76 on that forward and discounted at
e^(-rT) then needs no spot, no dividend yield and barely any rate: an error in r moves calls and
puts the same way and cancels in the smile, where a spot-based Black-Scholes with the wrong
dividend splits the put and call wings at the money.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy.stats import norm

from alphasurface.derive.black_scholes import price
from alphasurface.derive.implied_vol import implied_vol


def two_sided(frame: pd.DataFrame) -> pd.Series:
    """A real market: a positive bid and an ask above it."""
    return (frame["bid"] > 0) & (frame["ask"] > frame["bid"])


def parity_forward(board: pd.DataFrame, rate: float, tenor: float, n: int = 5) -> float:
    """F = K + e^(rT) (C - P), the median over the `n` strikes nearest the money where both the
    call and the put have two-sided quotes. `board` is one expiry: strike, kind, bid, ask.
    NaN when no strike has both sides quoted."""
    quoted = board[two_sided(board)]
    if quoted.empty:
        return math.nan
    mids = quoted.assign(mid=(quoted["bid"] + quoted["ask"]) / 2).pivot_table(
        index="strike", columns="kind", values="mid", aggfunc="first"
    )
    if not {"call", "put"} <= set(mids.columns):
        return math.nan
    pairs = mids.dropna(subset=["call", "put"])
    if pairs.empty:
        return math.nan
    # Nearest the money is where calls and puts are worth the same, so rank by |C - P|.
    near = pairs.assign(gap=(pairs["call"] - pairs["put"]).abs()).nsmallest(n, "gap")
    implied = near.index.to_numpy(float) + math.exp(rate * tenor) * (near["call"] - near["put"])
    return float(np.median(implied))


def black76_price(F: float, K: float, T: float, r: float, sigma: float, kind: str) -> float:
    """e^(-rT) [F N(d1) - K N(d2)] for a call; Black-Scholes with the carry equal to the rate."""
    return price(F, K, T, r, sigma, r, kind)


def black76_iv(target: float, F: float, K: float, T: float, r: float, kind: str) -> float:
    """Black-76 implied vol of an option price on forward F, NaN when the price admits none."""
    return implied_vol(target, F, K, T, r, r, kind)


def forward_delta(F: float, K: float, T: float, sigma: float, kind: str) -> float:
    """Undiscounted delta against the forward: N(d1) for a call, N(d1) - 1 for a put. The
    convention surfaces are quoted in (25-delta, 10-delta)."""
    if not (F > 0 and K > 0 and T > 0 and sigma > 0):
        return math.nan
    d1 = (math.log(F / K) + 0.5 * sigma * sigma * T) / (sigma * math.sqrt(T))
    return float(norm.cdf(d1)) if kind == "call" else float(norm.cdf(d1) - 1.0)
