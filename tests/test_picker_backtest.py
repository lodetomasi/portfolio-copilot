"""Offline, deterministic tests for the disclosed PROXY backtest of the stock picker.

Every scenario uses synthetic, hand-computable prices/surprises/fundamentals/rating
events -- no network, no yfinance/SEC objects. Point-in-time correctness (nothing dated
after ``D`` may influence the score at ``D``) is the property most tests are built around.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

import numpy as np
import pandas as pd
import pytest

from portfolio_copilot.portfolio.picker_backtest import (
    _forward_return,
    _t_stat,
    proxy_score_at,
    run_proxy_backtest,
)


def _daily_series(start: str, days: int, value_at: Callable[[int], float]) -> pd.Series:
    idx = pd.date_range(start, periods=days, freq="D")
    return pd.Series([value_at(i) for i in range(days)], index=idx, dtype=float)


def _flat_then_jump(start: str, flat_days: int, extra_days: int, jump_to: float) -> pd.Series:
    """Flat at 100.0 for ``flat_days``, then a huge one-day jump for ``extra_days`` more."""
    idx = pd.date_range(start, periods=flat_days + extra_days, freq="D")
    values = [100.0] * flat_days + [jump_to] * extra_days
    return pd.Series(values, index=idx, dtype=float)


def _random_walk(
    seed: int, start: str, days: int, drift: float = 0.0004, vol: float = 0.01
) -> pd.Series:
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, size=days)
    idx = pd.date_range(start, periods=days, freq="D")
    return pd.Series(100 * np.exp(np.cumsum(rets)), index=idx)


# ---------------------------------------------------------------------------
# forward return arithmetic
# ---------------------------------------------------------------------------


def test_forward_return_exact_arithmetic():
    start = pd.Timestamp("2020-01-01")
    prices = _daily_series("2020-01-01", 400, lambda i: 100.0 + i)
    as_of = pd.Timestamp("2020-01-01")
    target = as_of + pd.DateOffset(months=6)  # 2020-07-01
    expected_end = 100.0 + (target - start).days
    expected = expected_end / 100.0 - 1.0

    result = _forward_return(prices, as_of, horizon_months=6)
    assert result == pytest.approx(expected)


def test_forward_return_none_when_horizon_exceeds_available_history():
    prices = _daily_series("2020-01-01", 60, lambda i: 100.0 + i)  # only ~2 months of data
    assert _forward_return(prices, pd.Timestamp("2020-01-01"), horizon_months=6) is None


def test_forward_return_none_on_empty_series():
    assert _forward_return(pd.Series(dtype=float), pd.Timestamp("2020-01-01"), 6) is None
    assert _forward_return(None, pd.Timestamp("2020-01-01"), 6) is None


# ---------------------------------------------------------------------------
# point-in-time filtering (momentum, fundamentals, surprises, rating events)
# ---------------------------------------------------------------------------


def test_momentum_excludes_price_moves_after_d():
    # Flat at 100 for 800 days, then an enormous jump the day right after D.
    prices = _flat_then_jump("2020-01-01", flat_days=800, extra_days=50, jump_to=100_000.0)
    as_of = prices.index[799]  # the last flat day: D itself
    result = proxy_score_at(as_of, prices, [], [], [])

    # All three lookback returns are exactly 0 (flat history only) -> hand-computed score.
    expected = (
        (0.0 - (-0.20)) / (0.30 - (-0.20)) * 100.0
        + (0.0 - (-0.30)) / (0.50 - (-0.30)) * 100.0
        + (0.0 - (-0.40)) / (0.80 - (-0.40)) * 100.0
    ) / 3
    assert result["available"]["momentum"] is True
    assert result["components"]["momentum"] == pytest.approx(expected)

    # Once D actually moves past the jump, momentum must reflect it -- proving the filter
    # excludes the future, not that it is simply broken/always-neutral.
    later = prices.index[810]
    later_result = proxy_score_at(later, prices, [], [], [])
    assert later_result["components"]["momentum"] > result["components"]["momentum"] + 30


def test_fundamentals_use_filed_date_not_end_date():
    fundamentals = [
        {"end": date(2022, 12, 31), "filed": date(2023, 2, 10), "revenue": 100.0, "eps": 4.0},
        {"end": date(2023, 12, 31), "filed": date(2024, 2, 15), "revenue": 120.0, "eps": 5.0},
        # Filed AFTER D: must never influence the score at D even though its period ended
        # long before D.
        {"end": date(2024, 12, 31), "filed": date(2025, 2, 10), "revenue": 999.0, "eps": 99.0},
    ]
    before_2023_filing = proxy_score_at(date(2024, 1, 1), None, [], fundamentals, [])
    assert before_2023_filing["available"]["fundamental_momentum"] is False  # only one row filed

    after_2023_filing = proxy_score_at(date(2024, 6, 1), None, [], fundamentals, [])
    assert after_2023_filing["available"]["fundamental_momentum"] is True
    assert after_2023_filing["components"]["fundamental_momentum"] == pytest.approx(75.0)

    # A far-future D must still be unaffected by the row filed after it in this fixture --
    # rerun at a D before that filing to confirm the 999/99 row plays no part.
    still_before_future_filing = proxy_score_at(date(2024, 12, 31), None, [], fundamentals, [])
    assert still_before_future_filing["components"]["fundamental_momentum"] == pytest.approx(75.0)


def test_surprises_exclude_earnings_reported_after_d():
    # yfinance_surprises.derive_surprise_stats requires reported_eps to count a quarter as
    # "reported", and needs >= 4 such quarters before it will emit a stat at all.
    quarters = [
        {"earnings_date": date(2023, 1, 15), "reported_eps": 1.0, "surprise_pct": 0.02},
        {"earnings_date": date(2023, 4, 15), "reported_eps": 1.0, "surprise_pct": 0.03},
        {"earnings_date": date(2023, 7, 15), "reported_eps": 1.0, "surprise_pct": -0.01},
        {"earnings_date": date(2023, 10, 15), "reported_eps": 1.0, "surprise_pct": 0.04},
        # After D: a huge beat that must NOT leak into the score.
        {"earnings_date": date(2024, 4, 20), "reported_eps": 1.0, "surprise_pct": 0.50},
    ]
    result = proxy_score_at(date(2024, 3, 1), None, quarters, [], [])
    assert result["available"]["track_record"] is True
    mean_surprise = (0.02 + 0.03 - 0.01 + 0.04) / 4
    positive_share = 3 / 4
    expected = (
        (positive_share - 0.25) / (0.9 - 0.25) * 100.0
        + (mean_surprise - (-0.05)) / (0.10 - (-0.05)) * 100.0
    ) / 2
    assert result["components"]["track_record"] == pytest.approx(expected)

    # Only 3 of the 5 quarters are known yet at this earlier D -> below the 4-quarter floor.
    early = proxy_score_at(date(2023, 8, 1), None, quarters, [], [])
    assert early["available"]["track_record"] is False


def test_rating_events_exclude_upgrades_after_d():
    events = [
        {"date": date(2024, 1, 1), "action": "up"},
        {"date": date(2024, 4, 1), "action": "down"},  # after D
    ]
    result = proxy_score_at(date(2024, 3, 1), None, [], [], events)
    assert result["available"]["revision_momentum"] is True
    # net_upgrades_90d == 1 (only the "up" counts; "down" is after D) -> _linear(1, -4, 4)
    # == 62.5 raw, but only 1 trailing event (< the 3-event floor) shrinks it toward 50.
    assert result["components"]["revision_momentum"] == pytest.approx(50.0 + (62.5 - 50.0) / 3)


def test_revision_momentum_below_min_events_is_shrunk_toward_neutral():
    """finding 22: a single rating-change event must not fully drive the score the way it
    would with unanimous, well-covered history -- it is shrunk, not treated as reliable."""
    events = [{"date": date(2024, 1, 1), "action": "up"}]
    result = proxy_score_at(date(2024, 3, 1), None, [], [], events)

    assert result["available"]["revision_momentum"] is True
    assert 50.0 < result["components"]["revision_momentum"] < 62.5


def test_revision_momentum_at_or_above_min_events_is_not_shrunk():
    events = [
        {"date": date(2024, 1, 1), "action": "up"},
        {"date": date(2024, 1, 15), "action": "up"},
        {"date": date(2024, 2, 1), "action": "up"},
    ]
    result = proxy_score_at(date(2024, 3, 1), None, [], [], events)
    assert result["components"]["revision_momentum"] == pytest.approx(87.5)  # _linear(3,-4,4)


def test_rating_events_outside_trailing_window_are_ignored():
    # Real coverage exists (an upgrade happened once), but it is well outside the trailing
    # 90-day window: the component stays available (coverage is real) yet must not count
    # a stale event as a recent net upgrade -> neutral 50, not skewed positive.
    events = [{"date": date(2023, 1, 1), "action": "up"}]
    result = proxy_score_at(date(2024, 3, 1), None, [], [], events)
    assert result["available"]["revision_momentum"] is True
    assert result["components"]["revision_momentum"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# missing data handling
# ---------------------------------------------------------------------------


def test_only_prices_available_score_equals_momentum():
    prices = _daily_series("2020-01-01", 800, lambda i: 100.0 + i * 0.01)
    as_of = prices.index[700]
    result = proxy_score_at(as_of, prices, [], [], [])
    assert result["available"] == {
        "momentum": True,
        "track_record": False,
        "fundamental_momentum": False,
        "revision_momentum": False,
    }
    assert result["score"] == pytest.approx(result["components"]["momentum"])


def test_nothing_available_falls_back_to_neutral_fifty():
    result = proxy_score_at(date(2024, 1, 1), None, None, None, None)
    assert all(v is False for v in result["available"].values())
    assert all(v == pytest.approx(50.0) for v in result["components"].values())
    assert result["score"] == pytest.approx(50.0)
    assert result["as_of"] == "2024-01-01"


# ---------------------------------------------------------------------------
# ranking by potential: strictly better momentum + surprises must rank first
# ---------------------------------------------------------------------------


def test_better_stock_ranks_first_and_wins_the_backtest():
    winner_prices = _daily_series("2020-01-01", 800, lambda i: 100.0 * (1.0015**i))
    loser_prices = _daily_series("2020-01-01", 800, lambda i: 100.0 * (0.9995**i))
    as_of = winner_prices.index[700]

    winner = proxy_score_at(
        as_of,
        winner_prices,
        [{"earnings_date": date(2020, 1, 5), "surprise_pct": 0.08}],
        [],
        [{"date": as_of - pd.Timedelta(days=10), "action": "up"}],
    )
    loser = proxy_score_at(
        as_of,
        loser_prices,
        [{"earnings_date": date(2020, 1, 5), "surprise_pct": -0.06}],
        [],
        [{"date": as_of - pd.Timedelta(days=10), "action": "down"}],
    )
    assert winner["score"] > loser["score"]
    for name in winner["components"]:
        assert winner["components"][name] >= loser["components"][name]

    universe = {
        "WINNER": {
            "prices": winner_prices, "surprises": [], "fundamentals": [], "rating_events": [],
        },
        "LOSER": {
            "prices": loser_prices, "surprises": [], "fundamentals": [], "rating_events": [],
        },
    }
    benchmark = _daily_series("2020-01-01", 800, lambda i: 100.0 * (1.0002**i))
    result = run_proxy_backtest(
        universe, benchmark, rebalance_dates=[as_of], horizon_months=3, top_quantile=0.5
    )
    row = result["rows"][0]
    assert row["n_scored"] == 2
    assert row["n_top"] == 1
    # The only pick in the top bucket must be WINNER's own forward return.
    winner_fwd = _forward_return(winner_prices, as_of, 3)
    assert row["top_return"] == pytest.approx(winner_fwd)


# ---------------------------------------------------------------------------
# run_proxy_backtest: skipping, disclosures, aggregates
# ---------------------------------------------------------------------------


def test_empty_universe_never_raises_and_reports_zero():
    benchmark = _daily_series("2020-01-01", 400, lambda i: 100.0 + i)
    result = run_proxy_backtest({}, benchmark, rebalance_dates=[date(2020, 3, 1)], horizon_months=3)
    row = result["rows"][0]
    expected_benchmark_return = _forward_return(benchmark, pd.Timestamp(date(2020, 3, 1)), 3)
    assert row == {
        "date": "2020-03-01",
        "n_scored": 0,
        "n_top": 0,
        "n_skipped": 0,
        "top_return": None,
        "benchmark_return": expected_benchmark_return,
        "excess": None,
        "hit": None,
    }


def test_malformed_ticker_data_is_skipped_not_raised():
    prices = _daily_series("2020-01-01", 800, lambda i: 100.0 + i * 0.01)
    universe = {
        "GOOD": {"prices": prices, "surprises": [], "fundamentals": [], "rating_events": []},
        # fundamentals is not iterable -> TypeError inside the engine; must be caught and
        # counted, never propagated.
        "BAD": {"prices": prices, "surprises": [], "fundamentals": 12345, "rating_events": []},
        # no usable data anywhere -> skipped via the "not any(available)" branch.
        "EMPTY": {"prices": None, "surprises": None, "fundamentals": None, "rating_events": None},
    }
    as_of = prices.index[700]
    result = run_proxy_backtest(universe, prices, rebalance_dates=[as_of], horizon_months=3)
    row = result["rows"][0]
    assert row["n_scored"] == 1
    assert row["n_skipped"] == 2


def test_disclosures_always_present_even_with_no_rebalance_dates():
    benchmark = _daily_series("2020-01-01", 100, lambda i: 100.0 + i)
    result = run_proxy_backtest({}, benchmark, rebalance_dates=[], horizon_months=3)
    assert result["rows"] == []
    assert result["n_periods"] == 0
    assert result["mean_excess"] is None
    assert result["hit_rate"] is None
    assert result["t_stat"] is None
    assert len(result["disclosures"]) >= 4
    assert any("survivorship" in d.lower() for d in result["disclosures"])
    assert any("yahoo" in d.lower() for d in result["disclosures"])
    assert any("transaction cost" in d.lower() for d in result["disclosures"])
    assert any("consensus" in d.lower() for d in result["disclosures"])


def test_disclosures_add_sample_size_warning_below_eight_periods():
    prices = _daily_series("2020-01-01", 800, lambda i: 100.0 + i * 0.01)
    universe = {"A": {"prices": prices, "surprises": [], "fundamentals": [], "rating_events": []}}
    dates = [prices.index[400 + 30 * k] for k in range(3)]
    result = run_proxy_backtest(universe, prices, rebalance_dates=dates, horizon_months=1)
    assert result["n_periods"] < 8
    assert any("not distinguishable from luck" in d for d in result["disclosures"])
    assert result["t_stat"] is None


# ---------------------------------------------------------------------------
# t-stat helper and its threshold in run_proxy_backtest
# ---------------------------------------------------------------------------


def test_t_stat_none_below_two_and_zero_variance():
    assert _t_stat([]) is None
    assert _t_stat([0.05]) is None
    assert _t_stat([0.02, 0.02, 0.02]) is None  # zero variance -> undefined, not inf


def test_t_stat_manual_formula():
    values = [0.01, 0.03, -0.02, 0.04, 0.00, 0.02, 0.05, -0.01]
    result = _t_stat(values)
    n = len(values)
    m = sum(values) / n
    variance = sum((x - m) ** 2 for x in values) / (n - 1)
    expected = m / (variance / n) ** 0.5
    assert result == pytest.approx(expected)


def test_run_proxy_backtest_t_stat_matches_helper_at_eight_periods():
    winner_prices = _random_walk(seed=1, start="2016-01-01", days=1400, drift=0.0008)
    other_prices = _random_walk(seed=2, start="2016-01-01", days=1400, drift=0.0002)
    benchmark = _random_walk(seed=3, start="2016-01-01", days=1400, drift=0.0004)
    universe = {
        "A": {"prices": winner_prices, "surprises": [], "fundamentals": [], "rating_events": []},
        "B": {"prices": other_prices, "surprises": [], "fundamentals": [], "rating_events": []},
    }
    dates = list(pd.date_range("2017-06-01", periods=8, freq="60D"))
    result = run_proxy_backtest(universe, benchmark, rebalance_dates=dates, horizon_months=3)

    excesses = [r["excess"] for r in result["rows"] if r["excess"] is not None]
    assert len(excesses) == 8
    assert result["n_periods"] == 8
    assert result["t_stat"] == pytest.approx(_t_stat(excesses))
    assert result["t_stat"] is not None


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


def test_run_proxy_backtest_is_deterministic():
    prices_a = _random_walk(seed=10, start="2019-01-01", days=900)
    prices_b = _random_walk(seed=20, start="2019-01-01", days=900)
    benchmark = _random_walk(seed=30, start="2019-01-01", days=900)
    universe = {
        "A": {
            "prices": prices_a,
            "surprises": [{"earnings_date": date(2019, 6, 1), "surprise_pct": 0.02}],
            "fundamentals": [
                {
                    "end": date(2018, 12, 31), "filed": date(2019, 2, 1),
                    "revenue": 100.0, "eps": 4.0,
                },
                {
                    "end": date(2019, 12, 31), "filed": date(2020, 2, 1),
                    "revenue": 110.0, "eps": 4.4,
                },
            ],
            "rating_events": [{"date": date(2019, 6, 1), "action": "up"}],
        },
        "B": {"prices": prices_b, "surprises": [], "fundamentals": [], "rating_events": []},
    }
    dates = list(pd.date_range("2019-09-01", periods=4, freq="90D"))

    first = run_proxy_backtest(universe, benchmark, rebalance_dates=dates, horizon_months=3)
    second = run_proxy_backtest(universe, benchmark, rebalance_dates=dates, horizon_months=3)
    assert first == second


def test_proxy_score_at_is_deterministic():
    prices = _random_walk(seed=42, start="2018-01-01", days=800)
    as_of = prices.index[700]
    first = proxy_score_at(as_of, prices, [], [], [])
    second = proxy_score_at(as_of, prices, [], [], [])
    assert first == second


# ---------------------------------------------------------------------------
# custom weights
# ---------------------------------------------------------------------------


def test_custom_weights_isolate_a_single_component():
    prices = _daily_series("2020-01-01", 800, lambda i: 100.0 + i * 0.02)
    as_of = prices.index[700]
    result = proxy_score_at(as_of, prices, [], [], [], weights={"momentum": 1.0})
    assert result["score"] == pytest.approx(result["components"]["momentum"])
