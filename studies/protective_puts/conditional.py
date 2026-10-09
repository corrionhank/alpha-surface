"""Only hedge when a recession signal fires. Ride the rest of the time.

Run: python -m studies.protective_puts.conditional

The always-on hedge loses because it pays premium in the 90% of months that turn out fine. The
obvious fix is to buy protection only when something says a recession is coming. This tests
whether the signals can actually do that, against the only control that matters: random hedging
at the same duty cycle. A signal that hedges 30% of the time will beat the always-on hedge
whatever it does, simply by paying less premium. To have any skill it has to beat its own random
twin, and that is a much higher bar than beating buy-and-hold.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from studies.protective_puts import data, engine, metrics, scenarios, signals
from studies.protective_puts.engine import ROLLS, Strategy

HEDGE = Strategy("5% OTM monthly", moneyness=0.05, roll_days=ROLLS["monthly"])


def random_hedge(n: int, roll_days: int, duty: float, rng: np.random.Generator) -> np.ndarray:
    """A coin flip at each roll, weighted to match the signal's duty cycle."""
    cycles = int(np.ceil(n / roll_days))
    return np.repeat(rng.random(cycles) < duty, roll_days)[:n]


def main() -> None:
    p = argparse.ArgumentParser(description="Hedge only when recession signals fire.")
    p.add_argument("--years", type=float, default=21.0)
    p.add_argument("--skew", type=float, default=0.5)
    p.add_argument("--term-premium", type=float, default=0.025)
    p.add_argument("--dividend-yield", type=float, default=0.018)
    p.add_argument(
        "--percentile",
        type=float,
        default=0.80,
        help="how extreme a reading has to be to count, default 80th percentile",
    )
    p.add_argument("--trials", type=int, default=200, help="random-timing trials per signal")
    p.add_argument("--outdir", default="studies/protective_puts/figures")
    p.add_argument("--no-figures", action="store_true")
    p.add_argument("--show", action="store_true")
    args = p.parse_args()

    import matplotlib

    if not args.show:
        matplotlib.use("Agg")
    from studies.protective_puts import report

    df = data.load(years=args.years)
    flags = signals.build(df.index, df["spot"], percentile=args.percentile)
    rate = df["rate"]

    print(
        f"\nSPY daily, {df.index[0]:%Y-%m-%d} to {df.index[-1]:%Y-%m-%d} "
        f"({len(df):,} sessions). Hedge: {HEDGE.name}, bought only when the signal is on."
    )
    print(
        f"Signals are point-in-time: expanding percentiles at the {args.percentile:.0%} level, "
        "each series lagged by its real publication delay.\n"
    )

    def run(name, hedge_on=None, strategy=HEDGE):
        res = engine.run(
            df,
            strategy,
            skew_slope=args.skew,
            term_premium=args.term_premium,
            dividend_yield=args.dividend_yield,
            hedge_on=hedge_on,
        )
        return engine.Result(
            name, res.equity, res.premium_paid, res.payoff_received, res.cycles, res.hedged_cycles
        )

    baselines = [run("Buy and hold", strategy=scenarios.BUY_AND_HOLD), run("Always hedged")]
    conditional = [run(col, flags[col].to_numpy()) for col in flags.columns]

    table = metrics.table(baselines + conditional, rate)
    table["Hedged"] = [r.duty_cycle for r in baselines + conditional]
    print("WHEN TO PUT THE HEDGE ON")
    print(
        metrics.render(
            table[
                ["CAGR", "Vol", "Sharpe", "MaxDD", "Calmar", "Premium", "Recovery", "Hedged"]
            ].rename(columns={"Hedged": "Duty"})
        ),
        "\n",
    )

    # The control. Does the signal beat a coin flip that hedges just as often?
    print(
        f"SKILL TEST: each signal against {args.trials} random-timing twins at the same duty cycle"
    )
    rng = np.random.default_rng(20260713)
    skill, draws = {}, {}
    for res in conditional:
        if res.duty_cycle in (0.0, 1.0):
            continue
        sharpes = np.array(
            [
                metrics.summarize(
                    run("r", random_hedge(len(df), HEDGE.roll_days, res.duty_cycle, rng)).equity,
                    rate,
                )["Sharpe"]
                for _ in range(args.trials)
            ]
        )
        actual = metrics.summarize(res.equity, rate)["Sharpe"]
        draws[res.name] = sharpes
        skill[res.name] = {
            "Duty": res.duty_cycle,
            "Sharpe": actual,
            "Random mean": sharpes.mean(),
            "Random best": sharpes.max(),
            "Beats": (sharpes < actual).mean(),
        }
    skill_df = pd.DataFrame(skill).T
    print(
        skill_df.to_string(
            formatters={
                "Duty": "{:.0%}".format,
                "Sharpe": "{:.3f}".format,
                "Random mean": "{:.3f}".format,
                "Random best": "{:.3f}".format,
                "Beats": "{:.0%}".format,
            }
        )
    )
    print(
        "\n'Beats' is the share of random twins the signal outperformed. 50% is a coin flip:\n"
        "the signal is doing nothing that hedging less often would not have done by itself.\n"
    )

    if not args.no_figures:
        out = Path(args.outdir)
        out.mkdir(parents=True, exist_ok=True)
        paths = [
            report.equity_curves(baselines + conditional, out, "07-conditional.png"),
            report.signal_timeline(flags, df["spot"], out),
            report.skill_histograms(draws, skill, out),
        ]
        print("Figures:")
        for path in paths:
            print(f"  {path}")
        if args.show:
            report.show()


if __name__ == "__main__":
    main()
