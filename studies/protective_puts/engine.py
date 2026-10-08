"""The backtest.

Mechanics. The portfolio is always fully invested. At each roll it buys h units of the package
"one share plus one put on that share", so h = V / (S + premium). Paying for the put by selling
shares the put is meant to cover is circular; pricing the package dissolves it, and the book
stays exactly 100% hedged with no cash sleeve to explain away.

The put is marked to model every day against the live VIX, so the equity curve and its drawdowns
are what the hedged book would actually print, not just what it settles at on expiry.

Dividends. Stored closes are raw prices, which is correct for strikes and payoffs but omits the
~1.8%/yr SPY pays out. So a continuous yield is credited to the share leg and fed to the pricer,
where it correctly makes puts dearer.

The one real assumption is skew, and it is load-bearing. VIX is roughly at-the-money vol, but an
OTM put is the most bid-up contract on the board and trades several vol points above it. Pricing
protection at flat VIX undercharges the exact thing being bought. skew_slope is vol points per 1%
out of the money: at 0.5, a 5%-OTM put is priced 2.5 vol points over VIX. Sweep it, never trust
a single value.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from studies.protective_puts.bsm import put_price

TRADING_DAYS = 252
VIX_TENOR = 30 / 365  # VIX is a 30-day number, and that matters once you roll anything else

# Defaults are the realistic ones, not the flattering ones. Pricing a 1-year put at 30-day VIX
# undercharges it and hands every slow-rolling strategy a subsidy, so the term premium is on by
# default and a caller has to opt out of paying it. Same for skew on OTM strikes.
SKEW_SLOPE = 0.5  # vol points per 1% out of the money
TERM_PREMIUM = 0.025  # vol points added at a one-year tenor

# Trading days per roll. A "monthly" put is the 21-session cycle, not a calendar month.
ROLLS = {"monthly": 21, "quarterly": 63, "annual": 252}


@dataclass(frozen=True)
class Strategy:
    name: str
    moneyness: float = 0.05  # 0.05 buys a strike 5% below spot; 0.0 is at the money
    roll_days: int = 21
    hedged: bool = True
    short_moneyness: float | None = None  # sell a deeper put against it: a put spread

    def __post_init__(self):
        if self.short_moneyness is not None and self.short_moneyness <= self.moneyness:
            raise ValueError("the short leg must be further out of the money than the long leg")


@dataclass(frozen=True)
class Result:
    name: str
    equity: pd.Series
    premium_paid: pd.Series  # cash out on each roll
    payoff_received: pd.Series  # intrinsic collected at each expiry
    cycles: int = 0  # roll cycles in the run
    hedged_cycles: int = 0  # of which actually carried a put

    @property
    def duty_cycle(self) -> float:
        """Share of roll cycles that were hedged. 1.0 is always on, 0.0 is buy and hold."""
        return self.hedged_cycles / self.cycles if self.cycles else 0.0

    @property
    def total_premium(self) -> float:
        return float(self.premium_paid.sum())

    @property
    def total_payoff(self) -> float:
        return float(self.payoff_received.sum())

    @property
    def recovery(self) -> float:
        """Share of premium spent that came back as payoff. 1.0 would mean the hedge paid for itself."""
        return self.total_payoff / self.total_premium if self.total_premium else float("nan")


def implied_vol(
    vix: np.ndarray | float,
    moneyness: float,
    skew_slope: float,
    tenor: np.ndarray | float = VIX_TENOR,
    term_premium: float = 0.0,
):
    """VIX plus the two corrections that stand between a 30-day ATM index and the put being bought.

    skew_slope: vol points per 1% OTM, so 0.5 * 0.05 = +2.5 points on a 5% OTM put.

    term_premium: vol points to add at a one-year tenor, scaled in sqrt(time). VIX measures
    30-day vol, but the SPX term structure normally slopes up, so pricing a one-year put at VIX
    undercharges it and flatters any strategy that rolls slowly. Scaled so a 30-day option is
    unaffected. Zero reproduces flat VIX across every tenor.
    """
    scale = (np.sqrt(tenor) - np.sqrt(VIX_TENOR)) / (1 - np.sqrt(VIX_TENOR))
    vol = vix + skew_slope * moneyness + term_premium * scale
    return np.maximum(vol, 0.01)


def run_vol_target(
    data: pd.DataFrame,
    name: str = "Vol target 12%",
    target: float = 0.12,
    lookback: int = 21,
    max_exposure: float = 1.5,
    dividend_yield: float = 0.018,
    capital: float = 10_000.0,
) -> Result:
    """Manage risk by owning less of the thing, instead of insuring it.

    Exposure = target vol / trailing realized vol, capped. Volatility clusters, so yesterday's
    vol forecasts today's, which is what makes this work at all. The cash sleeve earns the bill
    rate. No options, no premium, no skew assumption to get wrong: the control that any option
    hedge has to beat before it is worth the complexity.
    """
    ret = data["spot"].pct_change().fillna(0.0)
    realized = ret.rolling(lookback).std() * np.sqrt(TRADING_DAYS)
    # Shift: today's position can only use vol measured through yesterday.
    exposure = (target / realized).shift(1).clip(upper=max_exposure).fillna(1.0)
    return run_exposure(data, exposure.to_numpy(), name, dividend_yield, capital)


def run_exposure(
    data: pd.DataFrame,
    exposure: np.ndarray,
    name: str,
    dividend_yield: float = 0.018,
    capital: float = 10_000.0,
) -> Result:
    """Hold `exposure` units of the index each day, the rest in cash at the bill rate.

    The general form of every no-option defensive strategy: vol targeting, trend filters, drawdown
    control and regime switches all reduce to a daily exposure in [0, cap]. The caller supplies a
    point-in-time exposure (already shifted, so today's weight uses only what was known yesterday);
    this just compounds it. No premium, no options.
    """
    ret = data["spot"].pct_change().fillna(0.0).to_numpy()
    total = ret + dividend_yield / TRADING_DAYS  # equity leg, dividends included
    cash = data["rate"].to_numpy() / TRADING_DAYS  # the uninvested sleeve earns the bill
    exp = np.clip(np.asarray(exposure, dtype=float), 0.0, None)

    daily = exp * total + (1 - exp) * cash
    equity = capital * np.cumprod(1 + daily)
    zeros = pd.Series(0.0, index=data.index)
    return Result(name, pd.Series(equity, index=data.index), zeros, zeros)


def vol_scale(
    result: Result,
    data: pd.DataFrame,
    target: float = 0.12,
    lookback: int = 21,
    max_exposure: float = 1.5,
    name: str | None = None,
) -> Result:
    """Vol-target an existing strategy: own less of it when its own realized vol runs hot.

    Lets a hedge and a sizing rule be stacked. The premium and payoff series are carried through
    unscaled, so they stay indicative rather than exact once the book is being resized.
    """
    ret = result.equity.pct_change().fillna(0.0)
    realized = ret.rolling(lookback).std() * np.sqrt(TRADING_DAYS)
    exposure = (target / realized).shift(1).clip(upper=max_exposure).fillna(1.0)

    daily = exposure * ret + (1 - exposure) * data["rate"] / TRADING_DAYS
    equity = result.equity.iloc[0] * (1 + daily).cumprod()
    return Result(name or f"{result.name} + vol target", equity, result.premium_paid,
                  result.payoff_received, result.cycles, result.hedged_cycles)


def run(
    data: pd.DataFrame,
    strategy: Strategy,
    skew_slope: float = SKEW_SLOPE,
    dividend_yield: float = 0.018,
    capital: float = 10_000.0,
    term_premium: float = TERM_PREMIUM,
    hedge_on: np.ndarray | None = None,
) -> Result:
    """hedge_on is read only at roll dates: once a put is bought it is held to expiry, because a
    signal that flips mid-cycle cannot retroactively change what you already paid for."""
    spot = data["spot"].to_numpy()
    vix = data["vix"].to_numpy()
    rate = data["rate"].to_numpy()
    n = len(spot)
    q = dividend_yield

    premium = np.zeros(n)
    payoff = np.zeros(n)

    if not strategy.hedged:
        # Buy and hold, dividends reinvested. The benchmark everything is measured against.
        equity = capital * (spot / spot[0]) * np.exp(q * np.arange(n) / TRADING_DAYS)
        return Result(strategy.name, pd.Series(equity, index=data.index),
                      pd.Series(premium, index=data.index), pd.Series(payoff, index=data.index))

    equity = np.empty(n)
    value = capital
    start = 0
    cycles = hedged_cycles = 0

    while start < n - 1:
        expiry = min(start + strategy.roll_days, n - 1)
        window = np.arange(start, expiry + 1)
        cycles += 1

        if hedge_on is not None and not hedge_on[start]:
            # Signal is off: ride the index naked for this cycle.
            units = value / spot[start]
            equity[window] = units * spot[window] * np.exp(q * (window - start) / TRADING_DAYS)
            value = equity[expiry]
            start = expiry
            continue

        hedged_cycles += 1
        tenor = (expiry - start) / TRADING_DAYS
        remaining = (expiry - window) / TRADING_DAYS

        def leg(m: float, _s=start, _e=expiry, _w=window, _t=tenor, _r=remaining):
            """Cost, daily marks and expiry intrinsic of one put struck m below the roll spot."""
            k = spot[_s] * (1 - m)
            entry = float(put_price(
                spot[_s], k, _t, rate[_s], implied_vol(vix[_s], m, skew_slope, _t, term_premium), q
            ))
            marks = put_price(
                spot[_w], k, _r, rate[_w],
                implied_vol(vix[_w], m, skew_slope, _r, term_premium), q,
            )
            return entry, marks, max(k - spot[_e], 0.0)

        cost, marks, intrinsic = leg(strategy.moneyness)
        if strategy.short_moneyness is not None:
            # Sell a deeper put against it. Cheaper, but protection stops at the short strike.
            sold, short_marks, short_intrinsic = leg(strategy.short_moneyness)
            cost -= sold
            marks = marks - short_marks
            intrinsic -= short_intrinsic

        units = value / (spot[start] + cost)  # units of the (share + hedge) package
        premium[start] += units * cost

        # Dividends accrue to the share leg only; the hedge covers the original share count.
        reinvested = np.exp(q * (window - start) / TRADING_DAYS)
        equity[window] = units * (spot[window] * reinvested + marks)

        payoff[expiry] += units * intrinsic
        value = equity[expiry]
        start = expiry  # the expiry bar is also the next roll bar

    return Result(
        strategy.name,
        pd.Series(equity, index=data.index),
        pd.Series(premium, index=data.index),
        pd.Series(payoff, index=data.index),
        cycles,
        hedged_cycles,
    )


def run_events(
    data: pd.DataFrame,
    strategy: Strategy,
    entries: np.ndarray,
    skew_slope: float = SKEW_SLOPE,
    dividend_yield: float = 0.018,
    capital: float = 10_000.0,
    term_premium: float = TERM_PREMIUM,
) -> Result:
    """Event-driven hedging: buy a put on the day a signal fires, hold it to expiry, then ride.

    run() hedges on a fixed calendar grid, which is wrong for a rare trigger like "a 3-sigma
    up-move just happened": the event almost never lands on a roll date, so the grid misses it.
    Here a rising edge in `entries` starts a put of strategy.roll_days tenor there and then. New
    signals during a hold are ignored, because you cannot buy a put you are already holding.
    """
    spot = data["spot"].to_numpy()
    vix = data["vix"].to_numpy()
    rate = data["rate"].to_numpy()
    n = len(spot)
    q = dividend_yield
    tenor_days = strategy.roll_days

    equity = np.empty(n)
    premium = np.zeros(n)
    payoff = np.zeros(n)
    value = capital
    i = 0
    hedged = 0

    while i < n:
        if entries[i] and i < n - 1:
            expiry = min(i + tenor_days, n - 1)
            window = np.arange(i, expiry + 1)
            strike = spot[i] * (1 - strategy.moneyness)
            tenor = (expiry - i) / TRADING_DAYS
            remaining = (expiry - window) / TRADING_DAYS

            cost = float(put_price(
                spot[i], strike, tenor, rate[i],
                implied_vol(vix[i], strategy.moneyness, skew_slope, tenor, term_premium), q,
            ))
            units = value / (spot[i] + cost)
            premium[i] += units * cost
            marks = put_price(
                spot[window], strike, remaining, rate[window],
                implied_vol(vix[window], strategy.moneyness, skew_slope, remaining, term_premium), q,
            )
            equity[window] = units * (spot[window] * np.exp(q * (window - i) / TRADING_DAYS) + marks)
            payoff[expiry] += units * max(strike - spot[expiry], 0.0)
            value = equity[expiry]
            hedged += 1
            i = expiry  # resume at expiry; if it is not another entry, we ride from there
        else:
            equity[i] = value
            if i < n - 1:
                value *= (spot[i + 1] / spot[i]) * math.exp(q / TRADING_DAYS)
            i += 1

    return Result(
        strategy.name,
        pd.Series(equity, index=data.index),
        pd.Series(premium, index=data.index),
        pd.Series(payoff, index=data.index),
        cycles=hedged,
        hedged_cycles=hedged,
    )
