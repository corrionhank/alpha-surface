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

from alphasurface.collector.chains import CHAIN_COLUMNS, SyntheticChains, _today, get_provider
from alphasurface.derive import forward as fw
from alphasurface.derive import vol_surface as vs
from alphasurface.derive.black_scholes import price
from alphasurface.derive.implied_vol import bounds, implied_vol

# The synthetic chain counts tenor in whole days from its own date. At 16:00 New York on that
# date, time to a 16:00 settlement is the same whole number of days, so the two conventions agree.
NOW = pd.Timestamp(f"{_today().date()} 16:00", tz=vs.ET)


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
    amount of tick noise does that. The forward is itself solved from those cent quotes by
    parity, so a cent of forward error leaves a bias of a few thousandths of a vol point; a wrong
    convention leaves tenths.
    """
    provider = SyntheticChains(spot=750.0, rate=0.04, div=0.012)
    chain = provider.chain("TEST")
    surface = vs.build(chain, rate=0.04, div=0.012, now=NOW, moneyness=(0.75, 1.25), max_spread=1.0)

    assert not surface.empty
    expected = np.array(
        [provider.iv(k, t) for k, t in zip(surface["strike"], surface["tenor"], strict=False)]
    )
    error = surface["iv"].to_numpy() - expected

    assert abs(error.mean()) < 5e-5, "systematic bias: the forward or the tenor is wrong"
    assert np.median(np.abs(error)) < 5e-5  # the typical contract is recovered exactly
    assert np.abs(error).max() < 6e-3  # the worst is a sub-dollar contract, one tick wide

    # And the noise must live where the theory says it does: in the cheap contracts.
    cheap = surface["price"] < 1.0
    assert np.median(np.abs(error[cheap])) > np.median(np.abs(error[~cheap]))


def test_build_keeps_only_the_out_of_the_money_side():
    surface = vs.build(SyntheticChains().chain("TEST"), rate=0.04, div=0.012, now=NOW)
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

    kept = vs.build(chain, rate=0.04, div=0.012, now=NOW, min_open_interest=1.0)
    assert (kept["open_interest"] >= 1.0).all()

    tight = vs.build(chain, rate=0.04, div=0.012, now=NOW, max_spread=0.001)
    assert len(tight) < len(vs.build(chain, rate=0.04, div=0.012, now=NOW, max_spread=1.0))


def test_term_structure_slopes_up_for_a_contango_surface():
    surface = vs.build(SyntheticChains(slope=0.04).chain("TEST"), rate=0.04, div=0.012, now=NOW)
    term = vs.atm_term_structure(surface)
    assert len(term) > 3
    assert term["dte"].is_monotonic_increasing
    assert term["atm_iv"].iloc[-1] > term["atm_iv"].iloc[0]  # calm-market term structure


def test_the_put_wing_is_bid_over_the_call_wing():
    """Equity skew: 25-delta puts trade above 25-delta calls. A surface that loses this is wrong."""
    surface = vs.build(SyntheticChains(skew=-0.06).chain("TEST"), rate=0.04, div=0.012, now=NOW)
    expiry = vs.atm_term_structure(surface).iloc[4]["expiry"]
    assert vs.skew_25delta(surface, expiry) > 0


def test_smile_is_ordered_for_plotting():
    surface = vs.build(SyntheticChains().chain("TEST"), rate=0.04, div=0.012, now=NOW)
    expiry = surface["expiry"].iloc[0]
    board = vs.smile(surface, expiry)
    assert board["log_moneyness"].is_monotonic_increasing
    assert (board["expiry"] == expiry).all()


def test_mesh_covers_the_grid_with_no_holes():
    surface = vs.build(SyntheticChains().chain("TEST"), rate=0.04, div=0.012, now=NOW)
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


# --- Forward, Black-76 and the summaries ------------------------------------------------------


def test_parity_recovers_the_forward_the_chain_was_priced_on():
    provider = SyntheticChains(spot=750.0, rate=0.04, div=0.012)
    chain = provider.chain("TEST")
    for expiry, board in chain.groupby("expiry"):
        T = vs.tenor_years(expiry, NOW)
        expected = 750.0 * math.exp((0.04 - 0.012) * T)
        assert fw.parity_forward(board, 0.04, T) == pytest.approx(expected, abs=0.02)


def test_parity_needs_both_sides_quoted():
    board = pd.DataFrame(
        {"strike": [100.0, 100.0], "kind": ["call", "put"], "bid": [2.0, 0.0], "ask": [2.2, 0.0]}
    )
    assert math.isnan(fw.parity_forward(board, 0.04, 0.25))


@pytest.mark.parametrize("sigma", [0.10, 0.25, 0.80])
@pytest.mark.parametrize("K", [90.0, 100.0, 115.0])
@pytest.mark.parametrize("kind", ["call", "put"])
def test_black76_inverts_its_own_price(sigma, K, kind):
    F, T, r = 101.0, 0.4, 0.045
    target = fw.black76_price(F, K, T, r, sigma, kind)
    assert fw.black76_iv(target, F, K, T, r, kind) == pytest.approx(sigma, abs=1e-6)


def test_forward_delta_conventions():
    assert fw.forward_delta(100.0, 100.0, 0.25, 0.2, "call") == pytest.approx(0.52, abs=0.01)
    assert fw.forward_delta(100.0, 100.0, 0.25, 0.2, "put") == pytest.approx(-0.48, abs=0.01)
    assert math.isnan(fw.forward_delta(100.0, 100.0, 0.0, 0.2, "call"))


def test_the_smile_is_continuous_at_the_forward_whatever_the_carry_inputs():
    """Wrong rate and dividend inputs split a spot-based smile at the money; the parity forward
    and Black-76 do not care, because the error cancels between calls and puts."""
    provider = SyntheticChains(spot=750.0, rate=0.04, div=0.012)
    chain = provider.chain("TEST")
    surface = vs.build(chain, rate=0.02, div=0.0, now=NOW, max_spread=1.0)  # both inputs wrong
    expiry = vs.atm_term_structure(surface).iloc[5]["expiry"]
    board = vs.smile(surface, expiry)
    put = board[board["kind"] == "put"].iloc[-1]  # the put just below F
    call = board[board["kind"] == "call"].iloc[0]  # the call just above it
    assert abs(call["iv"] - put["iv"]) < 0.002

    # The old way: Black-Scholes on spot with the same wrong inputs, on the same two strikes.
    raw = chain[chain["expiry"] == expiry].set_index(["strike", "kind"])
    T = put["tenor"]

    def spot_iv(k, kind):
        q = raw.loc[(k, kind)]
        return implied_vol((q["bid"] + q["ask"]) / 2, 750.0, k, T, 0.02, 0.0, kind)

    gap = abs(spot_iv(call["strike"], "call") - spot_iv(put["strike"], "put"))
    assert gap > 0.005  # a visible kink at the money


def test_expiries_are_chosen_across_tenors_and_bounded_by_the_horizon():
    today = pd.Timestamp("2026-10-08")
    listed = [(today + pd.Timedelta(days=d)).strftime("%Y-%m-%d") for d in range(0, 420)]
    six = vs.select_expiries(listed, vs.HORIZONS["6M"], today)
    days = [(pd.Timestamp(e) - today).days for e in six]
    assert days == [7, 14, 21, 30, 45, 60, 90, 120, 180]
    one = vs.select_expiries(listed, vs.HORIZONS["1M"], today)
    assert [(pd.Timestamp(e) - today).days for e in one] == [7, 14, 21, 30]
    year = vs.select_expiries(listed, vs.HORIZONS["1Y"], today)
    assert len(year) == len(vs.TENORS) <= vs.MAX_EXPIRIES
    # Monthlies only: nearest per target, deduplicated, today's expiry left out.
    monthly = ["2026-10-08", "2026-10-16", "2026-11-20", "2026-12-18", "2027-01-15"]
    assert vs.select_expiries(monthly, vs.HORIZONS["3M"], today) == monthly[1:]


def test_the_vol_grid_reads_the_equity_skew():
    surface = vs.build(
        SyntheticChains(skew=-0.06, curve=0.03).chain("TEST"), rate=0.04, div=0.012, now=NOW
    )
    g = vs.grid(surface)
    row = g[g["dte"] == 30].iloc[0]
    assert row["p10"] > row["p25"] > row["atm"] > row["c25"]  # puts bid over calls
    assert row["rr25"] == pytest.approx(row["c25"] - row["p25"])
    assert row["rr25"] < 0 and row["bf25"] > 0  # skewed and smiling
    # The 25-delta point really is 25 delta: rebuild delta from the interpolated vol's strike.
    board = vs.smile(surface, row["expiry"])
    puts = board[board["kind"] == "put"].sort_values("delta")
    k25 = np.interp(-0.25, puts["delta"], puts["strike"])
    d = fw.forward_delta(row["forward"], k25, row["tenor"], row["p25"], "put")
    assert d == pytest.approx(-0.25, abs=0.01)


def test_wings_beyond_the_quoted_strikes_are_blank_not_invented():
    surface = vs.build(SyntheticChains().chain("TEST"), rate=0.04, div=0.012, now=NOW)
    board = vs.smile(surface, surface["expiry"].iloc[0])
    assert math.isnan(vs.iv_at_delta(board, -0.0001))
    heat = vs.heat(surface, np.array([-80.0, 0.0]))
    assert heat[-80.0].isna().all() and heat[0.0].notna().all()


def test_constant_maturity_interpolates_total_variance():
    g = pd.DataFrame(
        {
            "expiry": ["a", "b"],
            "dte": [20, 40],
            "tenor": [20 / 365, 40 / 365],
            "atm": [0.20, 0.30],
            "rr25": [-0.02, -0.04],
            "bf25": [0.01, 0.01],
        }
    )
    at = vs.at_tenor(g, 30)
    w = (0.20**2 * 20 + 0.30**2 * 40) / 2  # variance-time, halfway in T
    assert at["atm"] == pytest.approx(math.sqrt(w / 30))
    assert at["rr25"] == pytest.approx(-0.03) and not at["extrapolated"]
    assert vs.at_tenor(g, 90)["extrapolated"]
    slope, leg = vs.term_slope(g)
    assert leg == 40 and slope == pytest.approx(0.30 - at["atm"])


def test_settlement_time_and_the_floor():
    assert vs.settlement_time("2026-10-16", "PM") == pd.Timestamp("2026-10-16 20:00", tz="UTC")
    assert vs.settlement_time("2026-10-16", "AM") == pd.Timestamp("2026-10-16 13:30", tz="UTC")
    after = pd.Timestamp("2026-10-16 17:00", tz=vs.ET)
    assert vs.tenor_years("2026-10-16", after) == vs.T_MIN
