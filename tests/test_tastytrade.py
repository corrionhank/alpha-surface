"""tastytrade plumbing, offline: the SDK and the streamer are replaced with fakes."""

from __future__ import annotations

import math
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace as NS

import pandas as pd
import pytest

from alphasurface.collector import chains, tasty
from alphasurface.collector.tastytrade_collector import metrics_frames


def _row(bid, ask, last=math.nan, prev=100.0, close=math.nan, oi=0.0, vol=0.0, t=None):
    return {
        "bid": bid,
        "ask": ask,
        "last": last,
        "volume": vol,
        "last_time": t,
        "open_interest": oi,
        "prev_close": prev,
        "day_close": close,
    }


def test_mark_prefers_mid_then_falls_back():
    assert tasty.mark(_row(1.0, 1.2)) == pytest.approx(1.1)
    assert tasty.mark(_row(0.0, 0.0, last=2.5)) == 2.5
    assert tasty.mark(_row(math.nan, math.nan, close=3.0)) == 3.0
    assert tasty.mark(_row(math.nan, math.nan, prev=4.0)) == 4.0


def test_metrics_frames_normalize_units():
    m = NS(
        symbol="SPY",
        implied_volatility_index=Decimal("0.154"),
        implied_volatility_index_5_day_change=Decimal("-0.01"),
        implied_volatility_index_rank="0.30",
        implied_volatility_index_rank_source="tos",
        tw_implied_volatility_index_rank=Decimal("0.12"),
        tos_implied_volatility_index_rank=Decimal("0.30"),
        implied_volatility_percentile="0.157",
        implied_volatility_30_day=Decimal("15.41"),
        historical_volatility_30_day=Decimal("9.88"),
        historical_volatility_60_day=Decimal("11"),
        historical_volatility_90_day=None,
        iv_hv_30_day_difference=Decimal("5.53"),
        liquidity_rating=4,
        beta=Decimal("1"),
        corr_spy_3month=Decimal("1"),
        earnings=NS(expected_report_date=date(2026, 10, 29), time_of_day="AMC"),
        dividend_ex_date=None,
        updated_at=datetime(2026, 10, 8, 21, 6),
        option_expiration_implied_volatilities=[
            NS(
                expiration_date=date(2026, 10, 16),
                settlement_type="PM",
                option_chain_type="Standard",
                implied_volatility=Decimal("0.13"),
            )
        ],
    )
    frame, term = metrics_frames([m], pd.Timestamp("2026-10-08 21:10", tz="UTC"))
    r = frame.iloc[0]
    assert r["iv30"] == pytest.approx(0.1541) and r["hv30"] == pytest.approx(
        0.0988
    )  # percent -> decimal
    assert r["ivx"] == pytest.approx(0.154) and r["iv_rank"] == pytest.approx(0.30)
    assert math.isnan(r["hv90"]) and r["iv_hv_diff"] == pytest.approx(5.53)  # vol points kept
    assert term.iloc[0]["expiry"] == "2026-10-16" and term.iloc[0]["iv"] == pytest.approx(0.13)


def _nested():
    strikes = [
        NS(
            strike_price=Decimal(k),
            call=f"SPY C{k}",
            put=f"SPY P{k}",
            call_streamer_symbol=f".SPYC{k}",
            put_streamer_symbol=f".SPYP{k}",
        )
        for k in (50, 95, 100, 105, 200)
    ]
    exp = NS(expiration_date=date(2026, 10, 16), settlement_type="PM", strikes=strikes)
    return [NS(expirations=[exp])]


def test_chain_from_nested_and_stream(monkeypatch):
    def quotes(symbols, wait=3.0):
        out = {"SPY": _row(99.9, 100.1, prev=99.0)}
        out.update(
            {
                s: _row(1.0, 1.1, last=1.05, prev=1.0, oi=10, vol=5, t=1_790_000_000_000)
                for s in symbols
                if s.startswith(".")
            }
        )
        return out

    monkeypatch.setattr(tasty, "nested_chain", lambda symbol: _nested())
    monkeypatch.setattr(tasty, "stream_quotes", quotes)
    df = chains.TastytradeChains().chain("SPY")
    assert set(df["strike"]) == {95.0, 100.0, 105.0}  # 50 and 200 fall outside the 25% band
    assert len(df) == 6 and set(df["kind"]) == {"call", "put"}
    assert df["underlying"].iloc[0] == pytest.approx(100.0)
    assert df["underlying_prev"].iloc[0] == pytest.approx(99.0)
    assert df["change"].iloc[0] == pytest.approx(0.05)
    assert list(df.columns) == chains.CHAIN_COLUMNS + chains.EXTRA_COLUMNS
    assert chains.TastytradeChains().expirations("SPY") == ["2026-10-16"]


def test_not_configured_falls_back(monkeypatch):
    monkeypatch.setattr(tasty, "ready", lambda: False)
    assert chains.default_source() == "synthetic"
    assert chains.source_label("synthetic") == "sample data"
    assert chains.source_label("yfinance") == "yfinance, delayed"
