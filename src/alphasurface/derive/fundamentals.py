"""Fundamental ratios and statement growth. Pure functions of numbers and frames, no I/O.

Statements arrive long form, one row per (statement, freq, period_end, item, value), the shape
collector.fundamentals stores. Ratios take the provider's trailing figure when it has one and
fall back to one computed from the latest annual statements, so a field Yahoo leaves blank still
fills when the statements carry it.
"""

from __future__ import annotations

import math

import pandas as pd

# Display rows per statement: (label, Yahoo line items in order of preference).
ITEMS: dict[str, list[tuple[str, tuple[str, ...]]]] = {
    "income": [
        ("Revenue", ("Total Revenue", "Operating Revenue")),
        ("Gross profit", ("Gross Profit",)),
        ("Operating income", ("Operating Income", "Total Operating Income As Reported")),
        ("EBITDA", ("EBITDA", "Normalized EBITDA")),
        ("Net income", ("Net Income", "Net Income Common Stockholders")),
        ("Diluted EPS", ("Diluted EPS",)),
    ],
    "balance": [
        (
            "Cash and investments",
            ("Cash Cash Equivalents And Short Term Investments", "Cash And Cash Equivalents"),
        ),
        ("Total assets", ("Total Assets",)),
        ("Total liabilities", ("Total Liabilities Net Minority Interest",)),
        ("Total debt", ("Total Debt",)),
        ("Net debt", ("Net Debt",)),
        ("Shareholder equity", ("Stockholders Equity", "Common Stock Equity")),
    ],
    "cashflow": [
        ("Operating cash flow", ("Operating Cash Flow",)),
        ("Capital expenditure", ("Capital Expenditure",)),
        ("Free cash flow", ("Free Cash Flow",)),
        ("Buybacks", ("Repurchase Of Capital Stock",)),
        ("Dividends paid", ("Cash Dividends Paid", "Common Stock Dividend Paid")),
        ("Stock-based compensation", ("Stock Based Compensation",)),
    ],
}
PER_SHARE = {"Diluted EPS"}  # shown as is, never scaled to millions
# Growth is year over year: one period back for annual figures, four for quarterly.
LAG = {"annual": 1, "quarterly": 4}


def ratio(a: float | None, b: float | None) -> float:
    """a / b, NaN when either is missing or b is zero."""
    if a is None or b is None or a != a or b != b or b == 0:
        return math.nan
    return float(a) / float(b)


def change(new: float | None, base: float | None) -> float:
    """Relative change against the size of the base, so growth off a loss keeps its sign."""
    if new is None or base is None or new != new or base != base or base == 0:
        return math.nan
    return (float(new) - float(base)) / abs(float(base))


def wide(long: pd.DataFrame, statement: str, freq: str) -> pd.DataFrame:
    """Line items by period for one statement: display labels down, period ends across, newest
    first. Each label takes the first of its Yahoo items that has a value in that period."""
    rows = (
        long[(long["statement"] == statement) & (long["freq"] == freq)] if not long.empty else long
    )
    if rows.empty:
        return pd.DataFrame()
    grid = rows.pivot_table(index="item", columns="period_end", values="value", aggfunc="last")
    grid = grid[sorted(grid.columns, reverse=True)]
    out = {}
    for label, items in ITEMS[statement]:
        present = [i for i in items if i in grid.index]
        if present:
            out[label] = grid.loc[present].bfill().iloc[0]
    return pd.DataFrame(out).T if out else pd.DataFrame()


def growth(table: pd.DataFrame, lag: int) -> pd.DataFrame:
    """Each cell's change against the same row `lag` periods earlier (columns newest first)."""
    if table.empty:
        return table
    vals = table.to_numpy(dtype=float)
    out = pd.DataFrame(math.nan, index=table.index, columns=table.columns)
    for j in range(vals.shape[1] - lag):
        out.iloc[:, j] = [change(n, b) for n, b in zip(vals[:, j], vals[:, j + lag], strict=True)]
    return out


def latest(long: pd.DataFrame, statement: str, label: str, freq: str = "annual") -> float:
    """The newest value of one display row, NaN when the statement does not carry it."""
    table = wide(long, statement, freq)
    if table.empty or label not in table.index:
        return math.nan
    row = table.loc[label].dropna()
    return float(row.iloc[0]) if len(row) else math.nan


def key_ratios(snap: dict, long: pd.DataFrame) -> dict[str, float]:
    """Valuation and profitability, decimals except the multiples. snap is one fundamentals row."""

    def pick(field: str, fallback: float) -> float:
        v = snap.get(field)
        return float(v) if v is not None and v == v else fallback

    revenue = latest(long, "income", "Revenue")
    net = latest(long, "income", "Net income")
    equity = latest(long, "balance", "Shareholder equity")
    cap = pick("market_cap", math.nan)
    fcf = pick("free_cash_flow", latest(long, "cashflow", "Free cash flow"))
    return {
        "gross_margin": pick(
            "gross_margin", ratio(latest(long, "income", "Gross profit"), revenue)
        ),
        "operating_margin": pick(
            "operating_margin", ratio(latest(long, "income", "Operating income"), revenue)
        ),
        "net_margin": pick("profit_margin", ratio(net, revenue)),
        "roe": pick("roe", ratio(net, equity)),
        "roa": pick("roa", ratio(net, latest(long, "balance", "Total assets"))),
        "debt_to_equity": pick(
            "debt_to_equity", ratio(latest(long, "balance", "Total debt"), equity)
        ),
        "fcf_yield": ratio(fcf, cap),
        "ev_to_ebitda": pick(
            "ev_to_ebitda", ratio(snap.get("enterprise_value"), latest(long, "income", "EBITDA"))
        ),
        "price_to_sales": pick("price_to_sales", ratio(cap, revenue)),
        "price_to_book": pick("price_to_book", ratio(cap, equity)),
    }


def surprise(actual: float | None, estimate: float | None) -> float:
    """Earnings surprise as a decimal of the estimate's size."""
    return change(actual, estimate)


def scale(values: pd.DataFrame | pd.Series) -> tuple[float, str]:
    """Divisor and unit for a block of dollar figures: billions when any reaches $1B."""
    arr = pd.Series(values.to_numpy().ravel(), dtype=float).abs().dropna()
    return (1e9, "B") if len(arr) and arr.max() >= 1e9 else (1e6, "M")
