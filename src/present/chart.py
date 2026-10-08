"""Charts: a watchlist on the left, the selected symbol's chart and key stats on the right.

Click a row to open its chart. Type any ticker into the add box to put it on the list; the list
is saved per user (present.watchlist). Quotes are live from tastytrade when connected, bars come
through present.data (stored, topped up live, a new symbol backfilled once), and the whole view
refreshes every 30 seconds while the market is open.
"""

from __future__ import annotations

import math

import pandas as pd
import streamlit as st

from derive.market_state import rolling_vol
from present import auth, data, theme, watchlist
from present.charts import tradingview_html

ET = "America/New_York"
USER = auth.user() or "guest"
RANGES = {"5D": ("1h", 5), "1M": ("1h", 22), "3M": ("1d", 63), "6M": ("1d", 126),
          "1Y": ("1d", 252), "5Y": ("1d", 1260)}

if "watchlist" not in st.session_state:
    st.session_state["watchlist"] = watchlist.load(USER, data.config)
if "chart_symbol" not in st.session_state:
    st.session_state["chart_symbol"] = st.session_state["watchlist"][0]


def _save(symbols: list[str]) -> None:
    st.session_state["watchlist"] = watchlist.save(USER, symbols, data.config)


def _add() -> None:
    sym = data.clean(st.session_state.get("wl_add") or "")
    if sym:
        if data.bars(sym, "1d").empty:
            st.session_state["wl_error"] = f"{sym} not found."
        else:
            _save([sym, *st.session_state["watchlist"]])
            st.session_state["chart_symbol"] = sym
    st.session_state["wl_add"] = None


def _pct(x: float, d: int = 2) -> str:
    return "" if x != x else f"{x:+.{d}%}"


def _num(x: float, spec: str = ",.2f") -> str:
    return "" if x is None or x != x else format(x, spec)


@st.cache_data(ttl=300, show_spinner="Loading watchlist...")
def _history(symbols: tuple[str, ...]) -> dict[str, pd.Series]:
    return {s: data.closes(s, live=False) for s in symbols}


def _rows(symbols: list[str]) -> pd.DataFrame:
    hist = _history(tuple(symbols))
    live = data.quotes(tuple(symbols))
    rows = []
    for sym in symbols:
        h = hist.get(sym, pd.Series(dtype=float))
        q = live.get(data.clean(sym))
        last = q["last"] if q else (float(h.iloc[-1]) if len(h) else math.nan)
        prev = (q["prev"] if q and q["prev"] == q["prev"] else
                float(h.iloc[-2]) if len(h) > 1 else math.nan)
        rows.append({"Symbol": sym.lstrip("^"), "Last": last,
                     "Chg %": (last / prev - 1) * 100 if prev == prev and prev else math.nan,
                     "30D": h.tail(30).round(2).tolist()})
    return pd.DataFrame(rows)


def _with_live_bar(df: pd.DataFrame, q: dict | None, interval: str) -> pd.DataFrame:
    """Fold the live mark into today's daily candle during the session."""
    if q is None or interval != "1d" or df.empty or not data.market_open():
        return df
    df = df.copy()
    today = pd.Timestamp.now(tz=ET).date()
    last_day = df["ts"].iloc[-1].tz_convert(ET).date()
    px = q["last"]
    if last_day == today:
        i = df.index[-1]
        df.loc[i, "close"] = px
        df.loc[i, "high"] = max(df.loc[i, "high"], px)
        df.loc[i, "low"] = min(df.loc[i, "low"], px)
    else:
        ts = pd.Timestamp(today).tz_localize(ET).tz_convert("UTC")
        df.loc[len(df)] = {"ts": ts, "symbol": df["symbol"].iloc[-1], "interval": "1d",
                           "open": px, "high": px, "low": px, "close": px, "volume": 0}
    return df


@st.fragment(run_every=30 if data.market_open() else None)
def view() -> None:
    symbols = st.session_state["watchlist"]
    left, right = st.columns([1, 3.2], gap="medium")

    with left, theme.card("watchlist"):
        theme.panel_head("Watchlist", f"{len(symbols)} symbols")
        st.selectbox("Add symbol", sorted(set(watchlist.DEFAULT) - set(symbols)) or [""],
                     index=None, placeholder="Add a symbol", key="wl_add",
                     accept_new_options=True, on_change=_add, label_visibility="collapsed")
        if err := st.session_state.pop("wl_error", None):
            st.caption(err)
        table = _rows(symbols)
        sel = st.dataframe(
            table, key="wl_table", hide_index=True, width="stretch",
            height=min(36 * (len(table) + 1) + 4, 760), on_select="rerun",
            selection_mode="single-row",
            column_config={
                "Symbol": st.column_config.TextColumn(width="small"),
                "Last": st.column_config.NumberColumn(format="%.2f"),
                "Chg %": st.column_config.NumberColumn(format="%+.2f"),
                "30D": st.column_config.LineChartColumn(width="small"),
            },
        )
        picked = sel.selection.rows if sel and sel.selection else []
        if picked:
            st.session_state["chart_symbol"] = symbols[picked[0]]
        current = st.session_state["chart_symbol"]
        if current in symbols and st.button(f"Remove {current.lstrip('^')}", width="stretch"):
            _save([s for s in symbols if s != current])
            st.session_state["chart_symbol"] = st.session_state["watchlist"][0]
            st.rerun()

    with right, theme.card("chart"):
        sym = st.session_state["chart_symbol"]
        title, ctl = st.columns([3, 1.6], vertical_alignment="center")
        rng = ctl.segmented_control("Range", list(RANGES), default="6M", key="chart_range",
                                    label_visibility="collapsed") or "6M"
        interval, n = RANGES[rng]
        q = data.quote(sym)
        bars = data.bars(sym, interval)
        daily = data.bars(sym, "1d")
        if daily.empty:
            title.markdown(f'<span class="panel-title">{sym}</span>', unsafe_allow_html=True)
            st.warning(f"No data for {sym}.")
            return
        last = q["last"] if q else float(daily["close"].iloc[-1])
        prev = q["prev"] if q and q["prev"] == q["prev"] else float(daily["close"].iloc[-2])
        chg = last - prev
        cls = "up" if chg >= 0 else "down"
        title.markdown(
            f'<div class="quote-head"><span class="sym">{sym.lstrip("^")}</span>'
            f'<span class="px">{last:,.2f}</span><span class="{cls}">{chg:+,.2f} ({chg / prev:+.2%})</span>'
            f'<span class="src">{q["source"] if q else "last close"}</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="panel-rule"></div>', unsafe_allow_html=True)
        shown = _with_live_bar(bars, q, interval).tail(n * (7 if interval == "1h" else 1)).reset_index(drop=True)
        st.iframe(tradingview_html(shown, interval, height=500, colors=theme.chart_colors()), height=510)

        closes = daily["close"]
        year = daily.tail(252)
        rv = float(rolling_vol(closes).iloc[-1]) / 100 if len(closes) > 22 else math.nan
        today_bar = daily.iloc[-1]
        m = data.metrics(sym)
        stats = [
            ("Prev close", _num(prev)),
            ("Day range", f"{_num(today_bar['low'])} to {_num(today_bar['high'])}"),
            ("52W range", f"{_num(year['low'].min())} to {_num(year['high'].max())}"),
            ("Volume", _num(today_bar["volume"], ",.0f")),
            ("Avg vol, 30D", _num(daily["volume"].tail(30).mean(), ",.0f")),
            ("Realized vol, 21D", "" if rv != rv else f"{rv:.1%}"),
            ("IVx", "" if not m or m.get("ivx") != m.get("ivx") else f"{m['ivx']:.1%}"),
            ("IV rank", "" if not m or m.get("iv_rank") != m.get("iv_rank") else f"{m['iv_rank']:.0%}"),
            ("Earnings", "" if not m or pd.isna(m.get("earnings_date")) else
             f"{pd.Timestamp(m['earnings_date']):%b %-d}"),
        ]
        cells = "".join(f"<div><dt>{k}</dt><dd>{v or '&nbsp;'}</dd></div>" for k, v in stats)
        st.markdown(f'<dl class="kstats">{cells}</dl>', unsafe_allow_html=True)


st.markdown(
    """<style>
.quote-head { display: flex; align-items: baseline; gap: 12px; font-variant-numeric: tabular-nums; }
.quote-head .sym { font-size: 1rem; font-weight: 600; }
.quote-head .px { font-size: 1.375rem; font-weight: 600; letter-spacing: -0.01em; }
.quote-head .up { color: var(--good); font-weight: 500; }
.quote-head .down { color: var(--risk); font-weight: 500; }
.quote-head .src { font-size: 12px; color: var(--fg-subtle); }
.kstats { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); margin: 4px 0 0;
  border-top: 1px solid var(--line); }
.kstats div { padding: 8px 12px 8px 0; border-bottom: 1px solid var(--line); }
.kstats dt { font-size: 11.5px; color: var(--fg-subtle); }
.kstats dd { margin: 2px 0 0; font-size: 13.5px; font-weight: 600; font-variant-numeric: tabular-nums; }
</style>""",
    unsafe_allow_html=True,
)
theme.intro("Charts", eyebrow="Markets")
view()
