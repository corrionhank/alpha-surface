"""One chart for the whole investigation.

Run: python -m studies.protective_puts.summary

Pulls the headline results from every study onto a single canvas:
  - the return / drawdown map, which is the frame everything collapsed to;
  - the signal scorecard, which points the right way and which is backwards;
  - the equity curves of the strategies that matter.

Recomputes from the same functions the studies use, so the numbers match. Exploratory throughout
(PROTOCOL.md): this charts a tradeoff and a set of directional signal tests, not certified alpha.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from studies.protective_puts import data, engine, frontier, metrics, scenarios
from studies.protective_puts.engine import ROLLS, Strategy
from studies.protective_puts.exhaustion import _rising_edge, precision, vix_percentile, zscore
from studies.protective_puts.skill import bear_ahead

INK = "#14171A"
GRID = "#E4E7EB"


def key_strategies(df) -> dict:
    """The five points that tell the story, from insure-and-bleed to de-risk-and-keep."""
    spot = df["spot"]
    out = {}
    out["Buy and hold"] = engine.run(df, scenarios.BUY_AND_HOLD)
    out["Always-hedged put"] = engine.run(df, Strategy("put", moneyness=0.05,
                                                       roll_days=ROLLS["monthly"]))
    out["Vol target 15%"] = engine.run_vol_target(df, "Vol target 15%", target=0.15,
                                                  max_exposure=1.5)
    # The same 2-sigma-drop signal, two ways: as an option, and as a sizing rule.
    entries = _rising_edge((zscore(spot, 21) < -2.0).shift(1).fillna(False).to_numpy())
    out["Down-move put"] = engine.run_events(df, Strategy("dput", moneyness=0.05,
                                                          roll_days=ROLLS["quarterly"]), entries)
    out["Down-move de-risk"] = engine.run_exposure(
        df, frontier.downside_derisk(df, 21, 2.0, off=0.0, hold=63), "De-risk")
    return out


def signal_scorecard(df) -> pd.DataFrame:
    """Lift over base rate for the signals tested across the studies. Positive points the right way."""
    spot, vix = df["spot"], df["vix"]
    q, y = ROLLS["quarterly"], ROLLS["annual"]
    truth = {q: bear_ahead(spot.to_numpy(), q), y: bear_ahead(spot.to_numpy(), y)}
    vp = vix_percentile(vix)

    tests = [
        ("3sig up-move", (zscore(spot, 63) > 3.0).shift(1), q),
        ("2sig down (1m)", (zscore(spot, 21) < -2.0).shift(1), q),
        ("2sig down (3m)", (zscore(spot, 63) < -2.0).shift(1), q),
        ("VIX complacent", (vp < 0.20).shift(1), y),
        ("VIX stress", (vp > 0.80).shift(1), q),
    ]
    if "vix3m" in df:
        tests.append(("Backwardation", (vix > df["vix3m"]).shift(1), q))

    rows = {}
    for name, sig, horizon in tests:
        d = precision(sig.fillna(False), truth[horizon])
        rows[name] = {"lift": d["lift"], "ci_lo": d["ci_lo"] - d["base_rate"],
                      "ci_hi": d["ci_hi"] - d["base_rate"], "events": d["events"],
                      "beats": d["beats_base"]}
    return pd.DataFrame(rows).T


def chart(df, strategies, scores, rate, out: Path) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    stats = {n: metrics.summarize(r.equity, rate) for n, r in strategies.items()}
    palette = {
        "Buy and hold": INK, "Always-hedged put": "#EF5350", "Vol target 15%": "#2C5CF6",
        "Down-move put": "#E1590C", "Down-move de-risk": "#12855F",
    }

    fig = plt.figure(figsize=(15, 9))
    gs = fig.add_gridspec(2, 3, width_ratios=[1.5, 1, 1], height_ratios=[1, 1],
                          hspace=0.28, wspace=0.28)
    big = fig.add_subplot(gs[:, 0])
    sk = fig.add_subplot(gs[0, 1:])
    eq = fig.add_subplot(gs[1, 1:])

    def _clean(ax):
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)

    # --- the whole cloud, faint, for context ---
    for _, _, exp in frontier.build_strategies(df):
        s = metrics.summarize(engine.run_exposure(df, exp, "x").equity, rate)
        big.scatter(s["MaxDD"] * 100, s["CAGR"] * 100, s=16, color="#C9CED6", alpha=0.6,
                    edgecolor="none", zorder=1)
    big.scatter([], [], s=16, color="#C9CED6", label="74 defensive strategies")

    # --- the five labelled points ---
    # (dx, dy, ha) label offsets placed by hand to keep the crowded middle readable.
    label_at = {
        "Buy and hold": (0.7, 0.2, "left"),
        "Always-hedged put": (0.9, 0.25, "left"),
        "Vol target 15%": (0.7, 0.2, "left"),
        "Down-move put": (-0.7, -0.45, "right"),
        "Down-move de-risk": (0.7, 0.2, "left"),
    }
    for name, s in stats.items():
        big.scatter(s["MaxDD"] * 100, s["CAGR"] * 100, s=150, color=palette[name], zorder=5,
                    edgecolor="white", linewidth=1.2)
        dx, dy, ha = label_at[name]
        big.annotate(name, (s["MaxDD"] * 100, s["CAGR"] * 100),
                     xytext=(s["MaxDD"] * 100 + dx, s["CAGR"] * 100 + dy), fontsize=9,
                     color=palette[name], weight="600", ha=ha)

    # the arrow that is the punchline: same signal, drop the option tax
    p, d = stats["Down-move put"], stats["Down-move de-risk"]
    big.annotate("", xy=(d["MaxDD"] * 100, d["CAGR"] * 100),
                 xytext=(p["MaxDD"] * 100, p["CAGR"] * 100),
                 arrowprops=dict(arrowstyle="->", color="#12855F", lw=1.6, alpha=0.7))
    big.text((p["MaxDD"] + d["MaxDD"]) * 50 - 2.5, (p["CAGR"] + d["CAGR"]) * 50 + 0.35,
             "same signal,\ndrop the option tax", fontsize=8, color="#12855F", style="italic",
             ha="center")

    _clean(big)
    big.set_title("The return / drawdown map", loc="left", fontsize=12, color=INK, weight="700")
    big.set_xlabel("Max drawdown (%)   → better", fontsize=10, color=INK)
    big.set_ylabel("CAGR (%)", fontsize=10, color=INK)
    big.legend(frameon=False, fontsize=8, loc="lower left")

    # --- signal scorecard: lift over base rate ---
    order = scores.iloc[::-1]
    ypos = np.arange(len(order))
    colors = ["#12855F" if b else "#E1590C" for b in order["beats"]]
    err = [(order["lift"] - order["ci_lo"]).to_numpy() * 100,
           (order["ci_hi"] - order["lift"]).to_numpy() * 100]
    sk.barh(ypos, order["lift"] * 100, color=colors, height=0.62)
    sk.errorbar(order["lift"] * 100, ypos, xerr=err, fmt="none", ecolor=INK, elinewidth=1,
                capsize=2)
    sk.axvline(0, color=INK, linestyle="--", linewidth=1.2)
    for yi, (idx, r) in enumerate(order.iterrows()):
        sk.text(0.4, yi, f" n={int(r['events'])}", va="center", fontsize=7, color=INK)
    sk.set_yticks(ypos)
    sk.set_yticklabels(order.index, fontsize=8.5)
    _clean(sk)
    sk.set_title("Signal skill: lift over base rate", loc="left", fontsize=12, color=INK,
                 weight="600")
    sk.set_xlabel("percentage points; green clears its confidence interval", fontsize=8.5,
                  color=INK)

    # --- equity curves ---
    for name, res in strategies.items():
        eq.plot(res.equity.index, res.equity, color=palette[name], linewidth=1.6, label=name)
    eq.set_yscale("log")
    _clean(eq)
    eq.set_title("Growth of $10,000 (log)", loc="left", fontsize=11, color=INK, weight="600")
    eq.legend(frameon=False, fontsize=8, loc="upper left")

    fig.suptitle("Protective puts, and what actually protects: research summary",
                 fontsize=15, color=INK, weight="800", x=0.02, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.97))
    path = out / "17-summary.png"
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def main() -> None:
    p = argparse.ArgumentParser(description="One chart summarizing the protective-put study.")
    p.add_argument("--years", type=float, default=21.0)
    p.add_argument("--outdir", default="studies/protective_puts/figures")
    args = p.parse_args()

    df = data.load(years=args.years)
    rate = df["rate"]
    strategies = key_strategies(df)
    scores = signal_scorecard(df)

    print(f"\nRESEARCH SUMMARY. SPY {df.index[0]:%Y-%m-%d} to {df.index[-1]:%Y-%m-%d}, "
          f"{len(df):,} sessions.\n")
    board = pd.DataFrame({n: metrics.summarize(r.equity, rate) for n, r in strategies.items()}).T
    print(board[["CAGR", "Vol", "Sharpe", "MaxDD", "Calmar"]].to_string(formatters={
        "CAGR": "{:.2%}".format, "Vol": "{:.1%}".format, "Sharpe": "{:.2f}".format,
        "MaxDD": "{:.1%}".format, "Calmar": "{:.2f}".format,
    }))

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    print("\nFigure:", chart(df, strategies, scores, rate, out))


if __name__ == "__main__":
    main()
