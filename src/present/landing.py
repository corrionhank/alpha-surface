"""Landing page: what the product does, every solution in one section, and the way in.

Rendered as one HTML block so the sections can run full-bleed, which Streamlit's own layout
cannot do. It goes through st.markdown rather than st.html: st.html sanitizes away inline SVG and
link targets, which the icons and in-app links need. The preview card and the data figures are live, read from the store on each visit;
nothing on this page is a sample. Links go to the sign-in page, which forwards to the page asked
for once you are in.
"""

from __future__ import annotations

import math
import re
from html import escape

import pandas as pd
import streamlit as st

from config import REPO_ROOT
from derive import market_state as ms
from present import data, theme
from storage import reader

T = theme.TOKENS


@st.cache_data(ttl=300)
def _closes(symbol: str) -> pd.Series:
    df = reader.get_ohlcv(data.conn(), symbol, "1d")
    if df.empty:
        return pd.Series(dtype=float)
    dates = df["ts"].dt.tz_convert("America/New_York").dt.date
    return pd.Series(df["close"].to_numpy(), index=dates)


def snapshot() -> dict | None:
    """The overview page's state strip, condensed for the preview card. None without data."""
    spy, vix, vix3m = _closes("SPY"), _closes("^VIX"), _closes("^VIX3M")
    if len(spy) < 200 or vix.empty:
        return None
    iv_rv = pd.concat({"iv": vix, "rv": ms.rolling_vol(spy)}, axis=1).dropna()
    vrp = iv_rv["iv"] - iv_rv["rv"]
    term = pd.concat({"front": vix, "back": vix3m}, axis=1).dropna()
    slope = ms.term_slope(*term.iloc[-1]) if len(term) else float("nan")
    ratio = term["back"] / term["front"]
    vix_last = float(vix.iloc[-1])
    vrp_now = float(vrp.iloc[-1]) if len(vrp) else float("nan")
    dist200 = ms.sma_distance(spy, 200)
    return {
        "asof": max(spy.index[-1], vix.index[-1]),
        "regime": ms.regime(vix_last, slope, vrp_now),
        "vix": vix_last,
        "em_day": vix_last / math.sqrt(252),
        "vrp": vrp_now,
        "vrp_pct": ms.percentile_rank(vrp, vrp_now),
        "vix_pct": ms.percentile_rank(vix.tail(252), vix_last),
        "ratio_pct": ms.percentile_rank(ratio.tail(252), float(ratio.iloc[-1])) if len(ratio) else math.nan,
        "stretch_pct": ms.percentile_rank(dist200, float(dist200.iloc[-1])),
    }


@st.cache_data(ttl=300)
def store_stats() -> dict:
    row = data.conn().execute(
        "SELECT count(*), count(DISTINCT symbol), min(ts), max(ts) FROM ohlcv"
    ).fetchone()
    formulas = (REPO_ROOT / "docs" / "formulas.md").read_text(encoding="utf-8")
    return {
        "bars": row[0] or 0,
        "symbols": row[1] or 0,
        "years": ((row[3] - row[2]).days / 365.25) if row[2] is not None else 0.0,
        "sections": len(re.findall(r"^## \d+\.", formulas, flags=re.M)),
    }


icon, MARK, ARROW = theme.icon, theme.MARK, theme.ARROW

# (page stem, icon paths, title, description). Every page the product has, in nav order.
SOLUTIONS = [
    ("overview", '<path d="M3 12h4l3-8 4 16 3-8h4"/>', "Market overview",
     "Regime, stretch, the priced move and implied minus realized vol for the index complex, "
     "each shown with its own percentile."),
    ("option_chain", '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 10h18M3 15h18M12 4v16"/>',
     "Options chain",
     "Every expiry and strike with implied vol solved in house. Pick a contract for intrinsic and "
     "extrinsic value, decay per day, its price against realized vol, and the yield for selling it."),
    ("scanner", '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>', "Options scanner",
     "Sweep chains across a watchlist for stale quotes after a move, vol out of line with realized, "
     "unusual activity, price spikes and open gaps, with an alert when something new shows up."),
    ("scenarios", '<path d="M3 12h4"/><path d="M7 12c4 0 6-5 14-6"/><path d="M7 12h14"/>'
     '<path d="M7 12c4 0 6 5 14 6"/>', "Market scenarios",
     "Thousands of simulated futures, with jumps or reshuffled history, then what they mean for a "
     "position, a hedged option and a bankroll. Real crashes replayed from today's price."),
    ("vol_surface", '<path d="m3 17 5-7 4 5 3-4 6 6"/><path d="M3 21h18"/>', "Volatility surface",
     "The full surface from mid quotes, with the smile, ATM term structure and 25-delta skew "
     "drawn from the same numbers."),
    ("chart", '<path d="M7 3v4M7 17v4M17 3v2M17 13v8"/><rect x="5" y="7" width="4" height="10" rx="1"/>'
     '<rect x="15" y="5" width="4" height="8" rx="1"/>', "Price charts",
     "Daily and hourly bars from the local store, with range, change and realized vol for the "
     "window on screen."),
    ("pricing", '<path d="M18 7V5H6l6 7-6 7h12v-2"/>', "Black-Scholes pricer",
     "Price and Greeks for any European option with a continuous dividend yield, plus value "
     "against spot."),
    ("pot_odds", '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
     "Pot odds",
     "The win rate a payoff needs to break even, set against the odds implied vol and realized "
     "vol each give you."),
    ("docs_portal", '<path d="M4 19.5V5a2 2 0 0 1 2-2h14v16H6a2 2 0 0 0-2 2.5z"/><path d="M8 7h8M8 11h6"/>',
     "Docs and formulas",
     "Every metric traced to its formula and rendered in the app, from realized vol to the "
     "delta-hedged option, so no number on screen is a black box."),
]

STEPS = [
    ("Collect", "A collector writes quotes and bars to Parquet, partitioned by day and queried "
     "with DuckDB. Records are append-only, so any past state can be rebuilt as it was known."),
    ("Derive", "Implied vol comes from our own Black-Scholes inversion, not a vendor's number. "
     "Realized vol, the variance risk premium, expected moves and the regime flag follow the "
     "formulas in the docs."),
    ("Present", "Every figure arrives with its percentile or regime, so a number never shows up "
     "without its context. No buy or sell signals, ever."),
]


def _pct(p: float) -> str:
    return "n/a" if p != p else f"{p:.0%}"


def preview(s: dict) -> str:
    """Hero product card, built from the live snapshot."""
    status = theme.STATUS.get(s["regime"])
    regime = theme.badge_html(s["regime"].replace("_", " ").capitalize(), status)
    bars = "".join(
        f'<div class="lp-bar"><span>{label}</span>{theme.bar_html(p, _pct(p))}</div>'
        for label, p in (
            ("VIX, 1y", s["vix_pct"]),
            ("VIX3M / VIX", s["ratio_pct"]),
            ("SPY vs 200d", s["stretch_pct"]),
        )
    )
    return f"""
<div class="lp-preview">
  <div class="lp-card-head">
    <div><div class="lp-card-title">Market state</div>
      <div class="lp-card-desc">SPY and the VIX complex</div></div>
    {theme.tag_html(f"as of {s['asof']:%b %-d}")}
  </div>
  <div class="lp-gauge">
    <div class="lp-gauge-label">Implied minus realized vol, percentile of its history</div>
    {theme.meter_html(s["vrp_pct"] * 100 if s["vrp_pct"] == s["vrp_pct"] else float("nan"),
                      (20, 40, 60, 80), "Cheap", "Typical", "Rich")}
  </div>
  <dl class="lp-mini">
    <div><dt>Regime</dt><dd>{regime}</dd></div>
    <div><dt>VIX</dt><dd>{s['vix']:.1f}</dd></div>
    <div><dt>1 SD move today</dt><dd>{s['em_day']:.2f}%</dd></div>
    <div><dt>IV minus RV</dt><dd>{s['vrp']:+.1f}</dd></div>
  </dl>
  <div class="lp-bars">{bars}</div>
</div>"""


def page() -> str:
    s = snapshot()
    stats = store_stats()
    arrow = icon(ARROW, 20)

    cards = "".join(
        f'<a class="lp-feature" href="/login?next={stem}" target="_self">'
        f'<span class="lp-icon-tile">{icon(paths)}</span>'
        f"<h3>{escape(title)}</h3><p>{escape(desc)}</p>"
        f'<span class="lp-more">Open {icon(ARROW, 16)}</span></a>'
        for stem, paths, title, desc in SOLUTIONS
    )
    steps = "".join(
        f'<div class="lp-step"><span class="lp-num">{i}</span><h3>{name}</h3><p>{escape(text)}</p></div>'
        for i, (name, text) in enumerate(STEPS, start=1)
    )
    tiles = "".join(
        f'<div class="lp-stat"><dt>{label}</dt><dd>{value}</dd><dd class="lp-stat-sub">{sub}</dd></div>'
        for label, value, sub in (
            ("Bars stored", f"{stats['bars']:,}", "daily and hourly, deduplicated"),
            ("Symbols", f"{stats['symbols']}", "index ETFs, VIX complex, T-bill rate"),
            ("Years of history", f"{stats['years']:.0f}", "daily, back to the earliest bar"),
            ("Formula sections", f"{stats['sections']}", "every metric traced to its math"),
        )
    )
    product = "".join(
        f'<li><a href="/login?next={stem}" target="_self">{escape(title)}</a></li>'
        for stem, _, title, _ in SOLUTIONS
        if stem != "docs_portal"
    )
    hero_right = preview(s) if s else ""
    chips = "".join(f'<span class="lp-chip">{c}</span>' for c in
                    ("SPY", "QQQ", "IWM", "DIA", "VIX complex", "T-bill rate"))

    return f"""
<div class="lp">
<header class="lp-header"><div class="lp-wrap lp-header-row">
  <a class="lp-logo" href="/" target="_self"><span class="lp-logo-mark">{icon(MARK, 18)}</span>
    <span>Derivative-Implied Pricing</span></a>
  <nav class="lp-nav"><a href="#solutions">Solutions</a><a href="#how">How it works</a><a href="#data">Data</a></nav>
  <div class="lp-actions">
    <a class="lp-btn lp-btn-secondary" href="/login" target="_self">Sign in</a>
    <a class="lp-btn lp-btn-primary" href="/login?mode=signup" target="_self">Get started</a>
  </div>
  <details class="lp-menu"><summary aria-label="Menu">{icon('<path d="M4 6h16M4 12h16M4 18h16"/>')}</summary>
    <div class="lp-menu-panel"><a href="#solutions">Solutions</a><a href="#how">How it works</a>
      <a href="#data">Data</a><a href="/login" target="_self">Sign in</a></div></details>
</div></header>

<section class="lp-hero"><div class="lp-wrap lp-hero-grid">
  <div>
    <span class="lp-pill"><span class="lp-dot"></span>For options and futures traders</span>
    <h1>One stop shop for live market and derivatives analysis.</h1>
    <p class="lp-lead">Built for options and futures traders looking to find value in real time.
      Chains, implied vol, expected moves and the gap to realized vol, side by side in one view.</p>
    <div class="lp-cta-row">
      <a class="lp-btn lp-btn-primary lp-btn-lg" href="/login?mode=signup" target="_self">Get started {arrow}</a>
      <a class="lp-btn lp-btn-secondary lp-btn-lg" href="#solutions">See the solutions</a>
    </div>
  </div>
  {hero_right}
</div>
<div class="lp-wrap lp-chips"><span class="lp-chips-label">Tracking</span>{chips}</div>
</section>

<section class="lp-section lp-white" id="solutions"><div class="lp-wrap">
  <div class="lp-intro"><p class="lp-eyebrow">Solutions</p>
    <h2>Every tool, one place.</h2>
    <p class="lp-lead">One store and one set of formulas under every view, so a number on one
      page agrees with the same number on another.</p></div>
  <div class="lp-features">{cards}</div>
</div></section>

<section class="lp-section" id="how"><div class="lp-wrap">
  <div class="lp-intro"><p class="lp-eyebrow">How it works</p>
    <h2>Collect, derive, present.</h2>
    <p class="lp-lead">Three layers, each small enough to check by hand.</p></div>
  <div class="lp-steps">{steps}</div>
</div></section>

<section class="lp-section lp-white" id="data"><div class="lp-wrap lp-data">
  <div class="lp-intro"><p class="lp-eyebrow">Data</p>
    <h2>History you cannot backfill, kept from day one.</h2>
    <p class="lp-lead">Implied vol history is gone if nobody stored it. These figures are read
      from the local store each time this page loads.</p></div>
  <dl class="lp-stats">{tiles}</dl>
</div></section>

<section class="lp-section"><div class="lp-wrap">
  <div class="lp-band">
    <h2>Start with the market's own numbers.</h2>
    <p>Read-only by design. It never places, changes or cancels an order.</p>
    <div class="lp-cta-row lp-center">
      <a class="lp-btn lp-btn-inverse lp-btn-lg" href="/login?mode=signup" target="_self">Get started {arrow}</a>
      <a class="lp-btn lp-btn-inverse-outline lp-btn-lg" href="/login" target="_self">Sign in</a>
    </div>
  </div>
</div></section>

<footer class="lp-footer"><div class="lp-wrap">
  <div class="lp-footer-grid">
    <div><h2>About</h2><p>One stop shop for live market and derivatives analysis, built for
      options and futures traders looking to find value in real time.</p></div>
    <div><h4>Product</h4><ul>{product}</ul></div>
    <div><h4>Resources</h4><ul><li><a href="/login?next=docs_portal" target="_self">Docs and formulas</a></li>
      <li><a href="#how">How it works</a></li><li><a href="#data">Data</a></li></ul></div>
    <div><h4>Account</h4><ul><li><a href="/login" target="_self">Sign in</a></li>
      <li><a href="/login?mode=signup" target="_self">Create account</a></li></ul></div>
  </div>
  <div class="lp-footer-bottom"><span>&copy; 2026 Derivative-Implied Pricing</span>
    <span>Not investment advice. Read-only, never trades.</span></div>
</div></footer>
</div>"""


CSS = """
<style>
header[data-testid="stHeader"] { display: none !important; }
[data-testid="stSidebar"], [data-testid="stExpandSidebarButton"] { display: none !important; }
[data-testid="stMainBlockContainer"] { max-width: none !important; padding: 0 !important; }
[data-testid="stMain"] { scroll-behavior: smooth; }
@media (prefers-reduced-motion: reduce) { [data-testid="stMain"] { scroll-behavior: auto; } }

.lp { color: var(--fg); font-family: var(--sans); }
.lp a { text-decoration: none; color: inherit; }
.lp-wrap { max-width: 1152px; margin: 0 auto; padding: 0 24px; }
@media (min-width: 1024px) { .lp-wrap { padding: 0 32px; } }
.lp h1, .lp h2 { font-family: var(--serif); font-weight: 400; letter-spacing: -0.025em;
  text-wrap: balance; color: var(--fg); margin: 0; padding: 0; }
.lp h3 { font-family: var(--sans); font-size: 1.125rem; font-weight: 600; letter-spacing: -0.025em;
  margin: 0; padding: 0; color: var(--fg); }
.lp p { margin: 0; }
.lp-lead { font-size: 1.125rem; line-height: 1.625; color: var(--fg-muted); }
.lp-eyebrow { font-size: 0.875rem; font-weight: 600; color: var(--fg-subtle); line-height: 20px; }

.lp-header { position: sticky; top: 0; z-index: 40; background: rgba(255,255,255,0.9);
  backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); border-bottom: 1px solid var(--line); }
.lp-header-row { display: flex; align-items: center; gap: 40px; height: 64px; }
.lp-logo { display: flex; align-items: center; gap: 10px; font-size: 15px; font-weight: 600;
  letter-spacing: -0.025em; }
.lp-logo-mark { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 5px;
  background: var(--fg); color: #fff; }
.lp-nav { display: flex; gap: 28px; }
.lp-nav a { font-size: 15px; color: var(--fg-muted); transition: color .15s; }
.lp-nav a:hover { color: var(--fg); }
.lp-actions { margin-left: auto; display: flex; gap: 8px; }
.lp-menu { display: none; margin-left: auto; position: relative; }
.lp-menu summary { list-style: none; display: grid; place-items: center; width: 40px; height: 40px;
  border-radius: 6px; border: 1px solid var(--line-strong); cursor: pointer; }
.lp-menu summary::-webkit-details-marker { display: none; }
.lp-menu-panel { position: absolute; right: 0; top: 48px; width: 224px; padding: 8px;
  border-radius: 8px; border: 1px solid var(--line); background: var(--surface);
  box-shadow: 0 10px 15px -3px rgba(0,0,0,0.1), 0 4px 6px -4px rgba(0,0,0,0.1); }
.lp-menu-panel a { display: block; padding: 8px 12px; border-radius: 6px; font-size: 0.875rem; }
.lp-menu-panel a:hover { background: var(--surface-raised); }
@media (max-width: 767px) { .lp-nav, .lp-actions { display: none; } .lp-menu { display: block; } }

.lp-btn { display: inline-flex; align-items: center; justify-content: center; gap: 8px;
  border-radius: 4px; font-size: 0.875rem; font-weight: 500; line-height: 20px; padding: 10px 16px;
  transition: background-color .15s; }
.lp-btn svg { transition: transform .15s; }
.lp-btn:hover svg { transform: translateX(2px); }
.lp-btn-lg { padding: 12px 20px; font-size: 1rem; }
.lp-btn-primary { background: var(--fg); color: #fff !important; }
.lp-btn-primary:hover { background: #2c2c2c; }
.lp-btn-secondary { background: var(--surface); color: var(--fg); border: 1px solid var(--line-strong); }
.lp-btn-secondary:hover { background: var(--surface-raised); }
.lp-btn-inverse { background: #fff; color: var(--fg) !important; }
.lp-btn-inverse:hover { background: rgba(255,255,255,0.9); }
.lp-btn-inverse-outline { color: #fff !important; box-shadow: inset 0 0 0 1px rgba(255,255,255,0.3); }
.lp-btn-inverse-outline:hover { background: rgba(255,255,255,0.1); }

.lp-hero { padding: 64px 0 80px; }
@media (min-width: 640px) { .lp-hero { padding-top: 96px; } }
@media (min-width: 1024px) { .lp-hero { padding-bottom: 112px; } }
.lp-hero-grid { display: grid; gap: 56px; align-items: center; }
@media (min-width: 1024px) { .lp-hero-grid { grid-template-columns: 1.05fr 1fr; } }
.lp-pill { display: inline-flex; align-items: center; gap: 8px; border-radius: 4px;
  background: var(--surface); padding: 5px 10px; font-size: 0.8125rem; color: var(--fg-muted);
  border: 1px solid var(--line); }
.lp-dot { width: 6px; height: 6px; border-radius: 9999px; background: var(--fg); }
.lp-hero h1 { margin-top: 24px; font-size: 3rem; line-height: 1.05; }
@media (min-width: 640px) { .lp-hero h1 { font-size: 3.75rem; } }
.lp-hero .lp-lead { margin-top: 24px; max-width: 34rem; }
.lp-cta-row { margin-top: 40px; display: flex; flex-wrap: wrap; gap: 12px; }
.lp-center { justify-content: center; }
.lp-chips { margin-top: 64px; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.lp-chips-label { font-size: 0.875rem; font-weight: 600; color: var(--fg-subtle); margin-right: 8px; }
.lp-chip { border-radius: 4px; background: var(--surface); padding: 5px 10px; font-size: 0.8125rem;
  color: var(--fg-muted); border: 1px solid var(--line); font-variant-numeric: tabular-nums; }

.lp-preview { border-radius: 8px; background: var(--surface); padding: 20px 22px;
  border: 1px solid var(--line); box-shadow: 0 24px 48px -28px rgba(0,0,0,0.25); }
@media (min-width: 640px) { .lp-preview { padding: 32px; } }
.lp-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.lp-card-title { font-weight: 600; letter-spacing: -0.025em; }
.lp-card-desc { margin-top: 2px; font-size: 0.875rem; color: var(--fg-subtle); }
.lp-gauge { margin-top: 18px; }
.lp-gauge-label { font-size: 12px; color: var(--fg-subtle); }
.lp-mini { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 0; margin: 14px 0 0;
  border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
.lp-mini > div { padding: 9px 12px; border-left: 1px solid var(--line); }
.lp-mini > div:first-child { border-left: none; }
.lp-mini dt { font-size: 11.5px; color: var(--fg-subtle); white-space: nowrap; }
.lp-mini dd { margin: 3px 0 0; font-size: 1.0625rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.lp-bars { margin-top: 20px; display: grid; gap: 10px; font-size: 0.875rem; }
.lp-bar { display: grid; grid-template-columns: 6.5rem 1fr; align-items: center; gap: 12px; }
.lp-bar > span:first-child { color: var(--fg-muted); }

.lp-section { padding: 96px 0; }
@media (min-width: 640px) { .lp-section { padding: 128px 0; } }
.lp-white { background: var(--surface); }
.lp-intro { max-width: 672px; }
.lp-intro h2 { margin-top: 12px; font-size: 2.25rem; line-height: 1.1; }
@media (min-width: 640px) { .lp-intro h2 { font-size: 3rem; } }
.lp-intro .lp-lead { margin-top: 24px; }

.lp-features { margin-top: 64px; display: grid; gap: 24px; }
@media (min-width: 768px) { .lp-features { grid-template-columns: repeat(2, 1fr); } }
@media (min-width: 1024px) { .lp-features { grid-template-columns: repeat(3, 1fr); } }
.lp-feature { display: flex; flex-direction: column; height: 100%; border-radius: 8px;
  background: var(--canvas); padding: 32px; transition: box-shadow .15s, background-color .15s; }
.lp-feature:hover { background: var(--surface); box-shadow: 0 2px 4px rgba(0,0,0,0.06), 0 16px 32px -12px rgba(0,0,0,0.16); }
.lp-icon-tile { display: grid; place-items: center; width: 40px; height: 40px; border-radius: 6px;
  background: var(--fg); color: #fff; }
.lp-feature h3 { margin-top: 24px; }
.lp-feature p { margin-top: 8px; line-height: 1.625; color: var(--fg-muted); }
.lp-more { margin-top: auto; padding-top: 40px; display: inline-flex; align-items: center; gap: 6px;
  font-size: 0.875rem; font-weight: 500; }
.lp-more svg { transition: transform .15s; }
.lp-feature:hover .lp-more svg { transform: translateX(2px); }

.lp-steps { margin-top: 64px; display: grid; gap: 24px; }
@media (min-width: 1024px) { .lp-steps { grid-template-columns: repeat(3, 1fr); } }
.lp-step { border-radius: 8px; background: var(--surface); padding: 28px; border: 1px solid var(--line); }
.lp-num { display: grid; place-items: center; width: 32px; height: 32px; border-radius: 4px;
  background: var(--fg); color: #fff; font-size: 0.875rem; font-weight: 600; }
.lp-step h3 { margin-top: 28px; font-family: var(--serif); font-weight: 400; font-size: 1.5rem;
  letter-spacing: -0.025em; }
.lp-step p { margin-top: 12px; line-height: 1.625; color: var(--fg-muted); }

.lp-data { display: grid; gap: 64px; }
@media (min-width: 1024px) { .lp-data { grid-template-columns: 1fr 1fr; align-items: center; } }
.lp-stats { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin: 0; }
.lp-stat { border-radius: 6px; background: var(--canvas); padding: 18px 20px; border: 1px solid var(--line); }
.lp-stat dt { font-size: 0.875rem; color: var(--fg-subtle); }
.lp-stat dd { margin: 8px 0 0; font-family: var(--serif); font-size: 2.25rem; line-height: 1;
  font-variant-numeric: tabular-nums; }
.lp-stat dd.lp-stat-sub { font-family: var(--sans); font-size: 0.75rem; line-height: 1.4;
  color: var(--fg-muted); }

.lp-band { border-radius: 12px; background: var(--fg); color: #fff; padding: 64px 32px;
  text-align: center; }
@media (min-width: 640px) { .lp-band { padding: 80px 64px; } }
.lp-band h2 { color: #fff; font-size: 2.25rem; line-height: 1.1; max-width: 48rem; margin: 0 auto; }
@media (min-width: 640px) { .lp-band h2 { font-size: 3rem; } }
.lp-band p { margin: 24px auto 0; max-width: 36rem; font-size: 1.125rem; line-height: 1.625;
  color: rgba(255,255,255,0.7); }
.lp-band :focus-visible, .lp-footer :focus-visible { outline-color: #fff; }

.lp-footer { background: var(--fg); color: #fff; }
.lp-footer-grid { display: grid; gap: 56px; padding: 80px 0 48px; }
@media (min-width: 1024px) { .lp-footer-grid { grid-template-columns: 1.6fr 1fr 1fr 1fr; } }
.lp-footer h2 { color: #fff; font-size: 1.875rem; }
.lp-footer-grid p { margin-top: 16px; max-width: 28rem; line-height: 1.625; color: rgba(255,255,255,0.65); }
.lp-footer h4 { margin: 0; font-family: var(--sans); font-size: 0.875rem; font-weight: 600; color: #fff; }
.lp-footer ul { list-style: none; margin: 16px 0 0; padding: 0; display: grid; gap: 12px; }
.lp-footer li { margin: 0; padding: 0 !important; }
.lp-footer ul a { font-size: 15px; color: rgba(255,255,255,0.65); transition: color .15s; }
.lp-footer ul a:hover { color: #fff; }
.lp-footer-bottom { display: flex; flex-direction: column; gap: 16px; padding: 24px 0 48px;
  font-size: 0.875rem; color: rgba(255,255,255,0.55); border-top: 1px solid rgba(255,255,255,0.12); }
@media (min-width: 768px) { .lp-footer-bottom { flex-direction: row; justify-content: space-between; } }
</style>
"""

def flat(html: str) -> str:
    """One unindented HTML block: markdown would read a blank line plus indentation as code."""
    return "\n".join(line.strip() for line in html.splitlines() if line.strip())


st.markdown(CSS, unsafe_allow_html=True)
st.markdown(flat(page()), unsafe_allow_html=True)
