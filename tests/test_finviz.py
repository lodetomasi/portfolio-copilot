"""Offline tests for the Finviz discovery provider (no network: screener is faked)."""

import pandas as pd
import pytest

from portfolio_copilot.providers.finviz import PRESETS, STYLE_ORDER, FinvizProvider, validate_preset


@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_presets_use_valid_finviz_filters(preset):
    validate_preset(PRESETS[preset])  # raises on unknown label/option


def test_validate_preset_rejects_unknown_option():
    with pytest.raises(ValueError):
        validate_preset({"Market Cap.": "Gigantic"})


class _FakeScreener:
    calls: list = []

    def __init__(self, df=None):
        self.filters = None

    def set_filter(self, filters_dict):
        self.filters = filters_dict

    def screener_view(self, order, ascend, limit, verbose):
        _FakeScreener.calls.append((order, ascend, limit))
        return pd.DataFrame(
            {
                "Ticker": ["AAA", "BBB", "CCC"],
                "Company": ["A Inc", "B Corp", "C plc"],
                "Sector": ["Tech", "Health", "Tech"],
                "Market Cap": [5e9, 3e9, float("nan")],
                "Price": [10.0, 20.0, 30.0],
            }
        )


def test_screen_returns_candidates_with_provenance_and_caches():
    provider = FinvizProvider(screener_factory=_FakeScreener)
    out = provider.screen("quality_growth", limit=2)
    assert out["ok"] is True and out["source"] == "finviz" and out["tier"] == "C"
    assert [c["Ticker"] for c in out["candidates"]] == ["AAA", "BBB"]
    assert out["filters"] == PRESETS["quality_growth"]
    assert "Re-score" in out["note"]
    again = provider.screen("quality_growth", limit=2)
    assert again is out  # cached: one screener call only
    assert len(_FakeScreener.calls) == 1


def test_screen_handles_empty_result_and_nan():
    class Empty(_FakeScreener):
        def screener_view(self, order, ascend, limit, verbose):
            return pd.DataFrame()

    out = FinvizProvider(screener_factory=Empty).screen("momentum")
    assert out["ok"] is False and out["candidates"] == [] and "no rows" in out["error"]

    full = FinvizProvider(screener_factory=_FakeScreener).screen("quality_value", limit=3)
    assert full["candidates"][2]["Market Cap"] is None  # NaN -> null, never invented


@pytest.mark.parametrize("preset,limit", [("nope", 10), ("momentum", 0)])
def test_screen_rejects_bad_arguments(preset, limit):
    with pytest.raises(ValueError):
        FinvizProvider(screener_factory=_FakeScreener).screen(preset, limit)


def test_screen_degrades_when_scraper_call_raises():
    class Boom(_FakeScreener):
        def screener_view(self, order, ascend, limit, verbose):
            raise ConnectionError("finviz unreachable")

    out = FinvizProvider(screener_factory=Boom).screen("quality_growth", limit=5)
    assert out["ok"] is False
    assert out["candidates"] == []
    assert "finviz unreachable" in out["error"]
    assert out["source"] == "finviz" and out["tier"] == "C"


# --- screen() must rank by the style's own signal, not always Market Cap. (finding 8) -----


@pytest.mark.parametrize("preset", sorted(PRESETS))
def test_screen_orders_by_the_preset_own_style_order_not_market_cap(preset):
    _FakeScreener.calls.clear()
    FinvizProvider(screener_factory=_FakeScreener).screen(preset, limit=5)
    order_used = _FakeScreener.calls[-1][0]
    assert order_used == STYLE_ORDER[preset]


# --- a transient scrape failure must not be cached as "unavailable" for the TTL (finding 28)


def test_screen_does_not_cache_a_failed_scrape():
    class FlakyThenGood:
        calls = 0

        def __init__(self):
            pass

        def set_filter(self, filters_dict):
            pass

        def screener_view(self, order, ascend, limit, verbose):
            FlakyThenGood.calls += 1
            if FlakyThenGood.calls == 1:
                raise ConnectionError("blip")
            return pd.DataFrame(
                {
                    "Ticker": ["AAA"],
                    "Company": ["A Inc"],
                    "Sector": ["Tech"],
                    "Market Cap": [5e9],
                    "Price": [10.0],
                }
            )

    provider = FinvizProvider(screener_factory=FlakyThenGood)
    first = provider.screen("quality_growth", limit=5)
    assert first["ok"] is False

    second = provider.screen("quality_growth", limit=5)
    assert FlakyThenGood.calls == 2  # the failure was not cached; the retry actually ran
    assert second["ok"] is True
    assert second is not first
