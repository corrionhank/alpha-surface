"""Smoke test for the scanner page on the synthetic provider: nothing is fetched until the
button, a scan renders hits, and the options-or-underlying tab renders. No network, no writes."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from alphasurface.config import REPO_ROOT

PAGE = str(REPO_ROOT / "src" / "alphasurface" / "present" / "scanner.py")


def test_scanner_page_runs_a_synthetic_scan():
    at = AppTest.from_file(PAGE, default_timeout=90)
    at.run()
    assert not at.exception
    assert any(i.value.startswith("Ready to scan") for i in at.info)

    at.selectbox(key="scan_source").set_value("synthetic")
    at.text_area[0].set_value("SPY, QQQ")
    at.selectbox(key="preset").set_value("rich").run()
    at.button(key="run_scan").click().run()
    assert not at.exception
    assert any('panel-title">Rich premium' in m.value for m in at.markdown)
    assert any('panel-title">Side by side<' in m.value for m in at.markdown)
