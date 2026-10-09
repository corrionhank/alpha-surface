"""Fundamentals and macro: the ratio and growth math, normalization of Yahoo- and FRED-shaped
inputs, and the per-symbol write-through. No network: fetchers are plain functions passed in."""

from __future__ import annotations

import math
import time

import pandas as pd
import pytest

from alphasurface.collector import economy as econ
from alphasurface.collector import fundamentals as fa
from alphasurface.collector import reference as ref
from alphasurface.config import ApiKeys, Config
from alphasurface.derive import economy as em
from alphasurface.derive import fundamentals as fd
from alphasurface.storage import reference as store

NOW = pd.Timestamp("2026-10-08 20:00", tz="UTC")


@pytest.fixture
def cfg(tmp_path):
    return Config(data_dir=tmp_path)


def statement_rows(
    statement: str, freq: str, items: dict[str, list[float]], ends: list[str]
) -> pd.DataFrame:
    rows = [
        {
            "collected_at": NOW,
            "source": "yfinance",
            "symbol": "TST",
            "statement": statement,
            "freq": freq,
            "period_end": pd.Timestamp(e),
            "item": item,
            "value": v,
        }
        for item, vals in items.items()
        for e, v in zip(ends, vals, strict=True)
        if v == v
    ]
    return pd.DataFrame(rows)


YEARS = ["2025-09-30", "2024-09-30", "2023-09-30"]
LONG = pd.concat(
    [
        statement_rows(
            "income",
            "annual",
            {
                "Total Revenue": [400.0, math.nan, 300.0],
                "Operating Revenue": [399.0, 350.0, 299.0],
                "Gross Profit": [200.0, 160.0, 120.0],
                "Net Income": [100.0, -50.0, -100.0],
                "EBITDA": [150.0, 120.0, 90.0],
                "Diluted EPS": [2.0, -1.0, -2.0],
            },
            YEARS,
        ),
        statement_rows(
            "balance",
            "annual",
            {
                "Stockholders Equity": [500.0, 450.0, 400.0],
                "Total Debt": [250.0, 200.0, 150.0],
                "Total Assets": [1000.0, 900.0, 800.0],
            },
            YEARS,
        ),
        statement_rows("cashflow", "annual", {"Free Cash Flow": [80.0, 60.0, 40.0]}, YEARS),
        statement_rows(
            "income",
            "quarterly",
            {"Total Revenue": [110.0, 105.0, 100.0, 95.0, 100.0]},
            ["2026-06-30", "2026-03-31", "2025-12-31", "2025-09-30", "2025-06-30"],
        ),
    ],
    ignore_index=True,
)


def test_wide_takes_first_item_with_a_value_newest_first():
    t = fd.wide(LONG, "income", "annual")
    assert list(t.columns) == sorted(t.columns, reverse=True)
    # Total Revenue is blank for 2024, so that year falls back to Operating Revenue.
    assert t.loc["Revenue"].tolist() == [400.0, 350.0, 300.0]
    assert "Operating income" not in t.index  # not in the statement, not invented
    assert fd.wide(LONG, "income", "monthly").empty


def test_growth_is_year_over_year_for_both_frequencies():
    annual = fd.growth(fd.wide(LONG, "income", "annual"), fd.LAG["annual"])
    assert annual.loc["Revenue"].iloc[0] == pytest.approx(400 / 350 - 1)
    assert math.isnan(annual.loc["Revenue"].iloc[-1])  # nothing older to compare with
    # Growth off a loss keeps its sign: -50 to +100 is an improvement of 3x the loss.
    assert annual.loc["Net income"].iloc[0] == pytest.approx(3.0)
    assert annual.loc["Net income"].iloc[1] == pytest.approx(0.5)
    quarterly = fd.growth(fd.wide(LONG, "income", "quarterly"), fd.LAG["quarterly"])
    assert quarterly.loc["Revenue"].iloc[0] == pytest.approx(110 / 100 - 1)  # vs Jun 2025
    assert quarterly.loc["Revenue"].iloc[1:].isna().all()


def test_ratios_prefer_the_snapshot_and_fall_back_to_statements():
    snap = {
        "market_cap": 2000.0,
        "gross_margin": 0.6,
        "debt_to_equity": math.nan,
        "enterprise_value": 2100.0,
        "free_cash_flow": None,
    }
    r = fd.key_ratios(snap, LONG)
    assert r["gross_margin"] == 0.6  # provider's figure
    assert r["debt_to_equity"] == pytest.approx(250 / 500)  # computed: snapshot was blank
    assert r["net_margin"] == pytest.approx(100 / 400)
    assert r["fcf_yield"] == pytest.approx(80 / 2000)
    assert r["ev_to_ebitda"] == pytest.approx(2100 / 150)
    assert r["price_to_book"] == pytest.approx(2000 / 500)
    assert math.isnan(fd.key_ratios({}, pd.DataFrame())["roe"])


def test_small_math():
    assert fd.ratio(1, 0) != fd.ratio(1, 0)  # NaN
    assert fd.surprise(2.02, 1.89) == pytest.approx(0.13 / 1.89)
    assert fd.scale(pd.Series([5e9, 1e8])) == (1e9, "B")
    assert fd.scale(pd.Series([5e8])) == (1e6, "M")


def test_normalize_info_units_and_recommendations():
    info = {
        "quoteType": "EQUITY",
        "longName": "Test Corp",
        "dividendYield": 0.32,
        "debtToEquity": 78.4,
        "marketCap": 1e12,
        "currentPrice": 100.0,
        "trailingPE": 30.0,
    }
    recs = pd.DataFrame(
        {
            "period": ["0m", "-1m"],
            "strongBuy": [6, 5],
            "buy": [19, 20],
            "hold": [13, 13],
            "sell": [3, 3],
            "strongSell": [3, 2],
        }
    )
    row = fa.normalize_info(info, "TST", NOW, recs).iloc[0]
    assert row["dividend_yield"] == pytest.approx(0.0032)
    assert row["debt_to_equity"] == pytest.approx(0.784)
    assert row["rec_buy"] == 19 and row["rec_strong_sell"] == 3  # the current month only
    assert math.isnan(row["forward_pe"])
    assert fa.normalize_info({"trailingPegRatio": None}, "NOPE", NOW).empty


def test_normalize_statement_long_form():
    frame = pd.DataFrame(
        {pd.Timestamp("2025-09-30"): [400.0, None], pd.Timestamp("2024-09-30"): [350.0, 2.0]},
        index=["Total Revenue", "Diluted EPS"],
    )
    long = fa.normalize_statement(frame, "TST", "income", "annual", NOW)
    assert len(long) == 3  # the blank is dropped
    assert set(long.columns) >= {
        "collected_at",
        "symbol",
        "statement",
        "freq",
        "period_end",
        "item",
        "value",
    }
    assert long["period_end"].dt.tz is None
    assert fa.normalize_statement(pd.DataFrame(), "TST", "income", "annual", NOW).empty


def test_normalize_earnings_keeps_the_next_date():
    idx = pd.DatetimeIndex(
        ["2026-11-02 16:00", "2026-07-30 16:00"], tz="America/New_York", name="Earnings Date"
    )
    raw = pd.DataFrame(
        {"EPS Estimate": [1.98, 1.89], "Reported EPS": [None, 2.02], "Surprise(%)": [None, 6.74]},
        index=idx,
    )
    df = fa.normalize_earnings(raw, "TST", NOW)
    assert df["report_date"].iloc[0] > df["report_date"].iloc[1]  # newest first
    assert df["surprise"].iloc[1] == pytest.approx(0.0674)
    assert math.isnan(df["eps_actual"].iloc[0])
    assert str(df["report_date"].dt.tz) == "UTC"


def test_filings_filter_and_edgar_links():
    raw = [
        {
            "date": "2026-07-31",
            "type": "10-Q",
            "title": "Periodic Financial Reports",
            "edgarUrl": "https://finance.yahoo.com/sec-filing/TST/0000320193-26-000020_320193",
            "exhibits": {"10-Q": "https://cdn.example.com/q.htm"},
        },
        {"date": "2026-08-01", "type": "4", "title": "Insider", "edgarUrl": ""},
        {
            "date": "2026-09-01",
            "type": "8-K/A",
            "title": "Changes",
            "edgarUrl": "https://example.com/other",
        },
    ]
    df = fa.normalize_filings(raw, "TST")
    assert df["type"].tolist() == ["8-K/A", "10-Q"]  # form 4 dropped, newest first
    q = df.iloc[1]
    assert q["url"] == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000020/"
        "0000320193-26-000020-index.htm"
    )
    assert q["cik"] == "320193" and q["document"] == "https://cdn.example.com/q.htm"
    assert df.iloc[0]["url"] == "https://example.com/other"  # no accession number to rebuild from
    assert fa.edgar_url("TST") == "https://www.sec.gov/edgar/browse/?CIK=TST"
    assert fa.normalize_filings(None, "TST").empty


def _snap(symbol: str, collected=NOW) -> pd.DataFrame:
    return pd.DataFrame(
        [{"collected_at": collected, "source": "yfinance", "symbol": symbol, "name": symbol}]
    )


def test_refresh_for_serves_fresh_store_without_fetching(cfg, monkeypatch):
    monkeypatch.setattr(fa, "_now", lambda: NOW)
    store.append(_snap("AAA"), "fundamentals", cfg)
    store.append(_snap("BBB", NOW - pd.Timedelta(days=2)), "fundamentals", cfg)

    def boom():
        raise AssertionError("should not fetch")

    got = fa.refresh_for(
        "fundamentals", "symbol", "AAA", boom, config=cfg, max_age=pd.Timedelta(hours=12)
    )
    assert got.origin == "fresh" and got.frame["symbol"].tolist() == [
        "AAA"
    ]  # BBB's pull not mixed in


def test_refresh_for_stale_serves_store_and_refreshes(cfg, monkeypatch):
    monkeypatch.setattr(fa, "_now", lambda: NOW)
    store.append(_snap("AAA", NOW - pd.Timedelta(days=2)), "fundamentals", cfg)
    got = fa.refresh_for(
        "fundamentals",
        "symbol",
        "AAA",
        lambda: _snap("AAA"),
        config=cfg,
        max_age=pd.Timedelta(hours=12),
    )
    assert got.origin == "stale"
    for _ in range(50):  # the background fetch lands in the store
        if len(store.read("fundamentals", cfg)) == 2:
            break
        time.sleep(0.05)
    assert len(store.read("fundamentals", cfg)) == 2


def test_refresh_for_first_fetch_waits_and_offline_never_fetches(cfg, monkeypatch):
    got = fa.refresh_for(
        "earnings", "symbol", "NEW", lambda: _snap("NEW"), config=cfg, max_age=pd.Timedelta(hours=6)
    )
    assert got.origin == "live" and not store.read("earnings", cfg).empty
    monkeypatch.setattr(ref, "OFFLINE", True)
    none = fa.refresh_for(
        "earnings",
        "symbol",
        "OTHER",
        lambda: _snap("OTHER"),
        config=cfg,
        max_age=pd.Timedelta(hours=6),
    )
    assert none.origin == "none" and none.frame.empty


def test_fred_observations_and_macro_without_key(cfg):
    df = econ.normalize_observations(
        "UNRATE",
        [{"date": "2026-08-01", "value": "4.2"}, {"date": "2026-09-01", "value": "."}],
        NOW,
    )
    assert df["value"].tolist() == [4.2] and df["series"].iloc[0] == "UNRATE"
    assert econ.normalize_observations("UNRATE", [], NOW).empty
    assert econ.macro(cfg).frame.empty  # no key: nothing fetched, nothing shown
    keyed = Config(data_dir=cfg.data_dir, keys=ApiKeys(fred="k"))
    store.append(
        pd.concat([df.assign(collected_at=pd.Timestamp.now(tz="UTC"))]), "macro_series", keyed
    )
    assert econ.macro(keyed).origin == "fresh"


def test_rates_math():
    idx = pd.to_datetime(["2026-01-02", "2026-02-02", "2026-03-02"])
    ten = pd.Series([4.0, 4.2, 4.5], index=idx)
    bill = pd.Series([4.4, 4.3], index=idx[:2])
    assert em.value_on(ten, "2026-02-15") == 4.2
    assert math.isnan(em.value_on(ten, "2025-12-31"))
    assert em.spread(ten, bill).round(2).tolist() == [-0.4, -0.1]  # only the shared dates
    assert em.change_bp(ten, 28) == pytest.approx(30.0)  # 4.5 vs 4.2 on Feb 2
    assert em.change_bp(ten, 30) == pytest.approx(50.0)  # Jan 31 still reads Jan 2's 4.0
    assert em.curve_at({"10Y": ten, "3M": bill}, "2026-03-05") == {"10Y": 4.5, "3M": 4.3}
    cpi = pd.Series(
        range(100, 114), index=pd.date_range("2025-01-01", periods=14, freq="MS"), dtype=float
    )
    assert em.yoy(cpi, 12).iloc[-1] == pytest.approx((113 / 101 - 1) * 100)
