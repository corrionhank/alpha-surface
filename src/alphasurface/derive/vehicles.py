"""Options or the underlying: the same directional idea expressed several ways, side by side.

For a target move over a horizon, each vehicle (shares, a delta-one position on margin standing
in for a future, and calls or puts at a few strikes) is marked at the target, at an unchanged
price, and across simulated paths. The comparison is what each one costs, what it makes if the
idea is right, what it loses if nothing happens, and how its outcomes spread. It informs the
choice of instrument; it does not say whether to take the trade.

Time is in trading days (derive.positions' clock). Options are valued with implied vol held
where it is at entry. Shares short on 50% Reg T margin; the delta-one position on the margin
given. Formulas: docs/scanner.md, "Options or the underlying".
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from alphasurface.derive import positions as pos
from alphasurface.derive import simulate as sim

REG_T = 0.5


def vehicles(
    spot: float, move: float, margin: float
) -> list[tuple[str, list[pos.Leg], float | None]]:
    """(name, legs, capital override). Option capital is the premium, worked out on pricing."""
    bull = move >= 0
    kind = "call" if bull else "put"
    lot = 1 if bull else -1
    step = pos.strike_step(spot)

    def k(m: float) -> float:
        return round(spot * (1 + m) / step) * step

    stock = [pos.Leg("stock", 0, lot)]
    out = [
        (
            "Shares, 100" if bull else "Short shares, 100",
            stock,
            100 * spot * (1 if bull else REG_T),
        ),
        (f"Delta one, {margin:.0%} margin", stock, 100 * spot * margin),
    ]
    strikes = {"ITM": k(-move / 2), "ATM": k(0), "Halfway": k(move / 2), "At target": k(move)}
    seen = set()
    for label, strike in strikes.items():
        if strike in seen:
            continue
        seen.add(strike)
        out.append((f"{label} {kind} {strike:g}", [pos.Leg(kind, strike, 1)], None))
    return out


def _breakeven(grid: np.ndarray, pnl: np.ndarray, toward_up: bool) -> float:
    """First price at which the P&L crosses zero, searching away from spot in the trade's
    direction. NaN if it never does on the grid."""
    order = np.arange(len(grid)) if toward_up else np.arange(len(grid))[::-1]
    sign = np.sign(pnl[order])
    flips = np.nonzero(np.diff(sign) > 0)[0]
    if not len(flips):
        return math.nan
    i, j = order[flips[0]], order[flips[0] + 1]
    return float(np.interp(0, [pnl[i], pnl[j]], [grid[i], grid[j]]))


def compare(
    spot: float,
    move: float,
    days: int,
    expiry_days: int,
    iv: float,
    r: float,
    q: float,
    margin: float = 0.10,
    sim_vol: float | None = None,
    drift_to_target: bool = False,
    n_paths: int = 4000,
    seed: int = 7,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (table, curves). curves is P&L at the horizon across a price grid, one column per
    vehicle. sim_vol defaults to iv. drift_to_target sets the drift so the median path ends at
    the target; otherwise paths drift at r - q, the market's own neutral world."""
    if expiry_days < days:
        raise ValueError("the options must not expire before the horizon")
    sim_vol = sim_vol or iv
    target = spot * (1 + move)
    left = expiry_days - days
    t = days / pos.TRADING_DAYS
    width = 3 * max(iv, sim_vol) * math.sqrt(max(t, 1 / pos.TRADING_DAYS))
    grid = np.linspace(spot * (1 - width), spot * (1 + width), 241)

    mu = (math.log1p(move) / t + sim_vol**2 / 2) if drift_to_target and t > 0 else r - q
    ends = sim.gbm(spot, mu, sim_vol, days, n_paths, np.random.default_rng(seed))[:, -1]

    rows, curves = [], {}
    for name, legs, capital in vehicles(spot, move, margin):
        entry = float(pos.value(legs, np.array([spot]), expiry_days, r, iv, q)[0])
        option = legs[0].kind != "stock"
        capital = abs(entry) if option else capital

        def at(S, legs=legs, entry=entry):
            return pos.value(legs, np.asarray(S, float), left, r, iv, q) - entry

        curve = at(grid)
        outcomes = at(ends)
        var, _ = sim.var_cvar(outcomes, 0.95)
        delta = (
            float(
                pos.bs_delta(
                    spot, legs[0].strike, expiry_days / pos.TRADING_DAYS, r, iv, q, legs[0].kind
                )
            )
            * 100
            if option
            else 100.0 * legs[0].qty
        )
        be = _breakeven(grid, curve, move >= 0)
        pnl_target = float(at([target])[0])
        rows.append(
            {
                "Vehicle": name,
                "Capital": capital,
                "Delta, shares": delta,
                "P&L at target": pnl_target,
                "Return at target": pnl_target / capital if capital else math.nan,
                "P&L if flat": float(at([spot])[0]),
                "Max loss": abs(entry) if option else (100 * spot if move >= 0 else math.inf),
                "Breakeven": be,
                "Breakeven move": be / spot - 1 if np.isfinite(be) else math.nan,
                "EV, simulated": float(outcomes.mean()),
                "P(profit)": float((outcomes > 0).mean()),
                "VaR 95%": var,
            }
        )
        curves[name] = curve
    return pd.DataFrame(rows), pd.DataFrame(curves, index=pd.Index(grid, name="price"))
