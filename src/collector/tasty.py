"""tastytrade connection: one session per process, read-only calls only.

The SDK is async; Streamlit and the CLI are not. One daemon thread owns an event loop and the
Session, and callers hand it work. One process means one session and one token refresh every
~15 minutes, which is what the API asks for.

Quotes come from the DXLink streamer, not REST: one connection per process, kept open, with a
live cache of the latest Quote, Trade and Summary per symbol. A request subscribes only to what
is not cached yet, waits briefly for the first events, and reads the cache. (The REST snapshot,
/market-data/by-type, answers 403 for this account.)

Limits this respects (developer.tastytrade.com, rate limits and backoff):
  - No published REST quota; bursts get 429 with no headers. At most CONCURRENCY requests in
    flight, and 429 / 5xx / network errors back off exponentially with jitter, MAX_TRIES at most.
  - Too many failed logins block the IP for about 8 hours. A failed token refresh is never
    retried: the client stops and reports it until the process restarts.
  - DXLink: 5 sessions per credential set (this uses one per process), 25,000 subscriptions per
    session (capped at MAX_SYMBOLS x 3 event types here, oldest dropped first), 10,000
    subscription changes a minute (sent in batches of SUB_BATCH).

Read endpoints only. Nothing here imports or calls order entry (Development principle 3).
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import threading
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from config import Tastytrade, load_config

log = logging.getLogger(__name__)
logging.getLogger("tastytrade").setLevel(logging.WARNING)  # the SDK logs every frame at DEBUG
logging.getLogger("httpx").setLevel(logging.WARNING)

CONCURRENCY = 4
MAX_TRIES = 4
MAX_SYMBOLS = 4000  # x3 event types stays far under DXLink's 25,000 per session
SUB_BATCH = 500  # symbols per subscription message, so no message is "too long"


class NotConfigured(RuntimeError):
    """No credentials in .env, or the last sign-in failed."""


class _Retry(Exception):
    def __init__(self, status: int, url: str):
        super().__init__(f"HTTP {status} from {url}")
        self.status = status


async def _check(response: httpx.Response) -> None:
    """httpx response hook: turn throttling and server errors into a retryable exception before
    the SDK tries to parse them."""
    if response.status_code == 429 or response.status_code >= 500:
        raise _Retry(response.status_code, response.request.url.path)


class _Client:
    def __init__(self, creds: Tastytrade):
        self._loop = asyncio.new_event_loop()
        threading.Thread(target=self._loop.run_forever, daemon=True, name="tastytrade").start()
        self._sem: asyncio.Semaphore | None = None
        self._session = self.run(self._open(creds))
        self.stream = _Stream(self)

    async def _open(self, creds: Tastytrade):
        from tastytrade import Session

        self._sem = asyncio.Semaphore(CONCURRENCY)
        session = Session(creds.client_secret, creds.refresh_token, is_test=creds.sandbox,
                          timeout=20, event_hooks={"response": [_check]})
        await session.refresh()  # fail here, once, rather than inside every later call
        return session

    def run(self, coro: Awaitable[Any], timeout: float = 90) -> Any:
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    async def call(self, fn: Callable[..., Awaitable[Any]], *args: Any, **kwargs: Any) -> Any:
        """fn(session, *args) under the concurrency cap, with backoff on throttling."""
        assert self._sem is not None
        for attempt in range(1, MAX_TRIES + 1):
            try:
                async with self._sem:
                    return await fn(self._session, *args, **kwargs)
            except (_Retry, httpx.TransportError) as exc:
                if attempt == MAX_TRIES:
                    raise
                wait = min(8.0, 0.5 * 2 ** (attempt - 1)) * (0.5 + random.random())
                log.warning("tastytrade %s, retry %d in %.1fs", exc, attempt, wait)
                await asyncio.sleep(wait)
        raise AssertionError("unreachable")


_lock = threading.Lock()
_client: _Client | None = None
_failed: str | None = None


def ready() -> bool:
    """Credentials present and no failed sign-in so far in this process."""
    return load_config().tastytrade.ready and _failed is None


def client() -> _Client:
    global _client, _failed
    if _client is not None:
        return _client
    with _lock:
        if _client is not None:
            return _client
        if _failed is not None:
            raise NotConfigured(f"tastytrade sign-in failed earlier, not retrying: {_failed}")
        creds = load_config().tastytrade
        if not creds.ready:
            raise NotConfigured("set TASTYTRADE_CLIENT_SECRET and TASTYTRADE_REFRESH_TOKEN in .env")
        try:
            _client = _Client(creds)
        except Exception as exc:  # do not retry a refresh grant: repeated failures block the IP
            _failed = f"{type(exc).__name__}: {exc}"[:200]
            raise NotConfigured(f"tastytrade sign-in failed: {_failed}") from exc
    return _client


def _gather(calls: list[Awaitable[Any]]) -> list[Any]:
    async def go():
        return await asyncio.gather(*calls)
    return client().run(go())


def metrics(symbols: list[str]) -> list:
    """Market metrics (IV rank and percentile, IVx, HV, per-expiry IV) for the symbols."""
    from tastytrade.metrics import get_market_metrics

    c = client()
    chunks = [symbols[i:i + 50] for i in range(0, len(symbols), 50)]
    return [m for part in _gather([c.call(get_market_metrics, ch) for ch in chunks]) for m in part]


def nested_chain(symbol: str) -> list:
    """Every listed expiry and strike, with option symbols. Definitions, not quotes."""
    from tastytrade.instruments import NestedOptionChain

    c = client()
    return c.run(c.call(NestedOptionChain.get, symbol))


def level() -> str:
    """Market-data level the quote token carries, e.g. 'demo' or real-time. Cached per process."""
    global _level
    if _level is None:
        c = client()

        async def fetch(session):
            return (await session._get("/api-quote-tokens")).get("level", "unknown")
        _level = str(c.run(c.call(fetch)))
    return _level


_level: str | None = None


def stream_quotes(symbols: list[str], wait: float = 3.0) -> dict[str, dict]:
    """Latest bid, ask, last, day volume, open interest and prior close per streamer symbol.

    Symbols are dxfeed streamer symbols: SPY, VIX, or .SPY261016C700 for an option (the nested
    chain lists them). Waits up to `wait` seconds for symbols seen for the first time; anything
    still silent after that is left out.
    """
    c = client()
    return c.run(c.stream.snapshot(list(dict.fromkeys(symbols)), wait), timeout=wait + 60)


def _f(x) -> float:
    return math.nan if x is None else float(x)


class _Stream:
    """One DXLink connection and a cache of the latest event of each kind per symbol."""

    def __init__(self, owner: _Client):
        self.owner = owner
        self.cache: dict[str, dict[str, Any]] = {}
        self.order: dict[str, None] = {}  # subscribed symbols, oldest first
        self.streamer = None
        self.task: asyncio.Task | None = None
        self.up: asyncio.Event | None = None
        self.fails = 0

    async def _run(self) -> None:
        from tastytrade import DXLinkStreamer
        from tastytrade.dxfeed import Quote, Summary, Trade

        try:
            async with DXLinkStreamer(self.owner._session) as streamer:
                self.streamer, self.fails = streamer, 0
                if self.order:  # resubscribe after a reconnect
                    await self._subscribe(list(self.order))
                self.up.set()
                await asyncio.gather(*(self._pump(streamer, cls) for cls in (Quote, Trade, Summary)))
        except Exception as exc:  # dropped connection: the next snapshot reconnects, backed off
            self.fails += 1
            log.warning("tastytrade streamer stopped: %s", exc)
        finally:
            self.streamer = None
            self.up = None

    async def _pump(self, streamer, cls) -> None:
        name = cls.__name__
        async for event in streamer.listen(cls):
            self.cache.setdefault(event.event_symbol, {})[name] = event

    async def _subscribe(self, symbols: list[str]) -> None:
        from tastytrade.dxfeed import Quote, Summary, Trade

        for i in range(0, len(symbols), SUB_BATCH):
            part = symbols[i:i + SUB_BATCH]
            for cls in (Quote, Trade, Summary):
                await self.streamer.subscribe(cls, part, refresh_interval=0.5)

    async def _trim(self) -> None:
        from tastytrade.dxfeed import Quote, Summary, Trade

        extra = len(self.order) - MAX_SYMBOLS
        if extra <= 0:
            return
        drop = list(self.order)[:extra]
        for cls in (Quote, Trade, Summary):
            await self.streamer.unsubscribe(cls, drop)
        for sym in drop:
            self.order.pop(sym, None)
            self.cache.pop(sym, None)

    async def _ensure_up(self) -> None:
        if self.streamer is not None:
            return
        if self.task is None or self.task.done():
            if self.fails:
                await asyncio.sleep(min(30.0, 2.0 ** self.fails))
            self.up = asyncio.Event()
            self.task = asyncio.create_task(self._run())
        await asyncio.wait_for(self.up.wait(), timeout=20)

    async def snapshot(self, symbols: list[str], wait: float) -> dict[str, dict]:
        await self._ensure_up()
        new = [s for s in symbols if s not in self.order]
        for sym in symbols:  # most recently used goes to the back
            self.order.pop(sym, None)
            self.order[sym] = None
        if new:
            await self._subscribe(new)
            deadline = asyncio.get_running_loop().time() + wait
            while asyncio.get_running_loop().time() < deadline:
                if all("Quote" in self.cache.get(s, {}) for s in new):
                    break
                await asyncio.sleep(0.1)
            await asyncio.sleep(0.3)  # let Trade and Summary land behind the Quote
            await self._trim()
        return {s: _row(self.cache[s]) for s in symbols if s in self.cache}


def mark(row: dict) -> float:
    """Mid of a two-sided market; else the last trade, the session close, the prior close."""
    bid, ask = row["bid"], row["ask"]
    if bid == bid and ask == ask and bid > 0 and ask >= bid:
        return (bid + ask) / 2
    for x in (row["last"], row["day_close"], row["prev_close"]):
        if x == x and x > 0:
            return x
    return math.nan


def _row(events: dict[str, Any]) -> dict:
    q, t, m = events.get("Quote"), events.get("Trade"), events.get("Summary")
    return {
        "bid": _f(q.bid_price) if q else math.nan,
        "ask": _f(q.ask_price) if q else math.nan,
        "last": _f(t.price) if t else math.nan,
        "volume": _f(t.day_volume) if t and t.day_volume is not None else 0.0,
        "last_time": t.time if t else None,
        "open_interest": float(m.open_interest) if m and m.open_interest is not None else 0.0,
        "prev_close": _f(m.prev_day_close_price) if m else math.nan,
        "day_close": _f(m.day_close_price) if m else math.nan,
    }
