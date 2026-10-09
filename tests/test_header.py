"""The market bar renders offline: the tape from the store, the status, and both menus."""

from __future__ import annotations

from streamlit.testing.v1 import AppTest


def _bar():
    import streamlit as st

    from alphasurface.present import header

    st.session_state["user"] = "test@example.com"
    header.bar()


def test_market_bar_renders_without_a_feed():
    at = AppTest.from_function(_bar, default_timeout=30)
    at.run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    assert 'class="tape"' in text and ("Market open" in text or "Market closed" in text)
