"""Pot odds: breakeven, EV, edge, Kelly, and the risk-neutral probability they are measured
against. Anchors are hand-checkable so a regression is obvious."""

from __future__ import annotations

import math

import pytest

from derive import black_scholes as bs
from derive import pot_odds as po


def test_even_money_needs_half():
    odds = po.from_payoff(risk=100, reward=100)
    assert odds.ratio == 1.0
    assert odds.breakeven == 0.5


@pytest.mark.parametrize(
    "risk,reward,breakeven",
    [(100, 300, 0.25), (300, 100, 0.75), (200, 100, 2 / 3), (1, 4, 0.2)],
)
def test_breakeven_is_risk_over_total(risk, reward, breakeven):
    assert po.from_payoff(risk, reward).breakeven == pytest.approx(breakeven)


def test_credit_vertical_breakeven_is_width_minus_credit():
    # 5-wide sold for 1.65: risk 3.35, keep 1.65, so you need to win 67% of the time.
    odds = po.from_credit_vertical(width=5.0, credit=1.65)
    assert odds.risk == pytest.approx(3.35)
    assert odds.reward == pytest.approx(1.65)
    assert odds.breakeven == pytest.approx(3.35 / 5.0)


def test_debit_vertical_breakeven_is_debit_over_width():
    odds = po.from_debit_vertical(width=5.0, debit=1.90)
    assert odds.risk == pytest.approx(1.90)
    assert odds.reward == pytest.approx(3.10)
    assert odds.breakeven == pytest.approx(1.90 / 5.0)


def test_credit_and_debit_verticals_are_two_sides_of_one_trade():
    # The seller's risk is the buyer's reward. Their breakevens must sum to 1.
    sell = po.from_credit_vertical(width=5.0, credit=2.0)
    buy = po.from_debit_vertical(width=5.0, debit=2.0)
    assert sell.risk == pytest.approx(buy.reward)
    assert sell.reward == pytest.approx(buy.risk)
    assert sell.breakeven + buy.breakeven == pytest.approx(1.0)


def test_ev_is_zero_at_the_breakeven():
    odds = po.from_payoff(risk=3.35, reward=1.65)
    assert po.expected_value(odds.breakeven, odds) == pytest.approx(0.0, abs=1e-12)
    assert po.edge(odds.breakeven, odds) == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("p", [0.05, 0.4, 0.5, 0.75, 0.95])
@pytest.mark.parametrize("risk,reward", [(100, 300), (3.35, 1.65), (1, 1)])
def test_ev_equals_total_stake_times_edge(p, risk, reward):
    # EV = (R + W) * edge, the identity the whole page rests on.
    odds = po.from_payoff(risk, reward)
    assert po.expected_value(p, odds) == pytest.approx((risk + reward) * po.edge(p, odds))


def test_kelly_is_zero_without_edge():
    odds = po.from_payoff(risk=100, reward=100)
    assert po.kelly(odds.breakeven, odds) == 0.0
    assert po.kelly(0.3, odds) == 0.0  # negative edge does not become a short


def test_kelly_matches_the_textbook_coin_flip():
    # Even money at 60%: f* = 2p - 1 = 0.2.
    assert po.kelly(0.6, po.from_payoff(1, 1)) == pytest.approx(0.2)
    # 3-to-1 at 40%: f* = 0.4 - 0.6/3 = 0.2.
    assert po.kelly(0.4, po.from_payoff(100, 300)) == pytest.approx(0.2)


@pytest.mark.parametrize("risk,reward", [(0, 100), (100, 0), (-1, 5)])
def test_payoff_must_be_positive(risk, reward):
    with pytest.raises(ValueError):
        po.from_payoff(risk, reward)


@pytest.mark.parametrize("width,credit", [(5.0, 5.0), (5.0, 6.0), (5.0, 0.0)])
def test_credit_must_fit_inside_the_width(width, credit):
    with pytest.raises(ValueError):
        po.from_credit_vertical(width, credit)


def test_itm_probability_is_the_two_sides_of_one_coin():
    args = (100.0, 105.0, 0.25, 0.05, 0.20, 0.0)
    above = bs.itm_probability(*args, "call")
    below = bs.itm_probability(*args, "put")
    assert above + below == pytest.approx(1.0)
    assert 0.0 < above < 1.0


def test_atm_itm_probability_clears_half_by_the_drift():
    # d2 = (r - q - sigma^2/2)T / (sigma sqrt(T)) = (0.05 - 0.02)/0.2 = 0.15, so Phi(d2) > 1/2.
    # An ATM call is odds-on under Q: the drift r - sigma^2/2 is positive at these inputs.
    p = bs.itm_probability(100, 100, 1.0, 0.05, 0.20, 0.0, "call")
    assert p == pytest.approx(0.5596, abs=1e-4)


def test_itm_probability_is_monotone_in_strike():
    ps = [bs.itm_probability(100, k, 0.5, 0.05, 0.2, 0.0, "call") for k in (80, 95, 100, 110, 130)]
    assert ps == sorted(ps, reverse=True)  # the further out, the less likely


def test_itm_probability_degenerates_to_intrinsic():
    assert bs.itm_probability(110, 100, 0.0, 0.05, 0.2, 0.0, "call") == 1.0
    assert bs.itm_probability(90, 100, 0.0, 0.05, 0.2, 0.0, "call") == 0.0
    assert bs.itm_probability(110, 100, 1.0, 0.05, 0.0, 0.0, "put") == 0.0


def _fair_credit(width: float, p_win: float) -> float:
    """Zero-EV credit for a short vertical: p*c = (1-p)(X-c) solves to c = X(1-p).

    The credit prices the loss, not the win, which is why c/X is the probability of max loss.
    """
    return width * (1 - p_win)


def test_a_fairly_priced_spread_has_no_edge():
    """The point of the page: sell a spread at the model's own price and the pot odds it lays
    you are exactly the model's probability, so the edge is zero. Edge can only come from
    disagreeing with the model."""
    S, K, T, r, sigma, width = 100.0, 95.0, 0.25, 0.0, 0.20, 5.0
    p_model = bs.itm_probability(S, K, T, r, sigma, 0.0, "call")  # stays above the short put
    odds = po.from_credit_vertical(width, _fair_credit(width, p_model))
    assert odds.breakeven == pytest.approx(p_model)
    assert po.edge(p_model, odds) == pytest.approx(0.0, abs=1e-12)
    assert po.expected_value(p_model, odds) == pytest.approx(0.0, abs=1e-12)
    assert po.kelly(p_model, odds) == pytest.approx(0.0, abs=1e-12)  # float dust, not a stake


def test_selling_rich_vol_is_the_edge():
    """Sell at implied vol, get paid at realized vol. IV above RV has to produce a positive edge:
    this is the variance risk premium expressed as pot odds."""
    S, K, T, r, width = 100.0, 95.0, 0.25, 0.0, 5.0
    iv, rv = 0.25, 0.15

    p_iv = bs.itm_probability(S, K, T, r, iv, 0.0, "call")
    p_rv = bs.itm_probability(S, K, T, r, rv, 0.0, "call")
    assert p_rv > p_iv  # calmer vol means the short strike is likelier to hold

    odds = po.from_credit_vertical(width, _fair_credit(width, p_iv))  # priced off the market's vol
    assert odds.breakeven == pytest.approx(p_iv)
    assert po.edge(p_rv, odds) > 0  # ...but the world moves at realized vol
    assert po.expected_value(p_rv, odds) > 0
    assert po.kelly(p_rv, odds) > 0
    assert math.isclose(po.edge(p_rv, odds), p_rv - p_iv, rel_tol=1e-9)


def test_selling_cheap_vol_is_negative_edge():
    """The trade only works one way round. Sell vol below realized and the edge inverts."""
    S, K, T, r, width = 100.0, 95.0, 0.25, 0.0, 5.0
    p_iv = bs.itm_probability(S, K, T, r, 0.15, 0.0, "call")  # market too calm
    p_rv = bs.itm_probability(S, K, T, r, 0.25, 0.0, "call")  # world is wilder

    odds = po.from_credit_vertical(width, _fair_credit(width, p_iv))
    assert po.edge(p_rv, odds) < 0
    assert po.expected_value(p_rv, odds) < 0
    assert po.kelly(p_rv, odds) == 0.0  # no edge, no stake
