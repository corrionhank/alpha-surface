"""Smoke test: the scenarios page renders every tab against the stored data without raising."""

from __future__ import annotations

import pytest
from streamlit.testing.v1 import AppTest

from config import REPO_ROOT, load_config
from storage import reader, schema

PAGE = REPO_ROOT / "src" / "present" / "scenarios.py"


def _has_spy() -> bool:
    with schema.connect(load_config(), persistent=False) as conn:
        return "SPY" in reader.available_symbols(conn, "1d")


@pytest.mark.skipif(not _has_spy(), reason="needs stored SPY daily bars")
@pytest.mark.parametrize("model", ["Brownian motion", "Jump diffusion", "Historical bootstrap"])
def test_page_renders(model):
    at = AppTest.from_file(str(PAGE), default_timeout=60)
    at.run()
    assert not at.exception
    at.sidebar.radio[0].set_value(model).run()
    assert not at.exception
    assert any("Market scenarios" in m.value for m in at.markdown)
