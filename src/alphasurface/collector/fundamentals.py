"""Company fundamentals from Yahoo, fetched write-through: key stats, statements, earnings, filings.

provider -> fetch -> {returned to the page now, appended to the store for later studies}

The freshness model is collector.reference's, keyed per symbol (refresh_for): the page gets the
stored copy at once and a background fetch starts when that copy is older than its window; only
a symbol never seen before waits, briefly, for its first fetch. Filings are links, not data, so
they are fetched on demand and never stored.

Sources (yfinance 1.4): Ticker.info and recommendations_summary for the snapshot; income_stmt,
balance_sheet, cashflow and their quarterly forms; get_earnings_dates; sec_filings. Yahoo
reports dividendYield and debtToEquity in percent; both are stored as decimals.
"""

from __future__ import annotations

import logging
import re
import threading
from concurrent.futures import Future, ThreadPoolExecutor

import pandas as pd

from alphasurface.collector import reference as ref
from alphasurface.config import Config
from alphasurface.storage import reference as store

log = logging.getLogger(__name__)

FUNDS = {"ETF", "MUTUALFUND", "INDEX"}  # quote types that file no statements
MAX_AGE = {
    "fundamentals": pd.Timedelta(hours=12),
    "financials": pd.Timedelta(hours=12),
    "earnings": pd.Timedelta(hours=6),
    "etf_profile": pd.Timedelta(hours=6),
    "etf_holdings": pd.Timedelta(hours=6),
}
STATEMENTS = {  # (statement, freq): Ticker attribute
    ("income", "annual"): "income_stmt",
    ("income", "quarterly"): "quarterly_income_stmt",
    ("balance", "annual"): "balance_sheet",
    ("balance", "quarterly"): "quarterly_balance_sheet",
    ("cashflow", "annual"): "cashflow",
    ("cashflow", "quarterly"): "quarterly_cashflow",
}
REPORTS = re.compile(r"^(10-K|10-Q|8-K|20-F|40-F|6-K)(/A)?$")
EDGAR_LINK = re.compile(r"/sec-filing/[^/]+/(\d{10}-\d{2}-\d{6})_(\d+)")


def _num(x) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return float("nan")


def _now() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


# --- Snapshot: profile, key stats, analyst view ---------------------------------------------


def normalize_info(
    info: dict, symbol: str, now: pd.Timestamp, recs: pd.DataFrame | None = None
) -> pd.DataFrame:
    """Ticker.info (plus the current month of recommendations_summary) -> one snapshot row.
    Empty when Yahoo does not know the symbol."""
    if not info or not (info.get("quoteType") or info.get("longName") or info.get("shortName")):
        return pd.DataFrame()
    g = info.get
    row = {
        "collected_at": now,
        "source": "yfinance",
        "symbol": symbol,
        "name": g("longName") or g("shortName") or symbol,
        "quote_type": str(g("quoteType") or ""),
        "exchange": str(g("fullExchangeName") or g("exchange") or ""),
        "sector": str(g("sector") or ""),
        "industry": str(g("industry") or ""),
        "currency": str(g("currency") or ""),
        "price": _num(g("currentPrice") or g("regularMarketPrice")),
        "prev_close": _num(g("regularMarketPreviousClose") or g("previousClose")),
        "market_cap": _num(g("marketCap")),
        "enterprise_value": _num(g("enterpriseValue")),
        "trailing_pe": _num(g("trailingPE")),
        "forward_pe": _num(g("forwardPE")),
        "trailing_eps": _num(g("trailingEps")),
        "forward_eps": _num(g("forwardEps")),
        "dividend_yield": (
            _num(g("dividendYield")) / 100
            if g("dividendYield") is not None
            else _num(g("trailingAnnualDividendYield"))
        ),
        "beta": _num(g("beta")),
        "week52_low": _num(g("fiftyTwoWeekLow")),
        "week52_high": _num(g("fiftyTwoWeekHigh")),
        "gross_margin": _num(g("grossMargins")),
        "operating_margin": _num(g("operatingMargins")),
        "profit_margin": _num(g("profitMargins")),
        "roe": _num(g("returnOnEquity")),
        "roa": _num(g("returnOnAssets")),
        "debt_to_equity": _num(g("debtToEquity")) / 100,
        "free_cash_flow": _num(g("freeCashflow")),
        "ev_to_ebitda": _num(g("enterpriseToEbitda")),
        "price_to_sales": _num(g("priceToSalesTrailing12Months")),
        "price_to_book": _num(g("priceToBook")),
        "revenue_growth": _num(g("revenueGrowth")),
        "earnings_growth": _num(g("earningsGrowth")),
        "target_low": _num(g("targetLowPrice")),
        "target_mean": _num(g("targetMeanPrice")),
        "target_median": _num(g("targetMedianPrice")),
        "target_high": _num(g("targetHighPrice")),
        "recommendation": str(g("recommendationKey") or ""),
        "recommendation_mean": _num(g("recommendationMean")),
        "analysts": _num(g("numberOfAnalystOpinions")),
        "employees": _num(g("fullTimeEmployees")),
        "website": str(g("website") or ""),
        "summary": str(g("longBusinessSummary") or ""),
    }
    counts = {
        "strongBuy": "rec_strong_buy",
        "buy": "rec_buy",
        "hold": "rec_hold",
        "sell": "rec_sell",
        "strongSell": "rec_strong_sell",
    }
    current = None
    if recs is not None and not recs.empty and "period" in recs:
        now_month = recs[recs["period"] == "0m"]
        current = now_month.iloc[0] if len(now_month) else None
    for src, col in counts.items():
        row[col] = _num(current.get(src)) if current is not None else float("nan")
    return pd.DataFrame([row])


def fetch_snapshot(symbol: str) -> pd.DataFrame:
    import yfinance as yf

    t = yf.Ticker(symbol)
    info = t.info or {}
    recs = None
    if str(info.get("quoteType") or "").upper() not in FUNDS:
        try:
            recs = t.recommendations_summary
        except Exception:
            log.info("no recommendations for %s", symbol)
    return normalize_info(info, symbol, _now(), recs)


# --- Statements ------------------------------------------------------------------------------


def normalize_statement(
    frame: pd.DataFrame, symbol: str, statement: str, freq: str, now: pd.Timestamp
) -> pd.DataFrame:
    """A Yahoo statement (items down, period ends across) -> long rows, blanks dropped."""
    if frame is None or frame.empty:
        return pd.DataFrame()
    # Built row by row: melt on Yahoo's datetime-labelled columns fails in this pandas.
    long = pd.DataFrame(
        [
            (str(item), pd.Timestamp(period).tz_localize(None), _num(v))
            for item, row in frame.iterrows()
            for period, v in row.items()
        ],
        columns=["item", "period_end", "value"],
    ).dropna(subset=["value"])
    long.insert(0, "freq", freq)
    long.insert(0, "statement", statement)
    long.insert(0, "symbol", symbol)
    long.insert(0, "source", "yfinance")
    long.insert(0, "collected_at", now)
    return long.reset_index(drop=True)


def fetch_financials(symbol: str) -> pd.DataFrame:
    import yfinance as yf

    t, now = yf.Ticker(symbol), _now()
    parts = []
    for (statement, freq), attr in STATEMENTS.items():
        try:
            parts.append(normalize_statement(getattr(t, attr), symbol, statement, freq, now))
        except Exception:
            log.info("no %s %s statement for %s", freq, statement, symbol)
    parts = [p for p in parts if not p.empty]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# --- Earnings --------------------------------------------------------------------------------


def normalize_earnings(dates: pd.DataFrame, symbol: str, now: pd.Timestamp) -> pd.DataFrame:
    """get_earnings_dates -> one row per report: date (UTC), estimate, actual, surprise decimal.
    The next, unreported date is kept with a blank actual."""
    if dates is None or dates.empty:
        return pd.DataFrame()
    df = (
        dates.rename_axis("report_date")
        .reset_index()
        .rename(
            columns={
                "EPS Estimate": "eps_estimate",
                "Reported EPS": "eps_actual",
                "Surprise(%)": "surprise",
            }
        )
    )
    for col in ("eps_estimate", "eps_actual", "surprise"):
        df[col] = pd.to_numeric(df[col], errors="coerce") if col in df else float("nan")
    df["surprise"] = df["surprise"] / 100
    df["report_date"] = pd.to_datetime(df["report_date"], utc=True)
    df["collected_at"], df["source"], df["symbol"] = now, "yfinance", symbol
    cols = [
        "collected_at",
        "source",
        "symbol",
        "report_date",
        "eps_estimate",
        "eps_actual",
        "surprise",
    ]
    return (
        df[cols]
        .drop_duplicates("report_date")
        .sort_values("report_date", ascending=False)
        .reset_index(drop=True)
    )


def fetch_earnings(symbol: str) -> pd.DataFrame:
    import yfinance as yf

    return normalize_earnings(yf.Ticker(symbol).get_earnings_dates(limit=16), symbol, _now())


# --- Filings: links only, never stored -------------------------------------------------------


def filing_url(yahoo_link: str) -> str:
    """Yahoo's filing link -> the filing's index page on SEC EDGAR, or the Yahoo link when the
    accession number cannot be read from it."""
    m = EDGAR_LINK.search(yahoo_link or "")
    if not m:
        return yahoo_link or ""
    acc, cik = m.groups()
    return (
        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{acc}-index.htm"
    )


def edgar_url(symbol: str, cik: str | None = None) -> str:
    """The company's filing list on SEC EDGAR."""
    return f"https://www.sec.gov/edgar/browse/?CIK={cik or symbol}"


def normalize_filings(filings: list[dict] | None, symbol: str) -> pd.DataFrame:
    """sec_filings -> periodic and current reports, newest first, with EDGAR links and the CIK."""
    cols = ["symbol", "date", "type", "title", "url", "document", "cik"]
    rows = []
    for f in filings or []:
        kind = str(f.get("type", "")).strip()
        if not REPORTS.match(kind):
            continue
        link = str(f.get("edgarUrl", ""))
        m = EDGAR_LINK.search(link)
        exhibits = f.get("exhibits") if isinstance(f.get("exhibits"), dict) else {}
        rows.append(
            {
                "symbol": symbol,
                "date": pd.Timestamp(f.get("date")),
                "type": kind,
                "title": str(f.get("title", "")).strip(),
                "url": filing_url(link),
                "document": str(exhibits.get(kind) or exhibits.get(kind.split("/")[0]) or ""),
                "cik": str(int(m.group(2))) if m else "",
            }
        )
    if not rows:
        return pd.DataFrame(columns=cols)
    return (
        pd.DataFrame(rows, columns=cols).sort_values("date", ascending=False).reset_index(drop=True)
    )


def fetch_filings(symbol: str) -> pd.DataFrame:
    import yfinance as yf

    return normalize_filings(yf.Ticker(symbol).sec_filings, symbol)


# --- Write-through, keyed per symbol ---------------------------------------------------------

_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="fundamentals")
_inflight: dict[tuple[str, str], Future] = {}
_lock = threading.Lock()


def stored(table: str, key_col: str, key: str, config: Config) -> pd.DataFrame:
    """Rows of the most recent stored fetch for one key, empty when none."""
    try:
        return store.latest(table, config, where=f"WHERE {key_col} = ?", params=[key])
    except Exception:
        log.exception("could not read stored %s for %s", table, key)
        return pd.DataFrame()


def _job(table: str, fetch, config: Config) -> pd.DataFrame:
    try:
        return ref.write_through(table, fetch(), config)
    except Exception:
        log.warning("%s fetch failed", table, exc_info=True)
        return pd.DataFrame()


def refresh_for(
    table: str,
    key_col: str,
    key: str,
    fetch,
    *,
    config: Config,
    max_age: pd.Timedelta,
    wait: float = 10.0,
) -> ref.Fetched:
    """collector.reference.refresh for one key of a table (a symbol, a series source): the
    stored copy now, a background fetch when it is stale, a short wait only when nothing is
    stored. Honors collector.reference.OFFLINE."""
    have = stored(table, key_col, key, config)
    asof = pd.Timestamp(have["collected_at"].max()) if not have.empty else None
    stale = asof is None or _now() - asof > max_age
    future = None
    if stale and not ref.OFFLINE:
        with _lock:
            future = _inflight.get((table, key))
            if future is None or future.done():
                future = _pool.submit(_job, table, fetch, config)
                _inflight[(table, key)] = future
    if not have.empty:
        return ref.Fetched(
            have,
            "stale" if stale else "fresh",
            asof,
            "refreshing in the background" if future is not None else "",
        )
    if future is not None:
        try:
            frame = future.result(timeout=wait)
            if not frame.empty:
                return ref.Fetched(frame, "live", pd.Timestamp(frame["collected_at"].max()))
        except Exception:
            log.warning("%s for %s did not arrive within %.0fs", table, key, wait)
    return ref.Fetched(pd.DataFrame(), "none", None, "no data yet")
