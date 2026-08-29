"""Advanced risk math: stationary-bootstrap Monte Carlo, drawdown/shortfall
distributions, discrete CVaR, fractional Kelly.

Pure math on pandas/numpy inputs, zero I/O (same boundary as ``analytics/metrics.py``).
Parameter sources (verified 2026-08-29 against the primary PDFs):

- Stationary bootstrap: Politis & Romano 1994; mean block length rule ``n ** (1/3)``
  clamped to [2, 12] per Patton, Politis & White 2009 (optimal-rate correction of
  Politis & White 2004) -- for monthly equity returns the optimum is ~2-4, NOT 12.
- Discrete CVaR estimator: Rockafellar & Uryasev 2000 (``lambda * VaR +
  (1 - lambda) * CVaR+``); small-sample tail caveat: Yamai & Yoshiba 2002.
- Fractional Kelly (default 0.5): MacLean, Thorp & Ziemba 2010; estimation-error
  asymmetry: Chopra & Ziemba 1993.
- Quantile MC standard error (10k paths for a p99): Dong & Nakayama 2020 / Glasserman 2003.
- Monthly-rebalancing simulation assumption: Jaconetti, Kinniry & Zilbering (Vanguard) 2010.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_JOINT_OBSERVATIONS = 24


def monthly_returns(closes: pd.DataFrame) -> pd.DataFrame:
    """Joint monthly simple returns from a closes frame.

    All-NaN columns are dropped and listed in ``result.attrs["dropped"]``; rows with
    any remaining NaN are dropped so the history stays JOINT (cross-asset correlations
    need aligned rows) and their COUNT is declared in ``result.attrs["rows_dropped"]``
    -- never silently ignored. Fewer than ``MIN_JOINT_OBSERVATIONS`` joint rows raises
    ``ValueError`` -- simulating on insufficient history would invent precision that
    is not there.
    """
    if closes is None or closes.empty:
        raise ValueError("closes is empty")
    dropped = [col for col in closes.columns if closes[col].dropna().empty]
    frame = closes.drop(columns=dropped)
    if frame.empty:
        raise ValueError("closes has no usable columns")
    raw = frame.pct_change().iloc[1:]
    returns = raw.dropna(how="any")
    if len(returns) < MIN_JOINT_OBSERVATIONS:
        raise ValueError(
            f"insufficient joint history: {len(returns)} monthly observations "
            f"(< {MIN_JOINT_OBSERVATIONS})"
        )
    returns.attrs["dropped"] = dropped
    returns.attrs["rows_dropped"] = int(len(raw) - len(returns))
    return returns


def default_mean_block(n_obs: int) -> int:
    """Mean block length ``clamp(round(n_obs ** (1/3)), 2, 12)`` -- the N^(1/3)
    optimal-rate rule (Patton-Politis-White 2009)."""
    return int(min(12, max(2, round(n_obs ** (1.0 / 3.0)))))


def block_bootstrap_paths(
    returns: pd.DataFrame,
    months: int,
    n_paths: int,
    seed: int,
    mean_block: int | None = None,
) -> np.ndarray:
    """Stationary bootstrap (Politis & Romano 1994) of joint monthly return rows.

    Index recursion: with probability ``1 - 1/mean_block`` the next month continues
    the current block (previous index + 1, circular wrap), otherwise it restarts at a
    uniform index -- geometric block lengths with the given mean, rows always sampled
    JOINTLY so cross-asset correlation survives. Returns an array of shape
    ``(n_paths, months, n_assets)``. Same seed, same output (PCG64).
    """
    if months <= 0:
        raise ValueError(f"months must be > 0, got {months}")
    if n_paths <= 0:
        raise ValueError(f"n_paths must be > 0, got {n_paths}")
    values = returns.to_numpy(dtype=float)
    n_obs = values.shape[0]
    if n_obs < MIN_JOINT_OBSERVATIONS:
        raise ValueError(
            f"insufficient joint history: {n_obs} rows (< {MIN_JOINT_OBSERVATIONS})"
        )
    if np.isnan(values).any():
        raise ValueError("returns contain NaN: pass the output of monthly_returns")
    block = default_mean_block(n_obs) if mean_block is None else int(mean_block)
    if block < 1:
        raise ValueError(f"mean_block must be >= 1, got {mean_block}")

    rng = np.random.Generator(np.random.PCG64(seed))
    p_restart = 1.0 / block
    starts = rng.integers(0, n_obs, size=(n_paths, months))
    keep = rng.random((n_paths, months)) >= p_restart
    idx = np.empty((n_paths, months), dtype=np.int64)
    idx[:, 0] = starts[:, 0]
    for t in range(1, months):
        idx[:, t] = np.where(keep[:, t], (idx[:, t - 1] + 1) % n_obs, starts[:, t])
    return values[idx]
