"""What every page reads: the shared DuckDB connection, and live market data for any symbol.

Pages never query a provider directly. They call bars(), quote() and metrics() here, which go
through collector.feed: stored history topped up live and written through, the live tastytrade
mark, and tastytrade's IV metrics. Each is cached briefly so reruns and several open tabs do
not multiply provider calls, and each degrades to what is stored when a provider is down.
"""

from __future__ import annotations

import logging
import math
import threading
import time

import pandas as pd
import streamlit as st

from alphasurface import clock, symbols
from alphasurface.config import load_config
from alphasurface.storage import schema

log = logging.getLogger(__name__)
config = load_config()
ET = "America/New_York"


@st.cache_resource
def _connect():
    # In-memory: no file lock against a running collector; views re-glob Parquet per query.
    return schema.connect(config, persistent=False)


def conn():
    # A cursor per script run: the cached connection is shared across sessions and DuckDB
    # connections are not safe for concurrent queries. Cursors share the catalog but not
    # session state, so the timezone is set again here.
    c = _connect().cursor()
    c.execute("SET TimeZone='UTC'")
    _refresh_views(c)
    return c


_views_lock = threading.Lock()
_views_at = 0.0
VIEW_TTL = 30  # seconds; the collector writes hourly at most


def _refresh_views(c) -> None:
    """Re-glob the Parquet so newly collected data appears. Views live in the catalog every
    cursor shares, so two sessions replacing them at once is a DuckDB write-write conflict:
    serialize the refresh and skip it while the last one is fresh."""
    global _views_at
    with _views_lock:
        if time.monotonic() - _views_at < VIEW_TTL:
            return
        schema.ensure_views(c, config)
        _views_at = time.monotonic()


# --- Live market data for any symbol ------------------------------------------------------------


def clean(symbol: str) -> str:
    """The stored spelling of any input (alphasurface.symbols): vix -> ^VIX, SPX -> ^GSPC, /ES -> ES=F."""
    return symbols.to_store(symbol)


@st.cache_data(ttl=300, show_spinner="Loading bars...")
def bars(symbol: str, interval: str = "1d") -> pd.DataFrame:
    """Bars for any symbol: stored history, topped up live and written through. A symbol never
    seen before is backfilled once. Empty when the provider does not know the symbol."""
    from alphasurface.collector import feed

    return feed.bars(clean(symbol), interval, config=config, background=True)


def closes(symbol: str, live: bool = True) -> pd.Series:
    """Daily closes by New York date, with today's live mark as the last point when available."""
    df = bars(symbol, "1d")
    if df.empty:
        return pd.Series(dtype=float)
    dates = df["ts"].dt.tz_convert(ET).dt.date
    s = pd.Series(df["close"].to_numpy(), index=dates)
    s = s[~s.index.duplicated(keep="last")]  # one close per session, even from a bad file
    return with_live(s, symbol) if live else s


@st.cache_data(ttl=15, show_spinner=False)
def quotes(symbols: tuple[str, ...]) -> dict[str, dict]:
    """Live marks for many symbols in one streamer call, keyed as given. Missing when the feed
    is off or does not carry a symbol."""
    from alphasurface.collector import feed

    return feed.quotes([clean(s) for s in symbols]) | {}


def quote(symbol: str) -> dict | None:
    """Live mark, prior close, bid and ask (tastytrade), or None when there is no live feed."""
    return quotes((clean(symbol),)).get(clean(symbol))


def market_open(now: pd.Timestamp | None = None) -> bool:
    """Inside the regular NYSE session, holidays and 13:00 early closes honored (alphasurface.clock)."""
    return clock.is_open(now)


def with_live(series: pd.Series, symbol: str, live: dict[str, dict] | None = None) -> pd.Series:
    """A date-indexed close series with today's live mark as its last point, during the regular
    session only: outside it the official close stands, so an after-hours quote never
    overwrites a close. Pass `live` (from quotes()) to overlay many series with one call."""
    if series.empty or not market_open():
        return series
    q = (live or {}).get(clean(symbol)) if live is not None else quote(symbol)
    if q is None:
        return series
    out = series.copy()
    out.loc[pd.Timestamp.now(tz=ET).date()] = q["last"]  # replaces today's bar or appends it
    return out


@st.cache_data(ttl=600, show_spinner=False)
def metrics(symbol: str) -> dict | None:
    """tastytrade IV metrics for one symbol (IVx, IV rank and percentile, HV30, earnings):
    the stored pull when under 15 minutes old, else a live pull through the gateway."""
    from alphasurface.collector import feed, tasty
    from alphasurface.storage import reference

    sym = symbols.to_tasty(symbol)
    try:
        stored = reference.latest(
            "market_metrics", config, by="symbol", where="WHERE symbol = ?", params=[sym]
        )
    except Exception:
        stored = pd.DataFrame()
    if not stored.empty:
        last = stored.iloc[-1]
        if pd.Timestamp.now(tz="UTC") - pd.Timestamp(last["collected_at"]) < pd.Timedelta(
            minutes=15
        ):
            return last.to_dict()
    if tasty.ready():
        try:
            frame, _ = feed.metrics([sym], config=config)
            if not frame.empty:
                return frame.iloc[0].to_dict()
        except Exception:
            log.warning("metrics for %s unavailable", sym, exc_info=True)
    return stored.iloc[-1].to_dict() if not stored.empty else None


@st.cache_data(ttl=1800, show_spinner=False)
def top_up(symbols: tuple[str, ...], interval: str = "1d") -> pd.Timestamp:
    """Refresh stored bars for these symbols in the background, at most every 30 minutes, so a
    page that reads the store in one fast query still sees today's bars without waiting."""
    from alphasurface.collector import feed

    def run():
        for sym in symbols:
            try:
                feed.bars(sym, interval, config=config)
            except Exception:
                log.warning("top-up of %s failed", sym, exc_info=True)

    threading.Thread(target=run, daemon=True, name="top-up").start()
    return pd.Timestamp.now(tz="UTC")


# --- Feed, rates, implied vol and instruments (collector.feed does the work) ---------------


@st.cache_data(ttl=300, show_spinner=False)
def feed_label() -> str:
    """'tastytrade real-time', 'tastytrade delayed', 'tastytrade', or '' without a feed."""
    from alphasurface.collector import feed

    return feed.feed_label()


@st.cache_data(ttl=3600, show_spinner=False)
def rate_source() -> tuple[float, str]:
    """Risk-free rate as a decimal and its source: tastytrade, the 13-week T-bill, or 4%."""
    from alphasurface.collector import feed

    return feed.risk_free_rate(config=config)


def rate() -> float:
    """Annual risk-free rate as a decimal. See rate_source()."""
    return rate_source()[0]


@st.cache_data(ttl=3600, show_spinner=False)
def dividend_yield(symbol: str) -> float:
    """Annual dividend yield as a decimal (tastytrade metrics), 0.0 when unknown."""
    from alphasurface.collector import feed

    try:
        return feed.dividend_yield(symbol, config=config)
    except Exception:
        log.warning("dividend yield for %s unavailable", symbol, exc_info=True)
        return 0.0


@st.cache_data(ttl=300, show_spinner=False)
def implied_vol(symbol: str, days: int) -> tuple[float, str]:
    """Implied vol for a horizon in days, decimal, and its source: tastytrade IV at the nearest
    expiry, IVx, VIX or VXN, 21-day realized vol. (nan, "") when nothing is available."""
    from alphasurface.collector import feed

    try:
        return feed.horizon_iv(symbol, days, config=config)
    except Exception:
        log.warning("implied vol for %s unavailable", symbol, exc_info=True)
        return math.nan, ""


@st.cache_data(ttl=60, show_spinner=False)
def metrics_table(symbol_list: tuple[str, ...]) -> pd.DataFrame:
    """tastytrade metrics, one row per symbol (the latest of each), missing or stale symbols
    pulled live in one call. Use this, not a table-wide latest(), for any multi-symbol view."""
    from alphasurface.collector import feed

    try:
        return feed.latest_metrics(list(symbol_list), config=config)
    except Exception:
        log.warning("metrics table unavailable", exc_info=True)
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def search(phrase: str) -> list[tuple[str, str]]:
    """(symbol, description) matches for a phrase: built-in indices and futures, then tastytrade."""
    from alphasurface.collector import feed

    return feed.search(phrase)


@st.cache_data(ttl=86400, show_spinner=False)
def describe(symbol: str) -> str:
    """A symbol's name, or '' when no source knows it."""
    from alphasurface.collector import feed

    try:
        return feed.describe(symbol, config=config)
    except Exception:
        log.warning("no description for %s", symbol, exc_info=True)
        return ""


def resolve(symbol: str) -> str | None:
    """The stored spelling of a symbol some provider knows, or None. Never backfills: use it to
    validate a symbol before adding it anywhere."""
    from alphasurface.collector import feed

    try:
        return feed.resolve(symbol, config=config)
    except Exception:
        log.warning("could not resolve %s", symbol, exc_info=True)
        return None


def ensure_daily(symbol_list: tuple[str, ...], timeout: float = 20.0) -> list[str]:
    """Backfill daily history for symbols with none stored, waiting at most `timeout` seconds,
    so a first run renders instead of stopping. Returns the symbols still missing."""
    from concurrent.futures import ThreadPoolExecutor, wait

    from alphasurface.collector import feed
    from alphasurface.storage import reader

    have = set(reader.available_symbols(conn(), "1d"))
    missing = [s for s in dict.fromkeys(clean(x) for x in symbol_list) if s not in have]
    if not missing:
        return []
    pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="backfill")
    jobs = {pool.submit(feed.bars, s, "1d", config=config): s for s in missing}
    done, _ = wait(jobs, timeout=timeout)
    pool.shutdown(wait=False)
    ok = {jobs[f] for f in done if f.exception() is None and not f.result().empty}
    if ok:
        bars.clear()
        global _views_at
        _views_at = 0.0  # new series files: re-glob on the next query
    return [s for s in missing if s not in ok]
