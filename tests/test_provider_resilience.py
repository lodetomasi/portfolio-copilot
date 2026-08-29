"""Regression tests: yfinance failures must degrade gracefully, never crash a tool.

Covers CLAUDE.md rule 6 ("se il dato e' assente, degradare lo score e dichiararlo") for
paths that were previously letting a raw yfinance exception (or a silently empty
multi-ticker frame) escape out of an MCP tool.
"""

from __future__ import annotations

import httpx
import pandas as pd
import pytest
from yfinance.exceptions import YFRateLimitError

import portfolio_copilot.server as server
from portfolio_copilot.portfolio.ledger import DecisionRecord
from portfolio_copilot.providers import yfinance_provider as yfp
from portfolio_copilot.providers.yfinance_provider import YFinanceProvider


class _RaisingTicker:
    """Stands in for yf.Ticker(...): every access raises, like a rate-limited session."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    @property
    def info(self):
        raise YFRateLimitError()

    def history(self, **kwargs):
        raise YFRateLimitError()


def _raising_yahooquery_factory(symbol, timeout=8.0):
    """Stands in for yahooquery.Ticker(...): construction itself raises, like an outage."""
    raise YFRateLimitError()


def _fail_yahooquery_too(monkeypatch):
    """server.provider is a fallback chain (yfinance -> yahooquery): a test that wants a
    snapshot lookup to fail end-to-end offline must also break the yahooquery leg, or
    FallbackMarketData will fall through to a real (unmocked) network call."""
    monkeypatch.setattr(server._yahooquery_provider, "_ticker_factory", _raising_yahooquery_factory)


def test_analyze_stock_degrades_instead_of_crashing_on_yfinance_failure(monkeypatch):
    monkeypatch.setattr(yfp.yf, "Ticker", _RaisingTicker)
    _fail_yahooquery_too(monkeypatch)
    result = server.analyze_stock("AAPL", cross_check_sec=False)
    assert result["score"] is None
    assert result["confidence"] == 0.0
    assert result.get("error")


def test_review_decisions_degrades_price_on_yfinance_rate_limit(monkeypatch):
    monkeypatch.setattr(yfp.yf, "Ticker", _RaisingTicker)
    _fail_yahooquery_too(monkeypatch)
    decision = DecisionRecord(
        id="2026-01-01:AAPL:BUY",
        date="2026-01-01",
        symbol="AAPL",
        action="BUY",
        reason="test",
    )
    monkeypatch.setattr(server, "load_decisions", lambda: [decision])
    report = server.review_decisions(min_days=0)
    assert "AAPL" in report["price_errors"]
    assert "RateLimit" in report["price_errors"]["AAPL"]


class _MisalignedTicker:
    """Two 'good' tickers whose monthly bars never land on the same calendar day, plus a
    'BAD' ticker whose fetch raises outright."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol

    def history(self, **kwargs):
        if self.symbol == "US":
            idx = pd.to_datetime(["2024-01-02", "2024-02-01", "2024-03-01"])
        elif self.symbol == "EU":
            idx = pd.to_datetime(["2024-01-03", "2024-02-02", "2024-03-04"])
        elif self.symbol == "BAD":
            raise YFRateLimitError()
        else:
            raise AssertionError(f"unexpected ticker {self.symbol}")
        return pd.DataFrame({"Close": [100.0, 101.0, 102.0]}, index=idx)


def test_get_monthly_closes_aligns_tickers_with_different_trading_days(monkeypatch):
    monkeypatch.setattr(yfp.yf, "Ticker", _MisalignedTicker)
    df = YFinanceProvider().get_monthly_closes({"core_us": "US", "core_eu": "EU"})
    assert len(df) == 3
    assert df.attrs["missing"] == []


def test_get_monthly_closes_isolates_a_ticker_whose_fetch_raises(monkeypatch):
    monkeypatch.setattr(yfp.yf, "Ticker", _MisalignedTicker)
    df = YFinanceProvider().get_monthly_closes({"core": "US", "other": "BAD"})
    assert list(df.columns) == ["core"]
    assert df.attrs["missing"] == ["other"]
    assert len(df) == 3


class _CountingTicker:
    """Stands in for yf.Ticker(...) and counts how many times each symbol was fetched, so
    tests can assert on cache hits without touching the network."""

    calls: dict[str, int] = {}

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        _CountingTicker.calls[symbol] = _CountingTicker.calls.get(symbol, 0) + 1

    @property
    def info(self):
        return {"currentPrice": 100.0, "currency": "USD"}

    def history(self, **kwargs):
        idx = pd.to_datetime(["2024-01-02", "2024-02-01", "2024-03-01"])
        return pd.DataFrame({"Close": [100.0, 101.0, 102.0]}, index=idx)


def test_get_stock_snapshot_uses_ttl_cache(monkeypatch):
    """Repeated snapshot requests for the same ticker within the TTL must not re-hit
    yfinance, like every other provider (CLAUDE.md: 'cache TTL per dati di mercato')."""
    monkeypatch.setattr(yfp.yf, "Ticker", _CountingTicker)
    _CountingTicker.calls.clear()
    provider = YFinanceProvider()
    first = provider.get_stock_snapshot("AAPL")
    second = provider.get_stock_snapshot("AAPL")
    assert _CountingTicker.calls.get("AAPL") == 1
    assert second.price == first.price


def test_get_monthly_closes_uses_ttl_cache(monkeypatch):
    monkeypatch.setattr(yfp.yf, "Ticker", _CountingTicker)
    _CountingTicker.calls.clear()
    provider = YFinanceProvider()
    provider.get_monthly_closes({"core": "AAPL"})
    provider.get_monthly_closes({"core": "AAPL"})
    assert _CountingTicker.calls.get("AAPL") == 1


def _raise_connect_error(*args, **kwargs):
    raise httpx.ConnectError("boom")


def test_fx_rates_degrades_instead_of_crashing_on_ecb_network_failure(monkeypatch):
    """ECB is a free, unauthenticated HTTP endpoint with no SLA. A network failure must
    degrade like every other provider (CLAUDE.md rule 6), not crash the MCP tool."""
    monkeypatch.setattr(httpx, "get", _raise_connect_error)
    result = server.fx_rates()
    assert result["ok"] is False
    assert result["source"] == "ecb_eurofxref"
    assert "boom" in result["error"]


def test_convert_amount_to_eur_degrades_instead_of_crashing_on_ecb_network_failure(monkeypatch):
    monkeypatch.setattr(httpx, "get", _raise_connect_error)
    result = server.convert_amount_to_eur(100.0, "USD")
    assert result["ok"] is False
    assert result["eur"] is None
    assert result["amount"] == 100.0
    assert result["currency"] == "USD"
    assert result["source"] == "ecb_eurofxref"
    assert "boom" in result["error"]


def test_fx_rates_degrades_on_ecb_http_status_error(monkeypatch):
    def fake_get(url, timeout, follow_redirects):
        return httpx.Response(503, request=httpx.Request("GET", url), text="unavailable")

    monkeypatch.setattr(httpx, "get", fake_get)
    result = server.fx_rates()
    assert result["ok"] is False
    assert "503" in result["error"]


def test_fx_rates_still_returns_rates_when_ecb_is_reachable(monkeypatch):
    """Guard against a degrade-everything fix: a healthy ECB response must still pass
    through untouched, with no `ok` key forced onto the happy path."""

    def fake_get(url, timeout, follow_redirects):
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            text=(
                '<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" '
                'xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">'
                '<Cube><Cube time="2026-08-27"><Cube currency="USD" rate="1.165"/>'
                "</Cube></Cube></gesmes:Envelope>"
            ),
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    result = server.fx_rates()
    assert result["rates"]["USD"] == pytest.approx(1.165)
    assert result["as_of"] == "2026-08-27"
