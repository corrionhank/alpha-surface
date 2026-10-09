"""Query helpers over the ohlcv view."""

from __future__ import annotations

import duckdb
import pandas as pd

from alphasurface.storage.schema import session_dates

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
    """One symbol's bars, oldest first. Daily bars come back one per New York session, the
    later stamp winning, whatever the files hold: the write path keys them that way, and this
    keeps a bad file from ever doubling a day on a page."""
    df = conn.execute(
        f"{_SELECT} WHERE symbol = ? AND interval = ? ORDER BY ts", [symbol, interval]
    ).df()
    if interval == "1d" and not df.empty:
        df = (
            df.assign(ts=session_dates(df["ts"]))
            .drop_duplicates("ts", keep="last")
            .reset_index(drop=True)
        )
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
    conn: duckdb.DuckDBPyConnection,
    symbols: list[str],
    before,
    source: str | None = None,
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
    params = [
        *symbols,
        before,
        before - pd.Timedelta(days=lookback_days),
        *([source] if source else []),
    ]
    return conn.execute(
        f"""
        SELECT * FROM option_chain
        WHERE symbol IN ({marks}) AND collected_at < ? AND collected_at >= ? {src}
        QUALIFY row_number() OVER (
            PARTITION BY symbol, expiry, strike, kind ORDER BY collected_at DESC) = 1
        """,
        params,
    ).df()
