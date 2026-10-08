"""How good does the hunch have to be?

Run: python -m studies.protective_puts.skill

Every signal tested so far failed. That leaves the question the signals were only ever a proxy for:
suppose you simply *knew*, some of the time. You deploy a one-year protective put on a third of the
cycles, and some fraction of those calls are real bear markets. How right do you have to be before
the hedge pays for itself?

This is a hypothetical with perfect hindsight deliberately dialled in, which is why it is honest:
the oracle is the *upper bound* on any forecaster. If a strategy needs 70% precision to break even,
and nothing in the literature forecasts recessions at 70% precision, the strategy is dead, and no
amount of signal engineering will revive it.

It is also just pot odds (docs/formulas.md section 11). The hedge is a bet: you pay premium to win
a payoff, so there is a breakeven hit rate, and the only question is whether you can clear it.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from studies.protective_puts import data, engine, metrics, scenarios
from studies.protective_puts.engine import ROLLS, Strategy

BEAR = -0.15  # a "bear market" is a 15% drawdown some time in the next year
HEDGE = Strategy("1y 5% OTM put", moneyness=0.05, roll_days=ROLLS["annual"])


def bear_ahead(spot: np.ndarray, horizon: int, depth: float = BEAR) -> np.ndarray:
    """True where the index falls more than `depth` from today at some point within the horizon.

    This is the oracle. It reads the future on purpose: it is the thing a forecaster is trying to
    approximate, and it defines the ceiling on what any forecaster could ever be worth.
    """
    n = len(spot)
    out = np.zeros(n, dtype=bool)
    for i in range(n):
        window = spot[i:i + horizon + 1]
        out[i] = (window.min() / spot[i] - 1) < depth
    return out


def forecaster(truth: np.ndarray, precision: float, deploy: float, rng) -> np.ndarray:
    """A hunch with a known hit rate.

    Calls `deploy` of the cycles. Of those calls, `precision` of them are real bears; the rest are
    false alarms drawn from the calm cycles. Precision equal to the base rate is no skill at all.
    """
    n = len(truth)
    calls = int(round(deploy * n))
    true_idx, false_idx = np.flatnonzero(truth), np.flatnonzero(~truth)

    hits = min(int(round(precision * calls)), len(true_idx))
    misses = min(calls - hits, len(false_idx))

    picked = np.concatenate([
        rng.choice(true_idx, hits, replace=False),
        rng.choice(false_idx, misses, replace=False),
    ]).astype(int)
    out = np.zeros(n, dtype=bool)
    out[picked] = True
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="What hit rate does a hedging hunch need?")
    p.add_argument("--years", type=float, default=21.0)
    p.add_argument("--deploy", type=float, default=1 / 3, help="fraction of cycles hedged")
    p.add_argument("--trials", type=int, default=60)
    p.add_argument("--outdir", default="studies/protective_puts/figures")
    args = p.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    from studies.protective_puts import report

    df = data.load(years=args.years)
    rate, spot = df["rate"], df["spot"].to_numpy()
    n, roll = len(df), HEDGE.roll_days

    starts = np.arange(0, n - 1, roll)
    truth_daily = bear_ahead(spot, roll)
    truth = truth_daily[starts]  # was a bear coming, as of each roll date
    base_rate = truth.mean()

    bh = metrics.summarize(engine.run(df, scenarios.BUY_AND_HOLD).equity, rate)
    always = metrics.summarize(engine.run(df, HEDGE).equity, rate)
    oracle = metrics.summarize(
        engine.run(df, HEDGE, hedge_on=np.repeat(truth, roll)[:n]).equity, rate
    )

    print(f"\nSPY {df.index[0]:%Y-%m-%d} to {df.index[-1]:%Y-%m-%d}. "
          f"Hedge: {HEDGE.name}, deployed on {args.deploy:.0%} of the {len(starts)} annual cycles.")
    print(f"A bear ({BEAR:.0%} drawdown within a year) was actually coming on "
          f"{base_rate:.0%} of them. That is the hit rate of a dart board.\n")

    print(f"{'Buy and hold':<26} CAGR {bh['CAGR']:>6.2%}  Sharpe {bh['Sharpe']:.2f}  "
          f"MaxDD {bh['MaxDD']:>6.1%}")
    print(f"{'Always hedged (1y put)':<26} CAGR {always['CAGR']:>6.2%}  "
          f"Sharpe {always['Sharpe']:.2f}  MaxDD {always['MaxDD']:>6.1%}")
    print(f"{'Perfect foresight':<26} CAGR {oracle['CAGR']:>6.2%}  Sharpe {oracle['Sharpe']:.2f}  "
          f"MaxDD {oracle['MaxDD']:>6.1%}   <- the ceiling, hedging only the real bears\n")

    rng = np.random.default_rng(20260714)
    grid = np.round(np.arange(0.2, 1.01, 0.1), 2)
    rows = {}
    for precision in grid:
        runs = [
            metrics.summarize(
                engine.run(
                    df, HEDGE,
                    hedge_on=np.repeat(forecaster(truth, precision, args.deploy, rng), roll)[:n],
                ).equity,
                rate,
            )
            for _ in range(args.trials)
        ]
        rows[precision] = {
            "CAGR": np.mean([r["CAGR"] for r in runs]),
            "Sharpe": np.mean([r["Sharpe"] for r in runs]),
            "MaxDD": np.mean([r["MaxDD"] for r in runs]),
            "Beat B&H": np.mean([r["Sharpe"] > bh["Sharpe"] for r in runs]),
        }
    curve = pd.DataFrame(rows).T.rename_axis("precision")

    print("IF YOUR HUNCH IS RIGHT THIS OFTEN, HEDGING A THIRD OF THE TIME GIVES YOU:")
    print(curve.to_string(formatters={
        "CAGR": "{:.2%}".format, "Sharpe": "{:.3f}".format,
        "MaxDD": "{:.1%}".format, "Beat B&H": "{:.0%}".format,
    }))

    clears = curve[curve["Sharpe"] > bh["Sharpe"]]
    if len(clears):
        need = clears.index[0]
        print(f"\nBreakeven: you need to be right about {need:.0%} of the time for a one-year put, "
              f"deployed {args.deploy:.0%} of the time, to beat buy-and-hold on Sharpe.")
        print(f"A dart board scores {base_rate:.0%}. You must beat that by "
              f"{need - base_rate:+.0%} to add anything at all.")
    else:
        print(f"\nNo precision on the grid beats buy-and-hold on Sharpe. Even perfect foresight "
              f"({oracle['Sharpe']:.2f}) fails to clear {bh['Sharpe']:.2f}.")

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    print("\nFigure:", report.skill_curve(curve, bh, base_rate, oracle, out))
    curve.to_csv(out / "skill-curve.csv")


if __name__ == "__main__":
    main()
