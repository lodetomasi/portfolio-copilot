"""Deterministic backtest of the cash-flow-first plan on a price history.

Given monthly prices per bucket, replays: pool contributions, buy toward targets with the
same fee-aware engine used live, never sell. Reports what happened; it forecasts nothing.
"""

from __future__ import annotations

import pandas as pd

from portfolio_copilot.analytics.metrics import max_drawdown
from portfolio_copilot.portfolio.rebalance import FeeModel, allocate_cash_to_targets


def simulate_cash_flow_plan(
    prices: pd.DataFrame,
    targets: dict[str, float],
    *,
    initial_cash: float,
    monthly_contribution: float,
    fee_model: FeeModel | None = None,
    rebalance_band_abs: float = 0.03,
    contribution_every_months: int = 1,
) -> dict:
    """Replay the plan month by month.

    ``prices``: one row per month (ascending), one column per target bucket, positive floats.
    Contributions are pooled and invested every ``contribution_every_months`` months using
    ``allocate_cash_to_targets``. Returns path statistics and accounting checks.
    """
    fee_model = fee_model or FeeModel()
    missing = [b for b in targets if b not in prices.columns]
    if missing:
        raise ValueError(f"Missing price series for buckets: {missing}")
    if prices.empty or len(prices) < 2:
        raise ValueError("Need at least two monthly price rows")
    clean = prices[list(targets)].astype(float)
    if (clean <= 0).any().any() or clean.isna().any().any():
        raise ValueError("Prices must be positive and non-NaN")

    units = dict.fromkeys(targets, 0.0)
    cash = float(initial_cash)
    contributed = float(initial_cash)
    fees = 0.0
    orders = 0
    values: list[float] = []
    drifts: list[float] = []
    out_of_band_months = 0

    for step, (_, row) in enumerate(clean.iterrows()):
        month = step + 1
        if step > 0:
            cash += monthly_contribution
            contributed += monthly_contribution
        invest_now = step == 0 or month % contribution_every_months == 0
        current_values = {b: units[b] * float(row[b]) for b in targets}
        if invest_now and cash > 0:
            result = allocate_cash_to_targets(
                current_values=current_values,
                targets=targets,
                cash_eur=cash,
                fee_model=fee_model,
                rebalance_band_abs=rebalance_band_abs,
            )
            for order in result["orders"]:
                units[order["symbol"]] += order["value_eur"] / float(row[order["symbol"]])
                cash -= order["value_eur"] + order["estimated_fee_eur"]
                fees += order["estimated_fee_eur"]
                orders += 1
            current_values = {b: units[b] * float(row[b]) for b in targets}
        invested = sum(current_values.values())
        values.append(invested + cash)
        if invested > 0:
            drift = max(abs(current_values[b] / invested - w) for b, w in targets.items())
            drifts.append(drift)
            if drift > rebalance_band_abs:
                out_of_band_months += 1

    value_series = pd.Series(values)
    final_value = values[-1]
    final_weights = (
        {b: units[b] * float(clean.iloc[-1][b]) / (final_value - cash) for b in targets}
        if final_value - cash > 0
        else dict.fromkeys(targets, 0.0)
    )
    return {
        "months": len(values),
        "contributed_eur": round(contributed, 2),
        "final_value_eur": round(final_value, 2),
        "cash_left_eur": round(max(0.0, cash), 2) if cash > -1e-6 else round(cash, 2),
        "gain_eur": round(final_value - contributed, 2),
        "fees_eur": round(fees, 2),
        "fees_pct_of_contributions": round(fees / contributed, 4) if contributed else 0.0,
        "orders": orders,
        "max_drawdown": max_drawdown(value_series),
        "max_abs_drift": round(max(drifts), 4) if drifts else None,
        "months_out_of_band": out_of_band_months,
        "months_out_of_band_pct": (
            round(out_of_band_months / len(drifts), 4) if drifts else 0.0
        ),
        "final_weights": {b: round(w, 4) for b, w in final_weights.items()},
        "note": "Replay of past prices with the plan rules. Not a forecast.",
        "cash_never_negative": cash >= -1e-9,
    }
