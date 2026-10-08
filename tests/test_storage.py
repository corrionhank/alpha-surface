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


def test_one_file_per_series(config):
    writer.write_ohlcv(_bars("SPY", [500, 501]), config)
    writer.write_ohlcv(_bars("QQQ", [400, 401]), config)
    files = sorted(p.relative_to(config.parquet_dir / "ohlcv").as_posix()
                   for p in (config.parquet_dir / "ohlcv").rglob("*.parquet"))
    assert files == ["1h/QQQ.parquet", "1h/SPY.parquet"]


def test_compact_moves_day_partitions_aside(config):
    old = config.parquet_dir / "ohlcv" / "year=2026" / "month=7" / "day=10" / "data.parquet"
    old.parent.mkdir(parents=True)
    _bars("SPY", [500, 501, 502]).to_parquet(old, index=False)
    writer.write_ohlcv(_bars("SPY", [500, 555], start="2026-07-10 14:30"), config)  # overlaps
    out = writer.compact_ohlcv(config)
    assert out["moved"] == 1 and not old.exists()
    with schema.connect(config, persistent=False) as conn:
        df = reader.get_ohlcv(conn, "SPY", "1h")
    assert df["close"].tolist() == [500, 500, 555]  # the series file's newer rows won
    assert writer.compact_ohlcv(config)["moved"] == 0
