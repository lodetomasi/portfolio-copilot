import math

import pytest

from portfolio_copilot.portfolio.rebalance import FeeModel
from portfolio_copilot.portfolio.replacement import (
    propose_replacement,
    propose_sells,
    sell_summary,
    utility,
)

# ---------------------------------------------------------------------------
# utility()
# ---------------------------------------------------------------------------


def test_utility_basic_no_adjustment():
    assert utility(80.0, 1.0) == 80.0


def test_utility_scales_with_confidence():
    assert utility(80.0, 0.5) == 40.0


def test_utility_scales_with_fit_and_thesis_health():
    assert utility(100.0, 1.0, fit=0.5, thesis_health=0.5) == 25.0


def test_utility_risk_penalty_reduces_score():
    assert utility(100.0, 1.0, risk_penalty=0.5) == 50.0


def test_utility_zero_confidence_is_zero():
    assert utility(100.0, 0.0) == 0.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"score": 150.0, "confidence": 1.0},
        {"score": -1.0, "confidence": 1.0},
        {"score": 80.0, "confidence": 1.5},
        {"score": 80.0, "confidence": -0.1},
        {"score": 80.0, "confidence": 1.0, "fit": 2.0},
        {"score": 80.0, "confidence": 1.0, "thesis_health": -0.1},
        {"score": 80.0, "confidence": 1.0, "risk_penalty": 1.1},
        {"score": math.nan, "confidence": 1.0},
    ],
)
def test_utility_rejects_out_of_range_inputs(kwargs):
    with pytest.raises(ValueError):
        utility(**kwargs)


# ---------------------------------------------------------------------------
# propose_replacement()
# ---------------------------------------------------------------------------


def test_hold_when_improvement_below_minimum():
    current = {"symbol": "AAA", "value_eur": 1000.0, "utility": 60.0}
    candidates = [{"symbol": "BBB", "utility": 70.0}]  # only +10, min_improvement is 15
    out = propose_replacement(current, candidates, FeeModel())

    assert out["action"] == "HOLD"
    assert out["sell"] is None
    assert out["buy"] is None
    assert out["fees_eur"] == 0.0
    assert out["utility_improvement"] == 10.0


def test_replace_when_improvement_large_and_fees_fine():
    current = {"symbol": "AAA", "value_eur": 5000.0, "utility": 40.0}
    candidates = [{"symbol": "BBB", "utility": 80.0}]
    fee_model = FeeModel(fixed_fee_eur=2.95, variable_fee_pct=0.0, max_fee_ratio=0.01)

    out = propose_replacement(current, candidates, fee_model)

    assert out["action"] == "REPLACE"
    assert out["sell"]["symbol"] == "AAA"
    assert out["sell"]["side"] == "SELL"
    assert out["buy"]["symbol"] == "BBB"
    assert out["buy"]["side"] == "BUY"
    assert out["fees_eur"] == pytest.approx(5.90, abs=1e-6)
    assert out["utility_improvement"] == 40.0
    # proceeds are conserved: sell value == buy value + both fees
    assert out["buy"]["value_eur"] + out["fees_eur"] == pytest.approx(
        out["sell"]["value_eur"], abs=1e-6
    )


def test_hold_when_roundtrip_fees_too_high():
    current = {"symbol": "AAA", "value_eur": 100.0, "utility": 10.0}
    candidates = [{"symbol": "BBB", "utility": 90.0}]
    # max_fee_ratio is lenient so the *roundtrip* cap (default 0.02) is what trips.
    fee_model = FeeModel(fixed_fee_eur=2.95, variable_fee_pct=0.0, max_fee_ratio=0.5)

    out = propose_replacement(current, candidates, fee_model)

    assert out["action"] == "HOLD"
    assert out["sell"] is None
    assert out["buy"] is None
    assert "fee" in out["reason"].lower()


def test_hold_when_buy_below_minimum_economic_order():
    current = {"symbol": "AAA", "value_eur": 100.0, "utility": 10.0}
    candidates = [{"symbol": "BBB", "utility": 90.0}]
    fee_model = FeeModel(fixed_fee_eur=2.95, variable_fee_pct=0.0, max_fee_ratio=0.01)

    # Loosen the roundtrip cap so the fee-ratio check on the buy leg is the one that fires.
    out = propose_replacement(current, candidates, fee_model, max_roundtrip_fee_ratio=0.5)

    assert out["action"] == "HOLD"
    assert out["sell"] is None
    assert out["buy"] is None
    assert "economic" in out["reason"].lower() or "minimum" in out["reason"].lower()


def test_sell_to_cash_when_utility_far_below_cash():
    current = {"symbol": "AAA", "value_eur": 2000.0, "utility": 20.0}
    fee_model = FeeModel(fixed_fee_eur=2.95, variable_fee_pct=0.0, max_fee_ratio=0.01)

    out = propose_replacement(current, [], fee_model, cash_utility=55.0, min_improvement=15.0)

    assert out["action"] == "SELL_TO_CASH"
    assert out["sell"]["symbol"] == "AAA"
    assert out["sell"]["side"] == "SELL"
    assert out["buy"] is None
    assert out["fees_eur"] == pytest.approx(2.95, abs=1e-6)


def test_sell_to_cash_requires_a_stricter_gap_than_a_plain_rotation():
    # current.utility sits exactly at cash_utility - min_improvement (40): the general
    # improvement check (35 >= 15) would pass, but the cash-specific rule requires a
    # strictly larger gap before giving up all future upside by moving to cash.
    current = {"symbol": "AAA", "value_eur": 2000.0, "utility": 40.0}
    fee_model = FeeModel(fixed_fee_eur=2.95, variable_fee_pct=0.0, max_fee_ratio=0.01)

    out = propose_replacement(current, [], fee_model, cash_utility=55.0, min_improvement=15.0)

    assert out["action"] == "HOLD"


def test_hold_when_current_position_has_no_value():
    current = {"symbol": "AAA", "value_eur": 0.0, "utility": 10.0}
    out = propose_replacement(current, [{"symbol": "BBB", "utility": 90.0}], FeeModel())
    assert out["action"] == "HOLD"
    assert out["sell"] is None


# ---------------------------------------------------------------------------
# propose_sells() / sell_summary()
# ---------------------------------------------------------------------------

TARGETS = {"A": 0.70, "B": 0.20, "C": 0.10}


def test_propose_sells_sells_excess_down_to_target_not_below():
    current_values = {"A": 8000.0, "B": 1500.0, "C": 500.0}  # total 10000
    fee_model = FeeModel(fixed_fee_eur=2.95, variable_fee_pct=0.0, max_fee_ratio=0.01)

    out = propose_sells(
        current_values, TARGETS, fee_model, rebalance_band_abs=0.03, allow_sells=True
    )

    assert len(out) == 1
    order = out[0]
    assert order["symbol"] == "A"
    assert order["side"] == "SELL"
    assert order["value_eur"] == 1000.0  # 8000 - 7000 target, not below target


def test_propose_sells_never_sells_underweight_or_in_band_buckets():
    current_values = {"A": 8000.0, "B": 1500.0, "C": 500.0}
    fee_model = FeeModel(fixed_fee_eur=2.95, variable_fee_pct=0.0, max_fee_ratio=0.01)

    out = propose_sells(
        current_values, TARGETS, fee_model, rebalance_band_abs=0.03, allow_sells=True
    )

    symbols_sold = {o["symbol"] for o in out}
    assert "B" not in symbols_sold  # underweight (1500 < 2000 target)
    assert "C" not in symbols_sold  # underweight (500 < 1000 target)


def test_propose_sells_empty_when_allow_sells_false():
    current_values = {"A": 8000.0, "B": 1500.0, "C": 500.0}
    fee_model = FeeModel(fixed_fee_eur=2.95, variable_fee_pct=0.0, max_fee_ratio=0.01)

    out = propose_sells(
        current_values, TARGETS, fee_model, rebalance_band_abs=0.03, allow_sells=False
    )

    assert out == []


def test_propose_sells_skips_uneconomic_orders():
    # A is overweight (0.735 > 0.70 + 0.03) but the excess (35) is far below the
    # fee model's minimum economic order (295), so no order should be proposed at all.
    current_values = {"A": 735.0, "B": 200.0, "C": 65.0}  # total 1000
    fee_model = FeeModel(fixed_fee_eur=2.95, variable_fee_pct=0.0, max_fee_ratio=0.01)

    out = propose_sells(
        current_values, TARGETS, fee_model, rebalance_band_abs=0.03, allow_sells=True
    )

    assert out == []


def test_propose_sells_respects_band_width():
    # A is at 0.72, inside a 0.03 band around 0.70 -> no sell. Widen the band and it stays
    # inside; narrow it and it becomes a sell.
    current_values = {"A": 7200.0, "B": 2000.0, "C": 800.0}  # total 10000
    fee_model = FeeModel(fixed_fee_eur=2.95, variable_fee_pct=0.0, max_fee_ratio=0.05)

    inside_band = propose_sells(
        current_values, TARGETS, fee_model, rebalance_band_abs=0.03, allow_sells=True
    )
    assert inside_band == []

    outside_band = propose_sells(
        current_values, TARGETS, fee_model, rebalance_band_abs=0.01, allow_sells=True
    )
    assert len(outside_band) == 1
    assert outside_band[0]["symbol"] == "A"


def test_sell_summary_reports_suppressed_count_when_sells_disabled():
    current_values = {"A": 8000.0, "B": 1500.0, "C": 500.0}
    fee_model = FeeModel(fixed_fee_eur=2.95, variable_fee_pct=0.0, max_fee_ratio=0.01)

    suppressed = sell_summary(
        current_values, TARGETS, fee_model, rebalance_band_abs=0.03, allow_sells=False
    )
    assert suppressed["orders"] == []
    assert suppressed["candidate_count"] == 1
    assert suppressed["suppressed_count"] == 1

    allowed = sell_summary(
        current_values, TARGETS, fee_model, rebalance_band_abs=0.03, allow_sells=True
    )
    assert len(allowed["orders"]) == 1
    assert allowed["candidate_count"] == 1
    assert allowed["suppressed_count"] == 0


def test_propose_sells_rejects_invalid_targets():
    with pytest.raises(ValueError):
        propose_sells(
            current_values={"A": 100.0},
            targets={"A": 0.5},
            fee_model=FeeModel(),
            allow_sells=True,
        )


def test_propose_sells_rejects_negative_cash():
    with pytest.raises(ValueError):
        propose_sells(
            current_values={"A": 100.0},
            targets={"A": 1.0},
            fee_model=FeeModel(),
            allow_sells=True,
            cash_eur=-5.0,
        )


# ---------------------------------------------------------------------------
# finding 6: buy-leg fee gate and reported fee_ratio must use the same basis
# ---------------------------------------------------------------------------


def test_replace_buy_leg_rejected_when_true_fee_ratio_would_exceed_the_cap():
    fee_model = FeeModel(fixed_fee_eur=2.95, variable_fee_pct=0.005, max_fee_ratio=0.01)
    current = {"symbol": "AAA", "value_eur": 601.89, "utility": 10.0}
    candidates = [{"symbol": "BBB", "utility": 90.0}]
    out = propose_replacement(current, candidates, fee_model, max_roundtrip_fee_ratio=1.0)
    # Previously this admitted a buy order whose OWN fee_ratio (0.01005) already exceeded
    # max_fee_ratio (0.01) -- the tool must never approve an order violating its own cap.
    assert out["action"] == "HOLD"
    assert out["buy"] is None


@pytest.mark.parametrize("sell_value", [500.0, 601.89, 1_000.0, 2_500.0, 10_000.0])
def test_replace_buy_leg_fee_ratio_never_exceeds_cap_when_replace_happens(sell_value):
    fee_model = FeeModel(fixed_fee_eur=2.95, variable_fee_pct=0.005, max_fee_ratio=0.01)
    current = {"symbol": "AAA", "value_eur": sell_value, "utility": 10.0}
    candidates = [{"symbol": "BBB", "utility": 90.0}]
    out = propose_replacement(current, candidates, fee_model, max_roundtrip_fee_ratio=1.0)
    if out["action"] == "REPLACE":
        assert out["buy"]["fee_ratio"] <= fee_model.max_fee_ratio + 1e-9


# ---------------------------------------------------------------------------
# finding 8: a real candidate ticker literally named "CASH" must not be
# swallowed by the internal cash sentinel
# ---------------------------------------------------------------------------


def test_real_candidate_named_cash_is_not_confused_with_the_cash_sentinel():
    fee_model = FeeModel()
    current = {"symbol": "AAA", "value_eur": 5000.0, "utility": 20.0}
    candidates = [{"symbol": "CASH", "utility": 90.0}]  # real ticker, e.g. Pathward Financial
    out = propose_replacement(
        current, candidates, fee_model, cash_utility=55.0, min_improvement=15.0
    )
    assert out["action"] == "REPLACE"
    assert out["buy"] is not None
    assert out["buy"]["symbol"] == "CASH"
    assert "CASH" in out["reason"]


# ---------------------------------------------------------------------------
# finding 9: a candidate sharing current's symbol must never trigger a wash trade
# ---------------------------------------------------------------------------


def test_candidate_matching_current_symbol_never_produces_a_wash_trade():
    fee_model = FeeModel()
    current = {"symbol": "AAA", "value_eur": 5000.0, "utility": 40.0}
    candidates = [{"symbol": "AAA", "utility": 80.0}]  # same ticker as current
    out = propose_replacement(current, candidates, fee_model)
    assert out["action"] == "HOLD"
    assert out["sell"] is None
    assert out["buy"] is None


def test_candidate_matching_current_symbol_case_insensitive_still_ignored():
    fee_model = FeeModel()
    current = {"symbol": "AAA", "value_eur": 5000.0, "utility": 40.0}
    candidates = [{"symbol": "aaa", "utility": 80.0}]
    out = propose_replacement(current, candidates, fee_model)
    assert out["action"] == "HOLD"
