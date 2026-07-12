"""Massive-style CSS polish for the app. Base palette is in .streamlit/config.toml."""

from __future__ import annotations

import streamlit as st

# Keep in sync with .streamlit/config.toml.
BLUE = "#2C5CF6"
INK = "#0F172A"
GRAY = "#4B5563"
MUTED = "#6B7280"
BORDER = "#E5E7EB"
SURFACE = "#FFFFFF"
PANEL = "#F7F8FA"

_CSS = f"""
<style>
:root {{
  --mv-blue: {BLUE}; --mv-ink: {INK}; --mv-gray: {GRAY};
  --mv-muted: {MUTED}; --mv-border: {BORDER}; --mv-panel: {PANEL};
}}

/* Hide only the clutter, keep the header so it can act as a navbar. */
[data-testid="stAppDeployButton"], [data-testid="stMainMenu"],
[data-testid="stStatusWidget"], [data-testid="stDecoration"] {{ display: none !important; }}
header[data-testid="stHeader"] {{ background: {SURFACE}; border-bottom: 1px solid var(--mv-border); }}

/* Keep the collapsed-sidebar reopen control visible so the sidebar is never lost. */
[data-testid="stExpandSidebarButton"] {{
  display: inline-flex !important; visibility: visible !important; opacity: 1 !important;
}}

/* Top navbar links */
[data-testid="stTopNavLink"] {{ font-weight: 600; color: var(--mv-gray) !important; }}
[data-testid="stTopNavLink"]:hover {{ color: var(--mv-ink) !important; }}
[data-testid="stTopNavLink"][aria-current="page"] {{ color: var(--mv-blue) !important; font-weight: 700; }}

html, body, [class*="css"], .stApp {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, Helvetica, sans-serif;
}}
h1, h2, h3 {{ color: var(--mv-ink) !important; font-weight: 800 !important; letter-spacing: -0.025em !important; }}
h1 {{ font-size: 2.4rem !important; }}
[data-testid="stMarkdownContainer"] p {{ color: var(--mv-gray); }}

[data-testid="stMetric"] {{
  background: {SURFACE};
  border: 1px solid var(--mv-border);
  border-radius: 14px;
  padding: 14px 18px;
}}
[data-testid="stMetricValue"] {{ color: var(--mv-ink); font-weight: 800; letter-spacing: -0.02em; }}
[data-testid="stMetricLabel"] {{ color: var(--mv-muted); font-weight: 600; }}

[data-testid="stSidebar"] {{ border-right: 1px solid var(--mv-border); }}

.stButton > button, [data-testid="stBaseButton-secondary"] {{
  border-radius: 8px; border: 1px solid var(--mv-border); font-weight: 600;
}}
[data-testid="stBaseButton-primary"] {{
  background: var(--mv-blue); border-color: var(--mv-blue); color: #fff; font-weight: 700;
}}

a, a:visited {{ color: var(--mv-blue) !important; }}
[data-testid="stCaptionContainer"] {{ color: var(--mv-muted) !important; }}
</style>
"""


def apply() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
