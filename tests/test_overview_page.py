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
