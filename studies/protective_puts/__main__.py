"""Do protective puts actually protect you?

Run: python -m studies.protective_puts
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from studies.protective_puts import data, engine, metrics, scenarios


def crisis_drawdowns(results, windows) -> dict:
    """Peak-to-trough of each strategy inside each crisis window."""
    out = {}
    for label, (start, end) in windows.items():
        sliced = {}
        for res in results:
            equity = res.equity.loc[start:end]
            if equity.empty:
                continue
            sliced[res.name] = float((equity / equity.cummax() - 1).min())
        if sliced:
            out[label] = sliced
    return out


def main() -> None:
    p = argparse.ArgumentParser(description="Protective put study on 21 years of S&P 500 data.")
    p.add_argument("--years", type=float, default=21.0, help="lookback, default 21")
    p.add_argument(
        "--skew", type=float, default=0.5, help="vol points per 1%% OTM added to VIX, default 0.5"
    )
    p.add_argument(
        "--term-premium",
        type=float,
        default=0.025,
        help="vol points added at a 1-year tenor, since VIX is 30-day. Default 0.025",
    )
    p.add_argument("--dividend-yield", type=float, default=0.018)
    p.add_argument("--capital", type=float, default=10_000.0)
    p.add_argument("--outdir", default="studies/protective_puts/figures")
    p.add_argument("--no-figures", action="store_true")
    p.add_argument("--show", action="store_true", help="open the figures in matplotlib windows")
    args = p.parse_args()

    # Pick the backend before pyplot is imported, or Agg is locked in and --show draws nothing.
    import matplotlib

    if not args.show:
        matplotlib.use("Agg")
    from studies.protective_puts import report

    df = data.load(years=args.years)
    span = f"{df.index[0]:%Y-%m-%d} to {df.index[-1]:%Y-%m-%d}"
    years = (df.index[-1] - df.index[0]).days / 365.25
    print(f"\nSPY daily, {span} ({years:.1f} years, {len(df):,} sessions)")
    print(
        f"Puts priced at VIX + {args.skew} vol points per 1% OTM, "
        f"+{args.term_premium:.1%} vol at 1y tenor, dividends {args.dividend_yield:.1%}, "
        f"marked to model daily.\n"
    )

    def run_all(strategies, skew=None):
        return [
            engine.run(
                df,
                s,
                skew_slope=args.skew if skew is None else skew,
                dividend_yield=args.dividend_yield,
                capital=args.capital,
                term_premium=args.term_premium,
            )
            for s in strategies
        ]

    ladder = run_all(scenarios.LADDER)
    print("SCENARIO 1: which strike do you buy?")
    print(metrics.render(metrics.table(ladder, df["rate"])), "\n")

    cadence = run_all(scenarios.CADENCE)
    print("SCENARIO 2: how often do you roll?")
    print(metrics.render(metrics.table(cadence, df["rate"])), "\n")

    crises = crisis_drawdowns(ladder, scenarios.CRISES)
    print("SCENARIO 3: what did it buy you in the tails?")
    print((pd.DataFrame(crises) * 100).round(1).to_string(), "\n")

    print("SCENARIO 4: how much rides on the skew assumption?")
    sweep = {}
    for strategy in scenarios.LADDER[1:]:
        by_slope = {}
        for slope in scenarios.SKEW_SWEEP:
            res = engine.run(
                df,
                strategy,
                skew_slope=slope,
                dividend_yield=args.dividend_yield,
                capital=args.capital,
                term_premium=args.term_premium,
            )
            by_slope[slope] = metrics.summarize(res.equity, df["rate"])["CAGR"]
        sweep[strategy.name] = by_slope
    print((pd.DataFrame(sweep) * 100).round(2).rename_axis("skew slope").to_string(), "\n")

    if not args.no_figures:
        out = Path(args.outdir)
        out.mkdir(parents=True, exist_ok=True)
        paths = [
            report.equity_curves(ladder, out),
            report.drawdowns(ladder, out),
            report.cost_of_protection(ladder, out),
            report.skew_sensitivity(sweep, out),
            report.crisis_bars(crises, out),
            report.cadence_curves(cadence, out),
        ]
        print("Figures:")
        for path in paths:
            print(f"  {path}")
        if args.show:
            print("\nClose the windows to exit.")
            report.show()


if __name__ == "__main__":
    main()
