"""Black-Scholes pricing page: inputs, price and Greeks, value-vs-spot curve."""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from derive import black_scholes as bs
from present import theme
from present.surface_charts import apply_layout

theme.intro("Black-Scholes pricing", eyebrow="Pricing", tag="European, continuous dividend")

with st.sidebar:
    st.header("Inputs")
    S = st.number_input("Spot (S)", min_value=0.01, value=100.0, step=1.0)
    K = st.number_input("Strike (K)", min_value=0.01, value=100.0, step=1.0)
    T = st.number_input("Time to expiry (years)", min_value=0.0, value=1.0, step=0.25, format="%.4f")
    r = st.number_input("Risk-free rate (%)", value=5.0, step=0.25) / 100
    sigma = st.number_input("Volatility (%)", min_value=0.0, value=20.0, step=1.0) / 100
    q = st.number_input("Dividend yield (%)", min_value=0.0, value=0.0, step=0.25) / 100

call = bs.greeks(S, K, T, r, sigma, q, "call")
put = bs.greeks(S, K, T, r, sigma, q, "put")

c1, c2 = st.columns(2)
c1.metric("Call price", f"{call.price:.4f}")
c2.metric("Put price", f"{put.price:.4f}")

greeks_card = theme.card("greeks")
with greeks_card:
    theme.panel_head("Greeks", "Per share")
greeks_df = pd.DataFrame(
    {
        "Call": [call.delta, call.gamma, call.vega / 100, call.theta / 365, call.rho / 100],
        "Put": [put.delta, put.gamma, put.vega / 100, put.theta / 365, put.rho / 100],
    },
    index=["Delta", "Gamma", "Vega (per 1% vol)", "Theta (per day)", "Rho (per 1% rate)"],
)
greeks_card.dataframe(greeks_df.style.format("{:.4f}"), width="stretch")

curve_card = theme.card("curve")
with curve_card:
    theme.panel_head("Value vs spot")
spots = np.linspace(0.5 * K, 1.5 * K, 120)
fig = go.Figure()
for kind, color, dash in (("call", theme.TOKENS["fg"], "solid"), ("put", theme.TOKENS["ink_2"], "dash")):
    values = [bs.price(s, K, T, r, sigma, q, kind) for s in spots]
    fig.add_trace(go.Scatter(
        x=spots, y=values, mode="lines", name=kind.title(), line=dict(color=color, width=2, dash=dash),
        hovertemplate=f"S %{{x:.2f}}<br>{kind} %{{y:.4f}}<extra></extra>",
    ))
fig.add_vline(x=K, line=dict(color=theme.TOKENS["line_strong"], width=1, dash="dot"),
              annotation_text="strike", annotation_font_color=theme.TOKENS["fg_subtle"])
fig.update_xaxes(title="spot")
fig.update_yaxes(title="option value")
fig = apply_layout(fig, 340)
fig.update_layout(legend=dict(orientation="h", x=0, y=1.1))
curve_card.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
