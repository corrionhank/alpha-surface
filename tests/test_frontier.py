"""The general exposure engine and the frontier's exposure generators.

run_exposure is the primitive under every no-option defensive strategy, so its edge cases (fully
invested, fully in cash, clipped) must be exact. The generators must be point-in-time and must do
what their name says.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from studies.protective_puts import engine, frontier
from studies.protective_puts.engine import Strategy


def frame(spot, vix=0.20, rate=0.02) -> pd.DataFrame:
    spot = np.asarray(spot, dtype=float)
    idx = pd.bdate_range("2006-01-03", periods=len(spot))
    return pd.DataFrame(
        {"spot": spot, "vix": np.full(len(spot), vix), "rate": np.full(len(spot), rate)}, index=idx
    )


def test_full_exposure_is_buy_and_hold():
    data = frame(np.linspace(100, 160, 300))
    full = engine.run_exposure(data, np.ones(len(data)), "full", dividend_yield=0.0)
    naked = engine.run(data, Strategy("bh", hedged=False), dividend_yield=0.0)
    assert full.equity.iloc[-1] == pytest.approx(naked.equity.iloc[-1], rel=1e-9)


def test_zero_exposure_earns_the_bill_rate():
    data = frame(np.linspace(100, 200, 253), rate=0.04)  # a year of trading days
    cash = engine.run_exposure(
        data, np.zeros(len(data)), "cash", dividend_yield=0.0, capital=1_000.0
    )
    # Every day compounds at the bill rate and the rallying price is ignored entirely.
    assert cash.equity.iloc[-1] == pytest.approx(1_000.0 * (1 + 0.04 / 252) ** len(data), rel=1e-9)


def test_exposure_is_clipped_at_zero():
    data = frame(np.full(50, 100.0), rate=0.0)  # zero bill rate, so all-cash is flat
    # A negative weight would mean shorting; the engine floors exposure at zero instead.
    res = engine.run_exposure(data, np.full(len(data), -0.5), "neg", dividend_yield=0.0)
    assert (res.equity.diff().dropna().abs() < 1e-9).all()  # flat: all in (zero-yield) cash


def test_vol_target_generator_matches_the_engine():
    rng = np.random.default_rng(4)
    data = frame(100 * np.exp(np.cumsum(rng.normal(0.0002, 0.011, 600))))
    exp = frontier.vol_target(data, target=0.12, lookback=21, cap=1.5, estimator="realized")
    a = engine.run_exposure(data, exp, "gen")
    b = engine.run_vol_target(data, target=0.12, lookback=21, max_exposure=1.5)
    assert a.equity.iloc[-1] == pytest.approx(b.equity.iloc[-1], rel=1e-9)


def test_trend_filter_derisks_below_the_average():
    # Rise then a sustained fall: exposure must drop to `off` once price is under its MA.
    data = frame(np.r_[np.linspace(100, 160, 220), np.linspace(160, 90, 120)])
    exp = frontier.trend_ma(data, ma_days=100, off=0.0)
    assert exp[120] == pytest.approx(1.0)  # climbing, above the average
    assert exp[-1] == pytest.approx(0.0)  # well below it, de-risked


def test_drawdown_control_is_full_at_highs_and_cut_in_a_slump():
    data = frame(np.r_[np.linspace(100, 200, 100), np.linspace(200, 150, 60)])
    exp = frontier.drawdown_control(data, cap_dd=0.15, floor=0.0)
    assert exp[99] == pytest.approx(1.0, abs=1e-9)  # at the peak
    assert exp[-1] < 0.3  # 25% off the peak, well past the 15% cap, so near the floor


def test_generators_are_point_in_time():
    # Truncating the series must not change any earlier exposure: no signal may see the future.
    rng = np.random.default_rng(6)
    full = frame(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 500))))
    part = full.iloc[:300]
    for gen in (
        lambda d: frontier.vol_target(d, 0.12, 21, 1.5, "realized"),
        lambda d: frontier.trend_ma(d, 100, 0.0),
        lambda d: frontier.drawdown_control(d, 0.15, 0.0),
    ):
        np.testing.assert_allclose(gen(full)[:300], gen(part), rtol=1e-9, equal_nan=True)


def test_the_sweep_builds_a_large_diverse_family():
    data = frame(100 * np.exp(np.cumsum(np.random.default_rng(1).normal(0, 0.01, 400))))
    strategies = frontier.build_strategies(data)
    assert len(strategies) > 60
    families = {fam for _, fam, _ in strategies}
    assert families == {
        "Vol target",
        "Trend",
        "TS momentum",
        "Drawdown ctrl",
        "VIX regime",
        "Downside",
    }
    for _, _, exp in strategies:
        assert len(exp) == len(data)
        assert np.isfinite(exp).all()
