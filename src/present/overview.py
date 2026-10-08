"""Overview: the derivatives trader's cockpit, most critical numbers first.

Layout: a full-width KPI strip (index prices, implied vol and its changes, today's priced move,
regime, the fear and greed lens, implied minus realized). Below it a two-column grid: the main
column holds SPY and QQQ charts, the implied vol panel and VIX term curve, the expected-move
cone, fund fundamentals and holdings, and the watchlist; a sticky right rail holds the fear and
greed meter, the economic calendar and the news feed, so context stays in view while you scroll.

Market series come from the store. Fund data, news and the calendar come write-through from
collector.reference: the page shows the latest stored copy at once and a stale copy refreshes
in the background, so a slow provider never holds the page up. docs/dashboard.md.
"""

from __future__ import annotations

import math
from html import escape

import numpy as np
import pandas as pd
import streamlit as st

from collector import reference as ref
from derive import expected_move, funds, iv_panel, sentiment
from derive import market_state as ms
from present import data, market_charts, theme
from present.charts import tradingview_html

T = theme.TOKENS
NO_BAR = {"displayModeBar": False}
ET = "America/New_York"

st.markdown(
    """<style>
.kpi-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; margin: 0 0 1rem;
  background: var(--line); border: 1px solid var(--line); border-radius: var(--r-lg); overflow: hidden; }
@media (min-width: 768px) { .kpi-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
@media (min-width: 1200px) { .kpi-grid { grid-template-columns: repeat(6, minmax(0, 1fr)); } }
.kpi { background: var(--surface); padding: 10px 14px 11px; min-width: 0; }
.kpi .l { font-size: 12px; color: var(--fg-subtle); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kpi .v { font-size: 1.25rem; font-weight: 600; line-height: 1.25; margin-top: 2px; letter-spacing: -0.01em;
  font-variant-numeric: tabular-nums; }
.kpi .s { font-size: 12px; color: var(--fg-muted); margin-top: 2px; font-variant-numeric: tabular-nums;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kv { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; margin: 0;
  border-top: 1px solid var(--line); }
.kv div { padding: 7px 10px 7px 0; border-bottom: 1px solid var(--line); }
.kv dt { font-size: 11.5px; color: var(--fg-subtle); }
.kv dd { margin: 1px 0 0; font-size: 0.9375rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.sublabel { font-size: 12px; font-weight: 600; color: var(--fg-muted); margin: 8px 0 0; }
.sublabel span { font-weight: 400; color: var(--fg-subtle); }
.card-sub { font-size: 12.5px; color: var(--fg-muted); font-variant-numeric: tabular-nums; }
.feed { font-size: 13px; }
.feed-row { padding: 8px 0; border-top: 1px solid var(--line); }
.feed-row:first-child { border-top: none; padding-top: 2px; }
.feed-row a { color: var(--fg) !important; text-decoration: none; font-weight: 500; line-height: 1.4; }
.feed-row a:hover { text-decoration: underline; }
.feed-row .m { display: flex; gap: 10px; color: var(--fg-subtle); font-size: 11.5px; margin-top: 2px; }
.cal-day { font-size: 11.5px; font-weight: 600; color: var(--fg-subtle); margin: 10px 0 2px; }
.cal-day:first-child { margin-top: 2px; }
.cal-row { display: grid; grid-template-columns: 2.9rem 1fr; gap: 8px; padding: 5px 0;
  border-top: 1px solid var(--line); font-size: 12.5px; }
.cal-row .t { color: var(--fg-subtle); font-variant-numeric: tabular-nums; }
.cal-row .n { display: block; font-variant-numeric: tabular-nums; color: var(--fg-subtle); font-size: 11.5px; }
.ivr-wrap { font-size: 13px; font-variant-numeric: tabular-nums; }
.ivr { display: grid; grid-template-columns: 4.5rem minmax(180px, 1fr) 4.5rem 4.5rem 4.5rem 8.5rem 6.5rem;
  align-items: center; column-gap: 14px; height: 34px; border-bottom: 1px solid var(--line); }
.ivr:last-child { border-bottom: none; }
.ivr > span { text-align: right; white-space: nowrap; }
.ivr > span:first-child, .ivr > .db, .ivr > .axis { text-align: left; }
.ivr .sym { font-weight: 600; }
.ivr .m { color: var(--fg-muted); }
.ivr .m em { font-style: normal; color: var(--fg-subtle); margin-left: 4px; }
.ivr .b { font-weight: 600; }
.ivr-head { height: 26px; font-size: 11.5px; color: var(--fg-subtle); }
.ivr-head > span { color: var(--fg-subtle); }
.ivr .axis { position: relative; height: 100%; }
.ivr .axis span { position: absolute; top: 50%; transform: translate(-50%, -50%); }
.ivr .axis span:first-child { transform: translate(0, -50%); }
.ivr .db { position: relative; height: 100%; }
.ivr .db::before { content: ""; position: absolute; left: 0; right: 0; top: 50%; border-top: 1px solid var(--line); }
.ivr .db i { position: absolute; top: 50%; }
.ivr .seg { height: 2px; margin-top: -1px; background: var(--fg); opacity: 0.35; }
.ivr .seg.cheap { background: none; border-top: 2px dotted var(--fg); height: 0; }
.ivr .hv, .ivr .iv { width: 9px; height: 9px; margin: -4.5px 0 0 -4.5px; border-radius: 50%; }
.ivr .hv { background: var(--surface); border: 1.5px solid var(--fg-muted); box-sizing: border-box; }
.ivr .iv { background: var(--fg); }
.ivr .rk { display: inline-flex; align-items: center; justify-content: flex-end; gap: 8px; }
.ivr .rk i { display: inline-block; width: 64px; height: 4px; border-radius: 2px;
  background: var(--surface-raised); position: relative; overflow: hidden; }
.ivr .rk i b { position: absolute; left: 0; top: 0; bottom: 0; background: var(--fg); }
.ivr-key { display: inline-flex; align-items: center; gap: 6px; }
.ivr-key i { display: inline-block; width: 8px; height: 8px; border-radius: 50%; box-sizing: border-box; }
.ivr-key .k-iv { background: var(--fg); }
.ivr-key .k-hv { border: 1.5px solid var(--fg-muted); }
.fg-top { display: flex; align-items: baseline; gap: 10px; }
.fg-top .score { font-size: 1.75rem; font-weight: 600; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
/* Right rail: stays in view while the main column scrolls, and scrolls on its own if taller. */
[data-testid="stHorizontalBlock"]:has(.st-key-rail) { align-items: stretch !important; }
[data-testid="stColumn"]:has(.st-key-rail) > [data-testid="stVerticalBlock"] { height: 100%; }
[data-testid="stLayoutWrapper"]:has(> .st-key-rail) {
  position: sticky; top: calc(var(--header) + var(--bar) + 12px);
}
.st-key-rail { max-height: calc(100vh - var(--header) - var(--bar) - 24px); overflow-y: auto;
  scrollbar-width: thin; }
</style>""",
    unsafe_allow_html=True,
)


VOL = {"VIX": "^VIX", "VXN": "^VXN", "VIX1D": "^VIX1D", "VIX9D": "^VIX9D", "VIX3M": "^VIX3M",
       "VIX6M": "^VIX6M", "VVIX": "^VVIX", "SKEW": "^SKEW"}
MACRO = list(data.config.symbols.get("macro_etfs", {}).get("etfs", ["TLT", "IEF", "HYG", "GLD"]))
SYMBOLS = sorted({*data.config.equities(), *MACRO, *VOL.values(), "TLT", "IEF", "HYG"})


@st.cache_data(ttl=300, show_spinner="Reading the store...")
def store_bars() -> dict[str, pd.DataFrame]:
    """Every daily series the page uses, in one query. The view globs thousands of day files,
    so one read for all symbols costs the same as one read for one symbol."""
    marks = ", ".join("?" for _ in SYMBOLS)
    df = data.conn().execute(
        f"SELECT ts, symbol, interval, open, high, low, close, volume FROM ohlcv "
        f"WHERE interval = '1d' AND symbol IN ({marks}) ORDER BY symbol, ts", SYMBOLS,
    ).df()
    return {sym: g.reset_index(drop=True) for sym, g in df.groupby("symbol")}


def daily(symbol: str) -> pd.DataFrame:
    return store_bars().get(symbol, pd.DataFrame(columns=["ts", "symbol", "interval", "open", "high",
                                                    "low", "close", "volume"]))


LIVE = ("SPY", "QQQ", "IWM", "DIA", "^VIX", "^VIX1D", "^VIX9D", "^VIX3M", "^VIX6M", "TLT",
        "IEF", "HYG", "GLD")


def closes(symbol: str) -> pd.Series:
    """Daily closes indexed by NY trading date, with today's live mark as the last point while
    the session is open (present.data.with_live)."""
    df = daily(symbol)
    if df.empty:
        return pd.Series(dtype=float)
    dates = df["ts"].dt.tz_convert(ET).dt.date
    s = pd.Series(df["close"].to_numpy(), index=dates)
    return data.with_live(s, symbol, live) if symbol in LIVE else s


@st.cache_data(ttl=60, show_spinner=False)
def reference(table: str) -> ref.Fetched:
    """Latest stored copy, refreshing in the background when stale. Reads only; cheap."""
    now = pd.Timestamp.now(tz="UTC")
    fetchers = {
        "etf_profile": (lambda: ref.fetch_profiles(["SPY", "QQQ"]), "symbol"),
        "etf_holdings": (lambda: ref.fetch_holdings(["SPY", "QQQ"]), "fund"),
        "news": (lambda: ref.fetch_news(ref.NEWS_QUERIES), None),
        "econ_calendar": (lambda: ref.fetch_calendar(now - pd.Timedelta(days=3),
                                                     now + pd.Timedelta(days=10)), None),
    }
    fetch, by = fetchers[table]
    return ref.refresh(table, fetch, config=data.config, by=by)


@st.cache_data(ttl=300, show_spinner=False)
def name_metrics() -> pd.DataFrame:
    """Latest tastytrade market metrics per name. Read from the store; when the last pull is
    older than 15 minutes and credentials are set, pulled again through the gateway (which
    stores it), so page views add to the IV history without hammering the API."""
    from collector import feed, tasty
    from collector.tastytrade_collector import SINGLE_NAMES
    from storage import reference

    stored = reference.latest("market_metrics", data.config)
    stale = stored.empty or (pd.Timestamp.now(tz="UTC")
                             - pd.Timestamp(stored["collected_at"].max())) > pd.Timedelta(minutes=15)
    if stale and tasty.ready():
        try:
            return feed.metrics(list(dict.fromkeys(data.config.equities() + SINGLE_NAMES)),
                                config=data.config)[0]
        except Exception:  # the page keeps the stored copy
            pass
    return stored


@st.cache_data(ttl=60, show_spinner=False)
def news_feed() -> pd.DataFrame:
    return ref.news_history(data.config, hours=48)


def chg(series: pd.Series, n: int) -> float:
    s = series.dropna()
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1) if len(s) > n else math.nan


def f_pct(x: float, d: int = 1, sign: bool = True) -> str:
    return "n/a" if x != x else (f"{x:+.{d}%}" if sign else f"{x:.{d}%}")


def f_pts(x: float, d: int = 2) -> str:
    return "n/a" if x != x else f"{x:+.{d}f}"


def colored(text: str, x: float) -> str:
    up, down = theme.polarity()
    return text if x != x else f'<span style="color:{up if x >= 0 else down}">{text}</span>'


def asof_tag(source: str, ts) -> str:
    return theme.asof(source, ts)


def stat(label: str, value: str, x: float = math.nan) -> str:
    """A label and value pair for a panel header; signed values take the status colors."""
    cls = "" if x != x else (' class="up"' if x >= 0 else ' class="down"')
    return f'<span>{label} <b{cls}>{value}</b></span>'



def head(title: str, tag: str) -> None:
    theme.panel_head(title, tag)


def html(markup: str) -> None:
    """Flat HTML through markdown: st.html would strip the SVG and the link targets."""
    st.markdown("\n".join(line.strip() for line in markup.splitlines() if line.strip()),
                unsafe_allow_html=True)


# --- Inputs ---------------------------------------------------------------------------------

data.top_up(tuple(SYMBOLS))  # keep the stored daily bars current, in the background
live = data.quotes(LIVE) if data.market_open() else {}
stored_daily = set(store_bars())
if "SPY" not in stored_daily or "^VIX" not in stored_daily:
    st.warning("No SPY or ^VIX daily data. Seed them first:")
    st.code("python -m collector.yfinance_collector --interval 1d --period 10y "
            "--symbols 'SPY,QQQ,^VIX,^VIX3M'", language="bash")
    st.stop()

c = {s: closes(s) for s in ["SPY", "QQQ", "TLT", "IEF", "HYG", *VOL.values()]}
spy, qqq, vix, vix3m = c["SPY"], c["QQQ"], c["^VIX"], c["^VIX3M"]

vix_last = float(vix.iloc[-1])
vrp_series = iv_panel.iv_minus_rv(vix, spy)
vrp_now = float(vrp_series.iloc[-1]) if len(vrp_series) else math.nan
vxn_rv = iv_panel.iv_minus_rv(c["^VXN"], qqq) if len(qqq) and len(c["^VXN"]) else pd.Series(dtype=float)
term = pd.concat({"front": vix, "back": vix3m}, axis=1).dropna()
ratio = term["back"] / term["front"]
slope = ms.term_slope(*term.iloc[-1]) if len(term) else math.nan
flag = ms.regime(vix_last, slope, vrp_now)
dist200 = ms.sma_distance(spy, 200)
d200 = float(dist200.iloc[-1])
move_pct, move_src = iv_panel.priced_move_today(c["^VIX1D"], vix)
fg = sentiment.fear_greed(spy, vix, vix3m, c["TLT"], c["HYG"], c["IEF"])
fg_week = float(fg.history.iloc[-6]) if len(fg.history) > 5 else math.nan
vol = iv_panel.panel({name: c[sym] for name, sym in VOL.items()})

theme.intro(
    "Market overview",
    eyebrow="Overview",
    tag="live" if live else f"close {spy.index[-1]:%b %-d}",
)

# --- KPI band ----------------------------------------------------------------------------------


def kpi(label: str, value: str, sub: str, color: str | None = None) -> str:
    style = f' style="color:{color}"' if color else ""
    return (f'<div class="kpi"><div class="l">{label}</div><div class="v"{style}>{value}</div>'
            f'<div class="s">{sub}</div></div>')


def price_kpi(sym: str, s: pd.Series) -> str:
    if len(s) < 2:
        return kpi(sym, "n/a", "no stored bars")
    d1 = chg(s, 1)
    return kpi(sym, f"{float(s.iloc[-1]):,.2f}",
               f"{colored(f_pct(d1, 2), d1)} 1d, {f_pct(chg(s, 5))} 1w, {f_pct(chg(s, 21))} 1m")


def vol_kpi(name: str) -> str:
    if name not in vol.index:
        return kpi(name, "n/a", "not stored")
    r = vol.loc[name]
    return kpi(name, f"{r['level']:.2f}",
               f"{f_pts(r['1d'])} 1d, {f_pts(r['1w'])} 1w, {f_pts(r['1m'])} 1m")


def rv_gap_kpi(label: str, gap: pd.Series, against: str) -> str:
    if gap.empty:
        return kpi(label, "n/a", f"needs {against}")
    now = float(gap.iloc[-1])
    return kpi(label, f"{now:+.1f} pts",
               f"{against} vs RV21, {f_pct(ms.percentile_rank(gap, now), 0, False)} pctile")


spot = float(spy.iloc[-1])
regime_sub = f"VIX {vix_last:.1f}, term {slope:+.0%}" if slope == slope else f"VIX {vix_last:.1f}"
term_sub = ("VIX3M over VIX, contango" if slope >= 0 else "VIX3M over VIX, backwardation") \
    if slope == slope else "needs ^VIX3M"
tiles = [
    price_kpi("SPY", spy),
    price_kpi("QQQ", qqq),
    vol_kpi("VIX"),
    vol_kpi("VXN"),
    kpi("Priced move today", f"{move_pct:.2f}%",
        f"1 SD, about {spot * move_pct / 100:,.2f} on SPY, from {move_src}"),
    kpi("Regime", flag.replace("_", " ").capitalize(), regime_sub, theme.status_color(flag)),
    kpi("Fear and greed", f"{fg.score:.0f}",
        f"{fg.label}, {fg_week:.0f} a week ago" if fg_week == fg_week else fg.label),
    rv_gap_kpi("SPY implied minus realized", vrp_series, "VIX"),
    rv_gap_kpi("QQQ implied minus realized", vxn_rv, "VXN"),
    kpi("Term structure", f"{float(ratio.iloc[-1]):.2f}" if len(ratio) else "n/a", term_sub),
    kpi("SPY vs 200-day", f"{d200:+.1f}%",
        f"{f_pct(ms.percentile_rank(dist200, d200), 0, False)} pctile, "
        f"{float(ms.drawdown(spy).iloc[-1]):.1f}% off 52w high"),
    vol_kpi("SKEW") if "SKEW" in vol.index else vol_kpi("VVIX"),
]
st.markdown(f'<div class="kpi-grid">{"".join(tiles)}</div>', unsafe_allow_html=True)

# --- Layout: main grid and right rail -------------------------------------------------------

main, rail_col = st.columns([3.1, 1], gap="medium")

with main:
    # Charts
    left, right = st.columns(2, gap="small")
    for col, sym in ((left, "SPY"), (right, "QQQ")):
        with col, theme.card(f"chart-{sym.lower()}"):
            df = daily(sym).tail(126)
            s = c[sym]
            if df.empty:
                st.info(f"No {sym} data.")
                continue
            rv_sym = float(ms.rolling_vol(s).iloc[-1])
            head(f"{sym}  {float(s.iloc[-1]):,.2f}",
                 stat("1M", f_pct(chg(s, 21)), chg(s, 21)) + stat("3M", f_pct(chg(s, 63)), chg(s, 63))
                 + stat("6M", f_pct(chg(s, 126)), chg(s, 126)) + stat("RV21", f"{rv_sym:.1f}%"))
            st.iframe(tradingview_html(df, "1d", height=300, colors=theme.chart_colors()), height=318)

    # Implied versus realized, name by name: a dumbbell per name on one vol axis
    mm = name_metrics()
    with theme.card("names"):
        asof = mm["collected_at"].max() if not mm.empty else None
        head("Implied vs realized vol",
             '<span class="ivr-key"><i class="k-iv"></i>Implied 30D</span>'
             '<span class="ivr-key"><i class="k-hv"></i>Realized 30D</span>'
             f"<span>{asof_tag('tastytrade', asof)}</span>")
        if mm.empty:
            st.info("No tastytrade metrics yet. Add credentials to .env.")
        else:
            mm = (mm.assign(ratio=mm["iv30"] / mm["hv30"])
                  .dropna(subset=["ivx", "hv30"]).sort_values("ratio", ascending=False))
            top = max(float(mm["ivx"].max()), float(mm["hv30"].max()))
            step = 0.1 if top <= 0.6 else 0.2
            vmax = math.ceil(top / step + 0.25) * step

            def x(v: float) -> float:
                return 100 * min(max(v / vmax, 0.0), 1.0)

            ticks = "".join(f'<span style="left:{x(t):.2f}%">{t:.0%}</span>'
                            for t in np.arange(0, vmax + 1e-9, step))
            today = pd.Timestamp.now(tz=ET).normalize().tz_localize(None)
            rows = [f'<div class="ivr ivr-head"><span>Symbol</span><span class="axis">{ticks}</span>'
                    '<span>IVx</span><span>HV30</span><span>IV / HV</span><span>IV rank</span>'
                    '<span>Earnings</span></div>']
            for _, r in mm.iterrows():
                iv, hv = float(r["ivx"]), float(r["hv30"])
                lo, hi = sorted((x(iv), x(hv)))
                ed = pd.Timestamp(r["earnings_date"]) if pd.notna(r["earnings_date"]) else None
                if ed is not None and ed.tzinfo is not None:
                    ed = ed.tz_localize(None)
                days = (ed.normalize() - today).days if ed is not None else None
                earn = f"{ed:%b %-d} <em>{days}d</em>" if days is not None and 0 <= days <= 60 else ""
                rank = float(r["iv_rank"]) if r["iv_rank"] == r["iv_rank"] else 0.0
                rows.append(
                    f'<div class="ivr"><span class="sym">{escape(str(r["symbol"]))}</span>'
                    f'<span class="db"><i class="seg{" cheap" if iv < hv else ""}" '
                    f'style="left:{lo:.2f}%;width:{hi - lo:.2f}%"></i>'
                    f'<i class="hv" style="left:{x(hv):.2f}%"></i>'
                    f'<i class="iv" style="left:{x(iv):.2f}%"></i></span>'
                    f'<span>{iv:.1%}</span><span class="m">{hv:.1%}</span>'
                    f'<span class="b">{r["ratio"]:.2f}x</span>'
                    f'<span class="rk"><i><b style="width:{rank:.0%}"></b></i>{rank:.0%}</span>'
                    f'<span class="m">{earn}</span></div>'
                )
            st.markdown(f'<div class="ivr-wrap">{"".join(rows)}</div>', unsafe_allow_html=True)

    # Implied vol
    IV_COLS = "4.2rem 3.4rem 3.2rem 3.2rem 3.2rem minmax(0,1fr) 2.6rem"
    left, right = st.columns([1.15, 1], gap="small")
    with left, theme.card("ivpanel"):
        head("Implied vol", asof_tag("Cboe via yfinance", pd.Timestamp(vix.index[-1])))
        rows = [f'<div class="bar-row bar-head" style="grid-template-columns: {IV_COLS};">'
                '<span></span><span>Level</span><span>1d</span><span>1w</span><span>1m</span>'
                '<span class="left">Percentile, 1y</span><span></span></div>']
        for name, r in vol.iterrows():
            rows.append(
                f'<div class="bar-row" style="grid-template-columns: {IV_COLS};">'
                f'<span class="name">{name}</span><span class="num">{r["level"]:.2f}</span>'
                f'<span class="num">{f_pts(r["1d"])}</span><span class="num">{f_pts(r["1w"])}</span>'
                f'<span class="num">{f_pts(r["1m"])}</span>'
                f'{theme.bar_html(r["pct_1y"], f_pct(r["pct_1y"], 0, False))}</div>'
            )
        st.markdown(f'<div class="bar-table">{"".join(rows)}</div>', unsafe_allow_html=True)

    with right, theme.card("term"):
        curve = iv_panel.term_curve(c)
        upward = not curve.empty and curve["Today"].iloc[-1] > curve["Today"].iloc[0]
        head("VIX term curve", stat("Shape", "contango" if upward else "inverted")
             + stat("1D move", f"{move_pct:.2f}%"))
        if curve.empty:
            st.info("VIX term data unavailable.")
        else:
            st.plotly_chart(market_charts.term_curve_chart(curve, height=270), width="stretch",
                            config=NO_BAR)

    # Expected move
    _HORIZONS = {"1W": 7, "2W": 14, "1M": 30, "2M": 60}
    universe = [s for s in data.config.equities() if s in stored_daily]
    with theme.card("cone"):
        hc, sym_col, hor_col = st.columns([2.2, 1, 1.5], vertical_alignment="center")
        hc.markdown('<span class="panel-title">Expected move</span>', unsafe_allow_html=True)
        symbol = sym_col.selectbox("Symbol", universe, index=universe.index("SPY"),
                                   label_visibility="collapsed")
        hor = hor_col.segmented_control("Horizon", list(_HORIZONS), default="1M",
                                        label_visibility="collapsed")
        horizon = _HORIZONS[hor or "1M"]
        st.markdown('<div class="panel-rule"></div>', unsafe_allow_html=True)
        hist = daily(symbol).tail(90)
        cone_spot = float(hist["close"].iloc[-1])
        implied = {"SPY": vix, "QQQ": c["^VXN"]}.get(symbol)
        if implied is not None and len(implied):
            iv, iv_src = float(implied.iloc[-1]) / 100, "VIX" if symbol == "SPY" else "VXN"
        else:
            iv, iv_src = float(ms.rolling_vol(closes(symbol)).iloc[-1]) / 100, "21d realized vol"
        if np.isnan(iv):
            st.info(f"Not enough {symbol} history.")
        else:
            st.plotly_chart(
                market_charts.cone_chart(hist, expected_move.cone(cone_spot, iv, horizon), height=330),
                width="stretch", config=NO_BAR,
            )
            st.caption(f"1 and 2 SD range at {iv_src} {iv:.1%}.")

with main:
    # Fund fundamentals and holdings ---------------------------------------------------------

    profiles, holdings = reference("etf_profile"), reference("etf_holdings")


    def money_short(x: float) -> str:
        if x != x:
            return "n/a"
        for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
            if abs(x) >= div:
                return f"${x / div:,.1f}{unit}"
        return f"${x:,.0f}"


    def num(x: float, spec: str) -> str:
        return "n/a" if x != x else format(x, spec)


    left, right = st.columns(2, gap="small")
    for col, sym in ((left, "SPY"), (right, "QQQ")):
        with col, theme.card(f"fund-{sym.lower()}"):
            pf = profiles.frame
            prof = pf[pf["symbol"] == sym] if not pf.empty else pd.DataFrame()
            head(f"{sym} fundamentals", asof_tag("yfinance", profiles.asof))
            if prof.empty:
                st.info("Fund profile loading.")
            else:
                p = prof.iloc[-1]
                last = float(c[sym].iloc[-1]) if len(c[sym]) else math.nan
                span = p["week52_high"] - p["week52_low"]
                pos52 = (last - p["week52_low"]) / span if span == span and span > 0 else math.nan
                items = [
                    ("Trailing P/E", num(p["trailing_pe"], ".1f")),
                    ("Price to book", num(p["price_to_book"], ".2f")),
                    ("Dividend yield", f_pct(p["dividend_yield"], 2, False)),
                    ("Expense ratio", f_pct(p["expense_ratio"], 3, False)),
                    ("Assets", money_short(p["total_assets"])),
                    ("Year to date", f_pct(p["ytd_return"])),
                    ("3-year average return", f_pct(p["three_year_return"])),
                    ("52-week range", f"{num(p['week52_low'], ',.0f')} to {num(p['week52_high'], ',.0f')}, "
                                      f"at {f_pct(pos52, 0, False)}"),
                ]
                html('<dl class="kv">' + "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in items)
                     + "</dl>")
            hf = holdings.frame
            h = hf[hf["fund"] == sym] if not hf.empty else pd.DataFrame()
            top = h[h["kind"] == "holding"].sort_values("rank") if not h.empty else h
            if not top.empty:
                conc = funds.concentration(top["weight"])
                top_max = float(top["weight"].max())
                st.markdown(
                    f'<div class="sublabel">Top 10 holdings <span>{f_pct(conc["top"], 1, False)} of '
                    f'the fund, {conc["effective"]:.1f} effective names</span></div>',
                    unsafe_allow_html=True)
                bars = "".join(
                    f'<div class="bar-row" style="grid-template-columns: 3.6rem minmax(0,1fr);">'
                    f'<span class="name" title="{escape(str(r["name"]))}">{escape(str(r["key"]))}</span>'
                    f'{theme.bar_html(r["weight"] / top_max, f_pct(r["weight"], 1, False))}</div>'
                    for _, r in top.iterrows()
                )
                st.markdown(f'<div class="bar-table">{bars}</div>', unsafe_allow_html=True)
                sectors = h[h["kind"] == "sector"].sort_values("rank").head(6)
                if not sectors.empty:
                    s_max = float(sectors["weight"].max())
                    st.markdown('<div class="sublabel">Largest sectors</div>', unsafe_allow_html=True)
                    bars = "".join(
                        f'<div class="bar-row" style="grid-template-columns: 9rem minmax(0,1fr);">'
                        f'<span class="name">{escape(str(r["name"]))}</span>'
                        f'{theme.bar_html(r["weight"] / s_max, f_pct(r["weight"], 1, False))}</div>'
                        for _, r in sectors.iterrows()
                    )
                    st.markdown(f'<div class="bar-table">{bars}</div>', unsafe_allow_html=True)

    # Watchlist

    wl_rows = {}
    for sym in universe + [m for m in MACRO if m in stored_daily]:
        s = closes(sym).tail(300)  # covers the longest window below; skips decades of rolling
        if len(s) < 2:
            continue
        rvs = ms.rolling_vol(s)
        wl_rows[sym] = {
            "Last": float(s.iloc[-1]),
            "1d": chg(s, 1) * 100,
            "1w": chg(s, 5) * 100,
            "1m": chg(s, 21) * 100,
            "vs 50d": float(ms.sma_distance(s, 50).iloc[-1]),
            "vs 200d": float(ms.sma_distance(s, 200).iloc[-1]),
            "RV21": float(rvs.iloc[-1]),
            "RV pctile 1y": ms.percentile_rank(rvs.tail(252), float(rvs.iloc[-1])),
            "Drawdown": float(ms.drawdown(s).iloc[-1]),
        }
    wl = pd.DataFrame(wl_rows).T
    up, down = theme.polarity()
    with theme.card("watchlist"):
        head("Index and cross-asset ETFs", asof_tag("daily", pd.Timestamp(spy.index[-1])))
        st.dataframe(
            wl.style.format(
                {"Last": "{:,.2f}", "1d": "{:+.2f}%", "1w": "{:+.1f}%", "1m": "{:+.1f}%",
                 "vs 50d": "{:+.1f}%", "vs 200d": "{:+.1f}%", "RV21": "{:.1f}%",
                 "RV pctile 1y": "{:.0%}", "Drawdown": "{:.1f}%"},
                na_rep="",
            ).map(lambda v: f"color:{up}" if v > 0 else f"color:{down}", subset=["1d"]),
            width="stretch",
        )

# --- Right rail ------------------------------------------------------------------------------

FG_EDGES = (25, 45, 55, 75)  # band edges of derive.sentiment's labels

with rail_col, st.container(key="rail"):
    with theme.card("feargreed"):
        head("Fear and greed", "composite of 6 measures")
        if fg.score != fg.score:
            st.info("Not enough history for the composite.")
        else:
            status = {"extreme fear": "risk", "fear": "warn", "greed": "warn", "extreme greed": "risk"}
            week = f"{fg_week:.0f} a week ago" if fg_week == fg_week else ""
            html(f'''<div class="fg-top"><span class="score">{fg.score:.0f}</span>
{theme.badge_html(fg.label.capitalize(), status.get(fg.label))}
<span class="card-sub">{week}</span></div>
{theme.meter_html(fg.score, FG_EDGES, "Extreme fear", "Neutral", "Extreme greed")}''')
            bars = "".join(
                f'<div class="bar-row" style="grid-template-columns: 9rem minmax(0,1fr);">'
                f'<span class="name" title="{escape(r["reads"])}">{escape(r["name"])}</span>'
                f'{theme.bar_html(r["score"] / 100, format(r["score"], ".0f"))}</div>'
                for _, r in fg.components.iterrows()
            )
            st.markdown(f'<div class="bar-table">{bars}</div>', unsafe_allow_html=True)
            st.plotly_chart(market_charts.score_history_chart(fg.history), width="stretch",
                            config=NO_BAR)
    news_state, cal = reference("news"), reference("econ_calendar")
    with theme.card("calendar"):
        head("Economic calendar", asof_tag("Yahoo Finance", cal.asof))
        events = cal.frame
        if events.empty:
            st.info("Calendar loading.")
        else:
            only_key = st.toggle("Key releases only", value=True)
            us = events[events["region"] == "US"].copy()
            if only_key:
                us = us[us["key"].astype(bool)]
            today = pd.Timestamp.now(tz=ET).normalize()
            us["local"] = pd.to_datetime(us["time"], utc=True).dt.tz_convert(ET)
            us = us[us["local"] >= today].sort_values("local")
            if us.empty:
                st.info("No US releases scheduled.")

            def fmt(x: float) -> str:
                return "" if x != x else f"{x:g}"

            rows, day = [], None
            for _, e in us.head(14).iterrows():
                d = e["local"].normalize()
                if d != day:
                    label = ("Today" if d == today else "Tomorrow" if d == today + pd.Timedelta(days=1)
                             else f"{d:%a %b %-d}")
                    rows.append(f'<div class="cal-day">{label}</div>')
                    day = d
                nums = [f"{k} {fmt(e[col])}" for k, col in (("act", "actual"), ("exp", "expected"),
                                                             ("prior", "last")) if fmt(e[col])]
                key = theme.badge_html("key", None) if e["key"] and not only_key else ""
                label = "" if pd.isna(e["period"]) else str(e["period"]).strip()
                period = f" ({escape(label)})" if label and label.lower() not in ("nan", "none") else ""
                rows.append(
                    f'<div class="cal-row"><span class="t">{e["local"]:%H:%M}</span>'
                    f'<span>{escape(str(e["event"]))}{period} {key}'
                    f'<span class="n">{", ".join(nums)}</span></span></div>'
                )
            html("".join(rows))

    with theme.card("news"):
        feed = news_feed()
        head("Market news", asof_tag("Yahoo Finance", news_state.asof))
        if feed.empty:
            st.info("Headlines loading.")
        else:
            now = pd.Timestamp.now(tz="UTC")

            def ago(ts: pd.Timestamp) -> str:
                mins = int((now - ts).total_seconds() // 60)
                if mins < 60:
                    return f"{max(mins, 0)}m ago"
                return f"{mins // 60}h ago" if mins < 1440 else f"{ts.tz_convert(ET):%b %-d}"

            rows = []
            for _, n in feed.head(20).iterrows():
                tickers = [t for t in str(n.get("related", "")).split(",") if t and not t.startswith("^")][:2]
                tick = f"<span>{escape(', '.join(tickers))}</span>" if tickers else ""
                rows.append(
                    f'<div class="feed-row"><a href="{escape(str(n["link"]))}" target="_blank" '
                    f'rel="noopener">{escape(str(n["title"]))}</a>'
                    f'<div class="m"><span>{ago(pd.Timestamp(n["published"]))}</span>'
                    f'<span>{escape(str(n["publisher"]))}</span>{tick}</div></div>'
                )
            html(f'<div class="feed">{"".join(rows)}</div>')

