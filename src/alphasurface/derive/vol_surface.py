"""Build a volatility surface from a raw options chain.

Per expiry, in order:

  1. Time. Years from the capture instant to the expiry's settlement (16:00 ET for PM-settled,
     09:30 ET for AM-settled), floored at an hour so a same-day expiry cannot blow up.
  2. Forward. From put-call parity at the strikes nearest the money (derive.forward); the
     carry-implied forward S e^((r - q) T) only when no strike has both sides quoted.
  3. Quotes. Two-sided markets only: a positive bid, an ask above it, a spread no wider than
     `max_spread` of the mid. Out of the money against the forward, so puts below F and calls at
     or above it: one continuous smile, no kink at the money.
  4. Vol. Black-76 on the forward, discounted at the rate. Anything outside IV_BAND is a bad
     print, not a volatility.
  5. Enough points. An expiry with fewer than `min_points` survivors is dropped rather than drawn
     as a line between two dots.

Then the summaries traders read: IV at the 10- and 25-delta points and at the money per expiry
(the vol grid), the 25-delta risk reversal and butterfly, constant-maturity values interpolated
in total variance, and the term slope.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from alphasurface.derive.forward import black76_iv, forward_delta, parity_forward, two_sided

ET = "America/New_York"
QUOTE_MID, QUOTE_LAST = "mid", "last"

TENORS = (7, 14, 21, 30, 45, 60, 90, 120, 180, 270, 365)  # target days, for expiry selection
HORIZONS = {"1M": 31, "3M": 92, "6M": 183, "1Y": 366}
MAX_EXPIRIES = 12
SETTLE = {"PM": "16:00", "AM": "09:30"}
T_MIN = 1 / (365 * 24)  # an hour, in years
IV_BAND = (0.01, 3.0)
GRID_DELTAS = {"p10": -0.10, "p25": -0.25, "c25": 0.25, "c10": 0.10}

SURFACE_COLUMNS = [
    "expiry",
    "dte",
    "tenor",
    "forward",
    "forward_source",
    "strike",
    "kind",
    "bid",
    "ask",
    "price",
    "spread",
    "iv",
    "delta",
    "log_moneyness",
    "moneyness",
    "volume",
    "open_interest",
]


# --- Expiries and time ----------------------------------------------------------------------


def select_expiries(
    listed: list[str], horizon_days: int, today: pd.Timestamp | None = None
) -> list[str]:
    """The listed expiry nearest each target tenor up to the horizon, deduplicated, at most
    MAX_EXPIRIES, in date order. Same-day expiries are left out: they have no smile left."""
    today = _ny_date(today if today is not None else pd.Timestamp.now(tz=ET))
    days = {e: (pd.Timestamp(e) - today).days for e in listed}
    live = {e: d for e, d in days.items() if d >= 1}
    if not live:
        return []
    chosen: list[str] = []
    for target in (t for t in TENORS if t <= horizon_days):
        best = min(live, key=lambda e: (abs(live[e] - target), live[e]))
        if best not in chosen and live[best] <= horizon_days * 1.2:
            chosen.append(best)
    return sorted(chosen)[:MAX_EXPIRIES]


def _utc(t) -> pd.Timestamp:
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _ny_date(t) -> pd.Timestamp:
    """Midnight of t's New York date, naive, for day counts against expiry dates. A naive t is
    taken as a New York wall time."""
    t = pd.Timestamp(t)
    return (t.tz_convert(ET).tz_localize(None) if t.tzinfo is not None else t).normalize()


def settlement_time(expiry: str, settlement: str = "PM") -> pd.Timestamp:
    """When an expiry settles, as a UTC instant."""
    hhmm = SETTLE.get(str(settlement).upper(), SETTLE["PM"])
    return pd.Timestamp(f"{expiry} {hhmm}").tz_localize(ET).tz_convert("UTC")


def tenor_years(expiry: str, now: pd.Timestamp, settlement: str = "PM") -> float:
    """Years from now to settlement, floored at T_MIN."""
    seconds = (settlement_time(expiry, settlement) - _utc(now)).total_seconds()
    return max(seconds / (365 * 86400), T_MIN)


def mid_price(chain: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Mid where a two-sided market exists, last otherwise, and which one each row used. The
    surface uses two-sided rows only; the contract table shows both."""
    ok = two_sided(chain)
    mid = np.where(ok, (chain["bid"] + chain["ask"]) / 2, chain["last"])
    source = np.where(ok, QUOTE_MID, QUOTE_LAST)
    return pd.Series(mid, index=chain.index), pd.Series(source, index=chain.index)


# --- The surface ----------------------------------------------------------------------------


def build(
    chain: pd.DataFrame,
    rate: float = 0.04,
    div: float = 0.0,
    *,
    now: pd.Timestamp | None = None,
    settlement: str | dict[str, str] = "PM",
    max_spread: float = 0.5,
    min_open_interest: float = 0.0,
    moneyness: tuple[float, float] = (0.5, 1.5),
    min_points: int = 4,
) -> pd.DataFrame:
    """Tidy surface: one row per surviving contract, with its own Black-76 implied vol.

    `rate` discounts and turns parity into a forward; `div` is used only for the fallback forward
    when no strike has both sides quoted. `settlement` is "PM", "AM" or a map of expiry to either;
    a chain with a `settlement` column overrides both. `moneyness` bounds K / F. The result's
    attrs carry `quoted` (rows in) and `kept` (rows out).
    """
    if chain.empty:
        out = pd.DataFrame(columns=SURFACE_COLUMNS)
        out.attrs.update(quoted=0, kept=0)
        return out

    now = _utc(now if now is not None else chain["ts"].max())
    today = _ny_date(now)
    spot = float(chain["underlying"].iloc[0])
    pieces = []
    for expiry, board in chain.groupby("expiry", sort=True):
        if "settlement" in board and board["settlement"].notna().any():
            kind_of_settle = str(board["settlement"].dropna().iloc[0])
        elif isinstance(settlement, dict):
            kind_of_settle = settlement.get(expiry, "PM")
        else:
            kind_of_settle = settlement
        T = tenor_years(str(expiry), now, kind_of_settle)
        F = parity_forward(board, rate, T)
        source = "parity"
        if F != F or F <= 0:  # NaN: no strike quoted on both sides
            F, source = spot * math.exp((rate - div) * T), "carry"

        df = board[two_sided(board)].copy()
        if df.empty:
            continue
        df["price"] = (df["bid"] + df["ask"]) / 2
        df["spread"] = (df["ask"] - df["bid"]) / df["price"]
        otm = ((df["kind"] == "call") & (df["strike"] >= F)) | (
            (df["kind"] == "put") & (df["strike"] < F)
        )
        df = df[
            otm
            & (df["spread"] <= max_spread)
            & (df["open_interest"].fillna(0) >= min_open_interest)
            & (df["strike"] / F).between(*moneyness)
        ].copy()
        if df.empty:
            continue
        df["iv"] = [
            black76_iv(p, F, k, T, rate, kind)
            for p, k, kind in zip(df["price"], df["strike"], df["kind"], strict=True)
        ]
        df = df[df["iv"].between(*IV_BAND)]
        if len(df) < min_points:
            continue
        df["delta"] = [
            forward_delta(F, k, T, v, kind)
            for k, v, kind in zip(df["strike"], df["iv"], df["kind"], strict=True)
        ]
        df["expiry"] = str(expiry)
        df["tenor"] = T
        df["dte"] = max((pd.Timestamp(expiry) - today).days, 0)
        df["forward"] = F
        df["forward_source"] = source
        df["log_moneyness"] = np.log(df["strike"] / F)
        df["moneyness"] = df["strike"] / F
        pieces.append(df)

    out = (
        pd.concat(pieces, ignore_index=True)[SURFACE_COLUMNS]
        .sort_values(["tenor", "strike"])
        .reset_index(drop=True)
        if pieces
        else pd.DataFrame(columns=SURFACE_COLUMNS)
    )
    out.attrs.update(quoted=len(chain), kept=len(out))
    return out


def smile(surface: pd.DataFrame, expiry: str) -> pd.DataFrame:
    """One expiry's smile, puts then calls in moneyness order: one continuous curve."""
    return surface[surface["expiry"] == expiry].sort_values("log_moneyness").reset_index(drop=True)


# --- Summaries ------------------------------------------------------------------------------


def iv_at_moneyness(board: pd.DataFrame, log_moneyness: float = 0.0) -> float:
    """IV interpolated at a log-moneyness inside the quoted range, NaN outside it."""
    b = board.sort_values("log_moneyness")
    x, y = b["log_moneyness"].to_numpy(float), b["iv"].to_numpy(float)
    if len(x) < 2 or not x[0] <= log_moneyness <= x[-1]:
        return math.nan
    return float(np.interp(log_moneyness, x, y))


def iv_at_delta(board: pd.DataFrame, delta: float) -> float:
    """IV at a forward delta (negative for puts), interpolated on that side of the smile. NaN
    when the quoted strikes do not reach that far into the wing."""
    side = board[board["kind"] == ("put" if delta < 0 else "call")].sort_values("delta")
    x, y = side["delta"].to_numpy(float), side["iv"].to_numpy(float)
    if len(x) < 2 or not x[0] <= delta <= x[-1]:
        return math.nan
    return float(np.interp(delta, x, y))


def grid(surface: pd.DataFrame) -> pd.DataFrame:
    """One row per expiry: IV at the 10- and 25-delta points and at the money, the 25-delta risk
    reversal (call minus put) and butterfly (wings average minus ATM)."""
    rows = []
    for expiry, board in surface.groupby("expiry", sort=False):
        row = {
            "expiry": expiry,
            "dte": int(board["dte"].iloc[0]),
            "tenor": float(board["tenor"].iloc[0]),
            "forward": float(board["forward"].iloc[0]),
            "n": len(board),
            "atm": iv_at_moneyness(board, 0.0),
        }
        row |= {k: iv_at_delta(board, d) for k, d in GRID_DELTAS.items()}
        row["rr25"] = row["c25"] - row["p25"]
        row["bf25"] = (row["c25"] + row["p25"]) / 2 - row["atm"]
        rows.append(row)
    cols = [
        "expiry",
        "dte",
        "tenor",
        "forward",
        "n",
        "p10",
        "p25",
        "atm",
        "c25",
        "c10",
        "rr25",
        "bf25",
    ]
    if not rows:
        return pd.DataFrame(columns=cols)
    return pd.DataFrame(rows)[cols].sort_values("tenor").reset_index(drop=True)


def atm_term_structure(surface: pd.DataFrame) -> pd.DataFrame:
    """ATM vol per expiry, interpolated at the forward."""
    g = grid(surface)
    return g[["expiry", "dte", "tenor", "atm"]].rename(columns={"atm": "atm_iv"}).dropna()


def skew_25delta(surface: pd.DataFrame, expiry: str) -> float:
    """25-delta put IV minus 25-delta call IV: positive when the put wing is bid, the normal
    state for equity indices. The negative of the risk reversal."""
    board = smile(surface, expiry)
    return iv_at_delta(board, -0.25) - iv_at_delta(board, 0.25)


def at_tenor(g: pd.DataFrame, days: float) -> dict:
    """Constant-maturity values at `days`: ATM interpolated in total variance (sigma^2 T, linear
    in T), the risk reversal and butterfly linearly in T. Outside the listed range the nearest
    expiry stands in, flagged `extrapolated`."""
    out = {"atm": math.nan, "rr25": math.nan, "bf25": math.nan, "extrapolated": True}
    usable = g.dropna(subset=["atm"]).sort_values("tenor")
    if usable.empty:
        return out
    years = days / 365
    t = usable["tenor"].to_numpy(float)
    w = usable["atm"].to_numpy(float) ** 2 * t
    inside = t[0] <= years <= t[-1]
    if inside and len(t) > 1:
        out["atm"] = float(math.sqrt(np.interp(years, t, w) / years))
    else:
        out["atm"] = float(usable["atm"].iloc[-1 if years > t[-1] else 0])
    for col in ("rr25", "bf25"):
        s = usable.dropna(subset=[col])
        if s.empty:
            continue
        ts, v = s["tenor"].to_numpy(float), s[col].to_numpy(float)
        out[col] = float(np.interp(years, ts, v))  # flat beyond the ends
    out["extrapolated"] = not inside
    return out


def term_slope(g: pd.DataFrame, short: int = 30, long: int = 90) -> tuple[float, int]:
    """ATM at `long` days minus ATM at `short` days, or at the longest listed tenor when the
    surface stops before `long`. Returns the slope and the long leg's days."""
    usable = g.dropna(subset=["atm"])
    if len(usable) < 2:
        return math.nan, long
    longest = int(usable["dte"].max())
    leg = long if longest >= long else longest
    return at_tenor(g, leg)["atm"] - at_tenor(g, short)["atm"], leg


# --- Gridded views --------------------------------------------------------------------------


def heat(surface: pd.DataFrame, points: np.ndarray) -> pd.DataFrame:
    """IV by expiry (rows) and moneyness K/F - 1 in percent (columns), interpolated within each
    expiry's quoted range and blank outside it: no invented wings."""
    rows = {}
    for expiry, board in surface.groupby("expiry", sort=False):
        b = board.sort_values("log_moneyness")
        x = (b["moneyness"].to_numpy(float) - 1) * 100
        y = b["iv"].to_numpy(float)
        vals = np.interp(points, x, y)
        vals[(points < x[0]) | (points > x[-1])] = np.nan
        rows[expiry] = vals
    return pd.DataFrame.from_dict(rows, orient="index", columns=points)


def mesh(surface: pd.DataFrame, n_strike: int = 45, n_tenor: int = 25):
    """The scattered quotes on a regular grid for the 3D view: moneyness K/F - 1 in percent by
    days to expiry. Linear inside the hull of real quotes, nearest outside it, because a linear
    extrapolation invents wing structure that never traded."""
    from scipy.interpolate import griddata

    if surface.empty or surface["expiry"].nunique() < 2:
        return None
    x = (surface["moneyness"].to_numpy(float) - 1) * 100
    y = surface["dte"].to_numpy(float)
    z = surface["iv"].to_numpy(float)
    xi = np.linspace(np.percentile(x, 2), np.percentile(x, 98), n_strike)
    yi = np.linspace(y.min(), y.max(), n_tenor)
    gx, gy = np.meshgrid(xi, yi)
    zi = griddata((x, y), z, (gx, gy), method="linear")
    gaps = np.isnan(zi)
    if gaps.any():
        zi[gaps] = griddata((x, y), z, (gx[gaps], gy[gaps]), method="nearest")
    return xi, yi, zi
