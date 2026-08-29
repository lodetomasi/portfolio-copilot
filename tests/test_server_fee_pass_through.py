"""Regression tests: rebalance_portfolio, generate_order_plan and backtest_plan must thread
``variable_fee_pct`` into the ``FeeModel`` they build, exactly like allocate_cash and
build_investment_plan already do. Without it, the fee-ratio economics gate silently checks
orders against the wrong (zero) variable fee, understating fees and approving orders that
would violate the user's own ``max_fee_ratio`` under their broker's real fee schedule.
"""

from __future__ import annotations

import pandas as pd

import portfolio_copilot.server as server


def test_rebalance_portfolio_threads_variable_fee_pct_into_fee_model():
    # Real fee schedule: 0.5% variable fee. Minimum economic order becomes
    # 2.95 / (0.01 - 0.005) = 590 EUR, so 300 EUR of cash buys nothing.
    result = server.rebalance_portfolio(
        current_values={"sat": 0.0},
        targets={"sat": 1.0},
        cash_eur=300.0,
        fixed_fee_eur=2.95,
        variable_fee_pct=0.005,
        max_fee_ratio=0.01,
    )
    assert result["orders"] == []
    assert result["unallocated_cash"] == 300.0


def test_generate_order_plan_threads_variable_fee_pct_into_fee_model():
    result = server.generate_order_plan(
        current_values={"sat": 0.0},
        targets={"sat": 1.0},
        cash_eur=300.0,
        fixed_fee_eur=2.95,
        variable_fee_pct=0.005,
        max_fee_ratio=0.01,
    )
    assert result["orders"] == []
    assert result["unallocated_cash"] == 300.0


def _fake_monthly_closes(tickers, period="5y"):
    idx = pd.date_range("2024-01-31", periods=2, freq="ME")
    df = pd.DataFrame({bucket: [100.0, 100.0] for bucket in tickers}, index=idx)
    df.attrs.update({"missing": [], "source": "fake", "as_of": "2024-02-29T00:00:00+00:00"})
    return df


def test_backtest_plan_threads_variable_fee_pct_into_fee_model(monkeypatch):
    monkeypatch.setattr(server.provider, "get_monthly_closes", _fake_monthly_closes)

    result = server.backtest_plan(
        tickers_by_bucket={"sat": "SAT"},
        targets={"sat": 1.0},
        initial_cash=300.0,
        monthly_contribution=0.0,
        fixed_fee_eur=2.95,
        variable_fee_pct=0.005,
        max_fee_ratio=0.01,
    )

    assert result["ok"] is True
    assert result["orders"] == 0
    assert result["fees_eur"] == 0.0
    assert result["cash_left_eur"] == 300.0
