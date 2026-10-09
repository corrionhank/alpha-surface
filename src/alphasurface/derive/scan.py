"""Scan many option chains at once for the setups usually checked by hand.

The input is one normalized frame, a row per contract across every symbol scanned, plus a
per-symbol context (today's move, realized vols, ATM implied vol) and daily history. Each preset
is a filter set and a rule; each hit carries a sentence saying why, with the numbers in it.
Descriptive like the rest of the app: a hit is a place to look, not a trade.
Rules, formulas and default thresholds: docs/scanner.md.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import norm

from alphasurface import clock
from alphasurface.derive.implied_vol import implied_vol
from alphasurface.derive.market_state import rolling_vol

NY = "America/New_York"
SESSION_MINUTES = 390  # 09:30 to 16:00
TRADING_DAYS = 252
ABS_MOVE = math.sqrt(2 / math.pi)  # E|Z| for a standard normal: a straddle is about 0.8 sigma

HIT_COLUMNS = [
    "symbol",
    "expiry",
    "dte",
    "strike",
    "kind",
    "mark",
    "iv",
    "delta",
    "spread",
    "open_interest",
    "volume",
    "score",
    "reason",
]
CONTRACT = ["symbol", "expiry", "strike", "kind"]


# --- Time ---------------------------------------------------------------------------------


def minutes_to_close(now: pd.Timestamp) -> float:
    """Regular-session minutes left today: the whole session before the open, 0 after the
    close, on a weekend or a holiday; half days close at 13:00 (alphasurface.clock, offline)."""
    return clock.minutes_to_close(now)


def _ny_date(ts) -> pd.Timestamp:
    return pd.Timestamp(ts).tz_convert(NY).tz_localize(None).normalize()


# --- Normalizing a pull -------------------------------------------------------------------


def normalize(chain: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """Provider quotes to one row per live contract with mark, spread, distance and dte.

    Mark is the mid of a two-sided market, else the last print (flagged quote="last"). dte is
    calendar days from today in New York; 0 is a same-day expiry.
    """
    df = chain.copy()
    for col in ("underlying_prev", "change", "last_trade"):
        if col not in df:
            df[col] = np.nan
    for col in (
        "strike",
        "bid",
        "ask",
        "last",
        "volume",
        "open_interest",
        "underlying",
        "underlying_prev",
        "change",
    ):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["expiry"] = df["expiry"].astype(str)
    df["dte"] = (pd.to_datetime(df["expiry"]) - _ny_date(now)).dt.days
    df = df[df["dte"] >= 0].copy()

    two_sided = (df["bid"] > 0) & (df["ask"] > df["bid"])
    df["mark"] = np.where(two_sided, (df["bid"] + df["ask"]) / 2, df["last"].where(df["last"] > 0))
    df["quote"] = np.where(two_sided, "mid", "last")
    df["spread"] = (df["ask"] - df["bid"]).where(two_sided)
    df["spread_pct"] = df["spread"] / df["mark"]
    df["spot"] = df["underlying"]
    df["distance"] = df["strike"] / df["spot"] - 1
    df["spot_change"] = df["spot"] / df["underlying_prev"] - 1
    df["volume"] = df["volume"].fillna(0)
    df["open_interest"] = df["open_interest"].fillna(0)
    return df.reset_index(drop=True)


def add_greeks(df: pd.DataFrame, r: float, q: float, minutes_left: float) -> pd.DataFrame:
    """Our own implied vol and Black-Scholes delta, gamma and theta for every row.

    Tenor is calendar days / 365, the app's convention, except for same-day expiries, which
    use the session clock: minutes left / 390 / 252 of a trading year. That makes a 0DTE IV
    directly comparable with realized vol, which is annualized over trading days too.
    """
    df = df.copy()
    session = minutes_left / SESSION_MINUTES / TRADING_DAYS
    df["tenor"] = np.where(df["dte"] > 0, df["dte"] / 365, session)
    df["iv"] = [
        implied_vol(m, s, k, t, r, q, kind) if m > 0 and t > 0 else math.nan
        for m, s, k, t, kind in zip(
            df["mark"], df["spot"], df["strike"], df["tenor"], df["kind"], strict=False
        )
    ]
    S, K, T, v = (df[c].to_numpy(float) for c in ("spot", "strike", "tenor", "iv"))
    ok = (T > 0) & (v > 0)
    Ts, vs = np.where(ok, T, 1.0), np.where(ok, v, 1.0)
    d1 = (np.log(S / K) + (r - q + 0.5 * vs**2) * Ts) / (vs * np.sqrt(Ts))
    d2 = d1 - vs * np.sqrt(Ts)
    call = (df["kind"] == "call").to_numpy()
    dq, dr = np.exp(-q * Ts), np.exp(-r * Ts)
    delta = np.where(call, dq * norm.cdf(d1), -dq * norm.cdf(-d1))
    gamma = dq * norm.pdf(d1) / (S * vs * np.sqrt(Ts))
    common = -S * dq * norm.pdf(d1) * vs / (2 * np.sqrt(Ts))
    theta = np.where(
        call,
        common - r * K * dr * norm.cdf(d2) + q * S * dq * norm.cdf(d1),
        common + r * K * dr * norm.cdf(-d2) - q * S * dq * norm.cdf(-d1),
    )
    df["delta"] = np.where(ok, delta, np.nan)
    df["gamma"] = np.where(ok, gamma, np.nan)
    # Per calendar day; a same-day option's decay is in its tenor, not in a daily theta.
    df["theta_day"] = np.where(ok & (df["dte"] > 0).to_numpy(), theta / 365, np.nan)
    return df


def attach_reference(
    df: pd.DataFrame, prev: pd.DataFrame | None, now: pd.Timestamp
) -> pd.DataFrame:
    """What each contract and its underlying were worth before, to measure the move since.

    First choice is our own last stored quote (prev, from storage.reader.previous_chain). Where
    there is none, the vendor's prior close: an option with no trade today still sits at its
    last print, otherwise last minus the vendor's change. elapsed_days feeds the theta term.
    """
    df = df.copy()
    df["ref_mark"] = np.nan
    df["ref_spot"] = np.nan
    df["ref_source"] = None
    df["elapsed_days"] = np.nan

    if prev is not None and not prev.empty:
        p = prev.copy()
        two = (p["bid"] > 0) & (p["ask"] > p["bid"])
        p["ref_mark"] = np.where(two, (p["bid"] + p["ask"]) / 2, p["last"].where(p["last"] > 0))
        p["ref_spot"] = p["underlying"]
        p["ref_time"] = pd.to_datetime(p["collected_at"], utc=True)
        p["expiry"] = p["expiry"].astype(str)
        p["strike"] = p["strike"].astype(float)
        p = p[[*CONTRACT, "ref_mark", "ref_spot", "ref_time"]].drop_duplicates(CONTRACT)
        df = df.drop(columns=["ref_mark", "ref_spot"]).merge(p, on=CONTRACT, how="left")
        hit = df["ref_mark"].notna()
        df.loc[hit, "ref_source"] = "last stored pull"
        df.loc[hit, "elapsed_days"] = (
            pd.Timestamp(now) - df.loc[hit, "ref_time"]
        ).dt.total_seconds() / 86400
        df = df.drop(columns="ref_time")

    gap = df["ref_mark"].isna() & df["underlying_prev"].notna() & (df["last"] > 0)
    if gap.any():
        traded_today = pd.to_datetime(df["last_trade"], utc=True, errors="coerce")
        traded_today = traded_today.dt.tz_convert(NY).dt.date == _ny_date(now).date()
        prior = np.where(traded_today, df["last"] - df["change"], df["last"])
        df.loc[gap, "ref_mark"] = pd.Series(prior, index=df.index)[gap]
        df.loc[gap, "ref_spot"] = df.loc[gap, "underlying_prev"]
        df.loc[gap, "ref_source"] = "prior close"
        df.loc[gap, "elapsed_days"] = 1.0
    df.loc[~(df["ref_mark"] > 0), ["ref_mark", "ref_spot"]] = np.nan
    return df


# --- Per-symbol context ---------------------------------------------------------------------


def daily_closes(bars: pd.DataFrame) -> pd.Series:
    """Daily closes indexed by New York date."""
    if bars is None or bars.empty:
        return pd.Series(dtype=float)
    dates = pd.to_datetime(bars["ts"], utc=True).dt.tz_convert(NY).dt.date
    return pd.Series(bars["close"].to_numpy(float), index=dates).groupby(level=0).last()


def atm_iv(
    rows: pd.DataFrame, r: float, q: float, target_dte: int = 30
) -> tuple[float, str | None, float]:
    """ATM implied vol of one symbol from normalized rows: the expiry nearest target_dte with at
    least 5 days left (else the nearest with any), the strike nearest spot, IV solved for just
    that call and put and averaged. Returns (iv, expiry, strike)."""
    d = rows[rows["mark"] > 0]
    pool = d[d["dte"] >= 5] if (d["dte"] >= 5).any() else d[d["dte"] >= 1]
    if pool.empty:
        return math.nan, None, math.nan
    expiry = pool.loc[(pool["dte"] - target_dte).abs().idxmin(), "expiry"]
    board = pool[pool["expiry"] == expiry]
    strike = float(board.loc[(board["strike"] - board["spot"]).abs().idxmin(), "strike"])
    ivs = [
        implied_vol(m, sp, strike, dte / 365, r, q, kind)
        for m, sp, dte, kind in board.loc[
            board["strike"] == strike, ["mark", "spot", "dte", "kind"]
        ].itertuples(index=False)
    ]
    ivs = [v for v in ivs if v > 0]
    return (float(np.mean(ivs)) if ivs else math.nan), expiry, strike


def symbol_context(
    base: pd.DataFrame,
    history: dict[str, pd.DataFrame],
    r: float,
    q: float,
    prev_atm: dict[str, float] | None = None,
) -> pd.DataFrame:
    """One row per symbol: spot, today's move, realized vols over 5/10/21/63 sessions, ATM IV
    now and at the last stored pull. base is the full normalized pull, before any filter, so
    every symbol scanned has a context. Today's spot is appended to the closes when history ends
    before today, so a move in progress counts in the short windows."""
    rows = []
    today = pd.Timestamp.now(tz=NY).date()
    for symbol, g in base.groupby("symbol"):
        spot = float(g["spot"].iloc[0])
        prev_close = (
            float(g["underlying_prev"].iloc[0]) if g["underlying_prev"].notna().any() else math.nan
        )
        closes = daily_closes(history.get(symbol))
        if not prev_close > 0 and (closes.index < today).any():
            prev_close = float(closes[closes.index < today].iloc[-1])
        if len(closes) and closes.index[-1] < today and spot > 0:
            closes = pd.concat([closes, pd.Series([spot], index=[today])])
        row = {
            "symbol": symbol,
            "spot": spot,
            "prev_close": prev_close,
            "change": spot / prev_close - 1 if prev_close > 0 else math.nan,
        }
        for w in (5, 10, 21, 63):
            row[f"rv{w}"] = (
                float(rolling_vol(closes, w).iloc[-1]) / 100 if len(closes) > w else math.nan
            )
        row["atm_iv"], row["atm_expiry"], row["atm_strike"] = atm_iv(g, r, q)
        row["atm_dte"] = (
            int(g.loc[g["expiry"] == row["atm_expiry"], "dte"].iloc[0]) if row["atm_expiry"] else -1
        )
        row["atm_iv_prev"] = (prev_atm or {}).get(symbol, math.nan)
        rows.append(row)
    return pd.DataFrame(rows).set_index("symbol") if rows else pd.DataFrame()


def prev_atm_ivs(prev: pd.DataFrame | None, r: float, q: float) -> dict[str, float]:
    """ATM IV of each symbol at its last stored pull, solved the same way as now."""
    if prev is None or prev.empty:
        return {}
    out = {}
    for symbol, g in prev.groupby("symbol"):
        at = pd.to_datetime(g["collected_at"], utc=True).max()
        out[symbol] = atm_iv(normalize(g, at), r, q)[0]
    return out


def prepare(
    chain: pd.DataFrame,
    now: pd.Timestamp,
    r: float,
    q: float,
    filters: Filters,
    prev: pd.DataFrame | None = None,
    history: dict[str, pd.DataFrame] | None = None,
):
    """Pull to scannable frame: normalize, filter, solve IV and Greeks for the survivors only,
    attach references for the move since, and build the per-symbol context. Returns
    (frame, context)."""
    minutes = minutes_to_close(now)
    base = normalize(chain, now)
    ctx = symbol_context(base, history or {}, r, q, prev_atm_ivs(prev, r, q))
    frame = add_greeks(prefilter(base, filters), r, q, minutes)
    frame["minutes_left"] = minutes
    frame = attach_reference(frame, prev, now)
    return postfilter(frame, filters).reset_index(drop=True), ctx


# --- Filters --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Filters:
    dte_min: int = 0
    dte_max: int = 60
    zero_dte: bool = False  # same-day expiries only
    dist_max: float = 0.15  # |strike / spot - 1|
    delta_min: float = 0.0  # on |delta|
    delta_max: float = 1.0
    min_oi: float = 0.0
    min_volume: float = 0.0
    max_spread: float = math.inf  # dollars
    max_spread_pct: float = math.inf  # of mark
    min_premium: float = 0.0
    side: str = "both"  # call | put | both


def prefilter(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    """Everything that needs no implied vol, so only survivors get solved."""
    keep = df["distance"].abs() <= f.dist_max
    keep &= (df["dte"] == 0) if f.zero_dte else df["dte"].between(f.dte_min, f.dte_max)
    keep &= df["open_interest"] >= f.min_oi
    keep &= df["volume"] >= f.min_volume
    keep &= df["mark"].fillna(0) >= f.min_premium
    if math.isfinite(f.max_spread):
        keep &= df["spread"] <= f.max_spread
    if math.isfinite(f.max_spread_pct):
        keep &= df["spread_pct"] <= f.max_spread_pct
    if f.side in ("call", "put"):
        keep &= df["kind"] == f.side
    return df[keep]


def postfilter(df: pd.DataFrame, f: Filters) -> pd.DataFrame:
    if f.delta_min <= 0 and f.delta_max >= 1:
        return df
    a = df["delta"].abs()
    return df[(a >= f.delta_min) & (a <= f.delta_max)]


# --- Rules ----------------------------------------------------------------------------------


def _hits(rows: pd.DataFrame, score, reason) -> pd.DataFrame:
    out = rows.copy()
    out["score"] = list(score)
    out["reason"] = list(reason)
    for col in HIT_COLUMNS:
        if col not in out:
            out[col] = np.nan
    return out[HIT_COLUMNS].reset_index(drop=True)


def _empty() -> pd.DataFrame:
    return pd.DataFrame(columns=HIT_COLUMNS)


def _symbol_row(symbol: str, c: pd.Series) -> dict:
    return {
        "symbol": symbol,
        "expiry": c.get("atm_expiry"),
        "dte": c.get("atm_dte"),
        "strike": c.get("atm_strike"),
        "iv": c.get("atm_iv"),
    }


def stale_after_move(df, ctx, hist, move_pct=1.0, lag_ratio=0.5, min_spreads=2.0):
    """The underlying moved, the option barely did. Expected change from the Greeks at the
    current IV: delta dS + gamma dS^2 / 2 + theta x days elapsed. A lag smaller than a few
    spreads is just the spread, so it is not reported."""
    d = df[df["ref_mark"].notna() & (df["spread"] > 0) & df["delta"].notna()].copy()
    if d.empty:
        return _empty()
    dS = d["spot"] - d["ref_spot"]
    d["move"] = dS / d["ref_spot"]
    theta = d["theta_day"].fillna(0) * d["elapsed_days"].fillna(0)
    d["expected"] = d["delta"] * dS + 0.5 * d["gamma"] * dS**2 + theta
    d["actual"] = d["mark"] - d["ref_mark"]
    d["lag"] = d["expected"] - d["actual"]
    keep = (d["move"].abs() >= move_pct / 100) & (d["expected"].abs() > 0)
    keep &= np.sign(d["lag"]) == np.sign(d["expected"])
    keep &= d["actual"].abs() <= lag_ratio * d["expected"].abs()
    keep &= d["lag"].abs() >= min_spreads * d["spread"]
    d = d[keep]
    if d.empty:
        return _empty()
    score = d["lag"].abs() / d["spread"]
    reason = [
        f"{r.symbol} {r.move:+.1%} since the {r.ref_source} ({r.ref_spot:.2f} to {r.spot:.2f}). "
        f"The {r.strike:g} {r.kind} moved {r.actual:+.2f}; delta and gamma imply {r.expected:+.2f}. "
        f"Lag {r.lag:+.2f}, {s:.1f}x the {r.spread:.2f} spread."
        for r, s in zip(d.itertuples(), score, strict=False)
    ]
    return _hits(d, score, reason)


def rv_up_iv_asleep(df, ctx, hist, ratio=1.5, short_window=5, long_window=21):
    """Realized vol jumped but implied vol did not follow: ATM IV sits below the short-window
    realized, or fell since the last stored pull while realized rose."""
    short, long = f"rv{int(short_window)}", f"rv{int(long_window)}"
    rows, score, reason = [], [], []
    for sym, c in ctx.iterrows():
        rs, rl, iv, prev = c.get(short), c.get(long), c["atm_iv"], c["atm_iv_prev"]
        if not (rs > 0 and rl > 0 and iv > 0) or rs / rl < ratio:
            continue
        below, fell = iv < rs, prev > 0 and iv < prev
        if not (below or fell):
            continue
        why = []
        if below:
            why.append(f"below the {int(short_window)}-day realized")
        if fell:
            why.append(f"down from {prev:.1%} at the last stored pull")
        rows.append(_symbol_row(sym, c))
        score.append(rs / rl)
        reason.append(
            f"{sym}: {int(short_window)}-day realized vol {rs:.1%} is {rs / rl:.1f}x the "
            f"{int(long_window)}-day ({rl:.1%}), yet ATM IV is {iv:.1%}, " + " and ".join(why) + "."
        )
    return _hits(pd.DataFrame(rows), score, reason) if rows else _empty()


def _vol_gap(df, ctx, window):
    rv = df["symbol"].map(ctx[f"rv{int(window)}"]) if f"rv{int(window)}" in ctx else np.nan
    return rv, (df["iv"] - rv) * 100


def rich_premium(df, ctx, hist, gap_min=5.0, window=21):
    """Implied well above realized: the premium a seller is paid over what the stock has
    actually been doing."""
    d = df[df["iv"].notna()].copy()
    d["rv"], d["gap"] = _vol_gap(d, ctx, window)
    d = d[d["gap"] >= gap_min]
    reason = [
        f"IV {r.iv:.1%} vs {int(window)}-day realized {r.rv:.1%}: {r.gap:+.1f} vol pts. "
        f"Mark {r.mark:.2f}, spread {r.spread:.2f}, OI {r.open_interest:,.0f}."
        for r in d.itertuples()
    ]
    return _hits(d, d["gap"], reason) if len(d) else _empty()


def cheap_convexity(df, ctx, hist, gap_max=-2.0, window=21):
    """Out-of-the-money options priced below what realized vol says they are worth."""
    otm = ((df["kind"] == "call") & (df["strike"] > df["spot"])) | (
        (df["kind"] == "put") & (df["strike"] < df["spot"])
    )
    d = df[otm & df["iv"].notna()].copy()
    d["rv"], d["gap"] = _vol_gap(d, ctx, window)
    d = d[d["gap"] <= gap_max]
    reason = [
        f"OTM {r.kind} {r.distance:+.1%} from spot at IV {r.iv:.1%}, {-r.gap:.1f} vol pts under "
        f"{int(window)}-day realized {r.rv:.1%}. Mark {r.mark:.2f}, delta {r.delta:+.2f}."
        for r in d.itertuples()
    ]
    return _hits(d, -d["gap"], reason) if len(d) else _empty()


def unusual_activity(df, ctx, hist, ratio_min=2.0, notional_min=250_000.0, volume_min=500.0):
    """Volume far above open interest with real money behind it: new positions, not churn."""
    d = df.copy()
    d["ratio"] = d["volume"] / d["open_interest"].clip(lower=1)
    d["notional"] = d["volume"] * d["mark"].fillna(0) * 100
    d = d[(d["ratio"] >= ratio_min) & (d["notional"] >= notional_min) & (d["volume"] >= volume_min)]
    reason = [
        f"{r.volume:,.0f} contracts traded against {r.open_interest:,.0f} open, {r.ratio:.1f}x. "
        f"About ${r.notional:,.0f} of premium at a {r.mark:.2f} mark."
        for r in d.itertuples()
    ]
    return _hits(d, d["ratio"], reason) if len(d) else _empty()


def price_spike(df, ctx, hist, z_min=2.0, window=21):
    """Today's move in units of the stock's own daily realized vol."""
    rows, score, reason = [], [], []
    for sym, c in ctx.iterrows():
        rv, chg = c.get(f"rv{int(window)}"), c["change"]
        if not (rv > 0) or not np.isfinite(chg):
            continue
        daily = rv / math.sqrt(TRADING_DAYS)
        z = math.log1p(chg) / daily
        if abs(z) < z_min:
            continue
        rows.append(_symbol_row(sym, c))
        score.append(abs(z))
        reason.append(
            f"{sym} {chg:+.2%} today, {z:+.1f} standard deviations of its {int(window)}-day "
            f"realized vol ({rv:.1%} a year, {daily:.2%} a day)."
        )
    return _hits(pd.DataFrame(rows), score, reason) if rows else _empty()


def gap_events(bars: pd.DataFrame) -> pd.DataFrame:
    """Every daily gap (open versus prior close) and how many sessions it took to fill.

    A gap up fills when a later low (the same day counts) trades back to the prior close; a gap
    down when a high does. sessions_to_fill is 0 for a same-day fill and NaN if still open.
    """
    if bars is None or len(bars) < 3:
        return pd.DataFrame(columns=["date", "direction", "size", "level", "sessions_to_fill"])
    b = bars.sort_values("ts").reset_index(drop=True)
    dates = pd.to_datetime(b["ts"], utc=True).dt.tz_convert(NY).dt.date
    prev = b["close"].shift(1)
    size = b["open"] / prev - 1
    lows, highs = b["low"].to_numpy(float), b["high"].to_numpy(float)
    out = []
    for i in range(1, len(b)):
        s = size.iloc[i]
        if not np.isfinite(s) or s == 0:
            continue
        level = float(prev.iloc[i])
        hit = np.nonzero(lows[i:] <= level)[0] if s > 0 else np.nonzero(highs[i:] >= level)[0]
        out.append(
            {
                "date": dates.iloc[i],
                "direction": "up" if s > 0 else "down",
                "size": abs(s),
                "level": level,
                "sessions_to_fill": float(hit[0]) if len(hit) else math.nan,
                "age": len(b) - 1 - i,
            }
        )
    return pd.DataFrame(out)


def gap_fill_rate(
    events: pd.DataFrame, direction: str, size: float, horizon: int, band: float = 2.0
) -> tuple[float, int]:
    """Share of past gaps in the same direction, sized within [size/band, size*band], that
    filled within horizon sessions. Gaps too recent to have had the full horizon are left out."""
    if events.empty:
        return math.nan, 0
    pool = events[
        (events["direction"] == direction)
        & events["size"].between(size / band, size * band)
        & (events["age"] >= horizon)
    ]
    if pool.empty:
        return math.nan, 0
    return float((pool["sessions_to_fill"] <= horizon).mean()), len(pool)


def open_gaps(df, ctx, hist, gap_min=0.5, lookback=10, horizon=5):
    """Daily gaps from the last few sessions that have not filled, each with the base rate of
    similar gaps filling, from the symbol's own stored history. A base rate, not a forecast."""
    rows, score, reason = [], [], []
    for sym, c in ctx.iterrows():
        ev = gap_events(hist.get(sym))
        if ev.empty:
            continue
        live = ev[
            (ev["age"] < lookback) & ev["sessions_to_fill"].isna() & (ev["size"] >= gap_min / 100)
        ]
        since = ev["date"].iloc[0].year
        for g in live.itertuples():
            rate, n = gap_fill_rate(ev, g.direction, g.size, int(horizon))
            dist = g.level / c["spot"] - 1 if c["spot"] > 0 else math.nan
            rows.append(_symbol_row(sym, c) | {"strike": g.level})
            score.append(rate if np.isfinite(rate) else 0.0)
            base = (
                f"Of {n} {g.direction} gaps of {g.size / 2:.1%} to {g.size * 2:.1%} since {since}, "
                f"{rate:.0%} filled within {int(horizon)} sessions."
                if n
                else "Too few similar gaps for a base rate."
            )
            when = "today" if g.age == 0 else f"{g.age} session{'s' if g.age > 1 else ''} ago"
            reason.append(
                f"{sym} gapped {g.direction} {g.size:.1%} on {g.date:%b %-d} ({when}) from "
                f"{g.level:.2f} and has not filled; the fill level is {dist:+.1%} from spot. "
                + base
            )
    return _hits(pd.DataFrame(rows), score, reason) if rows else _empty()


def zero_dte(df, ctx, hist, window=21):
    """Same-day expiries: the ATM straddle's implied move to the close against the move
    realized vol implies over the minutes left. Straddle about 0.8 x one standard deviation."""
    d = df[(df["dte"] == 0) & df["mark"].notna()]
    rows, score, reason = [], [], []
    for sym, g in d.groupby("symbol"):
        minutes = float(g["minutes_left"].iloc[0]) if "minutes_left" in g else 0.0
        spot = float(g["spot"].iloc[0])
        both = g.pivot_table(
            index="strike", columns="kind", values="mark", aggfunc="first"
        ).dropna()
        if minutes <= 0 or both.empty or not {"call", "put"} <= set(both.columns):
            continue
        k = both.index[np.abs(both.index - spot).argmin()]
        straddle = float(both.loc[k, "call"] + both.loc[k, "put"])
        rv = ctx.loc[sym].get(f"rv{int(window)}") if sym in ctx.index else math.nan
        sd_rv = (
            spot * rv * math.sqrt(minutes / SESSION_MINUTES / TRADING_DAYS) if rv > 0 else math.nan
        )
        fair = ABS_MOVE * sd_rv
        ratio = straddle / fair if fair > 0 else math.nan
        iv = g[(g["strike"] == k)]["iv"].mean() if "iv" in g else math.nan
        rows.append(
            {
                "symbol": sym,
                "expiry": g["expiry"].iloc[0],
                "dte": 0,
                "strike": k,
                "kind": "straddle",
                "mark": straddle,
                "iv": iv,
            }
        )
        score.append(ratio if np.isfinite(ratio) else 0.0)
        reason.append(
            f"{minutes:.0f} min to the close. ATM {k:g} straddle {straddle:.2f} prices "
            f"about ±{straddle / ABS_MOVE / spot:.2%} (1 SD) to the close; {int(window)}-day "
            f"realized implies a {fair:.2f} straddle, so the market charges {ratio:.2f}x realized."
        )
    return _hits(pd.DataFrame(rows), score, reason) if rows else _empty()


# --- Presets --------------------------------------------------------------------------------


@dataclass(frozen=True)
class Param:
    default: float
    label: str
    step: float = 0.5


@dataclass(frozen=True)
class Preset:
    key: str
    name: str
    about: str
    rule: Callable
    filters: Filters = field(default_factory=Filters)
    params: dict[str, Param] = field(default_factory=dict)
    level: str = "contract"  # contract | symbol
    score: str = "Score"

    def defaults(self) -> dict[str, float]:
        return {k: p.default for k, p in self.params.items()}


PRESETS: dict[str, Preset] = {
    p.key: p
    for p in [
        Preset(
            "stale",
            "Stale after a move",
            "The stock moved but the option has not caught up with what its delta and gamma imply.",
            stale_after_move,
            Filters(dte_min=0, dte_max=45, dist_max=0.10, delta_min=0.15, min_oi=100),
            {
                "move_pct": Param(1.0, "Underlying move at least (%)", 0.25),
                "lag_ratio": Param(0.5, "Option moved at most this share of expected", 0.05),
                "min_spreads": Param(2.0, "Lag at least this many spreads", 0.5),
            },
            score="Lag in spreads",
        ),
        Preset(
            "rv_up",
            "Realized up, IV asleep",
            "Short-window realized vol jumped while ATM implied vol stayed below it or fell.",
            rv_up_iv_asleep,
            Filters(dte_min=5, dte_max=60, dist_max=0.05),
            {
                "ratio": Param(1.5, "Short / long realized at least", 0.1),
                "short_window": Param(5, "Short window (5 or 10)", 5),
                "long_window": Param(21, "Long window (21 or 63)", 42),
            },
            level="symbol",
            score="RV ratio",
        ),
        Preset(
            "rich",
            "Rich premium",
            "Implied well above realized, in the 20 to 45 day, 10 to 30 delta zone premium sellers use.",
            rich_premium,
            Filters(
                dte_min=20,
                dte_max=45,
                dist_max=0.20,
                delta_min=0.10,
                delta_max=0.30,
                min_oi=500,
                max_spread_pct=0.10,
            ),
            {
                "gap_min": Param(5.0, "IV minus RV at least (vol pts)", 0.5),
                "window": Param(21, "Realized window (5, 10, 21, 63)", 1),
            },
            score="IV - RV (pts)",
        ),
        Preset(
            "cheap",
            "Cheap convexity",
            "Out-of-the-money options with implied vol under realized: tails priced below recent movement.",
            cheap_convexity,
            Filters(
                dte_min=7,
                dte_max=60,
                dist_max=0.15,
                delta_min=0.05,
                delta_max=0.35,
                min_oi=100,
                max_spread_pct=0.15,
            ),
            {
                "gap_max": Param(-2.0, "IV minus RV at most (vol pts)", 0.5),
                "window": Param(21, "Realized window (5, 10, 21, 63)", 1),
            },
            score="RV - IV (pts)",
        ),
        Preset(
            "unusual",
            "Unusual activity",
            "Volume well above open interest with meaningful premium behind it.",
            unusual_activity,
            Filters(dte_min=0, dte_max=60, dist_max=0.20),
            {
                "ratio_min": Param(2.0, "Volume / open interest at least", 0.5),
                "notional_min": Param(250_000.0, "Premium traded at least ($)", 50_000.0),
                "volume_min": Param(500.0, "Volume at least", 100.0),
            },
            score="Volume / OI",
        ),
        Preset(
            "spike",
            "Price spikes",
            "Today's move measured in the stock's own daily realized vol.",
            price_spike,
            Filters(dte_min=0, dte_max=45, dist_max=0.05),
            {
                "z_min": Param(2.0, "Move at least (standard deviations)", 0.25),
                "window": Param(21, "Realized window (5, 10, 21, 63)", 1),
            },
            level="symbol",
            score="|z|",
        ),
        Preset(
            "gaps",
            "Open gaps",
            "Recent daily gaps not yet filled, with how often similar gaps filled before.",
            open_gaps,
            Filters(dte_min=0, dte_max=45, dist_max=0.05),
            {
                "gap_min": Param(0.5, "Gap at least (%)", 0.25),
                "lookback": Param(10, "Look back (sessions)", 1),
                "horizon": Param(5, "Base rate horizon (sessions)", 1),
            },
            level="symbol",
            score="Fill base rate",
        ),
        Preset(
            "zero_dte",
            "0DTE map",
            "Same-day expiries: the straddle's move to the close against realized vol's.",
            zero_dte,
            Filters(zero_dte=True, dist_max=0.03),
            {"window": Param(21, "Realized window (5, 10, 21, 63)", 1)},
            level="symbol",
            score="Straddle / RV fair",
        ),
    ]
}


def run(
    preset: Preset,
    frame: pd.DataFrame,
    ctx: pd.DataFrame,
    history: dict[str, pd.DataFrame],
    params: dict | None = None,
) -> pd.DataFrame:
    """Apply one preset's rule to a frame that is already normalized, filtered and has Greeks
    and references attached. Hits sorted by score, highest first."""
    hits = preset.rule(frame, ctx, history, **(preset.defaults() | (params or {})))
    return hits.sort_values("score", ascending=False, na_position="last").reset_index(drop=True)


def describe(hit: pd.Series) -> str:
    """The contract a hit is about, e.g. "QQQ 2026-11-13 600 put"; the symbol alone when the
    hit is about the underlying."""
    parts = [str(hit["symbol"])]
    if isinstance(hit.get("kind"), str) and hit["kind"] in ("call", "put", "straddle"):
        parts += [str(hit["expiry"]), f"{float(hit['strike']):g}", hit["kind"]]
    return " ".join(parts)


def hit_id(preset_key: str, hit: pd.Series) -> str:
    """Stable identity of a hit, for alert de-duplication."""
    strike = "" if pd.isna(hit.get("strike")) else f"{float(hit['strike']):g}"
    return "|".join(
        [
            preset_key,
            str(hit["symbol"]),
            str(hit.get("expiry") or ""),
            strike,
            str(hit.get("kind") or ""),
        ]
    )
