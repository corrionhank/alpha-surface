"""One PNG: only the findings that hold up.

Run: python -m studies.protective_puts.findings

Four panels, one working result each, with the number that carries it. The failures (always-on
puts, macro signals, up-move exhaustion, cheap-vol timing) are left out by design; this is the
distilled "what protects" sheet. Everything recomputed from the study functions so it matches.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from studies.protective_puts import data, engine, frontier, metrics, summary
from studies.protective_puts.engine import ROLLS
from studies.protective_puts.exhaustion import precision, vix_percentile, zscore
from studies.protective_puts.skill import HEDGE, bear_ahead, forecaster

INK, GRID, MUTED = "#14171A", "#E4E7EB", "#6B7280"
GREEN, BLUE, RED, ORANGE = "#12855F", "#2C5CF6", "#EF5350", "#E1590C"


def build(df, out: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rate = df["rate"]
    spot = df["spot"]

    strat = summary.key_strategies(df)
    stats = {n: metrics.summarize(r.equity, rate) for n, r in strat.items()}
    bh = stats["Buy and hold"]

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    def clean(ax):
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)

    def caption(ax, text):
        ax.text(0.0, -0.22, text, transform=ax.transAxes, fontsize=9.5, color=MUTED, va="top")

    # === 1. Own less, don't insure ===
    ax = axes[0, 0]
    pts = [
        ("Buy & hold", bh, INK),
        ("Always-hedged put", stats["Always-hedged put"], RED),
        ("De-risk on 2σ drop", stats["Down-move de-risk"], GREEN),
    ]
    for name, s, c in pts:
        ax.scatter(
            s["MaxDD"] * 100,
            s["CAGR"] * 100,
            s=220,
            color=c,
            edgecolor="white",
            linewidth=1.4,
            zorder=5,
        )
        ax.annotate(
            name,
            (s["MaxDD"] * 100, s["CAGR"] * 100),
            xytext=(s["MaxDD"] * 100 + 1.2, s["CAGR"] * 100 + 0.15),
            fontsize=10,
            color=c,
            weight="700",
        )
    clean(ax)
    ax.set_title("1.  Own less, don't insure", loc="left", fontsize=13, color=INK, weight="800")
    ax.set_xlabel("Max drawdown (%)   → safer", fontsize=9, color=INK)
    ax.set_ylabel("CAGR (%)", fontsize=9, color=INK)
    caption(
        ax,
        "Managing exposure cut the drawdown to -23% while keeping 10.3% CAGR.\nBuying "
        "puts every month cut it only to -51% and halved the return.",
    )

    # === 2. The one signal with real skill ===
    ax = axes[0, 1]
    q = ROLLS["quarterly"]
    truth_q = bear_ahead(spot.to_numpy(), q)
    truth_y = bear_ahead(spot.to_numpy(), ROLLS["annual"])
    vp = vix_percentile(df["vix"])
    rows = [
        ("2σ drop (3m)", precision((zscore(spot, 63) < -2).shift(1), truth_q), GREEN),
        ("2σ drop (1m)", precision((zscore(spot, 21) < -2).shift(1), truth_q), GREEN),
        ("3σ up-move", precision((zscore(spot, 63) > 3).shift(1), truth_q), ORANGE),
        ("VIX complacent", precision((vp < 0.20).shift(1), truth_y), ORANGE),
    ]
    y = np.arange(len(rows))[::-1]
    for yi, (_nm, d, c) in zip(y, rows, strict=False):
        lift = d["lift"] * 100
        ax.barh(yi, lift, color=c, height=0.6)
        # The CI is on precision; its half-widths are the same in lift-space (a shift by base).
        lo = max((d["precision"] - d["ci_lo"]) * 100, 0.0)
        hi = max((d["ci_hi"] - d["precision"]) * 100, 0.0)
        ax.errorbar(lift, yi, xerr=[[lo], [hi]], fmt="none", ecolor=INK, elinewidth=1, capsize=3)
    ax.axvline(0, color=INK, linestyle="--", linewidth=1.2)
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows], fontsize=10)
    clean(ax)
    ax.set_title(
        "2.  One signal actually predicts a bear", loc="left", fontsize=13, color=INK, weight="800"
    )
    ax.set_xlabel("Lift over base rate (pp); right of the line = predictive", fontsize=9, color=INK)
    caption(
        ax,
        "After a 2σ drop a further 15% fall is 33% likely vs a 7% baseline.\nUp-moves and "
        "VIX complacency point the wrong way.",
    )

    # === 3. The first drawdown is nearly free ===
    ax = axes[1, 0]
    fstats = []
    for _, _, exp in frontier.build_strategies(df):
        s = metrics.summarize(engine.run_exposure(df, exp, "x").equity, rate)
        fstats.append((s["MaxDD"], s["CAGR"]))
    fs = pd.DataFrame(fstats, columns=["MaxDD", "CAGR"])
    ax.scatter(fs["MaxDD"] * 100, fs["CAGR"] * 100, s=22, color="#C9CED6", edgecolor="none")
    front = fs.loc[frontier.non_dominated(fs)].sort_values("MaxDD")
    ax.plot(
        front["MaxDD"] * 100,
        front["CAGR"] * 100,
        color=GREEN,
        linewidth=2,
        marker="o",
        markersize=4,
        zorder=4,
    )
    ax.scatter(bh["MaxDD"] * 100, bh["CAGR"] * 100, s=200, marker="*", color=INK, zorder=5)
    ax.annotate(
        "buy & hold",
        (bh["MaxDD"] * 100, bh["CAGR"] * 100),
        xytext=(bh["MaxDD"] * 100 + 1.5, bh["CAGR"] * 100),
        fontsize=9,
        color=INK,
        weight="600",
        va="center",
    )
    clean(ax)
    ax.set_title(
        "3.  The first 20 points of drawdown are ~free",
        loc="left",
        fontsize=13,
        color=INK,
        weight="800",
    )
    ax.set_xlabel("Max drawdown (%)   → safer", fontsize=9, color=INK)
    ax.set_ylabel("CAGR (%)", fontsize=9, color=INK)
    caption(
        ax,
        "74 defensive strategies (grey), efficient frontier in green.\nCutting drawdown "
        "from -55% to -35% costs essentially no return.",
    )

    # === 4. How good must the call be? ===
    ax = axes[1, 1]
    n, roll = len(df), HEDGE.roll_days
    starts = np.arange(0, n - 1, roll)
    truth = bear_ahead(spot.to_numpy(), roll)[starts]
    base = truth.mean()
    bh_sh = bh["Sharpe"]
    rng = np.random.default_rng(20260715)
    grid = np.round(np.arange(0.2, 1.01, 0.1), 2)
    curve = []
    for prec in grid:
        sh = [
            metrics.summarize(
                engine.run(
                    df, HEDGE, hedge_on=np.repeat(forecaster(truth, prec, 1 / 3, rng), roll)[:n]
                ).equity,
                rate,
            )["Sharpe"]
            for _ in range(25)
        ]
        curve.append(np.mean(sh))
    ax.plot(grid * 100, curve, color=BLUE, linewidth=2, marker="o", markersize=4)
    ax.axhline(bh_sh, color=INK, linestyle="--", linewidth=1.3, label=f"buy & hold ({bh_sh:.2f})")
    ax.axvline(base * 100, color=ORANGE, linewidth=1.4, label=f"dart board ({base:.0%})")
    clean(ax)
    ax.set_title(
        "4.  A skilled call clears a low bar", loc="left", fontsize=13, color=INK, weight="800"
    )
    ax.set_xlabel("How often your bear call is right (%)", fontsize=9, color=INK)
    ax.set_ylabel("Sharpe", fontsize=9, color=INK)
    ax.legend(frameon=False, fontsize=8.5, loc="lower right")
    caption(
        ax,
        "Be right ~40% of the time (vs a 29% base rate) and hedging a\nthird of the "
        "time beats buy & hold. A reachable bar for a real read.",
    )

    fig.suptitle(
        "What actually protects: the findings that hold up",
        fontsize=17,
        color=INK,
        weight="800",
        x=0.02,
        ha="left",
    )
    fig.text(
        0.02,
        0.005,
        "SPY 2005-2026, 21 years. Drawdown reductions are the robust result; Sharpe edges are "
        "within noise and lean on 2008/2020. Exploratory — see PROTOCOL.md.",
        fontsize=8.5,
        color=MUTED,
    )
    fig.tight_layout(rect=(0, 0.03, 1, 0.96), h_pad=4.0)
    path = out / "18-what-works.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def main() -> None:
    p = argparse.ArgumentParser(description="One PNG of the working findings.")
    p.add_argument("--years", type=float, default=21.0)
    p.add_argument("--outdir", default="studies/protective_puts/figures")
    args = p.parse_args()
    df = data.load(years=args.years)
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    print("Figure:", build(df, out))


if __name__ == "__main__":
    main()
