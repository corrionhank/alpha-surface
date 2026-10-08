"""The fear and greed lens: orientation of each component, bands, and no look-ahead."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from derive import sentiment


def _series(values, start="2015-01-01"):
    idx = pd.bdate_range(start, periods=len(values)).date
    return pd.Series(np.asarray(values, dtype=float), index=idx)


def _market(n=900, seed=1, spy_drift=0.0004, vix_level=18.0):
    rng = np.random.default_rng(seed)
    spy = _series(100 * np.exp(np.cumsum(spy_drift + 0.01 * rng.standard_normal(n))))
    vix = _series(vix_level + rng.standard_normal(n))
    vix3m = vix * 1.1
    tlt = _series(100 * np.exp(np.cumsum(0.005 * rng.standard_normal(n))))
    hyg = _series(80 * np.exp(np.cumsum(0.003 * rng.standard_normal(n))))
    ief = _series(95 * np.exp(np.cumsum(0.002 * rng.standard_normal(n))))
    return spy, vix, vix3m, tlt, hyg, ief


@pytest.mark.parametrize("score,band", [(10, "extreme fear"), (30, "fear"), (50, "neutral"),
                                        (60, "greed"), (90, "extreme greed"), (float("nan"), "n/a")])
def test_bands(score, band):
    assert sentiment.label(score) == band


def test_expanding_score_has_no_lookahead():
    s = _series(np.arange(400.0))
    sc = sentiment.expanding_score(s, min_history=10)
    assert sc.iloc[-1] == pytest.approx(100.0)  # a new high is the top of its own history so far
    assert sc.iloc[:9].isna().all()
    # Appending a larger value later must not change an earlier day's score.
    sc2 = sentiment.expanding_score(pd.concat([s, _series([1e6], "2030-01-01")]), min_history=10)
    assert sc2.iloc[200] == pytest.approx(sc.iloc[200])
    assert (100 - sc).iloc[-1] == pytest.approx(sentiment.expanding_score(s, True, 10).iloc[-1])


def test_score_is_an_average_of_components_in_range():
    fg = sentiment.fear_greed(*_market())
    assert 0 <= fg.score <= 100 and fg.label != "n/a"
    assert set(fg.components["name"]) == {"VIX vs 50-day", "SPY vs 125-day", "Term structure",
                                          "Safe-haven demand", "Junk-bond demand", "Realized vol"}
    assert fg.score == pytest.approx(fg.components["score"].mean())
    assert fg.history.between(0, 100).all()


def test_a_vix_spike_reads_as_fear():
    spy, vix, vix3m, tlt, hyg, ief = _market()
    calm = sentiment.fear_greed(spy, vix, vix3m, tlt, hyg, ief)
    spiked = vix.copy()
    spiked.iloc[-5:] = 45.0
    stressed = sentiment.fear_greed(spy, spiked, vix3m, tlt, hyg, ief)
    row = stressed.components.set_index("name")
    assert row.loc["VIX vs 50-day", "score"] < 5  # inverted: a spike is fear
    assert row.loc["Term structure", "score"] < 5  # VIX3M under VIX: backwardation
    assert stressed.score < calm.score


def test_short_history_leaves_components_out():
    spy, vix, vix3m, tlt, hyg, ief = _market(n=200)
    fg = sentiment.fear_greed(spy, vix, vix3m, tlt, hyg, ief)
    assert fg.score != fg.score and fg.label == "n/a"
