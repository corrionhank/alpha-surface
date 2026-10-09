"""Market-data gateway: the one way provider data enters the app.

    provider (tastytrade, collector.chains, yfinance bars)
        -> feed
            -> the caller, at once (analysis in memory, on the spot)
            -> Parquet + DuckDB (option_chain, ohlcv, reference tables), for backtests later

Every pull a page, the scanner or the CLI makes comes back immediately and is also written to
the global store, stamped with when it was true and where it came from. Storing never breaks
the caller: a failed write is logged and the data is returned anyway. Synthetic chains are
never stored, so the store only ever holds real quotes.

tastytrade is the primary source wherever it has the data: live quotes, intraday candles,
market metrics, the risk-free rate, instrument names. Yahoo backs daily history and stands in
for intraday bars without credentials. Symbols are converted through alphasurface.symbols, so ^GSPC, SPX
and /ES each reach the right series and the right live quote.
"""

from __future__ import annotations

import logging
import math
import threading

import pandas as pd

from alphasurface import clock
from alphasurface.collector.chains import get_provider
from alphasurface.config import Config, load_config
from alphasurface.storage import reader, schema, writer
from alphasurface.symbols import display, kind, to_store, to_streamer, to_tasty

log = logging.getLogger(__name__)

NOT_STORED = {"synthetic"}  # made-up quotes stay out of the store
METRICS_MAX_AGE = pd.Timedelta(minutes=15)  # a stored metrics pull younger than this is current
IV_MAX_AGE = pd.Timedelta(days=1)  # older stored IV is not used for a horizon


# --- Units ---------------------------------------------------------------------------------


def as_fraction(value: float, reference: float = math.nan) -> float:
    """A rate or yield reported without documented units, as a decimal. Picks whichever of
    value or value/100 is closer to a reference when there is one; else reads anything under
    0.25 as already decimal, since no rate or dividend yield here runs to 25%."""
    if value is None or value != value:
        return math.nan
    v = float(value)
    if reference == reference and reference is not None:
        return min((v, v / 100), key=lambda c: abs(c - reference))
    return v if abs(v) < 0.25 else v / 100


# --- Feed status ---------------------------------------------------------------------------


def feed_label() -> str:
    """'tastytrade real-time', 'tastytrade delayed', 'tastytrade' when the account's delay flag
    cannot be read, or '' without credentials."""
    from alphasurface.collector import tasty

    if not tasty.ready():
        return ""
    try:
        delayed = tasty.feed_status()["delayed"]
    except Exception:
        log.warning("feed status unavailable", exc_info=True)
        return ""
    return {True: "tastytrade delayed", False: "tastytrade real-time"}.get(delayed, "tastytrade")


# --- Chains --------------------------------------------------------------------------------


def expirations(source: str, symbol: str) -> list[str]:
    """Listed expiries. Metadata, not market data, so nothing is stored."""
    return list(get_provider(source).expirations(symbol))


def chain(
    source: str,
    symbol: str,
    expiries: list[str] | None = None,
    *,
    config: Config | None = None,
    store: bool = True,
) -> pd.DataFrame:
    """Raw quotes for these expiries, returned now and appended to option_chain. A tastytrade
    chain carries frame.attrs["coverage"], the share of subscribed contracts that quoted."""
    frame = get_provider(source).chain(symbol, expiries)
    if store and source not in NOT_STORED:
        store_chain(frame, source, config)
    return frame


def store_chain(frame: pd.DataFrame, source: str, config: Config | None = None) -> None:
    try:
        writer.append_chain(frame, source, config or load_config())
    except Exception:  # the page keeps working; the pull is only missing from history
        log.warning("could not store %s chain pull", source, exc_info=True)


# --- Market metrics ------------------------------------------------------------------------


def metrics(
    symbols: list[str], *, config: Config | None = None, store: bool = True
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """tastytrade market metrics (per symbol) and per-expiry IV (per symbol and expiry),
    returned now and appended to market_metrics and iv_term. Symbols in tastytrade spelling."""
    from alphasurface.collector import tasty
    from alphasurface.collector.tastytrade_collector import metrics_frames
    from alphasurface.storage import reference

    frame, term = metrics_frames(tasty.metrics(symbols), pd.Timestamp.now(tz="UTC"))
    if store:
        config = config or load_config()
        for table, df in (("market_metrics", frame), ("iv_term", term)):
            try:
                reference.append(df, table, config)
            except Exception:  # the caller still gets the numbers; only history misses a pull
                log.warning("could not store %s", table, exc_info=True)
    return frame, term


def _latest(table: str, config: Config, symbols: list[str]) -> pd.DataFrame:
    from alphasurface.storage import reference

    if not symbols:
        return pd.DataFrame()
    marks = ", ".join("?" * len(symbols))
    try:
        return reference.latest(
            table, config, by="symbol", where=f"WHERE symbol IN ({marks})", params=list(symbols)
        )
    except Exception:
        log.warning("could not read %s", table, exc_info=True)
        return pd.DataFrame()


def latest_metrics(
    symbols: list[str], *, config: Config | None = None, max_age: pd.Timedelta = METRICS_MAX_AGE
) -> pd.DataFrame:
    """One row per symbol: the latest stored metrics, with every missing or stale symbol pulled
    live in a single call first when tastytrade is connected. Symbols in any spelling; the
    frame's symbol column is tastytrade's (SPX, not ^GSPC)."""
    from alphasurface.collector import tasty

    config = config or load_config()
    wanted = list(dict.fromkeys(to_tasty(s) for s in symbols if s))
    stored = _latest("market_metrics", config, wanted)
    now = pd.Timestamp.now(tz="UTC")
    fresh = set()
    if not stored.empty:
        age = now - pd.to_datetime(stored["collected_at"], utc=True)
        fresh = set(stored.loc[age < max_age, "symbol"])
    todo = [s for s in wanted if s not in fresh]
    if todo and tasty.ready():
        try:
            live, _ = metrics(todo, config=config)
        except Exception:
            log.warning("metrics for %s unavailable", ",".join(todo), exc_info=True)
            live = pd.DataFrame()
        if not live.empty:
            stored = pd.concat(
                [
                    stored[~stored["symbol"].isin(live["symbol"])] if not stored.empty else stored,
                    live,
                ],
                ignore_index=True,
            )
    if stored.empty:
        return stored
    order = {s: i for i, s in enumerate(wanted)}
    return stored.sort_values("symbol", key=lambda c: c.map(order)).reset_index(drop=True)


def _stored_close(symbol: str, config: Config, conn=None) -> float:
    own = conn is None
    conn = conn or schema.connect(config, persistent=False)
    try:
        bar = reader.latest_bar(conn, to_store(symbol), "1d")
    except Exception:
        bar = None
    finally:
        if own:
            conn.close()
    return float(bar["close"]) if bar is not None else math.nan


def risk_free_rate(*, config: Config | None = None, conn=None) -> tuple[float, str]:
    """Annual risk-free rate as a decimal, and where it came from: tastytrade's published rate,
    else the stored 13-week T-bill yield (^IRX), else 4%."""
    from alphasurface.collector import tasty

    config = config or load_config()
    irx = _stored_close("^IRX", config, conn) / 100
    if tasty.ready():
        try:
            return as_fraction(tasty.risk_free_rate(), irx), "tastytrade"
        except Exception:
            log.warning("tastytrade risk-free rate unavailable", exc_info=True)
    if irx == irx:
        return irx, "13-week T-bill"
    return 0.04, "default"


def dividend_yield(symbol: str, *, config: Config | None = None, conn=None) -> float:
    """Annual dividend yield as a decimal from tastytrade metrics, 0.0 when unknown. The
    reported yield's units are checked against the dividend per share over the last close."""
    config = config or load_config()
    df = latest_metrics([symbol], config=config, max_age=pd.Timedelta(days=1))
    if df.empty or "dividend_yield" not in df:
        return 0.0
    row = df.iloc[0]
    rate = row.get("dividend_rate_per_share", math.nan)
    spot = _stored_close(symbol, config, conn)
    ref = rate / spot if rate == rate and spot == spot and spot > 0 else math.nan
    y = as_fraction(row["dividend_yield"], ref)
    return y if y == y and y >= 0 else 0.0


def horizon_iv(
    symbol: str,
    days: int,
    *,
    config: Config | None = None,
    conn=None,
    now: pd.Timestamp | None = None,
) -> tuple[float, str]:
    """Implied vol for a horizon `days` out, decimal, and its source. In order: tastytrade's IV
    at the listed expiry nearest the horizon, tastytrade IVx, VIX (SPY) or VXN (QQQ), 21-day
    realized vol. (nan, "") when none is available."""
    from alphasurface.derive.market_state import rolling_vol

    config = config or load_config()
    now = now or pd.Timestamp.now(tz="UTC")
    sym = to_tasty(symbol)
    metrics_row = latest_metrics([sym], config=config)
    term = _latest("iv_term", config, [sym])
    if not term.empty:
        term = term[now - pd.to_datetime(term["collected_at"], utc=True) < IV_MAX_AGE]
        today = now.tz_convert(clock.NY).tz_localize(None).normalize()
        exp = pd.to_datetime(term["expiry"])
        term = term[(exp >= today) & (term["iv"] > 0)]
        if not term.empty:
            target = today + pd.Timedelta(days=max(days, 0))
            gap = (pd.to_datetime(term["expiry"]) - target).abs()
            best = term.loc[gap.idxmin()]
            return float(best["iv"]), f"tastytrade IV, {pd.Timestamp(best['expiry']):%b %-d} expiry"
    if not metrics_row.empty:
        row = metrics_row.iloc[0]
        age = now - pd.Timestamp(row["collected_at"]).tz_convert("UTC")
        if (
            age < IV_MAX_AGE
            and row.get("ivx", math.nan) == row.get("ivx", math.nan)
            and row["ivx"] > 0
        ):
            return float(row["ivx"]), "tastytrade IVx"
    index = {"SPY": "^VIX", "QQQ": "^VXN"}.get(display(symbol))
    if index:
        level = _stored_close(index, config, conn)
        if level == level:
            return level / 100, display(index)
    own = conn is None
    conn = conn or schema.connect(config, persistent=False)
    try:
        closes = reader.get_ohlcv(conn, to_store(symbol), "1d", tail=30)["close"]
    finally:
        if own:
            conn.close()
    if len(closes) > 22:
        return float(rolling_vol(closes).iloc[-1]) / 100, "realized vol, 21D"
    return math.nan, ""


# --- Bars ----------------------------------------------------------------------------------

# Yahoo, per interval: (top-up window when the stored history is recent, first backfill,
# "recent" age). 5m stays at five sessions either way.
_BARS = {
    "1d": ("1mo", "10y", pd.Timedelta(days=25)),
    "1h": ("5d", "2y", pd.Timedelta(days=4)),
    "5m": ("5d", "5d", pd.Timedelta(days=2)),
}
# tastytrade candles: the most sessions one request may reach back (Development principle 4).
CANDLE_SESSIONS = {"5m": 5, "1h": 30}


def _candle_frame(events: list, symbol: str, interval: str) -> pd.DataFrame:
    if not events:
        return pd.DataFrame(columns=schema.OHLCV_COLUMNS)
    return pd.DataFrame(
        {
            "ts": pd.to_datetime([e.time for e in events], unit="ms", utc=True),
            "symbol": symbol,
            "interval": interval,
            "open": [float(e.open) for e in events],
            "high": [float(e.high) for e in events],
            "low": [float(e.low) for e in events],
            "close": [float(e.close) for e in events],
            "volume": [int(e.volume or 0) for e in events],
        }
    )


def candles(
    symbol: str,
    interval: str,
    *,
    stored: pd.DataFrame | None = None,
    now: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Intraday bars from tastytrade candles, in the ohlcv schema under the stored symbol.
    Reaches back CANDLE_SESSIONS[interval] sessions at most, and only from the last stored bar
    when the series is already current. Empty without credentials, for an interval candles do
    not serve here, or when the feed has nothing."""
    from alphasurface.collector import tasty

    sym = to_store(symbol)
    if interval not in CANDLE_SESSIONS or not tasty.ready():
        return pd.DataFrame(columns=schema.OHLCV_COLUMNS)
    streamer = to_streamer(sym)
    if not streamer:
        return pd.DataFrame(columns=schema.OHLCV_COLUMNS)
    market = "future" if kind(sym) == "future" else "equity"
    start = clock.sessions_back(CANDLE_SESSIONS[interval], now, market)
    if stored is not None and not stored.empty:
        start = max(start, pd.to_datetime(stored["ts"], utc=True).max())
    try:
        events = tasty.candles(streamer, interval, start.to_pydatetime())
    except Exception:
        log.warning("tastytrade %s candles for %s unavailable", interval, sym, exc_info=True)
        return pd.DataFrame(columns=schema.OHLCV_COLUMNS)
    return _candle_frame(events, sym, interval)


def bars(
    symbol: str,
    interval: str = "1d",
    *,
    config: Config | None = None,
    conn=None,
    background: bool = False,
) -> pd.DataFrame:
    """OHLC bars for any symbol, stored history topped up live and new bars written through.

    5m and 1h come from tastytrade candles when connected (a few sessions at most, see
    candles()), else Yahoo. 1d is Yahoo history: a symbol never seen before is backfilled once
    (10 years), after that only the last few sessions are fetched. Empty for a symbol no
    provider knows. background=True writes on a thread so a page is not held up by a first
    backfill; a CLI should leave it False so the write lands before exit.
    """
    from alphasurface.collector.yfinance_collector import fetch_ohlcv

    sym = to_store(symbol)
    top_up, first, recent_age = _BARS[interval]
    config = config or load_config()
    own = conn is None
    conn = conn or schema.connect(config, persistent=False)
    try:
        stored = reader.get_ohlcv(conn, sym, interval)
    finally:
        if own:
            conn.close()

    fresh = candles(sym, interval, stored=stored)
    if fresh.empty:
        recent = not stored.empty and pd.Timestamp.now(tz="UTC") - stored["ts"].max() < recent_age
        period = top_up if recent and len(stored) >= 30 else first
        try:
            fresh = fetch_ohlcv(sym, interval, period)
        except Exception:
            log.warning("could not fetch %s bars for %s", interval, sym, exc_info=True)
            fresh = pd.DataFrame(columns=schema.OHLCV_COLUMNS)

    if not fresh.empty:
        if background:
            threading.Thread(target=_store_bars, args=(fresh, config), daemon=True).start()
        else:
            _store_bars(fresh, config)

    out = pd.concat([stored, fresh], ignore_index=True) if not fresh.empty else stored
    if out.empty:
        return out
    out = schema.normalize_daily(out)
    out["ts"] = pd.to_datetime(out["ts"], utc=True)
    return out.drop_duplicates("ts", keep="last").sort_values("ts").reset_index(drop=True)


def daily(
    symbol: str,
    *,
    config: Config | None = None,
    conn=None,
    years: int = 10,
    background: bool = False,
) -> pd.DataFrame:
    """Daily bars, live-topped and written through. See bars()."""
    return bars(symbol, "1d", config=config, conn=conn, background=background)


def _store_bars(frame: pd.DataFrame, config: Config) -> None:
    try:
        writer.write_ohlcv(frame, config)
    except Exception:
        log.warning("could not store bars", exc_info=True)


# --- Quotes --------------------------------------------------------------------------------


def quotes(symbols: list[str]) -> dict[str, dict]:
    """Live mark, prior close, bid and ask per symbol from the tastytrade streamer, in one call,
    keyed as given. Empty without credentials or when the feed is down; a symbol the streamer
    does not carry is simply missing. Any spelling works: ^VIX, SPX, /ES (front month)."""
    from alphasurface.collector import tasty

    if not tasty.ready() or not symbols:
        return {}
    wanted = {sym: to_streamer(sym) for sym in symbols}
    streamers = [s for s in wanted.values() if s]
    if not streamers:
        return {}
    try:
        rows = tasty.stream_quotes(streamers, wait=3.0)
    except Exception:
        log.warning("live quotes unavailable", exc_info=True)
        return {}
    source = feed_label() or "tastytrade"
    now = pd.Timestamp.now(tz="UTC")
    out = {}
    for sym, streamer in wanted.items():
        row = rows.get(streamer) if streamer else None
        mark = tasty.mark(row) if row else math.nan
        if mark == mark:
            out[sym] = {
                "last": mark,
                "prev": row["prev_close"],
                "bid": row["bid"],
                "ask": row["ask"],
                "at": now,
                "source": source,
            }
    return out


def quote(symbol: str) -> dict | None:
    """One symbol's live quote, or None. See quotes()."""
    return quotes([symbol]).get(symbol)


# --- Instruments ---------------------------------------------------------------------------


def search(phrase: str) -> list[tuple[str, str]]:
    """(symbol, description) matches: built-in indices and futures roots first, then
    tastytrade's symbol search. Empty without credentials beyond the built-ins."""
    from alphasurface import symbols as sy
    from alphasurface.collector import tasty

    q = (phrase or "").strip().upper()
    if not q:
        return []
    builtin = [
        (d, desc)
        for d, desc in [(sy.INDICES[s][0], sy.INDICES[s][1]) for s in sy.INDICES]
        + list(sy.FUTURES.items())
        if d.lstrip("/").startswith(q.lstrip("/^"))
    ]
    found: list[tuple[str, str]] = []
    if tasty.ready():
        try:
            found = tasty.search(q)
        except Exception:
            log.warning("symbol search for %r failed", q, exc_info=True)
    return list(dict.fromkeys(builtin + found))


def describe(symbol: str, *, config: Config | None = None) -> str:
    """A symbol's name: built in for indices and futures, else the stored instruments row,
    else tastytrade (written through to the instruments table). Empty when unknown."""
    from alphasurface import symbols as sy
    from alphasurface.collector import tasty
    from alphasurface.storage import reference

    name = sy.describe(symbol)
    if name:
        return name
    config = config or load_config()
    sym = to_tasty(symbol)
    stored = _latest("instruments", config, [sym])
    if not stored.empty and str(stored.iloc[-1]["description"] or ""):
        return str(stored.iloc[-1]["description"])
    if not tasty.ready():
        return ""
    try:
        exact = [d for s, d in tasty.search(sym) if s.upper() == sym]
        name = (
            exact[0] if exact else (tasty.equity_description(sym) if kind(sym) == "equity" else "")
        )
    except Exception:
        log.warning("no description for %s", sym, exc_info=True)
        return ""
    if name:
        row = pd.DataFrame(
            [
                {
                    "collected_at": pd.Timestamp.now(tz="UTC"),
                    "source": "tastytrade",
                    "symbol": sym,
                    "description": name,
                    "kind": kind(sym),
                }
            ]
        )
        try:
            reference.append(row, "instruments", config)
        except Exception:
            log.warning("could not store instrument %s", sym, exc_info=True)
    return name


def resolve(symbol: str, *, config: Config | None = None, conn=None) -> str | None:
    """The stored spelling of a symbol some provider knows, or None, without backfilling it:
    a built-in index or future, a symbol with stored daily bars, an exact tastytrade search
    match, or without tastytrade a five-day Yahoo probe that is not stored."""
    from alphasurface import symbols as sy
    from alphasurface.collector import tasty
    from alphasurface.collector.yfinance_collector import fetch_ohlcv

    sym = to_store(symbol)
    if not sym:
        return None
    if sy.describe(sym):
        return sym
    config = config or load_config()
    own = conn is None
    conn = conn or schema.connect(config, persistent=False)
    try:
        if reader.latest_bar(conn, sym, "1d") is not None:
            return sym
    finally:
        if own:
            conn.close()
    if tasty.ready():
        try:
            hits = tasty.search(to_tasty(sym))
        except Exception:
            log.warning("symbol search for %s failed", sym, exc_info=True)
            hits = []
        if any(s.upper() == to_tasty(sym) for s, _ in hits):
            return sym
        if hits:
            return None  # tastytrade answered and does not list it
    try:
        probe = fetch_ohlcv(sym, "1d", "5d")
    except Exception:
        return None
    return sym if not probe.empty else None
