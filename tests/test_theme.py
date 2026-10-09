"""The theme colors are declared twice: in .streamlit/config.toml (what Streamlit paints) and in
theme.STREAMLIT (what the CSS and charts assume). These tests stop the two from drifting apart."""

from __future__ import annotations

import tomllib

from alphasurface.config import REPO_ROOT
from alphasurface.derive.market_state import REGIMES
from alphasurface.present import theme

CONFIG = tomllib.loads((REPO_ROOT / ".streamlit" / "config.toml").read_text())["theme"]


def test_config_toml_matches_theme():
    assert {k: CONFIG[k] for k in theme.STREAMLIT} == theme.STREAMLIT


def test_light_only():
    assert CONFIG["base"] == "light"


def test_every_regime_has_a_status():
    assert set(theme.STATUS) == set(REGIMES)
    assert all(s in (None, "good", "warn", "risk") for s in theme.STATUS.values())


def test_status_color_falls_back_to_ink():
    assert theme.status_color("normal") == theme.TOKENS["fg"]
    assert theme.status_color("stress") == theme.TOKENS["risk"]


def test_chart_colors_match_what_the_chart_reads():
    # charts.tradingview_html indexes exactly these keys; a mismatch is a KeyError at render.
    assert theme.chart_colors().keys() == {"text", "grid", "axis"}
