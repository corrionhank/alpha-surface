"""Point-in-time recession and valuation signals.

Every threshold here is an expanding-window percentile: what you would have known that day, never
the full sample. Every series is shifted by its real publication lag. Skipping either is how a
backtest "discovers" that hedging in 2008 and 2020 works, which is not a discovery, it is the
answer key.

Sources, all free and keyless:
  T10Y3M   FRED, daily from 1982. 10-year minus 3-month Treasury. The classic lead indicator.
  BAA10Y   FRED, daily from 1986. Moody's Baa corporate spread over the 10-year.
           The ICE BofA high-yield series are licence-capped on FRED to a 3-year window, so the
           Baa spread stands in: same credit-stress signal, longer and freely redistributable.
  UNRATE   FRED, monthly from 1948. Feeds the Sahm rule.
  CAPE     Shiller, monthly from 1871. The PE the question was actually about.
"""

from __future__ import annotations

import pandas as pd

from config import REPO_ROOT

CACHE = REPO_ROOT / "data" / "signals"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={id}&cosd=1960-01-01"
SHILLER_XLS = CACHE / "ie_data.xls"

# Publication lag, in months, for the series that are not observable same-day.
MONTHLY_LAG = 1


def _fred(series_id: str) -> pd.Series:
    """Daily or monthly FRED series, cached to disk so reruns are offline."""
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / f"{series_id}.csv"
    if not path.exists():
        pd.read_csv(FRED.format(id=series_id)).to_csv(path, index=False)

    df = pd.read_csv(path)
    df.columns = ["date", "value"]
    out = pd.Series(
        pd.to_numeric(df["value"], errors="coerce").values,
        index=pd.DatetimeIndex(pd.to_datetime(df["date"])),
        name=series_id,
    )
    return out.dropna()


def cape() -> pd.Series:
    """Shiller CAPE, monthly.

    His sheet stops in 2024-06. Rather than forward-fill a flat line through the last two years,
    the tail is extended by holding real 10-year average earnings constant and letting the real
    price move it: CAPE_t = CAPE_last * (real price now / real price then). Earnings averaged over
    a decade barely move in 24 months, and the signal only asks whether CAPE is high, not what it
    is to two decimals. The extension covers 24 of ~250 months in the study window.
    """
    raw = pd.read_excel(SHILLER_XLS, sheet_name="Data", skiprows=7)
    raw = raw[["Date", "P", "CPI", "CAPE"]].dropna(subset=["Date"])

    # Shiller writes 2024.10 for October, so the fractional part is the month, not a decimal year.
    year = raw["Date"].astype(float).astype(int)
    month = (raw["Date"].astype(float) * 100).round().astype(int) % 100
    idx = pd.to_datetime({"year": year, "month": month, "day": 1})

    series = pd.Series(pd.to_numeric(raw["CAPE"], errors="coerce").values, index=idx).dropna()
    price = pd.Series(pd.to_numeric(raw["P"], errors="coerce").values, index=idx)
    cpi = pd.Series(pd.to_numeric(raw["CPI"], errors="coerce").values, index=idx)

    real = (price / cpi).dropna()
    last = series.index[-1]
    tail = real[real.index > last]
    if len(tail):
        extended = series.iloc[-1] * (tail / real.loc[last])
        series = pd.concat([series, extended])
    return series.sort_index()


def _localize(series: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """FRED and Shiller publish naive dates; storage timestamps are tz-aware UTC."""
    if index.tz is not None and series.index.tz is None:
        series = series.copy()
        series.index = series.index.tz_localize(index.tz)
    return series


def _pit_high(series: pd.Series, pct: float, min_periods: int) -> pd.Series:
    """True when the series sits above its own expanding percentile.

    The threshold is shifted so today's reading cannot help set the bar it is being judged
    against. This is the difference between a signal and a memory.
    """
    bar = series.expanding(min_periods=min_periods).quantile(pct).shift(1)
    return (series > bar).where(bar.notna(), False)


def _monthly_to_daily(series: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """Lag a monthly series by its publication delay, then hold it flat across the month."""
    lagged = series.copy()
    lagged.index = lagged.index + pd.DateOffset(months=MONTHLY_LAG)
    return _localize(lagged, index).reindex(index, method="ffill")


def build(index: pd.DatetimeIndex, spot: pd.Series, percentile: float = 0.80) -> pd.DataFrame:
    """One boolean column per signal, aligned to the trading calendar.

    Everything is shifted a day at the end: the decision is made on yesterday's close, so the
    hedge is put on with information that was actually available when the order was sent.
    """
    # Every threshold is computed on the series' own full history, then sliced to the study
    # window. Computing it after slicing would leave the signal with no history to judge 2008
    # against, and it would sleep straight through the crisis it exists to catch.
    curve = _fred("T10Y3M")
    inverted = (curve < 0).rolling(252, min_periods=1).max().astype(bool)

    credit = _pit_high(_fred("BAA10Y"), percentile, min_periods=252 * 5)

    # Sahm: 3-month average unemployment 0.5pp above its trailing 12-month low.
    smooth = _fred("UNRATE").rolling(3).mean()
    sahm = (smooth - smooth.rolling(12).min()) >= 0.50

    valuation = _pit_high(cape(), percentile, min_periods=360)

    def daily(series: pd.Series) -> pd.Series:
        return _localize(series, index).reindex(index, method="ffill").fillna(False).astype(bool)

    out = pd.DataFrame(
        {
            "Yield curve": daily(inverted),
            "Credit spread": daily(credit),
            "Sahm rule": _monthly_to_daily(sahm, index).fillna(False).astype(bool),
            "High CAPE": _monthly_to_daily(valuation, index).fillna(False).astype(bool),
            "Below 200d": spot < spot.rolling(200, min_periods=200).mean(),
        },
        index=index,
    ).fillna(False)

    out["Any 2 of 5"] = out.sum(axis=1) >= 2
    return out.shift(1).fillna(False).astype(bool)
