"""Server-level tests for the capital_auction MCP tool's wiring: config defaults,
out-of-range weight clamping and error surfacing for corrupted local state -- none of
this had behavioral coverage before (only a tools/list membership check).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import portfolio_copilot.server as server
from portfolio_copilot.models import Holding, Portfolio, Provenance, StockSnapshot
from portfolio_copilot.portfolio.thesis import load_theses as _real_load_theses


def _snapshot(ticker: str, **overrides) -> StockSnapshot:
    data = dict(
        ticker=ticker,
        currency="USD",
        price=100.0,
        revenue_growth=0.05,
        earnings_growth=0.05,
        gross_margin=0.35,
        operating_margin=0.10,
        roe=0.10,
        current_ratio=1.2,
        debt_to_equity=80.0,
        forward_pe=22.0,
        sector="Technology",
        industry="Semiconductors",
        provenance=Provenance(
            source="yfinance", as_of=datetime.now(UTC), confidence=0.9, tier="B"
        ),
    )
    data.update(overrides)
    return StockSnapshot(**data)


@pytest.fixture(autouse=True)
def _no_stored_theses(monkeypatch):
    monkeypatch.setattr(server.thesis_module, "load_theses", lambda *a, **k: {})


# ---------------------------------------------------------------------------
# finding 23: a negative or out-of-range computed weight must never crash the tool
# ---------------------------------------------------------------------------


def test_negative_holding_value_never_crashes_the_auction(monkeypatch):
    portfolio = Portfolio(
        holdings=[
            Holding(name="Core ETF", asset_type="etf", market_value=100_000.0),
            Holding(
                symbol="SHORT", name="Short position", asset_type="equity", market_value=-500.0
            ),
        ]
    )
    monkeypatch.setattr(server, "_parse_export", lambda path, base_currency="EUR": portfolio)
    monkeypatch.setattr(
        server,
        "_snapshot_with_official_data",
        lambda symbol, cross_check_sec: (_snapshot(symbol), None),
    )
    result = server.capital_auction(path="dummy.csv", cash_eur=1_000.0, candidate_tickers=["SHORT"])
    assert result["decision"] in {"BUY", "NO_BUY"}


# ---------------------------------------------------------------------------
# finding 21: a per-stock cap must never silently default to "no limit" (1.0)
# ---------------------------------------------------------------------------


def test_stock_cap_defaults_conservatively_when_risk_limits_missing(monkeypatch):
    portfolio = Portfolio(holdings=[])
    monkeypatch.setattr(server, "_parse_export", lambda path, base_currency="EUR": portfolio)
    monkeypatch.setattr(
        server, "_load_portfolio_config", lambda *a, **k: {"targets": {"core_global": 1.0}}
    )
    monkeypatch.setattr(server, "_load_model_portfolios", lambda *a, **k: {"instruments": {}})
    monkeypatch.setattr(
        server,
        "_snapshot_with_official_data",
        lambda symbol, cross_check_sec: (
            _snapshot(symbol, revenue_growth=0.5, earnings_growth=0.5, roe=0.4),
            None,
        ),
    )
    result = server.capital_auction(path="dummy.csv", cash_eur=90_000.0, candidate_tickers=["HOT"])
    order = next((o for o in result["orders"] if o["symbol"] == "HOT"), None)
    assert order is None or order["value_eur"] <= 0.05 * 90_000.0 + 1e-6


# ---------------------------------------------------------------------------
# finding 4: a corrupted theses.json must degrade to ToolError, not a raw crash
# ---------------------------------------------------------------------------


def test_corrupted_theses_json_raises_tool_error_not_a_raw_crash(monkeypatch, tmp_path):
    portfolio = Portfolio(
        holdings=[Holding(name="Core ETF", asset_type="etf", market_value=100_000.0)]
    )
    monkeypatch.setattr(server, "_parse_export", lambda path, base_currency="EUR": portfolio)
    monkeypatch.setattr(server.thesis_module, "load_theses", _real_load_theses)  # undo the fixture
    (tmp_path / "theses.json").write_text("{not valid json", encoding="utf-8")
    monkeypatch.setenv("PORTFOLIO_COPILOT_HOME", str(tmp_path))
    with pytest.raises(ToolError):
        server.capital_auction(path="dummy.csv", cash_eur=1_000.0, candidate_tickers=[])


# ---------------------------------------------------------------------------
# finding 46 (server wiring): an ambiguous instruments config must surface as a
# clean ToolError, not a raw ValueError, through every tool that maps holdings
# ---------------------------------------------------------------------------


def test_capital_auction_raises_tool_error_on_ambiguous_instruments_config(monkeypatch):
    portfolio = Portfolio(
        holdings=[Holding(name="Some fund", isin="IE00BK5BQT80", market_value=1_000.0)]
    )
    monkeypatch.setattr(server, "_parse_export", lambda path, base_currency="EUR": portfolio)
    monkeypatch.setattr(
        server,
        "_load_model_portfolios",
        lambda *a, **k: {
            "instruments": {
                "global_equity": {"isin": "IE00BK5BQT80"},
                "small_cap_dup": {"isin": "IE00BK5BQT80"},
            }
        },
    )
    monkeypatch.setattr(
        server, "_load_portfolio_config", lambda *a, **k: {"targets": {"global_equity": 1.0}}
    )
    with pytest.raises(ToolError):
        server.capital_auction(path="dummy.csv", cash_eur=100.0, candidate_tickers=[])


def test_map_holdings_to_targets_raises_tool_error_on_ambiguous_instruments_config(monkeypatch):
    portfolio = Portfolio(
        holdings=[Holding(name="Some fund", isin="IE00BK5BQT80", market_value=1_000.0)]
    )
    monkeypatch.setattr(server, "_parse_export", lambda path, base_currency="EUR": portfolio)
    monkeypatch.setattr(
        server,
        "_load_model_portfolios",
        lambda *a, **k: {
            "instruments": {
                "global_equity": {"isin": "IE00BK5BQT80"},
                "small_cap_dup": {"isin": "IE00BK5BQT80"},
            }
        },
    )
    monkeypatch.setattr(
        server, "_load_portfolio_config", lambda *a, **k: {"targets": {"global_equity": 1.0}}
    )
    with pytest.raises(ToolError):
        server.map_holdings_to_targets(path="dummy.csv")
