"""Every method across five 5-year regime windows.

Run: python -m studies.protective_puts.regimes

The whole study leaned on 2008 and 2020, so the honest question is: does each method work in
every regime, or only in the crash windows? This runs each method once over the full 2001-2026
history (so the point-in-time signals keep their pre-window context), then buckets the daily
returns into five non-overlapping 5-year windows and scores each method inside each one, against
buy-and-hold in that same window.

The expected and actual answer: defensive overlays earn their keep in the crash regimes and cost
return in the calm bull regimes. "Protection is nearly free" is a full-sample average that hides
this. Exploratory (PROTOCOL.md).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from studies.protective_puts import data, engine, frontier, metrics, scenarios
from studies.protective_puts.engine import ROLLS, Strategy

# (label, short regime description) for each 5-year block, in order from the start.
REGIMES = [
    "Post-dotcom recovery",
    "GFC crash & rebound",
    "QE bull, low vol",
    "Bull + COVID crash",
    "Inflation bear + AI bull",
]


def methods(df) -> dict:
    """name -> full-history equity curve. One representative per family."""
    return {
        "Buy & hold": engine.run(df, scenarios.BUY_AND_HOLD).equity,
        "Always-hedged put": engine.run(
            df, Strategy("put", moneyness=0.05, roll_days=ROLLS["monthly"])
        ).equity,
        "Vol target 15%": engine.run_vol_target(df, target=0.15, max_exposure=1.5).equity,
        "De-risk on 2σ drop": engine.run_exposure(
            df, frontier.downside_derisk(df, 21, 2.0, off=0.0, hold=63), "d"
        ).equity,
        "Trend 200d": engine.run_exposure(df, frontier.trend_ma(df, 200, 0.0), "t").equity,
        "TS momentum 126d": engine.run_exposure(df, frontier.ts_momentum(df, 126, 0.0), "m").equity,
    }


def windows(index: pd.DatetimeIndex, n: int = 5) -> list[tuple]:
    """Five non-overlapping 5-year blocks from the first timestamp."""
    start = index[0]
    out = []
    for i in range(n):
        lo = start + pd.DateOffset(years=5 * i)
        hi = start + pd.DateOffset(years=5 * (i + 1))
        out.append((lo, hi))
    return out


def score(df, curves, rate) -> dict:
    """Per-window metrics for every method, plus the window's own descriptors."""
    wins = windows(df.index)
    out = {"windows": [], "metrics": {}}
    for (lo, hi), label in zip(wins, REGIMES, strict=False):
        mask = (df.index >= lo) & (df.index < hi)
        sub = df.index[mask]
        span = f"{sub[0]:%Y}-{sub[-1]:%Y}"
        bh_vix = float(df.loc[mask, "vix"].mean() * 100)
        out["windows"].append({"label": label, "span": span, "avg_vix": bh_vix})
        for name, eq in curves.items():
            w = eq.loc[sub]
            s = metrics.summarize(w, rate)
            out["metrics"].setdefault(name, []).append(s)
    return out


def frame(scored, key) -> pd.DataFrame:
    names = list(scored["metrics"])
    cols = [w["span"] for w in scored["windows"]]
    data_ = {c: [scored["metrics"][n][i][key] for n in names] for i, c in enumerate(cols)}
    return pd.DataFrame(data_, index=names)


def main() -> None:
    p = argparse.ArgumentParser(description="Methods across 5-year regime windows.")
    p.add_argument("--outdir", default="studies/protective_puts/figures")
    args = p.parse_args()

    df = data.load(years=30)  # full stored history, ~25y
    rate = df["rate"]
    curves = methods(df)
    scored = score(df, curves, rate)

    cagr = frame(scored, "CAGR")
    dd = frame(scored, "MaxDD")
    sharpe = frame(scored, "Sharpe")

    print(f"\nREGIME ANALYSIS. {df.index[0]:%Y-%m} to {df.index[-1]:%Y-%m}, five 5-year windows.\n")
    for i, w in enumerate(scored["windows"]):
        print(
            f"  W{i + 1} {w['span']}  {w['label']:<26} avg VIX {w['avg_vix']:.0f}  |  "
            f"buy-hold CAGR {cagr.loc['Buy & hold'].iloc[i]:+.1%}, "
            f"MaxDD {dd.loc['Buy & hold'].iloc[i]:.0%}"
        )

    print("\nCAGR by window:")
    print((cagr * 100).round(1).to_string())
    print("\nMax drawdown by window:")
    print((dd * 100).round(0).to_string())

    # Excess vs buy-hold, the regime story.
    ex_cagr = cagr.subtract(cagr.loc["Buy & hold"]).drop("Buy & hold")
    dd_red = dd.subtract(dd.loc["Buy & hold"]).drop("Buy & hold")  # positive = smaller drawdown
    print("\nExcess CAGR vs buy-hold (negative = cost you return in that regime):")
    print((ex_cagr * 100).round(1).to_string())
    print("\nDrawdown reduction vs buy-hold (pp, positive = safer, robust across every regime):")
    print((dd_red * 100).round(0).to_string())

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    from studies.protective_puts import report

    print("\nFigure:", report.regime_panel(df, curves, scored, cagr, dd, sharpe, out))
    cagr.to_csv(out / "regimes-cagr.csv")


if __name__ == "__main__":
    main()
