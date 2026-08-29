"""Server-level tests for the integration wave that wires the picker work packages
together: revisions/catalysts enrichment in analyze_stock/screen_stocks,
discover_stocks(mode=...), rank_candidates, backtest_picker and resolve_isins. All
offline -- every network-touching provider call is monkeypatched at the module level
server.py itself uses (server.<module>.<function>), never a real yfinance/SEC/OpenFIGI
request, per CLAUDE.md rule 9.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import httpx
import pandas as pd
import pytest
from mcp.server.mcpserver.exceptions import ToolError

import portfolio_copilot.server as server
from portfolio_copilot.models import Provenance, StockSnapshot
from portfolio_copilot.portfolio.mapping import map_holdings
from portfolio_copilot.providers.yfinance_estimates import AnalystEstimates
from portfolio_copilot.providers.yfinance_surprises import SurpriseHistory, SurpriseQuarter


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
        provenance=Provenance(source="yfinance", as_of=datetime.now(UTC), confidence=0.9, tier="B"),
    )
    data.update(overrides)
    return StockSnapshot(**data)


def _estimates(ticker: str) -> AnalystEstimates:
    return AnalystEstimates(
        ticker=ticker,
        est_eps_growth_1y=0.20,
        est_revenue_growth_1y=0.10,
        eps_revisions_up_30d=3,
        eps_revisions_down_30d=1,
        revision_balance=0.5,
        analyst_count=8,
        consensus_score=1.2,
        target_upside=0.15,
        next_earnings_date="2026-11-01",
        days_to_next_earnings=30,
        revision_net_90d=2,
        revision_pt_change_90d=0.05,
        revision_events_90d=4,
        provenance={
            "source": "yfinance",
            "tier": "B",
            "as_of": "2026-08-29",
            "confidence": 0.8,
            "missing_fields": [],
            "notes": [],
        },
    )


def _surprise_history(ticker: str) -> SurpriseHistory:
    return SurpriseHistory(
        ticker=ticker,
        quarters=[
            SurpriseQuarter(earnings_date=date(2026, 1, 1), reported_eps=1.0, surprise_pct=0.05)
        ],
        surprise_mean_8q=0.04,
        surprise_positive_share_8q=0.75,
        surprise_streak=3,
        quarters_available=6,
        provenance=Provenance(
            source="yfinance_earnings_dates", as_of=datetime.now(UTC), confidence=0.4, tier="B"
        ),
    )


# ---------------------------------------------------------------------------
# _enrich_snapshot_with_free_data -- success and total-fallback paths
# ---------------------------------------------------------------------------


def test_enrich_snapshot_fills_revisions_and_catalysts_fields_on_success(monkeypatch):
    monkeypatch.setattr(
        server.estimates_module, "fetch_estimates", lambda *a, **k: _estimates("ACME")
    )
    monkeypatch.setattr(
        server.surprises_module, "fetch_surprise_history", lambda *a, **k: _surprise_history("ACME")
    )
    monkeypatch.setattr(server.sec_provider, "cik_for_ticker", lambda ticker: 320193)
    monkeypatch.setattr(
        server.sec_filings_module,
        "insider_activity",
        lambda ticker, days=90, provider=None: {"ok": True, "filing_count": 5},
    )
    monkeypatch.setattr(
        server.sec_filings_module,
        "list_filings",
        lambda ticker, forms=(), limit=20, provider=None: [
            {"filing_date": date.today().isoformat()},
            {"filing_date": "2020-01-01"},  # outside the 90d window
        ],
    )

    snapshot, estimates_dict = server._enrich_snapshot_with_free_data(_snapshot("ACME"))

    assert snapshot.est_eps_growth_1y == 0.20
    assert snapshot.consensus_score == 1.2
    assert snapshot.revision_net_90d == 2
    assert snapshot.surprise_mean_8q == 0.04
    assert snapshot.surprise_streak == 3
    assert snapshot.insider_form4_90d == 5
    assert snapshot.filings_8k_90d == 1  # only the recent row is within 90 days
    assert estimates_dict["ticker"] == "ACME"
    assert any("yfinance_estimates" in n for n in snapshot.provenance.secondary_sources)


def test_enrich_snapshot_degrades_to_none_and_notes_when_everything_fails(monkeypatch):
    def _raise(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(server.estimates_module, "fetch_estimates", _raise)
    monkeypatch.setattr(server.surprises_module, "fetch_surprise_history", _raise)
    monkeypatch.setattr(server.sec_provider, "cik_for_ticker", _raise)

    base = _snapshot("NOPE")
    snapshot, estimates_dict = server._enrich_snapshot_with_free_data(base)

    assert estimates_dict is None
    assert snapshot.est_eps_growth_1y is None
    assert snapshot.surprise_mean_8q is None
    assert snapshot.insider_form4_90d is None
    assert snapshot.filings_8k_90d is None
    # estimates + surprises unavailable, plus the CIK lookup failure and its follow-up
    # "no CIK on file" note (cik stays None on a raised lookup, same as a clean miss).
    assert len(snapshot.provenance.secondary_sources) == 4
    # score_snapshot must still work -- revisions/catalysts fall back to unavailable, never crash.
    score = server.score_snapshot(snapshot)
    assert score.score is not None


def test_enrich_snapshot_folds_estimates_confidence_into_provenance_confidence(monkeypatch):
    """finding 25: yfinance_estimates' own coverage-based confidence (0.8 here, below the
    snapshot's original 0.9) must actually cap provenance.confidence -- not just appear as
    text in secondary_sources -- so scoring.engine's confidence formula can see it."""
    monkeypatch.setattr(
        server.estimates_module, "fetch_estimates", lambda *a, **k: _estimates("ACME")
    )
    monkeypatch.setattr(
        server.surprises_module, "fetch_surprise_history", lambda *a, **k: _surprise_history("ACME")
    )
    monkeypatch.setattr(server.sec_provider, "cik_for_ticker", lambda ticker: None)

    base = _snapshot("ACME")
    assert base.provenance.confidence == 0.9
    snapshot, _ = server._enrich_snapshot_with_free_data(base)

    assert snapshot.provenance.confidence == pytest.approx(0.8)


def test_enrich_snapshot_does_not_raise_a_lower_original_confidence(monkeypatch):
    """The fold is a cap (min), never a boost: a snapshot already less confident than the
    estimates provider must keep its own, lower confidence."""

    def _low_confidence_estimates(*a, **k):
        est = _estimates("ACME")
        est.provenance["confidence"] = 0.95
        return est

    monkeypatch.setattr(server.estimates_module, "fetch_estimates", _low_confidence_estimates)
    monkeypatch.setattr(
        server.surprises_module, "fetch_surprise_history", lambda *a, **k: _surprise_history("ACME")
    )
    monkeypatch.setattr(server.sec_provider, "cik_for_ticker", lambda ticker: None)

    base = _snapshot("ACME", provenance=Provenance(
        source="yfinance", as_of=datetime.now(UTC), confidence=0.5, tier="B"
    ))
    snapshot, _ = server._enrich_snapshot_with_free_data(base)

    assert snapshot.provenance.confidence == pytest.approx(0.5)


def test_enrich_snapshot_no_cik_never_calls_insider_or_8k(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(
        server.estimates_module, "fetch_estimates", lambda *a, **k: _estimates("EU")
    )
    monkeypatch.setattr(
        server.surprises_module, "fetch_surprise_history", lambda *a, **k: _surprise_history("EU")
    )
    monkeypatch.setattr(server.sec_provider, "cik_for_ticker", lambda ticker: None)
    monkeypatch.setattr(
        server.sec_filings_module,
        "insider_activity",
        lambda *a, **k: calls.append("insider") or {"ok": True, "filing_count": 1},
    )
    monkeypatch.setattr(
        server.sec_filings_module, "list_filings", lambda *a, **k: calls.append("8k") or []
    )

    snapshot, _ = server._enrich_snapshot_with_free_data(_snapshot("EU.MI"))

    assert calls == []
    assert snapshot.insider_form4_90d is None
    assert snapshot.filings_8k_90d is None
    assert any("no CIK on file" in n for n in snapshot.provenance.secondary_sources)


def test_analyze_stock_exposes_estimates_key(monkeypatch):
    monkeypatch.setattr(server.provider, "get_stock_snapshot", lambda ticker: _snapshot("ACME"))
    monkeypatch.setattr(
        server.sec_provider, "get_company_facts", lambda ticker: {"ok": False, "error": "no CIK"}
    )
    monkeypatch.setattr(server.sec_provider, "cik_for_ticker", lambda ticker: None)
    monkeypatch.setattr(
        server.estimates_module, "fetch_estimates", lambda *a, **k: _estimates("ACME")
    )
    monkeypatch.setattr(
        server.surprises_module, "fetch_surprise_history", lambda *a, **k: _surprise_history("ACME")
    )

    result = server.analyze_stock("ACME", cross_check_sec=True)

    assert result["estimates"]["ticker"] == "ACME"
    # revisions must now be an available component, not the permanent-unavailable placeholder.
    revisions = next(c for c in result["components"] if c["name"] == "revisions")
    assert revisions["available"] is True


def test_screen_stocks_reports_error_without_crashing_and_does_not_need_estimates_mock(monkeypatch):
    """A ticker whose base snapshot lookup fails must still degrade like before -- the new
    enrichment call is never reached for it."""

    def _raise(ticker):
        raise ValueError(f"unknown ticker {ticker}")

    monkeypatch.setattr(server.provider, "get_stock_snapshot", _raise)
    results = server.screen_stocks(["NOPE"])
    assert results[0]["ticker"] == "NOPE"
    assert results[0]["score"] is None


# ---------------------------------------------------------------------------
# discover_stocks(mode=...)
# ---------------------------------------------------------------------------


def test_discover_stocks_default_mode_is_universe_and_forwards_styles_sizes(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        server.finviz_provider,
        "discover_universe",
        lambda **kwargs: captured.update(kwargs) or {"ok": True, "candidates": []},
    )
    result = server.discover_stocks(styles=["momentum"], sizes=["mega"], per_screen=5)
    assert result == {"ok": True, "candidates": []}
    assert captured == {"per_screen": 5, "styles": ("momentum",), "sizes": ("mega",)}


def test_discover_stocks_preset_mode_matches_old_behaviour(monkeypatch):
    monkeypatch.setattr(
        server.finviz_provider,
        "screen",
        lambda preset, limit: {"ok": True, "preset": preset, "limit": limit},
    )
    result = server.discover_stocks(preset="momentum", limit=40, mode="preset")
    assert result == {"ok": True, "preset": "momentum", "limit": 40}


def test_discover_stocks_unknown_preset_still_raises_tool_error_regardless_of_mode():
    with pytest.raises(ToolError, match="Unknown preset"):
        server.discover_stocks(preset="not_a_real_preset")


def test_discover_stocks_unknown_mode_raises_tool_error():
    with pytest.raises(ToolError, match="Unknown mode"):
        server.discover_stocks(mode="not_a_real_mode")


# ---------------------------------------------------------------------------
# rank_candidates
# ---------------------------------------------------------------------------


def test_rank_candidates_ranks_every_ticker_without_excluding_anything(monkeypatch):
    def _fake_screen(tickers, min_score=0.0):
        return [
            {
                "ticker": "MEGA",
                "score": 90.0,
                "confidence": 0.8,
                "category": "Quality / Compounder",
                "components": [{"name": "growth", "score": 80, "weight": 20, "available": True}],
                "snapshot": {"market_cap": 900e9, "sector": "Technology", "industry": "Software"},
            },
            {
                "ticker": "MICRO",
                "score": 70.0,
                "confidence": 0.5,
                "category": "Asymmetric / High Risk",
                "components": [{"name": "growth", "score": 60, "weight": 20, "available": True}],
                "snapshot": {"market_cap": 100e6, "sector": "Biotech", "industry": "Biotech"},
            },
            {"ticker": "BROKEN", "error": "boom", "score": None, "confidence": 0.0},
        ]

    monkeypatch.setattr(server, "screen_stocks", _fake_screen)
    caps = {"risk_limits": {"max_single_stock_weight": 0.05}}
    monkeypatch.setattr(server, "_load_portfolio_config", lambda *a, **k: caps)

    result = server.rank_candidates(["MEGA", "MICRO", "BROKEN"], top_n=10)

    tickers = [item["ticker"] for item in result["ranked"]]
    assert tickers == ["MEGA", "MICRO", "BROKEN"]  # nothing excluded, ranked by score desc
    assert result["ranked"][0]["size_bucket"] == "mega"
    assert result["screening_errors"] == {"BROKEN": "boom"}
    assert "note" in result["summary"]


def test_rank_candidates_min_confidence_surfaces_low_confidence_tag(monkeypatch):
    def _fake_screen(tickers, min_score=0.0):
        return [
            {
                "ticker": "THIN",
                "score": 95.0,
                "confidence": 0.35,
                "category": "Quality / Compounder",
                "components": [{"name": "growth", "score": 90, "weight": 20, "available": True}],
                "snapshot": {"market_cap": 5e9},
            },
        ]

    monkeypatch.setattr(server, "screen_stocks", _fake_screen)
    monkeypatch.setattr(
        server, "_load_portfolio_config", lambda *a, **k: {"risk_limits": {}}
    )

    result = server.rank_candidates(["THIN"], top_n=10, min_confidence=0.5)

    assert "low_confidence" in result["ranked"][0]["tags"]


def test_rank_candidates_with_path_annotates_diversification(monkeypatch, tmp_path):
    from portfolio_copilot.models import Holding, Portfolio

    portfolio = Portfolio(
        holdings=[Holding(name="Core ETF", asset_type="etf", market_value=100_000.0)]
    )
    monkeypatch.setattr(server, "_parse_export", lambda path, base_currency="EUR": portfolio)
    monkeypatch.setattr(
        server,
        "screen_stocks",
        lambda tickers, min_score=0.0: [
            {
                "ticker": "X",
                "score": 50.0,
                "confidence": 0.6,
                "category": "Quality / Compounder",
                "components": [],
                "snapshot": {"market_cap": 5e9, "sector": "Industrials"},
            }
        ],
    )
    monkeypatch.setattr(server, "_load_portfolio_config", lambda *a, **k: {"risk_limits": {}})

    result = server.rank_candidates(["X"], path="dummy.csv")
    assert result["ranked"][0]["diversification"] is not None


# ---------------------------------------------------------------------------
# backtest_picker
# ---------------------------------------------------------------------------


def _month_end_series(months: int, start_value: float, monthly_growth: float) -> pd.Series:
    end = pd.Timestamp(date.today()).to_period("M").to_timestamp("M")
    index = pd.date_range(end=end, periods=months, freq="ME")
    values = [start_value * (1 + monthly_growth) ** i for i in range(months)]
    return pd.Series(values, index=index)


@pytest.fixture
def _isolated_backtest_picker(monkeypatch):
    """Every network-touching call backtest_picker can make, monkeypatched offline."""
    monkeypatch.setattr(
        server.surprises_module, "fetch_surprise_history", lambda *a, **k: _surprise_history("X")
    )
    monkeypatch.setattr(server.estimates_module, "fetch_rating_events", lambda *a, **k: [])
    monkeypatch.setattr(server, "_fetch_asfiled_fundamentals", lambda symbol: [])


def test_backtest_picker_happy_path_skips_ticker_with_no_price_history(
    monkeypatch, _isolated_backtest_picker
):
    prices = {
        "VWCE.MI": _month_end_series(48, 100.0, 0.01),
        "AAA": _month_end_series(48, 50.0, 0.02),
    }

    def _fake_get_monthly_closes(tickers, period="max"):
        (key, ticker), = tickers.items()
        series = prices.get(ticker)
        if series is None:
            return pd.DataFrame({key: pd.Series(dtype=float)})
        return pd.DataFrame({key: series})

    monkeypatch.setattr(server.provider, "get_monthly_closes", _fake_get_monthly_closes)

    result = server.backtest_picker(tickers=["AAA", "ZZZ"], years=2, horizon_months=3)

    assert result["ok"] is True
    assert result["tickers_used"] == ["AAA"]
    assert result["skipped"]["ZZZ"] == "no usable price history"
    assert result["disclosures"]  # mandatory disclosures always present
    assert isinstance(result["rows"], list) and len(result["rows"]) > 0


def test_backtest_picker_reports_missing_benchmark(monkeypatch, _isolated_backtest_picker):
    monkeypatch.setattr(
        server.provider,
        "get_monthly_closes",
        lambda tickers, period="max": pd.DataFrame({"benchmark": pd.Series(dtype=float)}),
    )
    result = server.backtest_picker(tickers=["AAA"], benchmark="NOPE")
    assert result["ok"] is False
    assert "benchmark" in result["error"].lower() or "NOPE" in result["error"]


# ---------------------------------------------------------------------------
# resolve_isins
# ---------------------------------------------------------------------------


def test_resolve_isins_attaches_yf_ticker_when_exch_code_given(monkeypatch):
    monkeypatch.setattr(
        server.openfigi_provider,
        "map_isins",
        lambda isins, exch_code=None: {
            "IT0000000001": {"ticker": "ENEL", "exch_code": "MI", "name": "Enel", "figi": "F1"},
            "IT0000000002": None,
        },
    )
    monkeypatch.setattr(server.openfigi_provider, "errors", {"IT0000000002": "no data returned"})

    result = server.resolve_isins(["IT0000000001", "IT0000000002"], exch_code="MI")

    assert result["results"]["IT0000000001"]["yf_ticker"] == "ENEL.MI"
    assert result["results"]["IT0000000002"] is None
    assert result["errors"] == {"IT0000000002": "no data returned"}


def test_resolve_isins_no_exch_code_never_invents_a_yf_ticker(monkeypatch):
    monkeypatch.setattr(
        server.openfigi_provider,
        "map_isins",
        lambda isins, exch_code=None: {"US0378331005": {"ticker": "AAPL"}},
    )
    result = server.resolve_isins(["US0378331005"])
    assert result["results"]["US0378331005"]["yf_ticker"] is None


def test_resolve_isins_does_not_leak_stale_errors_from_an_unrelated_prior_call(monkeypatch):
    """finding 26: openfigi_provider is a module-level singleton whose .errors dict is
    only pruned by a later SUCCESSFUL lookup of the SAME isin -- a failed isin's message
    must not leak into an unrelated later resolve_isins call's response."""
    import httpx as httpx_module

    def _response(status_code, body):
        return httpx_module.Response(
            status_code, request=httpx_module.Request("POST", "https://x"), json=body
        )

    def fake_post_miss(url, json, timeout, headers):
        return _response(200, [{"warning": "No identifier found."}])

    monkeypatch.setattr(httpx_module, "post", fake_post_miss)
    server.resolve_isins(["BAD0000000001"])
    assert "BAD0000000001" in server.openfigi_provider.errors

    def fake_post_hit(url, json, timeout, headers):
        return _response(
            200,
            [{"data": [{"ticker": "GOOD", "exchCode": "US", "name": "Good Co", "figi": "F1"}]}],
        )

    monkeypatch.setattr(httpx_module, "post", fake_post_hit)
    result = server.resolve_isins(["GOOD0000000001"])

    assert "BAD0000000001" not in result["errors"]
    assert result["results"]["GOOD0000000001"]["ticker"] == "GOOD"


def test_resolve_isins_raises_tool_error_on_http_failure(monkeypatch):
    def _raise(isins, exch_code=None):
        raise httpx.HTTPStatusError("429", request=None, response=None)

    monkeypatch.setattr(server.openfigi_provider, "map_isins", _raise)
    with pytest.raises(ToolError, match="OpenFIGI request failed"):
        server.resolve_isins(["US0378331005"])


# ---------------------------------------------------------------------------
# portfolio.mapping.map_holdings -- optional isin_resolver (never required)
# ---------------------------------------------------------------------------

_APPLE_ISIN = "US0378331005"


def _equity_holding(**overrides) -> dict:
    data = {
        "name": "Apple Inc",
        "isin": _APPLE_ISIN,
        "asset_type": "equity",
        "market_value": 2_000.0,
    }
    data.update(overrides)
    return data


def test_map_holdings_without_resolver_is_byte_for_byte_unchanged():
    out = map_holdings([_equity_holding()], {"global_equity": 1.0}, {})
    assert out["unmapped"] == [
        {
            "name": "Apple Inc",
            "asset_type": "equity",
            "market_value": 2_000.0,
            "why": "single_stock_equity",
        }
    ]


def test_map_holdings_resolver_adds_ticker_only_on_success():
    out = map_holdings(
        [_equity_holding()], {"global_equity": 1.0}, {}, isin_resolver=lambda isin: "AAPL"
    )
    assert out["unmapped"][0]["resolved_ticker"] == "AAPL"


def test_map_holdings_resolver_failure_degrades_silently():
    def _raise(isin):
        raise RuntimeError("rate limited")

    out = map_holdings([_equity_holding()], {"global_equity": 1.0}, {}, isin_resolver=_raise)
    assert "resolved_ticker" not in out["unmapped"][0]


def test_map_holdings_resolver_skipped_when_symbol_already_present():
    calls: list[str] = []

    def _resolver(isin: str) -> str:
        calls.append(isin)
        return "AAPL"

    out = map_holdings(
        [_equity_holding(symbol="AAPL")], {"global_equity": 1.0}, {}, isin_resolver=_resolver
    )
    assert calls == []
    assert "resolved_ticker" not in out["unmapped"][0]


# ---------------------------------------------------------------------------
# _annual_fundamental_rows / _fetch_asfiled_fundamentals
# ---------------------------------------------------------------------------


def _fy_row(end: str, filed: str, val: float) -> dict:
    return {"end": end, "filed": filed, "val": val, "form": "10-K", "fp": "FY"}


def _facts_with_tag_rows(**tag_rows: list[dict]) -> dict:
    """{tag: [row, ...]} -> a minimal SEC EDGAR companyfacts JSON shape."""
    gaap = {tag: {"units": {"USD": rows}} for tag, rows in tag_rows.items()}
    return {"facts": {"us-gaap": gaap}}


def test_annual_fundamental_rows_scans_every_tag_without_early_break():
    """A tag switch mid-history (old tag stops, new tag with the real concept takes over)
    must not hide the newer tag's rows behind the older tag's rows -- the exact bug
    documented by the picker-backtest work package for scripts/picker_backtest_report.py."""
    old_tag = "Revenues"
    new_tag = "RevenueFromContractWithCustomerExcludingAssessedTax"
    facts = _facts_with_tag_rows(
        **{
            old_tag: [_fy_row("2018-12-31", "2019-02-01", 100)],
            new_tag: [_fy_row("2023-12-31", "2024-02-01", 500)],
        }
    )
    rows = server._annual_fundamental_rows(facts, (old_tag, new_tag))
    ends = {r["end"] for r in rows}
    assert ends == {"2018-12-31", "2023-12-31"}


def test_annual_fundamental_rows_keeps_earliest_filed_per_end():
    facts = _facts_with_tag_rows(
        Revenues=[
            _fy_row("2020-12-31", "2021-02-01", 100),
            _fy_row("2020-12-31", "2022-02-01", 999),  # a later restated comparative
        ]
    )
    rows = server._annual_fundamental_rows(facts, ("Revenues",))
    assert rows == [{"end": "2020-12-31", "filed": "2021-02-01", "value": 100.0}]


def test_fetch_asfiled_fundamentals_degrades_to_empty_without_cik(monkeypatch):
    monkeypatch.setattr(server.sec_provider, "cik_for_ticker", lambda ticker: None)
    assert server._fetch_asfiled_fundamentals("ENEL.MI") == []


def test_fetch_asfiled_fundamentals_degrades_to_empty_on_fetch_error(monkeypatch):
    monkeypatch.setattr(server.sec_provider, "cik_for_ticker", lambda ticker: 320193)

    def _raise(url):
        raise RuntimeError("network down")

    monkeypatch.setattr(server.sec_provider, "_get_json", _raise)
    assert server._fetch_asfiled_fundamentals("AAPL") == []


def test_fetch_asfiled_fundamentals_merges_revenue_and_eps_by_end(monkeypatch):
    facts = _facts_with_tag_rows(
        Revenues=[_fy_row("2022-12-31", "2023-02-01", 1000)],
        EarningsPerShareDiluted=[_fy_row("2022-12-31", "2023-02-01", 5.0)],
    )
    monkeypatch.setattr(server.sec_provider, "cik_for_ticker", lambda ticker: 320193)
    monkeypatch.setattr(server.sec_provider, "_get_json", lambda url: facts)

    rows = server._fetch_asfiled_fundamentals("AAPL")
    assert rows == [{"end": "2022-12-31", "filed": "2023-02-01", "revenue": 1000.0, "eps": 5.0}]
