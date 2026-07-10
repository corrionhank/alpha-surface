"""Parquet append helpers with upsert (dedup) semantics.

Data volume is tiny (hourly bars), so each write does a read-modify-write on the
affected day partitions: concat, drop duplicates on the primary key keeping the
freshest row, rewrite. This makes collector retries idempotent — re-running never
accumulates duplicates and refreshes the still-forming latest bar.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from config import Config
from storage.schema import OHLCV_COLUMNS, PK_OHLCV


def _partition_path(config: Config, ts: pd.Timestamp) -> Path:
    return (
        config.parquet_dir
        / "ohlcv"
        / f"year={ts.year}"
        / f"month={ts.month}"
        / f"day={ts.day}"
        / "data.parquet"
    )


def write_ohlcv(df: pd.DataFrame, config: Config) -> int:
    """Append OHLCV rows to their day partitions, deduped on (ts, symbol, interval).

    Returns the number of rows handed in (post-normalization, pre-dedup)."""
    if df is None or df.empty:
        return 0

    df = df.loc[:, OHLCV_COLUMNS].copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["volume"] = df["volume"].fillna(0).astype("int64")
    df = df.dropna(subset=["open", "high", "low", "close"])
    if df.empty:
        return 0

    for (year, month, day), part in df.groupby(
        [df["ts"].dt.year, df["ts"].dt.month, df["ts"].dt.day], sort=False
    ):
        path = _partition_path(config, pd.Timestamp(year=year, month=month, day=day, tz="UTC"))
        path.parent.mkdir(parents=True, exist_ok=True)

        combined = pd.read_parquet(path) if path.exists() else None
        combined = pd.concat([combined, part], ignore_index=True) if combined is not None else part
        combined = (
            combined.drop_duplicates(subset=PK_OHLCV, keep="last")
            .sort_values("ts")
            .reset_index(drop=True)
        )
        combined.to_parquet(path, index=False)

    return len(df)
