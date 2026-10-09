"""Research: company fundamentals and the economy, one page in two tabs.

Fundamentals: key stats, valuation, profitability, analyst targets, statements, earnings and SEC
filings for a stock; profile and holdings for a fund. Economy: FRED macro series (with a key),
the economic calendar, the Treasury curve and the 10Y minus 3M spread.

Deep links: ?tab=fundamentals&symbol=AAPL and ?tab=economy. Data is write-through
(collector.fundamentals, collector.economy, collector.reference): the stored copy shows at once
and refreshes in the background past its window. Only the open tab runs.
"""

from __future__ import annotations

import logging
import math
from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from alphasurface.collector import economy as econ
from alphasurface.collector import fundamentals as fa
from alphasurface.collector import reference as ref
from alphasurface.derive import economy as em
from alphasurface.derive import fundamentals as fd
from alphasurface.present import data, theme, watchlist
from alphasurface.present.surface_charts import apply_layout
from alphasurface.storage import reference as store

log = logging.getLogger(__name__)

ET = "America/New_York"
T = theme.TOKENS
NA = "&ndash;"
NO_BAR = {"displayModeBar": False}
TABS = {"fundamentals": "Fundamentals", "economy": "Economy"}
LARGE_CAPS = [
    "AAPL",
    "MSFT",
    "NVDA",
    "AMZN",
    "GOOGL",
    "META",
    "TSLA",
    "AVGO",
    "JPM",
    "BRK-B",
    "LLY",
    "V",
    "XOM",
    "UNH",
    "COST",
    "NFLX",
    "AMD",
]
STATEMENTS = {"Income statement": "income", "Balance sheet": "balance", "Cash flow": "cashflow"}
YIELDS = {"3M": "^IRX", "5Y": "^FVX", "10Y": "^TNX", "30Y": "^TYX"}
UNITS = {"B": "billions", "M": "millions"}
FORMS = {
    "10-K": "Annual report",
    "10-K/A": "Annual report, amended",
    "10-Q": "Quarterly report",
    "10-Q/A": "Quarterly report, amended",
    "8-K": "Current report",
    "8-K/A": "Current report, amended",
    "20-F": "Annual report, foreign issuer",
    "6-K": "Current report, foreign issuer",
    "DEF 14A": "Proxy statement",
    "DEFA14A": "Additional proxy materials",
    "S-1": "Registration statement",
    "S-3": "Shelf registration",
    "S-3ASR": "Shelf registration",
    "S-8": "Employee plan registration",
    "11-K": "Employee plan annual report",
    "SD": "Specialized disclosure",
    "3": "Initial insider holdings",
    "4": "Insider transaction",
    "SC 13G": "Ownership over 5%",
    "SC 13G/A": "Ownership over 5%, amended",
    "SC 13D": "Active ownership over 5%",
    "SC 13D/A": "Active ownership over 5%, amended",
}
EXTERNAL = (
    '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
    'stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
    '<path d="M14 4h6v6"/><path d="M20 4 10 14"/><path d="M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5"/></svg>'
)
RECS = [
    ("rec_strong_buy", "Strong buy", T["good"], 1.0),
    ("rec_buy", "Buy", T["good"], 0.55),
    ("rec_hold", "Hold", T["line_strong"], 1.0),
    ("rec_sell", "Sell", T["risk"], 0.55),
    ("rec_strong_sell", "Strong sell", T["risk"], 1.0),
]


# --- Formatting -----------------------------------------------------------------------------


def ok(x) -> bool:
    try:
        return x is not None and not pd.isna(x)
    except (TypeError, ValueError):
        return False


def money(x, d: int = 2) -> str:
    if not ok(x):
        return NA
    for div, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(x) >= div:
            return f"{x / div:,.{d}f}{unit}"
    return f"{x:,.0f}"


def pct(x, d: int = 1, sign: bool = False) -> str:
    return format(x, f"{'+' if sign else ''}.{d}%") if ok(x) else NA


def num(x, spec: str = ",.2f") -> str:
    return format(x, spec) if ok(x) else NA


def mult(x) -> str:
    return f"{x:,.1f}x" if ok(x) and x > 0 else NA


def day(x, spec: str = "%b %-d, %Y") -> str:
    return pd.Timestamp(x).strftime(spec) if ok(x) else NA


def signed(text: str, x) -> str:
    """Wrap text in the up or down color by the sign of x."""
    if not ok(x) or x == 0:
        return text
    return f'<span class="{"up" if x > 0 else "down"}">{text}</span>'


def html(markup: str) -> None:
    """Flat HTML through markdown: st.html would strip the SVG and the link targets."""
    st.markdown(
        "\n".join(line.strip() for line in markup.splitlines() if line.strip()),
        unsafe_allow_html=True,
    )


def kv(rows: list[tuple[str, str]]) -> str:
    return (
        '<dl class="kvl">'
        + "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in rows)
        + "</dl>"
    )


def tiles(items: list[tuple[str, str, str]]) -> str:
    return (
        '<div class="kstrip">'
        + "".join(
            f'<div class="t"><div class="l">{label}</div><div class="v">{value}</div>'
            f'<div class="s">{sub}</div></div>'
            for label, value, sub in items
        )
        + "</div>"
    )


def empty(text: str) -> None:
    html(f'<p class="empty">{escape(text)}</p>')


def spark(values: pd.Series, w: int = 96, h: int = 26) -> str:
    v = values.dropna()
    if len(v) < 2:
        return ""
    lo, hi = float(v.min()), float(v.max())
    span = hi - lo or 1.0
    step = w / (len(v) - 1)
    pts = " ".join(
        f"{i * step:.1f},{h - 2 - (float(x) - lo) / span * (h - 4):.1f}" for i, x in enumerate(v)
    )
    return (
        f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><polyline points="{pts}" fill="none" '
        f'stroke="{T["fg_muted"]}" stroke-width="1.25" stroke-linejoin="round"/></svg>'
    )


# --- Loads: stored copy now, background refresh past the window ------------------------------


def _keyed(table: str, key_col: str, key: str, fetch) -> ref.Fetched:
    return fa.refresh_for(table, key_col, key, fetch, config=data.config, max_age=fa.MAX_AGE[table])


@st.cache_data(ttl=60, show_spinner="Loading fundamentals...")
def snapshot(sym: str) -> ref.Fetched:
    return _keyed("fundamentals", "symbol", sym, lambda: fa.fetch_snapshot(sym))


@st.cache_data(ttl=60, show_spinner=False)
def financials(sym: str) -> ref.Fetched:
    return _keyed("financials", "symbol", sym, lambda: fa.fetch_financials(sym))


@st.cache_data(ttl=60, show_spinner=False)
def earnings(sym: str) -> ref.Fetched:
    return _keyed("earnings", "symbol", sym, lambda: fa.fetch_earnings(sym))


@st.cache_data(ttl=60, show_spinner=False)
def fund(sym: str) -> tuple[ref.Fetched, ref.Fetched]:
    return (
        _keyed("etf_profile", "symbol", sym, lambda: ref.fetch_profiles([sym])),
        _keyed("etf_holdings", "fund", sym, lambda: ref.fetch_holdings([sym])),
    )


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def filings(sym: str) -> pd.DataFrame:
    if ref.OFFLINE:
        return pd.DataFrame()
    try:
        return fa.fetch_filings(sym)
    except Exception:
        log.warning("filings for %s unavailable", sym, exc_info=True)
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def vol_metrics(sym: str) -> dict:
    """The stored tastytrade metrics row (IVx, IV rank, earnings), read only, never pulled here."""
    try:
        df = store.latest(
            "market_metrics", data.config, where="WHERE symbol = ?", params=[sym.lstrip("^")]
        )
    except Exception:
        return {}
    return df.iloc[-1].to_dict() if not df.empty else {}


@st.cache_data(ttl=60, show_spinner=False)
def calendar() -> ref.Fetched:
    now = pd.Timestamp.now(tz="UTC")  # the Dashboard's window, so both pages share one stored pull
    return ref.refresh(
        "econ_calendar",
        lambda: ref.fetch_calendar(now - pd.Timedelta(days=3), now + pd.Timedelta(days=10)),
        config=data.config,
    )


@st.cache_data(ttl=60, show_spinner=False)
def macro() -> ref.Fetched:
    return econ.macro(data.config)


@st.cache_data(ttl=300, show_spinner="Loading yields...")
def yields() -> dict[str, pd.Series]:
    out = {}
    for tenor, sym in YIELDS.items():
        s = data.closes(sym, live=False)
        if len(s):
            out[tenor] = pd.Series(s.to_numpy(dtype=float), index=pd.to_datetime(s.index))
    return out


# --- Fundamentals ----------------------------------------------------------------------------


def _sync_symbol() -> None:
    sym = data.clean(st.session_state.get("research_symbol") or "") or "AAPL"
    st.session_state["research_symbol"] = sym
    st.session_state["research_qp"] = sym
    st.query_params["symbol"] = sym


def pick_symbol() -> str:
    qp = data.clean(str(st.query_params.get("symbol", "") or ""))
    if qp and qp != st.session_state.get("research_qp"):  # a deep link wins over the last pick
        st.session_state["research_qp"] = qp
        st.session_state["research_symbol"] = qp
    st.session_state.setdefault("research_symbol", qp or "AAPL")
    options = sorted(
        set(LARGE_CAPS) | set(watchlist.DEFAULT) | {st.session_state["research_symbol"]}
    )
    col, _ = st.columns([1, 4])
    col.selectbox(
        "Symbol",
        options,
        key="research_symbol",
        accept_new_options=True,
        on_change=_sync_symbol,
        label_visibility="collapsed",
        placeholder="Symbol",
    )
    return st.session_state["research_symbol"]


def quote_line(sym: str, snap: dict) -> str:
    view = data.price_view(data.bars(sym, "1d"), data.quote(sym))
    if view is None:
        if not ok(snap.get("price")):
            return ""
        asof = day(snap.get("collected_at"), "%b %-d") if ok(snap.get("collected_at")) else ""
        view = (snap["price"], snap.get("prev_close"), f"Yahoo Finance {asof}".strip(), None)
    px, base, label, ext = view

    def move(a, b) -> str:
        c = a - b if ok(b) else math.nan
        return signed(f"{c:+,.2f} ({c / b:+.2%})", c) if ok(c) and b else ""

    extended = (
        f'<div class="fa-ext"><span>{ext[0]}</span><b>{ext[1]:,.2f}</b>{move(ext[1], px)}</div>'
        if ext
        else ""
    )
    return (
        f'<div class="fa-quote"><div class="fa-px"><span class="px">{px:,.2f}</span>'
        f'<span class="chg">{move(px, base)}</span><span class="src">{escape(label)}</span></div>'
        f"{extended}</div>"
    )


def header(sym: str, snap: dict, meta: list[str]) -> None:
    parts = "".join(f"<span>{escape(m)}</span>" for m in meta if m)
    html(f"""<div class="fa-top"><div class="fa-id"><div><span class="sym">{escape(sym.lstrip("^"))}</span>
<span class="name">{escape(str(snap.get("name") or sym))}</span></div><div class="meta">{parts}</div></div>
{quote_line(sym, snap)}</div>""")


def range_note(price, lo, hi) -> str:
    if not (ok(price) and ok(lo) and ok(hi)) or hi <= lo:
        return ""
    return f"at {min(max((price - lo) / (hi - lo), 0), 1):.0%} of range"


def stock_tiles(snap: dict, ivm: dict, next_report: pd.Series | None) -> str:
    price = snap.get("price")
    ivx = ivm.get("ivx")
    report = ""
    if next_report is not None:
        report = day(next_report["report_date"], "%b %-d")
    elif ok(ivm.get("earnings_date")):
        report = day(ivm["earnings_date"], "%b %-d")
    est = (
        f"EPS estimate {next_report['eps_estimate']:.2f}"
        if next_report is not None and ok(next_report["eps_estimate"])
        else ""
    )
    return tiles(
        [
            (
                "Market cap",
                money(snap.get("market_cap")),
                f"EV {money(snap.get('enterprise_value'))}",
            ),
            ("P/E, TTM", mult(snap.get("trailing_pe")), f"Forward {mult(snap.get('forward_pe'))}"),
            ("EPS, TTM", num(snap.get("trailing_eps")), f"Forward {num(snap.get('forward_eps'))}"),
            ("Dividend yield", pct(snap.get("dividend_yield"), 2), ""),
            ("Beta", num(snap.get("beta")), "5Y monthly"),
            (
                "52-week range",
                f"{num(snap.get('week52_low'))} to {num(snap.get('week52_high'))}",
                range_note(price, snap.get("week52_low"), snap.get("week52_high")),
            ),
            (
                "IVx",
                pct(ivx),
                f"IV rank {pct(ivm.get('iv_rank'), 0)}" if ok(ivm.get("iv_rank")) else "",
            ),
            ("Next earnings", report or NA, est),
        ]
    )


def analysts(snap: dict) -> None:
    with theme.card("fa-analysts"):
        n = snap.get("analysts")
        consensus = str(snap.get("recommendation") or "").replace("_", " ").capitalize()
        meta = f"{consensus}, {n:.0f} analysts" if consensus and ok(n) else ""
        theme.panel_head("Analysts", escape(meta))
        lo, mid, mean, hi = (
            snap.get(k) for k in ("target_low", "target_median", "target_mean", "target_high")
        )
        price = snap.get("price")
        counts = [(label, snap.get(col), color, alpha) for col, label, color, alpha in RECS]
        total = sum(c for _, c, _, _ in counts if ok(c))
        if not (ok(lo) and ok(hi)) and not total:
            empty("No analyst coverage.")
            return
        out = []
        if ok(lo) and ok(hi) and hi > lo:

            def at(x):
                return f"{min(max((x - lo) / (hi - lo), 0), 1) * 100:.1f}%"

            marks = f'<i class="mean" style="left:{at(mean)}"></i>' if ok(mean) else ""
            if ok(price):
                marks += f'<i class="cur" style="left:{at(price)}"></i>'
            legend = (
                '<span class="lg"><i class="cur"></i>Current<i class="mean"></i>Mean</span>'
                if ok(price)
                else '<span class="lg"><i class="mean"></i>Mean</span>'
            )
            out.append(
                f'<div class="tgt"><div class="track">{marks}</div>'
                f'<div class="ends"><span>{num(lo)}</span>{legend}<span>{num(hi)}</span></div></div>'
            )
            up = (mean / price - 1) if ok(mean) and ok(price) and price else math.nan
            out.append(
                kv(
                    [
                        ("Low target", num(lo)),
                        ("Median target", num(mid)),
                        (
                            "Mean target",
                            f"{num(mean)} {signed(pct(up, 1, True), up) if ok(up) else ''}",
                        ),
                        ("High target", num(hi)),
                    ]
                )
            )
        if total:
            segs = "".join(
                f'<span style="width:{c / total:.2%};background:{color};opacity:{a}" '
                f'title="{label} {c:.0f}"></span>'
                for label, c, color, a in counts
                if ok(c) and c
            )
            legend = "".join(
                f"<span>{label} <b>{c:.0f}</b></span>" for label, c, _, _ in counts if ok(c)
            )
            out.append(
                f'<div class="rec"><div class="bar">{segs}</div><div class="legend">{legend}</div></div>'
            )
        html("".join(out))


def statements(sym: str, long: pd.DataFrame, asof) -> None:
    with theme.card("fa-statements"):
        title, kind_col, freq_col = st.columns([1.3, 2.4, 1.2], vertical_alignment="center")
        title.markdown(
            '<span class="panel-title">Financial statements</span>', unsafe_allow_html=True
        )
        with kind_col.container(key="fa-ctl-kind"):
            kind = (
                st.segmented_control(
                    "Statement",
                    list(STATEMENTS),
                    default="Income statement",
                    key="fa_statement",
                    label_visibility="collapsed",
                )
                or "Income statement"
            )
        with freq_col.container(key="fa-ctl-freq"):
            freq = (
                st.segmented_control(
                    "Period",
                    ["Annual", "Quarterly"],
                    default="Annual",
                    key="fa_freq",
                    label_visibility="collapsed",
                )
                or "Annual"
            ).lower()
        html('<div class="panel-rule"></div>')
        source = theme.asof("Yahoo Finance", asof) if asof is not None else ""
        full = fd.wide(long, STATEMENTS[kind], freq) if not long.empty else pd.DataFrame()
        if full.empty:
            empty(f"No {freq} {kind.lower()} for {sym}.")
            return
        table = full.iloc[:, :5]  # newest first
        latest = table.columns[0]
        yoy = fd.growth(full, fd.LAG[freq])[latest]
        div, unit = fd.scale(table.drop(index=[r for r in table.index if r in fd.PER_SHARE]))
        periods = list(reversed(table.columns))  # oldest to newest, the same order as the chart
        span = "year" if freq == "annual" else "quarter"
        head = (
            f"<th>USD {UNITS.get(unit, unit)}</th>"
            + "".join(f"<th>{pd.Timestamp(c):%b %Y}</th>" for c in periods)
            + f'<th class="yoy" title="Latest {span} against the same {span} a year earlier">YoY</th>'
        )
        body = []
        for label, row in table.iterrows():
            per_share = label in fd.PER_SHARE
            cells = "".join(
                f"<td>{num(row[c]) if per_share else num(row[c] / div if ok(row[c]) else row[c], ',.1f')}</td>"
                for c in periods
            )
            g = yoy.get(label, math.nan)
            name = f"{label}, USD" if per_share else label
            body.append(
                f"<tr><th>{escape(name)}</th>{cells}"
                f'<td class="yoy">{signed(pct(g, 1, True), g) if ok(g) else NA}</td></tr>'
            )
        left, right = st.columns([3, 2], gap="large")
        with left:
            html(
                f'<table class="ftab"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table>'
                f'<p class="src">{source}</p>'
            )
        with right:
            fig = statement_chart(long, freq, div, unit, height=36 * (len(body) + 1) + 24)
            if fig is None:
                empty("No revenue or earnings history.")
            else:
                st.plotly_chart(fig, width="stretch", config=NO_BAR)


def statement_chart(
    long: pd.DataFrame, freq: str, div: float, unit: str, height: int = 280
) -> go.Figure | None:
    income = fd.wide(long, "income", freq)
    cash = fd.wide(long, "cashflow", freq)
    series = [
        ("Revenue", income, T["fg"]),
        ("Net income", income, T["ink_2"]),
        ("Free cash flow", cash, T["line_strong"]),
    ]
    fig = go.Figure()
    for label, table, color in series:
        if table.empty or label not in table.index:
            continue
        row = table.loc[label].iloc[:5].dropna().sort_index()
        fig.add_trace(
            go.Bar(
                x=[f"{pd.Timestamp(c):%b %Y}" for c in row.index],
                y=row.to_numpy() / div,
                name=label,
                marker_color=color,
                hovertemplate=f"{label} %{{y:,.1f}}{unit}<extra></extra>",
            )
        )
    if not fig.data:
        return None
    fig = apply_layout(fig, max(height, 240))
    fig.update_layout(barmode="group", bargap=0.3, legend={"orientation": "h", "x": 0, "y": 1.1})
    fig.update_yaxes(title=None, ticksuffix=unit)
    return fig


def earnings_panel(sym: str, state: ref.Fetched) -> None:
    with theme.card("fa-earnings"):
        df = state.frame
        if df.empty:
            theme.panel_head("Earnings", "")
            empty(f"No earnings history for {sym}.")
            return
        df = df.sort_values("report_date", ascending=False)
        done = df[df["eps_actual"].notna()].head(8)
        beats = int((done["eps_actual"] > done["eps_estimate"]).sum())
        theme.panel_head("Earnings", f"Beat {beats} of last {len(done)}" if len(done) else "")
        upcoming = df[df["eps_actual"].isna() & (df["report_date"] > pd.Timestamp.now(tz="UTC"))]
        if len(upcoming):
            nxt = upcoming.iloc[-1]
            local = pd.Timestamp(nxt["report_date"]).tz_convert(ET)
            html(
                kv(
                    [
                        ("Next report", f"{local:%a %b %-d, %Y}"),
                        ("EPS estimate", num(nxt["eps_estimate"])),
                    ]
                )
            )
        rows = "".join(
            f"<tr><td>{day(r.report_date)}</td><td>{num(r.eps_estimate)}</td><td>{num(r.eps_actual)}</td>"
            f"<td>{signed(pct(r.surprise, 1, True), r.surprise)}</td></tr>"
            for r in done.itertuples()
        )
        if rows:
            html(
                f'<table class="etab"><thead><tr><th>Reported</th><th>Estimate</th><th>Actual</th>'
                f"<th>Surprise</th></tr></thead><tbody>{rows}</tbody></table>"
            )


def filings_panel(sym: str) -> None:
    with theme.card("fa-filings"):
        df = filings(sym)
        cik = df["cik"].iloc[0] if not df.empty and df["cik"].iloc[0] else None
        theme.panel_head(
            "Recent reports",
            f'<a href="{escape(fa.edgar_url(sym.lstrip("^"), cik))}" '
            'target="_blank" rel="noopener">All filings on EDGAR</a>',
        )
        if df.empty:
            empty("No recent filings.")
            return
        rows = "".join(
            f'<a class="fl" href="{escape(r.url)}" target="_blank" rel="noopener">'
            f'<span class="d">{day(r.date, "%b %-d, %Y")}</span>'
            f'<span class="k">{escape(r.type)}</span>'
            f'<span class="t">{escape(FORMS.get(str(r.type).upper(), r.title or r.type))}</span>'
            f'<span class="x">{EXTERNAL}</span></a>'
            for r in df.head(10).itertuples()
        )
        html(f'<div class="flist">{rows}</div>')


def stock_view(sym: str, snap: dict) -> None:
    fin, earn = financials(sym), earnings(sym)
    edf = earn.frame
    nxt = None
    if not edf.empty:
        up = edf[edf["eps_actual"].isna() & (edf["report_date"] > pd.Timestamp.now(tz="UTC"))]
        nxt = up.sort_values("report_date").iloc[0] if len(up) else None
    with theme.card("fa-head"):
        header(
            sym,
            snap,
            [
                snap.get("sector", ""),
                snap.get("industry", ""),
                snap.get("exchange", ""),
                snap.get("currency", ""),
            ],
        )
        html(stock_tiles(snap, vol_metrics(sym), nxt))

    long = fin.frame
    r = fd.key_ratios(snap, long)
    c1, c2, c3 = st.columns(3, gap="medium")
    with c1, theme.card("fa-valuation"):
        theme.panel_head("Valuation", "")
        html(
            kv(
                [
                    ("Enterprise value", money(snap.get("enterprise_value"))),
                    ("P/E, TTM", mult(snap.get("trailing_pe"))),
                    ("P/E, forward", mult(snap.get("forward_pe"))),
                    ("Price to sales", mult(r["price_to_sales"])),
                    ("Price to book", mult(r["price_to_book"])),
                    ("EV to EBITDA", mult(r["ev_to_ebitda"])),
                    ("Free cash flow yield", pct(r["fcf_yield"], 2)),
                ]
            )
        )
    with c2, theme.card("fa-profit"):
        theme.panel_head("Profitability", "")
        html(
            kv(
                [
                    ("Gross margin", pct(r["gross_margin"])),
                    ("Operating margin", pct(r["operating_margin"])),
                    ("Net margin", pct(r["net_margin"])),
                    ("Return on equity", pct(r["roe"])),
                    ("Return on assets", pct(r["roa"])),
                    (
                        "Debt to equity",
                        f"{r['debt_to_equity']:.2f}x" if ok(r["debt_to_equity"]) else NA,
                    ),
                    (
                        "Revenue growth, YoY",
                        signed(
                            pct(snap.get("revenue_growth"), 1, True), snap.get("revenue_growth")
                        ),
                    ),
                    (
                        "Earnings growth, YoY",
                        signed(
                            pct(snap.get("earnings_growth"), 1, True), snap.get("earnings_growth")
                        ),
                    ),
                ]
            )
        )
    with c3:
        analysts(snap)

    statements(sym, long, fin.asof)

    left, right = st.columns([1, 1], gap="medium")
    with left:
        earnings_panel(sym, earn)
    with right:
        filings_panel(sym)

    summary = str(snap.get("summary") or "").strip()
    if summary:
        with theme.card("fa-profile"):
            site = str(snap.get("website") or "")
            link = (
                f'<a href="{escape(site)}" target="_blank" rel="noopener">{escape(site.split("//")[-1])}</a>'
                if site
                else ""
            )
            theme.panel_head("Profile", link)
            emp = snap.get("employees")
            html(
                f'<p class="about">{escape(summary)}</p>'
                + (f'<p class="note">{emp:,.0f} employees</p>' if ok(emp) else "")
            )


def fund_view(sym: str, snap: dict) -> None:
    profile, holdings = fund(sym)
    p = profile.frame.iloc[0].to_dict() if not profile.frame.empty else {}
    kind = {"ETF": "ETF", "MUTUALFUND": "Mutual fund", "INDEX": "Index"}.get(
        snap.get("quote_type", ""), ""
    )
    with theme.card("fa-head"):
        header(
            sym,
            snap,
            [
                kind,
                str(p.get("category") or ""),
                snap.get("exchange", ""),
                snap.get("currency", ""),
            ],
        )
        if kind == "Index":
            html('<p class="note">No financial statements for indices.</p>')
            return
        html(
            tiles(
                [
                    ("Total assets", money(p.get("total_assets")), ""),
                    ("Expense ratio", pct(p.get("expense_ratio"), 2), ""),
                    ("Yield", pct(p.get("dividend_yield"), 2), ""),
                    (
                        "YTD return",
                        signed(pct(p.get("ytd_return"), 1, True), p.get("ytd_return")),
                        "",
                    ),
                    (
                        "3Y average return",
                        signed(
                            pct(p.get("three_year_return"), 1, True), p.get("three_year_return")
                        ),
                        "",
                    ),
                    ("Beta, 3Y", num(p.get("beta_3y")), ""),
                    ("P/E", mult(p.get("trailing_pe")), ""),
                    (
                        "52-week range",
                        f"{num(snap.get('week52_low'))} to {num(snap.get('week52_high'))}",
                        range_note(
                            snap.get("price"), snap.get("week52_low"), snap.get("week52_high")
                        ),
                    ),
                ]
            )
        )
        html('<p class="note">No financial statements for funds.</p>')
    h = holdings.frame
    left, right = st.columns([1, 1], gap="medium")
    for col, kind_key, title in (
        (left, "holding", "Top holdings"),
        (right, "sector", "Sector weights"),
    ):
        with col, theme.card(f"fa-{kind_key}"):
            rows = h[h["kind"] == kind_key].sort_values("rank") if not h.empty else h
            top = rows["weight"].max() if not rows.empty else 0
            theme.panel_head(
                title,
                theme.asof("Yahoo Finance", holdings.asof) if holdings.asof is not None else "",
            )
            if rows.empty:
                empty("Not reported for this fund.")
                continue
            body = "".join(
                f'<div class="bar-row" style="grid-template-columns: {"4.5rem 1fr minmax(0,9rem)" if kind_key == "holding" else "1fr minmax(0,9rem)"};">'
                + (
                    f'<span class="name"><b>{escape(str(r.key))}</b></span>'
                    if kind_key == "holding"
                    else ""
                )
                + f'<span class="name">{escape(str(r.name))}</span>'
                f"{theme.bar_html(r.weight / top if top else 0, pct(r.weight))}</div>"
                for r in rows.head(10).itertuples()
            )
            html(f'<div class="bar-table">{body}</div>')


def fundamentals_tab() -> None:
    sym = pick_symbol()
    state = snapshot(sym)
    if state.frame.empty:
        with theme.card("fa-head"):
            theme.panel_head(sym.lstrip("^"), "")
            empty(f"No fundamentals for {sym}.")
        return
    snap = state.frame.iloc[-1].to_dict()
    if str(snap.get("quote_type", "")).upper() in fa.FUNDS:
        fund_view(sym, snap)
    else:
        stock_view(sym, snap)


# --- Economy ---------------------------------------------------------------------------------


def macro_strip() -> None:
    if not data.config.keys.fred:  # optional source; README covers FRED_API_KEY
        return
    state = macro()
    df = state.frame
    with theme.card("ec-macro"):
        theme.panel_head("Macro", theme.asof("FRED", state.asof) if state.asof is not None else "")
        if df.empty:
            empty("Macro series loading.")
            return
        items = []
        for sid, (label, how) in econ.SERIES.items():
            s = df[df["series"] == sid].set_index("date")["value"].sort_index()
            if s.empty:
                continue
            if sid == "DFF":
                s = s.resample("ME").last()  # one point a month, like the others
            shown = em.yoy(s, 12) if how == "yoy" else s
            shown = shown.dropna()
            if shown.empty:
                continue
            last, prev = (
                float(shown.iloc[-1]),
                float(shown.iloc[-2]) if len(shown) > 1 else math.nan,
            )
            quarterly = sid.startswith("A191")
            period = (
                f"Q{shown.index[-1].quarter} {shown.index[-1]:%Y}"
                if quarterly
                else f"{shown.index[-1]:%b %Y}"
            )
            delta = f"{last - prev:+.2f} pts" if ok(prev) else ""
            items.append(
                (label, f"{last:.2f}%", f"{period} {delta}".strip(), spark(shown.tail(24)))
            )
        if not items:
            empty("Macro series loading.")
            return
        html(
            '<div class="mstrip">'
            + "".join(
                f'<div class="t"><div class="l">{label}</div><div class="v">{value}</div>'
                f'<div class="s">{sub}</div>{sp}</div>'
                for label, value, sub, sp in items
            )
            + "</div>"
        )


def calendar_panel() -> None:
    state = calendar()
    with theme.card("ec-calendar"):
        theme.panel_head(
            "Economic calendar",
            theme.asof("Yahoo Finance", state.asof) if state.asof is not None else "",
        )
        ev = state.frame
        if ev.empty:
            empty("Calendar loading.")
            return
        regions = sorted(r for r in ev["region"].dropna().unique() if r)
        a, b, c = st.columns([1.1, 1.2, 1.3], vertical_alignment="center")
        region = a.selectbox(
            "Region",
            ["All regions", *regions],
            index=(regions.index("US") + 1) if "US" in regions else 0,
            key="ec_region",
            label_visibility="collapsed",
        )
        view = (
            b.segmented_control(
                "View",
                ["Upcoming", "Released"],
                default="Upcoming",
                key="ec_view",
                label_visibility="collapsed",
            )
            or "Upcoming"
        )
        only_key = c.toggle("Key releases only", value=False, key="ec_key")
        ev = ev.copy()
        if region != "All regions":
            ev = ev[ev["region"] == region]
        if only_key:
            ev = ev[ev["key"].astype(bool)]
        ev["local"] = pd.to_datetime(ev["time"], utc=True).dt.tz_convert(ET)
        now = pd.Timestamp.now(tz=ET)
        today = now.normalize()
        upcoming = view == "Upcoming"
        ev = (
            ev[ev["local"] >= today].sort_values("local")
            if upcoming
            else ev[ev["local"] < now].sort_values("local", ascending=False)
        )
        if ev.empty:
            empty("No releases match.")
            return

        def val(x) -> str:
            return f"{x:g}" if ok(x) else ""

        def day_label(d: pd.Timestamp) -> str:
            if d == today:
                return "Today"
            if d == today + pd.Timedelta(days=1):
                return "Tomorrow"
            if d == today - pd.Timedelta(days=1):
                return "Yesterday"
            return f"{d:%A %b %-d}"

        fields = [("Forecast", "expected"), ("Prior", "last")]
        if not upcoming:
            fields.insert(0, ("Actual", "actual"))
        fields = [(c, f) for c, f in fields if ev[f].notna().any()]  # Yahoo rarely has forecasts
        cols = [c for c, _ in fields]
        rows, current = [], None
        for e in ev.itertuples():
            d = e.local.normalize()
            if d != current:
                rows.append(
                    f'<tr class="dayrow"><td colspan="{3 + len(cols)}">{day_label(d)}</td></tr>'
                )
                current = d
            period = "" if str(e.period).lower() in ("", "nan", "none") else escape(str(e.period))
            key = theme.badge_html("Key", None) if e.key else ""
            nums = [
                f"<b>{val(getattr(e, f))}</b>" if f == "actual" else val(getattr(e, f))
                for _, f in fields
            ]
            rows.append(
                f"<tr><td>{e.local:%H:%M}</td><td class='ev'>{escape(str(e.event))} {key}</td>"
                f"<td class='l'>{period}</td>" + "".join(f"<td>{n}</td>" for n in nums) + "</tr>"
            )
        widths = '<col style="width:4.5rem"><col><col style="width:6rem">' + "".join(
            '<col style="width:7rem">' for _ in cols
        )
        head = '<th>Time, ET</th><th class="l">Event</th><th class="l">Period</th>' + "".join(
            f"<th>{c}</th>" for c in cols
        )
        html(
            f'<div class="cwrap"><table class="ctab"><colgroup>{widths}</colgroup>'
            f"<thead><tr>{head}</tr></thead><tbody>{''.join(rows)}</tbody></table></div>"
        )


def rates_cards() -> None:
    ys = yields()
    with theme.card("ec-curve"):
        theme.panel_head("Treasury curve", "Yahoo Finance, percent")
        if not ys:
            empty("No Treasury yield history yet.")
        else:
            end = max(s.index.max() for s in ys.values())
            snaps = [
                ("Today", end, T["fg"], "solid"),
                ("1 month ago", end - pd.Timedelta(days=30), T["ink_2"], "solid"),
                ("1 year ago", end - pd.Timedelta(days=365), T["line_strong"], "dash"),
            ]
            fig = go.Figure()
            for label, when, color, dash in snaps:
                c = em.curve_at(ys, when)
                xs = [t for t in YIELDS if t in c and ok(c[t])]
                fig.add_trace(
                    go.Scatter(
                        x=xs,
                        y=[c[t] for t in xs],
                        name=label,
                        mode="lines+markers",
                        line=dict(color=color, width=2, dash=dash),
                        marker=dict(size=6),
                        hovertemplate=f"{label} %{{x}} %{{y:.2f}}%<extra></extra>",
                    )
                )
            fig = apply_layout(fig, 240)
            fig.update_layout(legend=dict(orientation="h", x=0, y=1.15))
            fig.update_yaxes(ticksuffix="%")
            st.plotly_chart(fig, width="stretch", config=NO_BAR)
            rows = "".join(
                f"<tr><th>{t}</th><td>{num(float(s.iloc[-1]), '.2f')}%</td>"
                + "".join(
                    f"<td>{signed(f'{em.change_bp(s, d):+.0f}', em.change_bp(s, d)) if ok(em.change_bp(s, d)) else NA}</td>"
                    for d in (1, 30, 365)
                )
                + "</tr>"
                for t, s in ys.items()
            )
            html(
                f'<table class="ytab"><thead><tr><th>Tenor</th><th>Yield</th><th>1D, bp</th><th>1M, bp</th>'
                f"<th>1Y, bp</th></tr></thead><tbody>{rows}</tbody></table>"
            )
    with theme.card("ec-spread"):
        if "10Y" not in ys or "3M" not in ys:
            theme.panel_head("10Y minus 3M", "")
            empty("Needs the 10-year and 3-month yields.")
            return
        sp = em.spread(ys["10Y"], ys["3M"])
        sp = sp[sp.index >= sp.index.max() - pd.Timedelta(days=5 * 365)]
        now = float(sp.iloc[-1])
        flag = theme.badge_html("Inverted", "risk") if now < 0 else ""
        theme.panel_head("10Y minus 3M", f"{flag} <b>{now:+.2f} pts</b>")
        fig = go.Figure(
            go.Scatter(
                x=sp.index,
                y=sp.to_numpy(),
                mode="lines",
                line=dict(color=T["fg"], width=1.5),
                hovertemplate="%{x|%b %-d, %Y} %{y:+.2f} pts<extra></extra>",
            )
        )
        fig.add_hline(y=0, line=dict(color=T["line_strong"], width=1))
        fig = apply_layout(fig, 240)
        fig.update_yaxes(ticksuffix=" pts", tickformat=".1f")
        st.plotly_chart(fig, width="stretch", config=NO_BAR)


def economy_tab() -> None:
    macro_strip()
    left, right = st.columns([3, 2], gap="medium")
    with left:
        calendar_panel()
    with right:
        rates_cards()


# --- Page ------------------------------------------------------------------------------------


def _sync_tab() -> None:
    label = st.session_state.get("research_tab", "Fundamentals")
    st.query_params["tab"] = next((k for k, v in TABS.items() if v == label), "fundamentals")


st.markdown(
    """<style>
.fa-top { display: flex; justify-content: space-between; align-items: flex-end; gap: 24px; flex-wrap: wrap;
  padding-bottom: 14px; }
.fa-id .sym { font-size: 1.125rem; font-weight: 700; letter-spacing: -0.01em; color: var(--fg); margin-right: 10px; }
.fa-id .name { font-size: 1.125rem; font-weight: 500; color: var(--fg); }
.fa-id .meta { display: flex; flex-wrap: wrap; gap: 0 14px; margin-top: 4px; font-size: 12.5px; color: var(--fg-subtle); }
.fa-px { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 12px; font-variant-numeric: tabular-nums; }
.fa-px .px { font-size: 1.75rem; font-weight: 700; letter-spacing: -0.02em; color: var(--fg); }
.fa-px .chg { font-size: 15px; font-weight: 600; }
.fa-px .src { font-size: 12px; color: var(--fg-subtle); }
.up { color: var(--good); }
.down { color: var(--risk); }
.kstrip, .mstrip { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 1px; background: var(--line);
  border: 1px solid var(--line); border-radius: var(--r-md); overflow: hidden; }
@media (min-width: 768px) { .kstrip { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .mstrip { grid-template-columns: repeat(5, minmax(0, 1fr)); } }
@media (min-width: 1400px) { .kstrip { grid-template-columns: repeat(8, minmax(0, 1fr)); } }
.kstrip .t, .mstrip .t { background: var(--surface); padding: 12px 14px 13px; min-width: 0; }
.kstrip .l, .mstrip .l { font-size: 12px; color: var(--fg-subtle); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.kstrip .v, .mstrip .v { font-size: 1.0625rem; font-weight: 600; margin-top: 2px; font-variant-numeric: tabular-nums;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--fg); }
.kstrip .s, .mstrip .s { font-size: 12px; color: var(--fg-muted); margin-top: 1px; min-height: 1.2em;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-variant-numeric: tabular-nums; }
.mstrip svg { display: block; margin-top: 8px; }
.kvl { margin: 0; }
.kvl div { display: flex; justify-content: space-between; gap: 16px; padding: 8px 0; border-bottom: 1px solid var(--line); }
.kvl div:last-child { border-bottom: none; }
.kvl dt { font-size: 13px; color: var(--fg-muted); }
.kvl dd { margin: 0; font-size: 13px; font-weight: 600; color: var(--fg); text-align: right;
  font-variant-numeric: tabular-nums; white-space: nowrap; }
.tgt { margin: 10px 0 6px; }
.tgt .track { position: relative; height: 4px; border-radius: 2px; background: var(--surface-raised);
  border: 1px solid var(--line); }
.tgt i { position: absolute; top: 50%; width: 10px; height: 10px; border-radius: 50%; transform: translate(-50%, -50%); }
.tgt i.mean { background: var(--surface); border: 2px solid var(--fg-subtle); }
.tgt i.cur { background: var(--fg); }
.tgt .ends { display: flex; justify-content: space-between; align-items: center; margin-top: 6px; font-size: 12px;
  color: var(--fg-subtle); font-variant-numeric: tabular-nums; }
.tgt .lg { display: inline-flex; align-items: center; gap: 6px; }
.tgt .lg i { position: static; transform: none; display: inline-block; width: 8px; height: 8px; margin-left: 8px; }
.rec { margin-top: 14px; }
.rec .bar { display: flex; align-items: stretch; height: 8px; border-radius: 2px; overflow: hidden; gap: 2px; }
.rec .bar span { display: block; height: 100%; }
.rec .legend { display: flex; flex-wrap: wrap; gap: 4px 14px; margin-top: 8px; font-size: 12px; color: var(--fg-subtle); }
.rec .legend b { color: var(--fg); font-weight: 600; }
.ftab, .etab, .ctab, .ytab { width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }
.ftab th, .ftab td, .etab th, .etab td, .ctab th, .ctab td, .ytab th, .ytab td {
  padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: right; vertical-align: top; }
.ftab thead th, .etab thead th, .ctab thead th, .ytab thead th { font-size: 12px; font-weight: 500;
  color: var(--fg-subtle); }
.ftab th:first-child, .ftab td:first-child, .etab th:first-child, .etab td:first-child,
.ctab th:first-child, .ctab td:first-child, .ytab th:first-child { text-align: left; padding-left: 0; }
.ftab tbody th { font-weight: 500; color: var(--fg-muted); text-align: left; padding-left: 0; }
.ftab td { color: var(--fg); font-weight: 600; }
.ftab td small { display: block; font-size: 11.5px; font-weight: 500; color: var(--fg-subtle); min-height: 1.2em; }
.ftab th:last-child, .ftab td:last-child, .etab th:last-child, .etab td:last-child,
.ctab th:last-child, .ctab td:last-child, .ytab th:last-child, .ytab td:last-child { padding-right: 0; }
.ytab tbody th { font-weight: 600; color: var(--fg); text-align: left; padding-left: 0; }
.cwrap { max-height: 900px; overflow-y: auto; }
.ctab thead th { position: sticky; top: 0; background: var(--surface); z-index: 1; }
.ctab .l, .ctab .ev { text-align: left; }
.ctab .ev { color: var(--fg); }
.ctab tr.past td { color: var(--fg-muted); }
.ctab tr.dayrow td { padding: 14px 0 6px; font-size: 12px; font-weight: 600; color: var(--fg-subtle); text-align: left; }
.ctab tr.dayrow.now td { color: var(--fg); }
.ctab td { color: var(--fg); }
.flist { font-size: 13px; }
.flist a.fl { display: grid; grid-template-columns: 6.75rem 4.5rem minmax(0, 1fr) 16px; gap: 12px;
  align-items: center; padding: 10px 8px; margin: 0 -8px; border-bottom: 1px solid var(--line);
  border-radius: 4px; color: var(--fg) !important; text-decoration: none !important; }
.flist a.fl:last-child { border-bottom: none; }
.flist a.fl:hover { background: var(--surface-raised); }
.flist a.fl:hover .t { text-decoration: underline; }
.fl .d { color: var(--fg-subtle); font-variant-numeric: tabular-nums; }
.fl .k { font-size: 12px; font-weight: 600; color: var(--fg-muted); font-variant-numeric: tabular-nums; }
.fl .t { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.fl .x { display: grid; place-items: center; color: var(--fg-subtle); }
.about { font-size: 13.5px; line-height: 1.6; color: var(--fg-muted); margin: 0; max-width: 980px; }
.fa-quote { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
.fa-ext { display: flex; align-items: baseline; gap: 8px; font-size: 13px; color: var(--fg-subtle);
  font-variant-numeric: tabular-nums; }
.fa-ext b { font-weight: 600; color: var(--fg); }
.st-key-fa-ctl-kind, .st-key-fa-ctl-freq { align-items: flex-end; }
/* Cards side by side end level: each column stretches to the row and its card fills the column. */
[data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [class*="st-key-card-"]) { align-items: stretch; }
[data-testid="stColumn"]:has(> [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"] > [class*="st-key-card-"]) > [data-testid="stVerticalBlock"] { height: 100%; }
[data-testid="stColumn"] [data-testid="stLayoutWrapper"]:has(> [class*="st-key-card-"]) { height: 100%; }
[data-testid="stColumn"] [class*="st-key-card-"] { height: 100%; }
.ftab .yoy { border-left: 1px solid var(--line) !important; padding-left: 16px !important; }
/* Streamlit styles markdown tables and paragraphs with the same specificity and later in the page:
   every cell gets a full border and its own padding. These rules win, scoped to this page's markup. */
[data-testid="stMarkdownContainer"] :is(.ftab, .etab, .ctab, .ytab) { margin: 0; border: 0; }
[data-testid="stMarkdownContainer"] :is(.ftab, .etab, .ctab, .ytab) :is(th, td) {
  border: 0; border-bottom: 1px solid var(--line); background: none; padding: 9px 14px; line-height: 1.35; }
[data-testid="stMarkdownContainer"] :is(.ftab, .etab, .ctab, .ytab) thead th {
  border-bottom: 1px solid var(--line-strong); padding-top: 2px; white-space: nowrap; }
[data-testid="stMarkdownContainer"] :is(.ftab, .etab, .ctab, .ytab) :is(th, td):first-child { padding-left: 0; }
[data-testid="stMarkdownContainer"] :is(.ftab, .etab, .ctab, .ytab) :is(th, td):last-child { padding-right: 0; }
[data-testid="stMarkdownContainer"] :is(.ftab, .etab, .ytab) tbody tr:last-child :is(th, td) { border-bottom: 0; }
[data-testid="stMarkdownContainer"] .ftab td small { display: none; }
[data-testid="stMarkdownContainer"] .ctab { table-layout: fixed; }
[data-testid="stMarkdownContainer"] .ctab thead th { position: sticky; top: 0; z-index: 1; background: var(--surface); }
[data-testid="stMarkdownContainer"] .ctab td.ev { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
[data-testid="stMarkdownContainer"] p.src { margin: 10px 0 0; font-size: 12px; color: var(--fg-subtle); text-align: right; }
[data-testid="stMarkdownContainer"] p.note { font-size: 12px; color: var(--fg-subtle); margin: 8px 0 0; }
[data-testid="stMarkdownContainer"] p.empty { font-size: 13px; color: var(--fg-subtle); margin: 8px 0; }
[data-testid="stMarkdownContainer"] p.about { font-size: 13.5px; line-height: 1.6; color: var(--fg-muted); margin: 0; }
</style>""",
    unsafe_allow_html=True,
)

theme.intro("Research", eyebrow="Markets")
default = TABS.get(str(st.query_params.get("tab", "fundamentals")).lower(), "Fundamentals")
fund_tab, econ_tab = st.tabs(
    list(TABS.values()), default=default, key="research_tab", on_change=_sync_tab
)
if fund_tab.open:
    with fund_tab:
        fundamentals_tab()
if econ_tab.open:
    with econ_tab:
        economy_tab()
