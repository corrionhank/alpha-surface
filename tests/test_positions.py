"""Vectorized pricing must agree with the scalar model; the hedged option must be a fair bet
when realized vol equals the vol it was struck at."""

from __future__ import annotations

import math

import numpy as np
import pytest

from alphasurface.derive import black_scholes as bs
from alphasurface.derive import positions as pos
from alphasurface.derive import simulate as sim


@pytest.mark.parametrize("kind", ["call", "put"])
@pytest.mark.parametrize(
    "S,K,T,sig", [(100, 100, 0.5, 0.2), (90, 110, 0.1, 0.35), (120, 80, 2.0, 0.15)]
)
def test_vector_matches_scalar(kind, S, K, T, sig):
    assert pos.bs_price(S, K, T, 0.04, sig, 0.01, kind) == pytest.approx(
        bs.price(S, K, T, 0.04, sig, 0.01, kind)
    )
    assert pos.bs_delta(S, K, T, 0.04, sig, 0.01, kind) == pytest.approx(
        bs.greeks(S, K, T, 0.04, sig, 0.01, kind).delta
    )


def test_parity_over_arrays():
    S = np.linspace(50, 150, 11)
    c, p = (
        pos.bs_price(S, 100, 0.5, 0.04, 0.25, 0.01, "call"),
        pos.bs_price(S, 100, 0.5, 0.04, 0.25, 0.01, "put"),
    )
    assert c - p == pytest.approx(S * math.exp(-0.01 * 0.5) - 100 * math.exp(-0.04 * 0.5))


def test_expiry_value_is_the_payoff():
    condor = pos.presets(100.0, 0.05)["Iron condor"]
    strikes = sorted(leg.strike for leg in condor)
    assert strikes == [90, 95, 105, 110]
    S = np.array([80.0, 92.5, 100.0, 107.5, 120.0])
    assert pos.value(condor, S, 0, 0.04, 0.2, 0.0).tolist() == pytest.approx(
        [-500, -250, 0, -250, -500]
    )


def test_stock_pnl_and_premium_sign():
    stock = [pos.Leg("stock", 0, 1)]
    assert pos.pnl(stock, 100, np.array([110.0]), 30, 10, 0.04, 0.2, 0.2, 0.0)[0] == pytest.approx(
        1000
    )
    assert pos.premium(pos.presets(100.0)["Short put"], 100, 30, 0.04, 0.2, 0.0) < 0
    assert pos.premium(stock, 100, 30, 0.04, 0.2, 0.0) == 0


def test_strike_rounding():
    legs = pos.presets(779.09, 0.05)["Short strangle"]
    assert {leg.strike for leg in legs} == {820.0, 740.0}


def _paths(sigma, n=20_000, days=30, r=0.04, q=0.0, seed=3):
    return sim.gbm(100.0, r - q, sigma, days, n, np.random.default_rng(seed))


def test_hedged_option_is_fair_when_realized_equals_implied():
    out = pos.delta_hedged_pnl(_paths(0.2), 100, 0.04, 0.2, 0.0, "call", side=-1)
    se = out.std() / math.sqrt(len(out))
    assert abs(out.mean()) < 4 * se + 0.01


def test_selling_rich_vol_earns_and_hedging_more_often_narrows():
    rich = pos.delta_hedged_pnl(_paths(0.15), 100, 0.04, 0.25, 0.0, "call", side=-1)
    assert rich.mean() > 0.5  # struck at 25 vol, realized 15
    daily = pos.delta_hedged_pnl(_paths(0.2), 100, 0.04, 0.2, 0.0, "put", side=1, hedge_every=1)
    weekly = pos.delta_hedged_pnl(_paths(0.2), 100, 0.04, 0.2, 0.0, "put", side=1, hedge_every=5)
    assert daily.std() < weekly.std()
