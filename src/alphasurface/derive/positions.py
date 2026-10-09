"""Multi-leg positions valued across many prices at once, and the delta-hedged option.

derive.black_scholes prices one contract at a time; here the same formulas run over whole arrays
of spot, so a position can be marked on every simulated path in one call. Time is in trading
days, 252 a year, the same clock the simulator steps on, so a tenor and a path line up exactly.

Quantities are contracts, positive long and negative short. A stock leg is a 100-share lot so
it sits on the same multiplier as an option. Values are in dollars per position.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import norm

MULT = 100
TRADING_DAYS = 252
KINDS = ("call", "put", "stock")


@dataclass(frozen=True)
class Leg:
    kind: str  # call | put | stock
    strike: float  # ignored for stock
    qty: float  # contracts or 100-share lots; negative is short


def bs_price(S, K: float, T, r: float, sigma, q: float, kind: str) -> np.ndarray:
    """Black-Scholes over arrays. T in years; T <= 0 returns intrinsic."""
    S, T, sigma = np.asarray(S, float), np.asarray(T, float), np.asarray(sigma, float)
    live = (T > 0) & (sigma > 0)
    Ts, vs = np.where(live, T, 1.0), np.where(live, sigma, 1.0)
    d1 = (np.log(S / K) + (r - q + 0.5 * vs**2) * Ts) / (vs * np.sqrt(Ts))
    d2 = d1 - vs * np.sqrt(Ts)
    if kind == "call":
        price = S * np.exp(-q * Ts) * norm.cdf(d1) - K * np.exp(-r * Ts) * norm.cdf(d2)
        intrinsic = np.maximum(S - K, 0.0)
    else:
        price = K * np.exp(-r * Ts) * norm.cdf(-d2) - S * np.exp(-q * Ts) * norm.cdf(-d1)
        intrinsic = np.maximum(K - S, 0.0)
    return np.where(live, price, intrinsic)


def bs_delta(S, K: float, T, r: float, sigma: float, q: float, kind: str) -> np.ndarray:
    S, T = np.asarray(S, float), np.asarray(T, float)
    live = T > 0
    Ts = np.where(live, T, 1.0)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * Ts) / (sigma * np.sqrt(Ts))
    if kind == "call":
        return np.where(live, np.exp(-q * Ts) * norm.cdf(d1), (S > K).astype(float))
    return np.where(live, -np.exp(-q * Ts) * norm.cdf(-d1), -(S < K).astype(float))


def value(legs: list[Leg], S, days_left: float, r: float, sigma, q: float) -> np.ndarray:
    """Dollar value of the position at spot S with days_left trading days to expiry."""
    S = np.asarray(S, float)
    T = days_left / TRADING_DAYS
    total = np.zeros_like(S)
    for leg in legs:
        unit = S if leg.kind == "stock" else bs_price(S, leg.strike, T, r, sigma, q, leg.kind)
        total = total + leg.qty * MULT * unit
    return total


def pnl(
    legs: list[Leg],
    S0: float,
    S_h,
    dte: int,
    horizon: int,
    r: float,
    iv_entry: float,
    iv_exit,
    q: float,
) -> np.ndarray:
    """P&L of opening at S0 with dte days left and marking at S_h after horizon days.

    Entry is priced at iv_entry; the exit mark uses iv_exit (scalar or one per outcome), which
    is how a vol shock reaches the position. Cash paid at entry is not carried at interest.
    """
    entry = value(legs, np.array([S0]), dte, r, iv_entry, q)[0]
    return value(legs, S_h, dte - horizon, r, iv_exit, q) - entry


def premium(legs: list[Leg], S0: float, dte: int, r: float, iv: float, q: float) -> float:
    """Net cost to open the option legs. Negative is a credit received."""
    opts = [leg for leg in legs if leg.kind != "stock"]
    return float(value(opts, np.array([S0]), dte, r, iv, q)[0]) if opts else 0.0


def strike_step(spot: float) -> float:
    return 5.0 if spot >= 200 else 1.0 if spot >= 25 else 0.5


def presets(spot: float, width: float = 0.05) -> dict[str, list[Leg]]:
    """Common structures around spot. width is the OTM distance as a fraction of spot."""
    step = strike_step(spot)

    def k(m: float) -> float:
        return round(spot * m / step) * step

    atm, up, dn, up2, dn2 = k(1), k(1 + width), k(1 - width), k(1 + 2 * width), k(1 - 2 * width)
    return {
        "Long call": [Leg("call", atm, 1)],
        "Long put": [Leg("put", atm, 1)],
        "Short put": [Leg("put", dn, -1)],
        "Covered call": [Leg("stock", 0, 1), Leg("call", up, -1)],
        "Protective put": [Leg("stock", 0, 1), Leg("put", dn, 1)],
        "Bull call spread": [Leg("call", atm, 1), Leg("call", up, -1)],
        "Bear put spread": [Leg("put", atm, 1), Leg("put", dn, -1)],
        "Long straddle": [Leg("call", atm, 1), Leg("put", atm, 1)],
        "Short strangle": [Leg("call", up, -1), Leg("put", dn, -1)],
        "Iron condor": [
            Leg("put", dn2, 1),
            Leg("put", dn, -1),
            Leg("call", up, -1),
            Leg("call", up2, 1),
        ],
        "Long stock": [Leg("stock", 0, 1)],
    }


def delta_hedged_pnl(
    paths: np.ndarray,
    strike: float,
    r: float,
    iv: float,
    q: float,
    kind: str,
    side: int,
    hedge_every: int = 1,
) -> np.ndarray:
    """P&L per share of one option bought (side=1) or sold (side=-1) at iv and delta-hedged.

    The hedge is rebalanced every hedge_every steps to the Black-Scholes delta at iv, the vol
    the trade was struck at; hedge_every=0 leaves the option naked, for comparison. The option expires at the last column of paths. Each hedge holding
    earns its price change less carry, and everything is compounded to expiry. With realized
    vol equal to iv the mean P&L is zero: a fair bet. The sign and size of the mean then follow
    the gap between implied and realized, roughly half of gamma times S squared times
    (iv squared minus realized squared), summed over the life of the trade.
    """
    m = paths.shape[1] - 1
    dt = 1 / TRADING_DAYS
    t = np.arange(m) * dt
    T = m * dt
    tau = T - t

    delta = bs_delta(paths[:, :-1], strike, tau, r, iv, q, kind)
    if hedge_every <= 0:
        delta = np.zeros_like(delta)
    elif hedge_every > 1:  # hold each hedge until the next rebalance date
        held = (np.arange(m) // hedge_every) * hedge_every
        delta = delta[:, held]
    hedge = -side * delta
    S0, S1 = paths[:, :-1], paths[:, 1:]
    carry = S0 * (math.exp((r - q) * dt) - 1)
    grow = np.exp(r * (T - t - dt))
    hedge_pnl = (hedge * (S1 - S0 - carry) * grow).sum(axis=1)

    entry = float(bs_price(paths[0, 0], strike, T, r, iv, q, kind))
    payoff = (
        np.maximum(paths[:, -1] - strike, 0)
        if kind == "call"
        else np.maximum(strike - paths[:, -1], 0)
    )
    return side * (payoff - entry * math.exp(r * T)) + hedge_pnl
