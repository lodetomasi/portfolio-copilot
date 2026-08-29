"""Regression test: every MCP tool wired into server.py during the integrator pass must be
reachable over the real stdio JSON-RPC transport, not merely importable as a Python
function -- a bad Annotated default, a name collision between a tool and the module it
wraps, or an eager network call in a module-level provider constructor would still pass a
plain `import server` but break `tools/list` for every real client.

Offline and deterministic: `tools/list` performs no network I/O (it only reads each
registered tool's schema), so spawning the server subprocess needs no mocking.
"""

from __future__ import annotations

import sys
from pathlib import Path

import anyio
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

REPO_ROOT = Path(__file__).resolve().parents[1]

# The 12 tools this integration pass adds on top of the pre-existing 16.
NEW_TOOL_NAMES = {
    "save_thesis",
    "check_thesis",
    "propose_replacement",
    "portfolio_exposure",
    "capital_auction",
    "personal_edge",
    "decision_quality",
    "macro_snapshot",
    "filing_sections",
    "insider_activity",
    "investor_relations_links",
    "map_holdings_to_targets",
    "save_portfolio_snapshot",
    "list_portfolio_snapshots",
    "compare_snapshots",
    "rank_candidates",
    "backtest_picker",
    "resolve_isins",
}

PRE_EXISTING_TOOL_NAMES = {
    "parse_portfolio_export",
    "get_portfolio_config",
    "analyze_stock",
    "screen_stocks",
    "portfolio_risk",
    "allocate_cash",
    "rebalance_portfolio",
    "generate_order_plan",
    "build_investment_plan",
    "backtest_plan",
    "discover_stocks",
    "log_decision",
    "review_decisions",
    "fx_rates",
    "convert_amount_to_eur",
    "company_facts",
}


async def _list_tool_names() -> set[str]:
    """Launch `python -m portfolio_copilot.server` as a real subprocess and ask it, over
    stdio JSON-RPC, which tools it exposes -- exactly what a real MCP client sees."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "portfolio_copilot.server"],
        cwd=str(REPO_ROOT),
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()
            return {tool.name for tool in result.tools}


def test_tools_list_over_stdio_includes_every_new_tool():
    names = anyio.run(_list_tool_names)
    missing = NEW_TOOL_NAMES - names
    assert not missing, f"missing from a real tools/list response: {sorted(missing)}"


def test_tools_list_over_stdio_still_includes_every_pre_existing_tool():
    """Guard against the new imports/singletons this pass adds accidentally shadowing or
    breaking registration of a tool that was already there."""
    names = anyio.run(_list_tool_names)
    missing = PRE_EXISTING_TOOL_NAMES - names
    assert not missing, f"pre-existing tool(s) dropped from tools/list: {sorted(missing)}"
