"""Scanner: many option chains at once, every hit with the reason it was flagged.

Scans run on a button, not on every rerun, and are cached for five minutes. Every chain and daily
bar a scan fetches goes through the market-data gateway (collector.feed), so it is analyzed here
and stored for history in the same step. The same scans run headless with
`python -m collector.scan`. Rules and thresholds: docs/scanner.md.
"""

from __future__ import annotations

import math
from dataclasses import asdict

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from collector import scan as cscan
from collector.chains import PROVIDERS, default_source, source_label
from derive import scan as sc
from derive import vehicles as vh
from derive.market_state import rolling_vol
from present import data, theme
from present.surface_charts import apply_layout
from storage import reader

T = theme.TOKENS
conn = data.conn()

st.markdown(
    """<style>
.feed { display: grid; gap: 0; font-size: 13px; }
.feed-row { display: grid; grid-template-columns: 4.5rem 1fr; gap: 12px; padding: 7px 0;
  border-top: 1px solid var(--line); line-height: 1.45; }
.feed-row:first-child { border-top: none; }
.feed-row .sym { font-weight: 600; color: var(--fg); }
.feed-row .why { color: var(--fg-muted); }
.about { margin: 0; font-size: 13px; color: var(--fg-muted); }
</style>""",
    unsafe_allow_html=True,
)


def _stored_rate() -> float:
    bar = reader.latest_bar(conn, "^IRX", "1d")
    return float(bar["close"]) if bar is not None else 4.0


def _load_defaults() -> None:
    """Put the chosen preset's default filters into the sidebar widgets."""
    f = sc.PRESETS[st.session_state["preset"]].filters
    ss = st.session_state
    ss["f_dte"] = (f.dte_min, max(f.dte_max, f.dte_min))
    ss["f_zero"] = f.zero_dte
    ss["f_dist"] = round(f.dist_max * 100)
    ss["f_delta"] = (f.delta_min, f.delta_max)
    ss["f_oi"] = int(f.min_oi)
    ss["f_vol"] = int(f.min_volume)
    ss["f_spread"] = 0.0 if math.isinf(f.max_spread) else f.max_spread
    ss["f_spread_pct"] = 0 if math.isinf(f.max_spread_pct) else round(f.max_spread_pct * 100)
    ss["f_side"] = {"both": "Both", "call": "Calls", "put": "Puts"}[f.side]


if "preset" not in st.session_state:
    st.session_state["preset"] = "stale"
    _load_defaults()

with st.sidebar:
    st.header("Universe")
    symbols_text = st.text_area("Symbols", ", ".join(cscan.UNIVERSE), height=80)
    providers = list(PROVIDERS)
    source = st.selectbox("Source", providers, index=providers.index(
        "tastytrade" if default_source() == "tastytrade" else "yfinance"), key="scan_source")
    max_exp = st.number_input("Expiries per symbol", 1, 8, 3, help="Nearest first.")

    st.header("Filters")
    dte = st.slider("Days to expiry", 0, 180, key="f_dte")
    zero = st.toggle("Same-day expiries only (0DTE)", key="f_zero")
    dist = st.slider("Distance from spot, at most (%)", 1, 50, key="f_dist")
    delta = st.slider("Delta, absolute", 0.0, 1.0, step=0.05, key="f_delta")
    min_oi = st.number_input("Open interest, at least", 0, step=100, key="f_oi")
    min_vol = st.number_input("Volume, at least", 0, step=50, key="f_vol")
    max_spread = st.number_input("Spread at most ($, 0 for any)", 0.0, step=0.05, key="f_spread")
    max_spread_pct = st.number_input("Spread at most (% of mark, 0 for any)", 0, 100, key="f_spread_pct")
    side = st.radio("Side", ["Both", "Calls", "Puts"], horizontal=True, key="f_side")

    st.header("Model inputs")
    rate = st.number_input("Risk-free rate (%)", value=round(_stored_rate(), 2), step=0.25) / 100
    div = st.number_input("Dividend yield (%)", 0.0, value=0.0, step=0.1) / 100

symbols = tuple(dict.fromkeys(s.strip().upper() for s in symbols_text.replace("\n", ",").split(",") if s.strip()))
filters = sc.Filters(
    dte_min=dte[0], dte_max=dte[1], zero_dte=zero, dist_max=dist / 100,
    delta_min=delta[0], delta_max=delta[1], min_oi=min_oi, min_volume=min_vol,
    max_spread=max_spread or math.inf, max_spread_pct=(max_spread_pct / 100) or math.inf,
    side={"Both": "both", "Calls": "call", "Puts": "put"}[side],
)

theme.intro("Options scanner", eyebrow="Scanner", tag=source_label(source))


@st.cache_data(ttl=300, show_spinner=False)
def _scan(symbols: tuple, preset: str, source: str, filters: dict, params: dict, r: float, q: float,
          max_exp: int) -> dict:
    res = cscan.run_scan(list(symbols), preset, source, sc.Filters(**filters), params, r=r, q=q,
                         max_expiries=max_exp, conn=data.conn(), background=True)
    return {"hits": res.hits, "context": res.context, "new": sorted(res.new), "errors": res.errors,
            "contracts": res.contracts, "kept": len(res.frame), "at": res.scanned_at}


scan_tab, vehicle_tab = st.tabs(["Scan", "Options or the underlying"])

with scan_tab:
    pick, go_col = st.columns([3, 1], vertical_alignment="bottom")
    key = pick.selectbox("Scan", list(sc.PRESETS), key="preset", on_change=_load_defaults,
                         format_func=lambda k: sc.PRESETS[k].name)
    preset = sc.PRESETS[key]
    run = go_col.button("Run scan", type="primary", width="stretch", key="run_scan")
    st.markdown(f'<p class="about">{preset.about}</p>', unsafe_allow_html=True)

    with st.expander("Thresholds"):
        cols = st.columns(len(preset.params) or 1)
        params = {
            name: col.number_input(p.label, value=float(p.default), step=float(p.step), key=f"p_{key}_{name}")
            for col, (name, p) in zip(cols, preset.params.items())
        }

    args = (symbols, key, source, asdict(filters), params, rate, div, int(max_exp))
    if run:
        st.session_state["scan_args"] = args
    if st.session_state.get("scan_args") != args:
        if "scan_args" in st.session_state:
            st.info("Settings changed. Run the scan to update.")
        else:
            st.info(f"Ready to scan {len(symbols)} symbols.")
    if "scan_args" in st.session_state:
        with st.spinner(f"Scanning {len(st.session_state['scan_args'][0])} chains..."):
            out = _scan(*st.session_state["scan_args"])
        shown = sc.PRESETS[st.session_state["scan_args"][1]]
        hits, ctx, new = out["hits"], out["context"], set(out["new"])
        ids = [sc.hit_id(shown.key, h) for _, h in hits.iterrows()]

        c1, c2, c3, c4 = st.columns(4)
        scanned = len(st.session_state["scan_args"][0])
        c1.metric("Symbols scanned", f"{scanned - len(out['errors'])} of {scanned}")
        c2.metric("Contracts pulled", f"{out['contracts']:,}", f"{out['kept']:,} after filters",
                  delta_color="off", delta_arrow="off")
        c3.metric("Hits", f"{len(hits)}")
        c4.metric("New since last run", f"{len(new)}" if st.session_state["scan_args"][2] != "synthetic" else "n/a")
        if out["errors"]:
            st.caption("Skipped: " + "; ".join(f"{s} ({e})" for s, e in out["errors"].items()))

        with theme.card("hits"):
            theme.panel_head(f"{shown.name}, {len(hits)} hit{'s' * (len(hits) != 1)}",
                             f"{out['at']:%b %-d %H:%M} UTC")
            if hits.empty:
                st.caption("No contracts passed the filters.")
            else:
                table = hits.copy()
                table.insert(0, "New", ["new" if i in new else "" for i in ids])
                fmt = {"strike": "{:g}", "mark": "{:.2f}", "iv": "{:.1%}", "delta": "{:+.2f}",
                       "spread": "{:.2f}", "open_interest": "{:,.0f}", "volume": "{:,.0f}",
                       "score": "{:.2f}", "dte": "{:.0f}"}
                st.dataframe(
                    table.style.format(fmt, na_rep=""), hide_index=True, width="stretch", placeholder="",
                    column_config={
                        "symbol": "Symbol", "expiry": "Expiry", "dte": "DTE", "strike": "Strike",
                        "kind": "Side", "mark": "Mark", "iv": "IV", "delta": "Delta", "spread": "Spread",
                        "open_interest": "OI", "volume": "Volume", "score": shown.score,
                        "reason": st.column_config.TextColumn("Why", width="large"),
                    },
                )

        left, right = st.columns(2)
        with left, theme.card("by_symbol"):
            theme.panel_head("Hits by symbol")
            counts = hits["symbol"].value_counts() if not hits.empty else pd.Series(dtype=int)
            if counts.empty:
                st.caption("No hits.")
            else:
                top = counts.max()
                rows = "".join(
                    f'<div class="bar-row" style="grid-template-columns: 4.5rem minmax(0,1fr);">'
                    f'<span class="name">{sym}</span>{theme.bar_html(n / top, str(n))}</div>'
                    for sym, n in counts.items()
                )
                st.markdown(f'<div class="bar-table">{rows}</div>', unsafe_allow_html=True)
        with right, theme.card("feed"):
            theme.panel_head("New since last run")
            fresh = hits[[i in new for i in ids]] if not hits.empty else hits
            if st.session_state["scan_args"][2] == "synthetic":
                st.caption("Synthetic scans are not recorded.")
            elif fresh.empty:
                st.caption("Nothing new.")
            else:
                rows = "".join(f'<div class="feed-row"><span class="sym">{h.symbol}</span>'
                               f'<span class="why">{h.reason}</span></div>' for h in fresh.head(12).itertuples())
                st.markdown(f'<div class="feed">{rows}</div>', unsafe_allow_html=True)

        if not ctx.empty:
            with st.expander("Symbol context"):
                show = ctx[["spot", "change", "rv5", "rv10", "rv21", "rv63", "atm_iv", "atm_iv_prev", "atm_dte"]]
                st.dataframe(
                    show.style.format({"spot": "{:,.2f}", "change": "{:+.2%}", "rv5": "{:.1%}", "rv10": "{:.1%}",
                                       "rv21": "{:.1%}", "rv63": "{:.1%}", "atm_iv": "{:.1%}",
                                       "atm_iv_prev": "{:.1%}", "atm_dte": "{:.0f}"}, na_rep=""),
                    width="stretch", placeholder="",
                    column_config={"spot": "Spot", "change": "Today", "rv5": "RV 5d", "rv10": "RV 10d",
                                   "rv21": "RV 21d", "rv63": "RV 63d", "atm_iv": "ATM IV",
                                   "atm_iv_prev": "ATM IV, last pull", "atm_dte": "ATM DTE"},
                )
                st.caption("ATM IV at the expiry nearest 30 days.")


def _defaults_for(symbol: str) -> tuple[float, float, float]:
    """Spot, implied vol and realized vol defaults from the store, decimals."""
    bars = reader.get_ohlcv(conn, symbol, "1d", tail=90)
    spot = float(bars["close"].iloc[-1]) if not bars.empty else 100.0
    rv = float(rolling_vol(bars["close"], 21).iloc[-1]) / 100 if len(bars) > 21 else 0.25
    vix = reader.latest_bar(conn, "^VIX", "1d") if symbol == "SPY" else None
    iv = float(vix["close"]) / 100 if vix is not None else rv
    return spot, iv, rv


with vehicle_tab:
    a, b, c, d = st.columns(4)
    v_symbol = a.text_input("Symbol", "SPY", key="v_symbol").strip().upper()
    spot0, iv0, rv0 = _defaults_for(v_symbol)
    v_spot = b.number_input("Spot", 0.01, value=round(spot0, 2), step=1.0, key=f"v_spot_{v_symbol}")
    v_move = c.number_input("Target move (%)", -50.0, 50.0, 3.0, 0.5) / 100
    v_days = d.number_input("Days to target (trading)", 1, 252, 10)
    e, f_, g, h = st.columns(4)
    v_exp = e.number_input("Option expiry (trading days)", 1, 504, max(21, int(v_days)))
    v_iv = f_.number_input("Implied vol (%)", 1.0, 300.0, round(iv0 * 100, 1), 0.5) / 100
    v_rv = g.number_input("Simulated vol (%)", 1.0, 300.0, round(rv0 * 100, 1), 0.5) / 100
    v_margin = h.number_input("Delta one margin (%)", 1.0, 100.0, 10.0, 1.0,
                              help="Margin as a share of notional, standing in for a future.") / 100
    to_target = st.toggle("Drift paths to the target", value=False)

    if v_exp < v_days:
        st.warning("The options expire before the target date.")
    else:
        table, curves = vh.compare(v_spot, v_move, int(v_days), int(v_exp), v_iv, rate, div,
                                   margin=v_margin, sim_vol=v_rv, drift_to_target=to_target)
        with theme.card("vehicles"):
            theme.panel_head("Side by side", f"Simulated: 4,000 paths at {v_rv:.1%} vol")
            st.dataframe(
                table.style.format({
                    "Capital": "${:,.0f}", "Delta, shares": "{:+.0f}", "P&L at target": "{:+,.0f}",
                    "Return at target": "{:+.0%}", "P&L if flat": "{:+,.0f}",
                    "Breakeven": "{:,.2f}", "Breakeven move": "{:+.2%}", "EV, simulated": "{:+,.0f}",
                    "P(profit)": "{:.0%}", "VaR 95%": "{:,.0f}",
                }, na_rep="n/a").format({"Max loss": lambda x: "unlimited" if math.isinf(x) else f"{x:,.0f}"}),
                hide_index=True, width="stretch",
            )
            st.caption(f"Options marked at unchanged IV; shorts at {vh.REG_T:.0%} Reg T. Excludes "
                       "commissions, borrow and roll.")

        with theme.card("vehicle_curves"):
            theme.panel_head("P&L at the horizon")
            fig = go.Figure()
            styles = [(T["fg"], "solid"), (T["fg"], "dash"), (T["fg_subtle"], "solid"),
                      (T["ink_2"], "dash"), (T["line_strong"], "solid"), (T["fg_subtle"], "dot")]
            for (name, col), (color, dash) in zip(curves.items(), styles):
                fig.add_trace(go.Scatter(x=curves.index, y=col, mode="lines", name=name,
                                         line=dict(color=color, width=2, dash=dash),
                                         hovertemplate=f"{name}<br>%{{x:,.2f}}: %{{y:+,.0f}}<extra></extra>"))
            fig.add_hline(y=0, line=dict(color=T["line_strong"], width=1))
            for x, label in ((v_spot, "spot"), (v_spot * (1 + v_move), "target")):
                fig.add_vline(x=x, line=dict(color=T["line_strong"], width=1, dash="dot"),
                              annotation_text=label, annotation_font_color=T["fg_subtle"])
            fig.update_xaxes(title="price at the horizon")
            fig.update_yaxes(title="P&L ($)")
            fig = apply_layout(fig, 380)
            fig.update_layout(legend=dict(orientation="h", x=0, y=1.12))
            st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
