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


def portfolio_monthly_returns(asset_paths: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Portfolio monthly return per path/month under MONTHLY REBALANCING to fixed
    ``weights`` (declared assumption; Vanguard 2010: frequency does not materially
    change risk-adjusted outcomes): the weighted sum of asset returns each month.
    ``weights`` must be 1-D and match the asset axis."""
    w = np.asarray(weights, dtype=float)
    if w.ndim != 1 or asset_paths.shape[2] != w.size:
        raise ValueError(
            f"weights length {w.size} does not match n_assets {asset_paths.shape[2]}"
        )
    return asset_paths @ w


def unit_value_paths(asset_paths: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Value index paths starting at 1.0 (pure market movement, no flows)."""
    port = portfolio_monthly_returns(asset_paths, weights)
    return np.cumprod(1.0 + port, axis=1)


def pac_value_paths(
    asset_paths: np.ndarray,
    weights: np.ndarray,
    monthly_contribution: float,
    initial: float = 0.0,
) -> np.ndarray:
    """Plan value paths: the contribution lands at month START, then the month's
    portfolio return applies. Used for shortfall vs total contributed."""
    port = portfolio_monthly_returns(asset_paths, weights)
    n_paths, months = port.shape
    values = np.empty((n_paths, months))
    current = np.full(n_paths, float(initial))
    for t in range(months):
        current = (current + monthly_contribution) * (1.0 + port[:, t])
        values[:, t] = current
    return values


def max_drawdown_per_path(unit_paths: np.ndarray) -> np.ndarray:
    """Max drawdown of each unit-value path, INCLUDING the implicit 1.0 start
    (a path that only falls from day one must not read as 0 drawdown). Signed
    negative values (e.g. -0.55)."""
    padded = np.concatenate(
        [np.ones((unit_paths.shape[0], 1)), np.asarray(unit_paths, dtype=float)], axis=1
    )
    peaks = np.maximum.accumulate(padded, axis=1)
    drawdowns = padded / peaks - 1.0
    return drawdowns.min(axis=1)


def drawdown_stats(unit_paths: np.ndarray) -> dict:
    """Severity convention, fixed here and in the key names: ``p95_worst =
    np.percentile(dd, 5)`` is the drawdown only 5% of paths exceed in severity
    (values are signed negatives), ``p99_worst = np.percentile(dd, 1)``."""
    dd = max_drawdown_per_path(unit_paths)
    return {
        "p50": float(np.percentile(dd, 50)),
        "p95_worst": float(np.percentile(dd, 5)),
        "p99_worst": float(np.percentile(dd, 1)),
        "prob_worse_than": {
            "-35%": float(np.mean(dd <= -0.35)),
            "-50%": float(np.mean(dd <= -0.50)),
        },
    }


def shortfall_stats(pac_paths: np.ndarray, contributed_total: float) -> dict:
    """Final plan value vs total contributed, across paths."""
    if contributed_total <= 0:
        raise ValueError(f"contributed_total must be > 0, got {contributed_total}")
    final = np.asarray(pac_paths, dtype=float)[:, -1]
    return {
        "prob_final_below_contributed": float(np.mean(final < contributed_total)),
        "final_p5": float(np.percentile(final, 5)),
        "final_p50": float(np.percentile(final, 50)),
        "final_p95": float(np.percentile(final, 95)),
    }


def cvar(returns_monthly: np.ndarray, alpha: float = 0.95) -> dict:
    """Historical Expected Shortfall of monthly returns, reported in RETURN terms
    (negative numbers), with the exact discrete estimator of Rockafellar & Uryasev
    2000: ``CVaR = lambda * VaR + (1 - lambda) * CVaR+`` where ``lambda =
    (psi(VaR) - alpha) / (1 - alpha)`` -- the plain tail mean is CVaR+ and is wrong
    whenever alpha splits an atom of the empirical distribution.

    Returns ``{"cvar", "var", "n_tail_obs", "alpha"}``; ``n_tail_obs`` (how many
    observations sit beyond VaR) belongs next to the number wherever it is shown --
    with 60-300 monthly observations the tail holds 3-15 points (Yamai & Yoshiba
    2002), so the figure is an estimate with declared support, never false precision.
    """
    arr = np.asarray(returns_monthly, dtype=float)
    if arr.size == 0:
        raise ValueError("returns_monthly is empty")
    if np.isnan(arr).any():
        raise ValueError("returns_monthly contains NaN")
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")

    losses = -arr
    n = losses.size
    k = int(np.ceil(alpha * n))
    var_loss = float(np.sort(losses)[k - 1])
    psi = float(np.mean(losses <= var_loss))
    lam = (psi - alpha) / (1.0 - alpha)
    tail = losses[losses > var_loss]
    n_tail = int(tail.size)
    cvar_plus = float(tail.mean()) if n_tail else var_loss
    cvar_loss = lam * var_loss + (1.0 - lam) * cvar_plus
    return {"cvar": -cvar_loss, "var": -var_loss, "n_tail_obs": n_tail, "alpha": alpha}


def kelly_fraction(p_win: float, payoff_ratio: float, fraction: float = 0.5) -> float:
    """Fractional Kelly: ``max(0, p - (1 - p) / payoff_ratio) * fraction``.

    Default 0.5 (half-Kelly): 75% of full-Kelly growth with P(double before halving)
    0.89 vs 0.67 (MacLean-Thorp-Ziemba 2010), and estimated means carry ~10x the
    error weight of variances (Chopra & Ziemba 1993) -- over-betting costs growth AND
    safety, so the venue cap must always win over Kelly at the call site. A negative
    edge returns 0.0: never a negative size.
    """
    if not 0.0 < p_win < 1.0:
        raise ValueError(f"p_win must be in (0, 1), got {p_win}")
    if payoff_ratio <= 0.0:
        raise ValueError(f"payoff_ratio must be > 0, got {payoff_ratio}")
    if not 0.0 < fraction <= 1.0:
        raise ValueError(f"fraction must be in (0, 1], got {fraction}")
    full = p_win - (1.0 - p_win) / payoff_ratio
    return max(0.0, full * fraction)
