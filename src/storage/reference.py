"""Reference data store: ETF profiles, holdings, news and the economic calendar.

Same shape as the chain store: every fetch is its own new Parquet file inside a day partition,
named by time and a random id, so concurrent writers (two sessions, a session and the CLI) never
touch the same file and nothing is read back on write. Duplicates are dropped at read time.
Read with a private in-memory DuckDB connection, so these reads never contend with the page's
shared connection or its views.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import duckdb
import pandas as pd

from config import Config

TABLES = ("etf_profile", "etf_holdings", "news", "econ_calendar", "market_metrics", "iv_term")


def _dir(config: Config, table: str) -> Path:
    if table not in TABLES:
        raise ValueError(f"unknown reference table {table!r}")
    return config.parquet_dir / table


def append(df: pd.DataFrame, table: str, config: Config) -> Path | None:
    """Store one fetch as a new file. df must carry collected_at (UTC). None for an empty frame."""
    if df is None or df.empty:
        return None
    stamp = pd.Timestamp(df["collected_at"].iloc[0])
    stamp = stamp.tz_convert("UTC") if stamp.tzinfo else stamp.tz_localize("UTC")
    folder = _dir(config, table) / f"year={stamp.year}" / f"month={stamp.month}" / f"day={stamp.day}"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{stamp:%H%M%S%f}-{uuid.uuid4().hex[:12]}.parquet"
    tmp = path.with_suffix(".tmp")
    df.to_parquet(tmp, index=False)
    tmp.replace(path)  # rename, so a reader never sees half a file
    return path


def _glob(config: Config, table: str) -> str | None:
    root = _dir(config, table)
    if not root.exists() or not any(root.rglob("*.parquet")):
        return None
    return str(root / "**" / "*.parquet").replace("'", "''")


def read(table: str, config: Config, where: str = "", params: list | None = None) -> pd.DataFrame:
    """Every stored row of a table, oldest first. Empty frame when nothing is stored."""
    glob = _glob(config, table)
    if glob is None:
        return pd.DataFrame()
    sql = (f"SELECT * FROM read_parquet('{glob}', union_by_name=true, hive_partitioning=false) "
           f"{where} ORDER BY collected_at")
    with duckdb.connect() as conn:
        conn.execute("SET TimeZone='UTC'")
        return conn.execute(sql, params or []).df()


def latest(table: str, config: Config, by: str | None = None) -> pd.DataFrame:
    """Rows of the most recent fetch, per value of `by` when given (e.g. per fund)."""
    glob = _glob(config, table)
    if glob is None:
        return pd.DataFrame()
    part = f"PARTITION BY {by}" if by else ""
    sql = (f"SELECT * FROM read_parquet('{glob}', union_by_name=true, hive_partitioning=false) "
           f"QUALIFY collected_at = max(collected_at) OVER ({part})")
    with duckdb.connect() as conn:
        conn.execute("SET TimeZone='UTC'")
        return conn.execute(sql).df()


def last_collected(table: str, config: Config) -> pd.Timestamp | None:
    glob = _glob(config, table)
    if glob is None:
        return None
    with duckdb.connect() as conn:
        conn.execute("SET TimeZone='UTC'")
        value = conn.execute(
            f"SELECT max(collected_at) FROM read_parquet('{glob}', union_by_name=true, "
            "hive_partitioning=false)"
        ).fetchone()[0]
    return None if value is None else pd.Timestamp(value).tz_convert("UTC")
