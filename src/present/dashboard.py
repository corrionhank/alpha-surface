"""OHLCV dashboard page: price/volume chart plus summary stats."""

from __future__ import annotations

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from config import load_config
from present.charts import tradingview_html
from present.summary import summarize
from storage import reader, schema

config = load_config()


@st.cache_resource
def get_conn():
    # In-memory: no file lock against a running collector; views re-glob Parquet per query.
    return schema.connect(config, persistent=False)


conn = get_conn()
schema.ensure_views(conn, config)  # refresh so newly collected data appears

st.title("derivative-implied-pricing")
st.caption("yfinance OHLCV. Vol panels and market-state strip come with tastytrade data.")

symbols = reader.available_symbols(conn, interval="1h") or reader.available_symbols(conn)

if not symbols:
    st.warning("No data yet. Seed it first:")
    st.code("python -m collector.yfinance_collector --interval 1h --period 1mo", language="bash")
    st.stop()

with st.sidebar:
    st.header("Controls")
    symbol = st.selectbox("Symbol", symbols, index=symbols.index("SPY") if "SPY" in symbols else 0)
    interval = st.radio("Interval", ["1h", "1d"], horizontal=True)
    window = st.slider("Bars shown", min_value=50, max_value=4000, value=300, step=50)

df = reader.get_ohlcv(conn, symbol, interval, tail=window)

if df.empty:
    st.info(f"No {interval} bars stored for {symbol}.")
    st.code(f"python -m collector.yfinance_collector --interval {interval}", language="bash")
    st.stop()

s = summarize(df)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Last", f"{s['last']:.2f}", f"{s['change_abs']:+.2f} ({s['change_pct']:+.2f}%)")
c2.metric(f"Window change ({s['bars']} bars)", f"{s['window_change_pct']:+.2f}%")
c3.metric("High / Low", f"{s['high']:.2f}", f"low {s['low']:.2f}", delta_color="off")
c4.metric("Realized vol (ann.)", f"{s['rv_annualized_pct']:.1f}%", help="Close-to-close, historical.")

st.subheader(f"{symbol} {interval} OHLC and volume")
components.html(tradingview_html(df, interval, height=480), height=500, scrolling=False)

with st.expander("Raw bars"):
    show = df.copy()
    show["ts"] = show["ts"].dt.strftime("%Y-%m-%d %H:%M UTC")
    st.dataframe(show, width="stretch", hide_index=True)

last_ts = pd.Timestamp(s["last_ts"])
st.caption(f"Latest bar: {last_ts:%Y-%m-%d %H:%M UTC}. Source: yfinance")
