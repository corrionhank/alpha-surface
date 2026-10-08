"""Pot odds page: the payoff sets the breakeven win rate, and three sources of win
probability get measured against it. The market's odds come from implied vol, history's
odds from realized vol, and the gap between them is the variance risk premium."""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from derive import black_scholes as bs
from derive import pot_odds as po
from present import data, theme
from present.summary import realized_vol
from storage import reader

theme.intro("Pot odds", eyebrow="Pricing")

conn = data.conn()
symbols = sorted(set(reader.available_symbols(conn, interval="1d")) | {"SPY", "QQQ", "IWM", "DIA"})

with st.sidebar:
    st.header("Structure")
    structure = st.radio(
        "Position", ["Credit vertical", "Debit vertical", "Custom payoff"], label_visibility="collapsed"
    )

    if structure == "Custom payoff":
        risk = st.number_input("Max loss (R)", min_value=0.01, value=300.0, step=10.0)
        reward = st.number_input("Max gain (W)", min_value=0.01, value=200.0, step=10.0)
        odds, multiplier, unit = po.from_payoff(risk, reward), 1, ""
    else:
        width = st.number_input("Spread width", min_value=0.5, value=5.0, step=0.5)
        if structure == "Credit vertical":
            credit = st.number_input("Credit received", min_value=0.01, value=1.65, step=0.05)
            if credit >= width:
                st.error("Credit must be less than the width.")
                st.stop()
            odds = po.from_credit_vertical(width, credit)
        else:
            debit = st.number_input("Debit paid", min_value=0.01, value=1.90, step=0.05)
            if debit >= width:
                st.error("Debit must be less than the width.")
                st.stop()
            odds = po.from_debit_vertical(width, debit)
        multiplier, unit = 100, " per contract"  # one option contract covers 100 shares

    st.header("Win probability")
    p_manual = st.slider("Your estimate", 0.01, 0.99, 0.70, 0.01)

    st.subheader("Model inputs")
    symbol = data.clean(st.selectbox(
        "Symbol", symbols, index=symbols.index("SPY"), accept_new_options=True,
    ) or "SPY")
    live = data.quote(symbol)
    hist = data.closes(symbol)
    spot_default = float(live["last"]) if live else (float(hist.iloc[-1]) if len(hist) else 0.0)
    m = data.metrics(symbol)
    iv_default = float(m["ivx"]) * 100 if m is not None and m.get("ivx") == m.get("ivx") and m.get("ivx") else 18.0
    spot = st.number_input("Spot", min_value=0.01, value=spot_default or 100.0, step=1.0)
    strike = st.number_input("Strike that decides the trade", min_value=0.01, value=round(spot * 0.97, 0), step=1.0)
    side = st.radio("Wins if price finishes", ["Above the strike", "Below the strike"])
    days = st.number_input("Days to expiry", min_value=1, value=30, step=1)
    iv = st.number_input("Implied vol (%)", min_value=0.1, value=round(iv_default, 1), step=0.5,
                         help="Defaults to the symbol's tastytrade IVx.") / 100
    r = st.number_input("Risk-free rate (%)", value=5.0, step=0.25) / 100
    q = st.number_input("Dividend yield (%)", min_value=0.0, value=0.0, step=0.25) / 100
    lookback = st.slider("Realized vol lookback (daily bars)", 20, 504, 60, step=10)

# A call is in the money exactly when the price finishes above the strike, so the same
# function answers both directions.
option_kind = "call" if side == "Above the strike" else "put"
T = days / 365

c1, c2, c3, c4 = st.columns(4)
c1.metric("Breakeven win rate", f"{odds.breakeven:.1%}", help="p* = R / (R + W)")
c2.metric("Odds laid", f"{odds.ratio:.2f} : 1", help="b = W / R")
c3.metric("Max gain (W)", f"{odds.reward * multiplier:,.0f}")
c4.metric("Max loss (R)", f"{odds.risk * multiplier:,.0f}")

rows = [("Your estimate", p_manual), (f"Implied vol ({iv:.1%})", bs.itm_probability(spot, strike, T, r, iv, q, option_kind))]

rv = float("nan")
if len(hist) > 2:
    rv = realized_vol(hist.tail(lookback), "1d") / 100
if not math.isnan(rv):
    rows.append((f"Realized vol ({rv:.1%})", bs.itm_probability(spot, strike, T, r, rv, q, option_kind)))

odds_card = theme.card("odds")
with odds_card:
    theme.panel_head("Win probability by source", "Expected value per contract" if unit else "")
table = pd.DataFrame(
    {
        "Win probability": [p for _, p in rows],
        "Edge": [po.edge(p, odds) for _, p in rows],
        f"Expected value{unit}": [po.expected_value(p, odds) * multiplier for _, p in rows],
        "Kelly": [po.kelly(p, odds) for _, p in rows],
    },
    index=[label for label, _ in rows],
)
odds_card.dataframe(
    table.style.format({"Win probability": "{:.1%}", "Edge": "{:+.1%}", f"Expected value{unit}": "{:+,.2f}", "Kelly": "{:.1%}"}),
    width="stretch",
)
