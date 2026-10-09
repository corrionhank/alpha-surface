"""Smoke test for the options chain page on the synthetic provider: it renders, it defaults to the
at-the-money call, and selecting a put cell switches the contract panel to that put."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from alphasurface.config import REPO_ROOT

PAGE = str(REPO_ROOT / "src" / "alphasurface" / "present" / "option_chain.py")


def _title(at, text: str) -> bool:
    """Panel titles render through theme.panel_head as markdown, not st.subheader."""
    return any(f'panel-title">{text}<' in m.value for m in at.markdown)


def test_chain_page_renders_and_follows_the_selected_cell():
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.run()
    assert not at.exception
    expiry = next(sb.value for sb in at.selectbox if sb.label == "Expiry")
    assert _title(at, f"SPY 750 call, {expiry}")  # synthetic spot is 750

    strikes = at.dataframe[0].value["strike"].astype(float).tolist()
    key = f"chain-synthetic-SPY-{expiry}-20"
    at.session_state[key] = {
        "selection": {"rows": [], "columns": [], "cells": [(strikes.index(780.0), "put_mark")]}
    }
    at.run()
    assert not at.exception
    assert _title(at, f"SPY 780 put, {expiry}")
    assert _title(at, "Cash-secured put")

    # A different strike count rebuilds the board; the pick is kept by strike, not by row.
    at.segmented_control(key="chain_strikes").set_value("40").run()
    assert not at.exception
    assert _title(at, f"SPY 780 put, {expiry}")


def test_strikes_control_and_full_screen():
    at = AppTest.from_file(PAGE, default_timeout=60)
    at.run()
    rows = len(at.dataframe[0].value)
    assert rows == 41  # 20 strikes each side of the money, plus the money
    at.segmented_control(key="chain_strikes").set_value("10").run()
    assert len(at.dataframe[0].value) == 21
    at.segmented_control(key="chain_strikes").set_value("All").run()
    assert len(at.dataframe[0].value) > rows
    next(b for b in at.button if b.label == "Full screen").click().run()
    assert not at.exception and at.session_state["chain_full"]
    next(b for b in at.button if b.label == "Exit full screen").click().run()
    assert not at.session_state["chain_full"]
