"""DuckDB connection and views over the Parquet store. Table DDL: docs/schema.md."""

from __future__ import annotations

import duckdb

from config import Config

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
    if _has_parquet(config):
        cols = ", ".join(OHLCV_COLUMNS)
        glob = ohlcv_glob(config).replace("'", "''")  # CREATE VIEW cannot bind params
        conn.execute(
            f"CREATE OR REPLACE VIEW ohlcv AS "
            f"SELECT {cols} FROM read_parquet('{glob}', hive_partitioning=true)"
        )
    else:
        conn.execute(_OHLCV_EMPTY_VIEW)  # typed empty view before any data exists


def connect(config: Config, *, persistent: bool = True) -> duckdb.DuckDBPyConnection:
    """persistent=True opens market.duckdb (writable); False is in-memory with no file lock."""
    if persistent:
        config.data_dir.mkdir(parents=True, exist_ok=True)
        conn = duckdb.connect(str(config.db_path))
    else:
        conn = duckdb.connect()
    conn.execute("SET TimeZone='UTC'")
    ensure_views(conn, config)
    return conn
