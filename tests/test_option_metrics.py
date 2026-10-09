"""Single-contract metrics: the arithmetic the chain page shows next to a selected option."""

from __future__ import annotations

import math

import pytest

from alphasurface.collector.chains import SyntheticChains
from alphasurface.derive import option_metrics as om
from alphasurface.derive.black_scholes import price

S, R, Q = 100.0, 0.04, 0.01


def test_mark_is_the_mid_of_a_two_sided_market_else_last():
    assert om.mark(1.00, 1.20, 1.50) == (pytest.approx(1.10), om.QUOTE_MID)
    assert om.mark(0.0, 0.0, 1.50) == (1.50, om.QUOTE_LAST)  # closed market
    assert om.mark(1.20, 1.00, 1.50) == (1.50, om.QUOTE_LAST)  # crossed is not a market
    price_, src = om.mark(None, float("nan"), 0.0)  # nothing at all
    assert math.isnan(price_) and src == om.QUOTE_LAST


def test_intrinsic_and_extrinsic_split_the_premium():
    c = om.contract(S, 95.0, 30, R, Q, "call", 6.90, 7.10, 7.0)
    assert c.premium == pytest.approx(7.00)
    assert c.intrinsic == pytest.approx(5.00)
    assert c.extrinsic == pytest.approx(2.00)
    assert c.extrinsic_pct == pytest.approx(2.0 / 7.0)
    assert c.extrinsic_per_day == pytest.approx(2.0 / 30)
    assert c.spread == pytest.approx(0.20)
    assert c.spread_pct == pytest.approx(0.20 / 7.0)
    assert c.breakeven == pytest.approx(102.0)
    assert c.breakeven_move == pytest.approx(0.02)

    p = om.contract(S, 95.0, 30, R, Q, "put", 0.90, 1.10, 1.0)
    assert p.intrinsic == 0.0 and p.extrinsic == pytest.approx(1.00)  # all time value
    assert p.breakeven == pytest.approx(94.0)


@pytest.mark.parametrize("kind", ["call", "put"])
@pytest.mark.parametrize("K", [90.0, 100.0, 110.0])
def test_iv_round_trips_a_black_scholes_price(kind, K):
    fair = price(S, K, 45 / 365, R, 0.22, Q, kind)
    c = om.contract(S, K, 45, R, Q, kind, fair - 0.005, fair + 0.005, fair)
    assert c.iv == pytest.approx(0.22, abs=1e-4)
    assert 0 < c.prob_itm < 1
    assert c.theta < 0 and c.vega > 0 and c.gamma > 0


def test_put_call_parity_holds_through_the_metrics():
    K, dte = 105.0, 60
    T = dte / 365
    call = price(S, K, T, R, 0.25, Q, "call")
    put = price(S, K, T, R, 0.25, Q, "put")
    c = om.contract(S, K, dte, R, Q, "call", call - 0.01, call + 0.01, call)
    p = om.contract(S, K, dte, R, Q, "put", put - 0.01, put + 0.01, put)
    assert c.premium - p.premium == pytest.approx(S * math.exp(-Q * T) - K * math.exp(-R * T))
    assert c.iv == pytest.approx(p.iv, abs=1e-4)  # one volatility prices both sides
    assert c.delta - p.delta == pytest.approx(math.exp(-Q * T), abs=1e-6)


def test_vs_realized_labels_follow_the_vol_gap():
    fair = price(S, 100.0, 30 / 365, R, 0.20, Q, "call")
    c = om.contract(S, 100.0, 30, R, Q, "call", fair - 0.01, fair + 0.01, fair)

    rich = om.vs_realized(c, 0.15, R, Q)
    assert rich.vol_gap == pytest.approx(5.0, abs=0.05)
    assert rich.diff > 0 and rich.label == "Overpriced vs realized"
    assert rich.model == pytest.approx(price(S, 100.0, 30 / 365, R, 0.15, Q, "call"))

    cheap = om.vs_realized(c, 0.25, R, Q)
    assert cheap.diff < 0 and cheap.label == "Underpriced vs realized"

    assert om.vs_realized(c, 0.205, R, Q).label == "In line"  # inside the 1 vol point band
    assert math.isnan(om.vs_realized(c, float("nan"), R, Q).model)


def test_seller_yields_on_hand_computed_values():
    # Covered call: spot 100, sell the 105 call for 2 with 30 days left. Cash at work is 98.
    static, called = om.seller_yields(2.0, 100.0, 105.0, 30, "call")
    assert static.ret == pytest.approx(2 / 98)
    assert called.ret == pytest.approx(7 / 98)
    assert static.annualized == pytest.approx(2 / 98 * 365 / 30)
    assert static.apy == pytest.approx((1 + 2 / 98) ** (365 / 30) - 1)

    # Cash-secured put: sell the 95 put for 1.5. Cash at work is 93.5; no intrinsic to hand back.
    unchanged, kept_all = om.seller_yields(1.5, 100.0, 95.0, 30, "put")
    assert unchanged.ret == kept_all.ret == pytest.approx(1.5 / 93.5)


def test_intrinsic_is_not_counted_as_yield():
    # In-the-money call: spot 100, the 95 call for 7. Unchanged means called, so both rows keep 2.
    static, called = om.seller_yields(7.0, 100.0, 95.0, 30, "call")
    assert static.ret == pytest.approx(2 / 93) and called.ret == pytest.approx(2 / 93)

    # In-the-money put: the 105 put for 6 is 5 intrinsic. Unchanged keeps 1, not 6.
    unchanged, not_assigned = om.seller_yields(6.0, 100.0, 105.0, 30, "put")
    assert unchanged.ret == pytest.approx(1 / 99)
    assert not_assigned.ret == pytest.approx(6 / 99)


def test_fill_price_prefers_the_bid_and_says_when_it_could_not():
    assert om.fill_price(1.0, 1.2, 1.1) == (1.0, "bid")
    assert om.fill_price(0.0, 0.0, 1.1) == (1.1, om.QUOTE_LAST)  # no bid: last, flagged
    assert om.fill_price(1.0, 1.2, 1.1, at="mid") == (pytest.approx(1.1), om.QUOTE_MID)


def test_zero_days_to_expiry_does_not_divide_by_zero():
    c = om.contract(S, 95.0, 0, R, Q, "call", 5.0, 5.2, 5.1)
    assert c.intrinsic == 5.0 and c.extrinsic == pytest.approx(0.1)
    assert math.isnan(c.iv) and math.isnan(c.extrinsic_per_day) and math.isnan(c.delta)
    assert all(math.isnan(y.annualized) for y in om.seller_yields(5.1, S, 95.0, 0, "call"))


def test_no_price_at_all_leaves_everything_unknown():
    c = om.contract(S, 120.0, 30, R, Q, "call", 0.0, 0.0, 0.0)
    assert math.isnan(c.premium) and math.isnan(c.iv) and math.isnan(c.extrinsic)
    assert all(math.isnan(y.ret) for y in om.seller_yields(c.premium, S, 120.0, 30, "call"))


def test_a_quote_below_intrinsic_shows_negative_extrinsic():
    # Stale or crossed: the number is shown, not hidden, and admits no implied vol.
    c = om.contract(S, 90.0, 30, R, Q, "call", 9.0, 9.4, 9.2)
    assert c.extrinsic == pytest.approx(-0.8)
    assert math.isnan(c.iv)


def test_annualize_survives_absurd_compounding():
    simple, apy = om.annualize(50.0, 1)  # 51 ** 365 is past the largest float
    assert simple == pytest.approx(18250.0) and apy == math.inf
    assert all(math.isnan(x) for x in om.annualize(-1.0, 30))  # a total loss has no rate


def test_straddle_puts_calls_and_puts_side_by_side():
    provider = SyntheticChains(spot=750.0, rate=R, div=Q)
    expiry = provider.expirations("TEST")[2]
    board = provider.chain("TEST", [expiry])
    view = om.straddle(board, 750.0, 30, R, Q)

    assert view.columns[7] == "strike"
    assert view["strike"].is_monotonic_increasing and view["strike"].is_unique
    assert view.columns[:7].str.startswith("call_").all()
    assert view.columns[8:].str.startswith("put_").all()
    atm = view.iloc[(view["strike"] - 750.0).abs().argmin()]
    assert atm["call_iv"] == pytest.approx(atm["put_iv"], abs=5e-3)  # one smile, both sides
