"""Market-state metrics and the regime flag."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from derive import market_state as ms


def test_percentile_rank():
    s = pd.Series([1.0, 2.0, 3.0, 4.0, np.nan])
    assert ms.percentile_rank(s, 2.5) == 0.5
    assert ms.percentile_rank(s, 0.0) == 0.0
    assert ms.percentile_rank(s, 10.0) == 1.0
    assert np.isnan(ms.percentile_rank(pd.Series(dtype=float), 1.0))
    assert np.isnan(ms.percentile_rank(s, float("nan")))


def test_rolling_vol_matches_summary_estimator():
    # Same estimator as present.summary.realized_vol, as a rolling series.
    from present.summary import realized_vol

    rng = np.random.default_rng(3)
    close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, 300))))
    rolled = ms.rolling_vol(close, window=60)
    point = realized_vol(close.tail(61), "1d")
    assert rolled.iloc[-1] == pytest.approx(point)


def test_sma_distance_flat_series_is_zero():
    close = pd.Series([50.0] * 300)
    assert ms.sma_distance(close, 200).iloc[-1] == 0.0


def test_drawdown_zero_at_high_negative_below():
    close = pd.Series([100.0, 110.0, 99.0])
    dd = ms.drawdown(close, window=252)
    assert dd.iloc[1] == 0.0
    assert dd.iloc[2] == pytest.approx((99 / 110 - 1) * 100)


def test_term_slope_sign():
    assert ms.term_slope(15.0, 18.0) > 0  # contango
    assert ms.term_slope(30.0, 24.0) < 0  # inverted


def test_regime_base_buckets():
    assert ms.regime(12.0, 0.1, 5.0) == "low_vol"
    assert ms.regime(16.0, 0.1, 5.0) == "normal"
    assert ms.regime(22.0, 0.1, 5.0) == "elevated"
    assert ms.regime(35.0, 0.1, 5.0) == "stress"


def test_regime_escalation():
    assert ms.regime(16.0, -0.05, 5.0) == "elevated"  # inversion bumps one bucket
    assert ms.regime(16.0, -0.05, -2.0) == "stress"  # inversion plus negative VRP bumps two
    assert ms.regime(35.0, -0.05, -2.0) == "stress"  # capped
    assert ms.regime(12.0, float("nan"), float("nan")) == "low_vol"  # NaN never escalates


def test_regime_requires_vix():
    with pytest.raises(ValueError):
        ms.regime(float("nan"))
