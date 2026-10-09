"""Reference data, fetched write-through: ETF profiles, top holdings, news, economic calendar.

provider -> fetch -> {returned to the page for analysis now, appended to the store for later}

The page never waits on a provider. `refresh` hands back the latest stored copy at once and, when
that copy is older than its freshness window, starts a background fetch that lands in the store
for the next read. Only when nothing has ever been stored does it wait, briefly, for the first
fetch. A failed fetch or write is logged and the page carries on with what it has.

Sources (yfinance 1.4): Ticker.info and Ticker.funds_data for fund profiles and holdings;
yf.Search for news (Ticker.news returns nothing in this version); yf.Calendars for the economic
calendar. Finnhub general news joins only when FINNHUB_API_KEY is set, and FRED release dates
stand in for the calendar only if yf.Calendars is unavailable and FRED_API_KEY is set.
"""

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field

import pandas as pd

from alphasurface.config import Config, load_config
from alphasurface.storage import reference as store

log = logging.getLogger(__name__)

OFFLINE = False  # tests flip this so nothing touches the network

MAX_AGE = {  # freshness window per table before a background refresh starts
    "etf_profile": pd.Timedelta(hours=6),
    "etf_holdings": pd.Timedelta(hours=6),
    "news": pd.Timedelta(minutes=15),
    "econ_calendar": pd.Timedelta(hours=6),
}

# Events a derivatives desk plans around, matched case-insensitively from the start of a word.
# Yahoo abbreviates ("Cont Jobl Clm", "U Mich Sentiment"), so the fragments stay short.
KEY_EVENTS = re.compile(
    r"\b(?:CPI|PPI|PCE|non-?farm|payroll|unemploy|jobl|jobless|initial claims|GDP|retail sales|"
    r"ISM|FOMC|fed funds|rate decision|JOLTS|U Mich|michigan|consumer sentiment|durable)",
    re.I,
)


@dataclass
class Fetched:
    frame: pd.DataFrame
    origin: (
        str  # live (just fetched) | fresh (stored, in window) | stale (stored, refreshing) | none
    )
    asof: pd.Timestamp | None = None
    note: str = ""
    extra: dict = field(default_factory=dict)


def _now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


# --- Fetchers: provider -> normalized frame. No storage here. -------------------------------


def fetch_profiles(symbols: list[str]) -> pd.DataFrame:
    import yfinance as yf

    now, rows = _now(), []
    for sym in symbols:
        t = yf.Ticker(sym)
        info = t.info or {}
        expense = float("nan")
        try:  # the fund's own annual report figure, a decimal
            ops = t.funds_data.fund_operations
            expense = _num(ops.loc["Annual Report Expense Ratio", sym])
        except Exception:
            pass
        if expense != expense and info.get("netExpenseRatio") is not None:
            expense = _num(info["netExpenseRatio"]) / 100  # Yahoo reports this one in percent
        rows.append(
            {
                "collected_at": now,
                "source": "yfinance",
                "symbol": sym,
                "name": info.get("longName") or info.get("shortName") or sym,
                "trailing_pe": _num(info.get("trailingPE")),
                "forward_pe": _num(info.get("forwardPE")),
                "price_to_book": _num(info.get("priceToBook")),
                "dividend_yield": _num(info.get("yield")),  # decimal
                "expense_ratio": expense,
                "total_assets": _num(info.get("totalAssets")),
                "ytd_return": _num(info.get("ytdReturn")) / 100,  # Yahoo: percent
                "three_year_return": _num(info.get("threeYearAverageReturn")),
                "beta_3y": _num(info.get("beta3Year")),
                "nav": _num(info.get("navPrice")),
                "week52_high": _num(info.get("fiftyTwoWeekHigh")),
                "week52_low": _num(info.get("fiftyTwoWeekLow")),
                "category": info.get("category") or "",
            }
        )
    return pd.DataFrame(rows)


def fetch_holdings(symbols: list[str]) -> pd.DataFrame:
    """Top holdings (kind=holding) and sector weights (kind=sector) per fund, weights decimal."""
    import yfinance as yf

    now, rows = _now(), []
    for sym in symbols:
        fd = yf.Ticker(sym).funds_data
        top = fd.top_holdings
        for rank, (ticker, row) in enumerate(top.iterrows(), start=1):
            rows.append(
                {
                    "collected_at": now,
                    "source": "yfinance",
                    "fund": sym,
                    "kind": "holding",
                    "rank": rank,
                    "key": str(ticker),
                    "name": str(row.get("Name", ticker)),
                    "weight": _num(row.get("Holding Percent")),
                }
            )
        sectors = sorted((fd.sector_weightings or {}).items(), key=lambda kv: -_num(kv[1]))
        for rank, (sector, w) in enumerate(sectors, start=1):
            rows.append(
                {
                    "collected_at": now,
                    "source": "yfinance",
                    "fund": sym,
                    "kind": "sector",
                    "rank": rank,
                    "key": sector,
                    "name": sector.replace("_", " ").capitalize(),
                    "weight": _num(w),
                }
            )
    return pd.DataFrame(rows)


NEWS_QUERIES = ["S&P 500", "Nasdaq 100", "stock market", "Federal Reserve"]


def fetch_news(queries: list[str]) -> pd.DataFrame:
    import yfinance as yf

    now, rows = _now(), []
    for q in queries:
        for n in yf.Search(q, news_count=10, max_results=1, timeout=10).news or []:
            rows.append(
                {
                    "collected_at": now,
                    "source": "yfinance",
                    "id": str(n.get("uuid", "")),
                    "title": str(n.get("title", "")).strip(),
                    "publisher": str(n.get("publisher", "")),
                    "link": str(n.get("link", "")),
                    "published": pd.Timestamp(n.get("providerPublishTime", 0), unit="s", tz="UTC"),
                    "related": ",".join(n.get("relatedTickers") or []),
                    "query": q,
                }
            )
    key = load_config().keys.finnhub
    if key:
        import httpx

        resp = httpx.get(
            "https://finnhub.io/api/v1/news",
            params={"category": "general", "token": key},
            timeout=10,
        )
        resp.raise_for_status()
        for n in resp.json()[:40]:
            rows.append(
                {
                    "collected_at": now,
                    "source": "finnhub",
                    "id": f"fh-{n.get('id')}",
                    "title": str(n.get("headline", "")).strip(),
                    "publisher": str(n.get("source", "")),
                    "link": str(n.get("url", "")),
                    "published": pd.Timestamp(n.get("datetime", 0), unit="s", tz="UTC"),
                    "related": str(n.get("related", "")),
                    "query": "finnhub general",
                }
            )
    return dedupe_news(pd.DataFrame(rows))


def dedupe_news(df: pd.DataFrame) -> pd.DataFrame:
    """One row per story, newest first. The same story arrives from several queries and, across
    feeds, under different ids, so match on id and on the normalized headline."""
    if df.empty:
        return df
    df = df[df["title"].astype(str).str.len() > 0].copy()
    df["_norm"] = (
        df["title"].str.lower().str.replace(r"[^a-z0-9 ]", "", regex=True).str.split().str.join(" ")
    )
    df = df.sort_values(["published", "collected_at"], ascending=False)
    df = df.drop_duplicates("id").drop_duplicates("_norm")
    return df.drop(columns="_norm").reset_index(drop=True)


def normalize_calendar(
    raw: pd.DataFrame, now: pd.Timestamp, source: str = "yfinance"
) -> pd.DataFrame:
    """yf.Calendars economic events -> one row per event, times UTC, key events flagged."""
    if raw is None or raw.empty:
        return pd.DataFrame(
            columns=[
                "collected_at",
                "source",
                "event",
                "region",
                "time",
                "period",
                "actual",
                "expected",
                "last",
                "revised",
                "key",
            ]
        )
    df = raw.reset_index().rename(
        columns={
            "Event": "event",
            "Region": "region",
            "Event Time": "time",
            "For": "period",
            "Actual": "actual",
            "Expected": "expected",
            "Last": "last",
            "Revised": "revised",
        }
    )
    for col in ("actual", "expected", "last", "revised"):
        df[col] = pd.to_numeric(df.get(col), errors="coerce")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df["event"] = df["event"].astype(str).str.rstrip("* ").str.strip()
    df["period"] = df["period"].astype(str).replace({"nan": "", "None": ""})
    df["key"] = df["event"].str.contains(KEY_EVENTS)
    df["collected_at"], df["source"] = now, source
    cols = [
        "collected_at",
        "source",
        "event",
        "region",
        "time",
        "period",
        "actual",
        "expected",
        "last",
        "revised",
        "key",
    ]
    return (
        df[cols]
        .drop_duplicates(["event", "region", "time"])
        .sort_values("time")
        .reset_index(drop=True)
    )


def fetch_calendar(start: pd.Timestamp, end: pd.Timestamp, pages: int = 15) -> pd.DataFrame:
    import yfinance as yf

    now = _now()
    if hasattr(yf, "Calendars"):
        cal = yf.Calendars(start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"))
        frames = []
        for page in range(pages):  # the endpoint pages 100 events at a time, newest first
            ev = cal.get_economic_events_calendar(limit=100, offset=page * 100, force=True)
            frames.append(ev)
            if len(ev) < 100:
                break
        return normalize_calendar(pd.concat(frames) if frames else pd.DataFrame(), now)

    key = load_config().keys.fred
    if not key:
        return normalize_calendar(pd.DataFrame(), now)
    import httpx

    resp = httpx.get(
        "https://api.stlouisfed.org/fred/releases/dates",
        timeout=10,
        params={
            "api_key": key,
            "file_type": "json",
            "realtime_start": start.strftime("%Y-%m-%d"),
            "realtime_end": end.strftime("%Y-%m-%d"),
            "include_release_dates_with_no_data": "true",
        },
    )
    resp.raise_for_status()
    raw = pd.DataFrame(resp.json().get("release_dates", []))
    if raw.empty:
        return normalize_calendar(raw, now, "fred")
    raw = raw.rename(columns={"release_name": "Event", "date": "Event Time"})
    raw["Region"] = "US"
    return normalize_calendar(raw.set_index("Event"), now, "fred")


# --- Write-through and background refresh ---------------------------------------------------


def write_through(table: str, frame: pd.DataFrame, config: Config) -> pd.DataFrame:
    """Store a fetched frame and hand it back. A failed write is logged, never raised."""
    try:
        store.append(frame, table, config)
    except Exception:
        log.exception("could not store %s fetch", table)
    return frame


_pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="reference")
_inflight: dict[str, Future] = {}
_lock = threading.Lock()


def _job(table: str, fetch, config: Config) -> pd.DataFrame:
    try:
        return write_through(table, fetch(), config)
    except Exception:
        log.exception("%s fetch failed", table)
        return pd.DataFrame()


def refresh(
    table: str, fetch, *, config: Config | None = None, by: str | None = None, wait: float = 8.0
) -> Fetched:
    """Latest stored copy now; a background fetch when it is stale; a short wait only when
    nothing is stored yet. fetch is a zero-argument callable returning the normalized frame."""
    config = config or load_config()
    stored = _safe_latest(table, config, by)
    asof = stored["collected_at"].max() if not stored.empty else None
    stale = asof is None or _now() - pd.Timestamp(asof) > MAX_AGE[table]
    future = None
    if stale and not OFFLINE:
        with _lock:
            future = _inflight.get(table)
            if future is None or future.done():
                future = _pool.submit(_job, table, fetch, config)
                _inflight[table] = future
    if not stored.empty:
        return Fetched(
            stored,
            "stale" if stale else "fresh",
            pd.Timestamp(asof),
            "refreshing in the background" if future is not None else "",
        )
    if future is not None:
        try:
            frame = future.result(timeout=wait)
            if not frame.empty:
                return Fetched(frame, "live", pd.Timestamp(frame["collected_at"].max()))
        except Exception:
            log.warning("%s first fetch did not finish within %.0fs", table, wait)
    return Fetched(pd.DataFrame(), "none", None, "no data yet")


def _safe_latest(table: str, config: Config, by: str | None) -> pd.DataFrame:
    try:
        return store.latest(table, config, by)
    except Exception:
        log.exception("could not read stored %s", table)
        return pd.DataFrame()


def news_history(config: Config, hours: int = 72) -> pd.DataFrame:
    """Stories from every stored pull over the last `hours`, deduped: the feed keeps stories a
    single pull has already rotated out."""
    try:
        df = store.read(
            "news", config, "WHERE published >= ?", [_now() - pd.Timedelta(hours=hours)]
        )
    except Exception:
        log.exception("could not read stored news")
        return pd.DataFrame()
    return dedupe_news(df)
