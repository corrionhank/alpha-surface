"""Black-Scholes puts, vectorized over a price path.

derive.black_scholes prices one option at a time. Marking a 21-year daily path across a dozen
scenarios and a skew sweep is a few million evaluations, so the study uses the array form.
The two must agree, and tests/test_protective_puts.py holds them to it.
"""

from __future__ import annotations

import numpy as np
from scipy.stats import norm


def put_price(S, K, T, r, sigma, q=0.0) -> np.ndarray:
    """Put value, elementwise over broadcastable arrays. T in years.

    At expiry (T <= 0) or with no vol, the put settles at discounted intrinsic, matching the
    degenerate branch in derive.black_scholes.price.
    """
    S, K, T, r, sigma, q = np.broadcast_arrays(
        *(np.asarray(x, dtype=float) for x in (S, K, T, r, sigma, q))
    )
    live = (T > 0) & (sigma > 0)

    # Placeholders keep the log and the division finite on the dead entries, which get masked out.
    T_safe = np.where(live, T, 1.0)
    sigma_safe = np.where(live, sigma, 1.0)

    vol = sigma_safe * np.sqrt(T_safe)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma_safe**2) * T_safe) / vol
    d2 = d1 - vol

    priced = K * np.exp(-r * T_safe) * norm.cdf(-d2) - S * np.exp(-q * T_safe) * norm.cdf(-d1)
    settled = np.maximum(K * np.exp(-r * T) - S * np.exp(-q * T), 0.0)
    return np.where(live, priced, settled)
