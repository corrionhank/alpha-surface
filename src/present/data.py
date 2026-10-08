"""What every page reads: the shared DuckDB connection, and live market data for any symbol.

Pages never query a provider directly. They call bars(), quote() and metrics() here, which go
through collector.feed: stored history topped up live and written through, the live tastytrade
mark, and tastytrade's IV metrics. Each is cached briefly so reruns and several open tabs do
not multiply provider calls, and each degrades to what is stored when a provider is down.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import time as dtime

import pandas as pd
import streamlit as st

from config import load_config
from storage import schema

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
    """Upper-case, trimmed; Yahoo's ^ for indices is kept (^VIX) and added for bare index names
    the store already uses that way."""
    sym = (symbol or "").strip().upper()
    return f"^{sym}" if sym in {"VIX", "VIX3M", "VIX1D", "VIX9D", "VIX6M", "VVIX", "VXN", "SKEW", "IRX"} else sym


@st.cache_data(ttl=300, show_spinner="Loading bars...")
def bars(symbol: str, interval: str = "1d") -> pd.DataFrame:
    """Bars for any symbol: stored history, topped up live and written through. A symbol never
    seen before is backfilled once. Empty when the provider does not know the symbol."""
    from collector import feed

    return feed.bars(clean(symbol), interval, config=config, background=True)


def closes(symbol: str, live: bool = True) -> pd.Series:
    """Daily closes by New York date, with today's live mark as the last point when available."""
    df = bars(symbol, "1d")
    if df.empty:
        return pd.Series(dtype=float)
    dates = df["ts"].dt.tz_convert(ET).dt.date
    s = pd.Series(df["close"].to_numpy(), index=dates)
    return with_live(s, symbol) if live else s


@st.cache_data(ttl=15, show_spinner=False)
def quotes(symbols: tuple[str, ...]) -> dict[str, dict]:
    """Live marks for many symbols in one streamer call, keyed as given. Missing when the feed
    is off or does not carry a symbol."""
    from collector import feed

    return feed.quotes([clean(s) for s in symbols]) | {}


def quote(symbol: str) -> dict | None:
    """Live mark, prior close, bid and ask (tastytrade), or None when there is no live feed."""
    return quotes((clean(symbol),)).get(clean(symbol))


def market_open(now: pd.Timestamp | None = None) -> bool:
    """Regular US equity session, 09:30 to 16:00 ET on weekdays. Exchange holidays are not
    checked, so a holiday weekday reads as open."""
    now = now or pd.Timestamp.now(tz=ET)
    return now.weekday() < 5 and dtime(9, 30) <= now.time() < dtime(16, 0)


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
    from collector import feed, tasty
    from storage import reference

    sym = clean(symbol).lstrip("^")
    try:
        stored = reference.read("market_metrics", config, "WHERE symbol = ?", [sym])
    except Exception:
        stored = pd.DataFrame()
    if not stored.empty:
        last = stored.iloc[-1]
        if pd.Timestamp.now(tz="UTC") - pd.Timestamp(last["collected_at"]) < pd.Timedelta(minutes=15):
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
    from collector import feed

    def run():
        for sym in symbols:
            try:
                feed.bars(sym, interval, config=config)
            except Exception:
                log.warning("top-up of %s failed", sym, exc_info=True)

    threading.Thread(target=run, daemon=True, name="top-up").start()
    return pd.Timestamp.now(tz="UTC")
