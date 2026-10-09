"""Daily bars are keyed by New York session date, whoever stamped them and however."""

from __future__ import annotations

import pandas as pd
import pytest

from alphasurface.config import Config
from alphasurface.storage import reader, schema, writer


def _daily(stamps: list[str], closes: list[float], symbol: str = "^VIX") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts": pd.to_datetime(stamps, utc=True),
            "symbol": symbol,
            "interval": "1d",
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": 0,
        }
    )


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(data_dir=tmp_path)


def test_session_dates_maps_every_vendor_stamp_to_new_york_midnight():
    stamps = pd.Series(
        pd.to_datetime(
            [
                "2026-10-07 04:00",  # midnight New York (EDT)
                "2026-10-07 05:00",  # midnight Chicago, Yahoo's stamp for Cboe indices
                "2026-10-07 00:00",  # midnight UTC, the New York evening before
                "2026-10-07 20:00",  # stamped at the close
                "2026-12-07 05:00",  # midnight New York (EST)
                "2026-12-07 06:00",  # midnight Chicago (CST)
            ],
            utc=True,
        )
    )
    out = schema.session_dates(stamps)
    ny = out.dt.tz_convert(schema.NY)
    assert (ny.dt.hour == 0).all()
    assert [d.isoformat() for d in ny.dt.date] == ["2026-10-07"] * 4 + ["2026-12-07"] * 2


def test_chicago_and_new_york_stamps_collapse_to_one_bar(config):
    writer.write_ohlcv(_daily(["2026-10-06 04:00", "2026-10-07 04:00"], [15.0, 15.1]), config)
    writer.write_ohlcv(_daily(["2026-10-07 05:00", "2026-10-08 05:00"], [15.2, 15.4]), config)
    with schema.connect(config, persistent=False) as conn:
        df = reader.get_ohlcv(conn, "^VIX", "1d")
    assert len(df) == 3
    assert df["close"].tolist() == [15.0, 15.2, 15.4]  # the later write won Oct 7
    assert (df["ts"].dt.tz_convert(schema.NY).dt.hour == 0).all()


def test_existing_duplicates_collapse_on_next_write(config):
    path = writer._series_path(config, "1d", "^VIX")
    path.parent.mkdir(parents=True)
    _daily(["2026-10-07 04:00", "2026-10-07 05:00"], [15.08, 15.08]).to_parquet(path, index=False)
    writer.write_ohlcv(_daily(["2026-10-08 05:00"], [15.41]), config)
    stored = pd.read_parquet(path)
    assert len(stored) == 2 and stored["ts"].is_unique


def test_intraday_stamps_are_untouched(config):
    bars = _daily(["2026-10-07 13:30", "2026-10-07 14:30"], [1.0, 2.0], symbol="SPY")
    bars["interval"] = "1h"
    writer.write_ohlcv(bars, config)
    with schema.connect(config, persistent=False) as conn:
        df = reader.get_ohlcv(conn, "SPY", "1h")
    assert df["ts"].tolist() == list(
        pd.to_datetime(["2026-10-07 13:30", "2026-10-07 14:30"], utc=True)
    )


def test_reads_never_double_a_session_even_from_a_bad_file(config):
    path = writer._series_path(config, "1d", "^VIX")
    path.parent.mkdir(parents=True)
    _daily(
        ["2026-10-06 04:00", "2026-10-07 04:00", "2026-10-07 05:00"], [15.0, 15.1, 15.2]
    ).to_parquet(path, index=False)  # written before the fix
    with schema.connect(config, persistent=False) as conn:
        df = reader.get_ohlcv(conn, "^VIX", "1d")
    assert len(df) == 2 and df["ts"].is_unique
    assert df["close"].tolist() == [15.0, 15.2]  # the later stamp wins
    closes = pd.Series(df["close"].to_numpy(), index=df["ts"].dt.tz_convert(schema.NY).dt.date)
    assert closes.index.is_unique
