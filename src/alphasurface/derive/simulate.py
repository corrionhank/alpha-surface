"""Monte Carlo market scenarios: many hypothetical futures instead of one forecast.

One path is an anecdote. A few thousand are a distribution, and the distribution is the only
honest answer to "what happens next". Everything here returns arrays of shape
(n_paths, days + 1), one row per path, column 0 the starting price, one step per trading day.

Models, from fewest assumptions about the shape to most:
  gbm        dS/S = mu dt + sigma dW. Lognormal, thin-tailed. Stepped exactly in log space, so
             there is no discretization error at any step size.
  jump       GBM plus Poisson jumps with normal log sizes (Merton, 1976). A negative mean jump
             gives the fat left tail equity actually has. The drift is compensated so the mean
             still grows at mu.
  bootstrap  Standardized historical daily returns, resampled in blocks and rescaled to the
             chosen drift and vol. History supplies the shape (skew, kurtosis, short-range
             clustering); you supply the level.
Formulas: docs/formulas.md section 14.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252
DT = 1 / TRADING_DAYS


def _from_log_returns(spot: float, steps: np.ndarray) -> np.ndarray:
    paths = np.empty((steps.shape[0], steps.shape[1] + 1))
    paths[:, 0] = spot
    paths[:, 1:] = spot * np.exp(np.cumsum(steps, axis=1))
    return paths


def gbm(
    spot: float, mu: float, sigma: float, days: int, n_paths: int, rng: np.random.Generator
) -> np.ndarray:
    """Geometric Brownian motion. mu and sigma annualized, decimals."""
    z = rng.standard_normal((n_paths, days))
    return _from_log_returns(spot, (mu - 0.5 * sigma**2) * DT + sigma * math.sqrt(DT) * z)


def jump(
    spot: float,
    mu: float,
    sigma: float,
    days: int,
    n_paths: int,
    rng: np.random.Generator,
    rate: float = 3.0,
    mean: float = -0.04,
    std: float = 0.05,
) -> np.ndarray:
    """Merton jump diffusion. rate is jumps per year; mean and std describe the log jump size.

    The compensator k = E[e^Y] - 1 comes off the drift, so E[S_t] = S_0 e^(mu t) as in GBM and
    the only thing that changes is the shape: more mass in the tails, less in the shoulders.
    """
    k = math.exp(mean + 0.5 * std**2) - 1
    z = rng.standard_normal((n_paths, days))
    counts = rng.poisson(rate * DT, (n_paths, days))
    # A sum of n normal jumps is one normal with n times the mean and n times the variance.
    jumps = counts * mean + np.sqrt(counts) * std * rng.standard_normal((n_paths, days))
    drift = (mu - rate * k - 0.5 * sigma**2) * DT
    return _from_log_returns(spot, drift + sigma * math.sqrt(DT) * z + jumps)


def bootstrap(
    spot: float,
    mu: float,
    sigma: float,
    days: int,
    n_paths: int,
    rng: np.random.Generator,
    log_returns: np.ndarray,
    block: int = 5,
) -> np.ndarray:
    """Block bootstrap of standardized historical returns, rescaled to mu and sigma."""
    r = np.asarray(log_returns, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) <= block:
        raise ValueError("need more history than one block")
    z = (r - r.mean()) / r.std(ddof=1)
    n_blocks = -(-days // block)
    starts = rng.integers(0, len(z) - block, size=(n_paths, n_blocks))
    idx = (starts[..., None] + np.arange(block)).reshape(n_paths, -1)[:, :days]
    return _from_log_returns(spot, (mu - 0.5 * sigma**2) * DT + sigma * math.sqrt(DT) * z[idx])


def replay(closes: pd.Series, start, days: int, spot: float) -> pd.Series | None:
    """A historical window rescaled to start at spot: 'what if the next days look like then'.

    closes is indexed by date. The window starts on the first session at or after start.
    None if the history does not cover the whole window.
    """
    window = closes[closes.index >= pd.Timestamp(start).date()].iloc[: days + 1]
    if len(window) < days + 1:
        return None
    return spot * window / float(window.iloc[0])


# --- Reading a set of paths ---------------------------------------------------------------

PCTS = (1, 5, 25, 50, 75, 95, 99)


def bands(paths: np.ndarray, qs=(5, 25, 50, 75, 95)) -> pd.DataFrame:
    """Percentile of price at every step: the fan the paths make."""
    return pd.DataFrame(np.percentile(paths, qs, axis=0).T, columns=[f"p{q}" for q in qs])


def terminal_stats(paths: np.ndarray) -> dict:
    """Mean, median and percentiles of where the paths end, plus the odds of finishing up."""
    end, spot = paths[:, -1], paths[0, 0]
    out = {
        "mean": float(end.mean()),
        "median": float(np.median(end)),
        "std": float(end.std()),
        "p_up": float((end > spot).mean()),
    }
    out |= {f"p{q}": float(v) for q, v in zip(PCTS, np.percentile(end, PCTS), strict=False)}
    return out


def max_drawdown(paths: np.ndarray) -> np.ndarray:
    """Worst peak-to-trough fall along each path, as a negative fraction."""
    return (paths / np.maximum.accumulate(paths, axis=1) - 1).min(axis=1)


def touch_probability(paths: np.ndarray, level: float) -> float:
    """Share of paths that reach level at any step, from whichever side it sits on."""
    if level >= paths[0, 0]:
        return float((paths.max(axis=1) >= level).mean())
    return float((paths.min(axis=1) <= level).mean())


def var_cvar(pnl: np.ndarray, alpha: float = 0.95) -> tuple[float, float]:
    """Empirical value at risk and expected shortfall, as positive losses.

    VaR is the loss exceeded in (1 - alpha) of outcomes; CVaR is the average loss in that tail.
    Read straight off the simulated outcomes, so the tail is whatever the model put there:
    thin under GBM, fat under jumps or the bootstrap. No normal approximation.
    """
    pnl = np.asarray(pnl, dtype=float)
    cut = np.quantile(pnl, 1 - alpha)
    tail = pnl[pnl <= cut]
    return float(-cut), float(-tail.mean()) if len(tail) else float(-cut)


# --- Betting a fraction of the bankroll ---------------------------------------------------


def bet_paths(
    p: float, b: float, f: float, n_bets: int, n_paths: int, rng: np.random.Generator
) -> np.ndarray:
    """Wealth paths, starting at 1, staking fraction f on a bet that wins b per 1 with prob p."""
    wins = rng.random((n_paths, n_bets)) < p
    growth = np.where(wins, 1 + f * b, 1 - f)
    out = np.ones((n_paths, n_bets + 1))
    out[:, 1:] = np.cumprod(growth, axis=1)
    return out


def growth_rate(p: float, b: float, f: float | np.ndarray) -> np.ndarray:
    """Expected log growth per bet, g(f) = p ln(1 + f b) + (1 - p) ln(1 - f).

    The mean of wealth grows with f all the way up; this, which governs the median, peaks at
    Kelly and turns negative past roughly twice it.
    """
    f = np.asarray(f, dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        return p * np.log1p(f * b) + (1 - p) * np.log1p(-f)
