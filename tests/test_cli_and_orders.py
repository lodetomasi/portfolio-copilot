"""CLI (typer) smoke tests on synthetic fixtures and the fee-estimator edge cases required by
CLAUDE.md ("commissioni > ordine"). Offline, deterministic."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from portfolio_copilot.cli import app
from portfolio_copilot.portfolio.orders import estimate_order_cost
from portfolio_copilot.portfolio.rebalance import FeeModel

FIXTURE = Path(__file__).parent / "fixtures" / "broker_export_page_layout.csv"
runner = CliRunner()


def test_cli_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("parse", "risk", "stock"):
        assert command in result.output


def test_cli_parse_prints_normalized_portfolio_json():
    result = runner.invoke(app, ["parse", str(FIXTURE)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert len(payload["holdings"]) == 7
    assert payload["holdings"][0]["symbol"] == "AB"


def test_cli_risk_prints_concentration_and_leverage():
    result = runner.invoke(app, ["risk", str(FIXTURE)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert round(payload["total_value"], 2) == 4147.02
    assert payload["concentration"]["top1"] > 0.7
    assert payload["leveraged_equivalent_exposure"] == 220.0 * 5 + 90.0 * 3


def test_cli_parse_missing_file_fails_loudly():
    result = runner.invoke(app, ["parse", "/nonexistent/export.csv"])
    assert result.exit_code != 0


def test_estimate_order_cost_flags_fee_larger_than_order_as_uneconomic():
    out = estimate_order_cost(40.0, FeeModel(fixed_fee_eur=50.0, max_fee_ratio=0.01))
    assert out["estimated_fee_eur"] == 50.0
    assert out["fee_ratio"] == 1.25
    assert out["economic"] is False
    assert out["minimum_economic_order_eur"] == 5000.0


def test_estimate_order_cost_zero_order_has_no_ratio():
    out = estimate_order_cost(0.0, FeeModel())
    assert out["fee_ratio"] is None and out["economic"] is False


def test_estimate_order_cost_default_model_minimum_is_295():
    out = estimate_order_cost(300.0, FeeModel())
    assert out["economic"] is True
    assert out["minimum_economic_order_eur"] == 295.0
