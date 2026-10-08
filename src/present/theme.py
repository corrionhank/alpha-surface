"""Theme: light monochrome, from .claude/STYLE_GUIDE.md (2026-10-07 dashboard revision).

Black on warm off-white. Newsreader serif for page titles only; Inter for everything else,
figures in tabular digits. Panels are hairline-bordered, not floating cards. Color only ever means status (good / warn / risk) and always sits next to a word or a
number. Streamlit's own theme config (.streamlit/config.toml) carries the colors and fonts so
widgets, dataframes and charts follow them; the CSS below covers what config cannot reach.
STREAMLIT must match the [theme] block there; tests/test_theme.py enforces that.
"""

from __future__ import annotations

from html import escape

import streamlit as st

TOKENS = {
    "canvas": "#f7f7f6",  # page background
    "surface": "#ffffff",  # cards, inputs, header
    "surface_raised": "#f1f1ef",  # hover fills, control tracks, neutral badges
    "line": "#e4e4e1",  # hairlines
    "line_strong": "#cfcfcb",  # input and secondary-button borders
    "fg": "#111111",  # text, chart ink, primary buttons
    "fg_muted": "#4a4a4a",  # body copy
    "fg_subtle": "#686868",  # captions, labels, axis text
    "ink_2": "#8a8a86",  # second series when two must be told apart
    "good": "#1d7a3e",
    "warn": "#8f5b00",
    "risk": "#b42318",
}
T = TOKENS

# The [theme] colors in .streamlit/config.toml, as this module expects them.
STREAMLIT = {
    "primaryColor": T["fg"],
    "backgroundColor": T["canvas"],
    "secondaryBackgroundColor": T["surface_raised"],
    "textColor": T["fg"],
    "linkColor": T["fg"],
    "borderColor": T["line_strong"],
    "dataframeBorderColor": T["line"],
    "dataframeHeaderBackgroundColor": T["surface_raised"],
    "codeBackgroundColor": T["surface_raised"],
    "codeTextColor": T["fg_muted"],
    "greenColor": T["good"],
    "orangeColor": T["warn"],
    "redColor": T["risk"],
}

# Regime flag to status. Normal is the absence of a status, so it stays ink.
STATUS = {"low_vol": "good", "normal": None, "elevated": "warn", "stress": "risk"}

SERIF = '"Newsreader", ui-serif, Georgia, serif'
SANS = '"Inter", ui-sans-serif, system-ui, sans-serif'
MONO = '"IBM Plex Mono", ui-monospace, "SFMono-Regular", monospace'

CONTENT_WIDTH = "none"  # the grid uses the whole screen; panels and the rail organize it
HEADER = "3.75rem"  # Streamlit's fixed header
BAR = "42px"  # the sticky market bar under it


def status_color(flag: str) -> str:
    status = STATUS.get(flag)
    return T[status] if status else T["fg"]


def polarity() -> tuple[str, str]:
    """Text colors for signed values: positive deltas good, negative risk."""
    return T["good"], T["risk"]


def chart_colors() -> dict[str, str]:
    """Colors for the Lightweight Charts iframe, which cannot read the page's CSS."""
    return {"text": T["fg_subtle"], "grid": "rgba(17,17,17,0.06)", "axis": T["line"]}


def intro(title: str, eyebrow: str | None = None, lead: str | None = None,
          tag: str | None = None) -> None:
    """Page title block: eyebrow and tag on one line, serif title, one muted lead line."""
    parts = ['<div class="intro">']
    if eyebrow or tag:
        parts.append('<div class="intro-top">')
        if eyebrow:
            parts.append(f'<p class="eyebrow">{escape(eyebrow)}</p>')
        if tag:
            parts.append(tag_html(tag))
        parts.append("</div>")
    parts.append(f"<h1>{escape(title)}</h1>")
    if lead:
        parts.append(f'<p class="lead">{escape(lead)}</p>')
    parts.append("</div>")
    st.markdown("".join(parts), unsafe_allow_html=True)


def icon(paths: str, size: int = 20) -> str:
    """Line icon on a 24px grid, 1.6 stroke, never filled, inheriting the text color."""
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" '
        f'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
        f"{paths}</svg>"
    )


# The logo mark (price line opening into the 1 SD cone) and the call-to-action arrow.
MARK = '<path d="M5 12h5"/><path d="M10 12c3 0 5-3 9-6"/><path d="M10 12c3 0 5 3 9 6"/>'
ARROW = '<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>'


def card(name: str):
    """A bordered panel: `with theme.card("cone"): ...`. Streamlit puts the key on the container
    as a CSS class, which is how the panel style finds it."""
    return st.container(key=f"card-{name}")


def panel_head(title: str, meta: str = "") -> None:
    """Panel header row: title left, source or as-of (any HTML) right, hairline under both."""
    st.markdown(f'<div class="panel-head"><span class="panel-title">{escape(title)}</span>'
                f'<span class="panel-meta">{meta}</span></div>', unsafe_allow_html=True)


def meter_html(value: float, edges: tuple[float, ...] = (25, 45, 55, 75), left: str = "",
               mid: str = "", right: str = "") -> str:
    """A 0 to 100 linear meter: a track split at edges, an ink marker at value with the number
    above it, and up to three anchor names under it. Replaces the ring gauge: a line reads
    faster, fits any width and needs no SVG."""
    v = 0.0 if value != value else max(0.0, min(float(value), 100.0))
    bounds = [0.0, *edges, 100.0]
    segs = "".join(f'<span style="width:{b - a:.2f}%"></span>' for a, b in zip(bounds, bounds[1:]))
    names = "".join(f'<span class="{cls}">{escape(t)}</span>'
                    for cls, t in (("l", left), ("m", mid), ("r", right)) if t)
    return (
        f'<div class="meter"><div class="meter-track">{segs}'
        f'<i class="meter-mark" style="left:{v:.2f}%"><b>{v:.0f}</b></i></div>'
        f'<div class="meter-names">{names}</div></div>'
    )


def bar_html(fraction: float, label: str) -> str:
    """Bar-list cell: ink fill on a hairline track, value to the right. fraction is 0 to 1."""
    width = 0.0 if fraction != fraction else max(0.0, min(fraction, 1.0))  # NaN draws empty
    return (
        f'<span class="bar"><span class="track"><span class="fill" style="width:{width:.0%}">'
        f'</span></span><span class="num">{escape(label)}</span></span>'
    )


def asof(source: str, ts=None) -> str:
    """Plain panel meta: 'tastytrade, Oct 8 7:29 PM ET'. No tag, no capitals."""
    import pandas as pd

    if ts is None or (isinstance(ts, float) and ts != ts):
        return escape(source)
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        return escape(f"{source}, {t:%b %-d}")
    t = t.tz_convert("America/New_York")
    return escape(f"{source}, {t:%b %-d %-I:%M %p} ET")


def cell_bar(fraction: float, label: str) -> str:
    """Inline bar for a table cell: a 64px track, ink fill, the value beside it."""
    w = 0.0 if fraction != fraction else max(0.0, min(fraction, 1.0))
    return f'<span class="cell-bar"><i><b style="width:{w:.0%}"></b></i>{escape(label)}</span>'


def tag_html(text: str) -> str:
    """Tiny uppercase mono tag, e.g. SAMPLE DATA. The only all-caps text in the system."""
    return f'<span class="mono-tag">{escape(text)}</span>'


def badge_html(text: str, status: str | None) -> str:
    """Status badge: status color on a 10% tint of itself, or neutral when status is None."""
    cls = f"badge badge-{status}" if status else "badge"
    return f'<span class="{cls}">{escape(text)}</span>'


def _css() -> str:
    return f"""
<style>
:root {{
  --canvas: {T["canvas"]}; --surface: {T["surface"]}; --surface-raised: {T["surface_raised"]};
  --line: {T["line"]}; --line-strong: {T["line_strong"]};
  --fg: {T["fg"]}; --fg-muted: {T["fg_muted"]}; --fg-subtle: {T["fg_subtle"]};
  --good: {T["good"]}; --warn: {T["warn"]}; --risk: {T["risk"]};
  --r-sm: 4px; --r-md: 6px; --r-lg: 8px;
  --shadow-pop: 0 8px 24px -8px rgba(0,0,0,0.18);
  --serif: {SERIF}; --sans: {SANS}; --mono: {MONO};
  --header: {HEADER}; --bar: {BAR};
}}

/* A markdown element holding only a <style> still takes a slot and a gap in the layout. Hide
   the slot; the style applies regardless. */
[data-testid="stElementContainer"]:has([data-testid="stMarkdownContainer"] > style:only-child) {{
  display: none;
}}

/* Chrome: hide Streamlit's own, keep the header as the navbar. */
[data-testid="stAppDeployButton"], [data-testid="stMainMenu"],
[data-testid="stStatusWidget"], [data-testid="stDecoration"] {{ display: none !important; }}
header[data-testid="stHeader"] {{ background: var(--surface); border-bottom: 1px solid var(--line); }}
[data-testid="stExpandSidebarButton"] {{
  display: inline-flex !important; visibility: visible !important; opacity: 1 !important;
}}
/* Nav: quiet links, the current page marked by an ink underline rather than a filled pill. */
[data-testid="stTopNavLink"] {{
  color: var(--fg-muted) !important; font-size: 14px; font-weight: 500;
  padding: 6px 10px; border-radius: 0; background: transparent !important;
  transition: color .15s;
}}
[data-testid="stTopNavLink"]:hover {{ color: var(--fg) !important; }}
[data-testid="stTopNavLink"][aria-current="page"] {{
  color: var(--fg) !important; box-shadow: inset 0 -2px 0 var(--fg);
}}

/* Page: full-width grid with fixed gutters; the market bar sits flush under the header. */
:root {{ --gutter: 1.25rem; }}
@media (min-width: 1024px) {{ :root {{ --gutter: 2rem; }} }}
[data-testid="stMainBlockContainer"] {{
  max-width: {CONTENT_WIDTH}; margin: 0 auto; padding: var(--header) var(--gutter) 4rem;
}}

[data-testid="stMain"] [data-testid="stVerticalBlock"] {{ gap: 0.75rem; }}
/* Streamlit pulls every markdown block up 16px to cancel a paragraph margin it no longer sets,
   so the next element overlapped the last line of HTML (hairlines through text). Undo it. */
[data-testid="stMarkdownContainer"] {{ margin-bottom: 0 !important; }}
[data-testid="stMarkdownContainer"] p {{ margin: 0 0 0.6rem; }}
[data-testid="stMarkdownContainer"] p:last-child {{ margin-bottom: 0; }}

/* Market bar: sticky strip under the nav with the tape, market status and the account menu. */
/* The wrapper Streamlit puts around a keyed container is the flex child, so it carries the
   sticky position and the bleed into the page gutters. */
[data-testid="stLayoutWrapper"]:has(> .st-key-marketbar) {{
  position: sticky; top: var(--header); z-index: 50;
  margin: 0 calc(-1 * var(--gutter)) 0.25rem !important;
  width: calc(100% + 2 * var(--gutter)) !important; max-width: none !important;
}}
.st-key-marketbar {{
  min-height: var(--bar); width: 100%; padding: 0 var(--gutter); background: var(--surface);
  border-bottom: 1px solid var(--line); justify-content: center;
}}
.st-key-marketbar [data-testid="stHorizontalBlock"] {{ align-items: center; gap: 1rem; }}
.st-key-marketbar button {{
  border: none !important; background: transparent !important; box-shadow: none !important;
  color: var(--fg-muted) !important; font-size: 13px; min-height: 30px; padding: 0 6px;
}}
.st-key-marketbar button:hover {{ color: var(--fg) !important; }}
.tape {{
  display: flex; align-items: center; overflow-x: auto; scrollbar-width: none;
  font-size: 13px; font-variant-numeric: tabular-nums; white-space: nowrap;
}}
.tape .tk {{ padding: 0 14px; border-left: 1px solid var(--line); color: var(--fg-muted); }}
.tape .tk:first-child {{ padding-left: 0; border-left: none; }}
.tape .tk b {{ color: var(--fg); font-weight: 600; margin-right: 6px; }}
.mkt {{ display: flex; align-items: center; justify-content: flex-end; gap: 12px;
  font-size: 12px; color: var(--fg-subtle); white-space: nowrap; }}
.mkt .dot {{ display: inline-block; width: 7px; height: 7px; border-radius: 50%;
  background: var(--line-strong); margin-right: 6px; vertical-align: 1px; }}
.mkt .dot.open {{ background: var(--good); }}
.mkt .state {{ color: var(--fg-muted); font-weight: 500; }}

/* Type: serif for the page title only; every other heading is Inter, tight and semibold. */
[data-testid="stMain"] h1 {{
  font-family: var(--serif); font-weight: 400; letter-spacing: -0.02em; color: var(--fg);
}}
[data-testid="stMain"] :is(h2, h3, h4):not(.lp *) {{
  font-family: var(--sans) !important; font-weight: 600 !important; letter-spacing: -0.01em;
  color: var(--fg); padding: 0.25rem 0 0; font-size: 1rem !important; line-height: 1.4;
}}
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{
  font-family: var(--sans) !important; font-size: 0.75rem !important; font-weight: 600 !important;
  letter-spacing: 0.02em; color: var(--fg-subtle); padding: 1rem 0 0.25rem;
}}
[data-testid="stHeadingWithActionElements"] a, [data-testid="stHeaderActionElements"] {{ display: none; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{
  color: var(--fg-subtle) !important; font-size: 12px !important; line-height: 1.5 !important;
}}
[data-testid="stMain"] p, [data-testid="stMain"] li {{ line-height: 1.55; }}
[data-testid="stDataFrame"], .tabular {{ font-variant-numeric: tabular-nums; }}

/* Page title block. */
.intro {{ max-width: 860px; margin: 0.75rem 0 0.25rem; }}
.intro-top {{ display: flex; align-items: center; gap: 10px; }}
.intro .eyebrow {{ margin: 0; font-size: 12px; font-weight: 600; color: var(--fg-subtle); }}
.intro h1 {{ margin: 4px 0 0; padding: 0; font-size: 1.75rem; line-height: 1.15; }}
.intro .lead {{ margin: 6px 0 0; font-size: 0.875rem; color: var(--fg-muted); }}

/* Panels: white, hairline border, small radius, no shadow. Content packs tighter inside. */
[data-testid="stMain"] [class*="st-key-card-"] {{
  background: var(--surface); border: 1px solid var(--line) !important;
  border-radius: var(--r-lg); box-shadow: none; padding: 12px 16px 14px; gap: 0.5rem;
}}
.panel-head {{
  display: flex; align-items: baseline; justify-content: space-between; gap: 16px;
  padding: 2px 0 9px; border-bottom: 1px solid var(--line); margin-bottom: 6px;
}}
.panel-title {{ font-size: 0.9375rem; font-weight: 600; letter-spacing: -0.01em; color: var(--fg); }}
.panel-rule {{ border-bottom: 1px solid var(--line); margin: -2px 0 2px; }}
.panel-meta {{ display: flex; align-items: center; gap: 14px; font-size: 12px; color: var(--fg-subtle);
  font-variant-numeric: tabular-nums; white-space: nowrap; }}
.panel-meta b {{ color: var(--fg); font-weight: 600; }}
.panel-meta .up {{ color: var(--good); }}
.panel-meta .down {{ color: var(--risk); }}

/* Numbers: a row of st.metric in columns becomes one stat strip, a bordered panel with
   hairline dividers, instead of a floating box per number. */
[data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] > [data-testid="stVerticalBlock"]
  > [data-testid="stElementContainer"] > [data-testid="stMetric"]) {{
  gap: 0 !important; background: var(--surface); border: 1px solid var(--line);
  border-radius: var(--r-lg); overflow: hidden;
}}
[data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] > [data-testid="stVerticalBlock"]
  > [data-testid="stElementContainer"] > [data-testid="stMetric"]) > [data-testid="stColumn"]
  + [data-testid="stColumn"] {{ border-left: 1px solid var(--line); }}
[data-testid="stMetric"] {{
  background: transparent; border: none; border-radius: 0; box-shadow: none; padding: 10px 14px;
}}
[data-testid="stMetricLabel"], [data-testid="stMetricLabel"] p {{
  color: var(--fg-subtle); font-size: 12px !important; font-weight: 400;
}}
[data-testid="stMetricValue"], [data-testid="stMetricValue"] div {{
  font-family: var(--sans) !important; font-weight: 600 !important; font-size: 1.375rem !important;
  line-height: 1.2; letter-spacing: -0.01em; font-variant-numeric: tabular-nums;
}}
[data-testid="stMetricDelta"] {{ font-size: 12px; }}

/* Bar list: label, numbers, then a percentile bar. Hairlines between rows only. */
.bar-table {{ font-size: 13px; font-variant-numeric: tabular-nums; }}
.bar-row {{
  display: grid; grid-template-columns: 5.25rem 3.5rem minmax(0, 1fr) 2.25rem;
  align-items: center; gap: 10px; padding: 6px 0; border-top: 1px solid var(--line);
}}
.bar-head {{ border-top: none; padding-top: 0; font-size: 11px; color: var(--fg-subtle); }}
.bar-head span {{ text-align: right; white-space: nowrap; }}
.bar-head .left {{ text-align: left; }}
.bar-row .num small {{ display: block; font-size: 11px; color: var(--fg-subtle); }}
.bar-row .name {{ color: var(--fg-muted); }}
.bar-row .num, .bar .num {{ text-align: right; color: var(--fg); }}
.bar {{ display: grid; grid-template-columns: minmax(0, 1fr) 3rem; align-items: center; gap: 8px; }}
.bar .num {{ white-space: nowrap; }}
.bar .track {{ height: 4px; border-radius: 2px; background: var(--surface-raised); overflow: hidden; }}
.bar .fill {{ display: block; height: 100%; border-radius: 2px; background: var(--fg); }}

/* Data table: compact rows, hairlines, numbers right-aligned in tabular digits. */
.dtable {{ width: 100%; border-collapse: collapse; font-size: 13px; font-variant-numeric: tabular-nums; }}
.dtable th {{ font-size: 11.5px; font-weight: 500; color: var(--fg-subtle); text-align: right;
  padding: 0 10px 6px; border-bottom: 1px solid var(--line); white-space: nowrap; }}
.dtable td {{ padding: 7px 10px; border-bottom: 1px solid var(--line); text-align: right;
  white-space: nowrap; color: var(--fg); }}
.dtable tr:last-child td {{ border-bottom: none; }}
.dtable th:first-child, .dtable td:first-child {{ text-align: left; padding-left: 0; }}
.dtable td:first-child {{ font-weight: 600; }}
.dtable th:last-child, .dtable td:last-child {{ padding-right: 0; }}
.dtable .l {{ text-align: left; }}
.dtable .sub {{ color: var(--fg-subtle); }}
.dtable .up {{ color: var(--good); }}
.dtable .down {{ color: var(--risk); }}
.dtable .cell-bar {{ display: inline-flex; align-items: center; gap: 8px; justify-content: flex-end; }}
.dtable .cell-bar i {{ display: inline-block; width: 96px; height: 4px; border-radius: 2px;
  background: var(--surface-raised); position: relative; overflow: hidden; }}
.dtable .cell-bar i b {{ position: absolute; left: 0; top: 0; bottom: 0; background: var(--fg); }}

/* Meter: banded 0 to 100 track with an ink marker. */
.meter {{ padding: 20px 0 0; margin-bottom: 12px; }}
.meter-track {{ position: relative; display: flex; gap: 2px; height: 6px; }}
.meter-track span {{ display: block; height: 100%; background: var(--line); }}
.meter-track span:first-child {{ border-radius: 2px 0 0 2px; }}
.meter-track span:last-child {{ border-radius: 0 2px 2px 0; }}
.meter-mark {{ position: absolute; top: -5px; width: 2px; height: 16px; margin-left: -1px;
  background: var(--fg); }}
.meter-mark b {{ position: absolute; bottom: 18px; left: 50%; transform: translateX(-50%);
  font-style: normal; font-size: 12px; font-weight: 600; color: var(--fg); white-space: nowrap;
  font-variant-numeric: tabular-nums; }}
.meter-names {{ position: relative; height: 16px; margin-top: 6px; font-size: 10.5px;
  color: var(--fg-subtle); }}
.meter-names span {{ position: absolute; white-space: nowrap; }}
.meter-names .l {{ left: 0; }}
.meter-names .m {{ left: 50%; transform: translateX(-50%); }}
.meter-names .r {{ right: 0; }}

.mono-tag {{
  display: inline-block; border-radius: 3px; background: var(--surface-raised);
  padding: 2px 7px; font-family: var(--sans); font-size: 11.5px; font-weight: 500; line-height: 1.4;
  color: var(--fg-muted); white-space: nowrap;
}}
.badge {{
  display: inline-block; white-space: nowrap; border-radius: 3px; padding: 1px 6px;
  font-size: 12px; font-weight: 500; background: var(--surface-raised); color: var(--fg-muted);
}}
.badge-good {{ background: rgba(29,122,62,0.10); color: var(--good); }}
.badge-warn {{ background: rgba(143,91,0,0.10); color: var(--warn); }}
.badge-risk {{ background: rgba(180,35,24,0.10); color: var(--risk); }}

/* Controls: white inputs with a gray edge, square-ish corners. */
[data-testid="stMain"] [data-baseweb="input"], [data-testid="stMain"] [data-baseweb="select"] > div,
[data-testid="stSidebar"] [data-baseweb="input"], [data-testid="stSidebar"] [data-baseweb="select"] > div {{
  background: var(--surface);
}}
[data-baseweb="input"] input, [data-baseweb="base-input"] {{ background: transparent !important; }}
[data-testid="stBaseButton-secondary"] {{
  background: var(--surface); border-color: var(--line-strong); color: var(--fg);
  transition: background-color .15s;
}}
[data-testid="stBaseButton-secondary"]:hover {{
  background: var(--surface-raised); border-color: var(--line-strong); color: var(--fg);
}}
/* Segmented control: a raised track, the active option lifted onto white. */
div:has(> [data-testid^="stBaseButton-segmented_control"]) {{
  background: var(--surface-raised); border-radius: var(--r-md); padding: 3px; gap: 2px;
}}
[data-testid^="stBaseButton-segmented_control"] {{
  border: none !important; border-radius: var(--r-sm) !important; background: transparent;
  color: var(--fg-muted); font-weight: 500; box-shadow: none; min-height: 30px;
  transition: color .15s, background-color .15s;
}}
[data-testid="stBaseButton-segmented_control"]:hover {{ color: var(--fg); background: transparent; }}
[data-testid="stBaseButton-segmented_controlActive"],
[data-testid="stBaseButton-segmented_controlActive"]:hover {{
  background: var(--surface); color: var(--fg); box-shadow: 0 1px 2px rgba(0,0,0,0.08);
}}
/* Tabs: underline style, matching the nav. */
[data-testid="stTabs"] [data-baseweb="tab-list"] {{ gap: 18px; border-bottom: 1px solid var(--line); }}
[data-testid="stTabs"] [data-baseweb="tab"] {{ padding: 6px 0; font-size: 14px; }}

[data-testid="stExpander"] details {{
  background: var(--surface); border: 1px solid var(--line); border-radius: var(--r-lg);
}}
[data-testid="stAlertContainer"] {{ border-radius: var(--r-md); }}
[data-testid="stPopoverBody"] {{ border-radius: var(--r-md); box-shadow: var(--shadow-pop); }}

:focus-visible {{ outline: 2px solid var(--fg); outline-offset: 2px; }}
@media (prefers-reduced-motion: reduce) {{ * {{ transition: none !important; }} }}
hr {{ border-color: var(--line); }}
.katex {{ color: var(--fg); }}
</style>
"""


def apply() -> None:
    st.markdown(_css(), unsafe_allow_html=True)
