"""Regression tests: expected validation failures inside MCP tools must reach the
client as `ToolError`, not fall through to the SDK's generic
`UnexpectedToolError("Error executing tool <name>")`.

The installed MCP SDK (mcp.server.mcpserver.tools.base.Tool.run) only forwards a
tool's failure text when the tool raises `ToolError` (or `ResourceError`) itself;
any other exception is swallowed into a message that names only the tool. Several
tools in server.py call code that raises plain `ValueError`/`FileNotFoundError`
for entirely expected conditions (targets not summing to 1.0, a missing export
path, unmappable columns) without translating them, so today those messages never
reach Claude -- breaking skills/rebalance/SKILL.md and
skills/portfolio-review/SKILL.md, which promise to report them verbatim.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import portfolio_copilot.server as server


def test_allocate_cash_raises_tool_error_with_message_when_targets_dont_sum_to_one():
    with pytest.raises(ToolError, match="Targets must sum to 1.0"):
        server.allocate_cash(
            current_values={"a": 100.0},
            targets={"a": 0.5, "b": 0.2},
            cash_eur=10.0,
        )


def test_rebalance_portfolio_raises_tool_error_with_message_when_targets_dont_sum_to_one():
    with pytest.raises(ToolError, match="Targets must sum to 1.0"):
        server.rebalance_portfolio(
            current_values={"a": 100.0},
            targets={"a": 0.5, "b": 0.2},
        )


def test_generate_order_plan_raises_tool_error_with_message_when_targets_dont_sum_to_one():
    with pytest.raises(ToolError, match="Targets must sum to 1.0"):
        server.generate_order_plan(
            current_values={"a": 100.0},
            targets={"a": 0.5, "b": 0.2},
            cash_eur=10.0,
        )


def test_parse_portfolio_export_tool_raises_tool_error_with_path_on_missing_file():
    missing_path = "/no/such/file.csv"
    with pytest.raises(ToolError, match="no/such/file.csv"):
        server.parse_portfolio_export(missing_path)


def test_parse_portfolio_export_tool_raises_tool_error_on_unmappable_columns(tmp_path: Path):
    bad = tmp_path / "bad.csv"
    bad.write_text("a;b;c\n1;2;3\n", encoding="utf-8")
    with pytest.raises(ToolError, match="Could not map"):
        server.parse_portfolio_export(str(bad))


def test_portfolio_risk_tool_raises_tool_error_with_path_on_missing_file():
    missing_path = "/no/such/file.csv"
    with pytest.raises(ToolError, match="no/such/file.csv"):
        server.portfolio_risk(missing_path)


def test_company_facts_degrades_instead_of_crashing_on_sec_http_error(monkeypatch):
    """company_facts must degrade like _snapshot_with_official_data does (server.py:63-72),
    not let a raw httpx.HTTPError blow through the MCP tool boundary (CLAUDE.md rule 6)."""

    def boom(ticker):
        raise httpx.HTTPStatusError("403 Forbidden", request=None, response=None)

    monkeypatch.setattr(server.sec_provider, "get_company_facts", boom)
    result = server.company_facts("MU")
    assert result["ok"] is False
    assert result["confidence"] == 0.0
    assert "403" in result["error"]
    assert result["ticker"] == "MU"


def test_build_investment_plan_raises_tool_error_on_negative_cash_now():
    """build_investment_plan calls _build_plan (portfolio/plan.py:115) directly with no
    try/except, so a plain ValueError from an invalid rookie input falls through to the
    SDK's generic UnexpectedToolError instead of reaching Claude with the actual reason."""
    with pytest.raises(ToolError, match="cash_now cannot be negative"):
        server.build_investment_plan(
            cash_now=-100.0,
            monthly_contribution=100.0,
            horizon_years=10.0,
            risk_tolerance="medium",
        )


def test_build_investment_plan_raises_tool_error_on_invalid_risk_tolerance():
    """Same gap via a different call site (portfolio/plan.py:44, suggest_profile)."""
    with pytest.raises(ToolError, match="risk_tolerance must be one of"):
        server.build_investment_plan(
            cash_now=1000.0,
            monthly_contribution=100.0,
            horizon_years=10.0,
            risk_tolerance="aggressive",
        )


def test_discover_stocks_raises_tool_error_on_unknown_preset():
    """discover_stocks calls FinvizProvider.screen() directly with no try/except, so an
    unknown preset's ValueError (providers/finviz.py:62) never reaches Claude."""
    with pytest.raises(ToolError, match="Unknown preset"):
        server.discover_stocks(preset="not_a_real_preset")


def test_filing_sections_degrades_instead_of_crashing_on_malformed_sec_json(monkeypatch):
    """filing_sections only caught httpx.HTTPError, so a malformed (non-JSON or non-dict)
    data.sec.gov response raised a raw JSONDecodeError/ValueError straight through the MCP
    tool boundary instead of the same readable ok=False result the module promises for
    every other external-data failure (a missing CIK, a missing filing)."""
    from portfolio_copilot.providers import sec_filings as sec_filings_module

    def boom(ticker, form="10-K", items=("1A", "7")):
        raise ValueError("Malformed SEC submissions payload for CIK 1: expected a JSON object")

    monkeypatch.setattr(sec_filings_module, "filing_sections", boom)
    result = server.filing_sections("ACME")
    assert result["ok"] is False
    assert result["confidence"] == 0.0
    assert "Malformed" in result["error"]
