"""Monte Carlo paths checked against what the math says they must average to."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest
from scipy.stats import kurtosis

from derive import simulate as sim

S, MU, SIG, DAYS, N = 100.0, 0.05, 0.20, 252, 40_000
T = DAYS / sim.TRADING_DAYS


@pytest.fixture
def rng():
    return np.random.default_rng(11)


def test_gbm_shape_and_start(rng):
    paths = sim.gbm(S, MU, SIG, 10, 7, rng)
    assert paths.shape == (7, 11) and (paths[:, 0] == S).all()


def test_gbm_mean_and_vol_drag(rng):
    end = sim.gbm(S, MU, SIG, DAYS, N, rng)[:, -1]
    assert end.mean() == pytest.approx(S * math.exp(MU * T), rel=0.01)
    # The median sits below the mean by the volatility drag, sigma^2 / 2 a year.
    assert np.median(end) == pytest.approx(S * math.exp((MU - SIG**2 / 2) * T), rel=0.01)
    assert np.log(end / S).std() == pytest.approx(SIG * math.sqrt(T), rel=0.02)


def test_jump_keeps_the_mean_and_fattens_the_tails(rng):
    jp = sim.jump(S, MU, SIG, DAYS, N, rng, rate=5, mean=-0.05, std=0.05)
    gb = sim.gbm(S, MU, SIG, DAYS, N, rng)
    assert jp[:, -1].mean() == pytest.approx(S * math.exp(MU * T), rel=0.015)
    daily_j, daily_g = np.diff(np.log(jp), axis=1).ravel(), np.diff(np.log(gb), axis=1).ravel()
    assert kurtosis(daily_j) > kurtosis(daily_g) + 1


def test_bootstrap_rescales_to_chosen_vol(rng):
    hist = rng.standard_t(4, 3000) * 0.01  # fat-tailed "history" at 1% a day
    paths = sim.bootstrap(S, MU, SIG, 60, 5000, rng, hist, block=5)
    daily = np.diff(np.log(paths), axis=1)
    assert daily.std() == pytest.approx(SIG * math.sqrt(sim.DT), rel=0.03)
    with pytest.raises(ValueError):
        sim.bootstrap(S, MU, SIG, 5, 10, rng, hist[:3], block=5)


def test_replay_rescales_to_spot():
    idx = pd.date_range("2020-02-19", periods=6, freq="B").date
    closes = pd.Series([200.0, 190.0, 180.0, 170.0, 180.0, 190.0], index=idx)
    path = sim.replay(closes, "2020-02-19", 3, spot=100.0)
    assert path.tolist() == pytest.approx([100.0, 95.0, 90.0, 85.0])
    assert sim.replay(closes, "2020-02-19", 10, spot=100.0) is None


def test_path_readers():
    paths = np.array([[100, 110, 90, 120], [100, 95, 85, 99]], dtype=float)
    assert sim.max_drawdown(paths).tolist() == pytest.approx([90 / 110 - 1, -0.15])
    assert sim.touch_probability(paths, 115) == 0.5
    assert sim.touch_probability(paths, 86) == 0.5  # only the second path dips to 85
    assert sim.touch_probability(paths, 91) == 1.0
    stats = sim.terminal_stats(paths)
    assert stats["p_up"] == 0.5 and stats["mean"] == pytest.approx(109.5)
    assert list(sim.bands(paths).columns) == ["p5", "p25", "p50", "p75", "p95"]


def test_var_cvar_on_a_known_sample():
    pnl = np.arange(-50, 50, dtype=float)  # 100 outcomes, one per dollar
    var, cvar = sim.var_cvar(pnl, 0.95)
    assert var == pytest.approx(-np.quantile(pnl, 0.05))
    assert cvar == pytest.approx(-pnl[pnl <= np.quantile(pnl, 0.05)].mean())
    assert cvar >= var > 0


def test_growth_rate_peaks_at_kelly():
    p, b = 0.55, 1.0
    grid = np.linspace(0, 0.5, 5001)
    assert grid[np.nanargmax(sim.growth_rate(p, b, grid))] == pytest.approx(p - (1 - p) / b, abs=1e-3)
    assert sim.growth_rate(p, b, 2.2 * (p - (1 - p) / b)) < 0  # over-betting a real edge loses


def test_bet_paths(rng):
    flat = sim.bet_paths(0.5, 1.0, 0.0, 20, 5, rng)
    assert flat.shape == (5, 21) and (flat == 1).all()
    w = sim.bet_paths(1.0, 2.0, 0.1, 3, 2, rng)  # always wins: 1.2 per bet
    assert w[:, -1] == pytest.approx([1.2**3] * 2)
