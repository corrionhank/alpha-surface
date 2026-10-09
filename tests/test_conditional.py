"""Conditional hedging: signals, lookahead, and the random control.

The whole study is worthless if a signal can see the future, so that is the first thing tested.
No network here: only the pure transforms are exercised, never the fetchers.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from studies.protective_puts import engine, signals
from studies.protective_puts.conditional import random_hedge
from studies.protective_puts.engine import Strategy


def series(values, start="2000-01-03") -> pd.Series:
    return pd.Series(values, index=pd.bdate_range(start, periods=len(values)), dtype=float)


def test_pit_thresholds_cannot_see_the_future():
    """The test that matters. Truncating the series after date t must not change the signal at t.

    If it does, the threshold was set with data that had not happened yet, and every result
    downstream is a memory of the answer rather than a forecast of it.
    """
    rng = np.random.default_rng(0)
    full = series(rng.normal(size=600).cumsum() + 50)
    signal = signals._pit_high(full, 0.80, min_periods=50)

    for cut in (80, 200, 450):
        truncated = signals._pit_high(full.iloc[:cut], 0.80, min_periods=50)
        pd.testing.assert_series_equal(signal.iloc[:cut], truncated)


def test_a_future_spike_cannot_change_a_past_signal():
    calm = series([10.0] * 100 + [20.0] + [10.0] * 10)
    spiked = calm.copy()
    spiked.iloc[-1] = 5_000.0  # a crisis that has not happened yet at bar 100

    before = signals._pit_high(calm, 0.80, min_periods=20)
    after = signals._pit_high(spiked, 0.80, min_periods=20)
    assert before.iloc[100] == after.iloc[100]  # bar 100 must not know about the spike


def test_todays_reading_does_not_set_its_own_bar():
    # A single record-high print must fire, which only works if the threshold excludes today.
    rising = series(list(range(1, 61)))
    assert signals._pit_high(rising, 0.80, min_periods=10).iloc[-1]


def test_no_signal_before_the_minimum_history():
    values = series(list(range(1, 61)))
    assert not signals._pit_high(values, 0.80, min_periods=30).iloc[:29].any()


def test_monthly_series_are_lagged_by_publication_delay():
    """Unemployment for March is not knowable in March."""
    monthly = pd.Series([False, True], index=pd.to_datetime(["2020-03-01", "2020-04-01"]))
    daily = pd.bdate_range("2020-03-02", "2020-06-01")
    out = signals._monthly_to_daily(monthly, daily)

    assert not out.loc["2020-04-15"]  # April's reading is not out yet
    assert out.loc["2020-05-15"]  # it lands a month later
    assert signals.MONTHLY_LAG == 1


def test_hedge_off_everywhere_is_buy_and_hold():
    data = frame(np.linspace(100, 140, 300))
    off = np.zeros(len(data), dtype=bool)
    hedged = engine.run(data, Strategy("p", moneyness=0.05), hedge_on=off, dividend_yield=0.0)
    naked = engine.run(data, Strategy("bh", hedged=False), dividend_yield=0.0)

    assert hedged.total_premium == 0.0
    assert hedged.duty_cycle == 0.0
    assert hedged.equity.iloc[-1] == pytest.approx(naked.equity.iloc[-1], rel=1e-9)


def test_hedge_on_everywhere_matches_the_unconditional_hedge():
    data = frame(np.linspace(100, 140, 300))
    on = np.ones(len(data), dtype=bool)
    conditional = engine.run(data, Strategy("p", moneyness=0.05), hedge_on=on, dividend_yield=0.0)
    always = engine.run(data, Strategy("p", moneyness=0.05), dividend_yield=0.0)

    assert conditional.duty_cycle == 1.0
    assert conditional.equity.iloc[-1] == pytest.approx(always.equity.iloc[-1], rel=1e-12)


def test_the_signal_is_only_read_at_roll_dates():
    """A put already bought cannot be un-bought when the signal flips mid-cycle."""
    data = frame(np.full(43, 100.0))
    flip = np.zeros(len(data), dtype=bool)
    flip[0] = True  # on at the first roll only
    res = engine.run(
        data, Strategy("p", moneyness=0.05, roll_days=21), hedge_on=flip, dividend_yield=0.0
    )
    assert res.cycles == 2
    assert res.hedged_cycles == 1
    assert res.duty_cycle == pytest.approx(0.5)


def test_random_hedge_matches_its_duty_cycle():
    rng = np.random.default_rng(7)
    n, roll = 5_000, 21
    duty = np.mean([random_hedge(n, roll, 0.30, rng).mean() for _ in range(50)])
    assert duty == pytest.approx(0.30, abs=0.02)


def test_random_hedge_is_constant_within_a_roll_cycle():
    """Random hedging has to be decided per cycle, not per day, or it is not comparable to a
    signal that can only act at the roll."""
    flags = random_hedge(84, 21, 0.5, np.random.default_rng(3))
    for start in range(0, 84, 21):
        block = flags[start : start + 21]
        assert block.all() or not block.any()


def frame(spot, vix=0.20, rate=0.02) -> pd.DataFrame:
    spot = np.asarray(spot, dtype=float)
    idx = pd.bdate_range("2010-01-04", periods=len(spot))
    return pd.DataFrame(
        {"spot": spot, "vix": np.full(len(spot), vix), "rate": np.full(len(spot), rate)}, index=idx
    )
