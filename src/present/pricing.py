"""Black-Scholes pricing page: inputs, price and Greeks, value-vs-spot curve."""

from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from derive import black_scholes as bs

st.title("Black-Scholes pricing")
st.caption("European options, continuous dividend yield. Formulas: Docs and Formulas, section 3.")

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

st.subheader("Greeks")
greeks_df = pd.DataFrame(
    {
        "Call": [call.delta, call.gamma, call.vega / 100, call.theta / 365, call.rho / 100],
        "Put": [put.delta, put.gamma, put.vega / 100, put.theta / 365, put.rho / 100],
    },
    index=["Delta", "Gamma", "Vega (per 1% vol)", "Theta (per day)", "Rho (per 1% rate)"],
)
st.dataframe(greeks_df.style.format("{:.4f}"), width="stretch")

st.subheader("Value vs spot")
spots = np.linspace(0.5 * K, 1.5 * K, 120)
curve = pd.DataFrame(
    {
        "Call": [bs.price(s, K, T, r, sigma, q, "call") for s in spots],
        "Put": [bs.price(s, K, T, r, sigma, q, "put") for s in spots],
    },
    index=spots,
)
st.line_chart(curve, height=320)
