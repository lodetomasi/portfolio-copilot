"""Regression tests: targets/fees/risk_limits/rebalancing rules must be loadable through a
deterministic Python loader (and, from server.py, an MCP tool), not hand-read by Claude from
the raw YAML. Every skill that touches these numbers promises "every number comes from an
MCP tool, never from memory or mental math" -- until this loader exists, nothing backs that
promise for config/portfolio.yaml.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from portfolio_copilot.portfolio.config import (
    EXAMPLE_CONFIG_PATH,
    load_portfolio_config,
)

EXAMPLE_TEXT = EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")


def test_load_portfolio_config_falls_back_to_example_when_default_missing(tmp_path: Path):
    default_path = tmp_path / "portfolio.yaml"
    example_path = tmp_path / "portfolio.example.yaml"
    example_path.write_text(EXAMPLE_TEXT, encoding="utf-8")

    result = load_portfolio_config(default_path=default_path, example_path=example_path)

    assert result["is_example"] is True
    assert result["source"] == str(example_path)
    assert result["targets"] == {
        "global_equity": 0.70,
        "small_cap": 0.10,
        "emerging_markets": 0.05,
        "global_bonds_hedged": 0.15,
    }
    assert result["risk_limits"]["max_single_stock_weight"] == 0.05


def test_load_portfolio_config_prefers_the_users_own_file_when_present(tmp_path: Path):
    default_path = tmp_path / "portfolio.yaml"
    example_path = tmp_path / "portfolio.example.yaml"
    example_path.write_text(EXAMPLE_TEXT, encoding="utf-8")
    default_path.write_text(
        yaml.safe_dump({"targets": {"only_bucket": 1.0}, "risk_limits": {}}),
        encoding="utf-8",
    )

    result = load_portfolio_config(default_path=default_path, example_path=example_path)

    assert result["is_example"] is False
    assert result["source"] == str(default_path)
    assert result["targets"] == {"only_bucket": 1.0}


def test_load_portfolio_config_raises_on_missing_explicit_path_without_falling_back(
    tmp_path: Path,
):
    missing = tmp_path / "nope.yaml"
    with pytest.raises(FileNotFoundError, match="nope.yaml"):
        load_portfolio_config(missing)


def test_load_portfolio_config_reports_as_of_from_file_mtime(tmp_path: Path):
    default_path = tmp_path / "portfolio.yaml"
    default_path.write_text(yaml.safe_dump({"targets": {"a": 1.0}}), encoding="utf-8")

    result = load_portfolio_config(default_path=default_path, example_path=default_path)

    assert result["as_of"], "as_of must be populated, never invented as a blank"


def test_real_example_config_defines_all_three_stock_category_caps():
    """quality/growth/high-risk are the three tiers used across stock-picker and
    position-review; all three must be real config keys, not two real plus one invented."""
    result = load_portfolio_config(EXAMPLE_CONFIG_PATH)
    risk_limits = result["risk_limits"]
    assert risk_limits["max_single_stock_weight"] == 0.05
    assert risk_limits["max_growth_stock_weight"] == 0.04
    assert risk_limits["max_high_risk_stock_weight"] == 0.02


def test_example_targets_use_model_portfolio_bucket_names():
    """Regression (live run 2026-08-29): the example targets used `core_global` while the
    mapping/model portfolios use `global_equity`, so the capital auction proposed buying an
    'empty' bucket the user already held at 79%. Every example target bucket must be a known
    instrument bucket, and the weights must sum to 1."""
    from portfolio_copilot.portfolio.config import load_portfolio_config
    from portfolio_copilot.portfolio.plan import load_model_portfolios

    cfg = load_portfolio_config("config/portfolio.example.yaml")
    buckets = set(load_model_portfolios()["instruments"])
    targets = cfg["targets"]
    assert targets, "example config must ship non-empty targets"
    unknown = set(targets) - buckets
    assert not unknown, f"example targets use unknown buckets {unknown}; known: {sorted(buckets)}"
    assert abs(sum(targets.values()) - 1.0) < 1e-9
