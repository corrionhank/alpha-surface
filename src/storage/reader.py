"""DuckDB query helpers over the ohlcv view.

All functions take a live connection (see ``storage.schema.connect``). At current
data volume it's cheap to pull a symbol's full series and slice in pandas.
"""

from __future__ import annotations

import duckdb
import pandas as pd

_SELECT = "SELECT ts, symbol, interval, open, high, low, close, volume FROM ohlcv"


def available_symbols(conn: duckdb.DuckDBPyConnection, interval: str | None = None) -> list[str]:
    if interval:
        rows = conn.execute(
            "SELECT DISTINCT symbol FROM ohlcv WHERE interval = ? ORDER BY symbol", [interval]
        ).fetchall()
    else:
        rows = conn.execute("SELECT DISTINCT symbol FROM ohlcv ORDER BY symbol").fetchall()
    return [r[0] for r in rows]


def get_ohlcv(
    conn: duckdb.DuckDBPyConnection,
    symbol: str,
    interval: str = "1h",
    tail: int | None = None,
) -> pd.DataFrame:
    """Return a symbol's bars ordered oldest→newest; ``tail`` keeps the last N."""
    df = conn.execute(
        f"{_SELECT} WHERE symbol = ? AND interval = ? ORDER BY ts", [symbol, interval]
    ).df()
    if tail is not None and len(df) > tail:
        df = df.tail(tail).reset_index(drop=True)
    return df


def latest_bar(
    conn: duckdb.DuckDBPyConnection, symbol: str, interval: str = "1h"
) -> pd.Series | None:
    df = conn.execute(
        f"{_SELECT} WHERE symbol = ? AND interval = ? ORDER BY ts DESC LIMIT 1", [symbol, interval]
    ).df()
    return None if df.empty else df.iloc[0]
