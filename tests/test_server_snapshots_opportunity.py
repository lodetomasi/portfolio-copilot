"""Server-level tests for the integrator pass: save_portfolio_snapshot/list_portfolio_snapshots/
compare_snapshots, log_decision's 'candidates' pass-through, capital_auction's
'candidates_for_ledger' price enrichment, and review_decisions' new 'opportunity' section.

Offline and deterministic throughout: every provider call is monkeypatched, and
PORTFOLIO_COPILOT_HOME is redirected to tmp_path by an autouse fixture so nothing here ever
touches the real data/private store.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import portfolio_copilot.server as server
from portfolio_copilot.models import Holding, Portfolio, Provenance, StockSnapshot
from portfolio_copilot.portfolio.ledger import DecisionRecord


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
def _isolated_home(tmp_path, monkeypatch):
    """Every test in this file gets its own throwaway PORTFOLIO_COPILOT_HOME and a stub
    thesis store, mirroring test_server_capital_auction.py's isolation."""
    monkeypatch.setenv("PORTFOLIO_COPILOT_HOME", str(tmp_path))
    monkeypatch.setattr(server.thesis_module, "load_theses", lambda *a, **k: {})


def _config_stub(monkeypatch, targets: dict, instruments: dict) -> None:
    monkeypatch.setattr(server, "_load_portfolio_config", lambda *a, **k: {"targets": targets})
    monkeypatch.setattr(
        server, "_load_model_portfolios", lambda *a, **k: {"instruments": instruments}
    )


# ---------------------------------------------------------------------------
# save_portfolio_snapshot
# ---------------------------------------------------------------------------


def test_save_portfolio_snapshot_maps_buckets_and_defaults_as_of(monkeypatch):
    portfolio = Portfolio(
        holdings=[
            Holding(name="World ETF", isin="IE0002", asset_type="etf", market_value=1000.0),
            Holding(
                symbol="ACME", name="Acme Corp", asset_type="equity", market_value=200.0
            ),
        ]
    )
    monkeypatch.setattr(server, "_parse_export", lambda path, base_currency="EUR": portfolio)
    _config_stub(
        monkeypatch,
        targets={"global_equity": 1.0},
        instruments={"global_equity": {"isin": "IE0002", "yf_ticker": "VWCE.MI"}},
    )

    result = server.save_portfolio_snapshot(path="dummy.csv")

    assert result["as_of"] == date.today().isoformat()
    assert result["total_value"] == pytest.approx(1200.0)
    by_name = {h["name"]: h for h in result["holdings"]}
    assert by_name["World ETF"]["bucket"] == "global_equity"
    assert by_name["Acme Corp"]["bucket"] is None
    assert any(u["name"] == "Acme Corp" for u in result["unmapped"])
    assert result["plan_targets"] == {"global_equity": 1.0}  # config fallback, no plan file


def test_save_portfolio_snapshot_prefers_investment_plan_targets_over_config(
    monkeypatch, tmp_path
):
    portfolio = Portfolio(holdings=[Holding(name="Cash", market_value=50.0)])
    monkeypatch.setattr(server, "_parse_export", lambda path, base_currency="EUR": portfolio)
    _config_stub(monkeypatch, targets={"global_equity": 1.0}, instruments={})
    (tmp_path / "investment_plan.json").write_text(
        json.dumps({"targets": {"growth": 0.8, "bonds": 0.2}}), encoding="utf-8"
    )

    result = server.save_portfolio_snapshot(path="dummy.csv", as_of="2026-01-15")

    assert result["plan_targets"] == {"growth": 0.8, "bonds": 0.2}


def test_save_portfolio_snapshot_refuses_overwrite_without_force(monkeypatch):
    portfolio = Portfolio(holdings=[Holding(name="Cash", market_value=50.0)])
    monkeypatch.setattr(server, "_parse_export", lambda path, base_currency="EUR": portfolio)
    _config_stub(monkeypatch, targets={"global_equity": 1.0}, instruments={})

    server.save_portfolio_snapshot(path="dummy.csv", as_of="2026-02-01")
    with pytest.raises(ToolError):
        server.save_portfolio_snapshot(path="dummy.csv", as_of="2026-02-01")

    updated = server.save_portfolio_snapshot(path="dummy.csv", as_of="2026-02-01", force=True)
    assert updated["as_of"] == "2026-02-01"


def test_save_portfolio_snapshot_raises_tool_error_on_bad_export_path(monkeypatch):
    def _raise(path, base_currency="EUR"):
        raise FileNotFoundError(path)

    monkeypatch.setattr(server, "_parse_export", _raise)
    with pytest.raises(ToolError):
        server.save_portfolio_snapshot(path="missing.csv")


# ---------------------------------------------------------------------------
# list_portfolio_snapshots / compare_snapshots
# ---------------------------------------------------------------------------


def test_list_and_compare_snapshots_round_trip(monkeypatch):
    portfolio_a = Portfolio(holdings=[Holding(name="Cash", market_value=100.0)])
    portfolio_b = Portfolio(holdings=[Holding(name="Cash", market_value=150.0)])
    _config_stub(monkeypatch, targets={"global_equity": 1.0}, instruments={})

    assert server.list_portfolio_snapshots() == {"dates": []}

    monkeypatch.setattr(server, "_parse_export", lambda path, base_currency="EUR": portfolio_a)
    server.save_portfolio_snapshot(path="a.csv", as_of="2026-01-01")
    monkeypatch.setattr(server, "_parse_export", lambda path, base_currency="EUR": portfolio_b)
    server.save_portfolio_snapshot(path="b.csv", as_of="2026-02-01")

    assert server.list_portfolio_snapshots() == {"dates": ["2026-01-01", "2026-02-01"]}

    diff_default = server.compare_snapshots(older="2026-01-01")  # newer defaults to latest
    assert diff_default["as_of_after"] == "2026-02-01"
    assert diff_default["total_change_eur"] == pytest.approx(50.0)

    diff_explicit = server.compare_snapshots(older="2026-01-01", newer="2026-02-01")
    assert diff_explicit == diff_default


def test_compare_snapshots_raises_tool_error_on_missing_dates(monkeypatch):
    _config_stub(monkeypatch, targets={"global_equity": 1.0}, instruments={})
    with pytest.raises(ToolError):
        server.compare_snapshots(older="2099-01-01")

    portfolio = Portfolio(holdings=[Holding(name="Cash", market_value=10.0)])
    monkeypatch.setattr(server, "_parse_export", lambda path, base_currency="EUR": portfolio)
    server.save_portfolio_snapshot(path="a.csv", as_of="2026-03-01")
    with pytest.raises(ToolError):
        server.compare_snapshots(older="2026-03-01", newer="2099-01-01")


def test_compare_snapshots_raises_tool_error_when_store_is_empty():
    with pytest.raises(ToolError):
        server.compare_snapshots(older="2026-01-01")


def test_compare_snapshots_raises_tool_error_when_latest_snapshot_is_corrupted(monkeypatch):
    """newer=None (the common 'compare with the most recently saved one' call) resolves via
    latest_snapshot(), which was never wrapped in the same try/except that already guards
    an explicit `newer` -- a corrupted/legacy .json file for the most recent date must
    still surface as a ToolError, not a raw ValueError."""
    _config_stub(monkeypatch, targets={"global_equity": 1.0}, instruments={})
    portfolio = Portfolio(holdings=[Holding(name="Cash", market_value=10.0)])
    monkeypatch.setattr(server, "_parse_export", lambda path, base_currency="EUR": portfolio)
    server.save_portfolio_snapshot(path="a.csv", as_of="2026-01-01")

    directory = server.snapshots_module.snapshots_dir()
    (directory / "2026-02-01.json").write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ToolError):
        server.compare_snapshots(older="2026-01-01")


# ---------------------------------------------------------------------------
# capital_auction's candidates_for_ledger
# ---------------------------------------------------------------------------


def test_capital_auction_candidates_for_ledger_prices_stock_bucket_and_cash(monkeypatch):
    portfolio = Portfolio(holdings=[])
    monkeypatch.setattr(server, "_parse_export", lambda path, base_currency="EUR": portfolio)
    _config_stub(
        monkeypatch,
        targets={"global_equity": 1.0},
        instruments={"global_equity": {"yf_ticker": "VWCE.MI"}},
    )
    monkeypatch.setattr(
        server,
        "_snapshot_with_official_data",
        lambda symbol, cross_check_sec: (_snapshot(symbol, price=250.0), None),
    )

    def fake_get_stock_snapshot(ticker):
        if ticker == "VWCE.MI":
            return _snapshot(ticker, price=110.5)
        raise AssertionError(f"unexpected ticker priced directly: {ticker}")

    monkeypatch.setattr(server.provider, "get_stock_snapshot", fake_get_stock_snapshot)

    result = server.capital_auction(path="dummy.csv", cash_eur=1000.0, candidate_tickers=["HOT"])
    by_symbol = {c["symbol"]: c for c in result["candidates_for_ledger"]}

    assert by_symbol["HOT"]["kind"] == "stock"
    assert by_symbol["HOT"]["price"] == pytest.approx(250.0)
    assert by_symbol["HOT"]["price_symbol"] is None

    assert by_symbol["global_equity"]["kind"] == "bucket"
    assert by_symbol["global_equity"]["price"] == pytest.approx(110.5)
    assert by_symbol["global_equity"]["price_symbol"] == "VWCE.MI"

    assert by_symbol["CASH"]["kind"] == "cash"
    assert by_symbol["CASH"]["price"] is None
    assert by_symbol["CASH"]["price_symbol"] is None


def test_capital_auction_candidates_for_ledger_never_invents_a_missing_bucket_price(
    monkeypatch,
):
    portfolio = Portfolio(holdings=[])
    monkeypatch.setattr(server, "_parse_export", lambda path, base_currency="EUR": portfolio)
    _config_stub(
        monkeypatch,
        targets={"global_equity": 1.0},
        instruments={"global_equity": {"yf_ticker": "VWCE.MI"}},
    )

    def _raise(ticker):
        raise ValueError("no data")

    monkeypatch.setattr(server.provider, "get_stock_snapshot", _raise)

    result = server.capital_auction(path="dummy.csv", cash_eur=1000.0, candidate_tickers=[])
    entry = next(c for c in result["candidates_for_ledger"] if c["symbol"] == "global_equity")
    assert entry["price"] is None
    assert entry["price_symbol"] == "VWCE.MI"


def test_capital_auction_candidates_for_ledger_bucket_with_no_instrument_has_no_price_symbol(
    monkeypatch,
):
    portfolio = Portfolio(holdings=[])
    monkeypatch.setattr(server, "_parse_export", lambda path, base_currency="EUR": portfolio)
    _config_stub(monkeypatch, targets={"mystery_bucket": 1.0}, instruments={})

    result = server.capital_auction(path="dummy.csv", cash_eur=1000.0, candidate_tickers=[])
    entry = next(c for c in result["candidates_for_ledger"] if c["symbol"] == "mystery_bucket")
    assert entry["price"] is None
    assert entry["price_symbol"] is None


# ---------------------------------------------------------------------------
# log_decision's 'candidates' pass-through
# ---------------------------------------------------------------------------


def test_log_decision_passes_candidates_through_to_the_ledger():
    rec = server.log_decision(
        symbol="MU",
        action="BUY",
        reason="won the auction",
        candidates=[
            {"symbol": "MU", "kind": "stock", "utility": 80.0, "price": 100.0},
            {
                "symbol": "global_equity",
                "kind": "bucket",
                "utility": 60.0,
                "price": 100.0,
                "price_symbol": "VWCE.MI",
            },
            {"symbol": "CASH", "kind": "cash", "utility": 55.0},
        ],
    )
    assert [c["symbol"] for c in rec["candidates"]] == ["MU", "global_equity", "CASH"]
    assert rec["candidates"][1]["price_symbol"] == "VWCE.MI"

    reloaded = server.load_decisions()[0]
    assert reloaded.candidates[2].kind == "cash"


def test_log_decision_candidates_defaults_to_empty_list():
    rec = server.log_decision(symbol="MU", action="HOLD", reason="no candidates supplied")
    assert rec["candidates"] == []


# ---------------------------------------------------------------------------
# review_decisions' 'opportunity' section
# ---------------------------------------------------------------------------


def _old_decision(**overrides) -> DecisionRecord:
    old_date = (date.today() - timedelta(days=100)).isoformat()
    data = dict(
        id="old:MU:BUY",
        date=old_date,
        symbol="MU",
        action="BUY",
        reason="test",
        price=100.0,
        candidates=[
            {"symbol": "MU", "kind": "stock", "utility": 80.0, "price": 100.0},
            {
                "symbol": "global_equity",
                "kind": "bucket",
                "utility": 60.0,
                "price": 100.0,
                "price_symbol": "VWCE.MI",
            },
            {"symbol": "CASH", "kind": "cash", "utility": 55.0},
        ],
    )
    data.update(overrides)
    return DecisionRecord(**data)


def test_review_decisions_opportunity_section_measures_regret_and_skips_cash_pricing(
    monkeypatch,
):
    decision = _old_decision()
    monkeypatch.setattr(server, "load_decisions", lambda: [decision])

    def fake_get_stock_snapshot(symbol):
        prices = {"MU": 150.0, "VWCE.MI": 105.0}
        if symbol not in prices:
            raise AssertionError(f"unexpected price lookup for {symbol!r} (cash needs none)")
        return _snapshot(symbol, price=prices[symbol])

    monkeypatch.setattr(server.provider, "get_stock_snapshot", fake_get_stock_snapshot)

    report = server.review_decisions(min_days=90)
    opp = report["opportunity"]

    assert opp["n_measured"] == 1
    row = opp["rows"][0]
    assert row["chosen"] == "MU"
    assert row["chosen_return"] == pytest.approx(0.5)
    assert row["best_available"] == pytest.approx(0.5)
    assert row["regret"] == pytest.approx(0.0)
    assert "CASH" not in report["price_errors"]


def test_review_decisions_opportunity_marks_candidate_unmeasurable_on_price_failure(
    monkeypatch,
):
    decision = _old_decision()
    monkeypatch.setattr(server, "load_decisions", lambda: [decision])

    def fake_get_stock_snapshot(symbol):
        if symbol == "MU":
            return _snapshot(symbol, price=150.0)
        raise ValueError("provider outage")

    monkeypatch.setattr(server.provider, "get_stock_snapshot", fake_get_stock_snapshot)

    report = server.review_decisions(min_days=90)
    assert "VWCE.MI" in report["price_errors"]
    row = report["opportunity"]["rows"][0]
    assert row["status"] == "measured"  # the chosen leg (MU) still priced fine
    unmeasurable_symbols = {c["symbol"] for c in row["unmeasurable_candidates"]}
    assert "global_equity" in unmeasurable_symbols
