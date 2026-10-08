"""Fund concentration from its top holdings."""

from __future__ import annotations

import numpy as np
import pandas as pd


def concentration(weights: pd.Series, n: int = 10) -> dict[str, float]:
    """Combined weight of the n largest holdings, the single largest, and the effective number
    of names among them (1 / sum of squared shares within the top n)."""
    w = pd.to_numeric(weights, errors="coerce").dropna().sort_values(ascending=False).head(n)
    if w.empty or w.sum() <= 0:
        return {"top": np.nan, "largest": np.nan, "effective": np.nan}
    share = w / w.sum()
    return {"top": float(w.sum()), "largest": float(w.iloc[0]), "effective": float(1 / (share**2).sum())}
