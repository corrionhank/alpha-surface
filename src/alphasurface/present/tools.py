"""Tools: the option pricer and pot odds, as dialogs rather than pages.

Open them from the Tools menu in the market bar on any page, or from a contract on the Options
page, which prefills them. Without a contract they start from a symbol's live spot, its IV and
the live risk-free rate, and every input stays editable for what-ifs.
"""

from __future__ import annotations

import math
from typing import TypedDict

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from alphasurface.derive import black_scholes as bs
from alphasurface.derive import pot_odds as po
from alphasurface.derive.market_state import rolling_vol
from alphasurface.present import data, theme
from alphasurface.present.surface_charts import apply_layout


class Prefill(TypedDict, total=False):
    symbol: str
    spot: float
    strike: float
    days: int
    iv: float  # decimal
    kind: str  # call | put
    label: str  # what it came from, e.g. "SPY 580 call, Oct 17"


def request(tool: str, prefill: Prefill | None = None) -> None:
    """Ask for a tool to open on the next run. Use as a button's on_click; the market bar opens
    it, so it works from any page."""
    st.session_state["tool_open"] = tool
    st.session_state["tool_prefill"] = prefill


def open_requested() -> None:
    """Called once per run by the market bar."""
    tool = st.session_state.pop("tool_open", None)
    prefill = st.session_state.pop("tool_prefill", None)
    if tool == "pricer":
        pricer(prefill)
    elif tool == "odds":
        odds(prefill)


def _num(x: float | None, default: float) -> float:
    return default if x is None or x != x else float(x)


def _defaults(prefill: Prefill | None, symbol: str) -> dict:
    """Spot, IV, rate and dividend for a symbol, overridden by whatever the prefill carries."""
    p = prefill or {}
    q = data.quote(symbol) if not p.get("spot") else None
    closes = data.closes(symbol) if not p.get("spot") and q is None else pd.Series(dtype=float)
    spot = p.get("spot") or (q["last"] if q else float(closes.iloc[-1]) if len(closes) else 100.0)
    iv = p.get("iv") or data.implied_vol(symbol, int(p.get("days", 30)))[0]
    return {
        "spot": round(float(spot), 2),
        "strike": float(p.get("strike") or round(float(spot))),
        "days": int(p.get("days", 30)),
        "iv": round(_num(iv, 0.20) * 100, 2),
        "rate": round(data.rate() * 100, 2),
        "div": round(data.dividend_yield(symbol) * 100, 2),
        "kind": p.get("kind", "call"),
    }


def _token(prefill: Prefill | None, symbol: str) -> str:
    """Widget keys change with the source, so a new contract resets the inputs."""
    p = prefill or {}
    return f"{symbol}-{p.get('strike', '')}-{p.get('days', '')}-{p.get('kind', '')}"


def _symbol_input(prefill: Prefill | None, key: str) -> str:
    if prefill and prefill.get("symbol"):
        return data.clean(prefill["symbol"])
    return data.clean(st.text_input("Symbol", value="SPY", key=key, max_chars=12)) or "SPY"


@st.dialog("Option pricer", width="large")
def pricer(prefill: Prefill | None = None) -> None:
    if prefill and prefill.get("label"):
        st.caption(prefill["label"])
    symbol = _symbol_input(prefill, "pr_symbol")
    d = _defaults(prefill, symbol)
    t = _token(prefill, symbol)
    c = st.columns(6)
    S = c[0].number_input("Spot", min_value=0.01, value=d["spot"], step=1.0, key=f"pr_s_{t}")
    K = c[1].number_input("Strike", min_value=0.01, value=d["strike"], step=1.0, key=f"pr_k_{t}")
    days = c[2].number_input("Days", min_value=0, value=d["days"], step=1, key=f"pr_d_{t}")
    sigma = c[3].number_input("IV %", min_value=0.0, value=d["iv"], step=0.5, key=f"pr_v_{t}") / 100
    r = c[4].number_input("Rate %", value=d["rate"], step=0.25, key=f"pr_r_{t}") / 100
    q = c[5].number_input("Div %", min_value=0.0, value=d["div"], step=0.1, key=f"pr_q_{t}") / 100
    T = days / 365

    call, put = bs.greeks(S, K, T, r, sigma, q, "call"), bs.greeks(S, K, T, r, sigma, q, "put")
    m = st.columns(4)
    m[0].metric("Call", f"{call.price:,.2f}")
    m[1].metric("Put", f"{put.price:,.2f}")
    m[2].metric("Call ITM probability", f"{bs.itm_probability(S, K, T, r, sigma, q, 'call'):.0%}")
    m[3].metric("Put ITM probability", f"{bs.itm_probability(S, K, T, r, sigma, q, 'put'):.0%}")

    left, right = st.columns([1, 1.6], gap="medium")
    with left:
        theme.panel_head("Greeks", "Per share")
        greeks = pd.DataFrame(
            {
                "Call": [call.delta, call.gamma, call.vega / 100, call.theta / 365, call.rho / 100],
                "Put": [put.delta, put.gamma, put.vega / 100, put.theta / 365, put.rho / 100],
            },
            index=[
                "Delta",
                "Gamma",
                "Vega, per vol point",
                "Theta, per day",
                "Rho, per rate point",
            ],
        )
        st.dataframe(greeks.style.format("{:+.4f}"), width="stretch")
    with right:
        theme.panel_head("Value against spot", "Today and at expiry")
        st.plotly_chart(
            _value_curve(S, K, T, r, sigma, q),
            width="stretch",
            config={"displayModeBar": False},
            key=f"pr_fig_{t}",
        )


def _value_curve(S: float, K: float, T: float, r: float, sigma: float, q: float) -> go.Figure:
    spots = np.linspace(min(S, K) * 0.8, max(S, K) * 1.2, 120)
    fig = go.Figure()
    for kind, color, dash in (
        ("call", theme.TOKENS["fg"], "solid"),
        ("put", theme.TOKENS["ink_2"], "dash"),
    ):
        now = [bs.price(s, K, T, r, sigma, q, kind) for s in spots]
        expiry = np.maximum(spots - K, 0) if kind == "call" else np.maximum(K - spots, 0)
        fig.add_trace(
            go.Scatter(
                x=spots,
                y=now,
                mode="lines",
                name=kind.title(),
                line={"color": color, "width": 2, "dash": dash},
                hovertemplate=f"spot %{{x:,.2f}}<br>{kind} %{{y:,.2f}}<extra></extra>",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=spots,
                y=expiry,
                mode="lines",
                showlegend=False,
                hoverinfo="skip",
                line={"color": theme.TOKENS["line_strong"], "width": 1, "dash": dash},
            )
        )
    fig.add_vline(
        x=S,
        line={"color": theme.TOKENS["fg_subtle"], "width": 1, "dash": "dot"},
        annotation_text="spot",
        annotation_font_color=theme.TOKENS["fg_subtle"],
    )
    fig = apply_layout(fig, 280)
    fig.update_layout(legend={"orientation": "h", "x": 0, "y": 1.12})
    return fig


@st.dialog("Pot odds", width="large")
def odds(prefill: Prefill | None = None) -> None:
    """The payoff sets the breakeven win rate; implied and realized vol each give a probability of
    winning to hold against it. The gap between those two is the variance risk premium."""
    if prefill and prefill.get("label"):
        st.caption(prefill["label"])
    symbol = _symbol_input(prefill, "po_symbol")
    d = _defaults(prefill, symbol)
    t = _token(prefill, symbol)

    left, right = st.columns([1, 1.5], gap="large")
    with left:
        structure = (
            st.segmented_control(
                "Structure",
                ["Credit vertical", "Debit vertical", "Custom"],
                default="Credit vertical",
                key=f"po_struct_{t}",
            )
            or "Credit vertical"
        )
        if structure == "Custom":
            a, b = st.columns(2)
            risk = a.number_input(
                "Max loss", min_value=0.01, value=300.0, step=10.0, key=f"po_risk_{t}"
            )
            reward = b.number_input(
                "Max gain", min_value=0.01, value=200.0, step=10.0, key=f"po_rew_{t}"
            )
            payoff, multiplier = po.from_payoff(risk, reward), 1
        else:
            a, b = st.columns(2)
            width = a.number_input("Width", min_value=0.5, value=5.0, step=0.5, key=f"po_w_{t}")
            label = "Credit" if structure == "Credit vertical" else "Debit"
            premium = b.number_input(
                label,
                min_value=0.01,
                value=1.65 if label == "Credit" else 1.90,
                step=0.05,
                key=f"po_p_{t}",
            )
            if premium >= width:
                st.error(f"{label} must be less than the width.")
                return
            build = po.from_credit_vertical if label == "Credit" else po.from_debit_vertical
            payoff, multiplier = build(width, premium), 100  # one contract covers 100 shares
        c1, c2 = st.columns(2)
        spot = c1.number_input("Spot", min_value=0.01, value=d["spot"], step=1.0, key=f"po_s_{t}")
        strike = c2.number_input(
            "Deciding strike", min_value=0.01, value=d["strike"], step=1.0, key=f"po_k_{t}"
        )
        above = (
            st.segmented_control(
                "Wins if price finishes",
                ["Above", "Below"],
                default="Above" if d["kind"] == "call" else "Below",
                key=f"po_side_{t}",
            )
            or "Above"
        )
        c3, c4 = st.columns(2)
        days = c3.number_input(
            "Days", min_value=1, value=max(d["days"], 1), step=1, key=f"po_d_{t}"
        )
        iv = (
            c4.number_input(
                "IV %", min_value=0.1, value=max(d["iv"], 0.1), step=0.5, key=f"po_v_{t}"
            )
            / 100
        )
        estimate = st.slider("Your win probability", 0.01, 0.99, 0.70, 0.01, key=f"po_est_{t}")
        lookback = st.slider(
            "Realized vol lookback, sessions", 20, 504, 60, step=10, key=f"po_lb_{t}"
        )

    kind = "call" if above == "Above" else "put"  # a call finishes in the money exactly when above
    T, r, q = days / 365, d["rate"] / 100, d["div"] / 100
    rows = [
        ("Your estimate", estimate),
        (f"Implied vol, {iv:.1%}", bs.itm_probability(spot, strike, T, r, iv, q, kind)),
    ]
    hist = data.closes(symbol, live=False).tail(lookback)
    if len(hist) > 2:
        rv = float(rolling_vol(hist, window=len(hist) - 1).iloc[-1]) / 100
        if not math.isnan(rv):
            rows.append(
                (f"Realized vol, {rv:.1%}", bs.itm_probability(spot, strike, T, r, rv, q, kind))
            )

    with right:
        m = st.columns(4)
        m[0].metric("Breakeven win rate", f"{payoff.breakeven:.1%}", help="R / (R + W)")
        m[1].metric("Odds laid", f"{payoff.ratio:.2f} to 1", help="W / R")
        m[2].metric("Max gain", f"{payoff.reward * multiplier:,.0f}")
        m[3].metric("Max loss", f"{payoff.risk * multiplier:,.0f}")
        theme.panel_head("Win probability by source", "Per contract" if multiplier == 100 else "")
        table = pd.DataFrame(
            {
                "Win probability": [p for _, p in rows],
                "Edge": [po.edge(p, payoff) for _, p in rows],
                "Expected value": [po.expected_value(p, payoff) * multiplier for _, p in rows],
                "Kelly": [po.kelly(p, payoff) for _, p in rows],
            },
            index=[name for name, _ in rows],
        )
        st.dataframe(
            table.style.format(
                {
                    "Win probability": "{:.1%}",
                    "Edge": "{:+.1%}",
                    "Expected value": "{:+,.2f}",
                    "Kelly": "{:.1%}",
                }
            ),
            width="stretch",
        )
