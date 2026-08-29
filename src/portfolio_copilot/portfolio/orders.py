from __future__ import annotations

from portfolio_copilot.portfolio.rebalance import FeeModel


def estimate_order_cost(value_eur: float, fee_model: FeeModel | None = None) -> dict:
    fee_model = fee_model or FeeModel()
    fee = fee_model.fee(value_eur)
    return {
        "order_value_eur": value_eur,
        "estimated_fee_eur": fee,
        "fee_ratio": fee / value_eur if value_eur > 0 else None,
        "economic": fee_model.is_economic(value_eur),
        "minimum_economic_order_eur": fee_model.minimum_economic_order,
    }
