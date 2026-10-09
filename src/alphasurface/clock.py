"""Exchange sessions: whether the market is open, honoring holidays and early closes.

Offline: pandas_market_calendars carries the NYSE and CME holiday and half-day rules, so nothing
here calls a provider. Equities follow the NYSE regular session (09:30 to 16:00 ET, 13:00 on a
half day); futures follow CME Globex equity hours, which open the evening before the trade date.
Every timestamp in and out is tz-aware.
"""

from __future__ import annotations

from functools import lru_cache

import pandas as pd

NY = "America/New_York"
_CALENDARS = {"equity": "NYSE", "future": "CME_Equity"}


@lru_cache(maxsize=16)
def _schedule(market: str, year: int) -> pd.DataFrame:
    """Sessions from a month before the year to a month after it, so lookups near New Year and
    next_open() across it need no second fetch."""
    import pandas_market_calendars as mcal

    return mcal.get_calendar(_CALENDARS[market]).schedule(f"{year - 1}-12-01", f"{year + 1}-01-31")


def _utc(now: pd.Timestamp | None) -> pd.Timestamp:
    t = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _rows(t: pd.Timestamp, market: str) -> pd.DataFrame:
    return _schedule(market, t.tz_convert(NY).year)


def session(
    now: pd.Timestamp | None = None, market: str = "equity"
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """The open and close of the session trading on now's New York date, or None on a day with
    no session (weekend, holiday)."""
    t = _utc(now)
    day = t.tz_convert(NY).normalize().tz_localize(None)
    sched = _rows(t, market)
    if day not in sched.index:
        return None
    row = sched.loc[day]
    return row["market_open"], row["market_close"]


def is_open(now: pd.Timestamp | None = None, market: str = "equity") -> bool:
    """Inside a regular session right now. Futures sessions span midnight, so any listed session
    containing now counts, minus the daily maintenance break when the calendar has one."""
    t = _utc(now)
    if market == "equity":
        s = session(t, market)
        return s is not None and s[0] <= t < s[1]
    sched = _rows(t, market)
    live = sched[(sched["market_open"] <= t) & (t < sched["market_close"])]
    if live.empty:
        return False
    row = live.iloc[0]
    if "break_start" in row and pd.notna(row["break_start"]):
        return not row["break_start"] <= t < row["break_end"]
    return True


def next_open(now: pd.Timestamp | None = None, market: str = "equity") -> pd.Timestamp | None:
    """The next session open strictly after now."""
    t = _utc(now)
    for year in (t.tz_convert(NY).year, t.tz_convert(NY).year + 1):
        opens = _schedule(market, year)["market_open"]
        later = opens[opens > t]
        if not later.empty:
            return later.iloc[0]
    return None


def sessions_back(n: int, now: pd.Timestamp | None = None, market: str = "equity") -> pd.Timestamp:
    """The open of the n-th most recent session that has opened by now (n=1 is the current or
    last session). Bounds an intraday pull to n sessions."""
    t = _utc(now)
    year = t.tz_convert(NY).year
    opens = pd.concat(
        [_schedule(market, year - 1)["market_open"], _schedule(market, year)["market_open"]]
    )
    opened = opens[opens <= t].drop_duplicates().sort_values()
    return opened.iloc[-min(max(n, 1), len(opened))]


def minutes_to_close(now: pd.Timestamp | None = None, market: str = "equity") -> float:
    """Regular-session minutes left today: the whole session before the open (210 on a half
    day), what is left during it, 0 after the close or on a day with no session."""
    t = _utc(now)
    s = session(t, market)
    if s is None:
        return 0.0
    open_, close = s
    start = max(t, open_)
    return max((close - start).total_seconds() / 60, 0.0)
