"""Performance stats. Formula definitions: docs/formulas.md section 8."""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def drawdown(equity: pd.Series) -> pd.Series:
    return equity / equity.cummax() - 1


def summarize(equity: pd.Series, rate: pd.Series) -> dict:
    """Annualized stats. rate is the daily risk-free series, used as the Sharpe/Sortino hurdle."""
    ret = equity.pct_change().dropna()
    years = (equity.index[-1] - equity.index[0]).days / 365.25
    excess = ret - rate.reindex(ret.index).ffill() / TRADING_DAYS

    vol = ret.std(ddof=1) * np.sqrt(TRADING_DAYS)
    downside = ret[ret < 0].std(ddof=1) * np.sqrt(TRADING_DAYS)
    dd = drawdown(equity)
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1
    max_dd = dd.min()

    return {
        "CAGR": cagr,
        "Vol": vol,
        "Sharpe": excess.mean() / ret.std(ddof=1) * np.sqrt(TRADING_DAYS),
        "Sortino": excess.mean() * TRADING_DAYS / downside if downside else np.nan,
        "MaxDD": max_dd,
        "Calmar": cagr / abs(max_dd) if max_dd else np.nan,
        "Worst day": ret.min(),
        "Final": equity.iloc[-1],
    }


def table(results, rate: pd.Series) -> pd.DataFrame:
    """One row per strategy, plus what the protection cost and what it returned."""
    rows = {}
    for res in results:
        stats = summarize(res.equity, rate)
        stats["Premium"] = res.total_premium
        stats["Payoff"] = res.total_payoff
        stats["Recovery"] = res.recovery
        rows[res.name] = stats
    return pd.DataFrame(rows).T


FORMATS = {
    "CAGR": "{:.2%}", "Vol": "{:.2%}", "Sharpe": "{:.2f}", "Sortino": "{:.2f}",
    "MaxDD": "{:.1%}", "Calmar": "{:.2f}", "Worst day": "{:.1%}",
    "Final": "{:,.0f}", "Premium": "{:,.0f}", "Payoff": "{:,.0f}", "Recovery": "{:.0%}",
    "Duty": "{:.0%}", "Hedged": "{:.0%}",
}


def render(df: pd.DataFrame) -> str:
    out = df.copy()
    for col, fmt in FORMATS.items():
        if col in out:
            out[col] = out[col].map(lambda v, f=fmt: "n/a" if pd.isna(v) else f.format(v))
    return out.to_string()
