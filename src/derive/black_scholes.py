"""Black-Scholes-Merton option pricing and Greeks.

European options with continuous dividend yield q. Formulas: docs/formulas.md section 3.
Rates and vol are decimals (0.05 = 5%). Vega is per 1.00 of vol, theta per year, rho per
1.00 of rate; scale at the display layer.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.stats import norm


@dataclass(frozen=True)
class Greeks:
    price: float
    delta: float
    gamma: float
    vega: float
    theta: float
    rho: float


def _d1_d2(S: float, K: float, T: float, r: float, sigma: float, q: float) -> tuple[float, float]:
    v = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma**2) * T) / v
    return d1, d1 - v


def price(
    S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0, kind: str = "call"
) -> float:
    """Option price. kind is 'call' or 'put'."""
    if T <= 0 or sigma <= 0:  # degenerate: discounted intrinsic
        fwd = S * math.exp(-q * T) - K * math.exp(-r * T)
        return max(fwd, 0.0) if kind == "call" else max(-fwd, 0.0)
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    if kind == "call":
        return S * math.exp(-q * T) * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
    return K * math.exp(-r * T) * norm.cdf(-d2) - S * math.exp(-q * T) * norm.cdf(-d1)


def itm_probability(
    S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0, kind: str = "call"
) -> float:
    """Probability of expiring in the money: Phi(d2) for a call, Phi(-d2) for a put.

    Read it as P(S_T > K) and P(S_T < K). Pass implied vol and you get the market's own odds;
    pass realized vol and you get the odds under the historical distribution. The gap between
    the two is the variance risk premium. Risk-neutral, so it drifts at r - q, not at any
    expected return.
    """
    if T <= 0 or sigma <= 0:
        itm = (S > K) if kind == "call" else (S < K)
        return 1.0 if itm else 0.0
    _, d2 = _d1_d2(S, K, T, r, sigma, q)
    return float(norm.cdf(d2) if kind == "call" else norm.cdf(-d2))


def greeks(
    S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0, kind: str = "call"
) -> Greeks:
    p = price(S, K, T, r, sigma, q, kind)
    if T <= 0 or sigma <= 0:
        itm = (S > K) if kind == "call" else (S < K)
        delta = (1.0 if kind == "call" else -1.0) if itm else 0.0
        return Greeks(p, delta, 0.0, 0.0, 0.0, 0.0)

    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    dq, dr = math.exp(-q * T), math.exp(-r * T)
    pdf = norm.pdf(d1)
    gamma = dq * pdf / (S * sigma * math.sqrt(T))
    vega = S * dq * pdf * math.sqrt(T)
    theta_common = -S * dq * pdf * sigma / (2 * math.sqrt(T))
    if kind == "call":
        delta = dq * norm.cdf(d1)
        theta = theta_common - r * K * dr * norm.cdf(d2) + q * S * dq * norm.cdf(d1)
        rho = K * T * dr * norm.cdf(d2)
    else:
        delta = -dq * norm.cdf(-d1)
        theta = theta_common + r * K * dr * norm.cdf(-d2) - q * S * dq * norm.cdf(-d1)
        rho = -K * T * dr * norm.cdf(-d2)
    return Greeks(p, delta, gamma, vega, theta, rho)
