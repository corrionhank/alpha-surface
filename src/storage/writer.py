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

import duckdb
import numpy as np
import pandas as pd

from config import Config
from storage.schema import CHAIN_COLUMNS, OHLCV_COLUMNS, PK_CHAIN, PK_OHLCV


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
    return (config.parquet_dir / table / f"year={ts.year}" / f"month={ts.month}" / f"day={ts.day}")


def _series_path(config: Config, interval: str, symbol: str) -> Path:
    return config.parquet_dir / "ohlcv" / interval / f"{symbol.replace('/', '_')}.parquet"


def _write_series(config: Config, interval: str, symbol: str, part: pd.DataFrame) -> None:
    """Merge rows into one series file. Caller holds the ohlcv lock."""
    path = _series_path(config, interval, symbol)
    path.parent.mkdir(parents=True, exist_ok=True)
    combined = pd.concat([pd.read_parquet(path), part], ignore_index=True) if path.exists() else part
    combined = (
        combined.drop_duplicates(subset=PK_OHLCV, keep="last").sort_values("ts").reset_index(drop=True)
    )
    tmp = path.with_suffix(".tmp")  # write then rename, so a reader never sees half a file
    combined.to_parquet(tmp, index=False)
    tmp.replace(path)


def write_ohlcv(df: pd.DataFrame, config: Config) -> int:
    """Upsert rows into their series files, deduped on (ts, symbol, interval). Returns rows in."""
    if df is None or df.empty:
        return 0

    df = df.loc[:, OHLCV_COLUMNS].copy()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df["volume"] = df["volume"].fillna(0).astype("int64")
    df = df.dropna(subset=["open", "high", "low", "close"])
    if df.empty:
        return 0

    with locked(config.parquet_dir / "ohlcv" / ".lock"):
        for (interval, symbol), part in df.groupby(["interval", "symbol"], sort=False):
            _write_series(config, interval, symbol, part)

    return len(df)


def compact_ohlcv(config: Config) -> dict:
    """One-off move from the old day-partition layout to one file per series.

    Every stored bar, in either layout, is merged into ohlcv/<interval>/<symbol>.parquet; files
    in any other layout are then moved, not deleted, to data/backup/. Safe to re-run.
    """
    root = config.parquet_dir / "ohlcv"
    with locked(root / ".lock"):
        stray = [f for f in root.rglob("*.parquet") if len(f.relative_to(root).parts) != 2]
        if not stray:
            return {"moved": 0, "series": 0}
        def read(files: list[Path]) -> pd.DataFrame:
            if not files:
                return pd.DataFrame(columns=OHLCV_COLUMNS)
            listed = ", ".join("'" + str(f).replace("'", "''") + "'" for f in files)
            return duckdb.sql(f"SELECT {', '.join(OHLCV_COLUMNS)} FROM read_parquet([{listed}], "
                              "hive_partitioning=false, union_by_name=true)").df()

        current = [f for f in root.rglob("*.parquet") if len(f.relative_to(root).parts) == 2]
        # Old rows first, so where both layouts hold a bar the series file's (newer) copy wins.
        bars = pd.concat([read(stray), read(current)], ignore_index=True)
        bars["ts"] = pd.to_datetime(bars["ts"], utc=True)
        groups = bars.groupby(["interval", "symbol"], sort=False)
        for (interval, symbol), part in groups:
            path = _series_path(config, interval, symbol)
            if path.exists():
                path.unlink()  # rebuilt from the full read above, which already includes it
            _write_series(config, interval, symbol, part)
        backup = config.data_dir / "backup" / f"ohlcv-day-partitions-{pd.Timestamp.now():%Y%m%d-%H%M%S}"
        for f in stray:
            dest = backup / f.relative_to(root)
            dest.parent.mkdir(parents=True, exist_ok=True)
            f.replace(dest)
        for d in sorted((p for p in root.rglob("*") if p.is_dir()), key=lambda p: -len(p.parts)):
            if not any(d.iterdir()):
                d.rmdir()
    return {"moved": len(stray), "series": groups.ngroups, "rows": len(bars), "backup": str(backup)}


def append_chain(chain: pd.DataFrame, source: str, config: Config,
                 collected_at: pd.Timestamp | None = None) -> Path | None:
    """Store one pull as a new file. Returns its path, or None for an empty pull.

    chain follows collector.chains.CHAIN_COLUMNS (extras optional). collected_at defaults to the
    pull's own capture time, so the stored row says when the quote was true, not when it landed.
    """
    if chain is None or chain.empty:
        return None
    out = pd.DataFrame(index=chain.index)
    ts = collected_at if collected_at is not None else pd.Timestamp(chain["ts"].iloc[0])
    out["collected_at"] = pd.Timestamp(ts).tz_convert("UTC") if pd.Timestamp(ts).tzinfo else pd.Timestamp(ts, tz="UTC")
    out["source"] = source
    for col in CHAIN_COLUMNS[2:]:
        out[col] = chain[col] if col in chain else np.nan
    out["expiry"] = out["expiry"].astype(str)
    out["kind"] = out["kind"].astype(str)
    for col in ("strike", "bid", "ask", "last", "volume", "open_interest", "underlying",
                "underlying_prev", "change"):
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
