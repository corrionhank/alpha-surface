"""Smoke test for the options chain page on the synthetic provider: it renders, it defaults to the
at-the-money call, and selecting a put cell switches the contract panel to that put."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from config import REPO_ROOT

PAGE = str(REPO_ROOT / "src" / "present" / "option_chain.py")



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
    key = f"chain-synthetic-SPY-{expiry}-0.85-1.15"
    at.session_state[key] = {
        "selection": {"rows": [], "columns": [], "cells": [(strikes.index(780.0), "put_mark")]}
    }
    at.run()
    assert not at.exception
    assert _title(at, f"SPY 780 put, {expiry}")
    assert _title(at, "Cash-secured put")
