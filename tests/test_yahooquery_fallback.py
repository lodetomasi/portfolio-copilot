"""Offline tests for the yahooquery-backed provider and the multi-provider fallback chain.

The yahooquery ``Ticker`` class is never imported for real network access here: every test
injects a fake factory (a plain callable returning an object with ``.price``,
``.summary_detail``, ``.financial_data`` and ``.key_stats`` attributes) via the
``ticker_factory`` constructor argument, exactly the seam ``YahooQueryProvider`` exposes for
this purpose.
"""

from __future__ import annotations

import math

import pandas as pd
import pytest

from portfolio_copilot.models import Provenance, StockSnapshot
from portfolio_copilot.providers.fallback import FallbackMarketData
from portfolio_copilot.providers.yahooquery_provider import YahooQueryProvider


class _FakeTicker:
    """Stand-in for yahooquery's ``Ticker``: canned per-module payloads for one symbol."""

    def __init__(self, symbol, timeout=8.0, *, modules):
        self.symbol = symbol
        self.timeout = timeout
        self._modules = modules

    def _get(self, name):
        payload = self._modules.get(name)
        if payload is None:
            return {self.symbol: f"Quote not found for symbol: {self.symbol}"}
        return {self.symbol: payload}

    @property
    def price(self):
        return self._get("price")

    @property
    def summary_detail(self):
        return self._get("summary_detail")

    @property
    def financial_data(self):
        return self._get("financial_data")

    @property
    def key_stats(self):
        return self._get("key_stats")


def make_factory(**modules):
    """Build a ticker_factory that always returns the same canned modules, and records
    every call (symbol, timeout) it received."""
    calls: list[tuple[str, float]] = []

    def factory(symbol, timeout=8.0):
        calls.append((symbol, timeout))
        return _FakeTicker(symbol, timeout, modules=modules)

    factory.calls = calls
    return factory


def raising_factory(exc: Exception):
    def factory(symbol, timeout=8.0):
        raise exc

    return factory


FULL_MODULES = {
    "price": {"currency": "USD", "marketCap": 4_665_759_498_240, "regularMarketPrice": 319.7},
    "summary_detail": {
        "trailingPE": 36.7,
        "forwardPE": 33.5,
        "priceToSalesTrailing12Months": 9.99,
        "fiftyDayAverage": 300.0,
        "twoHundredDayAverage": 280.0,
        "fiftyTwoWeekHigh": 344.57,
    },
    "financial_data": {
        "currentPrice": 319.7,
        "revenueGrowth": 0.164,
        "earningsGrowth": 0.287,
        "grossMargins": 0.4865,
        "operatingMargins": 0.3262,
        "freeCashflow": 107_721_875_456,
        "debtToEquity": 78.445,
        "currentRatio": 1.003,
        "returnOnEquity": 1.4875,
    },
    "key_stats": {"enterpriseToEbitda": 27.4},
}


# ---------------------------------------------------------------------------
# YahooQueryProvider
# ---------------------------------------------------------------------------


def test_yahooquery_provider_maps_fields_from_modules():
    factory = make_factory(**FULL_MODULES)
    provider = YahooQueryProvider(ticker_factory=factory)

    snap = provider.get_stock_snapshot("aapl")

    assert isinstance(snap, StockSnapshot)
    assert snap.ticker == "AAPL"
    assert snap.currency == "USD"
    assert snap.price == pytest.approx(319.7)
    assert snap.market_cap == pytest.approx(4_665_759_498_240)
    assert snap.revenue_growth == pytest.approx(0.164)
    assert snap.earnings_growth == pytest.approx(0.287)
    assert snap.gross_margin == pytest.approx(0.4865)
    assert snap.operating_margin == pytest.approx(0.3262)
    assert snap.free_cashflow == pytest.approx(107_721_875_456)
    assert snap.debt_to_equity == pytest.approx(78.445)
    assert snap.current_ratio == pytest.approx(1.003)
    assert snap.roe == pytest.approx(1.4875)
    assert snap.trailing_pe == pytest.approx(36.7)
    assert snap.forward_pe == pytest.approx(33.5)
    assert snap.price_to_sales == pytest.approx(9.99)
    assert snap.enterprise_to_ebitda == pytest.approx(27.4)

    # derived cheaply from summary_detail without a second network call
    assert snap.above_sma50 is True
    assert snap.above_sma200 is True
    assert snap.distance_52w_high == pytest.approx(319.7 / 344.57 - 1.0)

    # no history call was made, these stay unset
    assert snap.ret_1m is None
    assert snap.vol_1y is None

    assert snap.provenance.source == "yahooquery"
    assert snap.provenance.tier == "B"
    assert snap.provenance.confidence == pytest.approx(0.7)
    assert snap.provenance.missing_fields == []
    assert factory.calls == [("AAPL", 8.0)]


def test_yahooquery_provider_nan_values_become_none_not_missing():
    """A field present in the payload but NaN must map to None via the numeric coercion,
    the same behaviour as yfinance_provider's ``_f`` helper -- and, since the raw value was
    not literally absent, it must not be double-counted in missing_fields."""
    modules = {
        "price": {"currency": "USD", "regularMarketPrice": 100.0},
        "summary_detail": {},
        "financial_data": {"currentPrice": 100.0, "earningsGrowth": math.nan},
        "key_stats": {},
    }
    provider = YahooQueryProvider(ticker_factory=make_factory(**modules))

    snap = provider.get_stock_snapshot("NANCO")

    assert snap.price == 100.0
    assert snap.earnings_growth is None
    assert "earningsGrowth" not in snap.provenance.missing_fields


def test_yahooquery_provider_missing_price_lowers_confidence_and_reports_missing():
    provider = YahooQueryProvider(ticker_factory=make_factory())  # no modules -> all "not found"

    snap = provider.get_stock_snapshot("NOPE")

    assert snap.price is None
    assert snap.provenance.confidence == pytest.approx(0.3)
    assert "price" in snap.provenance.missing_fields
    assert "revenueGrowth" in snap.provenance.missing_fields


def test_yahooquery_provider_requires_ticker():
    provider = YahooQueryProvider(ticker_factory=make_factory(**FULL_MODULES))
    with pytest.raises(ValueError):
        provider.get_stock_snapshot("   ")


def test_yahooquery_provider_wraps_library_exceptions_as_value_error():
    provider = YahooQueryProvider(ticker_factory=raising_factory(TimeoutError("timed out")))
    with pytest.raises(ValueError) as excinfo:
        provider.get_stock_snapshot("AAPL")
    assert "AAPL" in str(excinfo.value)
    assert "timed out" in str(excinfo.value)


def test_yahooquery_provider_caches_repeat_lookups():
    factory = make_factory(**FULL_MODULES)
    provider = YahooQueryProvider(ticker_factory=factory)

    provider.get_stock_snapshot("AAPL")
    provider.get_stock_snapshot("aapl")

    assert factory.calls == [("AAPL", 8.0)]


# ---------------------------------------------------------------------------
# FallbackMarketData
# ---------------------------------------------------------------------------


def _snapshot(price, source="yfinance"):
    return StockSnapshot(
        ticker="XYZ",
        price=price,
        provenance=Provenance(source=source, as_of="2026-08-28T00:00:00Z", confidence=0.75),
    )


class _StubProvider:
    source_name = "yfinance"

    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    def get_stock_snapshot(self, ticker):
        if self._error is not None:
            raise self._error
        return self._result


def test_fallback_picks_second_provider_when_first_has_no_price():
    no_price = _StubProvider(result=_snapshot(price=None))
    good = YahooQueryProvider(ticker_factory=make_factory(**FULL_MODULES))

    fallback = FallbackMarketData([no_price, good])
    snap = fallback.get_stock_snapshot("AAPL")

    assert snap.price == pytest.approx(319.7)
    assert snap.provenance.source == "yahooquery"
    assert snap.provenance.secondary_sources == ["yfinance: no price"]


def test_fallback_all_providers_failing_raises_with_every_attempt_listed():
    broken = _StubProvider(error=RuntimeError("boom"))
    timing_out = YahooQueryProvider(
        ticker_factory=raising_factory(TimeoutError("upstream slow"))
    )

    fallback = FallbackMarketData([broken, timing_out])

    with pytest.raises(ValueError) as excinfo:
        fallback.get_stock_snapshot("AAPL")

    message = str(excinfo.value)
    assert "AAPL" in message
    assert "yfinance: RuntimeError: boom" in message
    assert "yahooquery: ValueError" in message
    assert "upstream slow" in message


def test_fallback_secondary_sources_accumulate_across_multiple_failed_attempts():
    no_price = _StubProvider(result=_snapshot(price=None))
    errors_out = _StubProvider(error=ValueError("bad ticker"))
    good = YahooQueryProvider(ticker_factory=make_factory(**FULL_MODULES))

    fallback = FallbackMarketData([no_price, errors_out, good])
    snap = fallback.get_stock_snapshot("AAPL")

    assert snap.provenance.secondary_sources == [
        "yfinance: no price",
        "yfinance: ValueError: bad ticker",
    ]


def test_fallback_min_price_required_false_accepts_first_result_even_without_price():
    no_price = _StubProvider(result=_snapshot(price=None))
    good = YahooQueryProvider(ticker_factory=make_factory(**FULL_MODULES))

    fallback = FallbackMarketData([no_price, good], min_price_required=False)
    snap = fallback.get_stock_snapshot("AAPL")

    assert snap.price is None
    assert snap.provenance.source == "yfinance"


def test_fallback_get_monthly_closes_uses_first_provider_with_non_empty_data():
    class _NoAttr:
        pass

    class _EmptyFrame:
        def get_monthly_closes(self, tickers, period="5y"):
            return pd.DataFrame()

    class _RaisesFrame:
        def get_monthly_closes(self, tickers, period="5y"):
            raise RuntimeError("rate limited")

    class _GoodFrame:
        def get_monthly_closes(self, tickers, period="5y"):
            df = pd.DataFrame({"core": [1.0, 2.0]})
            df.attrs["source"] = "good"
            return df

    fallback = FallbackMarketData([_NoAttr(), _EmptyFrame(), _RaisesFrame(), _GoodFrame()])
    df = fallback.get_monthly_closes({"core": "VWCE.DE"})

    assert list(df["core"]) == [1.0, 2.0]
    assert df.attrs["source"] == "good"


def test_fallback_get_monthly_closes_all_empty_returns_empty_frame_with_missing():
    class _EmptyFrame:
        def get_monthly_closes(self, tickers, period="5y"):
            return pd.DataFrame()

    fallback = FallbackMarketData([_EmptyFrame()])
    df = fallback.get_monthly_closes({"core": "VWCE.DE"})

    assert df.empty
    assert df.attrs["missing"] == ["core"]
