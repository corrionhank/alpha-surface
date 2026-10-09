"""Deploy protection when the market looks stretched.

Run: python -m studies.protective_puts.exhaustion

The thesis: after an extended run, a reversal is more likely, so buy a put. "Extended" is measured
three ways, all pointing at the same idea from different angles:

  MOMENTUM. A big price run-up. Standardize the trailing k-day return into a z-score and fire when
  it clears N sigma. The operator's own framing: 3-sigma up-move on the 3-month, hedge with a
  3-month put; 6-month run-up, hedge with a one-year put.

  COMPLACENCY. VIX sitting at a low percentile of its own history. Protection is cheap and nobody
  is scared, which the thesis says is exactly when a top forms.

  TERM STRUCTURE. Steep contango (VIX3M well above VIX). The vol market is pricing calm ahead, so
  the tails are on sale.

Every one of these is a timing claim, and a timing claim has exactly one crux: does the signal
predict a bear better than a coin? So this module leads with conditional precision and only then
runs a backtest. If a 3-sigma up-move is followed by a bear no more often than a random day is,
no choice of strike or tenor rescues it, and the precision table says so before the equity curve
gets a chance to mislead.

Everything point-in-time: expanding statistics, shifted a day. See PROTOCOL.md for why this is
exploratory and not a finding.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

from studies.protective_puts import data, engine, metrics, scenarios
from studies.protective_puts.engine import ROLLS, Strategy
from studies.protective_puts.skill import bear_ahead

TRADING_DAYS = 252


def zscore(spot: pd.Series, lookback: int, min_periods: int = 252) -> pd.Series:
    """Point-in-time z-score of the trailing `lookback`-day return.

    The mean and std are expanding and shifted, so the reading on any day is standardized only
    against returns that had already happened. A 3-sigma up-move is z > 3 here.
    """
    ret = spot.pct_change(lookback)
    mu = ret.expanding(min_periods).mean().shift(1)
    sd = ret.expanding(min_periods).std().shift(1)
    return (ret - mu) / sd


def vix_percentile(vix: pd.Series, min_periods: int = 252) -> pd.Series:
    """Where VIX sits in its own expanding history, as a point-in-time percentile in [0, 1]."""
    return (
        vix.expanding(min_periods)
        .apply(lambda w: (w[:-1] < w[-1]).mean() if len(w) > 1 else np.nan, raw=True)
        .shift(1)
    )


def episodes(signal: pd.Series) -> int:
    """Distinct events, not signal-days. Overlapping windows make a single run-up fire for weeks,
    and counting those days as independent samples fakes statistical power. This counts rising
    edges instead, which is the number the confidence interval should rest on.
    """
    s = signal.fillna(False).astype(bool).to_numpy()
    return int((s[1:] & ~s[:-1]).sum() + (1 if len(s) and s[0] else 0))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion. Honest at small n, where the normal approx is not."""
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def precision(signal: pd.Series, truth: np.ndarray) -> dict:
    """Does the signal, on its rising edge, predict a bear inside the horizon?

    Measured on episodes, not days, so a run-up that fires for a month counts once. Precision is
    P(bear ahead | signal just fired); lift is precision minus the base rate. Lift at or below zero
    means the signal is worthless or backwards.
    """
    s = signal.fillna(False).astype(bool).to_numpy()
    edges = np.flatnonzero(s & ~np.r_[False, s[:-1]])
    edges = edges[edges < len(truth)]
    n = len(edges)
    hits = int(truth[edges].sum()) if n else 0
    base = float(truth.mean())
    prec = hits / n if n else math.nan
    lo, hi = wilson(hits, n)
    return {
        "events": n,
        "precision": prec,
        "base_rate": base,
        "lift": prec - base if n else math.nan,
        "ci_lo": lo,
        "ci_hi": hi,
        # The signal beats the dart board only if the whole CI clears the base rate.
        "beats_base": bool(n and lo > base),
    }


# (name, lookback days, sigma, put tenor days) -- the operator's matched pairs plus a sigma sweep.
MOMENTUM = [
    ("3m runup 2.0sig -> 3m put", 63, 2.0, ROLLS["quarterly"]),
    ("3m runup 2.5sig -> 3m put", 63, 2.5, ROLLS["quarterly"]),
    ("3m runup 3.0sig -> 3m put", 63, 3.0, ROLLS["quarterly"]),
    ("6m runup 2.0sig -> 1y put", 126, 2.0, ROLLS["annual"]),
    ("6m runup 2.5sig -> 1y put", 126, 2.5, ROLLS["annual"]),
    ("12m runup 2.0sig -> 1y put", 252, 2.0, ROLLS["annual"]),
]


def main() -> None:
    p = argparse.ArgumentParser(description="Hedge when the market looks stretched.")
    p.add_argument("--years", type=float, default=21.0)
    p.add_argument("--trials", type=int, default=120)
    p.add_argument("--outdir", default="studies/protective_puts/figures")
    p.add_argument("--no-figures", action="store_true")
    args = p.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    from studies.protective_puts import report

    df = data.load(years=args.years)
    spot, vix, rate = df["spot"], df["vix"], df["rate"]
    n = len(df)
    rng = np.random.default_rng(20260715)

    print(
        f"\nEXHAUSTION HEDGING. SPY {df.index[0]:%Y-%m-%d} to {df.index[-1]:%Y-%m-%d}, "
        f"{n:,} sessions. Exploratory (see PROTOCOL.md)."
    )

    # Pre-compute the oracle bear labels once per horizon used below.
    truth = {h: bear_ahead(spot.to_numpy(), h) for h in (ROLLS["quarterly"], ROLLS["annual"])}

    # --- THE CRUX: conditional precision, before any backtest. ---
    print(
        "\nCRUX: after the signal fires, is a bear (15% drawdown within the put's tenor) "
        "more likely than at a random moment?"
    )
    diag = {}
    for name, look, sigma, tenor in MOMENTUM:
        sig = zscore(spot, look) > sigma
        diag[name] = precision(sig, truth[tenor])
    # Cross-asset signals, judged over the one-year horizon.
    vp = vix_percentile(vix)
    diag["VIX < 20th pct (complacent)"] = precision((vp < 0.20).shift(1), truth[ROLLS["annual"]])
    diag["VIX < 10th pct (very calm)"] = precision((vp < 0.10).shift(1), truth[ROLLS["annual"]])
    diag["Steep contango >10%"] = precision(
        (df.get("vix3m") / vix > 1.10).shift(1), truth[ROLLS["annual"]]
    )

    tbl = pd.DataFrame(diag).T
    print(
        tbl.to_string(
            formatters={
                "events": "{:.0f}".format,
                "precision": "{:.0%}".format,
                "base_rate": "{:.0%}".format,
                "lift": "{:+.0%}".format,
                "ci_lo": "{:.0%}".format,
                "ci_hi": "{:.0%}".format,
                "beats_base": "{}".format,
            }
        )
    )
    print(
        "\n'events' is the number of distinct signals in 21 years, not signal-days. A handful of "
        "events cannot support any claim, and 'beats_base' is only True if the whole Wilson\n"
        "interval clears the base rate. Read this table before the backtest below."
    )

    # --- The backtest, which only matters for signals that cleared the crux. ---
    print("\nBACKTEST (event-driven: buy a 5% OTM put the day the signal fires, hold to expiry):")
    bh = engine.run(df, scenarios.BUY_AND_HOLD)
    rows = {"Buy and hold": _stats(bh, rate)}
    for name, look, sigma, tenor in MOMENTUM:
        entries = _rising_edge((zscore(spot, look) > sigma).shift(1).fillna(False).to_numpy())
        strat = Strategy(name, moneyness=0.05, roll_days=tenor)
        res = engine.run_events(df, strat, entries)
        row = _stats(res, rate)
        # Control: fire the same number of puts on random days, held for the same tenor.
        if res.hedged_cycles and args.trials:
            twins = [
                metrics.summarize(
                    engine.run_events(
                        df, strat, _random_entries(n, res.hedged_cycles, tenor, rng)
                    ).equity,
                    rate,
                )["Sharpe"]
                for _ in range(args.trials)
            ]
            row["Beats random"] = float(np.mean(np.array(twins) < row["Sharpe"]))
        rows[name] = row

    bt = pd.DataFrame(rows).T
    print(
        bt.to_string(
            formatters={
                "CAGR": "{:.2%}".format,
                "Sharpe": "{:.3f}".format,
                "MaxDD": "{:.1%}".format,
                "N hedges": "{:.0f}".format,
                "Beats random": lambda v: "n/a" if pd.isna(v) else f"{v:.0%}",
            }
        )
    )

    if not args.no_figures:
        out = Path(args.outdir)
        out.mkdir(parents=True, exist_ok=True)
        print(
            "\nFigure:",
            report.precision_bars(tbl, out, title="Does a stretched market predict a bear?"),
        )
    tbl.to_csv(Path(args.outdir) / "exhaustion-precision.csv")


def _rising_edge(signal: np.ndarray) -> np.ndarray:
    """Keep only the first day of each True run. run_events ignores signals during a hold anyway,
    but this makes the entry count equal the number of distinct events."""
    return signal & ~np.r_[False, signal[:-1]]


def _random_entries(n: int, count: int, tenor: int, rng) -> np.ndarray:
    """`count` entries on random days, spaced at least a tenor apart so they cannot overlap and
    each one actually fires. The matched-frequency control for an event-driven hedge."""
    out = np.zeros(n, dtype=bool)
    slots = np.arange(0, n - 1, tenor)
    if len(slots) >= count:
        for s in rng.choice(slots, count, replace=False):
            out[s] = True
    return out


def _stats(res, rate) -> dict:
    s = metrics.summarize(res.equity, rate)
    return {
        "CAGR": s["CAGR"],
        "Sharpe": s["Sharpe"],
        "MaxDD": s["MaxDD"],
        "N hedges": res.hedged_cycles,
        "Beats random": np.nan,
    }


if __name__ == "__main__":
    main()
