"""Market-data gateway: the one way provider data enters the app.

    provider (collector.chains, yfinance bars)
        -> feed
            -> the caller, at once (analysis in memory, on the spot)
            -> Parquet + DuckDB (option_chain, ohlcv), append-only, for backtests later

Every pull a page, the scanner or the CLI makes comes back immediately and is also written to
the global store, stamped with when it was true and where it came from. Storing never breaks
the caller: a failed write is logged and the data is returned anyway. Synthetic chains are
never stored, so the store only ever holds real quotes. tastytrade chains come through chain()
like any provider; its market metrics through metrics().
"""

from __future__ import annotations

import logging
import threading

import pandas as pd

from collector.chains import get_provider
from config import Config, load_config
from storage import reader, schema, writer

log = logging.getLogger(__name__)

NOT_STORED = {"synthetic"}  # made-up quotes stay out of the store


def expirations(source: str, symbol: str) -> list[str]:
    """Listed expiries. Metadata, not market data, so nothing is stored."""
    return list(get_provider(source).expirations(symbol))


def chain(source: str, symbol: str, expiries: list[str] | None = None, *,
          config: Config | None = None, store: bool = True) -> pd.DataFrame:
    """Raw quotes for these expiries, returned now and appended to option_chain."""
    frame = get_provider(source).chain(symbol, expiries)
    if store and source not in NOT_STORED:
        store_chain(frame, source, config)
    return frame


def store_chain(frame: pd.DataFrame, source: str, config: Config | None = None) -> None:
    try:
        writer.append_chain(frame, source, config or load_config())
    except Exception:  # the page keeps working; the pull is only missing from history
        log.warning("could not store %s chain pull", source, exc_info=True)


def metrics(symbols: list[str], *, config: Config | None = None,
            store: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """tastytrade market metrics (per symbol) and per-expiry IV (per symbol and expiry),
    returned now and appended to market_metrics and iv_term."""
    from collector import tasty
    from collector.tastytrade_collector import metrics_frames
    from storage import reference

    frame, term = metrics_frames(tasty.metrics(symbols), pd.Timestamp.now(tz="UTC"))
    if store:
        config = config or load_config()
        for table, df in (("market_metrics", frame), ("iv_term", term)):
            try:
                reference.append(df, table, config)
            except Exception:  # the caller still gets the numbers; only history misses a pull
                log.warning("could not store %s", table, exc_info=True)
    return frame, term


# Per interval: (top-up window when the stored history is recent, first backfill, "recent" age)
_BARS = {"1d": ("1mo", "10y", pd.Timedelta(days=25)), "1h": ("5d", "2y", pd.Timedelta(days=4))}


def bars(symbol: str, interval: str = "1d", *, config: Config | None = None, conn=None,
         background: bool = False) -> pd.DataFrame:
    """OHLC bars for any symbol: stored history topped up live from yfinance, new bars written
    through. A symbol never seen before is backfilled once (10 years daily, 2 years hourly, the
    most Yahoo serves); after that only the last few sessions are fetched. Empty for a symbol
    the provider does not know. background=True writes on a thread so a page is not held up by
    a first backfill; a CLI should leave it False so the write lands before exit.
    """
    from collector.yfinance_collector import fetch_ohlcv

    top_up, first, recent_age = _BARS[interval]
    config = config or load_config()
    own = conn is None
    conn = conn or schema.connect(config, persistent=False)
    try:
        stored = reader.get_ohlcv(conn, symbol, interval)
    finally:
        if own:
            conn.close()

    recent = not stored.empty and pd.Timestamp.now(tz="UTC") - stored["ts"].max() < recent_age
    period = top_up if recent and len(stored) >= 30 else first
    try:
        fresh = fetch_ohlcv(symbol, interval, period)
    except Exception:
        log.warning("could not fetch %s bars for %s", interval, symbol, exc_info=True)
        fresh = pd.DataFrame(columns=schema.OHLCV_COLUMNS)

    if not fresh.empty:
        if background:
            threading.Thread(target=_store_bars, args=(fresh, config), daemon=True).start()
        else:
            _store_bars(fresh, config)

    out = pd.concat([stored, fresh], ignore_index=True) if not fresh.empty else stored
    if out.empty:
        return out
    out["ts"] = pd.to_datetime(out["ts"], utc=True)
    return out.drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)


def daily(symbol: str, *, config: Config | None = None, conn=None, years: int = 10,
          background: bool = False) -> pd.DataFrame:
    """Daily bars, live-topped and written through. See bars()."""
    return bars(symbol, "1d", config=config, conn=conn, background=background)


def quotes(symbols: list[str]) -> dict[str, dict]:
    """Live mark, prior close, bid and ask per symbol from the tastytrade streamer, in one call.
    Empty without credentials or when the feed is down; a symbol the streamer does not carry
    is simply missing. Yahoo-style index symbols (^VIX) are mapped to the streamer's (VIX)."""
    from collector import tasty

    if not tasty.ready() or not symbols:
        return {}
    try:
        rows = tasty.stream_quotes([s.lstrip("^") for s in symbols], wait=3.0)
        source = f"tastytrade {tasty.level()} feed"
    except Exception:
        log.warning("live quotes unavailable", exc_info=True)
        return {}
    now = pd.Timestamp.now(tz="UTC")
    out = {}
    for sym in symbols:
        row = rows.get(sym.lstrip("^"))
        mark = tasty.mark(row) if row else float("nan")
        if mark == mark:
            out[sym] = {"last": mark, "prev": row["prev_close"], "bid": row["bid"],
                        "ask": row["ask"], "at": now, "source": source}
    return out


def quote(symbol: str) -> dict | None:
    """One symbol's live quote, or None. See quotes()."""
    return quotes([symbol]).get(symbol)


def _store_bars(frame: pd.DataFrame, config: Config) -> None:
    try:
        writer.write_ohlcv(frame, config)
    except Exception:
        log.warning("could not store bars", exc_info=True)
