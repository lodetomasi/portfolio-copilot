import pytest

from portfolio_copilot.portfolio.rebalance import FeeModel, allocate_cash_to_targets


def test_fee_minimum_economic_order():
    model = FeeModel(fixed_fee_eur=2.95, max_fee_ratio=0.01)
    assert round(model.minimum_economic_order, 2) == 295.00
    assert model.is_economic(100) is False
    assert model.is_economic(300) is True


def test_targets_must_sum_to_one():
    with pytest.raises(ValueError):
        allocate_cash_to_targets(
            current_values={"A": 100},
            targets={"A": 0.8},
            cash_eur=100,
        )


def test_cash_never_negative():
    out = allocate_cash_to_targets(
        current_values={"A": 800, "B": 100, "C": 100},
        targets={"A": 0.70, "B": 0.20, "C": 0.10},
        cash_eur=400,
        fee_model=FeeModel(fixed_fee_eur=2.95, max_fee_ratio=0.02),
        rebalance_band_abs=0.01,
    )
    assert out["unallocated_cash"] >= 0
    assert sum(o["value_eur"] + o["estimated_fee_eur"] for o in out["orders"]) <= 400.01


def test_no_action_inside_band():
    out = allocate_cash_to_targets(
        current_values={"A": 800, "B": 150, "C": 50},
        targets={"A": 0.80, "B": 0.15, "C": 0.05},
        cash_eur=0,
        fee_model=FeeModel(),
        rebalance_band_abs=0.03,
    )
    assert out["orders"] == []


def test_waterfall_fills_largest_deficit_first_and_never_splits_below_minimum():
    # 400 EUR of cash on a portfolio already at target: a proportional split (240/120/40)
    # would generate nothing economic. The waterfall must invest it in one economic order.
    out = allocate_cash_to_targets(
        current_values={"A": 6000, "B": 3000, "C": 1000},
        targets={"A": 0.6, "B": 0.3, "C": 0.1},
        cash_eur=400,
        fee_model=FeeModel(fixed_fee_eur=2.95, max_fee_ratio=0.01),
        rebalance_band_abs=0.03,
    )
    assert len(out["orders"]) == 1
    order = out["orders"][0]
    assert order["symbol"] == "A"
    assert order["value_eur"] + order["estimated_fee_eur"] <= 400
    assert order["fee_ratio"] <= 0.01
    assert out["unallocated_cash"] < 2.95 + 0.01
    # A stays within target + band after the buy.
    assert (6000 + order["value_eur"]) / 10400 <= 0.6 + 0.03 + 1e-9


def test_top_up_never_pushes_a_bucket_beyond_band():
    # A is overweight even after counting the new cash (2000/2600 = 77% vs 50%): never buy it.
    out = allocate_cash_to_targets(
        current_values={"A": 2000, "B": 100},
        targets={"A": 0.5, "B": 0.5},
        cash_eur=500,
        fee_model=FeeModel(fixed_fee_eur=2.95, max_fee_ratio=0.01),
        rebalance_band_abs=0.03,
    )
    final_total = 2600
    bought = {o["symbol"]: o["value_eur"] for o in out["orders"]}
    assert "A" not in bought
    assert (100 + bought["B"]) / final_total <= 0.5 + 0.03 + 1e-9
    assert out["unallocated_cash"] >= 0


def test_zero_position_bucket_at_or_below_band_is_not_starved():
    # "s1" and "s2" are brand-new satellite buckets that hold nothing yet, with target
    # weights at/under the 3% band. Both are 100% underweight (deficit == full target
    # value) and must stay eligible for pass 1's waterfall -- being unfunded so far is
    # not "already on target", it is the definition of needing the first contribution.
    # Today the in-band skip zeroes their deficit purely because a 0/0 current weight
    # happens to fall within `rebalance_band_abs` of a small target, so only the biggest
    # newcomer ("s1") gets swept up by the pass-2 top-up (which can overshoot into the
    # band) while "s2" is left with literally nothing.
    out = allocate_cash_to_targets(
        current_values={"rest": 95000, "s1": 0, "s2": 0},
        targets={"rest": 0.95, "s1": 0.03, "s2": 0.02},
        cash_eur=8500,
        fee_model=FeeModel(fixed_fee_eur=2.95, max_fee_ratio=0.01),
        rebalance_band_abs=0.03,
    )
    bought = {o["symbol"]: o["value_eur"] for o in out["orders"]}
    assert bought.get("s2", 0.0) > 0.0
    # s2's deficit equals its full target value (2070 EUR); it should be funded close to
    # that, not just handed an uneconomic scrap.
    assert bought.get("s2", 0.0) >= 2000.0
    assert out["unallocated_cash"] >= 0


def test_returned_fee_ratio_never_exceeds_cap_after_cent_rounding():
    # is_economic() gates on the unrounded fee/value ratio, but the order actually handed
    # back to the caller reports fee_ratio computed from the *rounded* fee (rebalance.py
    # rounds fee to the nearest cent). With a variable fee component, rounding the fee up
    # can push the reported ratio above max_fee_ratio even though the unrounded check
    # passed -- silently breaching the documented cap on the object callers rely on.
    fee_model = FeeModel(fixed_fee_eur=1.22, variable_fee_pct=0.0072, max_fee_ratio=0.0093)
    out = allocate_cash_to_targets(
        current_values={"A": 2348.24, "B": 1481.16},
        targets={"A": 0.5, "B": 0.5},
        cash_eur=2064.91,
        fee_model=fee_model,
        rebalance_band_abs=0.03,
    )
    assert out["orders"], "expected at least one order to be generated"
    for order in out["orders"]:
        assert order["fee_ratio"] <= fee_model.max_fee_ratio + 1e-9
