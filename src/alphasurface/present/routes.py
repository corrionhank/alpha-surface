"""App pages as (file stem, nav title). The entrypoint builds the navigation from this list and
the sign-in page uses it to send you on to the page a link asked for."""

from __future__ import annotations

APP = [
    ("overview", "Dashboard"),
    ("option_chain", "Options"),
    ("scanner", "Screener"),
    ("chart", "Charts"),
    ("research", "Research"),
    ("vol_surface", "Volatility"),
    ("docs_portal", "Docs"),
]
DEFAULT = "overview"
STEMS = {stem for stem, _ in APP}


def page(stem: str) -> str:
    """A page script's path as st.Page and st.switch_page take it: relative to the entry script,
    alphasurface/app.py."""
    return f"present/{stem}.py"
