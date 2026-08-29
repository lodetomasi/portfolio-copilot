"""Edge-case and property-based tests for the cash allocator (FeeModel + allocate_cash_to_targets).

Scope: portfolio_copilot.portfolio.rebalance. Every test documents *current, intended*
behaviour per CLAUDE.md ("compra asset sottopeso", "evitare micro-ordini antieconomici",
"HOLD/WAIT/NO BUY sono risultati validi") and docs/FINANCIAL_LOGIC.md sections 9-10
(rebalancing waterfall, fee efficiency, minimum economic order). All fixtures are
synthetic; the suite is fully offline and deterministic (numpy default_rng with fixed
seeds for the property test).
"""

from __future__ import annotations

import numpy as np
import pytest

from portfolio_copilot.portfolio.rebalance import FeeModel, allocate_cash_to_targets


def test_commissions_exceed_cash_no_order_generated():
    """Fixed fee (50) bigger than available cash (40): nothing is economic, ever.

    FINANCIAL_LOGIC.md #10: min_order ~= fixed_fee / max_fee_ratio. With fixed_fee=50 the
    minimum economic order value is 5000 EUR, far above the 40 EUR of cash on hand, so the
    allocator must not manufacture a loss-making micro-order (CLAUDE.md #8).
    """
    fee_model = FeeModel(fixed_fee_eur=50.0, variable_fee_pct=0.0, max_fee_ratio=0.01)
    assert fee_model.minimum_economic_order == pytest.approx(5000.0)

    out = allocate_cash_to_targets(
        current_values={"A": 0.0},
        targets={"A": 1.0},
        cash_eur=40.0,
        fee_model=fee_model,
    )
    assert out["orders"] == []
    assert out["unallocated_cash"] == pytest.approx(40.0)


def test_infinite_minimum_order_when_variable_fee_at_or_above_cap():
    """max_fee_ratio <= variable_fee_pct: fee_ratio can never clear the cap, so the
    minimum economic order is infinite and no amount of cash ever produces an order.
    """
    fee_model = FeeModel(fixed_fee_eur=2.95, variable_fee_pct=0.02, max_fee_ratio=0.01)
    assert fee_model.minimum_economic_order == float("inf")
    assert fee_model.is_economic(1_000_000.0) is False

    out = allocate_cash_to_targets(
        current_values={"A": 0.0},
        targets={"A": 1.0},
        cash_eur=1_000_000.0,
        fee_model=fee_model,
    )
    assert out["orders"] == []
    assert out["unallocated_cash"] == pytest.approx(1_000_000.0)


def test_zero_weight_bucket_never_receives_orders():
    """A 0-weight target bucket is a valid target (validate_targets only rejects negative
    weights). Its deficit is always <= 0, so it never appears in the waterfall, and any
    pre-existing position in it is left untouched -- the allocator never sells
    (CLAUDE.md #9: "vendi solo se drift/rischio supera soglia o tesi è cambiata").
    """
    out = allocate_cash_to_targets(
        current_values={"A": 500.0, "B": 100.0},
        targets={"A": 1.0, "B": 0.0},
        cash_eur=500.0,
        fee_model=FeeModel(fixed_fee_eur=2.95, max_fee_ratio=0.01),
        rebalance_band_abs=0.03,
    )
    bought = {o["symbol"] for o in out["orders"]}
    assert "B" not in bought
    assert out["target_values"]["B"] == pytest.approx(0.0)


def test_current_values_with_symbols_outside_targets_are_counted_but_not_ordered():
    """A holding that is not a rebalancing target (e.g. a legacy position) still
    contributes to the portfolio total used to size target values, but it can never
    receive -- or block -- an order because the waterfall only iterates over `targets`.
    """
    out = allocate_cash_to_targets(
        current_values={"A": 500.0, "ZZZ": 300.0},
        targets={"A": 1.0},
        cash_eur=500.0,
        fee_model=FeeModel(fixed_fee_eur=2.95, max_fee_ratio=0.01),
    )
    # final_total = (500 + 300) + 500 = 1300, all of it targeted at A.
    assert out["target_values"] == {"A": pytest.approx(1300.0)}
    assert "ZZZ" not in out["target_values"]
    symbols_ordered = {o["symbol"] for o in out["orders"]}
    assert symbols_ordered <= {"A"}


def test_negative_current_values_do_not_break_safety_invariants():
    """A negative current value (e.g. a data glitch upstream) is not validated away, but
    the allocator's hard safety invariants must still hold: it never spends more cash
    than it was given, unallocated_cash never goes negative, and the portfolio total used
    to size targets floors each position at 0 (a debt does not inflate available total).
    """
    out = allocate_cash_to_targets(
        current_values={"A": -500.0, "B": 500.0},
        targets={"A": 0.5, "B": 0.5},
        cash_eur=1000.0,
        fee_model=FeeModel(fixed_fee_eur=2.95, max_fee_ratio=0.01),
        rebalance_band_abs=0.03,
    )
    # current_total floors A's contribution at 0: (0 + 500) + 1000 = 1500.
    assert out["target_values"] == {"A": pytest.approx(750.0), "B": pytest.approx(750.0)}
    total_spent = sum(o["value_eur"] + o["estimated_fee_eur"] for o in out["orders"])
    assert total_spent <= 1000.0 + 0.01
    assert out["unallocated_cash"] >= 0.0
    # No order is generated for a symbol currently in debt at more than double its final
    # target value; deficits are floored at 0 relative to raw (unfloored) current value.
    for order in out["orders"]:
        assert order["value_eur"] > 0.0


def test_cash_exactly_at_minimum_order_produces_no_order():
    """Cash equal to the *order-value* threshold (fixed_fee / max_fee_ratio) is not
    enough: the allocator must still carve the fee out of that same cash pool, so the
    resulting order value falls just under the threshold and fails is_economic.
    """
    fee_model = FeeModel(fixed_fee_eur=2.95, max_fee_ratio=0.01)
    minimum = fee_model.minimum_economic_order
    assert minimum == pytest.approx(295.0)

    out = allocate_cash_to_targets(
        current_values={"A": 0.0},
        targets={"A": 1.0},
        cash_eur=minimum,
        fee_model=fee_model,
    )
    assert out["orders"] == []
    assert out["unallocated_cash"] == pytest.approx(minimum)


def test_cash_exactly_at_minimum_order_plus_fee_produces_full_order():
    """Cash equal to minimum_economic_order + fixed_fee is exactly enough to place one
    order at the minimum economic size, spending all of it and landing the fee_ratio
    exactly on the cap.
    """
    fee_model = FeeModel(fixed_fee_eur=2.95, max_fee_ratio=0.01)
    cash = fee_model.minimum_economic_order + fee_model.fixed_fee_eur

    out = allocate_cash_to_targets(
        current_values={"A": 0.0},
        targets={"A": 1.0},
        cash_eur=cash,
        fee_model=fee_model,
    )
    assert len(out["orders"]) == 1
    order = out["orders"][0]
    assert order["value_eur"] == pytest.approx(295.0)
    assert order["estimated_fee_eur"] == pytest.approx(2.95)
    assert order["fee_ratio"] == pytest.approx(0.01)
    assert out["unallocated_cash"] == pytest.approx(0.0)


def test_huge_cash_precision():
    """A 1e9 EUR contribution must still be split and rounded to the cent without
    leaking or fabricating money: spend + unallocated reconciles exactly to the input.
    """
    fee_model = FeeModel(fixed_fee_eur=2.95, max_fee_ratio=0.01)
    out = allocate_cash_to_targets(
        current_values={"A": 1000.0, "B": 1000.0},
        targets={"A": 0.5, "B": 0.5},
        cash_eur=1_000_000_000.0,
        fee_model=fee_model,
        rebalance_band_abs=0.03,
    )
    total_spent = sum(o["value_eur"] + o["estimated_fee_eur"] for o in out["orders"])
    assert total_spent + out["unallocated_cash"] == pytest.approx(1_000_000_000.0, abs=0.01)
    assert out["unallocated_cash"] == pytest.approx(0.0, abs=0.01)
    for order in out["orders"]:
        assert order["fee_ratio"] <= fee_model.max_fee_ratio + 1e-9


def test_zero_band_only_buys_positions_still_at_zero():
    """rebalance_band_abs=0.0: a portfolio already sitting exactly on target has drift 0,
    which satisfies `abs(drift) <= 0`, so its deficit is zeroed and the (small,
    uneconomic) leftover cash stays unallocated rather than forcing a trade.
    """
    out = allocate_cash_to_targets(
        current_values={"A": 500.0, "B": 500.0},
        targets={"A": 0.5, "B": 0.5},
        cash_eur=100.0,
        fee_model=FeeModel(fixed_fee_eur=2.95, max_fee_ratio=0.01),
        rebalance_band_abs=0.0,
    )
    assert out["orders"] == []
    assert out["unallocated_cash"] == pytest.approx(100.0)


def test_band_of_one_swallows_every_deficit():
    """rebalance_band_abs=1.0 (100%): no drift can ever exceed the band, so pass 1 never
    fires regardless of how underweight a bucket is, and small leftover cash pass 2
    requires still is not met -- everything stays unallocated.
    """
    out = allocate_cash_to_targets(
        current_values={"A": 900.0, "B": 100.0},
        targets={"A": 0.5, "B": 0.5},
        cash_eur=100.0,
        fee_model=FeeModel(fixed_fee_eur=2.95, max_fee_ratio=0.01),
        rebalance_band_abs=1.0,
    )
    assert out["orders"] == []
    assert out["unallocated_cash"] == pytest.approx(100.0)


@pytest.mark.parametrize("epsilon", [1e-7, -1e-7])
def test_targets_sum_within_1e7_tolerance_does_not_raise(epsilon):
    """validate_targets() uses a 1e-6 default tolerance; a sum off by 1e-7 in either
    direction is well inside it and must not raise.
    """
    targets = {"A": 0.5 + epsilon, "B": 0.5 - epsilon}
    out = allocate_cash_to_targets(
        current_values={"A": 500.0},
        targets=targets,
        cash_eur=100.0,
    )
    assert out["target_values"]["A"] == pytest.approx(600.0 * targets["A"])


def _random_scenario(seed: int) -> dict:
    """Build one synthetic, non-negative allocation scenario from a seeded RNG."""
    rng = np.random.default_rng(seed)
    n_buckets = int(rng.integers(2, 6))
    symbols = [f"S{i}" for i in range(n_buckets)]
    raw_weights = rng.random(n_buckets) + 0.01
    weights = raw_weights / raw_weights.sum()
    return {
        "symbols": symbols,
        "targets": dict(zip(symbols, weights.tolist(), strict=True)),
        "current_values": {s: float(rng.uniform(0.0, 5000.0)) for s in symbols},
        "cash_eur": float(rng.uniform(0.0, 20_000.0)),
        "band": float(rng.uniform(0.0, 0.1)),
        "fee_model": FeeModel(
            fixed_fee_eur=float(rng.uniform(0.5, 10.0)),
            variable_fee_pct=float(rng.uniform(0.0, 0.005)),
            max_fee_ratio=float(rng.uniform(0.005, 0.03)),
        ),
    }


@pytest.mark.parametrize("seed", range(200))
def test_property_top_up_never_exceeds_target_plus_band(seed):
    """Across 200 seeded random scenarios: every bucket the allocator actually buys into
    ends up at or under target_weight + band (FINANCIAL_LOGIC.md #9 / rebalance.py's pass
    2 docstring: "without pushing it beyond target + band"). This deliberately excludes
    buckets the allocator never touches -- a pre-existing overweight position it
    correctly leaves alone (it never sells) is not a violation of this invariant.
    """
    scenario = _random_scenario(seed)
    out = allocate_cash_to_targets(
        current_values=scenario["current_values"],
        targets=scenario["targets"],
        cash_eur=scenario["cash_eur"],
        fee_model=scenario["fee_model"],
        rebalance_band_abs=scenario["band"],
    )

    bought: dict[str, float] = dict.fromkeys(scenario["symbols"], 0.0)
    for order in out["orders"]:
        bought[order["symbol"]] += order["value_eur"]

    final_total = sum(scenario["current_values"].values()) + scenario["cash_eur"]
    assert final_total > 0
    for symbol in scenario["symbols"]:
        if bought[symbol] <= 0.0:
            continue
        final_value = scenario["current_values"][symbol] + bought[symbol]
        weight = final_value / final_total
        tolerance = max(1e-9, 0.02 / final_total)  # sub-cent rounding slack
        assert weight <= scenario["targets"][symbol] + scenario["band"] + tolerance

    total_spent = sum(o["value_eur"] + o["estimated_fee_eur"] for o in out["orders"])
    assert total_spent <= scenario["cash_eur"] + 0.01
    assert out["unallocated_cash"] >= -1e-9


@pytest.mark.parametrize("seed", range(200))
def test_property_every_order_fee_matches_value_times_fee_ratio_within_one_cent(seed):
    """For every order the allocator returns, value_eur * fee_ratio must reconstruct
    estimated_fee_eur to within a cent -- callers (portfolio/plan.py, order display) rely
    on fee_ratio being derived consistently from the reported value/fee pair.
    """
    scenario = _random_scenario(seed)
    out = allocate_cash_to_targets(
        current_values=scenario["current_values"],
        targets=scenario["targets"],
        cash_eur=scenario["cash_eur"],
        fee_model=scenario["fee_model"],
        rebalance_band_abs=scenario["band"],
    )
    for order in out["orders"]:
        reconstructed_fee = order["value_eur"] * order["fee_ratio"]
        assert reconstructed_fee == pytest.approx(order["estimated_fee_eur"], abs=0.01)
        assert order["fee_ratio"] <= scenario["fee_model"].max_fee_ratio + 1e-9
