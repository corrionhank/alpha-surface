"""Vol surface: the IV solver, the chain cleaning, and the round trip.

The load-bearing test is the round trip. SyntheticChains prices every contract from a known
volatility, so solving that chain back has to return the volatility that went in. If the solver,
the forward, the tenor convention, or the OTM split is wrong anywhere, the round trip breaks.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from alphasurface.collector.chains import CHAIN_COLUMNS, SyntheticChains, get_provider
from alphasurface.derive import vol_surface as vs
from alphasurface.derive.black_scholes import price
from alphasurface.derive.implied_vol import bounds, implied_vol


@pytest.mark.parametrize("sigma", [0.08, 0.20, 0.65, 1.50])
@pytest.mark.parametrize("K", [80.0, 100.0, 130.0])
@pytest.mark.parametrize("kind", ["call", "put"])
def test_implied_vol_inverts_the_pricer(sigma, K, kind):
    S, T, r, q = 100.0, 0.5, 0.04, 0.01
    target = price(S, K, T, r, sigma, q, kind)
    assert implied_vol(target, S, K, T, r, q, kind) == pytest.approx(sigma, abs=1e-6)


def test_prices_outside_the_no_arb_bounds_have_no_solution():
    S, K, T, r, q = 100.0, 100.0, 1.0, 0.04, 0.0
    low, high = bounds(S, K, T, r, q, "call")
    assert math.isnan(implied_vol(low - 0.01, S, K, T, r, q, "call"))  # below intrinsic
    assert math.isnan(implied_vol(high + 0.01, S, K, T, r, q, "call"))  # above the forward
    assert math.isnan(implied_vol(0.0, S, K, T, r, q, "call"))
    assert math.isnan(implied_vol(5.0, S, K, 0.0, r, q, "call"))  # expired


def test_a_price_at_intrinsic_has_no_volatility():
    # A quote exactly at intrinsic implies zero vol, which is not a number the surface can use.
    intrinsic = 100 * math.exp(-0.0) - 90 * math.exp(-0.04 * 1.0)
    assert math.isnan(implied_vol(intrinsic, 100.0, 90.0, 1.0, 0.04, 0.0, "call"))


def test_deep_wing_quotes_still_solve():
    # Vega collapses here, which is exactly where Newton would fall over and Brent does not.
    target = price(100.0, 200.0, 0.05, 0.04, 0.60, 0.0, "call")
    assert implied_vol(target, 100.0, 200.0, 0.05, 0.04, 0.0, "call") == pytest.approx(
        0.60, abs=1e-5
    )


def test_synthetic_chain_has_the_provider_contract():
    chain = SyntheticChains().chain("TEST")
    assert list(chain.columns) == CHAIN_COLUMNS
    assert not chain.empty
    assert set(chain["kind"]) == {"call", "put"}
    assert (chain["ask"] > chain["bid"]).all()


def test_the_surface_round_trips_the_volatility_it_was_priced_from():
    """The one that matters. Solve the synthetic chain and recover its own smile.

    The chain is quoted in whole cents, like a real market, so the recovered vol cannot be exact:
    on a contract worth 40 cents, one tick of rounding is a fifth of a vol point. That noise is
    physical and is asserted loosely. What is asserted tightly is the *bias*, because a wrong
    forward, tenor convention or OTM split would shift every point in the same direction, and no
    amount of tick noise does that.
    """
    provider = SyntheticChains(spot=750.0, rate=0.04, div=0.012)
    chain = provider.chain("TEST")
    surface = vs.build(chain, rate=0.04, div=0.012, moneyness=(0.75, 1.25), max_spread=1.0)

    assert not surface.empty
    expected = np.array(
        [provider.iv(k, t) for k, t in zip(surface["strike"], surface["tenor"], strict=False)]
    )
    error = surface["iv"].to_numpy() - expected

    assert abs(error.mean()) < 1e-5, "systematic bias: the forward or the tenor is wrong"
    assert np.median(np.abs(error)) < 5e-5  # the typical contract is recovered exactly
    assert np.abs(error).max() < 6e-3  # the worst is a sub-dollar contract, one tick wide

    # And the noise must live where the theory says it does: in the cheap contracts.
    cheap = surface["price"] < 1.0
    assert np.median(np.abs(error[cheap])) > np.median(np.abs(error[~cheap]))


def test_build_keeps_only_the_out_of_the_money_side():
    surface = vs.build(SyntheticChains().chain("TEST"), rate=0.04, div=0.012)
    calls, puts = surface[surface["kind"] == "call"], surface[surface["kind"] == "put"]
    assert (calls["strike"] >= calls["forward"]).all()
    assert (puts["strike"] < puts["forward"]).all()


def test_mid_falls_back_to_last_when_the_market_is_closed():
    chain = pd.DataFrame(
        {
            "bid": [0.0, 1.0],
            "ask": [0.0, 1.4],
            "last": [2.5, 1.1],
        }
    )
    mid, source = vs.mid_price(chain)
    assert mid.tolist() == [2.5, 1.2]  # closed -> last; open -> the mid
    assert source.tolist() == [vs.QUOTE_LAST, vs.QUOTE_MID]


def test_wide_and_illiquid_quotes_are_dropped():
    provider = SyntheticChains()
    chain = provider.chain("TEST")
    chain.loc[chain.index[:20], "open_interest"] = 0.0

    kept = vs.build(chain, rate=0.04, div=0.012, min_open_interest=1.0)
    assert (kept["open_interest"] >= 1.0).all()

    tight = vs.build(chain, rate=0.04, div=0.012, max_spread=0.001)
    assert len(tight) < len(vs.build(chain, rate=0.04, div=0.012, max_spread=1.0))


def test_term_structure_slopes_up_for_a_contango_surface():
    surface = vs.build(SyntheticChains(slope=0.04).chain("TEST"), rate=0.04, div=0.012)
    term = vs.atm_term_structure(surface)
    assert len(term) > 3
    assert term["dte"].is_monotonic_increasing
    assert term["atm_iv"].iloc[-1] > term["atm_iv"].iloc[0]  # calm-market term structure


def test_the_put_wing_is_bid_over_the_call_wing():
    """Equity skew: 25-delta puts trade above 25-delta calls. A surface that loses this is wrong."""
    surface = vs.build(SyntheticChains(skew=-0.06).chain("TEST"), rate=0.04, div=0.012)
    expiry = vs.atm_term_structure(surface).iloc[4]["expiry"]
    assert vs.skew_25delta(surface, expiry) > 0


def test_smile_is_ordered_for_plotting():
    surface = vs.build(SyntheticChains().chain("TEST"), rate=0.04, div=0.012)
    expiry = surface["expiry"].iloc[0]
    board = vs.smile(surface, expiry)
    assert board["log_moneyness"].is_monotonic_increasing
    assert (board["expiry"] == expiry).all()


def test_mesh_covers_the_grid_with_no_holes():
    surface = vs.build(SyntheticChains().chain("TEST"), rate=0.04, div=0.012)
    xi, yi, zi = vs.mesh(surface)
    assert zi.shape == (len(yi), len(xi))
    assert np.isfinite(zi).all()  # nearest-neighbour fill leaves no gaps in the wings


def test_an_empty_chain_does_not_explode():
    empty = pd.DataFrame(columns=CHAIN_COLUMNS)
    assert vs.build(empty).empty
    assert vs.mesh(pd.DataFrame(columns=["expiry"])) is None


def test_providers_are_registered():
    assert get_provider("synthetic").name == "synthetic"
    assert get_provider("yfinance").name == "yfinance"
    with pytest.raises(KeyError):
        get_provider("not-a-feed")
