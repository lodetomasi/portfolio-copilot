"""Regression tests: the MCP tool `get_portfolio_config` must exist and expose
config/portfolio.yaml (falling back to config/portfolio.example.yaml) so skills can source
targets/fees/risk_limits/rebalancing rules from a tool instead of hand-reading the YAML file.
"""

from __future__ import annotations

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import portfolio_copilot.server as server


def test_get_portfolio_config_returns_the_repo_example_by_default():
    # This checkout has no user-created config/portfolio.yaml (it is git-ignored), so the
    # default call must fall back to config/portfolio.example.yaml and say so.
    result = server.get_portfolio_config()

    assert result["is_example"] is True
    assert result["source"].endswith("portfolio.example.yaml")
    assert result["risk_limits"]["max_single_stock_weight"] == 0.05
    assert result["fees"]["default_fixed_fee_eur"] == 2.95
    assert result["rebalancing"]["band_abs"] == 0.03


def test_get_portfolio_config_raises_tool_error_on_missing_explicit_path():
    with pytest.raises(ToolError, match="no/such/portfolio.yaml"):
        server.get_portfolio_config(path="/no/such/portfolio.yaml")
