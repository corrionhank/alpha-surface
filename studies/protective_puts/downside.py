"""Deploy protective puts after a sharp downside move.

Run: python -m studies.protective_puts.downside

The mirror of exhaustion.py, and a stronger prior. A 3-sigma up-move turned out to be a V-recovery
bottom, so hedging on it was backwards. A downside move is different: equity volatility clusters
and declines have short-term momentum (the leverage effect), so a 2-sigma drop plausibly does
predict more pain. This is the same signal family that beat its random twins in the conditional
study (vol expansion, backwardation).

But "predicts more volatility" is not "makes money as a hedge", and two things stand between them:

  THE PUT IS ALREADY EXPENSIVE. VIX spikes with the drop, so you buy protection after the price of
  protection has jumped. The engine prices off VIX, so this is captured, not assumed.

  YOU BUY NEAR THE BOUNCE. The best up-days in equities sit right next to the worst down-days. Hedge
  after a drop and you can cap the rebound. So this module reports the conditional forward return
  next to the precision: a signal can forecast a bear and still lose, if it is buying the dip.

Point-in-time throughout. Exploratory (see PROTOCOL.md); a strategy claim needs the sample we do
not have, but "does a drop predict more drop" is a direction, which a modest sample can speak to.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from studies.protective_puts import data, engine, metrics, scenarios
from studies.protective_puts.engine import ROLLS, Strategy
from studies.protective_puts.exhaustion import (
    _random_entries,
    _rising_edge,
    _stats,
    precision,
    vix_percentile,
    zscore,
)
from studies.protective_puts.skill import bear_ahead

# (name, lookback days, sigma, put tenor days). A drop wants short-dated protection, now.
DOWNSIDE = [
    ("1m drop 1.5sig -> 3m put", 21, 1.5, ROLLS["quarterly"]),
    ("1m drop 2.0sig -> 3m put", 21, 2.0, ROLLS["quarterly"]),
    ("3m drop 2.0sig -> 3m put", 63, 2.0, ROLLS["quarterly"]),
    ("3m drop 2.5sig -> 6m put", 63, 2.5, 126),
]


def forward_return(spot: pd.Series, edges: np.ndarray, horizon: int) -> tuple[float, float]:
    """Mean forward return over `horizon` days after the signal, against the unconditional mean.

    If the conditional mean is not below the unconditional, the drop is not a good moment to be
    hedged: on average the market is higher, not lower, `horizon` days later, and the put is a
    drag paid to sit through a bounce.
    """
    s = spot.to_numpy()
    n = len(s)
    idx = np.flatnonzero(edges)
    idx = idx[idx + horizon < n]
    if not len(idx):
        return float("nan"), float("nan")
    cond = np.mean([s[i + horizon] / s[i] - 1 for i in idx])
    base_idx = np.arange(0, n - horizon)
    uncond = np.mean(s[base_idx + horizon] / s[base_idx] - 1)
    return float(cond), float(uncond)


def main() -> None:
    p = argparse.ArgumentParser(description="Protective puts after a sharp drop.")
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

    print(f"\nDOWNSIDE HEDGING. SPY {df.index[0]:%Y-%m-%d} to {df.index[-1]:%Y-%m-%d}, "
          f"{n:,} sessions. Exploratory (see PROTOCOL.md).")

    truth = {h: bear_ahead(spot.to_numpy(), h) for h in (ROLLS["quarterly"], 126)}

    # Build every signal once: the drops, plus the two stress signals from the conditional study.
    signals: list[tuple[str, np.ndarray, int]] = []
    for name, look, sigma, tenor in DOWNSIDE:
        signals.append((name, (zscore(spot, look) < -sigma).shift(1).fillna(False).to_numpy(), tenor))
    vp = vix_percentile(vix)
    signals.append(("VIX > 80th pct (stress)", (vp > 0.80).shift(1).fillna(False).to_numpy(),
                    ROLLS["quarterly"]))
    if "vix3m" in df:
        signals.append(("Backwardation (VIX>VIX3M)",
                        (vix > df["vix3m"]).shift(1).fillna(False).to_numpy(), ROLLS["quarterly"]))

    # --- CRUX 1: does the drop predict MORE drop? ---
    print("\nCRUX 1: after the signal, is a further bear (15% drawdown within the tenor) more "
          "likely than at a random moment?")
    diag = {}
    for name, sig, tenor in signals:
        edges = _rising_edge(sig)
        d = precision(pd.Series(sig), truth[tenor])
        cond, uncond = forward_return(spot, edges, tenor)
        d["fwd_cond"] = cond
        d["fwd_base"] = uncond
        diag[name] = d
    tbl = pd.DataFrame(diag).T
    print(tbl[["events", "precision", "base_rate", "lift", "ci_lo", "ci_hi", "beats_base"]]
          .to_string(formatters={
              "events": "{:.0f}".format, "precision": "{:.0%}".format, "base_rate": "{:.0%}".format,
              "lift": "{:+.0%}".format, "ci_lo": "{:.0%}".format, "ci_hi": "{:.0%}".format,
          }))

    # --- CRUX 2: but is the market actually lower afterwards, or bouncing? ---
    print("\nCRUX 2: the tension. Mean forward return over the tenor, conditional on the signal "
          "vs unconditional.")
    print("A hedge only helps if conditional < unconditional. If the market is higher after the "
          "drop on average, you are hedging a bounce.")
    for name, sig, tenor in signals:
        row = diag[name]
        worse = row["fwd_cond"] < row["fwd_base"]
        print(f"  {name:<30} cond {row['fwd_cond']:+6.1%}  vs base {row['fwd_base']:+5.1%}  "
              f"({'lower, hedge justified' if worse else 'HIGHER, buying the dip'})")

    # --- The backtest: net of expensive vol and the missed bounce. ---
    print("\nBACKTEST (event-driven: buy a 5% OTM put the day the signal fires, hold to expiry):")
    rows = {"Buy and hold": _stats(engine.run(df, scenarios.BUY_AND_HOLD), rate)}
    for name, sig, tenor in signals:
        entries = _rising_edge(sig)
        strat = Strategy(name, moneyness=0.05, roll_days=tenor)
        res = engine.run_events(df, strat, entries)
        row = _stats(res, rate)
        if res.hedged_cycles and args.trials:
            twins = [
                metrics.summarize(
                    engine.run_events(df, strat, _random_entries(n, res.hedged_cycles, tenor, rng)
                                      ).equity, rate)["Sharpe"]
                for _ in range(args.trials)
            ]
            row["Beats random"] = float(np.mean(np.array(twins) < row["Sharpe"]))
        rows[name] = row
    bt = pd.DataFrame(rows).T
    print(bt.to_string(formatters={
        "CAGR": "{:.2%}".format, "Sharpe": "{:.3f}".format, "MaxDD": "{:.1%}".format,
        "N hedges": "{:.0f}".format, "Beats random": lambda v: "n/a" if pd.isna(v) else f"{v:.0%}",
    }))

    if not args.no_figures:
        out = Path(args.outdir)
        out.mkdir(parents=True, exist_ok=True)
        print("\nFigure:", report.precision_bars(tbl, out, "15-downside.png", title="Does a downside move predict more downside?"))
    tbl.to_csv(Path(args.outdir) / "downside-precision.csv")


if __name__ == "__main__":
    main()
