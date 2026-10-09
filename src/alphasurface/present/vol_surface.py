"""Volatility: the implied vol surface of one underlying, from a live chain.

Expiries are picked across tenors (about a week out to the chosen horizon) and pulled through the
gateway, so every pull is also stored. Vol is solved in house: a put-call parity forward per
expiry and Black-76 on it (derive.vol_surface, derive.forward). The vol grid reads first; the
surface, smile and term structure draw the same numbers.
"""

from __future__ import annotations

import math
from html import escape

import numpy as np
import pandas as pd
import streamlit as st

from alphasurface.collector import feed
from alphasurface.collector.chains import default_source, source_label
from alphasurface.derive import vol_surface as vs
from alphasurface.derive.market_state import rolling_vol
from alphasurface.present import data, surface_charts, theme
from alphasurface.storage import reader

ET = "America/New_York"
T = theme.TOKENS
NA = "&ndash;"
NO_BAR = {"displayModeBar": False}
SOURCE_NAMES = {
    "tastytrade": "tastytrade",
    "yfinance": "Yahoo, delayed",
    "synthetic": "Sample data",
}
VIX_FAMILY = [
    ("^VIX9D", "VIX9D", 9),
    ("^VIX", "VIX", 30),
    ("^VIX3M", "VIX3M", 93),
    ("^VIX6M", "VIX6M", 182),
]
INDEX_LIKE = {"SPY", "^GSPC", "^SPX", "SPX", "XSP"}


# --- Loads ----------------------------------------------------------------------------------


def sources() -> list[str]:
    """The default first: tastytrade when connected, else the sample surface; Yahoo either way."""
    return [default_source(), "yfinance"]


@st.cache_data(ttl=300, show_spinner="Pulling the chain...")
def load(source: str, symbol: str, horizon: str, rate: float) -> dict:
    """The chosen expiries' chain through the gateway (stored on the way) and its surface."""
    listed = feed.expirations(source, symbol)
    chosen = vs.select_expiries(listed, vs.HORIZONS[horizon])
    chain = feed.chain(source, symbol, chosen) if chosen else pd.DataFrame()
    surface = vs.build(chain, rate=rate) if not chain.empty else vs.build(chain)
    return {
        "chain": chain,
        "surface": surface,
        "chosen": chosen,
        "quoted": len(chain),
        "kept": len(surface),
        "coverage": chain.attrs.get("coverage", math.nan) if not chain.empty else math.nan,
        "asof": pd.Timestamp(chain["ts"].max()) if not chain.empty else None,
    }


@st.cache_data(ttl=300, show_spinner=False)
def prior(source: str, symbol: str, before: pd.Timestamp, rate: float) -> dict:
    """The surface from the latest stored quotes before this pull, for changes and the gray
    smile. Empty for the sample source, which is never stored."""
    if source in feed.NOT_STORED:
        return {"surface": vs.build(pd.DataFrame()), "asof": None}
    try:
        rows = reader.previous_chain(data.conn(), [symbol], before, source=source, lookback_days=4)
    except Exception:
        rows = pd.DataFrame()
    if rows.empty:
        return {"surface": vs.build(pd.DataFrame()), "asof": None}
    asof = pd.Timestamp(rows["collected_at"].max())
    return {"surface": vs.build(rows, rate=rate, now=asof), "asof": asof}


def vix_points() -> pd.DataFrame:
    rows = []
    for sym, label, days in VIX_FAMILY:
        s = data.closes(sym, live=False)
        if len(s):
            rows.append({"label": label, "days": days, "level": float(s.iloc[-1])})
    return pd.DataFrame(rows)


def realized(symbol: str) -> float:
    closes = data.closes(symbol, live=False)
    return float(rolling_vol(closes, 21).iloc[-1]) / 100 if len(closes) > 22 else math.nan


# --- Formatting -----------------------------------------------------------------------------


def ok(x) -> bool:
    return x is not None and x == x


def vol(x, d: int = 1) -> str:
    return f"{x * 100:.{d}f}%" if ok(x) else NA


def pts(x, d: int = 2) -> str:
    """A difference of vols, in vol points."""
    return f"{x * 100:+.{d}f}" if ok(x) else NA


def html(markup: str) -> None:
    st.markdown("".join(line.strip() for line in markup.splitlines()), unsafe_allow_html=True)


def empty(text: str) -> None:
    html(f'<p class="vs-empty">{escape(text)}</p>')


def head_row(title: str, meta: str, key: str, widths: list[float]):
    """A panel header with controls on the right: title and meta in the first column, one
    keyed, right-aligned column per control. Returns the control columns."""
    cols = st.columns(widths, vertical_alignment="center")
    cols[0].markdown(
        f'<span class="panel-title">{escape(title)}</span><span class="vs-meta">{meta}</span>',
        unsafe_allow_html=True,
    )
    out = []
    for i, col in enumerate(cols[1:]):
        out.append(col.container(key=f"vs-ctl-{key}-{i}"))
    html('<div class="panel-rule"></div>')
    return out


# --- Panels ---------------------------------------------------------------------------------


def kpis(
    symbol: str, source: str, loaded: dict | None, g: pd.DataFrame, prev_g: pd.DataFrame
) -> None:
    tiles = []
    if source == "synthetic" and loaded and not loaded["chain"].empty:
        spot = float(loaded["chain"]["underlying"].iloc[0])
        tiles.append(("Spot", f"{spot:,.2f}", "Sample chain"))
    else:
        view = data.price_view(data.bars(symbol, "1d"), data.quote(symbol))
        if view is None:
            tiles.append(("Spot", NA, ""))
        else:
            px, ref, label, ext = view
            chg = px / ref - 1 if ok(ref) and ref else math.nan
            sub = f"{chg:+.2%} {label}" if ok(chg) else label
            if ext:
                sub = f"{ext[0]} {ext[1]:,.2f}"
            tiles.append(("Spot", f"{px:,.2f}", sub))

    now30 = vs.at_tenor(g, 30) if not g.empty else {}
    was30 = vs.at_tenor(prev_g, 30) if not prev_g.empty else {}
    atm, rr, bf = now30.get("atm"), now30.get("rr25"), now30.get("bf25")
    change = atm - was30["atm"] if ok(atm) and ok(was30.get("atm")) else math.nan
    tiles.append(
        ("ATM IV, 30D", vol(atm), f"{pts(change)} pts since prior pull" if ok(change) else "")
    )
    tiles.append(("Risk reversal, 25Δ 30D", pts(rr), "call minus put, vol pts"))
    tiles.append(("Butterfly, 25Δ 30D", pts(bf), "wings minus ATM, vol pts"))
    slope, leg = vs.term_slope(g) if not g.empty else (math.nan, 90)
    tiles.append((f"Term slope, {leg}D minus 30D", pts(slope), "vol pts"))
    m = data.metrics(symbol) or {}
    rank = m.get("iv_rank")
    tiles.append(("IV rank", f"{rank:.0%}" if ok(rank) else NA, "tastytrade, 1 year"))
    rv = realized(symbol)
    gap = atm - rv if ok(atm) and ok(rv) else math.nan
    tiles.append(
        ("Realized vol, 21D", vol(rv), f"IV minus RV {pts(gap, 1)} pts" if ok(gap) else "")
    )
    cells = "".join(
        f'<div class="t"><div class="l">{escape(label)}</div><div class="v">{value}</div>'
        f'<div class="s">{escape(sub)}</div></div>'
        for label, value, sub in tiles
    )
    html(f'<div class="vs-kpis">{cells}</div>')


def vol_grid(g: pd.DataFrame, loaded: dict | None, error: str | None) -> None:
    with theme.card("vs-grid"):
        meta = ""
        if loaded and loaded["quoted"]:
            meta = f"{loaded['kept']:,} of {loaded['quoted']:,} quotes used, forward from put-call parity"
            cov = loaded["coverage"]
            if ok(cov) and cov < 0.95:
                meta += f", {cov:.0%} of contracts quoted"
        theme.panel_head("Vol grid", escape(meta))
        if error:
            st.error(error)
            return
        if g.empty:
            empty("No expiry has enough two-sided quotes for a smile.")
            return
        ivs = g[["p10", "p25", "atm", "c25", "c10"]].to_numpy(float)
        lo, hi = np.nanmin(ivs), np.nanmax(ivs)

        def shade(x: float) -> str:
            if not ok(x) or hi <= lo:
                return ""
            a = 0.03 + 0.15 * (x - lo) / (hi - lo)
            return f' style="background: rgba(22,26,51,{a:.3f})"'

        body = []
        for r in g.itertuples():
            iv_cells = "".join(
                f"<td{shade(getattr(r, c))}>{vol(getattr(r, c))}</td>"
                for c in ("p10", "p25", "atm", "c25", "c10")
            )
            body.append(
                f'<tr><td class="l">{pd.Timestamp(r.expiry):%b %-d, %Y}</td><td>{r.dte}</td>'
                f"<td>{r.forward:,.2f}</td>{iv_cells}<td>{pts(r.rr25)}</td><td>{pts(r.bf25)}</td></tr>"
            )
        html(
            '<table class="vs-table vgrid"><thead><tr><th class="l">Expiry</th><th>DTE</th>'
            "<th>Forward</th><th>10Δ put</th><th>25Δ put</th><th>ATM</th><th>25Δ call</th>"
            "<th>10Δ call</th><th>RR 25Δ</th><th>BF 25Δ</th></tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table>"
        )


def surface_panel(surface: pd.DataFrame, g: pd.DataFrame) -> None:
    with theme.card("vs-surface"):
        (ctl,) = head_row("Surface", "IV by moneyness and days to expiry", "view", [3, 1])
        with ctl:
            view = (
                st.segmented_control(
                    "View",
                    ["Heatmap", "3D"],
                    default="Heatmap",
                    key="vs_view",
                    label_visibility="collapsed",
                )
                or "Heatmap"
            )
        if surface.empty or surface["expiry"].nunique() < 2:
            empty("A surface needs at least two expiries with a smile.")
            return
        if view == "3D":
            st.plotly_chart(
                surface_charts.surface_3d(vs.mesh(surface)), width="stretch", config=NO_BAR
            )
            return
        spread = np.nanpercentile(np.abs(surface["moneyness"].to_numpy(float) - 1), 95) * 100
        reach = min(30.0, max(5.0, math.ceil(spread / 2.5) * 2.5))
        step = 1.0 if reach <= 10 else 2.5
        points = np.arange(-reach, reach + step / 2, step)
        heat = vs.heat(surface, points)
        dte = g.set_index("expiry")["dte"]
        labels = [f"{pd.Timestamp(e):%b %-d}  {dte.get(e, 0)}d" for e in heat.index]
        st.plotly_chart(
            surface_charts.surface_heatmap(heat, labels), width="stretch", config=NO_BAR
        )


def smile_panel(surface: pd.DataFrame, g: pd.DataFrame, prev: dict) -> None:
    with theme.card("vs-smile"):
        if g.empty:
            head_row("Smile", "", "smile", [1])
            empty("No smile to draw.")
            return
        expiries = g["expiry"].tolist()
        default = expiries[int((g["dte"] - 30).abs().argmin())]
        if st.session_state.get("vs_expiry") not in expiries:
            st.session_state["vs_expiry"] = default
        chosen = st.session_state["vs_expiry"]
        row = g.set_index("expiry").loc[chosen]
        meta = f"RR 25Δ {pts(row['rr25'])}, BF 25Δ {pts(row['bf25'])}"
        pick, axis_ctl = head_row("Smile", escape(meta), "smile", [1.2, 1.5, 1.4])
        with pick:
            st.selectbox(
                "Expiry",
                expiries,
                key="vs_expiry",
                format_func=lambda e: (
                    f"{pd.Timestamp(e):%b %-d, %Y}  {int(g.set_index('expiry').loc[e, 'dte'])}d"
                ),
                label_visibility="collapsed",
            )
        with axis_ctl:
            axis = (
                st.segmented_control(
                    "Axis",
                    ["Moneyness", "Strike"],
                    default="Moneyness",
                    key="vs_axis",
                    label_visibility="collapsed",
                )
                or "Moneyness"
            )
        board = vs.smile(surface, chosen)
        before = vs.smile(prev["surface"], chosen) if not prev["surface"].empty else None
        label = (
            f"Prior pull {pd.Timestamp(prev['asof']).tz_convert(ET):%b %-d %-I:%M %p}"
            if prev["asof"] is not None
            else "Prior pull"
        )
        fig = surface_charts.smile_chart(
            board,
            axis=axis.lower(),
            forward=float(row["forward"]),
            prior=before if before is not None and not before.empty else None,
            prior_label=label,
        )
        st.plotly_chart(fig, width="stretch", config=NO_BAR)


def term_panel(symbol: str, g: pd.DataFrame) -> None:
    with theme.card("vs-term"):
        at30 = vs.at_tenor(g, 30) if not g.empty else {}
        meta = f"30D constant maturity {vol(at30.get('atm'))}" if at30 else ""
        theme.panel_head("ATM term structure", escape(meta))
        term = g[["dte", "atm"]].rename(columns={"atm": "atm_iv"}).dropna()
        if term.empty:
            empty("No ATM vol to draw.")
            return
        vix = vix_points() if data.clean(symbol) in INDEX_LIKE else None
        fig = surface_charts.term_structure_chart(term, vix=vix, rv=realized(symbol))
        st.plotly_chart(fig, width="stretch", config=NO_BAR)


def contracts(surface: pd.DataFrame, symbol: str) -> None:
    with st.expander(f"Contracts ({len(surface):,})"):
        if surface.empty:
            empty("No contracts survived the filters.")
            return
        show = surface[
            [
                "expiry",
                "dte",
                "kind",
                "strike",
                "forward",
                "moneyness",
                "bid",
                "ask",
                "price",
                "spread",
                "iv",
                "delta",
                "volume",
                "open_interest",
            ]
        ].copy()
        st.download_button(
            "Download CSV",
            show.to_csv(index=False).encode(),
            file_name=f"{symbol.lstrip('^')}-surface.csv",
            mime="text/csv",
            type="tertiary",
            icon=":material/download:",
        )
        st.dataframe(
            show,
            hide_index=True,
            width="stretch",
            column_config={
                "expiry": st.column_config.TextColumn("Expiry"),
                "dte": st.column_config.NumberColumn("DTE"),
                "kind": st.column_config.TextColumn("Side"),
                "strike": st.column_config.NumberColumn("Strike", format="%.2f"),
                "forward": st.column_config.NumberColumn("Forward", format="%.2f"),
                "moneyness": st.column_config.NumberColumn("K/F", format="%.3f"),
                "bid": st.column_config.NumberColumn("Bid", format="%.2f"),
                "ask": st.column_config.NumberColumn("Ask", format="%.2f"),
                "price": st.column_config.NumberColumn("Mid", format="%.2f"),
                "spread": st.column_config.NumberColumn("Spread", format="percent"),
                "iv": st.column_config.NumberColumn("IV", format="percent"),
                "delta": st.column_config.NumberColumn("Delta", format="%+.3f"),
                "volume": st.column_config.NumberColumn("Volume", format="%d"),
                "open_interest": st.column_config.NumberColumn("OI", format="%d"),
            },
        )


# --- Page -----------------------------------------------------------------------------------

st.markdown(
    """<style>
.st-key-vs-toolbar { margin-bottom: 4px; }
[class*="st-key-vs-ctl-"] { align-items: flex-end; }
.vs-meta { margin-left: 12px; font-size: 12px; color: var(--fg-subtle); font-variant-numeric: tabular-nums; }
.vs-kpis { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; background: var(--line);
  border: 1px solid var(--line); border-radius: var(--r-md); overflow: hidden; }
@media (min-width: 900px) { .vs-kpis { grid-template-columns: repeat(4, minmax(0, 1fr)); } }
@media (min-width: 1400px) { .vs-kpis { grid-template-columns: repeat(7, minmax(0, 1fr)); } }
.vs-kpis .t { background: var(--surface); padding: 12px 14px 13px; min-width: 0; }
.vs-kpis .l { font-size: 12px; color: var(--fg-subtle); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.vs-kpis .v { font-size: 1.125rem; font-weight: 600; margin-top: 2px; color: var(--fg); font-variant-numeric: tabular-nums; }
.vs-kpis .s { font-size: 12px; color: var(--fg-muted); margin-top: 1px; min-height: 1.2em; white-space: nowrap;
  overflow: hidden; text-overflow: ellipsis; font-variant-numeric: tabular-nums; }
/* Streamlit styles markdown tables with the same specificity and later in the page (a border on
   every cell, its own padding); these rules win, scoped to this page's markup. */
[data-testid="stMarkdownContainer"] .vs-table { width: 100%; margin: 0; border: 0; border-collapse: collapse;
  font-size: 13px; font-variant-numeric: tabular-nums; }
[data-testid="stMarkdownContainer"] .vs-table :is(th, td) { border: 0; border-bottom: 1px solid var(--line);
  padding: 9px 14px; text-align: right; white-space: nowrap; background: none; color: var(--fg); }
[data-testid="stMarkdownContainer"] .vs-table thead th { font-size: 12px; font-weight: 500; color: var(--fg-subtle);
  border-bottom: 1px solid var(--line-strong); padding-top: 2px; }
[data-testid="stMarkdownContainer"] .vs-table :is(th, td).l { text-align: left; }
[data-testid="stMarkdownContainer"] .vs-table :is(th, td):first-child { padding-left: 0; }
[data-testid="stMarkdownContainer"] .vs-table :is(th, td):last-child { padding-right: 0; }
[data-testid="stMarkdownContainer"] .vs-table tbody tr:last-child td { border-bottom: 0; }
[data-testid="stMarkdownContainer"] .vgrid td:nth-child(n+4):nth-child(-n+8) { font-weight: 600; }
[data-testid="stMarkdownContainer"] .vgrid :is(th, td):nth-child(9) { border-left: 1px solid var(--line); }
[data-testid="stMarkdownContainer"] p.vs-empty { font-size: 13px; color: var(--fg-subtle); margin: 8px 0; }
/* Side-by-side cards end level: each column stretches to the row and its card fills it. */
[data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [class*="st-key-card-vs-"]) { align-items: stretch; }
[data-testid="stColumn"]:has(> [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"] > [class*="st-key-card-vs-"]) > [data-testid="stVerticalBlock"] { height: 100%; }
[data-testid="stColumn"] [data-testid="stLayoutWrapper"]:has(> [class*="st-key-card-vs-"]) { height: 100%; }
[data-testid="stColumn"] [class*="st-key-card-vs-"] { height: 100%; }
</style>""",
    unsafe_allow_html=True,
)

available = sources()
if st.session_state.get("vs_source") not in available:
    st.session_state["vs_source"] = available[0]
theme.intro("Volatility", eyebrow="Options", tag=source_label(st.session_state["vs_source"]))

with st.container(key="vs-toolbar"):
    c_sym, c_tenor, c_src, _ = st.columns([1.1, 1.5, 1.3, 3], vertical_alignment="center")
    raw = c_sym.text_input(
        "Symbol",
        value="SPY",
        key="vs_symbol",
        max_chars=12,
        placeholder="Symbol",
        label_visibility="collapsed",
    )
    horizon = (
        c_tenor.segmented_control(
            "Tenor", list(vs.HORIZONS), default="6M", key="vs_horizon", label_visibility="collapsed"
        )
        or "6M"
    )
    if len(available) > 1:
        c_src.selectbox(
            "Source",
            available,
            key="vs_source",
            format_func=SOURCE_NAMES.get,
            label_visibility="collapsed",
        )
source = st.session_state["vs_source"]
symbol = data.clean(raw) or "SPY"

loaded, error = None, None
try:
    loaded = load(source, symbol, horizon, data.rate())
except Exception as exc:  # a dead symbol or a rate-limited vendor fails its panel, not the page
    error = f"Could not load the {symbol.lstrip('^')} chain from {SOURCE_NAMES.get(source, source)}: {exc}"
if loaded is not None and not loaded["chosen"] and error is None:
    error = f"No listed expiries for {symbol.lstrip('^')} from {SOURCE_NAMES.get(source, source)}."

surface = loaded["surface"] if loaded else vs.build(pd.DataFrame())
g = vs.grid(surface)
prev = (
    prior(source, symbol, loaded["asof"] - pd.Timedelta(seconds=30), data.rate())
    if loaded and loaded["asof"] is not None
    else {"surface": vs.build(pd.DataFrame()), "asof": None}
)
prev_g = vs.grid(prev["surface"])

kpis(symbol, source, loaded, g, prev_g)
vol_grid(g, loaded, error)
surface_panel(surface, g)
left, right = st.columns(2, gap="medium")
with left:
    smile_panel(surface, g, prev)
with right:
    term_panel(symbol, g)
contracts(surface, symbol)
