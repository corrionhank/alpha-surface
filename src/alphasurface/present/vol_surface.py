"""Volatility surface viewer.

Talks to a ChainProvider and nothing else, so attaching a live feed is a change in
collector/chains.py alone. Implied vol is solved here from mid prices rather than taken from the
vendor, so the number and its assumptions are ours.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from alphasurface.collector import feed
from alphasurface.collector.chains import PROVIDERS, default_source, source_label
from alphasurface.derive import vol_surface as vs
from alphasurface.present import surface_charts, theme

with st.sidebar:
    st.header("Chain")
    source = st.selectbox("Source", list(PROVIDERS), index=list(PROVIDERS).index(default_source()))
    symbol = st.text_input("Symbol", value="SPY").strip().upper()

    st.subheader("Model inputs")
    rate = st.number_input("Risk-free rate (%)", value=4.0, step=0.25) / 100
    div = st.number_input("Dividend yield (%)", min_value=0.0, value=1.2, step=0.1) / 100

    st.subheader("Quote filters")
    lo, hi = st.slider("Moneyness (K / spot)", 0.50, 1.50, (0.80, 1.20), 0.01)
    max_spread = st.slider("Max bid-ask spread (% of mid)", 5, 100, 35, 5) / 100
    min_oi = st.number_input("Min open interest", min_value=0, value=0, step=50)

theme.intro("Volatility surface", eyebrow="Options", tag=source_label(source))


@st.cache_data(ttl=300, show_spinner="Pulling chain...")
def load_chain(source: str, symbol: str) -> tuple[pd.DataFrame, list[str]]:
    expiries = feed.expirations(source, symbol)[:10]
    return feed.chain(source, symbol, expiries), expiries  # stored on the way through


try:
    chain, expiries = load_chain(source, symbol)
except Exception as exc:  # a dead symbol or a rate-limited vendor should not blank the page
    st.error(f"Could not load the {symbol} chain from {source}: {exc}")
    st.stop()

if chain.empty:
    st.warning(f"No contracts for {symbol}.")
    st.stop()

surface = vs.build(
    chain,
    rate=rate,
    div=div,
    moneyness=(lo, hi),
    max_spread=max_spread,
    min_open_interest=float(min_oi),
)

if surface.empty:
    st.warning("Every quote was filtered out. Widen the spread or moneyness filters.")
    st.stop()

spot = float(chain["underlying"].iloc[0])
term = vs.atm_term_structure(surface)
stale = (surface["quote"] == vs.QUOTE_LAST).mean()

if stale > 0.5:
    st.warning(f"{stale:.0%} of contracts have no two-sided quote; marks use the last trade.")

front = term.iloc[0] if not term.empty else None
c1, c2, c3, c4 = st.columns(4)
c1.metric("Spot", f"{spot:,.2f}")
c2.metric(
    "Contracts kept",
    f"{len(surface):,}",
    f"of {len(chain):,} quoted",
    delta_color="off",
    delta_arrow="off",
)
if front is not None:
    c3.metric(f"ATM IV ({front['dte']}d)", f"{front['atm_iv']:.2%}")
    slope = term.iloc[-1]["atm_iv"] - front["atm_iv"] if len(term) > 1 else float("nan")
    c4.metric("Term slope", f"{slope:+.2%}", help="Back-month minus front-month ATM IV.")

mesh = vs.mesh(surface)
if mesh is not None:
    with theme.card("surface"):
        theme.panel_head("Surface", "Implied vol by log-moneyness and days to expiry")
        st.plotly_chart(
            surface_charts.surface_3d(mesh), width="stretch", config={"displayModeBar": False}
        )
else:
    st.info("A surface needs at least two expiries.")

left, right = st.columns(2)

with left, theme.card("smile"):
    head, pick = st.columns([1.4, 1], vertical_alignment="center")
    choice = pick.selectbox(
        "Expiry",
        term["expiry"] if not term.empty else surface["expiry"].unique(),
        format_func=lambda e: f"{e}  ({surface[surface['expiry'] == e]['dte'].iloc[0]}d)",
        label_visibility="collapsed",
    )
    skew = vs.skew_25delta(surface, choice)
    skew_txt = f"25-delta skew {skew:+.2%}" if pd.notna(skew) else ""
    head.markdown(
        f'<span class="panel-title">Smile</span> '
        f'<span class="panel-meta" style="display:inline">{skew_txt}</span>',
        unsafe_allow_html=True,
    )
    board = vs.smile(surface, choice)
    st.plotly_chart(
        surface_charts.smile_chart(board, spot), width="stretch", config={"displayModeBar": False}
    )

with right, theme.card("term"):
    theme.panel_head("ATM term structure", "Interpolated at the forward")
    st.plotly_chart(
        surface_charts.term_structure_chart(term), width="stretch", config={"displayModeBar": False}
    )

with st.expander(f"Surface data ({len(surface):,} contracts)"):
    show = surface[
        [
            "expiry",
            "dte",
            "kind",
            "strike",
            "moneyness",
            "bid",
            "ask",
            "price",
            "quote",
            "iv",
            "delta",
            "open_interest",
        ]
    ].copy()
    st.dataframe(
        show.style.format(
            {
                "moneyness": "{:.3f}",
                "bid": "{:.2f}",
                "ask": "{:.2f}",
                "price": "{:.2f}",
                "iv": "{:.2%}",
                "delta": "{:+.3f}",
                "open_interest": "{:,.0f}",
            }
        ),
        width="stretch",
        hide_index=True,
    )
