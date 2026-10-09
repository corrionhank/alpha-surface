"""Build a volatility surface from a raw options chain.

Most of the work here is throwing quotes away. A raw chain is mostly noise: zero bids, crossed
markets, stale last trades on contracts nobody has touched in a week, and deep wings where a
one-cent tick moves implied vol by ten points. Feed that to a surface plot and you get a hairball.

The rules, in order:

  1. Out-of-the-money side only. Calls above the forward, puts below. ITM options are wide, stale,
     and carry the same information as their OTM twin by put-call parity, so they add noise and
     no signal.
  2. A real two-sided quote, or nothing. Mid = (bid + ask) / 2. If the market is closed and there
     is no two-sided quote, fall back to last, but mark the row so the page can say the surface is
     built on stale prints rather than pretending it is live.
  3. Spread sanity. A market wider than `max_spread` of its own mid is not a price.
  4. No-arbitrage. Handled in derive.implied_vol: anything that admits no sigma returns NaN and
     drops out here.
  5. Enough points to be a smile. An expiry with fewer than `min_points` survivors is dropped
     rather than drawn as a line between two dots.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from alphasurface.derive.black_scholes import greeks
from alphasurface.derive.implied_vol import implied_vol

QUOTE_MID, QUOTE_LAST = "mid", "last"


def _tenor_years(expiry: pd.Series, asof: pd.Timestamp) -> pd.Series:
    """Expiries are calendar dates; the capture timestamp is a tz-aware instant. Drop the tz before
    subtracting, or pandas refuses to mix the two."""
    base = pd.Timestamp(asof)
    base = base.tz_localize(None) if base.tzinfo else base
    days = (pd.to_datetime(expiry) - base.normalize()).dt.days.clip(lower=0)
    return days / 365.0


def mid_price(chain: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Mid where a two-sided market exists, last otherwise. Also returns the source of each."""
    two_sided = (chain["bid"] > 0) & (chain["ask"] > chain["bid"])
    mid = np.where(two_sided, (chain["bid"] + chain["ask"]) / 2, chain["last"])
    source = np.where(two_sided, QUOTE_MID, QUOTE_LAST)
    return pd.Series(mid, index=chain.index), pd.Series(source, index=chain.index)


def build(
    chain: pd.DataFrame,
    rate: float = 0.04,
    div: float = 0.0,
    *,
    asof: pd.Timestamp | None = None,
    max_spread: float = 0.35,
    min_open_interest: float = 0.0,
    moneyness: tuple[float, float] = (0.75, 1.25),
    min_points: int = 4,
) -> pd.DataFrame:
    """Tidy surface: one row per surviving contract, with our own implied vol on it."""
    if chain.empty:
        return pd.DataFrame(columns=["expiry", "tenor", "strike", "kind", "iv", "moneyness"])

    df = chain.copy()
    asof = asof or pd.Timestamp(df["ts"].iloc[0])
    spot = float(df["underlying"].iloc[0])

    df["tenor"] = _tenor_years(df["expiry"], asof)
    df["price"], df["quote"] = mid_price(df)
    df["moneyness"] = df["strike"] / spot
    df["forward"] = spot * np.exp((rate - div) * df["tenor"])
    df["spread"] = np.where(
        df["ask"] > 0, (df["ask"] - df["bid"]) / df["price"].replace(0, np.nan), np.nan
    )

    otm = ((df["kind"] == "call") & (df["strike"] >= df["forward"])) | (
        (df["kind"] == "put") & (df["strike"] < df["forward"])
    )
    keep = (
        otm
        & (df["tenor"] > 0)
        & (df["price"] > 0)
        & df["moneyness"].between(*moneyness)
        & (df["open_interest"] >= min_open_interest)
        & (df["spread"].isna() | (df["spread"] <= max_spread))
    )
    df = df[keep].copy()
    if df.empty:
        return df.assign(iv=[])

    df["iv"] = [
        implied_vol(p, spot, k, t, rate, div, kind)
        for p, k, t, kind in zip(df["price"], df["strike"], df["tenor"], df["kind"], strict=False)
    ]
    df = df[df["iv"].notna() & (df["iv"] > 0)]
    if df.empty:
        return df

    df["log_moneyness"] = np.log(df["strike"] / df["forward"])
    df["delta"] = [
        greeks(spot, k, t, rate, v, div, kind).delta
        for k, t, v, kind in zip(df["strike"], df["tenor"], df["iv"], df["kind"], strict=False)
    ]
    df["dte"] = (df["tenor"] * 365).round().astype(int)

    # An expiry with a handful of survivors is a rumour, not a smile.
    counts = df.groupby("expiry")["iv"].transform("size")
    df = df[counts >= min_points]

    return df.sort_values(["tenor", "strike"]).reset_index(drop=True)


def atm_term_structure(surface: pd.DataFrame) -> pd.DataFrame:
    """ATM vol per expiry, interpolated at the forward rather than snapped to the nearest strike."""
    rows = []
    for expiry, group in surface.groupby("expiry"):
        group = group.sort_values("log_moneyness")
        if len(group) < 2:
            continue
        atm = np.interp(0.0, group["log_moneyness"], group["iv"])
        rows.append(
            {
                "expiry": expiry,
                "dte": int(group["dte"].iloc[0]),
                "tenor": float(group["tenor"].iloc[0]),
                "atm_iv": float(atm),
            }
        )
    return pd.DataFrame(rows).sort_values("dte").reset_index(drop=True)


def smile(surface: pd.DataFrame, expiry: str) -> pd.DataFrame:
    """One expiry's smile, ordered for plotting."""
    return surface[surface["expiry"] == expiry].sort_values("log_moneyness").reset_index(drop=True)


def skew_25delta(surface: pd.DataFrame, expiry: str) -> float:
    """25-delta put IV minus 25-delta call IV. The standard one-number summary of the smile's tilt.

    Positive is the normal state for equity index: downside puts are bid over upside calls.
    """
    board = smile(surface, expiry)
    puts = board[board["kind"] == "put"]
    calls = board[board["kind"] == "call"]
    if puts.empty or calls.empty:
        return float("nan")

    put_iv = np.interp(-0.25, puts["delta"].to_numpy()[::-1], puts["iv"].to_numpy()[::-1])
    call_iv = np.interp(0.25, calls["delta"].to_numpy()[::-1], calls["iv"].to_numpy()[::-1])
    return float(put_iv - call_iv)


def mesh(surface: pd.DataFrame, n_strike: int = 45, n_tenor: int = 25):
    """Interpolate the scattered quotes onto a regular grid for the 3D plot.

    Linear inside the convex hull of real quotes, nearest-neighbour outside it, because the wings
    are exactly where a linear extrapolation invents structure that was never traded.
    """
    from scipy.interpolate import griddata

    if surface.empty or surface["expiry"].nunique() < 2:
        return None

    x = surface["log_moneyness"].to_numpy()
    y = surface["dte"].to_numpy().astype(float)
    z = surface["iv"].to_numpy()

    xi = np.linspace(np.percentile(x, 2), np.percentile(x, 98), n_strike)
    yi = np.linspace(y.min(), y.max(), n_tenor)
    grid_x, grid_y = np.meshgrid(xi, yi)

    zi = griddata((x, y), z, (grid_x, grid_y), method="linear")
    gaps = np.isnan(zi)
    if gaps.any():
        zi[gaps] = griddata((x, y), z, (grid_x[gaps], grid_y[gaps]), method="nearest")
    return xi, yi, zi
