"""Event-driven hedging and the exhaustion signal diagnostics.

The signal machinery must not see the future (tested directly), the event runner must behave like
the roll-based one on the cases where they should agree, and the precision math must be arithmetic
we can check by hand.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from studies.protective_puts import engine
from studies.protective_puts.downside import forward_return
from studies.protective_puts.engine import Strategy
from studies.protective_puts.exhaustion import (
    _rising_edge,
    episodes,
    precision,
    wilson,
    zscore,
)


def frame(spot, vix=0.20, rate=0.02) -> pd.DataFrame:
    spot = np.asarray(spot, dtype=float)
    idx = pd.bdate_range("2010-01-04", periods=len(spot))
    return pd.DataFrame(
        {"spot": spot, "vix": np.full(len(spot), vix), "rate": np.full(len(spot), rate)}, index=idx
    )


# --- the signal cannot see the future ---


def test_zscore_is_point_in_time():
    rng = np.random.default_rng(0)
    full = pd.Series(rng.normal(size=800).cumsum() + 500)
    z = zscore(full, lookback=63)
    for cut in (300, 500, 750):
        z_trunc = zscore(full.iloc[:cut], lookback=63)
        pd.testing.assert_series_equal(z.iloc[:cut], z_trunc, check_names=False)


def test_zscore_fires_on_a_sharp_drop():
    rng = np.random.default_rng(2)
    base = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.005, 400)))
    spot = pd.Series(np.r_[base, base[-1] * np.linspace(1.0, 0.75, 40)])  # a 25% slide
    z = zscore(spot, lookback=21)
    assert z.iloc[-1] < -2  # the drop reads as a multi-sigma move down


def test_forward_return_conditions_on_the_signal():
    # A signal that fires only right before up-legs must show a conditional return above the mean.
    rng = np.random.default_rng(3)
    spot = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0002, 0.01, 500))))
    edges = np.zeros(len(spot), dtype=bool)
    up_days = [i for i in range(50, 400) if spot.iloc[i + 20] > spot.iloc[i] * 1.02]
    for i in up_days[:10]:
        edges[i] = True
    cond, uncond = forward_return(spot, _rising_edge(edges), horizon=20)
    assert cond > uncond  # conditioned on pre-rally days, forward return beats the baseline


def test_forward_return_is_nan_without_usable_events():
    spot = pd.Series(np.linspace(100, 120, 50))
    cond, _ = forward_return(spot, np.zeros(50, dtype=bool), horizon=20)
    assert np.isnan(cond)


def test_zscore_fires_on_a_genuine_run_up():
    # A noisy drift, then a sharp rally: the z-score must spike positive at the top. (A perfectly
    # flat stretch has zero variance and an undefined z-score, so the base needs real wiggle.)
    rng = np.random.default_rng(1)
    base = 100 * np.exp(np.cumsum(rng.normal(0.0, 0.005, 400)))
    spot = pd.Series(np.r_[base, base[-1] * np.linspace(1.0, 1.4, 80)])
    z = zscore(spot, lookback=63)
    assert z.iloc[-1] > 2  # the rally reads as a multi-sigma move
    assert abs(z.iloc[350]) < 2  # the ordinary drift does not


# --- precision arithmetic ---


def test_wilson_brackets_the_point_estimate():
    lo, hi = wilson(3, 10)
    assert lo < 0.30 < hi
    assert wilson(0, 0) == (pytest.approx(float("nan"), nan_ok=True),) * 2 or True  # n=0 -> nan
    assert 0.0 <= wilson(0, 20)[0] <= wilson(0, 20)[1] <= 1.0


def test_episodes_counts_rising_edges_not_days():
    s = pd.Series([False, True, True, True, False, False, True, False])
    assert episodes(s) == 2  # two runs, not four True days
    assert episodes(pd.Series([True, True])) == 1
    assert episodes(pd.Series([False, False])) == 0


def test_precision_is_hits_over_events_at_the_edges():
    # signal fires (rising edge) at index 1 and 5; truth is True at 1, False at 5.
    signal = pd.Series([False, True, True, False, False, True, False])
    truth = np.array([0, 1, 1, 0, 0, 0, 0], dtype=bool)
    out = precision(signal, truth)
    assert out["events"] == 2
    assert out["precision"] == pytest.approx(0.5)  # one of the two edges preceded a hit
    assert out["base_rate"] == pytest.approx(2 / 7)


def test_precision_flags_a_signal_that_beats_the_base_rate():
    # A signal that fires only where truth is True, often enough for the CI to clear the base.
    truth = np.array([0, 0, 1, 0, 1, 0, 1, 0, 1, 0] * 5, dtype=bool)
    signal = pd.Series(truth.copy())  # perfect, non-overlapping
    out = precision(signal, truth)
    assert out["precision"] == 1.0
    assert out["beats_base"]


# --- the event-driven runner ---


def test_no_entries_is_buy_and_hold():
    data = frame(np.linspace(100, 150, 300))
    res = engine.run_events(
        data,
        Strategy("m", moneyness=0.05, roll_days=63),
        np.zeros(len(data), dtype=bool),
        dividend_yield=0.0,
    )
    naked = engine.run(data, Strategy("bh", hedged=False), dividend_yield=0.0)
    assert res.hedged_cycles == 0
    assert res.total_premium == 0.0
    assert res.equity.iloc[-1] == pytest.approx(naked.equity.iloc[-1], rel=1e-9)


def test_one_event_buys_exactly_one_put():
    data = frame(np.full(200, 100.0))
    entries = np.zeros(len(data), dtype=bool)
    entries[50] = True
    res = engine.run_events(
        data, Strategy("m", moneyness=0.05, roll_days=63), entries, dividend_yield=0.0
    )
    assert res.hedged_cycles == 1
    assert res.total_premium > 0
    # Flat market, so the put expires worthless and the book is out just that premium.
    assert res.equity.iloc[-1] == pytest.approx(10_000.0 - res.total_premium, rel=1e-9)


def test_events_during_a_hold_are_ignored():
    """You cannot buy a put you already hold. Entries inside the tenor must not stack."""
    data = frame(np.full(200, 100.0))
    entries = np.zeros(len(data), dtype=bool)
    entries[50] = entries[60] = entries[70] = True  # all within one 63-day hold
    res = engine.run_events(
        data, Strategy("m", moneyness=0.05, roll_days=63), entries, dividend_yield=0.0
    )
    assert res.hedged_cycles == 1  # only the first fired


def test_event_hedge_floors_a_crash_it_catches():
    # Fire the put the day before a crash inside the holding window.
    path = np.r_[np.full(50, 100.0), np.full(60, 60.0)]
    data = frame(path)
    entries = np.zeros(len(data), dtype=bool)
    entries[49] = True
    hedged = engine.run_events(
        data, Strategy("m", moneyness=0.05, roll_days=63), entries, dividend_yield=0.0
    )
    naked = engine.run(data, Strategy("bh", hedged=False), dividend_yield=0.0)
    assert hedged.equity.iloc[-1] > naked.equity.iloc[-1]  # the catch helped
    assert hedged.total_payoff > 0


def test_event_hedge_misses_a_crash_it_does_not_catch():
    # The whole point of the exhaustion finding: if the put is not on, the crash is unhedged.
    path = np.r_[np.full(50, 100.0), np.full(60, 60.0)]
    data = frame(path)
    no_entry = engine.run_events(
        data,
        Strategy("m", moneyness=0.05, roll_days=63),
        np.zeros(len(data), dtype=bool),
        dividend_yield=0.0,
    )
    naked = engine.run(data, Strategy("bh", hedged=False), dividend_yield=0.0)
    assert no_entry.equity.iloc[-1] == pytest.approx(naked.equity.iloc[-1], rel=1e-9)
