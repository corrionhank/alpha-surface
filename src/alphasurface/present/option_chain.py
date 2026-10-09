"""Options chain: one expiry as a straddle board, and every number for the contract you click.

Talks to a ChainProvider like the vol surface page, so a live feed attaches in collector/chains.py
alone. IV, Greeks and the rest are ours (derive.option_metrics), solved from the mark with the
rate and dividend set in the sidebar (live defaults from present.data). During the session the
board and the contract panel refresh every 45 seconds; a pull is stored at most every 5 minutes
per expiry. Formulas: docs/formulas.md section 13.
"""

from __future__ import annotations

import math
from html import escape

import pandas as pd
import streamlit as st

from alphasurface.collector import feed
from alphasurface.collector.chains import PROVIDERS, default_source, source_label
from alphasurface.derive import option_metrics as om
from alphasurface.derive.market_state import rolling_vol
from alphasurface.present import data, theme, tools

T = theme.TOKENS
ET = "America/New_York"

st.markdown(
    """<style>
.chain-asof { margin-left: 10px; font-size: 12px; color: var(--fg-subtle); font-variant-numeric: tabular-nums; }
.chain-sides { display: flex; justify-content: space-between; margin: 0 6px 4px;
  font-size: 0.75rem; font-weight: 600; color: var(--fg-subtle); }
/* Full screen is the whole chain panel over the page (header, expiry, every strike), not
   Streamlit's own table fullscreen, which shows the same few rows alone on a blank screen. */
[data-testid="stMain"] .st-key-card-chain-full { position: fixed; inset: 0; z-index: 1000002;
  overflow-y: auto; margin: 0; border: 0; border-radius: 0; padding: 20px 32px 32px; background: var(--surface); }
:is(.st-key-card-chain, .st-key-card-chain-full) [data-testid="stElementToolbarButton"]:has(button[aria-label="Fullscreen"]) {
  display: none; }
.kv { font-size: 0.875rem; font-variant-numeric: tabular-nums; margin-top: 0.25rem; }
.kv-row { display: flex; justify-content: space-between; gap: 12px; padding: 8px 0;
  border-top: 1px solid var(--line); }
.kv-row:first-child { border-top: none; }
.kv-row .k { color: var(--fg-muted); }
.kv-row .v { color: var(--fg); text-align: right; }
.ytable { width: 100%; border-collapse: collapse; font-size: 0.875rem; font-variant-numeric: tabular-nums; }
.ytable th { padding: 0 0 6px; font-size: 0.75rem; font-weight: 400; color: var(--fg-subtle);
  text-align: right; border: none; background: none; }
.ytable td { padding: 8px 0; border: none; border-top: 1px solid var(--line); text-align: right;
  color: var(--fg); background: none; }
.ytable th:first-child, .ytable td:first-child { text-align: left; }
.ytable td:first-child { color: var(--fg-muted); }
</style>""",
    unsafe_allow_html=True,
)


def _fmt(x: float, spec: str, na: str = "n/a") -> str:
    return na if x is None or (isinstance(x, float) and math.isnan(x)) else format(x, spec)


def _kv(rows: list[tuple[str, str]]) -> str:
    cells = "".join(
        f'<div class="kv-row"><span class="k">{k}</span><span class="v">{v}</span></div>'
        for k, v in rows
    )
    return f'<div class="kv">{cells}</div>'


def _stored_rv(symbol: str, window: int) -> float:
    """Close-to-close realized vol over the last `window` sessions, decimal. Bars are live-topped
    and a symbol never seen before is backfilled once, so this works for any symbol."""
    closes = data.closes(symbol)
    if len(closes) <= window:
        return math.nan
    return float(rolling_vol(closes.tail(window * 3), window).iloc[-1]) / 100


def _dte(expiry: str, asof) -> int:
    """Calendar days from the capture date, the same convention as derive.vol_surface."""
    base = pd.Timestamp(asof)
    base = base.tz_localize(None) if base.tzinfo else base
    return max((pd.Timestamp(expiry) - base.normalize()).days, 0)


@st.cache_data(ttl=300, show_spinner="Pulling expiries...")
def load_expiries(source: str, symbol: str) -> list[str]:
    return feed.expirations(source, symbol)


STORE_EVERY = pd.Timedelta(minutes=5)


@st.cache_resource
def _last_stored() -> dict[tuple[str, str, str], pd.Timestamp]:
    """When each (source, symbol, expiry) chain was last stored, shared by every session."""
    return {}


@st.cache_data(ttl=40, show_spinner="Pulling chain...")
def load_chain(source: str, symbol: str, expiry: str) -> pd.DataFrame:
    # Through the gateway, which stores the pull for history; the board refreshes faster than
    # history needs, so only one pull per expiry every STORE_EVERY is kept.
    key, now = (source, symbol, expiry), pd.Timestamp.now(tz="UTC")
    last = _last_stored().get(key)
    store = last is None or now - last >= STORE_EVERY
    frame = feed.chain(source, symbol, [expiry], store=store)
    if store:
        _last_stored()[key] = now
    return frame


@st.cache_data(ttl=40, show_spinner="Solving implied vol...")
def load_board(source: str, symbol: str, expiry: str, rate: float, div: float):
    chain = load_chain(source, symbol, expiry)
    spot = float(chain["underlying"].iloc[0])
    dte = _dte(expiry, chain["ts"].iloc[0])
    return om.straddle(chain, spot, dte, rate, div), spot, dte


with st.sidebar:
    st.header("Chain")
    source = st.selectbox("Source", list(PROVIDERS), index=list(PROVIDERS).index(default_source()))
    symbol = st.text_input("Symbol", value="SPY").strip().upper()

    st.header("Model inputs")
    live_rate, rate_src = data.rate_source()
    rate = (
        st.number_input(
            "Risk-free rate (%)",
            value=round(live_rate * 100, 2),
            step=0.25,
            help=f"From {rate_src}.",
        )
        / 100
    )
    div = (
        st.number_input(
            "Dividend yield (%)",
            min_value=0.0,
            value=round(data.dividend_yield(symbol) * 100, 2),
            step=0.1,
            help="From tastytrade metrics; 0 when unknown.",
        )
        / 100
    )

    st.header("Realized vol")
    window = (
        st.segmented_control(
            "Window (sessions)", [10, 21, 63], default=21, format_func=lambda n: f"{n}d"
        )
        or 21
    )
    rv = _stored_rv(symbol, window)
    rv_stored = not math.isnan(rv)
    if not rv_stored:
        st.caption(f"No daily bars for {symbol}. Enter a realized vol.")
        rv = st.number_input("Realized vol (%)", min_value=0.1, value=15.0, step=0.5) / 100

    st.header("Seller yield")
    fill_at = st.radio("Fill at", ["Bid", "Mid"], horizontal=True)

theme.intro("Options chain", eyebrow="Options", tag=source_label(source))

try:
    expiries = load_expiries(source, symbol)
except Exception as exc:  # a dead symbol or a rate-limited vendor should not blank the page
    st.error(f"Could not list expiries for {symbol} from {source}: {exc}")
    st.stop()
if not expiries:
    st.warning(f"No option expiries for {symbol}.")
    st.stop()

today = pd.Timestamp.now(tz="UTC")

STRIKES = {"10": 10, "20": 20, "40": 40, "All": None}  # strikes each side of the money


def _toggle_full() -> None:
    st.session_state["chain_full"] = not st.session_state.get("chain_full", False)


@st.fragment(run_every=45 if data.market_open() else None)
def board() -> None:
    """The board, the contract panel and its cards. In the session it reruns alone every 45
    seconds; a click on the board reruns only this part too."""
    tiles = st.container()  # filled once the chain is loaded
    full_screen = st.session_state.get("chain_full", False)
    with theme.card("chain-full" if full_screen else "chain"):
        head, count, pick, grow = st.columns([2, 1.3, 1.3, 0.9], vertical_alignment="center")
        title = head.empty()
        title.markdown(
            f'<span class="panel-title">{escape(symbol)} chain</span>', unsafe_allow_html=True
        )
        strikes = (
            count.segmented_control(
                "Strikes",
                list(STRIKES),
                default="20",
                key="chain_strikes",
                label_visibility="collapsed",
            )
            or "20"
        )
        grow.button(
            "Exit full screen" if full_screen else "Full screen",
            icon=":material/fullscreen_exit:" if full_screen else ":material/fullscreen:",
            on_click=_toggle_full,
            type="tertiary",
            width="stretch",
        )
        # Default to the first expiry with time left: a same-day expiry has no tenor to solve IV from.
        first = next((i for i, e in enumerate(expiries) if _dte(e, today) > 0), 0)
        expiry = pick.selectbox(
            "Expiry",
            expiries,
            index=first,
            format_func=lambda e: f"{e}  ({_dte(e, today)}d)",
            label_visibility="collapsed",
        )

        try:
            chain = load_chain(source, symbol, expiry)
        except Exception as exc:
            st.error(f"Could not load the {symbol} {expiry} chain from {source}: {exc}")
            st.stop()
        if chain.empty:
            st.warning(f"No contracts for {symbol} on {expiry}.")
            st.stop()

        pulled = pd.Timestamp(chain["ts"].iloc[0])
        pulled = (pulled if pulled.tzinfo else pulled.tz_localize("UTC")).tz_convert(ET)
        meta = f"As of {pulled:%-I:%M:%S %p} ET"
        coverage = chain.attrs.get("coverage")
        if coverage is not None and coverage < 0.995:
            meta += f", {coverage:.0%} of contracts quoted"
        title.markdown(
            f'<span class="panel-title">{escape(symbol)} chain</span>'
            f'<span class="chain-asof">{meta}</span>',
            unsafe_allow_html=True,
        )

        full, spot, dte = load_board(source, symbol, expiry, rate, div)
        near = int((full["strike"] - spot).abs().argmin())
        each = STRIKES[strikes]
        view = (
            full if each is None else full.iloc[max(near - each, 0) : near + each + 1]
        ).reset_index(drop=True)

        atm = int((view["strike"] - spot).abs().argmin())
        shown = view.drop(columns=["call_iv_from", "put_iv_from"])
        calls = [c for c in shown.columns if c.startswith("call_")]
        puts = [c for c in shown.columns if c.startswith("put_")]

        def _shade(frame: pd.DataFrame) -> pd.DataFrame:
            """In-the-money cells on a raised fill, the strike nearest spot in ink, and an IV
            taken from the other side at its strike in muted italics."""
            styles = pd.DataFrame("", index=frame.index, columns=frame.columns)
            styles.loc[frame["strike"] < spot, calls] = f"background-color: {T['surface_raised']}"
            styles.loc[frame["strike"] > spot, puts] = f"background-color: {T['surface_raised']}"
            styles.loc[atm, "strike"] = f"background-color: {T['fg']}; color: {T['surface']}"
            for kind in ("call", "put"):
                borrowed = view[f"{kind}_iv_from"] != ""
                styles.loc[borrowed, f"{kind}_iv"] += (
                    f"; color: {T['fg_subtle']}; font-style: italic"
                )
            return styles

        fmt = {"strike": lambda k: f"{k:g}"}
        for side in ("call", "put"):
            fmt |= {f"{side}_{f}": "{:.2f}" for f in ("bid", "mark", "ask")}
            fmt |= {
                f"{side}_iv": "{:.1%}",
                f"{side}_delta": "{:+.2f}",
                f"{side}_volume": "{:,.0f}",
                f"{side}_open_interest": "{:,.0f}",
            }
        labels = {
            "bid": "Bid",
            "mark": "Mark",
            "ask": "Ask",
            "iv": "IV",
            "delta": "Delta",
            "volume": "Vol",
            "open_interest": "OI",
        }
        config = {"strike": st.column_config.Column("Strike")}
        config |= {c: st.column_config.Column(labels[c.split("_", 1)[1]]) for c in calls + puts}

        st.markdown(
            '<div class="chain-sides"><span>Calls</span><span>Puts</span></div>',
            unsafe_allow_html=True,
        )
        # The pick survives a refresh and a change of strike count: kept by strike, not by row.
        base = f"{source}-{symbol}-{expiry}"
        saved = st.session_state.get("chain_pick")
        default_cell = (atm, "call_mark")
        if saved and saved[0] == base and (view["strike"] == saved[1]).any():
            default_cell = (int(view.index[view["strike"] == saved[1]][0]), saved[2])
        event = st.dataframe(
            shown.style.apply(_shade, axis=None).format(fmt, na_rep=""),
            key=f"chain-{base}-{strikes}",
            on_select="rerun",
            selection_mode="single-cell",
            selection_default={"selection": {"cells": [default_cell]}},
            hide_index=True,
            column_config=config,
            width="stretch",
            placeholder="",
            # Every row shows without an inner scroll in full screen; inline, about 20 rows.
            height=35 * (len(view) + 1) + 3 if full_screen else min(35 * (len(view) + 1) + 3, 738),
        )
        st.caption(
            "Shaded: in the money. Mark: mid, or last trade without a two-sided quote. "
            "Italic IV: from the other side at that strike."
        )

    if dte == 0:
        st.info("Expires today: IV, Greeks and annualized yields are undefined.")

    stale = (chain["bid"] <= 0) | (chain["ask"] <= chain["bid"])
    if stale.mean() > 0.5:
        st.warning(
            f"{stale.mean():.0%} of contracts have no two-sided quote; marks use the last trade."
        )

    atm_iv = pd.Series([view.at[atm, "call_iv"], view.at[atm, "put_iv"]], dtype=float).mean()
    with tiles:
        a, b, c, d = st.columns(4)
        a.metric("Spot", f"{spot:,.2f}")
        b.metric("Days to expiry", f"{dte}", expiry, delta_color="off", delta_arrow="off")
        c.metric(
            "ATM implied vol",
            _fmt(atm_iv, ".1%"),
            f"strike {view.at[atm, 'strike']:g}",
            delta_color="off",
            delta_arrow="off",
        )
        d.metric(
            f"Realized vol, {window}d",
            _fmt(rv, ".1%"),
            None if rv_stored else "entered",
            delta_color="off",
            delta_arrow="off",
        )

    # The selected cell picks the contract. Nothing selected falls back to the ATM call; a click on the
    # strike column picks the out-of-the-money side at that strike.
    cells = event.selection.get("cells", []) if event else []
    row, col = cells[0] if cells else default_cell
    row = min(int(row), len(view) - 1)
    strike = float(view.at[row, "strike"])
    side = col.split("_", 1)[0] if col != "strike" else ("call" if strike >= spot else "put")
    st.session_state["chain_pick"] = (base, strike, col)

    quote = chain[(chain["kind"] == side) & (chain["strike"] == strike)]
    if quote.empty:
        st.info(f"No {side} quoted at {strike:g} for {expiry}.")
        st.stop()
    q = quote.iloc[0]
    other = om.OTHER[side]
    twin_iv = view.at[row, f"{other}_iv"] if view.at[row, f"{other}_iv_from"] == "" else math.nan
    k = om.contract(
        spot, strike, dte, rate, div, side, q["bid"], q["ask"], q["last"], float(twin_iv), other
    )

    quote_note = (
        theme.badge_html("Last trade, no live quote", "warn") if k.stale else "Mid of bid and ask"
    )
    if k.iv_from:
        quote_note += " " + theme.badge_html(f"IV from the {k.iv_from} at this strike", None)
    theme.panel_head(f"{symbol} {strike:g} {side}, {expiry}", quote_note)
    prefill = {
        "symbol": symbol,
        "spot": spot,
        "strike": strike,
        "days": dte,
        "kind": side,
        "iv": None if math.isnan(k.iv) else k.iv,
        "label": f"{symbol} {strike:g} {side}, {expiry}",
    }
    with st.container(horizontal=True, gap="small"):
        st.button(
            "Open in pricer",
            icon=":material/calculate:",
            on_click=tools.request,
            args=("pricer", prefill),
            type="tertiary",
        )
        st.button(
            "Pot odds",
            icon=":material/percent:",
            on_click=tools.request,
            args=("odds", prefill),
            type="tertiary",
        )

    spread = f"spread {k.spread:.2f}" if not math.isnan(k.spread) else "no two-sided quote"
    r1 = st.columns(4)
    r1[0].metric("Mark", _fmt(k.premium, ".2f"), spread, delta_color="off", delta_arrow="off")
    r1[1].metric(
        "Implied vol",
        _fmt(k.iv, ".1%"),
        f"from the {k.iv_from}" if k.iv_from else None,
        delta_color="off",
        delta_arrow="off",
    )
    r1[2].metric("Intrinsic", _fmt(k.intrinsic, ".2f"))
    r1[3].metric(
        "Extrinsic",
        _fmt(k.extrinsic, ".2f"),
        f"{_fmt(k.extrinsic_pct, '.0%')} of mark",
        delta_color="off",
        delta_arrow="off",
    )
    r2 = st.columns(4)
    r2[0].metric(
        "Extrinsic per day",
        _fmt(k.extrinsic_per_day, ".3f"),
        f"theta {_fmt(k.theta, '+.3f')} at IV",
        delta_color="off",
        delta_arrow="off",
    )
    r2[1].metric(
        "Breakeven at expiry",
        _fmt(k.breakeven, ",.2f"),
        f"{_fmt(k.breakeven_move, '+.2%')} from spot",
        delta_color="off",
        delta_arrow="off",
    )
    r2[2].metric(
        "Probability ITM", _fmt(k.prob_itm, ".0%"), help="Risk-neutral, at the contract's IV."
    )
    r2[3].metric("Contract value", _fmt(k.premium * 100, ",.0f"))

    if k.extrinsic < 0:
        st.info("Mark is below intrinsic, usually a stale or crossed quote.")

    g_col, r_col, y_col = st.columns(3)

    with g_col, theme.card("greeks"):
        theme.panel_head("Greeks", "Per share")
        st.markdown(
            _kv(
                [
                    ("Delta", _fmt(k.delta, "+.3f")),
                    ("Gamma", _fmt(k.gamma, ".4f")),
                    ("Vega, per vol point", _fmt(k.vega, ".3f")),
                    ("Theta, per day", _fmt(k.theta, "+.3f")),
                    ("Rho, per 1% rate", _fmt(k.rho, "+.3f")),
                ]
            ),
            unsafe_allow_html=True,
        )

    v = om.vs_realized(k, rv, rate, div)
    with r_col, theme.card("realized"):
        theme.panel_head("Versus realized vol", theme.badge_html(v.label, None))
        st.markdown(
            _kv(
                [
                    (f"Realized vol, {window}d", _fmt(v.rv, ".1%")),
                    ("Implied vol", _fmt(k.iv, ".1%")),
                    ("IV minus RV", f"{_fmt(v.vol_gap, '+.1f')} pts"),
                    ("Value at realized vol", _fmt(v.model, ".2f")),
                    ("Market minus model", f"{_fmt(v.diff, '+.2f')} ({_fmt(v.diff_pct, '+.0%')})"),
                ]
            ),
            unsafe_allow_html=True,
        )
        st.caption(f"In line within {om.IN_LINE_VOL_PTS:g} vol point.")

    fill, fill_src = om.fill_price(q["bid"], q["ask"], q["last"], at=fill_at.lower())
    with y_col, theme.card("yield"):
        meta = f"Fill {fill_src} {_fmt(fill, '.2f')}"
        if fill_src == om.QUOTE_LAST:
            meta = theme.badge_html(f"Last trade {_fmt(fill, '.2f')}", "warn")
        theme.panel_head("Covered call" if side == "call" else "Cash-secured put", meta)
        rows = "".join(
            f"<tr><td>{y.name}</td><td>{_fmt(y.ret, '.2%')}</td><td>{_fmt(y.annualized, '.1%')}</td>"
            f"<td>{_fmt(y.apy, '.1%')}</td></tr>"
            for y in om.seller_yields(fill, spot, strike, dte, side)
        )
        st.markdown(
            '<table class="ytable"><tr><th></th><th>Return</th><th>Annualized</th><th>APY</th></tr>'
            f"{rows}</table>",
            unsafe_allow_html=True,
        )
        st.caption("Before commissions, dividends and early assignment.")


board()
