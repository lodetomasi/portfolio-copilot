"""Server-level tests for personal_edge/decision_quality wiring: neither tool had any
behavioral coverage before (only their pure edge.py/quality.py counterparts were tested),
which is why the price-provenance drop (findings 28/29) and the decision_kind wiring for
bucket fills (finding 26) shipped without a test catching them.
"""

from __future__ import annotations

from datetime import UTC, datetime

import portfolio_copilot.server as server
from portfolio_copilot.models import Provenance, StockSnapshot
from portfolio_copilot.portfolio.ledger import DecisionRecord


def _snapshot(ticker: str, **overrides) -> StockSnapshot:
    data = dict(
        ticker=ticker,
        price=118.0,
        provenance=Provenance(
            source="yahooquery-fallback",
            as_of=datetime(2020, 1, 1, tzinfo=UTC),
            confidence=0.35,
            missing_fields=["market_cap"],
        ),
    )
    data.update(overrides)
    return StockSnapshot(**data)


def _decision(**overrides) -> DecisionRecord:
    data = dict(
        id="2020-01-01:AAPL:BUY",
        date="2020-01-01",
        symbol="AAPL",
        action="BUY",
        reason="test decision",
        price=100.0,
    )
    data.update(overrides)
    return DecisionRecord(**data)


# ---------------------------------------------------------------------------
# findings 28/29: price provenance must be surfaced, not silently discarded
# ---------------------------------------------------------------------------


def test_personal_edge_surfaces_price_provenance(monkeypatch):
    decision = _decision()
    monkeypatch.setattr(server, "load_decisions", lambda: [decision])
    monkeypatch.setattr(
        server.provider, "get_stock_snapshot", lambda symbol: _snapshot(symbol)
    )
    report = server.personal_edge(min_days=0, min_sample=1)
    assert "price_provenance" in report
    assert report["price_provenance"]["AAPL"]["source"] == "yahooquery-fallback"
    assert report["price_provenance"]["AAPL"]["confidence"] == 0.35


def test_decision_quality_surfaces_price_provenance(monkeypatch):
    decision = _decision()
    monkeypatch.setattr(server, "load_decisions", lambda: [decision])
    monkeypatch.setattr(
        server.provider, "get_stock_snapshot", lambda symbol: _snapshot(symbol)
    )
    result = server.decision_quality(decision.id)
    assert "price_provenance" in result
    assert result["price_provenance"]["AAPL"]["confidence"] == 0.35


# ---------------------------------------------------------------------------
# finding 26 (end-to-end): decision_kind recorded via log_decision must reach
# decision_quality's bucket-aware rubric
# ---------------------------------------------------------------------------


def test_log_decision_then_decision_quality_applies_bucket_rubric(tmp_path, monkeypatch):
    monkeypatch.setenv("PORTFOLIO_COPILOT_HOME", str(tmp_path))
    rec = server.log_decision(
        symbol="SWDA.MI",
        action="BUY",
        reason="Fills underweight core equity bucket per target allocation, twice over.",
        amount_eur=500.0,
        price=92.31,
        sources=["target_allocation"],
        confidence=0.9,
        decision_kind="bucket",
    )
    monkeypatch.setattr(
        server.provider, "get_stock_snapshot", lambda symbol: _snapshot(symbol, price=92.31)
    )
    result = server.decision_quality(rec["id"])
    assert result["quality"]["score"] >= 60.0


# ---------------------------------------------------------------------------
# finding 39: investor_relations_links' error paths must carry a full
# source/tier/confidence/as_of envelope, like every other provenance-bearing tool
# ---------------------------------------------------------------------------


class _NoWebsiteTicker:
    def __init__(self, symbol):
        self.info = {}


class _RaisingTicker:
    def __init__(self, symbol):
        pass

    @property
    def info(self):
        raise RuntimeError("boom")


def test_investor_relations_links_no_website_carries_full_provenance(monkeypatch):
    monkeypatch.setattr(server.yf, "Ticker", _NoWebsiteTicker)
    result = server.investor_relations_links("NOPE")
    assert result["ok"] is False
    assert result["source"] == "company_ir"
    assert result["tier"] == "A"
    assert result["confidence"] == 0.0
    assert "as_of" in result


def test_investor_relations_links_yfinance_failure_carries_full_provenance(monkeypatch):
    monkeypatch.setattr(server.yf, "Ticker", _RaisingTicker)
    result = server.investor_relations_links("NOPE")
    assert result["ok"] is False
    assert result["source"] == "company_ir"
    assert result["tier"] == "A"
    assert result["confidence"] == 0.0
    assert "as_of" in result


# ---------------------------------------------------------------------------
# finding 40: analyze_stock's evidence cross-check must compare the REAL
# pre-override yfinance reading, not the SEC value that already replaced it
# ---------------------------------------------------------------------------


def test_analyze_stock_evidence_uses_pre_override_snapshot_for_the_cross_check(monkeypatch):
    yfinance_snapshot = _snapshot("ACME", revenue_growth=0.30, provenance=Provenance(
        source="yfinance", as_of=datetime.now(UTC), confidence=0.8,
    ))
    monkeypatch.setattr(server.provider, "get_stock_snapshot", lambda ticker: yfinance_snapshot)
    monkeypatch.setattr(
        server.sec_provider,
        "get_company_facts",
        lambda ticker: {
            "ok": True, "fiscal_year": 2025, "as_of": "2026-03-01", "revenue_growth": -0.50,
        },
    )
    result = server.analyze_stock("ACME", cross_check_sec=True)
    metric = result["evidence"]["metrics"]["revenue_growth"]
    yfinance_reading = next(s for s in metric["sources"] if s["source"] == "yfinance")
    assert yfinance_reading["value"] == 0.30
    assert metric["status"] == "CONFLICT"
    assert metric["chosen_tier"] == "A"
