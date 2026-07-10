"""Storage round-trip + upsert semantics (no network)."""

from __future__ import annotations

import pandas as pd
import pytest

from config import Config
from present.summary import summarize
from storage import reader, schema, writer


def _bars(symbol: str, closes: list[float], start: str = "2026-07-10 13:30") -> pd.DataFrame:
    ts = pd.date_range(start, periods=len(closes), freq="1h", tz="UTC")
    return pd.DataFrame(
        {
            "ts": ts,
            "symbol": symbol,
            "interval": "1h",
            "open": closes,
            "high": [c + 1 for c in closes],
            "low": [c - 1 for c in closes],
            "close": closes,
            "volume": [1000 * (i + 1) for i in range(len(closes))],
        }
    )


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(data_dir=tmp_path)


def test_empty_view_before_any_data(config):
    with schema.connect(config, persistent=False) as conn:
        assert reader.available_symbols(conn) == []
        assert reader.get_ohlcv(conn, "SPY").empty


def test_write_and_read_roundtrip(config):
    writer.write_ohlcv(_bars("SPY", [500, 501, 502]), config)
    with schema.connect(config, persistent=False) as conn:
        assert reader.available_symbols(conn, "1h") == ["SPY"]
        df = reader.get_ohlcv(conn, "SPY", "1h")
    assert len(df) == 3
    assert df["ts"].is_monotonic_increasing
    assert df["close"].tolist() == [500, 501, 502]


def test_upsert_dedup_keeps_latest(config):
    writer.write_ohlcv(_bars("SPY", [500, 501, 502]), config)
    # Re-collect overlapping window with a revised middle bar (partial-bar refresh).
    writer.write_ohlcv(_bars("SPY", [500, 555, 502]), config)
    with schema.connect(config, persistent=False) as conn:
        df = reader.get_ohlcv(conn, "SPY", "1h")
    assert len(df) == 3  # no duplicates accumulated
    assert df["close"].tolist() == [500, 555, 502]  # freshest row won


def test_multi_symbol_and_summary(config):
    writer.write_ohlcv(_bars("SPY", [500, 505]), config)
    writer.write_ohlcv(_bars("QQQ", [400, 396]), config)
    with schema.connect(config, persistent=False) as conn:
        assert reader.available_symbols(conn) == ["QQQ", "SPY"]
        spy = reader.get_ohlcv(conn, "SPY", "1h")
    s = summarize(spy)
    assert s["symbol"] == "SPY"
    assert s["last"] == 505
    assert s["change_pct"] == pytest.approx(1.0)
