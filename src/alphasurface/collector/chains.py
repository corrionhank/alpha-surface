"""Options chain providers.

This is the seam. The pages talk to a ChainProvider (through collector.feed) and know nothing
about where the quotes came from. Three are registered:

    tastytrade  real-time quotes from a funded account (collector.tasty, read-only)
    yfinance    free, delayed; bid and ask read zero outside market hours
    synthetic   a deterministic surface for development and tests, never stored

A provider implements expirations(symbol), spot(symbol), quote(symbol) -> (last, prior close)
and chain(symbol, expirations) returning CHAIN_COLUMNS (plus any EXTRA_COLUMNS), one row per
contract: raw quotes, no derived fields. Implied vol is not the provider's job. Vendors publish IV
from their own model with their own rate and dividend assumptions, and yfinance in particular
reports 0.00001 for anything illiquid. We solve it ourselves in derive/, from mid prices, so the
number is ours and its assumptions are visible.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

import numpy as np
import pandas as pd

CHAIN_COLUMNS = [
    "ts",  # when the quote was captured, UTC
    "symbol",  # underlying
    "expiry",  # YYYY-MM-DD
    "strike",
    "kind",  # call | put
    "bid",
    "ask",
    "last",
    "volume",
    "open_interest",
    "underlying",  # spot at capture time
]

# Optional extras a provider may add after CHAIN_COLUMNS. Consumers must not require them: a
# provider without them simply leaves them out, and readers fill NaN.
EXTRA_COLUMNS = [
    "underlying_prev",  # the underlying's prior session close
    "change",  # the option's last print minus its prior close, as the vendor reports it
    "last_trade",  # when the option last traded, UTC
]


class ChainUnavailable(RuntimeError):
    """A chain cannot be built right now; the message says why, in words a page can show."""


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=CHAIN_COLUMNS)


def _today() -> pd.Timestamp:
    """Naive UTC date. Expiries are calendar dates, not instants, so tenor arithmetic stays naive
    and never trips over a tz-aware capture timestamp."""
    return pd.Timestamp.now(tz="UTC").tz_localize(None).normalize()


class YFinanceChains:
    """Real chains, free, delayed. Bid and ask are zero outside regular trading hours, in which
    case only `last` survives and the surface page will say so rather than pretend."""

    name = "yfinance"

    def _ticker(self, symbol: str):
        import yfinance as yf

        return yf.Ticker(symbol)

    def expirations(self, symbol: str) -> list[str]:
        return list(self._ticker(symbol).options)

    def spot(self, symbol: str) -> float:
        return self.quote(symbol)[0]

    def quote(self, symbol: str) -> tuple[float, float]:
        """Last price and the prior session's close. Before today's first bar exists, the last
        bar is yesterday's, so the prior close is that same bar and today's change reads zero
        rather than replaying yesterday's move."""
        hist = self._ticker(symbol).history(period="5d", interval="1d")
        if hist.empty:
            return math.nan, math.nan
        last = float(hist["Close"].iloc[-1])
        today = pd.Timestamp.now(tz="America/New_York").date()
        if hist.index[-1].date() == today and len(hist) > 1:
            return last, float(hist["Close"].iloc[-2])
        return last, last

    def chain(self, symbol: str, expirations: list[str] | None = None) -> pd.DataFrame:
        ticker = self._ticker(symbol)
        wanted = expirations or list(ticker.options)[:8]
        spot, prev = self.quote(symbol)
        now = datetime.now(UTC)

        frames = []
        for expiry in wanted:
            try:
                board = ticker.option_chain(expiry)
            except Exception:  # a single bad expiry must not kill the whole chain
                continue
            for kind, side in (("call", board.calls), ("put", board.puts)):
                if side is None or side.empty:
                    continue
                frames.append(
                    pd.DataFrame(
                        {
                            "ts": now,
                            "symbol": symbol,
                            "expiry": expiry,
                            "strike": side["strike"].astype(float),
                            "kind": kind,
                            "bid": side["bid"].astype(float),
                            "ask": side["ask"].astype(float),
                            "last": side["lastPrice"].astype(float),
                            "volume": side["volume"].fillna(0).astype(float),
                            "open_interest": side["openInterest"].fillna(0).astype(float),
                            "underlying": spot,
                            "underlying_prev": prev,
                            "change": pd.to_numeric(side["change"], errors="coerce")
                            if "change" in side
                            else math.nan,
                            "last_trade": pd.to_datetime(side["lastTradeDate"], utc=True)
                            if "lastTradeDate" in side
                            else pd.NaT,
                        }
                    )
                )
        cols = CHAIN_COLUMNS + EXTRA_COLUMNS
        return pd.concat(frames, ignore_index=True)[cols] if frames else _empty()


class TastytradeChains:
    """Chains from a tastytrade account (collector.tasty, read-only).

    Strikes and streamer symbols come from the nested chain endpoint (cached an hour); bid, ask,
    last trade, day volume, open interest and prior close from the DXLink streamer. Only strikes
    within `band` of spot are subscribed, so a chain is a few hundred symbols rather than the
    whole board, and without a live spot there is no band, so no chain. Contracts still silent
    after the first wait get a second one; the share that quoted is frame.attrs["coverage"].
    Quotes are as live as the account's feed (collector.feed.feed_label()).
    """

    name = "tastytrade"
    band = 0.25  # strikes within +-25% of spot

    def expirations(self, symbol: str) -> list[str]:
        from alphasurface.collector import tasty
        from alphasurface.symbols import to_tasty

        dates = {
            e.expiration_date for c in tasty.nested_chain(to_tasty(symbol)) for e in c.expirations
        }
        return [d.isoformat() for d in sorted(dates)]

    def spot(self, symbol: str) -> float:
        return self.quote(symbol)[0]

    def quote(self, symbol: str) -> tuple[float, float]:
        """Mid of a two-sided market (last trade, then the session close, as fallbacks) and the
        prior session's close."""
        from alphasurface.collector import tasty
        from alphasurface.symbols import to_streamer

        streamer = to_streamer(symbol)
        row = tasty.stream_quotes([streamer]).get(streamer) if streamer else None
        if row is None:
            return math.nan, math.nan
        return tasty.mark(row), row["prev_close"]

    def chain(self, symbol: str, expirations: list[str] | None = None) -> pd.DataFrame:
        from alphasurface.collector import tasty
        from alphasurface.symbols import display, to_tasty

        chains = tasty.nested_chain(to_tasty(symbol))
        spot, prev = self.quote(symbol)
        if not spot == spot or spot <= 0:
            raise ChainUnavailable(
                f"No live price for {display(symbol)}, so no strikes to pick. "
                "The feed may be down; try again shortly."
            )
        listed: dict[str, list] = {}
        for c in chains:
            for e in c.expirations:
                listed.setdefault(e.expiration_date.isoformat(), []).append(e)
        wanted = [e for e in (expirations or sorted(listed)[:8]) if e in listed]

        contracts = []  # (expiry, strike, kind, streamer symbol)
        for expiry in wanted:
            # SPX-style roots list the same date twice (AM and PM settled); keep PM when both exist.
            entries = sorted(listed[expiry], key=lambda e: e.settlement_type != "PM")
            for s in entries[0].strikes:
                k = float(s.strike_price)
                if abs(k / spot - 1) > self.band:
                    continue
                contracts += [
                    (expiry, k, "call", s.call_streamer_symbol),
                    (expiry, k, "put", s.put_streamer_symbol),
                ]
        if not contracts:
            return _empty()

        symbols = [c[3] for c in contracts]
        quotes = tasty.stream_quotes(symbols, wait=4.0)
        missing = [sym for sym in symbols if sym not in quotes]
        if missing:  # slow first quotes on a wide board: one more, shorter wait for the rest
            quotes |= tasty.stream_quotes(missing, wait=3.0, retry_missing=True)
        now = datetime.now(UTC)
        rows = []
        for expiry, k, kind, sym in contracts:
            q = quotes.get(sym)
            if q is None:
                continue
            last, prior = q["last"], q["prev_close"]
            rows.append(
                {
                    "ts": now,
                    "symbol": symbol,
                    "expiry": expiry,
                    "strike": k,
                    "kind": kind,
                    "bid": q["bid"],
                    "ask": q["ask"],
                    "last": last,
                    "volume": q["volume"],
                    "open_interest": q["open_interest"],
                    "underlying": spot,
                    "underlying_prev": prev,
                    "change": last - prior if last == last and prior == prior else math.nan,
                    "last_trade": pd.to_datetime(q["last_time"], unit="ms", utc=True)
                    if q["last_time"]
                    else pd.NaT,
                }
            )
        cols = CHAIN_COLUMNS + EXTRA_COLUMNS
        frame = pd.DataFrame(rows, columns=cols) if rows else _empty()
        frame.attrs["coverage"] = len(rows) / len(contracts)
        frame.attrs["subscribed"] = len(contracts)
        return frame


class SyntheticChains:
    """A deterministic, arbitrage-sane surface for development and tests.

    Generated from a parametric smile, then priced with Black-Scholes, so solving the chain back
    to implied vol must return the volatility that went in. That round trip is the strongest test
    the surface code has, and it needs no network and no open market.

        iv(x, T) = atm(T) + skew * x + curve * x^2,   x = log(K/F) / sqrt(T)

    Term structure slopes up (calm-market contango), skew is negative (puts bid over calls), and
    the curvature gives the wings their smile.
    """

    name = "synthetic"

    def __init__(
        self,
        spot: float = 750.0,
        atm: float = 0.16,
        slope: float = 0.04,
        skew: float = -0.06,
        curve: float = 0.03,
        rate: float = 0.04,
        div: float = 0.012,
        seed: int = 7,
    ):
        self.spot_price = spot
        self.atm, self.slope, self.skew, self.curve = atm, slope, skew, curve
        self.rate, self.div = rate, div
        self.rng = np.random.default_rng(seed)

    _TENORS = (7, 14, 30, 60, 90, 120, 180, 270, 365, 545, 730)

    def expirations(self, symbol: str) -> list[str]:
        today = _today()
        return [(today + pd.Timedelta(days=d)).strftime("%Y-%m-%d") for d in self._TENORS]

    def spot(self, symbol: str) -> float:
        return self.spot_price

    def iv(self, strike: float, tenor_years: float) -> float:
        forward = self.spot_price * math.exp((self.rate - self.div) * tenor_years)
        x = math.log(strike / forward) / math.sqrt(tenor_years)
        atm = self.atm + self.slope * math.sqrt(tenor_years)
        return max(atm + self.skew * x + self.curve * x * x, 0.02)

    def chain(self, symbol: str, expirations: list[str] | None = None) -> pd.DataFrame:
        from alphasurface.derive.black_scholes import price

        today = _today()
        wanted = expirations or self.expirations(symbol)
        strikes = np.round(np.arange(0.70, 1.31, 0.01) * self.spot_price, 0)
        now = datetime.now(UTC)

        rows = []
        for expiry in wanted:
            tenor = max((pd.Timestamp(expiry) - today).days, 1) / 365
            for strike, kind in ((s, k) for s in strikes for k in ("call", "put")):
                vol = self.iv(float(strike), tenor)
                fair = price(self.spot_price, float(strike), tenor, self.rate, vol, self.div, kind)
                if fair < 0.02:
                    continue  # a real market would not quote it
                # Both sides are quoted, the in-the-money side wider, as in a real market: it is
                # mostly intrinsic and few make a tight market in it. The surface keeps only the
                # out-of-the-money side either way (derive.vol_surface).
                itm = strike < self.spot_price if kind == "call" else strike > self.spot_price
                spread = max(0.05, fair * 0.01) if itm else max(0.02, fair * 0.02)
                rows.append(
                    {
                        "ts": now,
                        "symbol": symbol,
                        "expiry": expiry,
                        "strike": float(strike),
                        "kind": kind,
                        "bid": round(fair - spread / 2, 2),
                        "ask": round(fair + spread / 2, 2),
                        "last": round(fair, 2),
                        "volume": float(self.rng.integers(0, 5_000)),
                        "open_interest": float(self.rng.integers(50, 50_000)),
                        "underlying": self.spot_price,
                    }
                )
        return pd.DataFrame(rows, columns=CHAIN_COLUMNS) if rows else _empty()


PROVIDERS: dict[str, type] = {
    "tastytrade": TastytradeChains,
    "yfinance": YFinanceChains,
    "synthetic": SyntheticChains,
}


def source_label(source: str) -> str:
    """How a page tags its data: sample, delayed, or whether the tastytrade feed is real-time."""
    if source == "synthetic":
        return "sample data"
    if source == "tastytrade":
        from alphasurface.collector.feed import feed_label

        return feed_label() or "tastytrade"
    return f"{source}, delayed"


def default_source() -> str:
    """tastytrade when its credentials are set, otherwise the sample surface."""
    from alphasurface.collector import tasty

    return "tastytrade" if tasty.ready() else "synthetic"


def live_source() -> str:
    """The best real source: tastytrade when connected, else Yahoo. For the CLI and scheduled
    scans, which should never fall back to sample data."""
    from alphasurface.collector import tasty

    return "tastytrade" if tasty.ready() else "yfinance"


def get_provider(name: str):
    if name not in PROVIDERS:
        raise KeyError(f"unknown chain provider {name!r}. Have: {sorted(PROVIDERS)}")
    return PROVIDERS[name]()
