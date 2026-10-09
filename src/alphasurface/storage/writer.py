"""Parquet writes.

ohlcv: upsert. One file per series, ohlcv/<interval>/<symbol>.parquet, because bars are read a
symbol at a time; day partitions left thousands of tiny files for every query to open.
Read-modify-write with dedup on the primary key, under a file lock so two writers (a page and
the CLI, say) cannot interleave a read and a write of the same file.

option_chain: append-only. Every pull is its own new file inside its day partition, named by
time and a random id, so concurrent writers never touch the same file and nothing is ever
re-read on write. Duplicates from a retried write are dropped at read time by the view.
"""

from __future__ import annotations

import fcntl
import uuid
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pandas as pd

from alphasurface.config import Config
from alphasurface.storage.schema import (
    CHAIN_COLUMNS,
    OHLCV_COLUMNS,
    PK_CHAIN,
    PK_OHLCV,
    normalize_daily,
    session_dates,
)


@contextmanager
def locked(path: Path):
    """Exclusive advisory lock across processes and threads (each open is its own lock)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _partition_dir(config: Config, table: str, ts: pd.Timestamp) -> Path:
    return config.parquet_dir / table / f"year={ts.year}" / f"month={ts.month}" / f"day={ts.day}"


def _series_path(config: Config, interval: str, symbol: str) -> Path:
    return config.parquet_dir / "ohlcv" / interval / f"{symbol.replace('/', '_')}.parquet"


def _write_series(config: Config, interval: str, symbol: str, part: pd.DataFrame) -> None:
    """Merge rows into one series file. Caller holds the ohlcv lock.

    Incoming rows win over stored ones on the same key. Daily series are re-keyed to the New
    York session date first, stored rows included, so a series holds one bar per session even
    if an older write stamped it differently.
    """
    path = _series_path(config, interval, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined = (
        pd.concat([pd.read_parquet(path), part], ignore_index=True) if path.exists() else part
    )
    if interval == "1d":
        combined = combined.assign(ts=session_dates(combined["ts"]))
    combined = (
        combined.drop_duplicates(subset=PK_OHLCV, keep="last")
        .sort_values("ts")
        .reset_index(drop=True)
    )
    tmp = path.with_suffix(".tmp")  # write then rename, so a reader never sees half a file
    combined.to_parquet(tmp, index=False)
    tmp.replace(path)


def write_ohlcv(df: pd.DataFrame, config: Config) -> int:
    """Upsert rows into their series files, deduped on (ts, symbol, interval), daily bars keyed
    by New York session date (schema.session_dates). Returns rows in."""
    if df is None or df.empty:
        return 0

    df = normalize_daily(df.loc[:, OHLCV_COLUMNS].copy())
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["volume"] = df["volume"].fillna(0).astype("int64")
    df = df.dropna(subset=["open", "high", "low", "close"])
    if df.empty:
        return 0

    with locked(config.parquet_dir / "ohlcv" / ".lock"):
        for (interval, symbol), part in df.groupby(["interval", "symbol"], sort=False):
            _write_series(config, interval, symbol, part)

    return len(df)


def append_chain(
    chain: pd.DataFrame, source: str, config: Config, collected_at: pd.Timestamp | None = None
) -> Path | None:
    """Store one pull as a new file. Returns its path, or None for an empty pull.

    chain follows collector.chains.CHAIN_COLUMNS (extras optional). collected_at defaults to the
    pull's own capture time, so the stored row says when the quote was true, not when it landed.
    """
    if chain is None or chain.empty:
        return None
    out = pd.DataFrame(index=chain.index)
    ts = collected_at if collected_at is not None else pd.Timestamp(chain["ts"].iloc[0])
    out["collected_at"] = (
        pd.Timestamp(ts).tz_convert("UTC")
        if pd.Timestamp(ts).tzinfo
        else pd.Timestamp(ts, tz="UTC")
    )
    out["source"] = source
    for col in CHAIN_COLUMNS[2:]:
        out[col] = chain.get(col, np.nan)
    out["expiry"] = out["expiry"].astype(str)
    out["kind"] = out["kind"].astype(str)
    for col in (
        "strike",
        "bid",
        "ask",
        "last",
        "volume",
        "open_interest",
        "underlying",
        "underlying_prev",
        "change",
    ):
        out[col] = pd.to_numeric(out[col], errors="coerce").astype("float64")
    out["last_trade"] = pd.to_datetime(out["last_trade"], utc=True, errors="coerce")
    out = out.drop_duplicates(subset=PK_CHAIN, keep="last")

    stamp = out["collected_at"].iloc[0]
    folder = _partition_dir(config, "option_chain", stamp)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stamp:%H%M%S%f}-{uuid.uuid4().hex[:12]}.parquet"
    tmp = path.with_suffix(".tmp")
    out[CHAIN_COLUMNS].to_parquet(tmp, index=False)
    tmp.replace(path)
    return path
