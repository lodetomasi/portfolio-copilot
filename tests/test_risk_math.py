"""Offline, deterministic tests for analytics.risk_math (pure math, no I/O)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from portfolio_copilot.analytics.risk_math import (
    block_bootstrap_paths,
    default_mean_block,
    monthly_returns,
)

FIXTURE = Path(__file__).parent / "fixtures" / "risk_math_closes.csv"


def _closes() -> pd.DataFrame:
    return pd.read_csv(FIXTURE, index_col=0, parse_dates=True)


def _returns() -> pd.DataFrame:
    return monthly_returns(_closes())


def test_monthly_returns_shape_and_first_value():
    closes = _closes()
    returns = monthly_returns(closes)
    assert len(returns) == 120
    expected = closes.iloc[1]["eq"] / closes.iloc[0]["eq"] - 1.0
    assert returns.iloc[0]["eq"] == pytest.approx(expected)


def test_monthly_returns_drops_all_nan_column_and_declares_it():
    closes = _closes()
    closes["dead"] = np.nan
    returns = monthly_returns(closes)
    assert "dead" not in returns.columns
    assert returns.attrs["dropped"] == ["dead"]


def test_monthly_returns_counts_dropped_joint_rows():
    closes = _closes()
    closes.iloc[10, 1] = np.nan  # one NaN close kills two return rows (10-1 and 10)
    returns = monthly_returns(closes)
    assert returns.attrs["rows_dropped"] == 2
    assert len(returns) == 118


def test_monthly_returns_insufficient_history_raises():
    with pytest.raises(ValueError, match="insufficient"):
        monthly_returns(_closes().head(20))


def test_default_mean_block_follows_cube_root_rule_with_clamp():
    assert default_mean_block(68) == 4
    assert default_mean_block(300) == 7
    assert default_mean_block(8) == 2  # clamp basso
    assert default_mean_block(5000) == 12  # clamp alto


def test_bootstrap_shape_and_determinism():
    returns = _returns()
    a = block_bootstrap_paths(returns, months=36, n_paths=50, seed=42)
    b = block_bootstrap_paths(returns, months=36, n_paths=50, seed=42)
    c = block_bootstrap_paths(returns, months=36, n_paths=50, seed=43)
    assert a.shape == (50, 36, 3)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_bootstrap_samples_only_joint_source_rows():
    returns = _returns()
    source = {tuple(row) for row in returns.to_numpy()}
    paths = block_bootstrap_paths(returns, months=24, n_paths=20, seed=1)
    sampled = {tuple(row) for row in paths.reshape(-1, 3)}
    assert sampled <= source


def test_bootstrap_blocks_are_contiguous_with_wrap():
    n_obs = 60
    encoded = pd.DataFrame(
        {"a": np.arange(n_obs, dtype=float), "b": np.arange(n_obs, dtype=float)}
    )
    paths = block_bootstrap_paths(encoded, months=200, n_paths=30, seed=5, mean_block=4)
    idx = paths[:, :, 0]
    continuations = (idx[:, 1:] == (idx[:, :-1] + 1) % n_obs).mean()
    # p_restart = 1/4: attesi ~75% passi contigui (il seed fisso rende il valore stabile)
    assert 0.65 <= continuations <= 0.85


def test_bootstrap_invalid_inputs_raise():
    returns = _returns()
    with pytest.raises(ValueError):
        block_bootstrap_paths(returns, months=0, n_paths=10, seed=1)
    with pytest.raises(ValueError):
        block_bootstrap_paths(returns, months=12, n_paths=0, seed=1)
    with pytest.raises(ValueError):
        block_bootstrap_paths(returns, months=12, n_paths=10, seed=1, mean_block=0)
    broken = returns.copy()
    broken.iloc[3, 1] = np.nan
    with pytest.raises(ValueError):
        block_bootstrap_paths(broken, months=12, n_paths=10, seed=1)
