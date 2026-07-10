"""Streamlit frontend — the basic LAN dashboard, seeded with yfinance OHLCV.

This is the first working slice of the ``present`` layer. It reads the Parquet
lake through an in-memory DuckDB connection (no file lock, picks up new bars on
each collector run) and shows price, volume, and descriptive stats per symbol.
The four-question market-state strip and vol panels come later, on tastytrade data.

Run:  streamlit run src/present/streamlit_app.py
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from config import load_config
from present.summary import summarize
from storage import reader, schema

st.set_page_config(page_title="derivative-implied-pricing", page_icon="📈", layout="wide")

config = load_config()


@st.cache_resource
def get_conn():
    # In-memory: never takes the market.duckdb file lock, so it can't collide
    # with a running collector. Views re-glob the Parquet on every query.
    return schema.connect(config, persistent=False)


conn = get_conn()
schema.ensure_views(conn, config)  # refresh each run so newly-collected data appears

st.title("📈 derivative-implied-pricing")
st.caption("Basic yfinance slice — OHLCV. Vol panels & market-state strip land on tastytrade data.")

symbols = reader.available_symbols(conn, interval="1h") or reader.available_symbols(conn)

if not symbols:
    st.warning("No data yet. Seed the lake first:")
    st.code("python -m collector.yfinance_collector --interval 1h --period 1mo", language="bash")
    st.stop()

with st.sidebar:
    st.header("Controls")
    symbol = st.selectbox("Symbol", symbols, index=symbols.index("SPY") if "SPY" in symbols else 0)
    interval = st.radio("Interval", ["1h", "1d"], horizontal=True)
    window = st.slider("Bars shown", min_value=20, max_value=500, value=120, step=10)

df = reader.get_ohlcv(conn, symbol, interval, tail=window)

if df.empty:
    st.info(f"No {interval} bars stored for {symbol}. Run the collector for this interval.")
    st.code(f"python -m collector.yfinance_collector --interval {interval}", language="bash")
    st.stop()

s = summarize(df)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Last", f"{s['last']:.2f}", f"{s['change_abs']:+.2f} ({s['change_pct']:+.2f}%)")
c2.metric(f"Window Δ ({s['bars']} bars)", f"{s['window_change_pct']:+.2f}%")
c3.metric("High / Low", f"{s['high']:.2f}", f"low {s['low']:.2f}", delta_color="off")
c4.metric("Realized vol (ann.)", f"{s['rv_annualized_pct']:.1f}%", help="Close-to-close, historical — context, not a forecast.")

chart_df = df.set_index("ts")
st.subheader(f"{symbol} · {interval} · close")
st.line_chart(chart_df["close"], height=320)

st.subheader("Volume")
st.bar_chart(chart_df["volume"], height=160)

with st.expander("Raw bars"):
    show = df.copy()
    show["ts"] = show["ts"].dt.strftime("%Y-%m-%d %H:%M UTC")
    st.dataframe(show, width="stretch", hide_index=True)

last_ts = pd.Timestamp(s["last_ts"])
st.caption(f"Latest bar: {last_ts:%Y-%m-%d %H:%M UTC}  ·  source: yfinance")
