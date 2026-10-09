"""Implied volatility: invert Black-Scholes for sigma.

A live chain is full of prices that no volatility can produce: stale last trades, crossed markets,
quotes sitting below intrinsic. A solver that root-finds before checking the no-arbitrage bounds
will either not converge or, worse, converge on something quietly wrong. So the bounds come first,
and anything outside them returns NaN rather than a number that looks like an answer.

Price is strictly increasing in sigma, so once a price is inside the bounds a bracketed solve
cannot fail. Brent is used rather than Newton: vega collapses on deep wings, and Newton divides
by it.
"""

from __future__ import annotations

import math

from scipy.optimize import brentq

from alphasurface.derive.black_scholes import price

MIN_VOL, MAX_VOL = 1e-4, 5.0  # 0.01% to 500%. Outside this, the quote is not a volatility.


def bounds(S: float, K: float, T: float, r: float, q: float, kind: str) -> tuple[float, float]:
    """No-arbitrage price bounds. A quote outside these admits no implied volatility at all."""
    fwd, strike = S * math.exp(-q * T), K * math.exp(-r * T)
    if kind == "call":
        return max(fwd - strike, 0.0), fwd
    return max(strike - fwd, 0.0), strike


def implied_vol(
    target: float, S: float, K: float, T: float, r: float, q: float = 0.0, kind: str = "call"
) -> float:
    """Volatility implied by an option price, or NaN if the price admits none."""
    if not target > 0 or T <= 0 or S <= 0 or K <= 0:
        return math.nan

    low, high = bounds(S, K, T, r, q, kind)
    if target <= low + 1e-10 or target >= high - 1e-10:
        return math.nan  # at or beyond intrinsic: no volatility explains it

    def gap(sigma: float) -> float:
        return price(S, K, T, r, sigma, q, kind) - target

    if gap(MIN_VOL) > 0 or gap(MAX_VOL) < 0:
        return math.nan  # unreachable even at the extremes of the bracket
    try:
        return float(brentq(gap, MIN_VOL, MAX_VOL, xtol=1e-8, maxiter=100))
    except (ValueError, RuntimeError):
        return math.nan
