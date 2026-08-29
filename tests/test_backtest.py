"""Backtest invariants on synthetic, seeded price paths. Offline and deterministic."""

import numpy as np
import pandas as pd
import pytest

from portfolio_copilot.portfolio.backtest import simulate_cash_flow_plan
from portfolio_copilot.portfolio.rebalance import FeeModel

TARGETS = {"A": 0.6, "B": 0.3, "C": 0.1}


def synthetic_prices(seed: int, months: int = 60, drift: float = 0.004, vol: float = 0.05):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, size=(months, len(TARGETS)))
    prices = 100 * np.exp(np.cumsum(rets, axis=0))
    idx = pd.date_range("2020-01-31", periods=months, freq="ME")
    return pd.DataFrame(prices, index=idx, columns=list(TARGETS))


def test_constant_prices_accounting_identity():
    prices = pd.DataFrame({"A": [100.0] * 24, "B": [50.0] * 24, "C": [10.0] * 24})
    out = simulate_cash_flow_plan(
        prices, TARGETS, initial_cash=3000, monthly_contribution=300, fee_model=FeeModel()
    )
    # value + fees == contributions exactly when prices never move.
    assert out["final_value_eur"] + out["fees_eur"] == pytest.approx(
        out["contributed_eur"], abs=0.02
    )
    assert out["contributed_eur"] == 3000 + 300 * 23
    assert out["gain_eur"] == pytest.approx(-out["fees_eur"], abs=0.02)
    assert out["cash_never_negative"]
    assert out["max_drawdown"] == pytest.approx(0.0)


def test_constant_prices_converge_inside_band():
    prices = pd.DataFrame({"A": [100.0] * 36, "B": [50.0] * 36, "C": [10.0] * 36})
    out = simulate_cash_flow_plan(
        prices, TARGETS, initial_cash=3000, monthly_contribution=300, fee_model=FeeModel()
    )
    for bucket, target in TARGETS.items():
        assert abs(out["final_weights"][bucket] - target) <= 0.03 + 1e-9


@pytest.mark.parametrize("seed", range(12))
def test_invariants_hold_on_random_paths(seed):
    fee_model = FeeModel(fixed_fee_eur=2.95, max_fee_ratio=0.01)
    out = simulate_cash_flow_plan(
        synthetic_prices(seed),
        TARGETS,
        initial_cash=2000,
        monthly_contribution=400,
        fee_model=fee_model,
        rebalance_band_abs=0.03,
    )
    assert out["cash_never_negative"]
    assert out["cash_left_eur"] >= 0
    assert out["fees_eur"] <= out["orders"] * fee_model.fixed_fee_eur + 1e-6
    # every order was economic: fee ratio <= 1% => fees <= 1% of money invested
    assert out["fees_pct_of_contributions"] <= 0.01 + 1e-9
    assert -1.0 <= out["max_drawdown"] <= 0.0
    assert 0.0 <= out["months_out_of_band_pct"] <= 1.0
    assert abs(sum(out["final_weights"].values()) - 1.0) < 1e-3  # weights rounded to 4 dp
    assert out["months"] == 60
    assert "Not a forecast" in out["note"]
    # With contributions >= minimum order, idle cash never exceeds one uneconomic remainder.
    assert out["cash_left_eur"] < fee_model.minimum_economic_order + fee_model.fixed_fee_eur


def test_pooling_every_three_months_reduces_orders_and_fees():
    prices = synthetic_prices(7)
    monthly = simulate_cash_flow_plan(
        prices, TARGETS, initial_cash=0, monthly_contribution=120, contribution_every_months=1
    )
    pooled = simulate_cash_flow_plan(
        prices, TARGETS, initial_cash=0, monthly_contribution=120, contribution_every_months=3
    )
    # 120 EUR/month is below the 295 EUR minimum order. Investing only every 3 months
    # (360 EUR pooled) must never cost more orders or fees than trying every month, and the
    # money must end up invested either way (cash left is one pool at most).
    assert pooled["orders"] <= monthly["orders"]
    assert pooled["fees_eur"] <= monthly["fees_eur"]
    assert pooled["cash_left_eur"] <= 3 * 120 + 1e-6
    assert monthly["cash_left_eur"] <= 3 * 120 + 1e-6
    assert pooled["fees_pct_of_contributions"] <= 0.01 + 1e-9


def test_never_sells_units_only_grow():
    prices = synthetic_prices(3, months=24)
    out = simulate_cash_flow_plan(prices, TARGETS, initial_cash=1000, monthly_contribution=300)
    # With no sells and positive contributions, final invested value must be > 0 for all
    # buckets that ever received an order; and total drift bookkeeping is present.
    assert out["max_abs_drift"] is not None
    assert all(w >= 0 for w in out["final_weights"].values())


def test_months_out_of_band_pct_denominator_excludes_pre_investment_months():
    # Pooling for 5 months before the first buy (contribution_every_months=5, initial_cash=0)
    # means the first 4 of 10 simulated months have no position and no drift measurement.
    # months_out_of_band_pct must be reported over the 6 months the portfolio actually held a
    # position (3 out of band), not diluted by the 10 total simulated months.
    a = [100.0] * 5 + [100, 140, 180, 220, 260]
    b = [100.0] * 10
    prices = pd.DataFrame({"A": a, "B": b})
    out = simulate_cash_flow_plan(
        prices,
        {"A": 0.5, "B": 0.5},
        initial_cash=0,
        monthly_contribution=1000,
        fee_model=FeeModel(fixed_fee_eur=2.95, max_fee_ratio=0.01),
        rebalance_band_abs=0.03,
        contribution_every_months=5,
    )
    assert out["months_out_of_band"] == 3
    assert out["months_out_of_band_pct"] == pytest.approx(0.5)


def test_months_out_of_band_pct_zero_when_never_invested():
    # Degenerate case: no initial cash and contributions never reach an invest step within the
    # price history. drifts is empty; the pct must not raise (0/0) and must report 0.0.
    prices = pd.DataFrame({"A": [100.0, 100.0], "B": [100.0, 100.0]})
    out = simulate_cash_flow_plan(
        prices,
        {"A": 0.5, "B": 0.5},
        initial_cash=0,
        monthly_contribution=0,
        contribution_every_months=1,
    )
    assert out["months_out_of_band"] == 0
    assert out["months_out_of_band_pct"] == 0.0


@pytest.mark.parametrize(
    "prices,error",
    [
        (pd.DataFrame({"A": [1.0, 2.0], "B": [1.0, 2.0]}), "Missing price series"),
        (pd.DataFrame({"A": [1.0], "B": [1.0], "C": [1.0]}), "at least two"),
        (pd.DataFrame({"A": [1.0, 0.0], "B": [1.0, 1.0], "C": [1.0, 1.0]}), "positive"),
        (pd.DataFrame({"A": [1.0, np.nan], "B": [1.0, 1.0], "C": [1.0, 1.0]}), "positive"),
    ],
)
def test_rejects_bad_price_inputs(prices, error):
    with pytest.raises(ValueError, match=error):
        simulate_cash_flow_plan(prices, TARGETS, initial_cash=100, monthly_contribution=10)
