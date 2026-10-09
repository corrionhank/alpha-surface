"""Expected move: the range implied vol projects to a horizon.

EM(1 sigma, t) = S * sigma * sqrt(t / 365). docs/formulas.md section 5. Descriptive of
what is priced, not a forecast: about 68% of outcomes land inside 1 SD if the implied
number is right, and realized distributions are fatter-tailed than lognormal.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def cone(spot: float, iv: float, days: int) -> pd.DataFrame:
    """1 and 2 SD bands per calendar day from day 0 (all bands at spot) to the horizon."""
    t = np.arange(days + 1)
    sd = spot * iv * np.sqrt(t / 365)
    return pd.DataFrame(
        {"day": t, "lo2": spot - 2 * sd, "lo1": spot - sd, "hi1": spot + sd, "hi2": spot + 2 * sd}
    )
