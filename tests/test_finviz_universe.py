"""Offline tests for the Finviz universe sampler: no exclusions, sizes x styles union.

USER PRINCIPLE under test: the sampler must not exclude by size or style -- it unions
every (style, size) screen and only records which styles hit a candidate, never drops it.
"""

import pandas as pd
import pytest
from finvizfinance.constants import filter_dict, order_dict

from portfolio_copilot.providers.finviz import (
    PRESETS,
    SIZE_BUCKETS,
    STYLE_ORDER,
    FinvizProvider,
    validate_preset,
)


def test_size_buckets_are_valid_finviz_market_cap_options():
    options = filter_dict["Market Cap."]["option"]
    for label in SIZE_BUCKETS.values():
        assert label in options
        validate_preset({"Market Cap.": label})  # raises on unknown option


def test_style_order_names_are_valid_finviz_order_names():
    for name in STYLE_ORDER.values():
        assert name in order_dict


def test_style_order_covers_every_preset():
    assert set(STYLE_ORDER) == set(PRESETS)


def _row(ticker, company="Co", sector="Tech", industry="Software", cap=1e9):
    return {
        "Ticker": ticker,
        "Company": company,
        "Sector": sector,
        "Industry": industry,
        "Market Cap": cap,
    }


class _RecordingScreener:
    """Fake finvizfinance Overview: records each call, returns rows keyed by (cap, order)."""

    def __init__(self, calls, rows_by_call, boom_calls):
        self._calls = calls
        self._rows_by_call = rows_by_call
        self._boom_calls = boom_calls
        self.filters: dict | None = None

    def set_filter(self, filters_dict):
        self.filters = dict(filters_dict)

    def screener_view(self, order, ascend, limit, verbose):
        call_key = (self.filters.get("Market Cap."), order)
        self._calls.append(
            {"filters": dict(self.filters), "order": order, "ascend": ascend, "limit": limit}
        )
        if call_key in self._boom_calls:
            raise ConnectionError("finviz unreachable")
        rows = self._rows_by_call.get(call_key, [])
        return pd.DataFrame(rows) if rows else pd.DataFrame()


def _factory(calls, rows_by_call, boom_calls=frozenset()):
    def make():
        return _RecordingScreener(calls, rows_by_call, boom_calls)

    return make


def test_discover_universe_runs_one_screen_per_style_size_pair_with_size_override():
    calls: list = []
    rows_by_call = {
        (SIZE_BUCKETS["mega"], STYLE_ORDER["quality_growth"]): [_row("AAA", cap=3e11)],
    }
    provider = FinvizProvider(screener_factory=_factory(calls, rows_by_call))

    out = provider.discover_universe(
        styles=("quality_growth", "quality_value", "momentum"),
        sizes=("mega", "large", "mid", "small"),
        per_screen=15,
    )

    assert len(calls) == 12
    assert out["screens_run"] == 12
    assert out["screens_failed"] == []
    assert out["ok"] is True
    assert out["source"] == "finviz" and out["tier"] == "C"
    assert "nothing excluded" in out["note"].lower()

    growth_calls = [c for c in calls if c["order"] == STYLE_ORDER["quality_growth"]]
    assert len(growth_calls) == 4
    # size override applied: each size bucket used exactly once for this style
    assert {c["filters"]["Market Cap."] for c in growth_calls} == set(SIZE_BUCKETS.values())
    growth_filters = PRESETS["quality_growth"]
    for c in growth_calls:
        # other preset filters preserved untouched
        assert c["filters"]["EPS growththis year"] == growth_filters["EPS growththis year"]
        assert c["ascend"] is False
        assert c["limit"] == 15


def test_discover_universe_unions_and_dedupes_merging_styles_hit():
    calls: list = []
    rows_by_call = {
        (SIZE_BUCKETS["mega"], STYLE_ORDER["quality_growth"]): [_row("AAA", cap=3e11)],
        (SIZE_BUCKETS["mega"], STYLE_ORDER["quality_value"]): [_row("AAA", cap=3e11)],
        (SIZE_BUCKETS["mega"], STYLE_ORDER["momentum"]): [_row("BBB", cap=2.5e11)],
    }
    provider = FinvizProvider(screener_factory=_factory(calls, rows_by_call))

    out = provider.discover_universe(sizes=("mega",), per_screen=10)

    by_ticker = {c["Ticker"]: c for c in out["candidates"]}
    assert set(by_ticker) == {"AAA", "BBB"}
    assert len(out["candidates"]) == 2  # deduped, not 3 raw rows
    assert sorted(by_ticker["AAA"]["styles_hit"]) == ["quality_growth", "quality_value"]
    assert by_ticker["AAA"]["size_bucket"] == "mega"
    assert by_ticker["BBB"]["styles_hit"] == ["momentum"]


def test_discover_universe_keeps_other_screens_when_one_fails():
    calls: list = []
    boom_key = (SIZE_BUCKETS["small"], STYLE_ORDER["momentum"])
    rows_by_call = {
        (SIZE_BUCKETS["mega"], STYLE_ORDER["quality_growth"]): [_row("AAA")],
        (SIZE_BUCKETS["large"], STYLE_ORDER["quality_value"]): [_row("BBB")],
    }
    provider = FinvizProvider(screener_factory=_factory(calls, rows_by_call, boom_calls={boom_key}))

    out = provider.discover_universe(
        styles=("quality_growth", "quality_value", "momentum"),
        sizes=("mega", "large", "small"),
        per_screen=10,
    )

    assert out["screens_run"] == 9
    assert len(out["screens_failed"]) == 1
    failed = out["screens_failed"][0]
    assert failed == {
        "style": "momentum",
        "size": "small",
        "error": "ConnectionError: finviz unreachable",
    }
    tickers = {c["Ticker"] for c in out["candidates"]}
    assert {"AAA", "BBB"} <= tickers  # results from the other 8 screens are kept
    assert out["ok"] is True  # partial failure, sampler still usable


def test_discover_universe_all_screens_failing_is_not_ok():
    boom_key = (SIZE_BUCKETS["mega"], STYLE_ORDER["quality_growth"])
    provider = FinvizProvider(screener_factory=_factory([], {}, boom_calls={boom_key}))

    out = provider.discover_universe(styles=("quality_growth",), sizes=("mega",), per_screen=5)

    assert out["ok"] is False
    assert out["candidates"] == []
    assert len(out["screens_failed"]) == 1


def test_discover_universe_empty_screen_is_not_a_failure():
    """A screen with zero matches is not an error -- Finviz found nothing there, nothing broke."""
    provider = FinvizProvider(screener_factory=_factory([], {}))

    out = provider.discover_universe(styles=("quality_growth",), sizes=("mega",), per_screen=5)

    assert out["screens_run"] == 1
    assert out["screens_failed"] == []
    assert out["candidates"] == []
    assert out["ok"] is True


def test_discover_universe_caches_by_styles_sizes_per_screen():
    calls: list = []
    rows_by_call = {(SIZE_BUCKETS["mega"], STYLE_ORDER["quality_growth"]): [_row("AAA")]}
    provider = FinvizProvider(screener_factory=_factory(calls, rows_by_call))

    first = provider.discover_universe(styles=("quality_growth",), sizes=("mega",), per_screen=5)
    second = provider.discover_universe(styles=("quality_growth",), sizes=("mega",), per_screen=5)
    assert second is first
    assert len(calls) == 1  # second call served from cache, no new screen call

    third = provider.discover_universe(styles=("quality_growth",), sizes=("mega",), per_screen=6)
    assert third is not first
    assert len(calls) == 2  # different per_screen -> cache miss


@pytest.mark.parametrize(
    "bad_styles,bad_sizes",
    [(("nope",), ("mega",)), (("quality_growth",), ("huge",))],
)
def test_discover_universe_rejects_unknown_style_or_size(bad_styles, bad_sizes):
    provider = FinvizProvider(screener_factory=_factory([], {}))
    with pytest.raises(ValueError):
        provider.discover_universe(styles=bad_styles, sizes=bad_sizes)


def test_discover_universe_rejects_non_positive_per_screen():
    provider = FinvizProvider(screener_factory=_factory([], {}))
    with pytest.raises(ValueError):
        provider.discover_universe(styles=("quality_growth",), sizes=("mega",), per_screen=0)


def test_discover_universe_drops_rows_with_nan_ticker():
    """A malformed scraped row with a NaN Ticker must be dropped, not kept as a distinct
    None-ticker candidate for every such row (finding 9)."""
    calls: list = []
    key = (SIZE_BUCKETS["mega"], STYLE_ORDER["quality_growth"])
    rows_by_call = {
        key: [
            {**_row("AAA"), "Ticker": float("nan")},
            {**_row("BBB"), "Ticker": float("nan")},
            _row("CCC"),
        ]
    }
    provider = FinvizProvider(screener_factory=_factory(calls, rows_by_call))

    out = provider.discover_universe(styles=("quality_growth",), sizes=("mega",), per_screen=15)

    tickers = [c["Ticker"] for c in out["candidates"]]
    assert tickers == ["CCC"]


def test_discover_universe_does_not_cache_a_fully_failed_sample():
    """A transient scrape failure across every screen must not be cached as "unavailable"
    for the whole TTL (finding 28) -- a later, potentially-successful call must retry."""
    boom_key = (SIZE_BUCKETS["mega"], STYLE_ORDER["quality_growth"])
    calls: list = []
    provider = FinvizProvider(screener_factory=_factory(calls, {}, boom_calls={boom_key}))

    first = provider.discover_universe(styles=("quality_growth",), sizes=("mega",), per_screen=5)
    assert first["ok"] is False

    provider._screener_factory = _factory(
        calls, {boom_key: [_row("AAA")]}
    )
    second = provider.discover_universe(styles=("quality_growth",), sizes=("mega",), per_screen=5)

    assert len(calls) == 2  # the failed sample was not cached; the retry actually ran
    assert second["ok"] is True
    assert second is not first


def test_discover_universe_screener_factory_override_bypasses_provider_default():
    calls_default: list = []
    calls_override: list = []
    default_factory = _factory(calls_default, {})
    override_rows = {(SIZE_BUCKETS["mega"], STYLE_ORDER["quality_growth"]): [_row("ZZZ")]}
    override_factory = _factory(calls_override, override_rows)
    provider = FinvizProvider(screener_factory=default_factory)

    out = provider.discover_universe(
        styles=("quality_growth",),
        sizes=("mega",),
        per_screen=5,
        screener_factory=override_factory,
    )

    assert calls_default == []
    assert len(calls_override) == 1
    assert out["candidates"][0]["Ticker"] == "ZZZ"
