"""Reference data write-through: normalization, dedupe, append-only storage, and the stale
copy served while a refresh runs. No network: fetchers are plain functions passed in."""

from __future__ import annotations

import pandas as pd
import pytest

from alphasurface.collector import reference as ref
from alphasurface.config import Config
from alphasurface.storage import reference as store

NOW = pd.Timestamp("2026-10-07 20:00", tz="UTC")


@pytest.fixture
def cfg(tmp_path):
    return Config(data_dir=tmp_path)


def _news(ids, titles, minutes_ago, collected=NOW):
    return pd.DataFrame(
        {
            "collected_at": collected,
            "source": "yfinance",
            "id": ids,
            "title": titles,
            "publisher": "Wire",
            "link": "https://example.com",
            "related": "SPY",
            "published": [NOW - pd.Timedelta(minutes=m) for m in minutes_ago],
            "query": "q",
        }
    )


def test_dedupe_news_by_id_and_headline():
    df = _news(
        ["a", "a", "b", "c"],
        ["Stocks rise", "Stocks rise", "Stocks rise!", "Bonds fall"],
        [5, 5, 3, 10],
    )
    out = ref.dedupe_news(df)
    assert list(out["title"]) == ["Stocks rise!", "Bonds fall"]  # newest first, punctuation ignored


def test_normalize_calendar_flags_key_events():
    raw = pd.DataFrame(
        {
            "Event": ["CPI MM, SA*", "Mortgage Market Index", "Cont Jobl Clm"],
            "Region": ["US", "US", "US"],
            "Event Time": pd.to_datetime(
                ["2026-10-15 12:30", "2026-10-07 11:00", "2026-10-08 12:30"], utc=True
            ),
            "For": ["Sep", None, "Oct"],
            "Actual": [None, 204.7, None],
            "Expected": [0.3, None, None],
            "Last": [0.4, 213.6, 1.9],
            "Revised": [None, None, None],
        }
    ).set_index("Event")
    out = ref.normalize_calendar(raw, NOW)
    assert list(out["event"]) == ["Mortgage Market Index", "Cont Jobl Clm", "CPI MM, SA"]  # by time
    assert list(out["key"]) == [False, True, True]
    assert out["time"].dt.tz is not None and (out["collected_at"] == NOW).all()
    assert ref.normalize_calendar(pd.DataFrame(), NOW).empty


def test_store_appends_new_files_and_reads_latest(cfg):
    p1 = store.append(_news(["a"], ["One"], [5], NOW - pd.Timedelta(hours=1)), "news", cfg)
    p2 = store.append(_news(["b", "c"], ["Two", "Three"], [1, 2]), "news", cfg)
    assert p1 != p2 and p1.exists() and p2.exists()
    assert len(store.read("news", cfg)) == 3
    assert set(store.latest("news", cfg)["id"]) == {"b", "c"}
    assert store.append(pd.DataFrame(), "news", cfg) is None
    with pytest.raises(ValueError):
        store.append(_news(["x"], ["X"], [1]), "not_a_table", cfg)


def test_latest_per_key(cfg):
    base = {"source": "yfinance", "trailing_pe": 25.0}
    store.append(
        pd.DataFrame([{**base, "collected_at": NOW - pd.Timedelta(days=1), "symbol": "QQQ"}]),
        "etf_profile",
        cfg,
    )
    store.append(pd.DataFrame([{**base, "collected_at": NOW, "symbol": "SPY"}]), "etf_profile", cfg)
    assert set(store.latest("etf_profile", cfg, by="symbol")["symbol"]) == {"SPY", "QQQ"}
    assert set(store.latest("etf_profile", cfg)["symbol"]) == {"SPY"}


def test_write_through_returns_frame_even_when_storage_fails(cfg, monkeypatch):
    frame = _news(["a"], ["One"], [1])
    monkeypatch.setattr(
        store, "append", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
    )
    assert ref.write_through("news", frame, cfg) is frame


def test_refresh_first_fetch_then_stored_copy(cfg, monkeypatch):
    monkeypatch.setattr(ref, "OFFLINE", False)
    calls = []

    def fetch():
        calls.append(1)
        return _news(["a"], ["One"], [1], pd.Timestamp.now(tz="UTC"))

    first = ref.refresh("news", fetch, config=cfg, wait=10)
    assert first.origin == "live" and len(first.frame) == 1 and calls == [1]
    second = ref.refresh("news", fetch, config=cfg)
    assert second.origin == "fresh" and calls == [1]  # inside the window: no new fetch


def test_refresh_offline_with_nothing_stored(cfg, monkeypatch):
    monkeypatch.setattr(ref, "OFFLINE", True)
    out = ref.refresh("econ_calendar", lambda: pytest.fail("must not fetch"), config=cfg)
    assert out.origin == "none" and out.frame.empty


def test_failed_fetch_falls_back_to_stored(cfg, monkeypatch):
    monkeypatch.setattr(ref, "OFFLINE", False)
    store.append(_news(["old"], ["Old"], [600], NOW - pd.Timedelta(days=2)), "news", cfg)

    def broken():
        raise ConnectionError("provider down")

    out = ref.refresh("news", broken, config=cfg)
    assert out.origin == "stale" and list(out.frame["id"]) == ["old"]
