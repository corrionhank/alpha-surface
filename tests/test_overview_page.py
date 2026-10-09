"""Smoke test: the overview renders from stored data alone, with every network fetch off."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from alphasurface.collector import reference as ref
from alphasurface.config import REPO_ROOT, load_config
from alphasurface.storage import reader, schema

PAGE = REPO_ROOT / "src" / "alphasurface" / "present" / "overview.py"


def _has_core() -> bool:
    with schema.connect(load_config(), persistent=False) as conn:
        return {"SPY", "^VIX"} <= set(reader.available_symbols(conn, "1d"))


@pytest.mark.skipif(not _has_core(), reason="needs stored SPY and ^VIX daily bars")
def test_overview_renders_offline(monkeypatch):
    monkeypatch.setattr(ref, "OFFLINE", True)
    at = AppTest.from_file(str(PAGE), default_timeout=90)
    at.run()
    assert not at.exception
    text = " ".join(m.value for m in at.markdown)
    for needle in ("Dashboard", "kpi-grid", "Fear and greed", "Implied vol"):
        assert needle in text


def test_overview_on_an_empty_store_backfills_then_notes(monkeypatch, tmp_path):
    """No stored core history: the page asks the data layer to backfill it and, if that has not
    landed, says so in one line instead of stopping with a command to run."""
    import dataclasses

    import streamlit as st

    from alphasurface.present import data

    st.cache_data.clear()  # the stored-bar cache outlives one AppTest run
    cfg = dataclasses.replace(load_config(), data_dir=tmp_path)
    asked = []
    monkeypatch.setattr(ref, "OFFLINE", True)
    monkeypatch.setattr(data, "config", cfg)
    monkeypatch.setattr(data, "conn", lambda: schema.connect(cfg, persistent=False))
    monkeypatch.setattr(data, "top_up", lambda *a, **k: None)
    monkeypatch.setattr(
        data, "ensure_daily", lambda symbols, timeout=20: asked.append(symbols) or list(symbols)
    )
    at = AppTest.from_file(str(PAGE), default_timeout=90)
    at.run()
    assert not at.exception
    assert asked and "SPY" in asked[0]
    text = " ".join(m.value for m in at.markdown)
    assert "still loading" in text and "python -m" not in text
    st.cache_data.clear()
