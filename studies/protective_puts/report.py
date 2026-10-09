"""Figures. Plain matplotlib, no styling libraries.

The backend is the caller's choice: __main__ pins Agg unless --show is passed, so importing this
module never opens a window on its own. Under Agg the figures are closed after writing; under an
interactive backend they are kept alive so show() can put them on screen.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from studies.protective_puts.metrics import drawdown

INK, GRID = "#14171A", "#E4E7EB"
MUTED = "#6B7280"
COLORS = ["#14171A", "#2C5CF6", "#E1590C", "#12855F", "#8B5CF6"]


def _axes(title: str, ylabel: str, size=(11, 5.5)):
    fig, ax = plt.subplots(figsize=size)
    ax.set_title(title, loc="left", fontsize=13, color=INK, weight="600")
    ax.set_ylabel(ylabel, fontsize=10, color=INK)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    return fig, ax


def _save(fig, out: Path, name: str) -> Path:
    path = out / name
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    if plt.get_backend().lower() == "agg":
        plt.close(fig)  # headless: nothing will ever draw it, so free it
    return path


def show() -> None:
    """Put every open figure on screen. Blocks until the windows are closed."""
    plt.show()


def equity_curves(results, out: Path, name="01-equity.png") -> Path:
    fig, ax = _axes("Growth of $10,000, log scale", "Portfolio value")
    for res, color in zip(results, COLORS, strict=False):
        ax.plot(res.equity.index, res.equity, label=res.name, color=color, linewidth=1.4)
    ax.set_yscale("log")
    ax.legend(frameon=False, fontsize=9)
    return _save(fig, out, name)


def drawdowns(results, out: Path, name="02-drawdown.png") -> Path:
    fig, ax = _axes("Drawdown from prior peak", "Drawdown")
    for res, color in zip(results, COLORS, strict=False):
        dd = drawdown(res.equity)
        ax.plot(dd.index, dd * 100, label=res.name, color=color, linewidth=1.2)
    ax.set_ylabel("Drawdown (%)")
    ax.legend(frameon=False, fontsize=9, loc="lower left")
    return _save(fig, out, name)


def cost_of_protection(results, out: Path, name="03-cost.png") -> Path:
    """What was spent on premium against what came back as payoff."""
    hedged = [r for r in results if r.total_premium > 0]
    fig, ax = _axes("Cumulative premium paid vs payoff collected", "Dollars")
    for res, color in zip(hedged, COLORS[1:], strict=False):
        ax.plot(res.premium_paid.cumsum(), color=color, linewidth=1.4, label=f"{res.name}: paid")
        ax.plot(
            res.payoff_received.cumsum(),
            color=color,
            linewidth=1.4,
            linestyle="--",
            label=f"{res.name}: collected",
        )
    ax.legend(frameon=False, fontsize=8, ncol=2)
    return _save(fig, out, name)


def skew_sensitivity(sweep, out: Path, name="04-skew.png") -> Path:
    """sweep: {strategy name: {skew slope: CAGR}}. Flat VIX sits at slope 0."""
    fig, ax = _axes("How much the answer depends on the skew assumption", "CAGR (%)", size=(9, 5.5))
    for (label, series), color in zip(sweep.items(), COLORS[1:], strict=False):
        slopes = sorted(series)
        ax.plot(
            slopes,
            [series[s] * 100 for s in slopes],
            marker="o",
            color=color,
            linewidth=1.6,
            label=label,
        )
    ax.axvline(0.0, color=INK, linestyle=":", linewidth=1)
    ax.text(
        0.01,
        ax.get_ylim()[0],
        " flat VIX\n (undercharges the put)",
        fontsize=8,
        color=INK,
        va="bottom",
    )
    ax.set_xlabel("Skew premium, vol points per 1% OTM", fontsize=10, color=INK)
    ax.legend(frameon=False, fontsize=9)
    return _save(fig, out, name)


def crisis_bars(crisis_dd, out: Path, name="05-crises.png") -> Path:
    """crisis_dd: {crisis: {strategy: max drawdown}}."""
    crises = list(crisis_dd)
    names = list(next(iter(crisis_dd.values())))
    width = 0.8 / len(names)

    fig, ax = _axes("Worst drawdown inside each crisis", "Drawdown (%)", size=(10, 5.5))
    for i, (name_, color) in enumerate(zip(names, COLORS, strict=False)):
        xs = [j + i * width for j in range(len(crises))]
        vals = [crisis_dd[c][name_] * 100 for c in crises]
        bars = ax.bar(xs, vals, width=width, label=name_, color=color)
        ax.bar_label(bars, fmt="%.0f", fontsize=8, padding=-14, color="white")
    ax.set_xticks([j + 0.4 - width / 2 for j in range(len(crises))])
    ax.set_xticklabels(crises)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    return _save(fig, out, name)


def signal_timeline(flags, spot, out: Path, name="08-signals.png") -> Path:
    """When each signal was on, against the index it was meant to be protecting."""
    fig, (top, bot) = plt.subplots(
        2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [2, 3]}
    )
    top.plot(spot.index, spot, color=INK, linewidth=1.2)
    top.set_yscale("log")
    top.set_title(
        "Signals against the index they are hedging",
        loc="left",
        fontsize=13,
        color=INK,
        weight="600",
    )
    top.set_ylabel("SPY")
    top.grid(True, color=GRID, linewidth=0.8)
    top.set_axisbelow(True)

    names = list(flags.columns)
    for i, (col, color) in enumerate(zip(names, COLORS * 3, strict=False)):
        bot.fill_between(
            flags.index, i + 0.1, i + 0.9, where=flags[col].to_numpy(), color=color, linewidth=0
        )
    bot.set_yticks([i + 0.5 for i in range(len(names))])
    bot.set_yticklabels(names, fontsize=9)
    bot.set_ylim(0, len(names))
    bot.grid(True, axis="x", color=GRID, linewidth=0.8)
    bot.set_axisbelow(True)
    for side in ("top", "right"):
        top.spines[side].set_visible(False)
        bot.spines[side].set_visible(False)
    return _save(fig, out, name)


def skill_histograms(draws, skill, out: Path, name="09-skill.png") -> Path:
    """Each signal's Sharpe against the random twins that hedged just as often."""
    cols = len(draws)
    fig, axes = plt.subplots(1, cols, figsize=(3.4 * cols, 4), sharey=True)
    axes = np.atleast_1d(axes)
    for ax, (label, sharpes) in zip(axes, draws.items(), strict=False):
        ax.hist(sharpes, bins=30, color=GRID, edgecolor="#C9CED6", linewidth=0.5)
        ax.axvline(skill[label]["Sharpe"], color="#E1590C", linewidth=2)
        ax.set_title(
            f"{label}\nbeats {skill[label]['Beats']:.0%} of random", fontsize=10, color=INK
        )
        ax.set_xlabel("Sharpe", fontsize=9)
        ax.grid(True, color=GRID, linewidth=0.6)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
    axes[0].set_ylabel("Random twins", fontsize=9)
    fig.suptitle(
        "Signal (orange) vs random hedging at the same duty cycle",
        fontsize=13,
        color=INK,
        weight="600",
        x=0.01,
        ha="left",
    )
    return _save(fig, out, name)


def regime_panel(df, curves, scored, cagr, dd, sharpe, out: Path, name="19-regimes.png") -> Path:
    """SPY shaded by five 5-year windows, then heatmaps of each method's edge vs buy-hold in each."""
    import matplotlib.pyplot as plt
    from matplotlib.colors import TwoSlopeNorm

    from studies.protective_puts.regimes import windows as _wins

    wins = scored["windows"]
    spans = [w["span"] for w in wins]
    edges = _wins(df.index)

    fig = plt.figure(figsize=(15, 13))
    gs = fig.add_gridspec(4, 1, height_ratios=[1.5, 1.15, 1.15, 1.15], hspace=0.55)

    # --- price strip, shaded by regime ---
    ax = fig.add_subplot(gs[0])
    ax.plot(df.index, df["spot"], color=INK, linewidth=1.3)
    ax.set_yscale("log")
    shades = ["#EAF0FF", "#FDECEA", "#EAF6EF", "#F3EDFB", "#FEF3E6"]
    for (lo, hi), shade, w in zip(edges, shades, wins, strict=False):
        ax.axvspan(lo, min(hi, df.index[-1]), color=shade, zorder=0)
        mid = lo + (min(hi, df.index[-1]) - lo) / 2
        bh_c = cagr.loc["Buy & hold"].iloc[spans.index(w["span"])]
        bh_d = dd.loc["Buy & hold"].iloc[spans.index(w["span"])]
        trans = ax.get_xaxis_transform()  # data x, axes-fraction y: labels sit clear of the curve
        ax.text(
            mid,
            0.94,
            w["label"],
            transform=trans,
            ha="center",
            va="top",
            fontsize=9,
            color=INK,
            weight="600",
        )
        ax.text(
            mid,
            0.06,
            f"{w['span']}   VIX {w['avg_vix']:.0f}   B&H {bh_c:+.0%} / DD {bh_d:.0%}",
            transform=trans,
            ha="center",
            va="bottom",
            fontsize=7.5,
            color=MUTED,
        )
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    ax.set_title("SPY across five 5-year regimes", loc="left", fontsize=13, color=INK, weight="800")
    ax.set_ylabel("SPY (log)", fontsize=9, color=INK)

    # --- three heatmaps: excess CAGR, drawdown reduction, excess Sharpe ---
    ex_cagr = cagr.subtract(cagr.loc["Buy & hold"]).drop("Buy & hold") * 100
    dd_red = dd.subtract(dd.loc["Buy & hold"]).drop("Buy & hold") * 100  # + = smaller drawdown
    ex_sh = sharpe.subtract(sharpe.loc["Buy & hold"]).drop("Buy & hold")

    panels = [
        (ex_cagr, "Excess CAGR vs buy-hold (pp)", "{:+.1f}", 8),
        (dd_red, "Drawdown reduction vs buy-hold (pp, + = safer)", "{:+.0f}", 30),
        (ex_sh, "Excess Sharpe vs buy-hold", "{:+.2f}", 0.5),
    ]
    for row, (mat, title, fmt, lim) in enumerate(panels, start=1):
        hax = fig.add_subplot(gs[row])
        norm = TwoSlopeNorm(vmin=-lim, vcenter=0, vmax=lim)
        hax.imshow(mat.to_numpy(), cmap="RdYlGn", norm=norm, aspect="auto")
        hax.set_xticks(range(len(spans)))
        hax.set_xticklabels(spans, fontsize=9)
        hax.set_yticks(range(len(mat.index)))
        hax.set_yticklabels(mat.index, fontsize=9)
        for i in range(mat.shape[0]):
            for j in range(mat.shape[1]):
                hax.text(
                    j,
                    i,
                    fmt.format(mat.iloc[i, j]),
                    ha="center",
                    va="center",
                    fontsize=8.5,
                    color=INK,
                )
        hax.set_title(title, loc="left", fontsize=11, color=INK, weight="600")
        for s in ("top", "right", "left", "bottom"):
            hax.spines[s].set_visible(False)

    fig.suptitle(
        "Every method across market regimes: where the edge lives",
        fontsize=16,
        color=INK,
        weight="800",
        x=0.02,
        ha="left",
    )
    fig.text(
        0.02,
        0.005,
        "Green = beat buy-and-hold in that 5-year window, red = lagged it. Defensive methods "
        "win in the crash regimes (GFC, COVID) and cost return in the calm bulls.",
        fontsize=9,
        color=MUTED,
    )
    fig.tight_layout(rect=(0, 0.02, 1, 0.97))
    path = out / name
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


FAMILY_COLORS = {
    "Benchmark": INK,
    "Vol target": "#2C5CF6",
    "Trend": "#E1590C",
    "TS momentum": "#12855F",
    "Drawdown ctrl": "#8B5CF6",
    "VIX regime": "#0E9AA7",
    "Downside": "#D6336C",
}


def frontier_panel(tbl, curves, out: Path, name="16-frontier.png") -> Path:
    """Four views of the defensive-exposure sweep: the crash-protection frontier, the classic
    risk/return frontier, risk-adjusted return, and the frontier equity curves."""
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 2, figsize=(14, 11))
    bh = tbl.loc["Buy and hold"]
    front = tbl[tbl.get("frontier", False)].sort_values("MaxDD")

    def _style(ax, title, xl, yl):
        ax.set_title(title, loc="left", fontsize=12, color=INK, weight="600")
        ax.set_xlabel(xl, fontsize=10, color=INK)
        ax.set_ylabel(yl, fontsize=10, color=INK)
        ax.grid(True, color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for s in ("top", "right"):
            ax.spines[s].set_visible(False)

    def _scatter(ax, x, y, ym=100):
        # x axes are percentages (*100); y is a percentage for CAGR, raw for Sharpe (ym=1).
        for fam in tbl["family"].unique():
            sub = tbl[tbl["family"] == fam]
            ax.scatter(
                sub[x] * 100,
                sub[y] * ym,
                s=34,
                alpha=0.75,
                color=FAMILY_COLORS.get(fam, "#888"),
                label=fam,
                edgecolor="none",
            )
        ax.scatter(
            bh[x] * 100, bh[y] * ym, s=180, marker="*", color=INK, zorder=5, label="Buy and hold"
        )

    # (0,0) the crash-protection frontier: CAGR vs max drawdown.
    ax = axes[0, 0]
    _scatter(ax, "MaxDD", "CAGR")
    ax.plot(
        front["MaxDD"] * 100,
        front["CAGR"] * 100,
        color=INK,
        linewidth=1.2,
        linestyle="--",
        zorder=4,
        label="Efficient frontier",
    )
    _style(ax, "Crash-protection frontier", "Max drawdown (%)", "CAGR (%)")
    ax.legend(frameon=False, fontsize=7.5, loc="lower right", ncol=2)

    # (0,1) classic risk/return: CAGR vs volatility.
    ax = axes[0, 1]
    _scatter(ax, "Vol", "CAGR")
    _style(ax, "Return vs volatility", "Annualized volatility (%)", "CAGR (%)")

    # (1,0) risk-adjusted return: Sharpe vs max drawdown, with the buy-and-hold line.
    ax = axes[1, 0]
    _scatter(ax, "MaxDD", "Sharpe", ym=1)
    ax.axhline(
        bh["Sharpe"],
        color=INK,
        linestyle=":",
        linewidth=1,
        label=f"Buy-hold Sharpe {bh['Sharpe']:.2f}",
    )
    _style(ax, "Risk-adjusted return vs drawdown", "Max drawdown (%)", "Sharpe")
    ax.legend(frameon=False, fontsize=8, loc="lower right")

    # (1,1) equity curves of the frontier picks.
    ax = axes[1, 1]
    ax.plot(
        curves["Buy and hold"].index,
        curves["Buy and hold"],
        color=INK,
        linewidth=2,
        label="Buy and hold",
    )
    for nm, col in zip(
        front.index[:6],
        ["#2C5CF6", "#E1590C", "#12855F", "#8B5CF6", "#0E9AA7", "#D6336C"],
        strict=False,
    ):
        if nm in curves:
            ax.plot(curves[nm].index, curves[nm], color=col, linewidth=1.2, label=nm)
    ax.set_yscale("log")
    _style(ax, "Frontier equity curves (log)", "", "Growth of $10,000")
    ax.legend(frameon=False, fontsize=7.5, loc="upper left")

    fig.suptitle(
        "Defensive-exposure strategies: the return / drawdown tradeoff",
        fontsize=14,
        color=INK,
        weight="700",
        x=0.02,
        ha="left",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.98))
    path = out / name
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def precision_bars(
    tbl, out: Path, name="14-exhaustion.png", title="Does the signal predict a bear?"
) -> Path:
    """Each signal's lift over its OWN base rate, with the Wilson interval.

    Lift, not raw precision, because the signals span two horizons (3-month and 1-year) with
    different base rates, so raw hit rates are not comparable across rows. Lift is: everything to
    the left of zero is a signal that points the wrong way, and a bar is only green if its whole
    interval sits right of zero.
    """
    tbl = tbl[tbl["events"] > 0]
    base = tbl["base_rate"].to_numpy()[::-1]
    lift = tbl["precision"].to_numpy()[::-1] - base
    lo = lift - (tbl["ci_lo"].to_numpy()[::-1] - base)
    hi = (tbl["ci_hi"].to_numpy()[::-1] - base) - lift
    labels = list(tbl.index)[::-1]
    ev = tbl["events"].to_numpy()[::-1]
    ci_lo_lift = tbl["ci_lo"].to_numpy()[::-1] - base

    fig, ax = _axes(title, "", size=(11, 6))
    y = np.arange(len(labels))
    colors = [COLORS[3] if lo_i > 0 else COLORS[2] for lo_i in ci_lo_lift]
    ax.barh(y, lift * 100, color=colors, height=0.6)
    ax.errorbar(
        lift * 100, y, xerr=[lo * 100, hi * 100], fmt="none", ecolor=INK, elinewidth=1, capsize=3
    )
    ax.axvline(0, color=INK, linestyle="--", linewidth=1.4, label="Base rate: no predictive power")
    for yi, ei in enumerate(ev):
        ax.text(0.3, yi, f" n={ei:.0f}", va="center", fontsize=8, color=INK)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=9)
    ax.set_xlabel(
        "Lift over own base rate: P(bear | signal) - P(bear), percentage points",
        fontsize=10,
        color=INK,
    )
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    return _save(fig, out, name)


def skill_curve(curve, benchmark, base_rate, oracle, out: Path, name="11-skill-curve.png") -> Path:
    """Sharpe against how often the hunch is right, with the dart board and the ceiling marked."""
    fig, ax = _axes("How right must you be for hedging to pay?", "Sharpe", size=(10, 5.5))
    ax.plot(
        curve.index * 100,
        curve["Sharpe"],
        marker="o",
        color=COLORS[1],
        linewidth=1.8,
        label="Hedged a third of the time, at this precision",
    )
    ax.axhline(
        benchmark["Sharpe"],
        color=INK,
        linestyle="--",
        linewidth=1.4,
        label=f"Buy and hold ({benchmark['Sharpe']:.2f})",
    )
    ax.axhline(
        oracle["Sharpe"],
        color=COLORS[3],
        linestyle=":",
        linewidth=1.4,
        label=f"Perfect foresight ({oracle['Sharpe']:.2f})",
    )
    ax.axvline(
        base_rate * 100,
        color=COLORS[2],
        linewidth=1.2,
        label=f"Dart board ({base_rate:.0%} base rate)",
    )
    ax.set_xlabel("Share of your bear calls that are right (precision, %)", fontsize=10, color=INK)
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    return _save(fig, out, name)


def cadence_curves(results, out: Path, name="06-cadence.png") -> Path:
    fig, ax = _axes("Does the roll cadence change the bleed?", "Portfolio value")
    for res, color in zip(results, COLORS, strict=False):
        ax.plot(res.equity.index, res.equity, label=res.name, color=color, linewidth=1.4)
    ax.set_yscale("log")
    ax.legend(frameon=False, fontsize=9)
    return _save(fig, out, name)
