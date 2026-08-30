"""Offline, deterministic tests for analytics.risk_math (pure math, no I/O)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from portfolio_copilot.analytics.risk_math import (
    block_bootstrap_paths,
    cvar,
    default_mean_block,
    drawdown_stats,
    kelly_fraction,
    max_drawdown_per_path,
    monthly_returns,
    pac_value_paths,
    portfolio_monthly_returns,
    shortfall_stats,
    unit_value_paths,
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


# ---------------------------------------------------------------------------
# value paths, drawdown_stats, shortfall_stats
# ---------------------------------------------------------------------------


def test_portfolio_monthly_returns_is_weighted_sum():
    asset_paths = np.array([[[0.10, -0.02], [0.00, 0.04]]])  # 1 path, 2 mesi, 2 asset
    port = portfolio_monthly_returns(asset_paths, np.array([0.5, 0.5]))
    assert port == pytest.approx(np.array([[0.04, 0.02]]))


def test_portfolio_monthly_returns_weight_mismatch_raises():
    asset_paths = np.zeros((1, 2, 3))
    with pytest.raises(ValueError):
        portfolio_monthly_returns(asset_paths, np.array([0.5, 0.5]))


def test_unit_value_paths_compounds_from_one():
    asset_paths = np.array([[[0.10], [0.10]]])  # 1 path, 2 mesi, 1 asset
    unit = unit_value_paths(asset_paths, np.array([1.0]))
    assert unit == pytest.approx(np.array([[1.10, 1.21]]))


def test_pac_value_paths_contributes_at_month_start():
    asset_paths = np.array([[[0.10], [0.10]]])
    pac = pac_value_paths(asset_paths, np.array([1.0]), monthly_contribution=100.0)
    # (0+100)*1.1 = 110; (110+100)*1.1 = 231
    assert pac == pytest.approx(np.array([[110.0, 231.0]]))


def test_max_drawdown_per_path_prepends_the_unit_start():
    rising = np.array([[1.1, 1.2]])
    assert max_drawdown_per_path(rising) == pytest.approx(np.array([0.0]))
    falling = np.array([[0.9]])
    assert max_drawdown_per_path(falling) == pytest.approx(np.array([-0.1]))


def test_drawdown_stats_severity_convention_worked_example():
    # 100 path con max drawdown noto dd_i = -i/100 (i = 1..100)
    unit_paths = np.array([[1.0 - i / 100.0] for i in range(1, 101)])
    stats = drawdown_stats(unit_paths)
    assert stats["p50"] == pytest.approx(-0.505)
    assert stats["p95_worst"] == pytest.approx(-0.9505)  # MAI ~ -0.05
    assert stats["p99_worst"] == pytest.approx(-0.9901)
    assert stats["prob_worse_than"]["-35%"] == pytest.approx(0.66)
    assert stats["prob_worse_than"]["-50%"] == pytest.approx(0.51)


def test_shortfall_stats_worked_example():
    pac_paths = np.array([[1000.0], [1300.0], [1100.0]])
    stats = shortfall_stats(pac_paths, contributed_total=1200.0)
    assert stats["prob_final_below_contributed"] == pytest.approx(2.0 / 3.0)
    assert stats["final_p50"] == pytest.approx(1100.0)


def test_shortfall_stats_non_positive_contributed_raises():
    with pytest.raises(ValueError):
        shortfall_stats(np.array([[1.0]]), contributed_total=0.0)


# ---------------------------------------------------------------------------
# cvar (Rockafellar-Uryasev lambda estimator) + kelly_fraction
# ---------------------------------------------------------------------------


def test_cvar_uses_rockafellar_uryasev_lambda_estimator():
    # perdite 0.01..0.30 (rendimenti -0.01..-0.30), n=30, alpha=0.95:
    # k = ceil(28.5) = 29 -> VaR_loss = 0.29, psi = 29/30, lambda = 1/3,
    # coda = {0.30} -> CVaR_loss = (1/3)*0.29 + (2/3)*0.30 = 0.2966667
    returns = np.array([-(i / 100.0) for i in range(1, 31)])
    result = cvar(returns, alpha=0.95)
    assert result["var"] == pytest.approx(-0.29)
    assert result["cvar"] == pytest.approx(-0.2966667, rel=1e-5)
    assert result["n_tail_obs"] == 1
    # la media semplice della coda (CVaR+) darebbe -0.30: l'estimatore giusto differisce
    assert result["cvar"] != pytest.approx(-0.30)


def test_cvar_lambda_zero_when_alpha_hits_an_atom():
    # n=20, alpha=0.95: k = 19, psi = 19/20 = alpha -> lambda = 0 -> CVaR = CVaR+
    returns = np.array([-(i / 100.0) for i in range(1, 21)])
    result = cvar(returns, alpha=0.95)
    assert result["var"] == pytest.approx(-0.19)
    assert result["cvar"] == pytest.approx(-0.20)


def test_cvar_invalid_inputs_raise():
    with pytest.raises(ValueError):
        cvar(np.array([]))
    with pytest.raises(ValueError):
        cvar(np.array([0.01, np.nan]))
    with pytest.raises(ValueError):
        cvar(np.array([0.01, -0.02]), alpha=1.0)


def test_kelly_fraction_worked_examples():
    assert kelly_fraction(0.6, 2.0, fraction=1.0) == pytest.approx(0.40)
    assert kelly_fraction(0.6, 2.0) == pytest.approx(0.20)  # half-Kelly default


def test_kelly_fraction_negative_edge_is_zero_never_negative():
    assert kelly_fraction(0.3, 1.0) == 0.0


def test_kelly_fraction_invalid_inputs_raise():
    with pytest.raises(ValueError):
        kelly_fraction(0.0, 2.0)
    with pytest.raises(ValueError):
        kelly_fraction(1.0, 2.0)
    with pytest.raises(ValueError):
        kelly_fraction(0.6, 0.0)
    with pytest.raises(ValueError):
        kelly_fraction(0.6, 2.0, fraction=0.0)
