"""Single-contract metrics: what one option costs, how much of that is time, and what selling it
pays. Formulas: docs/formulas.md section 13.

Everything is computed from the quote and the spot with our own implied vol (derive.implied_vol),
so the numbers carry our rate and dividend assumptions rather than a vendor's. Units follow
derive.black_scholes: rates and vols are decimals, time is calendar days to expiry over 365.

Descriptive only. "Overpriced vs realized" says the market price sits above a Black-Scholes value
at trailing realized vol. That is a statement about the past, not a forecast and not a trade.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import pandas as pd

from alphasurface.derive.black_scholes import greeks, itm_probability, price
from alphasurface.derive.implied_vol import implied_vol

QUOTE_MID, QUOTE_LAST = "mid", "last"  # the same tags derive.vol_surface uses

# |IV - RV| inside this many vol points reads as in line. Price rises with vol, so the sign of the
# vol gap is the sign of the dollar gap; measuring it in vol points keeps one tolerance meaningful
# across strikes, where the dollar gap shrinks with vega.
IN_LINE_VOL_PTS = 1.0

NAN = math.nan


def _num(x) -> float:
    """Float or NaN. Vendors hand back None, NaN and zero for 'no quote'; treat them alike."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return NAN
    return x if math.isfinite(x) else NAN


def mark(bid, ask, last) -> tuple[float, str]:
    """Mid of a two-sided market, else the last print. Same rule as vol_surface.mid_price."""
    bid, ask, last = _num(bid), _num(ask), _num(last)
    if bid > 0 and ask > bid:
        return (bid + ask) / 2, QUOTE_MID
    return (last if last > 0 else NAN), QUOTE_LAST


def intrinsic(S: float, K: float, kind: str) -> float:
    """Spot-based: what exercising right now is worth."""
    return max(S - K, 0.0) if kind == "call" else max(K - S, 0.0)


@dataclass(frozen=True)
class Contract:
    kind: str
    spot: float
    strike: float
    dte: int
    premium: float  # the mark
    quote: str  # mid | last
    spread: float  # ask - bid; NaN without a two-sided market
    spread_pct: float  # spread / mark
    iv: float
    intrinsic: float
    extrinsic: float  # premium - intrinsic; can be negative, see docs section 13
    extrinsic_pct: float  # extrinsic / premium
    extrinsic_per_day: float  # extrinsic / calendar days left
    breakeven: float  # at expiry, for the buyer
    breakeven_move: float  # breakeven / spot - 1
    prob_itm: float  # risk-neutral, at IV
    delta: float
    gamma: float
    vega: float  # per vol point
    theta: float  # per calendar day
    rho: float  # per 1% of rate
    iv_from: str = ""  # "" when solved from this contract's price; "call" or "put" when borrowed

    @property
    def stale(self) -> bool:
        return self.quote == QUOTE_LAST


def contract(
    S: float,
    K: float,
    dte: int,
    r: float,
    q: float,
    kind: str,
    bid,
    ask,
    last,
    iv_override: float = NAN,
    iv_from: str = "",
) -> Contract:
    """Every per-contract number the chain page shows, from one quote.

    When this price does not solve for an IV (deep in the money, where a wide quote often sits
    under the no-arbitrage bound) and `iv_override` is given, the Greeks and probability use it:
    the other side's IV at the same strike, which put-call parity makes the same number.
    `iv_from` names that side and is kept on the result so a page can say so."""
    S, K, dte = float(S), float(K), int(dte)
    premium, quote = mark(bid, ask, last)
    two_sided = quote == QUOTE_MID
    spread = _num(ask) - _num(bid) if two_sided else NAN
    T = max(dte, 0) / 365

    intr = intrinsic(S, K, kind)
    extr = premium - intr
    iv = implied_vol(premium, S, K, T, r, q, kind)  # NaN for no price, no time, or out of bounds
    if not iv > 0 and iv_override > 0:
        iv = float(iv_override)
    else:
        iv_from = ""

    if iv > 0:
        g = greeks(S, K, T, r, iv, q, kind)
        delta, gamma, vega, theta, rho = g.delta, g.gamma, g.vega / 100, g.theta / 365, g.rho / 100
        p_itm = itm_probability(S, K, T, r, iv, q, kind)
    else:
        delta = gamma = vega = theta = rho = p_itm = NAN

    breakeven = K + premium if kind == "call" else K - premium
    return Contract(
        kind=kind,
        spot=S,
        strike=K,
        dte=dte,
        premium=premium,
        quote=quote,
        spread=spread,
        spread_pct=spread / premium if two_sided else NAN,
        iv=iv,
        intrinsic=intr,
        extrinsic=extr,
        extrinsic_pct=extr / premium if premium > 0 else NAN,
        extrinsic_per_day=extr / dte if dte > 0 else NAN,
        breakeven=breakeven,
        breakeven_move=breakeven / S - 1,
        prob_itm=p_itm,
        delta=delta,
        gamma=gamma,
        vega=vega,
        theta=theta,
        rho=rho,
        iv_from=iv_from,
    )


@dataclass(frozen=True)
class VsRealized:
    rv: float
    model: float  # Black-Scholes value at realized vol
    diff: float  # market - model, per share
    diff_pct: float  # diff / model
    vol_gap: float  # (IV - RV) in vol points
    label: str


def valuation_label(vol_gap: float, tol: float = IN_LINE_VOL_PTS) -> str:
    if math.isnan(vol_gap):
        return "No implied vol"
    if vol_gap > tol:
        return "Overpriced vs realized"
    if vol_gap < -tol:
        return "Underpriced vs realized"
    return "In line"


def vs_realized(c: Contract, rv: float, r: float, q: float) -> VsRealized:
    """The market's price against the same contract priced at trailing realized vol."""
    rv = _num(rv)
    model = price(c.spot, c.strike, max(c.dte, 0) / 365, r, rv, q, c.kind) if rv > 0 else NAN
    diff = c.premium - model
    gap = (c.iv - rv) * 100
    return VsRealized(
        rv=rv,
        model=model,
        diff=diff,
        diff_pct=diff / model if model > 0 else NAN,
        vol_gap=gap,
        label=valuation_label(gap),
    )


def fill_price(bid, ask, last, at: str = "bid") -> tuple[float, str]:
    """The premium a seller can expect. At the bid by default, since a sell at market hits it; at
    the mark when asked. With no bid (a closed market) it falls back to the last print and says so
    in the returned source."""
    if at == "bid":
        b = _num(bid)
        if b > 0:
            return b, "bid"
        lp = _num(last)
        return (lp if lp > 0 else NAN), QUOTE_LAST
    return mark(bid, ask, last)


def annualize(ret: float, dte: int) -> tuple[float, float]:
    """Simple annualized (ret x 365/dte) and compounded APY ((1 + ret)^(365/dte) - 1)."""
    if not dte > 0 or math.isnan(ret) or ret <= -1:
        return NAN, NAN
    n = 365 / dte
    try:
        apy = (1 + ret) ** n - 1
    except OverflowError:  # a weekly return compounded 52 times can outgrow a float
        apy = math.inf
    return ret * n, apy


@dataclass(frozen=True)
class Yield:
    name: str
    ret: float  # over the life of the trade
    annualized: float
    apy: float


def seller_yields(premium: float, S: float, K: float, dte: int, kind: str) -> list[Yield]:
    """Return on the cash tied up by selling one contract.

    Covered call: hold the shares, sell the call; the cash at work is spot less the premium taken
    in. Cash-secured put: hold the strike in cash; the cash at work is the strike less the premium.

    If unchanged is the return when the stock ends where it is now, so only the time value is
    kept: an in-the-money option gets exercised and hands its intrinsic back. Counting intrinsic
    as yield is what makes deep in-the-money sales look like free money. The second row is the
    best case: the call is called away at the strike, or the put expires worthless. Commissions,
    dividends and early assignment are ignored.
    """
    premium = _num(premium)
    kept = premium - intrinsic(S, K, kind)
    if kind == "call":
        basis = S - premium
        rows = [("If unchanged", kept), ("If called", premium + K - S)]
    else:
        basis = K - premium
        rows = [("If unchanged", kept), ("If not assigned", premium)]

    out = []
    for name, gain in rows:
        ret = gain / basis if premium > 0 and basis > 0 else NAN
        out.append(Yield(name, ret, *annualize(ret, dte)))
    return out


_SIDE_FIELDS = ["bid", "mark", "ask", "iv", "delta", "volume", "open_interest"]
OTHER = {"call": "put", "put": "call"}


def straddle(board: pd.DataFrame, S: float, dte: int, r: float, q: float) -> pd.DataFrame:
    """One expiry as a straddle view: a row per strike, call fields and put fields side by side,
    columns named call_<field>, strike, put_<field>. IV and delta are ours, solved per contract.

    A contract whose price does not solve for an IV takes the other side's solved IV at the same
    strike (see contract()); <side>_iv_from names the side it came from, "" when its own."""
    quotes = {
        kind: board[board["kind"] == kind].drop_duplicates("strike").set_index("strike")
        for kind in ("call", "put")
    }
    own = {
        kind: {
            float(K): contract(S, K, dte, r, q, kind, rec.bid, rec.ask, rec.last)
            for K, rec in quotes[kind].iterrows()
        }
        for kind in quotes
    }
    sides = {}
    for kind, contracts in own.items():
        rows = []
        for K, c in contracts.items():
            twin = own[OTHER[kind]].get(K)
            if not c.iv > 0 and twin is not None and twin.iv > 0:
                rec = quotes[kind].loc[K]
                c = contract(
                    S, K, dte, r, q, kind, rec.bid, rec.ask, rec.last, twin.iv, OTHER[kind]
                )
            rec = quotes[kind].loc[K]
            rows.append(
                {
                    "strike": K,
                    "bid": _num(rec.bid),
                    "mark": c.premium,
                    "ask": _num(rec.ask),
                    "iv": c.iv,
                    "delta": c.delta,
                    "volume": _num(rec.volume),
                    "open_interest": _num(rec.open_interest),
                    "iv_from": c.iv_from,
                }
            )
        side = pd.DataFrame(rows, columns=["strike", *_SIDE_FIELDS, "iv_from"])
        sides[kind] = side.set_index("strike").add_prefix(f"{kind}_")

    view = sides["call"].join(sides["put"], how="outer").sort_index().reset_index()
    for kind in ("call", "put"):
        view[f"{kind}_iv_from"] = view[f"{kind}_iv_from"].fillna("")
    # Mirrored around the strike, prices innermost, both sides still reading bid then ask.
    calls = ["open_interest", "volume", "delta", "iv", "bid", "mark", "ask"]
    return view[
        [
            *(f"call_{f}" for f in calls),
            "strike",
            *(f"put_{f}" for f in _SIDE_FIELDS),
            "call_iv_from",
            "put_iv_from",
        ]
    ]
