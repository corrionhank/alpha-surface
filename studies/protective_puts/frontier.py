"""The defensive-exposure frontier.

Run: python -m studies.protective_puts.frontier

Where the results point. Across every study the one robust result was that volatility-responsive
de-risking cuts drawdown, options are a tax, and Sharpe edges are inside the noise band. So this
drops options entirely and maps a large family of no-option dynamic-exposure strategies on the
return-vs-drawdown plane. The question is reframed from "beat buy-and-hold on Sharpe" (which needs
~89 years to answer) to "what CAGR do you give up per point of drawdown removed", which is
decision-relevant and rests on drawdown, the least noisy statistic here.

Every strategy is the same primitive: hold some exposure in [0, cap] to the index, the rest in
cash. Six families differ only in how they set that exposure, all point-in-time:

  VOL TARGET      exposure = target / trailing vol. The gen-1 winner, swept over target, horizon,
                  cap and estimator (realized, EWMA, VIX).
  TREND           full exposure above a moving average, reduced below it.
  TS MOMENTUM     full exposure when trailing 6-12m return is positive, reduced when negative.
  DRAWDOWN CTRL   exposure falls as the drawdown from the running peak deepens.
  VIX REGIME      exposure set by the level of VIX.
  DOWNSIDE        de-risk for a fixed window after a sigma-sized drop (the downside.py signal, as
                  a sizing rule instead of a put).

No strategy is tuned on the result. The whole cloud is plotted so nothing is cherry-picked, and
the efficient frontier (non-dominated on CAGR and drawdown) is highlighted. Exploratory: this maps
a tradeoff, it does not certify a winner. See PROTOCOL.md.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from studies.protective_puts import data, engine, metrics, scenarios
from studies.protective_puts.exhaustion import zscore

TD = 252


# --- exposure generators. Each returns a point-in-time weight in [0, cap], already shifted. ---

def _vol(ret: pd.Series, lookback: int, estimator: str, vix: pd.Series) -> pd.Series:
    if estimator == "realized":
        return ret.rolling(lookback).std() * np.sqrt(TD)
    if estimator == "ewma":
        return ret.ewm(span=lookback).std() * np.sqrt(TD)
    return vix  # VIX is already an annualized vol, observable at the close


def vol_target(df, target, lookback, cap, estimator) -> np.ndarray:
    ret = df["spot"].pct_change().fillna(0.0)
    vol = _vol(ret, lookback, estimator, df["vix"])
    return (target / vol).shift(1).clip(upper=cap).fillna(1.0).to_numpy()


def trend_ma(df, ma_days, off) -> np.ndarray:
    ma = df["spot"].rolling(ma_days).mean()
    on = (df["spot"] >= ma).shift(1)
    return np.where(on.fillna(True), 1.0, off)


def ts_momentum(df, lookback, off) -> np.ndarray:
    mom = df["spot"].pct_change(lookback)
    return np.where((mom > 0).shift(1).fillna(True), 1.0, off)


def drawdown_control(df, cap_dd, floor) -> np.ndarray:
    dd = (df["spot"] / df["spot"].cummax() - 1.0).shift(1).fillna(0.0)
    # Full exposure at the highs, linearly down to `floor` once the drawdown reaches cap_dd.
    return (floor + (1 - floor) * np.clip(1 + dd / cap_dd, 0.0, 1.0)).to_numpy()


def vix_regime(df, low, high, calm_exp, stress_exp) -> np.ndarray:
    v = df["vix"].shift(1)
    exp = np.interp(v.fillna(v.median()), [low, high], [calm_exp, stress_exp])
    return exp


def downside_derisk(df, lookback, sigma, off, hold) -> np.ndarray:
    drop = (zscore(df["spot"], lookback) < -sigma).shift(1).fillna(False).to_numpy()
    exp = np.ones(len(df))
    held = 0
    for i in range(len(df)):
        if drop[i]:
            held = hold
        if held > 0:
            exp[i] = off
            held -= 1
    return exp


def build_strategies(df) -> list[tuple[str, str, np.ndarray]]:
    """(name, family, exposure). A wide, untuned sweep."""
    S: list[tuple[str, str, np.ndarray]] = []

    for target in (0.10, 0.12, 0.15):
        for look in (21, 42, 63):
            for cap in (1.0, 1.5):
                for est in ("realized", "ewma"):
                    S.append((f"VT {target:.0%}/{look}d/{cap:g}x/{est[:4]}", "Vol target",
                              vol_target(df, target, look, cap, est)))
    for target in (0.12, 0.15, 0.18):
        for cap in (1.0, 1.5):
            S.append((f"VT {target:.0%}/VIX/{cap:g}x", "Vol target",
                      vol_target(df, target, 21, cap, "vix")))

    for ma in (50, 100, 150, 200):
        for off in (0.0, 0.5):
            S.append((f"Trend {ma}d/off{off:g}", "Trend", trend_ma(df, ma, off)))

    for look in (126, 189, 252):
        for off in (0.0, 0.5):
            S.append((f"TSmom {look}d/off{off:g}", "TS momentum", ts_momentum(df, look, off)))

    for cap_dd in (0.10, 0.15, 0.20):
        for floor in (0.0, 0.5):
            S.append((f"DDctrl {cap_dd:.0%}/floor{floor:g}", "Drawdown ctrl",
                      drawdown_control(df, cap_dd, floor)))

    for low, high, calm, stress in ((15, 30, 1.0, 0.3), (15, 25, 1.0, 0.5),
                                     (12, 35, 1.2, 0.2), (18, 40, 1.0, 0.4)):
        S.append((f"VIXreg {low}-{high}", "VIX regime",
                  vix_regime(df, low / 100, high / 100, calm, stress)))

    for look in (21, 63):
        for sigma in (1.5, 2.0):
            for off in (0.0, 0.5):
                S.append((f"Derisk {look}d/{sigma}s/off{off:g}", "Downside",
                          downside_derisk(df, look, sigma, off, hold=63)))
    return S


def main() -> None:
    p = argparse.ArgumentParser(description="Map the defensive-exposure frontier.")
    p.add_argument("--years", type=float, default=21.0)
    p.add_argument("--outdir", default="studies/protective_puts/figures")
    args = p.parse_args()

    import matplotlib

    matplotlib.use("Agg")
    from studies.protective_puts import report

    df = data.load(years=args.years)
    rate = df["rate"]

    strategies = build_strategies(df)
    print(f"\nDEFENSIVE-EXPOSURE FRONTIER. SPY {df.index[0]:%Y-%m-%d} to {df.index[-1]:%Y-%m-%d}, "
          f"{len(df):,} sessions, {len(strategies)} strategies. Exploratory (see PROTOCOL.md).")

    bh = engine.run(df, scenarios.BUY_AND_HOLD)
    rows = {"Buy and hold": {**metrics.summarize(bh.equity, rate), "family": "Benchmark"}}
    curves = {"Buy and hold": bh.equity}
    for name, family, exp in strategies:
        res = engine.run_exposure(df, exp, name)
        rows[name] = {**metrics.summarize(res.equity, rate), "family": family}
        curves[name] = res.equity

    tbl = pd.DataFrame(rows).T
    for col in ("CAGR", "Vol", "Sharpe", "MaxDD", "Calmar"):
        tbl[col] = pd.to_numeric(tbl[col])

    front = non_dominated(tbl)
    tbl["frontier"] = tbl.index.isin(front)

    bh_row = tbl.loc["Buy and hold"]
    print(f"\nBuy and hold: CAGR {bh_row.CAGR:.2%}, Sharpe {bh_row.Sharpe:.2f}, "
          f"MaxDD {bh_row.MaxDD:.1%}, Calmar {bh_row.Calmar:.2f}")

    print(f"\nEFFICIENT FRONTIER ({len(front)} of {len(tbl)}), non-dominated on CAGR vs drawdown:")
    show = tbl.loc[front].sort_values("MaxDD")
    print(show[["family", "CAGR", "Vol", "Sharpe", "MaxDD", "Calmar"]].to_string(formatters={
        "CAGR": "{:.2%}".format, "Vol": "{:.1%}".format, "Sharpe": "{:.2f}".format,
        "MaxDD": "{:.1%}".format, "Calmar": "{:.2f}".format,
    }))

    best_sharpe = tbl.drop("Buy and hold").sort_values("Sharpe", ascending=False).head(5)
    best_calmar = tbl.drop("Buy and hold").sort_values("Calmar", ascending=False).head(5)
    print("\nTop Sharpe:", ", ".join(f"{i} ({r.Sharpe:.2f})" for i, r in best_sharpe.iterrows()))
    print("Top Calmar:", ", ".join(f"{i} ({r.Calmar:.2f})" for i, r in best_calmar.iterrows()))

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    print("\nFigure:", report.frontier_panel(tbl, curves, out))
    tbl.drop(columns=[]).to_csv(out / "frontier.csv")


def non_dominated(tbl: pd.DataFrame) -> list:
    """Efficient-frontier index labels: non-dominated on (CAGR up, MaxDD up).

    A point is dominated if another is at least as good on both and strictly better on one.
    Shared by frontier.py and findings.py so the frontier is defined in exactly one place.
    """
    keep = []
    for name, row in tbl.iterrows():
        dominated = (
            (tbl["CAGR"] >= row["CAGR"]) & (tbl["MaxDD"] >= row["MaxDD"])
            & ((tbl["CAGR"] > row["CAGR"]) | (tbl["MaxDD"] > row["MaxDD"]))
        ).any()
        if not dominated:
            keep.append(name)
    return keep


if __name__ == "__main__":
    main()
