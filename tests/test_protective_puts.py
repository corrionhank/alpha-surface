"""Protective put study.

A backtest that is quietly wrong still prints a confident table, so these test the invariants
that would catch it: the vectorized pricer must agree with the scalar model, the unhedged leg
must reproduce buy-and-hold exactly, a flat market must lose precisely the premium, and a crash
must be floored by the strike.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from alphasurface.derive import black_scholes as bs
from studies.protective_puts import engine, metrics
from studies.protective_puts.bsm import put_price
from studies.protective_puts.engine import Strategy

TRADING_DAYS = engine.TRADING_DAYS


def frame(spot, vix=0.20, rate=0.02) -> pd.DataFrame:
    spot = np.asarray(spot, dtype=float)
    idx = pd.bdate_range("2010-01-04", periods=len(spot))
    return pd.DataFrame(
        {"spot": spot, "vix": np.full(len(spot), vix), "rate": np.full(len(spot), rate)}, index=idx
    )


@pytest.mark.parametrize("S", [80.0, 100.0, 130.0])
@pytest.mark.parametrize("K", [90.0, 100.0])
@pytest.mark.parametrize("T", [0.02, 0.25, 2.0])
@pytest.mark.parametrize("sigma", [0.10, 0.35])
def test_vectorized_pricer_matches_the_scalar_model(S, K, T, sigma):
    assert put_price(S, K, T, 0.03, sigma, 0.018) == pytest.approx(
        bs.price(S, K, T, 0.03, sigma, 0.018, "put"), abs=1e-10
    )


def test_pricer_settles_at_intrinsic():
    assert put_price(90.0, 100.0, 0.0, 0.03, 0.2) == pytest.approx(10.0)
    assert put_price(110.0, 100.0, 0.0, 0.03, 0.2) == pytest.approx(0.0)
    assert put_price(np.array([90.0, 110.0]), 100.0, 0.0, 0.0, 0.0).tolist() == [10.0, 0.0]


def test_pricer_broadcasts_over_a_path():
    path = np.linspace(80, 120, 25)
    prices = put_price(path, 100.0, 0.25, 0.02, 0.2)
    assert prices.shape == path.shape
    assert np.all(np.diff(prices) < 0)  # a put is monotonically cheaper as spot rises


def test_skew_adds_vol_points_for_otm_puts():
    # 0.5 slope, 5% OTM: 2.5 vol points over VIX. At the money, nothing is added.
    assert engine.implied_vol(0.20, 0.05, 0.5) == pytest.approx(0.225)
    assert engine.implied_vol(0.20, 0.00, 0.5) == pytest.approx(0.20)
    assert engine.implied_vol(0.20, 0.05, 0.0) == pytest.approx(0.20)  # flat VIX


def test_term_premium_only_bites_beyond_thirty_days():
    """VIX is a 30-day number. A 30-day put is priced at it; a 1-year put must cost more, or
    every slow-rolling strategy gets a subsidy the real market would never give it."""
    at_30d = engine.implied_vol(0.20, 0.0, 0.0, tenor=engine.VIX_TENOR, term_premium=0.025)
    at_1y = engine.implied_vol(0.20, 0.0, 0.0, tenor=1.0, term_premium=0.025)
    assert at_30d == pytest.approx(0.20)  # the anchor point, untouched
    assert at_1y == pytest.approx(0.225)  # the full premium lands at one year
    assert engine.implied_vol(0.20, 0.0, 0.0, tenor=0.25, term_premium=0.025) == pytest.approx(
        0.20 + 0.025 * (0.5 - (30 / 365) ** 0.5) / (1 - (30 / 365) ** 0.5)
    )
    # Zero reproduces flat VIX at every tenor, which is the assumption being tested against.
    assert engine.implied_vol(0.20, 0.0, 0.0, tenor=1.0, term_premium=0.0) == pytest.approx(0.20)


def test_term_premium_penalizes_the_slow_roll():
    data = frame(np.linspace(100, 130, TRADING_DAYS * 2))
    annual = Strategy("annual", moneyness=0.05, roll_days=252)
    flat = engine.run(data, annual, skew_slope=0.0, term_premium=0.0, dividend_yield=0.0)
    termed = engine.run(data, annual, skew_slope=0.0, term_premium=0.025, dividend_yield=0.0)
    assert termed.total_premium > flat.total_premium

    # A monthly roll sits at the VIX tenor, so it should barely notice.
    monthly = Strategy("monthly", moneyness=0.05, roll_days=21)
    m_flat = engine.run(data, monthly, skew_slope=0.0, term_premium=0.0, dividend_yield=0.0)
    m_termed = engine.run(data, monthly, skew_slope=0.0, term_premium=0.025, dividend_yield=0.0)
    assert m_termed.total_premium == pytest.approx(m_flat.total_premium, rel=0.02)


def test_unhedged_reproduces_buy_and_hold():
    data = frame(np.linspace(100, 150, 300))
    res = engine.run(data, Strategy("bh", hedged=False), dividend_yield=0.0, capital=1_000.0)
    assert res.equity.iloc[-1] == pytest.approx(1_000.0 * 150 / 100)
    assert res.total_premium == 0.0
    assert res.total_payoff == 0.0


def test_dividends_compound_into_the_unhedged_leg():
    data = frame(np.full(TRADING_DAYS + 1, 100.0))
    res = engine.run(data, Strategy("bh", hedged=False), dividend_yield=0.02, capital=1_000.0)
    assert res.equity.iloc[-1] == pytest.approx(1_000.0 * np.exp(0.02), rel=1e-6)


def test_flat_market_loses_exactly_the_premium():
    """Price never moves, so the puts expire worthless and the book is out the premium and
    nothing else. This is the bleed, isolated."""
    data = frame(np.full(TRADING_DAYS + 1, 100.0))
    res = engine.run(
        data, Strategy("put", moneyness=0.05, roll_days=21), dividend_yield=0.0, capital=10_000.0
    )
    assert res.total_payoff == pytest.approx(0.0)
    assert res.total_premium > 0
    assert res.equity.iloc[-1] == pytest.approx(10_000.0 - res.total_premium, rel=1e-9)


def test_the_strike_floors_a_crash():
    """A 40% gap inside one holding period. The ATM put means the loss cannot exceed what was
    paid for it, which is the entire point of buying protection."""
    path = np.concatenate([np.full(5, 100.0), np.full(17, 60.0)])
    data = frame(path, vix=0.20)
    hedged = engine.run(
        data, Strategy("put", moneyness=0.0, roll_days=21), dividend_yield=0.0, capital=10_000.0
    )
    naked = engine.run(data, Strategy("bh", hedged=False), dividend_yield=0.0, capital=10_000.0)

    assert naked.equity.iloc[-1] == pytest.approx(6_000.0)  # ate the whole 40%
    assert hedged.equity.iloc[-1] > 9_000.0  # floored at the strike, less the premium
    assert hedged.total_payoff > 0


def test_deeper_strikes_cost_less():
    data = frame(100 + np.zeros(TRADING_DAYS + 1))
    costs = [
        engine.run(
            data, Strategy(f"m{m}", moneyness=m, roll_days=21), dividend_yield=0.0
        ).total_premium
        for m in (0.0, 0.05, 0.10)
    ]
    assert costs == sorted(costs, reverse=True)  # further OTM is cheaper


def test_hedging_always_costs_something_in_a_rising_market():
    data = frame(np.linspace(100, 200, TRADING_DAYS * 2))
    hedged = engine.run(data, Strategy("put", moneyness=0.05), dividend_yield=0.0)
    naked = engine.run(data, Strategy("bh", hedged=False), dividend_yield=0.0)
    assert hedged.equity.iloc[-1] < naked.equity.iloc[-1]
    assert hedged.recovery < 1.0  # the puts never paid for themselves


def test_skew_only_makes_protection_dearer():
    data = frame(np.linspace(100, 130, TRADING_DAYS))
    cheap = engine.run(data, Strategy("p", moneyness=0.05), skew_slope=0.0, dividend_yield=0.0)
    dear = engine.run(data, Strategy("p", moneyness=0.05), skew_slope=1.0, dividend_yield=0.0)
    assert dear.total_premium > cheap.total_premium
    assert dear.equity.iloc[-1] < cheap.equity.iloc[-1]  # and it comes straight out of the return


def test_equity_is_marked_daily_not_just_at_expiry():
    # A mid-segment selloff must show up in the curve, or drawdown stats are fiction.
    path = np.concatenate([np.full(5, 100.0), np.full(6, 75.0), np.full(11, 100.0)])
    res = engine.run(frame(path), Strategy("p", moneyness=0.05, roll_days=21), dividend_yield=0.0)
    assert res.equity.iloc[8] < res.equity.iloc[0]  # the drop is visible before the put expires


def test_put_spread_is_cheaper_than_the_naked_put():
    data = frame(np.full(TRADING_DAYS + 1, 100.0))
    naked = engine.run(data, Strategy("p", moneyness=0.05), dividend_yield=0.0)
    spread = engine.run(
        data, Strategy("s", moneyness=0.05, short_moneyness=0.15), dividend_yield=0.0
    )
    assert 0 < spread.total_premium < naked.total_premium  # the sold leg pays for part of it


def test_put_spread_protection_stops_at_the_short_strike():
    """Below the short strike the two legs cancel, so the spread stops protecting. That cap is the
    whole trade-off and it has to show up in a crash."""
    crash = np.concatenate([np.full(3, 100.0), np.full(19, 50.0)])  # straight through both strikes
    data = frame(crash)
    naked = engine.run(data, Strategy("p", moneyness=0.05, roll_days=21), dividend_yield=0.0)
    spread = engine.run(
        data, Strategy("s", moneyness=0.05, short_moneyness=0.15, roll_days=21), dividend_yield=0.0
    )
    assert spread.equity.iloc[-1] < naked.equity.iloc[-1]  # capped protection is worse in a rout
    assert spread.total_payoff > 0  # but it still paid the 10-point width


def test_short_leg_must_be_further_out_of_the_money():
    with pytest.raises(ValueError):
        Strategy("bad", moneyness=0.10, short_moneyness=0.05)


def test_vol_target_cuts_volatility():
    rng = np.random.default_rng(11)
    # A calm stretch then a wild one: the target must shrink exposure into the storm.
    ret = np.concatenate([rng.normal(0.0003, 0.005, 600), rng.normal(0.0003, 0.030, 400)])
    data = frame(100 * np.exp(np.cumsum(ret)))

    managed = engine.run_vol_target(data, target=0.10, dividend_yield=0.0)
    naked = engine.run(data, Strategy("bh", hedged=False), dividend_yield=0.0)

    managed_vol = managed.equity.pct_change().std() * np.sqrt(TRADING_DAYS)
    naked_vol = naked.equity.pct_change().std() * np.sqrt(TRADING_DAYS)
    assert managed_vol < naked_vol
    assert managed.total_premium == 0.0  # it buys nothing


def test_vol_target_never_exceeds_its_exposure_cap():
    data = frame(100 + np.zeros(300))  # zero vol, so the raw signal wants infinite leverage
    managed = engine.run_vol_target(
        data, target=0.12, max_exposure=1.0, dividend_yield=0.0, capital=1_000.0
    )
    assert np.isfinite(managed.equity).all()
    assert managed.equity.iloc[-1] < 1_000.0 * 1.10  # capped, so no runaway compounding


def test_vol_scaling_an_unhedged_book_matches_the_standalone_vol_target():
    rng = np.random.default_rng(5)
    data = frame(100 * np.exp(np.cumsum(rng.normal(0.0002, 0.012, 800))))
    standalone = engine.run_vol_target(data, target=0.12, dividend_yield=0.0)
    stacked = engine.vol_scale(
        engine.run(data, Strategy("bh", hedged=False), dividend_yield=0.0), data, target=0.12
    )
    assert stacked.equity.iloc[-1] == pytest.approx(standalone.equity.iloc[-1], rel=1e-6)


def test_metrics_on_a_known_curve():
    idx = pd.bdate_range("2015-01-01", periods=TRADING_DAYS + 1)
    equity = pd.Series(1_000 * 1.10 ** (np.arange(len(idx)) / TRADING_DAYS), index=idx)
    stats = metrics.summarize(equity, pd.Series(0.0, index=idx))
    assert stats["CAGR"] == pytest.approx(0.10, abs=5e-3)  # a clean 10% year
    assert stats["MaxDD"] == pytest.approx(0.0)  # monotone, so no drawdown
    assert stats["Vol"] == pytest.approx(0.0, abs=1e-6)


def test_drawdown_is_measured_from_the_peak():
    equity = pd.Series([100, 120, 60, 90], index=pd.bdate_range("2020-01-01", periods=4))
    assert metrics.drawdown(equity).min() == pytest.approx(-0.5)  # 120 -> 60
