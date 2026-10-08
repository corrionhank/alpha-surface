"""DuckDB connection and views over the Parquet store. Table DDL: docs/schema.md."""

from __future__ import annotations

import duckdb

from config import Config

OHLCV_COLUMNS = ["ts", "symbol", "interval", "open", "high", "low", "close", "volume"]
PK_OHLCV = ["ts", "symbol", "interval"]

# Raw option quotes as the gateway (collector.feed) stored them: provider contract columns plus
# when and from where. Nothing derived; implied vol is solved at read time.
CHAIN_COLUMNS = [
    "collected_at", "source", "symbol", "expiry", "strike", "kind", "bid", "ask", "last",
    "volume", "open_interest", "underlying", "underlying_prev", "change", "last_trade",
]
PK_CHAIN = ["collected_at", "source", "symbol", "expiry", "strike", "kind"]
CHAIN_TYPES = {
    "collected_at": "TIMESTAMPTZ", "source": "VARCHAR", "symbol": "VARCHAR", "expiry": "VARCHAR",
    "strike": "DOUBLE", "kind": "VARCHAR", "bid": "DOUBLE", "ask": "DOUBLE", "last": "DOUBLE",
    "volume": "DOUBLE", "open_interest": "DOUBLE", "underlying": "DOUBLE",
    "underlying_prev": "DOUBLE", "change": "DOUBLE", "last_trade": "TIMESTAMPTZ",
}

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


def chain_glob(config: Config) -> str:
    return str(config.parquet_dir / "option_chain" / "**" / "*.parquet")


def _has_parquet(config: Config, table: str = "ohlcv") -> bool:
    root = config.parquet_dir / table
    return root.exists() and any(root.rglob("*.parquet"))


def _chain_view(config: Config) -> str:
    """Every stored pull, one row per contract per pull. Each pull is its own file, so a retried
    write can leave the same rows twice; the window keeps one per primary key at read time."""
    if not _has_parquet(config, "option_chain"):
        cols = ", ".join(f"CAST(NULL AS {t}) AS {c}" for c, t in CHAIN_TYPES.items())
        return f"CREATE OR REPLACE VIEW option_chain AS SELECT {cols} WHERE FALSE"
    cols = ", ".join(f"CAST({c} AS {t}) AS {c}" for c, t in CHAIN_TYPES.items())
    glob = chain_glob(config).replace("'", "''")
    pk = ", ".join(PK_CHAIN)
    return (
        f"CREATE OR REPLACE VIEW option_chain AS SELECT {cols} FROM read_parquet('{glob}', "
        f"hive_partitioning=true, union_by_name=true) "
        f"QUALIFY row_number() OVER (PARTITION BY {pk}) = 1"
    )


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
    conn.execute(_chain_view(config))


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
