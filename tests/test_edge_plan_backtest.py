"""Edge-case coverage for the investment plan builder and the cash-flow backtest.

Offline, deterministic, synthetic data only. Every test asserts the behaviour that
CLAUDE.md / docs/FINANCIAL_LOGIC.md intend (never invent data, never sell, degrade
explicitly instead of raising or leaking NaN). Tests encode the correct behaviour; when
one of them exposed a defect during the audit, the defect was fixed in src (never the test).
"""

from datetime import date

import numpy as np
import pandas as pd
import pytest

from portfolio_copilot.portfolio.backtest import simulate_cash_flow_plan
from portfolio_copilot.portfolio.plan import (
    build_calendar,
    build_investment_plan,
    contribution_cadence_months,
)
from portfolio_copilot.portfolio.rebalance import FeeModel

# ---------------------------------------------------------------------------
# plan.py: calendar edge cases (start_date, review cadence, horizon, zero length)
# ---------------------------------------------------------------------------


def test_build_calendar_zero_months_returns_no_events():
    assert build_calendar(date(2028, 1, 15), months=0, contribution_every=3, review_every=3) == []


def test_build_calendar_review_every_one_flags_review_or_annual_every_month():
    events = build_calendar(date(2028, 1, 15), months=24, contribution_every=5, review_every=1)
    # review_every=1 means every single simulated month carries a review-type action.
    assert len(events) == 24
    for event in events:
        month = event["month"]
        assert ("annual_review" in event["actions"]) == (month % 12 == 0)
        assert ("review" in event["actions"]) == (month % 12 != 0)
        assert ("contribute" in event["actions"]) == (month % 5 == 0)


def test_build_calendar_review_every_twelve_only_flags_annual_review():
    events = build_calendar(date(2028, 1, 15), months=24, contribution_every=3, review_every=12)
    # review_every == 12 is redundant with the annual_review branch: "review" never fires.
    assert len(events) == 8  # every month-multiple-of-3 in 1..24
    for event in events:
        assert "review" not in event["actions"]
        assert ("annual_review" in event["actions"]) == (event["month"] % 12 == 0)
    by_month = {e["month"]: e["actions"] for e in events}
    assert by_month[12] == ["contribute", "annual_review"]
    assert by_month[24] == ["contribute", "annual_review"]
    assert by_month[3] == ["contribute"]


def test_build_calendar_start_date_leap_day_clamps_and_rolls_into_next_year():
    # 2028-02-29 is a real leap day. _add_months clamps every event to day 28, so the
    # leap day itself must not resurface and the year must roll over correctly.
    events = build_calendar(date(2028, 2, 29), months=13, contribution_every=1, review_every=12)
    dates = [e["date"] for e in events]
    assert dates == [
        "2028-03-28",
        "2028-04-28",
        "2028-05-28",
        "2028-06-28",
        "2028-07-28",
        "2028-08-28",
        "2028-09-28",
        "2028-10-28",
        "2028-11-28",
        "2028-12-28",
        "2029-01-28",
        "2029-02-28",
        "2029-03-28",
    ]
    by_month = {e["month"]: e["actions"] for e in events}
    assert by_month[12] == ["contribute", "annual_review"]


def test_build_calendar_start_date_jan31_rolls_into_next_year():
    events = build_calendar(date(2028, 1, 31), months=13, contribution_every=1, review_every=12)
    dates = [e["date"] for e in events]
    assert dates == [
        "2028-02-28",
        "2028-03-28",
        "2028-04-28",
        "2028-05-28",
        "2028-06-28",
        "2028-07-28",
        "2028-08-28",
        "2028-09-28",
        "2028-10-28",
        "2028-11-28",
        "2028-12-28",
        "2029-01-28",
        "2029-02-28",
    ]
    by_month = {e["month"]: e["actions"] for e in events}
    assert by_month[12] == ["contribute", "annual_review"]


# ---------------------------------------------------------------------------
# plan.py: monthly_contribution extremes and a short (0.5y) horizon
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("monthly,expected_cadence", [(1e-6, 12), (1e6, 1)])
def test_contribution_cadence_handles_extreme_monthly_amounts(monthly, expected_cadence):
    assert contribution_cadence_months(monthly, FeeModel()) == expected_cadence


def test_build_plan_half_year_horizon_with_tiny_monthly_contribution_warns_and_never_invents():
    plan = build_investment_plan(
        cash_now=0,
        monthly_contribution=1e-6,
        horizon_years=0.5,
        risk_tolerance="medium",
        start_date=date(2028, 1, 15),
    )
    assert plan["horizon"]["months"] == 6
    assert plan["horizon"]["contributions_total_eur"] == 0.0
    assert plan["contribution"]["every_months"] == 12
    # 1e-6 EUR/month can never reach the 295 EUR minimum economic order: must be declared.
    assert any("minimum economic order" in w for w in plan["warnings"])
    assert plan["initial_orders"] == []


def test_build_plan_half_year_horizon_with_huge_monthly_contribution_invests_every_month():
    plan = build_investment_plan(
        cash_now=0,
        monthly_contribution=1e6,
        horizon_years=0.5,
        risk_tolerance="medium",
        start_date=date(2028, 1, 15),
    )
    assert plan["horizon"]["months"] == 6
    assert plan["horizon"]["contributions_total_eur"] == 6_000_000.0
    assert plan["contribution"]["every_months"] == 1
    assert plan["contribution"]["pooled_eur"] == 1_000_000.0
    assert plan["warnings"] == []


@pytest.mark.parametrize("start_date_", [date(2028, 2, 29), date(2028, 1, 31)])
@pytest.mark.parametrize("review_every_months", [1, 12])
def test_build_plan_calendar_survives_month_end_start_dates_and_review_cadences(
    start_date_, review_every_months
):
    plan = build_investment_plan(
        cash_now=1000,
        monthly_contribution=200,
        horizon_years=5,
        risk_tolerance="medium",
        start_date=start_date_,
        review_every_months=review_every_months,
        calendar_months=24,
    )
    assert plan["calendar"]  # cadence divides into 24 months, so events must exist
    assert all(event["date"].endswith("-28") for event in plan["calendar"])


def test_build_plan_calendar_months_zero_produces_empty_calendar():
    plan = build_investment_plan(
        cash_now=1000,
        monthly_contribution=200,
        horizon_years=5,
        risk_tolerance="medium",
        start_date=date(2028, 1, 15),
        calendar_months=0,
    )
    assert plan["calendar"] == []


# ---------------------------------------------------------------------------
# backtest.py: flat -> crash -> recovery path (drawdown correctness, never sells)
# ---------------------------------------------------------------------------


def test_backtest_flat_then_crash_then_recovery_reports_exact_drawdown():
    # Single bucket, no further contributions after the initial buy: value tracks price
    # exactly (units are constant), so max_drawdown must equal the price path's own
    # drawdown: trough at month 8 (price 40 vs. peak 100) => exactly -0.60.
    path = [100.0] * 4 + [90.0, 70.0, 50.0, 40.0] + [55.0, 70.0, 85.0, 95.0, 100.0]
    prices = pd.DataFrame({"A": path})
    out = simulate_cash_flow_plan(
        prices, {"A": 1.0}, initial_cash=1000, monthly_contribution=0, fee_model=FeeModel()
    )
    assert out["max_drawdown"] == pytest.approx(-0.6)
    assert out["cash_never_negative"]
    # No new cash ever arrives after the initial buy, so exactly one order is ever placed.
    assert out["orders"] == 1
    assert out["contributed_eur"] == 1000.0
    assert out["final_value_eur"] + out["fees_eur"] == pytest.approx(
        out["contributed_eur"], abs=0.02
    )


def test_backtest_never_sells_implied_units_are_non_decreasing_through_crash_and_recovery():
    # Two buckets that diverge sharply (A crashes and recovers, B stays flat) with ongoing
    # contributions: a rebalancer that could sell would trim A on the way down or B once A
    # recovers. allocate_cash_to_targets only ever buys, so the implied unit count of each
    # bucket -- backed out from the reported final_weights/final_value at growing price-history
    # prefixes -- must never decrease (rounding of final_weights to 4dp allows a tiny epsilon).
    a = [100.0] * 4 + [90.0, 70.0, 50.0, 40.0] + [55.0, 70.0, 85.0, 95.0, 100.0]
    b = [50.0] * len(a)
    prices = pd.DataFrame({"A": a, "B": b})
    targets = {"A": 0.5, "B": 0.5}

    previous_units = {"A": 0.0, "B": 0.0}
    for k in range(2, len(prices) + 1):
        out = simulate_cash_flow_plan(
            prices.iloc[:k],
            targets,
            initial_cash=1000,
            monthly_contribution=300,
            fee_model=FeeModel(),
            contribution_every_months=2,
        )
        invested = out["final_value_eur"] - out["cash_left_eur"]
        last_row = prices.iloc[k - 1]
        for bucket in targets:
            units = (
                (out["final_weights"][bucket] * invested) / float(last_row[bucket])
                if invested > 0
                else 0.0
            )
            floor = previous_units[bucket] - 0.01
            assert units >= floor, (k, bucket, units, previous_units[bucket])
            previous_units[bucket] = units


def test_backtest_low_priced_bucket_stays_numerically_sane():
    # A bucket priced at 0.01 must not trigger precision blow-ups (huge unit counts are
    # fine; NaN/inf and a broken accounting identity are not).
    prices = pd.DataFrame({"A": [0.01] * 6, "B": [100.0] * 6})
    out = simulate_cash_flow_plan(
        prices,
        {"A": 0.5, "B": 0.5},
        initial_cash=1000,
        monthly_contribution=300,
        fee_model=FeeModel(),
    )
    assert out["cash_never_negative"]
    assert np.isfinite(out["final_value_eur"])
    assert np.isfinite(out["max_drawdown"])
    assert abs(sum(out["final_weights"].values()) - 1.0) < 1e-3
    assert out["final_value_eur"] + out["fees_eur"] == pytest.approx(
        out["contributed_eur"], abs=0.02
    )


def test_backtest_unsorted_index_gives_same_result_as_default_index():
    # The docstring's precondition is row order ("ascending"), not index labels: the
    # function must key off physical row position, not the index, so scrambled index
    # labels on otherwise-identical rows must not change the outcome.
    targets = {"A": 0.6, "B": 0.4}
    data = {"A": [100.0, 110.0], "B": [50.0, 55.0]}
    sorted_result = simulate_cash_flow_plan(
        pd.DataFrame(data, index=[0, 1]), targets, initial_cash=1000, monthly_contribution=200
    )
    unsorted_result = simulate_cash_flow_plan(
        pd.DataFrame(data, index=[7, 3]), targets, initial_cash=1000, monthly_contribution=200
    )
    assert unsorted_result == sorted_result


def test_backtest_contribution_every_months_larger_than_available_history():
    # contribution_every_months=12 with only 3 monthly rows: only the initial buy (step 0)
    # ever fires: month indices 1..3 are never a multiple of 12. New cash piles up unspent.
    prices = pd.DataFrame({"A": [100.0, 100.0, 100.0]})
    out = simulate_cash_flow_plan(
        prices,
        {"A": 1.0},
        initial_cash=1000,
        monthly_contribution=200,
        fee_model=FeeModel(),
        contribution_every_months=12,
    )
    assert out["orders"] == 1
    assert out["contributed_eur"] == 1400.0
    assert out["cash_left_eur"] == 400.0
    assert out["fees_eur"] == 2.95
    assert out["cash_never_negative"]


def test_backtest_zero_initial_cash_and_zero_contribution_places_no_orders():
    prices = pd.DataFrame({"A": [100.0, 100.0, 100.0], "B": [50.0, 50.0, 50.0]})
    out = simulate_cash_flow_plan(
        prices, {"A": 0.5, "B": 0.5}, initial_cash=0, monthly_contribution=0, fee_model=FeeModel()
    )
    assert out["orders"] == 0
    assert out["contributed_eur"] == 0.0
    assert out["final_value_eur"] == 0.0
    assert out["cash_left_eur"] == 0.0
    assert out["fees_eur"] == 0.0
    assert out["cash_never_negative"]
    assert out["final_weights"] == {"A": 0.0, "B": 0.0}
    assert out["max_abs_drift"] is None
    assert out["months_out_of_band_pct"] == 0.0


def test_backtest_zero_cash_zero_contribution_drawdown_is_none_not_nan():
    # Regression test (audit 2026-08-28): max_drawdown() used to divide a constant-zero
    # value series by its own zero running max and returned NaN instead of None
    # (analytics/metrics.py, surfaced via portfolio/backtest.py). With no capital ever
    # invested, drawdown is undefined and must be reported as None, never as NaN
    # (CLAUDE.md: never invent/leak an undefined datum).
    prices = pd.DataFrame({"A": [100.0, 100.0, 100.0], "B": [50.0, 50.0, 50.0]})
    out = simulate_cash_flow_plan(
        prices, {"A": 0.5, "B": 0.5}, initial_cash=0, monthly_contribution=0, fee_model=FeeModel()
    )
    assert out["max_drawdown"] is None


def test_backtest_accounting_identity_holds_for_random_target_mixes():
    # CLAUDE.md: no invented returns. Under constant prices the only "gain" possible is
    # negative (fees), so invested value + fees + idle cash must reconstruct contributions
    # exactly (to rounding), whatever the target mix -- including near-zero-weight buckets.
    buckets = ["A", "B", "C", "D"]
    prices = pd.DataFrame(
        {"A": [100.0] * 24, "B": [50.0] * 24, "C": [10.0] * 24, "D": [5.0] * 24}
    )
    rng = np.random.default_rng(2024)
    for _ in range(5):
        weights = rng.dirichlet(np.ones(len(buckets)))
        targets = dict(zip(buckets, (float(w) for w in weights), strict=True))
        out = simulate_cash_flow_plan(
            prices, targets, initial_cash=3000, monthly_contribution=300, fee_model=FeeModel()
        )
        invested_value = out["final_value_eur"] - out["cash_left_eur"]
        assert invested_value + out["fees_eur"] + out["cash_left_eur"] == pytest.approx(
            out["contributed_eur"], abs=0.02
        )
        assert out["cash_never_negative"]
