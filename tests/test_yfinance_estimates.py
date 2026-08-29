"""Offline tests for the free Yahoo analyst-estimate / rating-event provider.

Every test injects a fake ``ticker_factory`` (mirroring the pattern in
``test_yahooquery_fallback.py``) exposing the same method/property names as yfinance's
``Ticker``, returning canned pandas/py objects -- never a real network call.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from portfolio_copilot.providers import yfinance_estimates
from portfolio_copilot.providers.yfinance_estimates import (
    AnalystEstimates,
    _coerce_date,
    _consensus_score,
    _f,
    _growth_1y,
    derive_revision_momentum,
    fetch_estimates,
    fetch_rating_events,
)

AS_OF = date(2026, 8, 29)


@pytest.fixture(autouse=True)
def _clean_cache():
    """The module-level TTLCache is a shared singleton; never let one test's canned data
    leak into another (same pattern as test_sec_filings.py's cache-clearing fixture)."""
    yfinance_estimates._CACHE._store.clear()
    yield


class _FakeTicker:
    """Stand-in for yfinance's ``Ticker``: canned per-method payloads, or a raised exception,
    for one symbol. ``raise_on`` names which method/property calls should blow up."""

    def __init__(
        self,
        symbol: str,
        *,
        earnings_estimate=None,
        revenue_estimate=None,
        eps_revisions=None,
        recommendations_summary=None,
        price_targets=None,
        calendar=None,
        upgrades_downgrades=None,
        raise_on: tuple[str, ...] = (),
    ) -> None:
        self.symbol = symbol
        self._earnings_estimate = earnings_estimate
        self._revenue_estimate = revenue_estimate
        self._eps_revisions = eps_revisions
        self._recommendations_summary = recommendations_summary
        self._price_targets = price_targets
        self._calendar = calendar
        self._upgrades_downgrades = upgrades_downgrades
        self._raise_on = set(raise_on)

    def _maybe_raise(self, name: str) -> None:
        if name in self._raise_on:
            raise RuntimeError(f"{name} boom")

    def get_earnings_estimate(self):
        self._maybe_raise("earnings_estimate")
        return self._earnings_estimate

    def get_revenue_estimate(self):
        self._maybe_raise("revenue_estimate")
        return self._revenue_estimate

    def get_eps_revisions(self):
        self._maybe_raise("eps_revisions")
        return self._eps_revisions

    def get_recommendations_summary(self):
        self._maybe_raise("recommendations_summary")
        return self._recommendations_summary

    def get_analyst_price_targets(self):
        self._maybe_raise("price_targets")
        return self._price_targets

    def get_calendar(self):
        self._maybe_raise("calendar")
        return self._calendar

    @property
    def upgrades_downgrades(self):
        self._maybe_raise("upgrades_downgrades")
        return self._upgrades_downgrades


def make_factory(**fake_ticker_kwargs):
    """Build a ticker_factory that always returns the same canned ``_FakeTicker`` and
    records every symbol it was called with."""
    calls: list[str] = []

    def factory(symbol):
        calls.append(symbol)
        return _FakeTicker(symbol, **fake_ticker_kwargs)

    factory.calls = calls
    return factory


def earnings_df(avg_0y=2.0, avg_1y=2.5, analysts_1y=18):
    return pd.DataFrame(
        {
            "avg": [avg_0y, avg_1y],
            "low": [avg_0y * 0.9, avg_1y * 0.9],
            "high": [avg_0y * 1.1, avg_1y * 1.1],
            "yearAgoEps": [1.5, avg_0y],
            "numberOfAnalysts": [15, analysts_1y],
            "growth": [0.1, 0.25],
        },
        index=["0y", "+1y"],
    )


def revenue_df(avg_0y=1000.0, avg_1y=1100.0):
    return pd.DataFrame(
        {
            "avg": [avg_0y, avg_1y],
            "low": [avg_0y * 0.9, avg_1y * 0.9],
            "high": [avg_0y * 1.1, avg_1y * 1.1],
            "numberOfAnalysts": [15, 18],
            "yearAgoRevenue": [900.0, avg_0y],
            "growth": [0.1, 0.1],
        },
        index=["0y", "+1y"],
    )


def revisions_df(up_0y=3, up_1y=4, down_0y=1, down_1y=0):
    return pd.DataFrame(
        {
            "upLast7days": [1, 2],
            "upLast30days": [up_0y, up_1y],
            "downLast30days": [down_0y, down_1y],
            "downLast7Days": [0, 0],
        },
        index=["0y", "+1y"],
    )


def recommendations_df():
    return pd.DataFrame(
        {
            "period": ["0m", "-1m", "-2m", "-3m"],
            "strongBuy": [10, 9, 8, 8],
            "buy": [5, 5, 5, 4],
            "hold": [3, 3, 4, 4],
            "sell": [1, 1, 1, 1],
            "strongSell": [0, 0, 0, 0],
        }
    )


def price_targets_dict(current=100.0, mean=115.0):
    return {"current": current, "high": 130.0, "low": 90.0, "mean": mean, "median": 112.0}


def calendar_dict(dates):
    return {"Earnings Date": dates}


def upgrades_downgrades_df(rows):
    """``rows`` is a list of (days_before_as_of, Action, current_pt, prior_pt) tuples."""
    index = [
        pd.Timestamp(AS_OF - timedelta(days=days), tz="UTC") for days, *_ in rows
    ]
    return pd.DataFrame(
        {
            "Firm": [f"Firm {i}" for i in range(len(rows))],
            "ToGrade": ["Overweight"] * len(rows),
            "FromGrade": ["Equal-Weight"] * len(rows),
            "Action": [r[1] for r in rows],
            "priceTargetAction": ["Raises"] * len(rows),
            "currentPriceTarget": [r[2] for r in rows],
            "priorPriceTarget": [r[3] for r in rows],
        },
        index=pd.DatetimeIndex(index, name="GradeDate"),
    )


# --- fetch_estimates: happy path -----------------------------------------------------------


def test_fetch_estimates_happy_path_all_fields_available():
    factory = make_factory(
        earnings_estimate=earnings_df(),
        revenue_estimate=revenue_df(),
        eps_revisions=revisions_df(),
        recommendations_summary=recommendations_df(),
        price_targets=price_targets_dict(),
        calendar=calendar_dict([date(2026, 7, 1), date(2026, 10, 15)]),
        upgrades_downgrades=upgrades_downgrades_df(
            [(9, "up", 130.0, 120.0), (20, "down", 100.0, 110.0)]
        ),
    )

    result = fetch_estimates("aapl", AS_OF, ticker_factory=factory)

    assert isinstance(result, AnalystEstimates)
    assert result.ticker == "AAPL"
    assert factory.calls == ["AAPL"]  # ticker() normalized to upper, called once
    assert result.est_eps_growth_1y == pytest.approx(0.25)
    assert result.est_revenue_growth_1y == pytest.approx(0.1)
    assert result.eps_revisions_up_30d == 7  # 3 + 4
    assert result.eps_revisions_down_30d == 1  # 1 + 0
    assert result.revision_balance == pytest.approx((7 - 1) / 8)
    assert result.analyst_count == 18  # numberOfAnalysts at '+1y', preferred over recs total
    assert result.consensus_score == pytest.approx((2 * 10 + 5 - 1 - 0) / (2 * 19))
    assert result.target_upside == pytest.approx(0.15)
    assert result.next_earnings_date == "2026-10-15"  # 2026-07-01 already in the past
    assert result.days_to_next_earnings == (date(2026, 10, 15) - AS_OF).days
    assert result.revision_net_90d == 0  # one up, one down within the 90d window
    assert result.revision_events_90d == 2
    assert result.revision_pt_change_90d == pytest.approx(
        ((130 / 120 - 1) + (100 / 110 - 1)) / 2
    )
    assert result.provenance["source"] == "yfinance"
    assert result.provenance["tier"] == "B"
    assert result.provenance["confidence"] == 1.0
    assert result.provenance["missing_fields"] == []
    assert "event-dated" in result.provenance["notes"][0]


def test_fetch_estimates_normalizes_and_strips_ticker():
    factory = make_factory(earnings_estimate=earnings_df())
    result = fetch_estimates("  msft ", AS_OF, ticker_factory=factory)
    assert result.ticker == "MSFT"
    assert factory.calls == ["MSFT"]


def test_fetch_estimates_empty_ticker_raises():
    with pytest.raises(ValueError):
        fetch_estimates("   ", AS_OF, ticker_factory=make_factory())


# --- partial failures: one module raising degrades only its own fields ---------------------


def test_fetch_estimates_partial_failure_isolates_the_failing_group():
    factory = make_factory(
        earnings_estimate=earnings_df(),
        revenue_estimate=revenue_df(),
        eps_revisions=revisions_df(),
        recommendations_summary=recommendations_df(),
        price_targets=price_targets_dict(),
        calendar=calendar_dict([date(2026, 10, 15)]),
        upgrades_downgrades=upgrades_downgrades_df([(9, "up", 130.0, 120.0)]),
        raise_on=("revenue_estimate",),
    )

    result = fetch_estimates("XYZ", AS_OF, ticker_factory=factory)

    assert result.est_revenue_growth_1y is None
    assert any("get_revenue_estimate" in m for m in result.provenance["missing_fields"])
    # every other group is unaffected by the revenue_estimate failure
    assert result.est_eps_growth_1y == pytest.approx(0.25)
    assert result.eps_revisions_up_30d == 7
    assert result.consensus_score is not None
    assert result.target_upside is not None
    assert result.next_earnings_date == "2026-10-15"
    assert result.revision_events_90d == 1
    assert 0.0 < result.provenance["confidence"] < 1.0


def test_fetch_estimates_all_sources_raise_degrades_gracefully_never_crashes():
    factory = make_factory(
        raise_on=(
            "earnings_estimate",
            "revenue_estimate",
            "eps_revisions",
            "recommendations_summary",
            "price_targets",
            "calendar",
            "upgrades_downgrades",
        )
    )

    result = fetch_estimates("ZZZZ", AS_OF, ticker_factory=factory)

    assert result.est_eps_growth_1y is None
    assert result.est_revenue_growth_1y is None
    assert result.eps_revisions_up_30d is None
    assert result.eps_revisions_down_30d is None
    assert result.revision_balance is None
    assert result.analyst_count is None
    assert result.consensus_score is None
    assert result.target_upside is None
    assert result.next_earnings_date is None
    assert result.days_to_next_earnings is None
    assert result.revision_net_90d is None
    assert result.revision_pt_change_90d is None
    assert result.revision_events_90d is None
    assert result.provenance["confidence"] == 0.0
    assert len(result.provenance["missing_fields"]) >= 7


def test_fetch_estimates_all_missing_but_data_present_and_empty():
    """Every source returns an empty/None payload (no exception) -- still degrades cleanly."""
    factory = make_factory(
        earnings_estimate=pd.DataFrame(),
        revenue_estimate=pd.DataFrame(),
        eps_revisions=pd.DataFrame(),
        recommendations_summary=pd.DataFrame(),
        price_targets={},
        calendar={},
        upgrades_downgrades=pd.DataFrame(),
    )

    result = fetch_estimates("EMPTY", AS_OF, ticker_factory=factory)

    assert result.est_eps_growth_1y is None
    assert result.analyst_count is None
    assert result.consensus_score is None
    assert result.target_upside is None
    assert result.next_earnings_date is None
    assert result.revision_events_90d is None  # empty upgrades_downgrades -> no events at all
    assert result.provenance["confidence"] == 0.0


def test_fetch_estimates_nan_values_become_none():
    df = earnings_df()
    df.loc["+1y", "avg"] = np.nan
    df.loc["+1y", "numberOfAnalysts"] = np.nan
    factory = make_factory(earnings_estimate=df)

    result = fetch_estimates("NANCO", AS_OF, ticker_factory=factory)

    assert result.est_eps_growth_1y is None  # NaN forward estimate can't yield a growth rate
    assert result.analyst_count is None  # falls through to recs-summary fallback, also absent


def test_fetch_estimates_analyst_count_falls_back_to_recommendations_total():
    df = earnings_df()
    df.loc["+1y", "numberOfAnalysts"] = np.nan
    factory = make_factory(earnings_estimate=df, recommendations_summary=recommendations_df())

    result = fetch_estimates("FALLBACK", AS_OF, ticker_factory=factory)

    assert result.analyst_count == 19  # 10 + 5 + 3 + 1 + 0 at period '0m'


def test_fetch_estimates_zero_or_negative_base_blocks_growth():
    df = earnings_df(avg_0y=0.0, avg_1y=2.5)
    factory = make_factory(earnings_estimate=df)
    result = fetch_estimates("ZEROBASE", AS_OF, ticker_factory=factory)
    assert result.est_eps_growth_1y is None

    df2 = earnings_df(avg_0y=-1.0, avg_1y=2.5)
    factory2 = make_factory(earnings_estimate=df2)
    result2 = fetch_estimates("NEGBASE", AS_OF, ticker_factory=factory2)
    assert result2.est_eps_growth_1y is None


def test_fetch_estimates_zero_target_or_zero_revisions_return_none():
    factory = make_factory(price_targets=price_targets_dict(current=0.0))
    result = fetch_estimates("ZEROTARGET", AS_OF, ticker_factory=factory)
    assert result.target_upside is None

    factory2 = make_factory(eps_revisions=revisions_df(up_0y=0, up_1y=0, down_0y=0, down_1y=0))
    result2 = fetch_estimates("ZERODIV", AS_OF, ticker_factory=factory2)
    assert result2.eps_revisions_up_30d == 0
    assert result2.eps_revisions_down_30d == 0
    assert result2.revision_balance is None  # 0/0 is undefined, not a fabricated zero


def test_fetch_estimates_uses_cache_on_second_call():
    factory = make_factory(earnings_estimate=earnings_df())
    first = fetch_estimates("CACHEHIT", AS_OF, ticker_factory=factory)
    second = fetch_estimates("CACHEHIT", AS_OF, ticker_factory=factory)
    assert second is first
    assert factory.calls == ["CACHEHIT"]  # ticker_factory invoked only once


def test_fetch_estimates_different_as_of_bypasses_cache():
    factory = make_factory(earnings_estimate=earnings_df())
    fetch_estimates("DATECACHE", AS_OF, ticker_factory=factory)
    fetch_estimates("DATECACHE", AS_OF + timedelta(days=1), ticker_factory=factory)
    assert factory.calls == ["DATECACHE", "DATECACHE"]


# --- calendar date selection -----------------------------------------------------------


def test_next_earnings_date_picks_earliest_future_date_ignoring_past_ones():
    factory = make_factory(
        calendar=calendar_dict(
            [date(2026, 1, 1), date(2026, 12, 25), date(2026, 9, 3), AS_OF]
        )
    )
    result = fetch_estimates("CALTEST", AS_OF, ticker_factory=factory)
    # AS_OF itself counts as ">= as_of" and is earlier than both future dates
    assert result.next_earnings_date == AS_OF.isoformat()
    assert result.days_to_next_earnings == 0


def test_next_earnings_date_none_when_calendar_has_only_past_dates():
    factory = make_factory(calendar=calendar_dict([date(2020, 1, 1)]))
    result = fetch_estimates("PASTONLY", AS_OF, ticker_factory=factory)
    assert result.next_earnings_date is None
    assert result.days_to_next_earnings is None


def test_next_earnings_date_missing_or_empty_calendar():
    for cal in (None, {}, {"Earnings Date": []}, {"Earnings Date": None}):
        factory = make_factory(calendar=cal)
        result = fetch_estimates(f"CAL{id(cal)}", AS_OF, ticker_factory=factory)
        assert result.next_earnings_date is None


# --- fetch_rating_events -----------------------------------------------------------------


def test_fetch_rating_events_filters_to_as_of_and_sorts_newest_first():
    factory = make_factory(
        upgrades_downgrades=upgrades_downgrades_df(
            [
                (-5, "up", 150.0, 140.0),  # 5 days in the FUTURE relative to as_of -> excluded
                (9, "up", 130.0, 120.0),
                (95, "init", None, None),
            ]
        )
    )
    events = fetch_rating_events("US1", AS_OF, ticker_factory=factory)
    assert len(events) == 2  # the future row is excluded
    assert events[0]["date"] > events[1]["date"]  # newest first
    assert events[0]["action"] == "up"
    assert events[0]["pt_current"] == 130.0
    assert events[0]["pt_prior"] == 120.0
    assert events[0]["firm"] == "Firm 1"


def test_fetch_rating_events_empty_dataframe_for_european_ticker():
    factory = make_factory(upgrades_downgrades=pd.DataFrame())
    assert fetch_rating_events("ENEL.MI", AS_OF, ticker_factory=factory) == []


def test_fetch_rating_events_none_dataframe():
    factory = make_factory(upgrades_downgrades=None)
    assert fetch_rating_events("ASML.AS", AS_OF, ticker_factory=factory) == []


def test_fetch_rating_events_raising_returns_empty_not_an_exception():
    factory = make_factory(raise_on=("upgrades_downgrades",))
    assert fetch_rating_events("BROKEN", AS_OF, ticker_factory=factory) == []


def test_fetch_rating_events_empty_ticker_raises():
    with pytest.raises(ValueError):
        fetch_rating_events("", AS_OF, ticker_factory=make_factory())


def test_fetch_rating_events_a_bad_nat_grade_date_drops_only_that_row_not_the_whole_history():
    """finding 24: pd.Timestamp(pd.NaT).date() returns NaT itself (not None), so the
    `d is None` guard misses it and `d > as_of` raises TypeError -- must not lose the
    other, otherwise-valid rows for this ticker."""
    good_row = upgrades_downgrades_df([(9, "up", 130.0, 120.0)])
    bad_index = pd.DatetimeIndex(
        [good_row.index[0], pd.NaT], name="GradeDate"
    )
    df = pd.concat([good_row, good_row.iloc[[0]]], ignore_index=True)
    df.index = bad_index

    factory = make_factory(upgrades_downgrades=df)
    events = fetch_rating_events("MIXEDNAT", AS_OF, ticker_factory=factory)

    assert len(events) == 1
    assert events[0]["action"] == "up"


# --- derive_revision_momentum -------------------------------------------------------------


def test_derive_revision_momentum_no_events_returns_all_none():
    momentum = derive_revision_momentum([], AS_OF)
    assert momentum == {
        "net_upgrades_90d": None,
        "upgrades_90d": None,
        "downgrades_90d": None,
        "pt_change_pct_90d": None,
        "n_events_90d": None,
    }


def test_derive_revision_momentum_arithmetic_and_window_filtering():
    events = [
        {"date": (AS_OF - timedelta(days=1)).isoformat(), "action": "up",
         "pt_prior": 100.0, "pt_current": 110.0},
        {"date": (AS_OF - timedelta(days=50)).isoformat(), "action": "up",
         "pt_prior": 50.0, "pt_current": 55.0},
        {"date": (AS_OF - timedelta(days=80)).isoformat(), "action": "down",
         "pt_prior": 200.0, "pt_current": 180.0},
        # outside the 90-day window -- must not affect the result
        {"date": (AS_OF - timedelta(days=91)).isoformat(), "action": "down",
         "pt_prior": 300.0, "pt_current": 100.0},
        # a 'main'/'init' action with no PT change -- counted in n_events, not in up/down
        {"date": (AS_OF - timedelta(days=10)).isoformat(), "action": "main",
         "pt_prior": None, "pt_current": None},
    ]
    momentum = derive_revision_momentum(events, AS_OF, window_days=90)
    assert momentum["upgrades_90d"] == 2
    assert momentum["downgrades_90d"] == 1
    assert momentum["net_upgrades_90d"] == 1
    assert momentum["n_events_90d"] == 4  # the 91-day-old row is excluded
    expected_pt = ((110 / 100 - 1) + (55 / 50 - 1) + (180 / 200 - 1)) / 3
    assert momentum["pt_change_pct_90d"] == pytest.approx(expected_pt)


def test_derive_revision_momentum_ignores_future_events_beyond_as_of():
    events = [
        {"date": (AS_OF + timedelta(days=5)).isoformat(), "action": "up",
         "pt_prior": 100.0, "pt_current": 200.0},
        {"date": (AS_OF - timedelta(days=1)).isoformat(), "action": "down",
         "pt_prior": None, "pt_current": None},
    ]
    momentum = derive_revision_momentum(events, AS_OF, window_days=90)
    assert momentum["n_events_90d"] == 1
    assert momentum["downgrades_90d"] == 1
    assert momentum["upgrades_90d"] == 0


def test_derive_revision_momentum_zero_or_missing_prior_pt_excluded_from_average():
    events = [
        {"date": (AS_OF - timedelta(days=1)).isoformat(), "action": "up",
         "pt_prior": 0.0, "pt_current": 50.0},
        {"date": (AS_OF - timedelta(days=2)).isoformat(), "action": "up",
         "pt_prior": None, "pt_current": 60.0},
    ]
    momentum = derive_revision_momentum(events, AS_OF, window_days=90)
    assert momentum["pt_change_pct_90d"] is None  # no usable PT-change pair
    assert momentum["upgrades_90d"] == 2


# --- small pure helpers ------------------------------------------------------------------


def test_f_handles_nan_inf_and_none():
    assert _f(float("nan")) is None
    assert _f(float("inf")) is None
    assert _f(None) is None
    assert _f("3.5") == 3.5
    assert _f("not a number") is None


def test_coerce_date_handles_multiple_input_types():
    assert _coerce_date(None) is None
    assert _coerce_date(date(2026, 1, 1)) == date(2026, 1, 1)
    assert _coerce_date(pd.Timestamp("2026-01-01", tz="UTC")) == date(2026, 1, 1)
    assert _coerce_date("2026-01-01") == date(2026, 1, 1)
    assert _coerce_date("not-a-date") is None


def test_growth_1y_missing_period_or_column_returns_none():
    df = pd.DataFrame({"avg": [1.0]}, index=["0y"])  # no '+1y' row
    assert _growth_1y(df, "avg") is None
    assert _growth_1y(None, "avg") is None
    assert _growth_1y(pd.DataFrame(), "avg") is None


# --- _consensus_score codomain (finding 1) -------------------------------------------------


def _recs_row(strong_buy=0, buy=0, hold=0, sell=0, strong_sell=0):
    return pd.DataFrame(
        {
            "period": ["0m"],
            "strongBuy": [strong_buy],
            "buy": [buy],
            "hold": [hold],
            "sell": [sell],
            "strongSell": [strong_sell],
        }
    )


def test_consensus_score_never_exceeds_plus_minus_one():
    # unanimous strongBuy -> the theoretical max
    all_strong_buy = _recs_row(strong_buy=10)
    assert _consensus_score(all_strong_buy) == pytest.approx(1.0)

    # unanimous strongSell -> the theoretical min
    all_strong_sell = _recs_row(strong_sell=10)
    assert _consensus_score(all_strong_sell) == pytest.approx(-1.0)

    # a common, non-unanimous bullish mix must NOT saturate to 1.0
    common_bullish = _recs_row(strong_buy=8, buy=8, hold=3, sell=1)
    score = _consensus_score(common_bullish)
    assert -1.0 <= score <= 1.0
    assert score < 1.0


@pytest.mark.parametrize(
    "strong_buy,buy,hold,sell,strong_sell",
    [
        (10, 5, 3, 1, 0),
        (0, 0, 10, 0, 0),
        (0, 0, 0, 5, 10),
        (3, 3, 3, 3, 3),
        (1, 0, 0, 0, 0),
    ],
)
def test_consensus_score_codomain_is_bounded_for_any_recommendation_mix(
    strong_buy, buy, hold, sell, strong_sell
):
    df = _recs_row(strong_buy, buy, hold, sell, strong_sell)
    score = _consensus_score(df)
    if score is not None:
        assert -1.0 <= score <= 1.0


def test_consensus_score_matches_engine_consumer_scale():
    """The engine feeds consensus_score straight into _linear(..., -1.0, 1.0); confirm a
    realistic non-unanimous bullish mix does not saturate the engine's revisions score."""
    from portfolio_copilot.scoring.engine import _linear

    common_bullish = _recs_row(strong_buy=8, buy=8, hold=3, sell=1)
    score = _consensus_score(common_bullish)
    assert _linear(score, -1.0, 1.0) < 100.0


# --- malformed calendar payload does not crash the whole fetch (finding 2) -----------------


def test_fetch_estimates_malformed_calendar_scalar_earnings_date_degrades_not_crashes():
    factory = make_factory(
        earnings_estimate=earnings_df(),
        calendar={"Earnings Date": date(2026, 10, 15)},  # scalar, not a list -- malformed
    )

    result = fetch_estimates("BADCAL", AS_OF, ticker_factory=factory)

    assert result.next_earnings_date is None
    assert result.days_to_next_earnings is None
    # every other, unrelated field is unaffected by the malformed calendar
    assert result.est_eps_growth_1y == pytest.approx(0.25)
    assert any("next_earnings_date" in m for m in result.provenance["missing_fields"])


# --- a genuinely failed fetch (exception, not confirmed-empty) is not cached (finding 3) ---


def test_fetch_estimates_does_not_cache_a_fully_failed_fetch():
    class FlakyFactory:
        def __init__(self):
            self.calls = 0

        def __call__(self, symbol):
            self.calls += 1
            if self.calls == 1:
                return _FakeTicker(
                    symbol,
                    raise_on=(
                        "earnings_estimate",
                        "revenue_estimate",
                        "eps_revisions",
                        "recommendations_summary",
                        "price_targets",
                        "calendar",
                        "upgrades_downgrades",
                    ),
                )
            return _FakeTicker(symbol, earnings_estimate=earnings_df())

    factory = FlakyFactory()

    first = fetch_estimates("RATELIMITED", AS_OF, ticker_factory=factory)
    assert first.provenance["confidence"] == 0.0

    second = fetch_estimates("RATELIMITED", AS_OF, ticker_factory=factory)

    assert factory.calls == 2  # the failed attempt was NOT cached; the retry actually ran
    assert second.est_eps_growth_1y == pytest.approx(0.25)


def test_fetch_estimates_partial_success_is_still_cached():
    """A partial (not fully-failed) result IS cached, unaffected by the finding-3 fix."""
    factory = make_factory(earnings_estimate=earnings_df(), raise_on=("revenue_estimate",))
    first = fetch_estimates("PARTIALCACHE", AS_OF, ticker_factory=factory)
    second = fetch_estimates("PARTIALCACHE", AS_OF, ticker_factory=factory)
    assert second is first
    assert factory.calls == ["PARTIALCACHE"]
