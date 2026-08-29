from __future__ import annotations

from portfolio_copilot.analytics.metrics import concentration
from portfolio_copilot.models import Portfolio


def summarize_portfolio_risk(portfolio: Portfolio) -> dict:
    total = portfolio.total_value
    if total <= 0:
        return {
            "total_value": 0.0,
            "weights": [],
            "concentration": concentration([]),
            "leveraged_nominal_value": 0.0,
            "leveraged_equivalent_exposure": 0.0,
        }

    rows = []
    leveraged_nominal = 0.0
    leveraged_equiv = 0.0

    for h in portfolio.holdings:
        w = h.market_value / total
        rows.append(
            {
                "name": h.name,
                "symbol": h.symbol,
                "market_value": h.market_value,
                "weight": w,
                "asset_type": h.asset_type.value,
                "leverage": h.leverage,
            }
        )
        if abs(h.leverage) > 1.0:
            leveraged_nominal += h.market_value
            leveraged_equiv += h.market_value * abs(h.leverage)

    weights = [r["weight"] for r in rows]
    return {
        "total_value": total,
        "weights": rows,
        "concentration": concentration(weights),
        "leveraged_nominal_value": leveraged_nominal,
        "leveraged_nominal_weight": leveraged_nominal / total,
        "leveraged_equivalent_exposure": leveraged_equiv,
        "leveraged_equivalent_to_portfolio": leveraged_equiv / total,
    }
