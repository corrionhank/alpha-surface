"""Expected-move cone: EM = S * sigma * sqrt(t/365)."""

from __future__ import annotations

import math

from alphasurface.derive import expected_move as em


def test_cone_starts_at_spot_and_widens():
    c = em.cone(500.0, 0.20, 30)
    assert len(c) == 31
    assert c.iloc[0][["lo2", "lo1", "hi1", "hi2"]].tolist() == [500.0] * 4
    widths = c["hi1"] - c["lo1"]
    assert (widths.diff().dropna() > 0).all()


def test_cone_bands_are_symmetric_and_2sd_is_twice_1sd():
    c = em.cone(500.0, 0.20, 30)
    assert ((c["hi1"] - 500.0) - (500.0 - c["lo1"])).abs().max() < 1e-9
    assert ((c["hi2"] - 500.0) - 2 * (c["hi1"] - 500.0)).abs().max() < 1e-9


def test_cone_edge_matches_formula():
    c = em.cone(500.0, 0.20, 30)
    assert abs((c["hi1"].iloc[-1] - 500.0) - 500.0 * 0.20 * math.sqrt(30 / 365)) < 1e-9
