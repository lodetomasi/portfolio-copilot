"""Server-level tests for the propose_replacement MCP tool's wiring -- the layer between
portfolio.replacement's pure function and the actual scoring/exposure/config plumbing.
Only the pure function was covered before (tests/test_replacement.py); none of this wiring
had any behavioral test, which is exactly why several defects here shipped undetected
(see the review findings this file locks fixes for).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import portfolio_copilot.server as server
from portfolio_copilot.models import Provenance, StockSnapshot


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
    """Isolate every test in this file from whatever theses.json happens to be on disk."""
    monkeypatch.setattr(server.thesis_module, "load_theses", lambda *a, **k: {})


# ---------------------------------------------------------------------------
# finding 13: the current holding's fit must never be measured against an
# exposure snapshot that already includes 100% of itself
# ---------------------------------------------------------------------------


def test_current_holding_fit_excludes_itself_from_the_exposure_snapshot(monkeypatch):
    # The live snapshot's own sector/industry must land in the SAME theme
    # (global_equity_core, via the "world equity" keyword) as the holding's name so a
    # genuine self-overlap is exercised -- otherwise the candidate's own classification
    # simply wouldn't intersect the portfolio's exposure map either way.
    monkeypatch.setattr(
        server,
        "_snapshot_with_official_data",
        lambda symbol, cross_check_sec: (
            _snapshot(symbol, sector="Global World Equity", industry="Diversified"),
            None,
        ),
    )
    holdings = [
        {
            "name": "Vanguard FTSE All-World UCITS ETF (USD) Acc",
            "symbol": "VWCE",
            "market_value": 10_000.0,
            "asset_type": "etf",
            "leverage": 1.0,
        },
    ]
    result = server.propose_replacement(
        current_symbol="VWCE",
        current_value_eur=10_000.0,
        candidate_tickers=[],
        holdings=holdings,
    )
    # Before the fix this was exactly 0.0: fit_score measured the holding against an
    # exposure map built FROM itself, so shared_driver_weight saturated to 1.0 and fit
    # collapsed to 0 regardless of how good the underlying score was.
    assert result["current_utility"] > 0.0


# ---------------------------------------------------------------------------
# finding 7: propose_replacement must respect risk_limits.max_single_stock_weight
# ---------------------------------------------------------------------------


def test_replace_buy_is_capped_by_configured_single_stock_weight(monkeypatch):
    def fake_score(symbol, cross_check_sec):
        if symbol.upper() == "HOT":
            return _snapshot(symbol, revenue_growth=0.35, earnings_growth=0.35, roe=0.30), None
        return _snapshot(symbol, revenue_growth=-0.05, earnings_growth=-0.05, roe=0.02), None

    monkeypatch.setattr(server, "_snapshot_with_official_data", fake_score)
    monkeypatch.setattr(
        server,
        "_load_portfolio_config",
        lambda *a, **k: {"risk_limits": {"max_single_stock_weight": 0.05}},
    )
    holdings = [
        {"symbol": "AAA", "name": "Company A", "market_value": 5_000.0,
         "asset_type": "equity", "leverage": 1.0},
    ]
    result = server.propose_replacement(
        current_symbol="AAA",
        current_value_eur=5_000.0,
        candidate_tickers=["HOT"],
        holdings=holdings,
        min_improvement=0.0,
        max_roundtrip_fee_ratio=1.0,
        cash_utility=0.0,
    )
    # HOT starts at 0% weight; 5% of the 5,000 EUR portfolio is only 250 EUR of headroom,
    # far below the ~4,994 EUR the sell leg would otherwise fund -- the cap must win.
    assert result["action"] == "HOLD"
    assert "cap" in result["reason"].lower()


def test_replace_buy_within_the_single_stock_cap_still_goes_through(monkeypatch):
    def fake_score(symbol, cross_check_sec):
        if symbol.upper() == "HOT":
            return _snapshot(symbol, revenue_growth=0.35, earnings_growth=0.35, roe=0.30), None
        return _snapshot(symbol, revenue_growth=-0.05, earnings_growth=-0.05, roe=0.02), None

    monkeypatch.setattr(server, "_snapshot_with_official_data", fake_score)
    monkeypatch.setattr(
        server,
        "_load_portfolio_config",
        lambda *a, **k: {"risk_limits": {"max_single_stock_weight": 1.0}},
    )
    holdings = [
        {"symbol": "AAA", "name": "Company A", "market_value": 5_000.0,
         "asset_type": "equity", "leverage": 1.0},
    ]
    result = server.propose_replacement(
        current_symbol="AAA",
        current_value_eur=5_000.0,
        candidate_tickers=["HOT"],
        holdings=holdings,
        min_improvement=0.0,
        max_roundtrip_fee_ratio=1.0,
        cash_utility=0.0,
    )
    assert result["action"] == "REPLACE"
    assert result["buy"]["symbol"] == "HOT"


# ---------------------------------------------------------------------------
# finding 10: utility() calls must be error-isolated like their neighboring
# _score_symbol_for_replacement calls
# ---------------------------------------------------------------------------


def test_out_of_range_score_for_a_candidate_lands_in_candidate_errors_not_a_crash(monkeypatch):
    def fake_score(ticker, exposure):
        if ticker.upper() == "BAD":
            return 80.0, 1.2, 1.0, None  # confidence 1.2 is out of [0, 1]
        return 50.0, 0.8, 1.0, None

    monkeypatch.setattr(server, "_score_symbol_for_replacement", fake_score)
    result = server.propose_replacement(
        current_symbol="CUR", current_value_eur=1_000.0, candidate_tickers=["GOOD", "BAD"]
    )
    assert "BAD" in result["candidate_errors"]
    assert any(c["symbol"] == "GOOD" for c in result["candidate_utilities"])


def test_out_of_range_score_for_current_symbol_raises_tool_error_not_a_crash(monkeypatch):
    def fake_score(ticker, exposure):
        return 80.0, 1.2, 1.0, None  # confidence 1.2 is out of [0, 1]

    monkeypatch.setattr(server, "_score_symbol_for_replacement", fake_score)
    with pytest.raises(ToolError):
        server.propose_replacement(
            current_symbol="CUR", current_value_eur=1_000.0, candidate_tickers=[]
        )


# ---------------------------------------------------------------------------
# finding 11: the tool's output must carry confidence, not just an opaque utility
# ---------------------------------------------------------------------------


def test_result_surfaces_confidence_for_current_and_candidates(monkeypatch):
    def fake_score(ticker, exposure):
        return 70.0, 0.42, 1.0, None

    monkeypatch.setattr(server, "_score_symbol_for_replacement", fake_score)
    result = server.propose_replacement(
        current_symbol="CUR", current_value_eur=1_000.0, candidate_tickers=["GOOD"]
    )
    assert result["current_confidence"] == 0.42
    assert result["candidate_utilities"][0]["confidence"] == 0.42


# ---------------------------------------------------------------------------
# finding 8/12: a real candidate ticker literally named CASH reaches the tool
# without being swallowed by the internal sentinel
# ---------------------------------------------------------------------------


def test_cash_named_candidate_survives_the_full_tool_wiring(monkeypatch):
    def fake_score(ticker, exposure):
        if ticker.upper() == "CASH":
            return 95.0, 0.9, 1.0, None
        return 20.0, 0.9, 1.0, None

    monkeypatch.setattr(server, "_score_symbol_for_replacement", fake_score)
    result = server.propose_replacement(
        current_symbol="CUR",
        current_value_eur=1_000.0,
        candidate_tickers=["CASH"],
        min_improvement=0.0,
        max_roundtrip_fee_ratio=1.0,
    )
    assert result["action"] == "REPLACE"
    assert result["buy"]["symbol"] == "CASH"


# ---------------------------------------------------------------------------
# finding 15: fit_score's theme-cap hard stop must actually be reachable when a
# real user config defines risk_limits.theme_caps -- not permanently dead code
# ---------------------------------------------------------------------------


def test_score_symbol_for_replacement_wires_theme_caps_from_config(monkeypatch):
    monkeypatch.setattr(
        server,
        "_load_portfolio_config",
        lambda *a, **k: {"risk_limits": {"theme_caps": {"semiconductors": 0.20}}},
    )
    monkeypatch.setattr(
        server,
        "_snapshot_with_official_data",
        lambda symbol, cross_check_sec: (
            _snapshot(symbol, sector=None, industry="Semiconductors"),
            None,
        ),
    )
    exposure = {"themes": {"semiconductors": 0.20}, "drivers": {}}
    score, confidence, fit, status = server._score_symbol_for_replacement("AMD", exposure)
    assert fit == 0.0
