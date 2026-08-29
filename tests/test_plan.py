from datetime import date

import pytest

from portfolio_copilot.portfolio.plan import (
    build_calendar,
    build_investment_plan,
    contribution_cadence_months,
    load_model_portfolios,
    suggest_profile,
)
from portfolio_copilot.portfolio.rebalance import FeeModel

START = date(2026, 1, 15)


def test_model_portfolios_are_valid_and_sum_to_one():
    models = load_model_portfolios()
    assert set(models["profiles"]) == {"cautious", "balanced", "growth"}
    for profile in models["profiles"].values():
        assert abs(sum(profile.targets.values()) - 1.0) < 1e-9
        assert all(bucket in models["instruments"] for bucket in profile.targets)


@pytest.mark.parametrize(
    "horizon,risk,expected",
    [
        (1, "high", "cautious"),
        (5, "low", "cautious"),
        (5, "medium", "balanced"),
        (5, "high", "balanced"),
        (10, "low", "balanced"),
        (10, "medium", "growth"),
        (20, "high", "growth"),
    ],
)
def test_suggest_profile_is_conservative_and_deterministic(horizon, risk, expected):
    assert suggest_profile(horizon, risk) == expected


def test_suggest_profile_rejects_unknown_risk():
    with pytest.raises(ValueError):
        suggest_profile(10, "yolo")


@pytest.mark.parametrize(
    "monthly,expected",
    [(100, 3), (150, 2), (295, 1), (1000, 1), (10, 12), (24.58, 12), (24.59, 12)],
)
def test_contribution_cadence_pools_until_order_is_economic(monthly, expected):
    # 2.95 EUR / 1% => 295 EUR minimum economic order.
    assert contribution_cadence_months(monthly, FeeModel()) == expected


def test_contribution_cadence_rejects_zero():
    with pytest.raises(ValueError):
        contribution_cadence_months(0, FeeModel())


def test_calendar_marks_contributions_reviews_and_annual_review():
    events = build_calendar(START, months=12, contribution_every=3, review_every=3)
    by_month = {e["month"]: e["actions"] for e in events}
    assert by_month[3] == ["contribute", "review"]
    assert by_month[6] == ["contribute", "review"]
    assert by_month[12] == ["contribute", "annual_review"]
    assert 1 not in by_month and 2 not in by_month
    assert events[0]["date"] == "2026-04-15"


def test_calendar_handles_month_end_dates():
    events = build_calendar(date(2026, 1, 31), months=2, contribution_every=1, review_every=12)
    assert [e["date"] for e in events] == ["2026-02-28", "2026-03-28"]


def test_build_plan_growth_profile_with_initial_orders_and_pooling():
    plan = build_investment_plan(
        cash_now=5000,
        monthly_contribution=100,
        horizon_years=15,
        risk_tolerance="high",
        start_date=START,
    )
    assert plan["profile"] == "growth"
    assert abs(sum(plan["targets"].values()) - 1.0) < 1e-9
    assert plan["contribution"]["every_months"] == 3
    assert plan["contribution"]["pooled_eur"] == 300.0
    assert plan["rules"]["execution"] == "MANUAL_ONLY"
    assert plan["horizon"]["contributions_total_eur"] == 5000 + 100 * 180
    assert "No return" in plan["horizon"]["note"]
    assert all(v["verify_before_use"] for v in plan["instruments"].values())

    orders = plan["initial_orders"]
    assert orders and all(o["side"] == "BUY" for o in orders)
    spent = sum(o["value_eur"] + o["estimated_fee_eur"] for o in orders)
    assert spent + plan["initial_unallocated_cash"] <= 5000 + 0.01
    assert all(o["fee_ratio"] <= 0.01 + 1e-9 for o in orders)


def test_build_plan_small_cash_keeps_unallocated_and_warns():
    plan = build_investment_plan(
        cash_now=200,
        monthly_contribution=10,
        horizon_years=2,
        risk_tolerance="high",
        start_date=START,
    )
    assert plan["profile"] == "cautious"
    # 200 EUR cannot fund any bucket above the 295 EUR minimum economic order.
    assert plan["initial_orders"] == []
    assert plan["initial_unallocated_cash"] == 200
    assert any("minimum economic order" in w for w in plan["warnings"])
    assert plan["contribution"]["every_months"] == 12


@pytest.mark.parametrize("kwargs", [{"cash_now": -1}, {"horizon_years": 0}])
def test_build_plan_rejects_bad_inputs(kwargs):
    base = dict(
        cash_now=1000, monthly_contribution=100, horizon_years=5, risk_tolerance="medium",
        start_date=START,
    )
    base.update(kwargs)
    with pytest.raises(ValueError):
        build_investment_plan(**base)
