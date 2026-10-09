"""Charts: the watchlist on the left, the selected symbol's chart and key stats on the right.

A row opens its chart; right-click a row (or its menu button) to replace, move or remove it, and
the add row at the bottom appends a symbol (present.watchlist_view).
The list is saved per user (present.watchlist). Quotes are live from tastytrade when connected,
bars come through present.data, and the view refreshes every 30 seconds during the session.
"""

from __future__ import annotations

import math
from html import escape

import pandas as pd
import streamlit as st

from alphasurface.derive.market_state import rolling_vol
from alphasurface.present import auth, data, theme, watchlist, watchlist_view
from alphasurface.present.charts import tradingview_html

ET = "America/New_York"
USER = auth.user() or "guest"
# Range: (bar interval, sessions shown, fallback interval when the first is unavailable).
RANGES = {
    "1D": ("5m", 1, "1h"),
    "5D": ("5m", 5, "1h"),
    "1M": ("1h", 22, "1d"),
    "3M": ("1d", 63, None),
    "6M": ("1d", 126, None),
    "YTD": ("1d", 0, None),
    "1Y": ("1d", 252, None),
    "5Y": ("1d", 1260, None),
}

if "watchlist" not in st.session_state:
    st.session_state["watchlist"] = watchlist.load(USER, data.config)
if "chart_symbol" not in st.session_state:
    st.session_state["chart_symbol"] = st.session_state["watchlist"][0]


def _save(symbols: list[str]) -> None:
    st.session_state["watchlist"] = watchlist.save(USER, symbols, data.config) or watchlist.DEFAULT
    if st.session_state["chart_symbol"] not in st.session_state["watchlist"]:
        st.session_state["chart_symbol"] = st.session_state["watchlist"][0]


def _valid(sym: str) -> bool:
    return bool(sym) and not data.bars(sym, "1d").empty


def _apply(action: dict) -> None:
    """Apply one watchlist action from the list component to the stored list."""
    kind, sym = action.get("type"), action.get("sym", "")
    symbols = list(st.session_state["watchlist"])
    i = symbols.index(sym) if sym in symbols else -1
    if kind == "open" and i >= 0:
        st.session_state["chart_symbol"] = sym
    elif kind == "add":
        new = data.clean(sym)
        if new in symbols:
            st.session_state["chart_symbol"] = new
        elif _valid(new):
            _save([*symbols, new])
            st.session_state["chart_symbol"] = new
        else:
            st.session_state["wl_error"] = f"No data for {new}."
    elif kind == "replace" and i >= 0:
        new = data.clean(action.get("to", ""))
        if new in symbols:
            st.session_state["wl_error"] = f"{new} is already on the list."
        elif _valid(new):
            symbols[i] = new
            if st.session_state["chart_symbol"] == sym:
                st.session_state["chart_symbol"] = new
            _save(symbols)
        else:
            st.session_state["wl_error"] = f"No data for {new}."
    elif kind == "remove" and i >= 0 and len(symbols) > 1:
        _save([s for s in symbols if s != sym])
    elif kind in ("top", "up", "down") and i >= 0:
        j = {"top": 0, "up": max(i - 1, 0), "down": min(i + 1, len(symbols) - 1)}[kind]
        symbols.insert(j, symbols.pop(i))
        _save(symbols)


def _num(x: float | None, spec: str = ",.2f") -> str:
    return "" if x is None or x != x else format(x, spec)


def _pct(x: float | None, spec: str = ".1%") -> str:
    return "" if x is None or x != x else format(x, spec)


def _short(x: float | None) -> str:
    """Volume and market cap: 1.2M, 3.4B."""
    if x is None or x != x:
        return ""
    for div, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= div:
            return f"{x / div:,.2f}{unit}"
    return f"{x:,.0f}"


@st.cache_data(ttl=300, show_spinner="Loading watchlist...")
def _history(symbols: tuple[str, ...]) -> dict[str, pd.Series]:
    return {s: data.closes(s, live=False).tail(30) for s in symbols}


def _rows(symbols: list[str]) -> list[watchlist_view.Row]:
    hist = _history(tuple(symbols))
    live = data.quotes(tuple(symbols))
    rows = []
    for sym in symbols:
        h = hist.get(sym, pd.Series(dtype=float))
        q = live.get(data.clean(sym))
        last = q["last"] if q else (float(h.iloc[-1]) if len(h) else math.nan)
        prev = (
            q["prev"]
            if q and q["prev"] == q["prev"]
            else float(h.iloc[-2])
            if len(h) > 1
            else math.nan
        )
        chg = last / prev - 1 if prev == prev and prev else math.nan
        rows.append(watchlist_view.row(sym, last, chg, h))
    return rows


def _watchlist(symbols: list[str]) -> None:
    st.markdown(
        f'<div class="panel-title wl-head">Watchlist <span class="wl-count">{len(symbols)}</span>'
        "</div>",
        unsafe_allow_html=True,
    )
    action = watchlist_view.render(
        _rows(symbols), st.session_state["chart_symbol"], error=st.session_state.pop("wl_error", "")
    )
    if action:
        _apply(action)
        st.rerun(scope="fragment")


def _with_live_bar(df: pd.DataFrame, q: dict | None) -> pd.DataFrame:
    """Fold the live mark into today's daily candle during the session."""
    if q is None or df.empty or not data.market_open():
        return df
    df = df.copy()
    today = pd.Timestamp.now(tz=ET).date()
    px = q["last"]
    if df["ts"].iloc[-1].tz_convert(ET).date() == today:
        i = df.index[-1]
        df.loc[i, "close"] = px
        df.loc[i, "high"] = max(df.loc[i, "high"], px)
        df.loc[i, "low"] = min(df.loc[i, "low"], px)
    else:
        ts = pd.Timestamp(today).tz_localize(ET).tz_convert("UTC")
        df.loc[len(df)] = {
            "ts": ts,
            "symbol": df["symbol"].iloc[-1],
            "interval": "1d",
            "open": px,
            "high": px,
            "low": px,
            "close": px,
            "volume": 0,
        }
    return df


def _bars(sym: str, rng: str, q: dict | None, daily: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    """Bars for the range, in the preferred interval when the provider has it."""
    interval, sessions, fallback = RANGES[rng]
    df = pd.DataFrame()
    if interval == "1d":
        df = _with_live_bar(daily, q)
    else:
        for iv in (interval, fallback):
            try:
                df = data.bars(sym, iv)
            except (KeyError, ValueError):  # interval not offered by this build of the feed
                continue
            if not df.empty:
                interval = iv
                break
        if df.empty:
            interval, df = "1d", _with_live_bar(daily, q)
            sessions = max(sessions, 22)
    if df.empty:
        return df, interval
    dates = df["ts"].dt.tz_convert(ET).dt.date
    if rng == "YTD":
        keep = dates >= pd.Timestamp.now(tz=ET).replace(month=1, day=1).date()
    else:
        days = sorted(dates.unique())
        keep = dates >= days[-min(sessions, len(days))]
    return df[keep].reset_index(drop=True), interval


def _change(px: float, ref: float) -> str:
    chg = px - ref
    return f'<span class="chg {"up" if chg >= 0 else "down"}">{chg:+,.2f} ({chg / ref:+.2%})</span>'


def _price(
    daily: pd.DataFrame, q: dict | None
) -> tuple[float, float, str, tuple[str, float] | None]:
    """(price, reference, label, extended): the live mark against the prior close during the
    session; outside it the official close against the close before, with any pre-market or
    after-hours mark beside it, so an extended-hours move never reads as the day's change."""
    now = pd.Timestamp.now(tz=ET)
    close = float(daily["close"].iloc[-1])
    before = float(daily["close"].iloc[-2]) if len(daily) > 1 else close
    if q and data.market_open():
        prev = q["prev"] if q["prev"] == q["prev"] else before
        feed = data.feed_label() if hasattr(data, "feed_label") else "Live"
        return q["last"], prev, f"{feed or 'Live'}, {now:%-I:%M %p} ET", None
    asof = daily["ts"].iloc[-1].tz_convert(ET)
    ext = None
    if q and abs(q["last"] - close) > 1e-9:
        ext = (
            "Pre-market" if now.date() > asof.date() and now.hour < 10 else "After hours",
            q["last"],
        )
    return close, before, f"At close {asof:%b %-d}", ext


def _quote_head(
    sym: str, name: str, price: tuple[float, float, str, tuple[str, float] | None]
) -> str:
    px, ref, label, ext = price
    extended = ""
    if ext:
        extended = (
            f'<div class="qh-ext"><span>{ext[0]}</span><b>{ext[1]:,.2f}</b>'
            f"{_change(ext[1], px)}</div>"
        )
    return (
        f'<div class="quote-head"><div class="qh-id"><span class="sym">{escape(sym.lstrip("^"))}</span>'
        f'<span class="name">{escape(name)}</span></div>'
        f'<div class="qh-px"><span class="px">{px:,.2f}</span>{_change(px, ref)}'
        f'<span class="src">{escape(label)}</span></div>{extended}</div>'
    )


def _stats(sym: str, last: float, prev: float, daily: pd.DataFrame) -> str:
    closes = daily["close"]
    year = daily.tail(252)
    bar = daily.iloc[-1]
    rv = float(rolling_vol(closes).iloc[-1]) / 100 if len(closes) > 22 else math.nan
    m = data.metrics(sym) or {}
    ivx = m.get("ivx", math.nan)
    move = last * ivx * math.sqrt(5 / 252) if ivx == ivx else math.nan
    earn = m.get("earnings_date")
    exdiv = m.get("dividend_ex_date")
    groups = {
        "Price": [
            ("Previous close", _num(prev)),
            ("Open", _num(bar["open"])),
            ("Day range", f"{_num(bar['low'])} to {_num(bar['high'])}"),
            ("52-week range", f"{_num(year['low'].min())} to {_num(year['high'].max())}"),
            ("Volume", _short(bar["volume"])),
            ("Avg volume, 30D", _short(daily["volume"].tail(30).mean())),
        ],
        "Volatility": [
            ("IVx", _pct(ivx)),
            ("IV rank", _pct(m.get("iv_rank"), ".0%")),
            ("IV percentile", _pct(m.get("iv_percentile"), ".0%")),
            ("Realized vol, 21D", _pct(rv)),
            (
                "IVx minus realized",
                "" if ivx != ivx or rv != rv else f"{(ivx - rv) * 100:+.1f} pts",
            ),
            ("Expected move, 1W", "" if move != move else f"±{move:,.2f} (±{move / last:.1%})"),
        ],
        "Profile": [
            ("Beta", _num(m.get("beta"))),
            ("Correlation to SPY, 3M", _num(m.get("corr_spy_3m"))),
            ("Market cap", _short(m.get("market_cap"))),
            ("P/E", _num(m.get("price_earnings_ratio"))),
            (
                "Earnings",
                "" if earn is None or pd.isna(earn) else f"{pd.Timestamp(earn):%b %-d, %Y}",
            ),
            (
                "Ex-dividend",
                "" if exdiv is None or pd.isna(exdiv) else f"{pd.Timestamp(exdiv):%b %-d, %Y}",
            ),
        ],
    }
    cols = []
    for title, items in groups.items():
        rows = "".join(f"<div><dt>{k}</dt><dd>{v or '&ndash;'}</dd></div>" for k, v in items)
        cols.append(f"<section><h4>{title}</h4><dl>{rows}</dl></section>")
    link = (
        f'<a class="more-link" href="/research?tab=fundamentals&symbol={escape(sym.lstrip("^"))}" '
        'target="_self">Financials, earnings and filings</a>'
    )
    return f'<div class="kstats">{"".join(cols)}</div>{link}'


def _chart(sym: str) -> None:
    daily = data.bars(sym, "1d")
    if daily.empty:
        st.markdown(
            f'<div class="chart-empty"><b>{escape(sym)}</b><span>No price history for this '
            "symbol yet.</span></div>",
            unsafe_allow_html=True,
        )
        return
    q = data.quote(sym)
    price = _price(daily, q)
    last, prev = price[0], price[1]
    name = data.describe(sym) if hasattr(data, "describe") else ""
    head, ctl = st.columns([3, 2], vertical_alignment="bottom")
    head.markdown(_quote_head(sym, name, price), unsafe_allow_html=True)
    with ctl.container(key="chart-range"):
        rng = (
            st.segmented_control(
                "Range", list(RANGES), default="6M", key="chart_range", label_visibility="collapsed"
            )
            or "6M"
        )
    bars, interval = _bars(sym, rng, q, daily)
    st.iframe(tradingview_html(bars, interval, height=680, colors=theme.chart_colors()), height=690)
    st.markdown(_stats(sym, last, prev, daily), unsafe_allow_html=True)


@st.fragment(run_every=30 if data.market_open() else None)
def view() -> None:
    symbols = st.session_state["watchlist"]
    left, right = st.columns([1, 3.4], gap="medium")
    with left, theme.rail("watchlist"), theme.card("watchlist"):
        _watchlist(symbols)
    with right, theme.card("chart"):
        _chart(st.session_state["chart_symbol"])


st.markdown(
    """<style>
.wl-count { margin-left: 6px; font-weight: 500; color: var(--fg-subtle); font-variant-numeric: tabular-nums; }
.wl-head { margin-bottom: 6px; }
.quote-head { display: flex; flex-direction: column; gap: 2px; font-variant-numeric: tabular-nums; }
.qh-id { display: flex; align-items: baseline; gap: 10px; }
.qh-id .sym { font-size: 1.125rem; font-weight: 700; letter-spacing: -0.01em; color: var(--fg); }
.qh-id .name { font-size: 13px; color: var(--fg-subtle); }
.qh-px { display: flex; align-items: baseline; flex-wrap: wrap; column-gap: 12px; }
.qh-px .px { font-size: 1.875rem; font-weight: 700; letter-spacing: -0.02em; color: var(--fg); }
.qh-px .chg { font-size: 15px; font-weight: 600; }
.qh-px .src { font-size: 12px; color: var(--fg-subtle); }
.qh-ext { display: flex; align-items: baseline; gap: 8px; font-size: 13px; color: var(--fg-subtle); }
.qh-ext b { font-weight: 600; color: var(--fg); }
.qh-ext .chg { font-size: 13px; font-weight: 500; }
.quote-head .chg.up { color: var(--good); }
.quote-head .chg.down { color: var(--risk); }
.st-key-chart-range { align-items: flex-end; }
.kstats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); column-gap: 40px; row-gap: 20px;
  margin-top: 12px; }
@media (max-width: 1100px) { .kstats { grid-template-columns: minmax(0, 1fr); } }
.kstats h4 { margin: 0 0 4px; padding: 0 !important; font-size: 12px !important; font-weight: 600 !important;
  color: var(--fg-subtle) !important; }
.kstats dl { margin: 0; }
.kstats dl div { display: flex; justify-content: space-between; gap: 16px; padding: 8px 0;
  border-bottom: 1px solid var(--line); }
.kstats dt { font-size: 13px; color: var(--fg-muted); }
.kstats dd { margin: 0; font-size: 13px; font-weight: 600; color: var(--fg); text-align: right;
  font-variant-numeric: tabular-nums; white-space: nowrap; }
.more-link { display: inline-block; margin-top: 12px; font-size: 13px; font-weight: 500; }
.chart-empty { display: flex; flex-direction: column; gap: 4px; padding: 48px 0; color: var(--fg-subtle); }
.chart-empty b { font-size: 1.125rem; color: var(--fg); }
</style>""",
    unsafe_allow_html=True,
)
theme.intro("Charts", eyebrow="Markets")
view()
