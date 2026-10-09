"""Implied vol panel: point changes, the term curve on common dates, today's priced move."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from alphasurface.derive import funds, iv_panel


def _s(values, start="2025-01-01"):
    return pd.Series(
        np.asarray(values, dtype=float), index=pd.bdate_range(start, periods=len(values)).date
    )


def test_changes_over_sessions():
    s = _s(np.arange(10.0, 40.0))  # 30 sessions, +1 a day
    out = iv_panel.changes(s)
    assert out["level"] == 39 and out["1d"] == 1 and out["1w"] == 5 and out["1m"] == 21
    assert out["pct_1y"] == pytest.approx(29 / 30)


def test_changes_short_and_empty():
    out = iv_panel.changes(_s([20.0, 21.0, 22.0]))
    assert out["1d"] == 1 and math.isnan(out["1w"]) and math.isnan(out["1m"])
    assert math.isnan(iv_panel.changes(pd.Series(dtype=float))["level"])


def test_panel_skips_missing():
    p = iv_panel.panel({"VIX": _s([15.0, 16.0]), "VXN": pd.Series(dtype=float)})
    assert list(p.index) == ["VIX"] and list(p.columns) == ["level", "1d", "1w", "1m", "pct_1y"]


def test_term_curve_uses_common_dates():
    n = 30
    series = {sym: _s(np.full(n, base) + np.arange(n)) for _, sym, base in iv_panel.TERM}
    series["^VIX1D"] = series["^VIX1D"].iloc[:-1]  # VIX1D one session behind
    curve = iv_panel.term_curve(series)
    assert list(curve.index) == ["VIX1D", "VIX9D", "VIX", "VIX3M", "VIX6M"]
    # Today is the last date every tenor has: one session before the others' last print.
    assert curve.loc["VIX", "Today"] == 30 + n - 2
    assert curve.loc["VIX", "A week ago"] == 30 + n - 7
    assert curve.attrs["asof"] == series["^VIX1D"].index[-1]


def test_iv_minus_rv_aligns():
    close = _s(100 * np.exp(np.cumsum(np.full(60, 0.01))))
    gap = iv_panel.iv_minus_rv(_s(np.full(60, 20.0)), close)
    assert len(gap) == 60 - 21 and gap.iloc[-1] == pytest.approx(
        20.0, abs=1e-9
    )  # constant drift: no vol


def test_priced_move_prefers_vix1d():
    assert iv_panel.priced_move_today(_s([15.87]), _s([20.0])) == (
        pytest.approx(15.87 / math.sqrt(252)),
        "VIX1D",
    )
    assert iv_panel.priced_move_today(pd.Series(dtype=float), _s([20.0]))[1] == "VIX"


def test_concentration():
    w = pd.Series([0.08, 0.07, 0.06, 0.04, 0.03, 0.03, 0.02, 0.02, 0.02, 0.02, 0.01])
    out = funds.concentration(w)
    assert out["top"] == pytest.approx(0.39) and out["largest"] == 0.08
    equal = funds.concentration(pd.Series([0.05] * 10))
    assert equal["effective"] == pytest.approx(10.0)
    assert math.isnan(funds.concentration(pd.Series(dtype=float))["top"])
