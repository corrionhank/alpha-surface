"""Macro series from FRED, fetched write-through. Optional: only with FRED_API_KEY set.

The rest of the Economy tab needs no key: the calendar is collector.reference's, and Treasury
yields are Yahoo daily bars through the bar gateway (present.data).
"""

from __future__ import annotations

import pandas as pd

from alphasurface.collector import fundamentals as fa
from alphasurface.config import Config

URL = "https://api.stlouisfed.org/fred/series/observations"
# FRED id: (label, how to read it). "yoy" series are index levels shown as a 12-month change.
SERIES = {
    "CPIAUCSL": ("CPI inflation", "yoy"),
    "PCEPILFE": ("Core PCE inflation", "yoy"),
    "UNRATE": ("Unemployment rate", "level"),
    "DFF": ("Fed funds rate", "level"),
    "A191RL1Q225SBEA": ("Real GDP growth", "level"),
}
YEARS = 4
MAX_AGE = pd.Timedelta(hours=12)


def normalize_observations(
    series_id: str, observations: list[dict], now: pd.Timestamp
) -> pd.DataFrame:
    """FRED observations -> long rows (series, date, value). FRED writes "." for a missing value."""
    df = pd.DataFrame(observations or [], columns=["date", "value"])
    if df.empty:
        return pd.DataFrame()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["date"] = pd.to_datetime(df["date"])
    df = df.dropna(subset=["value"])
    df.insert(0, "series", series_id)
    df.insert(0, "source", "fred")
    df.insert(0, "collected_at", now)
    return df.reset_index(drop=True)


def fetch_macro(key: str, series: dict = SERIES, years: int = YEARS) -> pd.DataFrame:
    import httpx

    now = pd.Timestamp.now(tz="UTC")
    start = (now - pd.DateOffset(years=years)).strftime("%Y-%m-%d")
    parts = []
    for sid in series:
        resp = httpx.get(
            URL,
            timeout=10,
            params={
                "series_id": sid,
                "api_key": key,
                "file_type": "json",
                "observation_start": start,
            },
        )
        resp.raise_for_status()
        parts.append(normalize_observations(sid, resp.json().get("observations", []), now))
    parts = [p for p in parts if not p.empty]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def macro(config: Config) -> fa.ref.Fetched:
    """Stored macro series, refreshed in the background past their window. Empty without a key."""
    if not config.keys.fred:
        return fa.ref.Fetched(pd.DataFrame(), "none", None, "no FRED key")
    return fa.refresh_for(
        "macro_series",
        "source",
        "fred",
        lambda: fetch_macro(config.keys.fred),
        config=config,
        max_age=MAX_AGE,
    )
