import numpy as np
import pytest

from portfolio_copilot.portfolio.auction import Candidate, capital_auction, marginal_utility
from portfolio_copilot.portfolio.rebalance import FeeModel


def _stock(symbol, edge, confidence, current_weight=0.0, cap_weight=1.0, **kw):
    return Candidate(
        symbol=symbol,
        kind="stock",
        edge=edge,
        confidence=confidence,
        current_weight=current_weight,
        cap_weight=cap_weight,
        **kw,
    )


def _bucket(symbol, edge, confidence, deficit_eur, current_weight=0.0, cap_weight=1.0, **kw):
    return Candidate(
        symbol=symbol,
        kind="bucket",
        edge=edge,
        confidence=confidence,
        deficit_eur=deficit_eur,
        current_weight=current_weight,
        cap_weight=cap_weight,
        **kw,
    )


def test_ranking_order_is_descending_by_utility():
    a = _stock("A", edge=0.9, confidence=0.9, risk=0.1)  # base 72.9
    b = _stock("B", edge=0.5, confidence=0.8)  # base 40
    c = _bucket("C", edge=0.5, confidence=1.0, deficit_eur=0.0)  # base 50, no bonus

    out = capital_auction(
        cash_eur=1000,
        candidates=[b, c, a],
        fee_model=FeeModel(),
        total_value_eur=100_000,
    )
    assert [row["symbol"] for row in out["ranking"]] == ["A", "C", "B"]
    assert out["ranking"][0]["kind"] == "stock"


def test_no_buy_when_all_utilities_at_or_below_cash_utility():
    b = _bucket("B", edge=0.5, confidence=1.0, deficit_eur=0.0)  # base 50
    s = _stock("S", edge=0.5, confidence=0.8)  # base 40

    out = capital_auction(
        cash_eur=5000,
        candidates=[b, s],
        fee_model=FeeModel(),
        total_value_eur=100_000,
    )
    assert out["decision"] == "NO_BUY"
    assert out["orders"] == []
    assert out["cash_kept_eur"] == 5000
    assert out["reasons"]


def test_cap_weight_is_never_exceeded():
    d = _stock("D", edge=1.0, confidence=1.0, current_weight=0.05, cap_weight=0.06)
    out = capital_auction(
        cash_eur=100_000,
        candidates=[d],
        fee_model=FeeModel(),
        total_value_eur=100_000,
    )
    assert out["decision"] == "BUY"
    order = out["orders"][0]
    final_total = 200_000
    final_weight = (0.05 * 100_000 + order["value_eur"]) / final_total
    assert final_weight <= 0.06 + 1e-9
    assert order["value_eur"] == pytest.approx(7000.0, abs=0.01)


def test_minimum_economic_order_is_respected():
    # deficit of 50 EUR is far below the ~295 EUR minimum economic order for the default
    # fee model: the auction must skip it rather than fire an antieconomic micro-order.
    e = _bucket("E", edge=1.0, confidence=1.0, deficit_eur=50.0)
    out = capital_auction(
        cash_eur=10_000,
        candidates=[e],
        fee_model=FeeModel(fixed_fee_eur=2.95, max_fee_ratio=0.01),
        total_value_eur=100_000,
    )
    assert out["orders"] == []
    assert out["decision"] == "NO_BUY"
    assert any("economic" in r for r in out["reasons"])


def test_deficit_bonus_lets_underweight_bucket_beat_a_better_stock():
    # Without the deficit bonus, G (base 64.8) ranks above F (base 58.5). With the bonus for
    # being 50% underweight (+10), F (68.5) must overtake G.
    f = _bucket("F", edge=0.65, confidence=0.9, deficit_eur=50_000)
    g = _stock("G", edge=0.72, confidence=0.9)

    out = capital_auction(
        cash_eur=200_000,
        candidates=[f, g],
        fee_model=FeeModel(),
        total_value_eur=100_000,
    )
    utilities = {row["symbol"]: row["utility"] for row in out["ranking"]}
    assert utilities["F"] > utilities["G"]
    assert out["ranking"][0]["symbol"] == "F"
    assert out["orders"][0]["symbol"] == "F"


def test_low_confidence_stock_is_never_bought():
    h = _stock("H", edge=1.0, confidence=0.3)  # below the 0.5 floor
    i = _stock("I", edge=0.9, confidence=0.9)

    out = capital_auction(
        cash_eur=50_000,
        candidates=[h, i],
        fee_model=FeeModel(),
        total_value_eur=100_000,
    )
    utilities = {row["symbol"]: row["utility"] for row in out["ranking"]}
    assert utilities["H"] == 0.0
    assert "H" not in {o["symbol"] for o in out["orders"]}
    assert "I" in {o["symbol"] for o in out["orders"]}
    assert any("H" in r and "confidence" in r for r in out["reasons"])


def test_marginal_utility_forces_zero_for_low_confidence_stock_directly():
    h = _stock("H", edge=1.0, confidence=0.49)
    assert marginal_utility(h, total_value_eur=100_000) == 0.0


def test_cash_kind_candidate_never_receives_an_order():
    cash_candidate = Candidate(
        symbol="CASH", kind="cash", edge=1.0, confidence=1.0, current_weight=0.0
    )
    stock = _stock("Z", edge=0.9, confidence=0.9)
    out = capital_auction(
        cash_eur=50_000,
        candidates=[cash_candidate, stock],
        fee_model=FeeModel(),
        total_value_eur=100_000,
    )
    assert "CASH" not in {o["symbol"] for o in out["orders"]}
    cash_row = next(row for row in out["ranking"] if row["symbol"] == "CASH")
    assert cash_row["utility"] == 55.0


def test_negative_cash_raises():
    with pytest.raises(ValueError):
        capital_auction(
            cash_eur=-1,
            candidates=[_stock("A", edge=0.9, confidence=0.9)],
            fee_model=FeeModel(),
            total_value_eur=100_000,
        )


def test_determinism():
    candidates = [
        _stock("A", edge=0.9, confidence=0.9, risk=0.1),
        _bucket("F", edge=0.65, confidence=0.9, deficit_eur=50_000),
        _stock("H", edge=1.0, confidence=0.3),
    ]
    kwargs = dict(cash_eur=75_000, fee_model=FeeModel(), total_value_eur=100_000)
    out1 = capital_auction(candidates=candidates, **kwargs)
    out2 = capital_auction(candidates=candidates, **kwargs)
    assert out1 == out2


def test_random_scenarios_invariants():
    rng = np.random.default_rng(1234)
    fee_model = FeeModel(fixed_fee_eur=2.95, variable_fee_pct=0.0, max_fee_ratio=0.01)

    for _ in range(100):
        total_value_eur = float(rng.uniform(1_000, 200_000))
        cash_eur = float(rng.uniform(0, 50_000))
        n = int(rng.integers(1, 6))

        candidates: list[Candidate] = []
        for i in range(n):
            kind = rng.choice(["bucket", "stock", "cash"], p=[0.4, 0.5, 0.1])
            current_weight = float(rng.uniform(0, 1))
            cap_weight = float(rng.uniform(0, 1))
            deficit_eur = float(rng.uniform(0, total_value_eur)) if kind == "bucket" else 0.0
            candidates.append(
                Candidate(
                    symbol=f"C{i}",
                    kind=kind,
                    edge=float(rng.uniform(0, 1)),
                    confidence=float(rng.uniform(0, 1)),
                    thesis_health=float(rng.uniform(0, 1)),
                    fit=float(rng.uniform(0, 1)),
                    risk=float(rng.uniform(0, 1)),
                    current_weight=current_weight,
                    cap_weight=cap_weight,
                    deficit_eur=deficit_eur,
                )
            )

        out = capital_auction(
            cash_eur=cash_eur,
            candidates=candidates,
            fee_model=fee_model,
            total_value_eur=total_value_eur,
        )

        assert out["cash_kept_eur"] >= 0
        spent = sum(o["value_eur"] + o["fee_eur"] for o in out["orders"])
        assert spent <= cash_eur + 1e-6

        by_symbol = {c.symbol: c for c in candidates}
        final_total = total_value_eur + cash_eur
        for order in out["orders"]:
            c = by_symbol[order["symbol"]]
            assert c.kind != "cash"
            current_value = c.current_weight * total_value_eur
            final_weight = (current_value + order["value_eur"]) / final_total
            assert final_weight <= c.cap_weight + 1e-4
            if c.kind == "bucket":
                assert order["value_eur"] <= c.deficit_eur + 1e-6

        assert out["decision"] == ("BUY" if out["orders"] else "NO_BUY")


# ---------------------------------------------------------------------------
# finding 20: a bucket's deficit bonus must scale against its OWN target value,
# not the entire portfolio's total value
# ---------------------------------------------------------------------------


def test_marginal_utility_bucket_bonus_uses_own_target_as_denominator():
    # bonds: target weight 20% of the portfolio, currently completely unfunded (0%) --
    # that is 100% underweight relative to ITS OWN target, so it deserves the full bonus,
    # not a bonus scaled by deficit-over-total-portfolio (which would only give 20%).
    bonds = _bucket("bonds", edge=0.5, confidence=1.0, deficit_eur=20_000.0, current_weight=0.0)
    utility = marginal_utility(bonds, total_value_eur=100_000.0)
    assert utility == pytest.approx(70.0)  # base 50 + full 20-point bonus


def test_fully_empty_bucket_clears_the_buy_threshold_with_cash_sized_for_its_own_gap():
    bonds = _bucket("bonds", edge=0.5, confidence=1.0, deficit_eur=20_000.0, current_weight=0.0)
    out = capital_auction(
        cash_eur=20_000.0,
        candidates=[bonds],
        fee_model=FeeModel(),
        total_value_eur=100_000.0,
    )
    assert out["decision"] == "BUY"
    assert out["orders"]


def test_partially_funded_bucket_gets_a_proportionally_smaller_bonus():
    # Half-funded relative to its own 20,000 EUR target (10,000 already held, 10,000
    # deficit) -> bonus should be half of the max (10 points), not a token amount.
    half_funded = _bucket(
        "bonds", edge=0.5, confidence=1.0, deficit_eur=10_000.0, current_weight=0.10
    )
    utility = marginal_utility(half_funded, total_value_eur=100_000.0)
    assert utility == pytest.approx(60.0)  # base 50 + 10-point (50%) bonus


# ---------------------------------------------------------------------------
# finding 22: the same symbol appearing as two Candidate rows must never be
# jointly awarded more than cap_weight in total
# ---------------------------------------------------------------------------


def test_duplicate_symbol_candidates_cannot_jointly_exceed_cap_weight():
    a1 = _stock("AAPL", edge=0.95, confidence=0.95, cap_weight=0.05)
    a2 = _stock("AAPL", edge=0.90, confidence=0.90, cap_weight=0.05)
    out = capital_auction(
        cash_eur=50_000,
        candidates=[a1, a2],
        fee_model=FeeModel(),
        total_value_eur=100_000.0,
    )
    combined = sum(o["value_eur"] for o in out["orders"] if o["symbol"] == "AAPL")
    combined_weight = combined / 150_000.0
    assert combined_weight <= 0.05 + 1e-6


# ---------------------------------------------------------------------------
# finding 24: _size_order's retry branch must never spend more than remaining_cash
# ---------------------------------------------------------------------------


def test_size_order_retry_branch_never_overspends_remaining_cash():
    from portfolio_copilot.portfolio.auction import _size_order

    fee_model = FeeModel(
        fixed_fee_eur=1.33736451524762,
        variable_fee_pct=0.0009227644501443555,
        max_fee_ratio=0.03527730995161153,
    )
    result = _size_order(
        fee_model, cap_eur=3289.608768848793, remaining_cash=242.02500066771105
    )
    assert result is not None
    value, fee = result
    assert value + fee <= 242.02500066771105 + 1e-9


def test_capital_auction_never_overspends_cash_with_realistic_variable_fee():
    fee_model = FeeModel(fixed_fee_eur=1.34, variable_fee_pct=0.0009, max_fee_ratio=0.035)
    stock = _stock("BBB", edge=1.0, confidence=1.0, cap_weight=1.0)
    out = capital_auction(
        cash_eur=3393.74500067863,
        candidates=[stock],
        fee_model=fee_model,
        total_value_eur=178_599.0,
    )
    spent = sum(o["value_eur"] + o["fee_eur"] for o in out["orders"])
    assert spent <= 3393.74500067863 + 1e-9
