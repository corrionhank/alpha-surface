"""Smoke test for the Volatility page on the sample chain: it renders every panel, its controls
work, and a failed chain pull shows its error in the vol grid panel without taking the page down."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from alphasurface.collector import feed
from alphasurface.config import REPO_ROOT

PAGE = str(REPO_ROOT / "src" / "alphasurface" / "present" / "vol_surface.py")


def _html(at) -> str:
    return "".join(m.value for m in at.markdown)


def test_page_renders_and_its_controls_work():
    at = AppTest.from_file(PAGE, default_timeout=90)
    at.run()
    assert not at.exception
    page = _html(at)
    assert "ATM IV, 30D" in page and "Risk reversal, 25Δ 30D" in page
    assert page.count("<tr>") > 5  # the vol grid has a row per expiry
    assert len(at.get("plotly_chart")) == 3  # surface, smile, term structure

    at.segmented_control(key="vs_view").set_value("3D").run()
    assert not at.exception
    at.segmented_control(key="vs_axis").set_value("Strike").run()
    assert not at.exception
    at.segmented_control(key="vs_horizon").set_value("1M").run()
    assert not at.exception and len(at.get("plotly_chart")) == 3


def test_a_failed_pull_fails_its_panel_only(monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("feed down")

    monkeypatch.setattr(feed, "expirations", boom)
    at = AppTest.from_file(PAGE, default_timeout=90)
    at.run()
    at.text_input(key="vs_symbol").set_value("ZZZQ").run()  # a symbol no cached pull covers
    assert not at.exception
    assert any("feed down" in e.value for e in at.error)
    assert "No smile to draw." in _html(at)
