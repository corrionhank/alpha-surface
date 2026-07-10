"""DuckDB connection + view registration over the Parquet lake.

Raw data lives in hive-partitioned Parquet (``data/parquet/{table}/year=/month=/day=``);
DuckDB views read it back. See ``docs/schema.md`` for the table DDL.

Read consumers (frontend, terminal, tests) should use ``persistent=False`` to get an
in-memory connection — it re-globs the Parquet on every query and never takes the
file lock, so it can't collide with a running collector.
"""

from __future__ import annotations

import duckdb

from config import Config

# Columns that make up the ohlcv table, in order (matches docs/schema.md).
OHLCV_COLUMNS = ["ts", "symbol", "interval", "open", "high", "low", "close", "volume"]
PK_OHLCV = ["ts", "symbol", "interval"]

_OHLCV_EMPTY_VIEW = """
CREATE OR REPLACE VIEW ohlcv AS
SELECT
    CAST(NULL AS TIMESTAMPTZ) AS ts,
    CAST(NULL AS VARCHAR)     AS symbol,
    CAST(NULL AS VARCHAR)     AS interval,
    CAST(NULL AS DOUBLE)      AS open,
    CAST(NULL AS DOUBLE)      AS high,
    CAST(NULL AS DOUBLE)      AS low,
    CAST(NULL AS DOUBLE)      AS close,
    CAST(NULL AS BIGINT)      AS volume
WHERE FALSE
"""


def ohlcv_glob(config: Config) -> str:
    return str(config.parquet_dir / "ohlcv" / "**" / "*.parquet")


def _has_parquet(config: Config) -> bool:
    root = config.parquet_dir / "ohlcv"
    return root.exists() and any(root.rglob("*.parquet"))


def ensure_views(conn: duckdb.DuckDBPyConnection, config: Config) -> None:
    """(Re)create the ohlcv view. Falls back to an empty typed view before any
    data has been collected so the frontend can render an empty state cleanly."""
    if _has_parquet(config):
        cols = ", ".join(OHLCV_COLUMNS)
        glob = ohlcv_glob(config).replace("'", "''")  # CREATE VIEW can't bind params
        conn.execute(
            f"CREATE OR REPLACE VIEW ohlcv AS "
            f"SELECT {cols} FROM read_parquet('{glob}', hive_partitioning=true)"
        )
    else:
        conn.execute(_OHLCV_EMPTY_VIEW)


def connect(config: Config, *, persistent: bool = True) -> duckdb.DuckDBPyConnection:
    """Open a connection with views registered.

    persistent=True  -> the on-disk market.duckdb (writable; used by the collector).
    persistent=False -> in-memory (used by read consumers; no file lock).
    """
    if persistent:
        config.data_dir.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(config.db_path))
    else:
        conn = duckdb.connect()
    ensure_views(conn, config)
    return conn
