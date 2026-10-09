"""Smoke test: the Research page renders a stock, a fund and the economy from a temp store, with
every provider fetch refused."""

from __future__ import annotations

import pandas as pd
import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from alphasurface.collector import economy as econ
from alphasurface.collector import fundamentals as fa
from alphasurface.collector import reference as ref
from alphasurface.config import REPO_ROOT, ApiKeys, Config
from alphasurface.present import data
from alphasurface.storage import reference as store
from alphasurface.storage import writer

PAGE = str(REPO_ROOT / "src" / "alphasurface" / "present" / "research.py")


def _refuse(*_a, **_k):
    raise AssertionError("no provider calls in this test")


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    cfg = Config(data_dir=tmp_path, keys=ApiKeys(fred="test-key"))
    now = pd.Timestamp.now(tz="UTC")
    base = {"collected_at": now, "source": "yfinance"}
    store.append(
        pd.DataFrame(
            [
                {
                    **base,
                    "symbol": "TST",
                    "name": "Test Corp",
                    "quote_type": "EQUITY",
                    "sector": "Technology",
                    "industry": "Software",
                    "exchange": "NasdaqGS",
                    "currency": "USD",
                    "price": 100.0,
                    "prev_close": 98.0,
                    "market_cap": 2e12,
                    "enterprise_value": 2.1e12,
                    "trailing_pe": 30.0,
                    "forward_pe": 25.0,
                    "trailing_eps": 3.3,
                    "forward_eps": 4.0,
                    "dividend_yield": 0.005,
                    "beta": 1.1,
                    "week52_low": 80.0,
                    "week52_high": 120.0,
                    "gross_margin": 0.6,
                    "target_low": 90.0,
                    "target_mean": 115.0,
                    "target_median": 112.0,
                    "target_high": 140.0,
                    "recommendation": "buy",
                    "analysts": 30.0,
                    "rec_strong_buy": 5.0,
                    "rec_buy": 15.0,
                    "rec_hold": 8.0,
                    "rec_sell": 1.0,
                    "rec_strong_sell": 1.0,
                    "summary": "Makes test software.",
                    "website": "https://example.com",
                    "employees": 1000.0,
                },
                {
                    **base,
                    "symbol": "FND",
                    "name": "Test Fund",
                    "quote_type": "ETF",
                    "exchange": "NYSEArca",
                    "currency": "USD",
                    "price": 50.0,
                    "prev_close": 50.5,
                    "week52_low": 40.0,
                    "week52_high": 55.0,
                },
            ]
        ),
        "fundamentals",
        cfg,
    )
    ends = ["2025-12-31", "2024-12-31"]
    store.append(
        pd.DataFrame(
            [
                {
                    **base,
                    "symbol": "TST",
                    "statement": s,
                    "freq": "annual",
                    "period_end": pd.Timestamp(e),
                    "item": item,
                    "value": v,
                }
                for s, item, vals in (
                    ("income", "Total Revenue", [5e10, 4e10]),
                    ("income", "Net Income", [1e10, 8e9]),
                    ("cashflow", "Free Cash Flow", [9e9, 7e9]),
                )
                for e, v in zip(ends, vals, strict=True)
            ]
        ),
        "financials",
        cfg,
    )
    store.append(
        pd.DataFrame(
            [
                {
                    **base,
                    "symbol": "TST",
                    "report_date": now + pd.Timedelta(days=20),
                    "eps_estimate": 1.0,
                    "eps_actual": float("nan"),
                    "surprise": float("nan"),
                },
                {
                    **base,
                    "symbol": "TST",
                    "report_date": now - pd.Timedelta(days=70),
                    "eps_estimate": 0.9,
                    "eps_actual": 1.0,
                    "surprise": 0.111,
                },
            ]
        ),
        "earnings",
        cfg,
    )
    store.append(
        pd.DataFrame(
            [
                {
                    **base,
                    "symbol": "FND",
                    "name": "Test Fund",
                    "category": "Large Blend",
                    "expense_ratio": 0.0009,
                    "total_assets": 5e11,
                }
            ]
        ),
        "etf_profile",
        cfg,
    )
    store.append(
        pd.DataFrame(
            [
                {
                    **base,
                    "fund": "FND",
                    "kind": "holding",
                    "rank": 1,
                    "key": "TST",
                    "name": "Test Corp",
                    "weight": 0.07,
                }
            ]
        ),
        "etf_holdings",
        cfg,
    )
    store.append(
        pd.DataFrame(
            [
                {
                    **base,
                    "event": "CPI",
                    "region": "US",
                    "time": now + pd.Timedelta(days=1),
                    "period": "Sep",
                    "actual": float("nan"),
                    "expected": 3.0,
                    "last": 2.9,
                    "revised": float("nan"),
                    "key": True,
                }
            ]
        ),
        "econ_calendar",
        cfg,
    )
    months = pd.date_range("2024-01-01", periods=24, freq="MS")
    store.append(
        pd.concat(
            [
                pd.DataFrame(
                    {
                        "collected_at": now,
                        "source": "fred",
                        "series": sid,
                        "date": months,
                        "value": [100 + i for i in range(24)] if how == "yoy" else 4.0,
                    }
                )
                for sid, (_, how) in econ.SERIES.items()
            ]
        ),
        "macro_series",
        cfg,
    )
    days = pd.date_range(end=now.normalize(), periods=400, freq="D", tz="UTC")
    for sym, level in (("^IRX", 4.0), ("^FVX", 3.8), ("^TNX", 4.2), ("^TYX", 4.6)):
        writer.write_ohlcv(
            pd.DataFrame(
                {
                    "ts": days,
                    "symbol": sym,
                    "interval": "1d",
                    "open": level,
                    "high": level,
                    "low": level,
                    "close": level,
                    "volume": 0,
                }
            ),
            cfg,
        )

    monkeypatch.setattr(data, "config", cfg)
    for name in ("fetch_snapshot", "fetch_financials", "fetch_earnings"):
        monkeypatch.setattr(fa, name, _refuse)
    monkeypatch.setattr(
        fa,
        "fetch_filings",
        lambda sym: fa.normalize_filings(
            [
                {
                    "date": "2026-07-31",
                    "type": "10-Q",
                    "title": "Periodic Financial Reports",
                    "edgarUrl": "https://finance.yahoo.com/sec-filing/TST/0000000001-26-000001_1",
                }
            ],
            sym,
        ),
    )
    monkeypatch.setattr(econ, "fetch_macro", _refuse)
    for name in ("fetch_calendar", "fetch_profiles", "fetch_holdings"):
        monkeypatch.setattr(ref, name, _refuse)
    st.cache_data.clear()
    return cfg


def _run(**params) -> AppTest:
    at = AppTest.from_file(PAGE, default_timeout=60)
    for k, v in params.items():
        at.query_params[k] = v
    at.run()
    assert not at.exception, at.exception
    return at


def _text(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def test_stock_fundamentals(cfg):
    text = _text(_run(tab="fundamentals", symbol="TST"))
    for needle in (
        "Test Corp",
        "Valuation",
        "Profitability",
        "Analysts",
        "Financial statements",
        "Revenue",
        "+25.0%",
        "Beat 1 of last 1",
        "Recent reports",
        "sec.gov",
        "Makes test software.",
    ):
        assert needle in text, needle


def test_fund_shows_profile_and_holdings(cfg):
    text = _text(_run(tab="fundamentals", symbol="FND"))
    for needle in (
        "Test Fund",
        "Large Blend",
        "Top holdings",
        "No financial statements for funds.",
    ):
        assert needle in text, needle
    assert "Financial statements" not in text


def test_economy(cfg):
    text = _text(_run(tab="economy"))
    for needle in (
        "Macro",
        "CPI inflation",
        "Economic calendar",
        "CPI",
        "Treasury curve",
        "10Y minus 3M",
    ):
        assert needle in text, needle
