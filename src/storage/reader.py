"""Query helpers over the ohlcv view."""

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
    conn: duckdb.DuckDBPyConnection, symbol: str, interval: str = "1h", tail: int | None = None
) -> pd.DataFrame:
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


def previous_chain(
    conn: duckdb.DuckDBPyConnection, symbols: list[str], before, source: str | None = None,
    lookback_days: float = 4.0,
) -> pd.DataFrame:
    """The latest stored quote for every contract of these symbols strictly before `before`,
    within lookback_days: what a scan compares against. Per contract rather than per pull, since
    a page may have stored one expiry at a time. Empty when nothing was stored yet."""
    if not symbols:
        return pd.DataFrame()
    before = pd.Timestamp(before)
    marks = ", ".join("?" for _ in symbols)
    src = "AND source = ?" if source else ""
    params = [*symbols, before, before - pd.Timedelta(days=lookback_days), *([source] if source else [])]
    return conn.execute(
        f"""
        SELECT * FROM option_chain
        WHERE symbol IN ({marks}) AND collected_at < ? AND collected_at >= ? {src}
        QUALIFY row_number() OVER (
            PARTITION BY symbol, expiry, strike, kind ORDER BY collected_at DESC) = 1
        """,
        params,
    ).df()


def chain_pulls(conn: duckdb.DuckDBPyConnection) -> pd.DataFrame:
    """One row per stored pull: when, from where, which symbol, how many contracts."""
    return conn.execute(
        "SELECT collected_at, source, symbol, count(*) AS contracts FROM option_chain "
        "GROUP BY ALL ORDER BY collected_at DESC"
    ).df()
