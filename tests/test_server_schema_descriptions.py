"""Regression test: `current_values`/`targets` on the cash-flow tools must carry
field-level `description`s in the exposed MCP JSON schema.

current_values holds absolute EUR amounts while targets holds weight fractions that must
sum to 1.0 (enforced by portfolio/rebalance.py's validate_targets). Nothing in the exposed
tool schema said so -- unlike `tickers_by_bucket` on backtest_plan, which already carries
Field(description="bucket -> yfinance ticker"). A model driving these tools cold had no
schema-level hint of the unit split or the sum-to-1 constraint.
"""

from __future__ import annotations

import portfolio_copilot.server as server


def _schema_properties(tool_name: str) -> dict:
    tools = {t.name: t for t in server.mcp._tool_manager.list_tools()}
    return tools[tool_name].parameters["properties"]


def test_allocate_cash_schema_documents_current_values_and_targets_units():
    props = _schema_properties("allocate_cash")
    assert "EUR" in props["current_values"]["description"]
    assert "1.0" in props["targets"]["description"]


def test_rebalance_portfolio_schema_documents_current_values_and_targets_units():
    props = _schema_properties("rebalance_portfolio")
    assert "EUR" in props["current_values"]["description"]
    assert "1.0" in props["targets"]["description"]


def test_generate_order_plan_schema_documents_current_values_and_targets_units():
    props = _schema_properties("generate_order_plan")
    assert "EUR" in props["current_values"]["description"]
    assert "1.0" in props["targets"]["description"]


def test_backtest_plan_schema_documents_targets_units():
    # backtest_plan has no current_values (it starts from initial_cash), only targets.
    props = _schema_properties("backtest_plan")
    assert "1.0" in props["targets"]["description"]
