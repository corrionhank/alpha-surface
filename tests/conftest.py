"""Shared test setup."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_tastytrade(monkeypatch, request):
    """Tests never reach tastytrade, whatever is in .env: pages fall back to stored or sample
    data. tests/test_tastytrade.py fakes the SDK itself."""
    from alphasurface.collector import tasty

    monkeypatch.setattr(tasty, "ready", lambda: False)
    monkeypatch.setattr(
        tasty, "client", lambda: (_ for _ in ()).throw(tasty.NotConfigured("tests"))
    )


@pytest.fixture(autouse=True)
def _no_yahoo(monkeypatch):
    """Bar top-ups never reach Yahoo in tests: pages read what is stored. Tests that exercise
    the gateway patch fetch_ohlcv themselves, which overrides this."""
    import pandas as pd

    from alphasurface.collector import yfinance_collector
    from alphasurface.storage import schema

    monkeypatch.setattr(
        yfinance_collector,
        "fetch_ohlcv",
        lambda *a, **k: pd.DataFrame(columns=schema.OHLCV_COLUMNS),
    )
