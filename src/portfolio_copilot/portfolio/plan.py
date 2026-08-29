"""Investment plan builder: rookie inputs in, deterministic plan + calendar out.

No return forecasts. Everything here is arithmetic on the user's own numbers plus
allocation choices read from ``config/model_portfolios.yaml``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml

from portfolio_copilot.portfolio.rebalance import FeeModel, allocate_cash_to_targets

DEFAULT_MODEL_PORTFOLIOS = Path(__file__).resolve().parents[3] / "config" / "model_portfolios.yaml"
RISK_LEVELS = ("low", "medium", "high")


@dataclass(frozen=True)
class ModelPortfolio:
    name: str
    description: str
    targets: dict[str, float]


def load_model_portfolios(path: Path | str = DEFAULT_MODEL_PORTFOLIOS) -> dict:
    """Load profiles and example instruments. Raises if a profile does not sum to 1.0."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    profiles: dict[str, ModelPortfolio] = {}
    for name, spec in raw["profiles"].items():
        targets = {k: float(v) for k, v in spec["targets"].items()}
        if abs(sum(targets.values()) - 1.0) > 1e-6:
            raise ValueError(f"Model portfolio '{name}' targets sum to {sum(targets.values()):.4f}")
        profiles[name] = ModelPortfolio(name=name, description=spec["description"], targets=targets)
    return {"profiles": profiles, "instruments": raw.get("instruments", {})}


def suggest_profile(horizon_years: float, risk_tolerance: str) -> str:
    """Map two rookie answers to a model portfolio name. Deterministic and conservative."""
    if risk_tolerance not in RISK_LEVELS:
        raise ValueError(f"risk_tolerance must be one of {RISK_LEVELS}")
    if horizon_years < 3:
        return "cautious"
    if horizon_years < 8:
        return "cautious" if risk_tolerance == "low" else "balanced"
    return {"low": "balanced", "medium": "growth", "high": "growth"}[risk_tolerance]


def contribution_cadence_months(monthly_contribution: float, fee_model: FeeModel) -> int:
    """How many months of contributions to pool so one order is economic (fee ratio <= cap).

    2.95 EUR fee and 1% cap => 295 EUR minimum order => 100 EUR/month pools every 3 months.
    Capped at 12: below that, the user must raise the contribution or accept the fee ratio.
    """
    if monthly_contribution <= 0:
        raise ValueError("monthly_contribution must be > 0")
    minimum = fee_model.minimum_economic_order
    if math.isinf(minimum):
        return 12
    return int(min(12, max(1, math.ceil(minimum / monthly_contribution))))


def _add_months(d: date, months: int) -> date:
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(d.day, 28))


def build_calendar(
    start_date: date,
    months: int,
    contribution_every: int,
    review_every: int = 3,
) -> list[dict]:
    """Dated events for the first ``months`` months: contribute / review / annual_review."""
    events: list[dict] = []
    for m in range(1, months + 1):
        when = _add_months(start_date, m)
        actions: list[str] = []
        if m % contribution_every == 0:
            actions.append("contribute")
        if m % 12 == 0:
            actions.append("annual_review")
        elif m % review_every == 0:
            actions.append("review")
        if actions:
            events.append({"date": when.isoformat(), "month": m, "actions": actions})
    return events


def build_investment_plan(
    *,
    cash_now: float,
    monthly_contribution: float,
    horizon_years: float,
    risk_tolerance: str,
    start_date: date,
    fee_model: FeeModel | None = None,
    rebalance_band_abs: float = 0.03,
    review_every_months: int = 3,
    calendar_months: int = 12,
    model_portfolios_path: Path | str = DEFAULT_MODEL_PORTFOLIOS,
) -> dict:
    """Build a complete, deterministic plan from four rookie inputs.

    Returns targets, example instruments (to verify), the initial orders for ``cash_now``,
    the fee-aware contribution cadence, a 12-month calendar and the review rules.
    Contribution totals contain NO return assumption.
    """
    if cash_now < 0:
        raise ValueError("cash_now cannot be negative")
    if horizon_years <= 0:
        raise ValueError("horizon_years must be > 0")
    fee_model = fee_model or FeeModel()
    models = load_model_portfolios(model_portfolios_path)
    profile_name = suggest_profile(horizon_years, risk_tolerance)
    profile = models["profiles"][profile_name]

    cadence = contribution_cadence_months(monthly_contribution, fee_model)
    pooled = monthly_contribution * cadence

    initial = allocate_cash_to_targets(
        current_values={},
        targets=profile.targets,
        cash_eur=cash_now,
        fee_model=fee_model,
        rebalance_band_abs=0.0,
    )
    months_total = int(round(horizon_years * 12))
    contributions_total = cash_now + monthly_contribution * months_total

    warnings: list[str] = []
    if cadence >= 12 and pooled < fee_model.minimum_economic_order:
        warnings.append(
            f"{monthly_contribution:.2f} EUR/month never reaches the minimum economic order "
            f"({fee_model.minimum_economic_order:.2f} EUR) within 12 months: raise the "
            "contribution or accept a fee ratio above the cap."
        )
    if initial["unallocated_cash"] > 0 and cash_now > 0:
        warnings.append(
            f"{initial['unallocated_cash']:.2f} EUR of the initial cash stays liquid: the "
            "order for one or more buckets would be below the minimum economic order."
        )

    return {
        "profile": profile_name,
        "profile_description": profile.description,
        "targets": profile.targets,
        "instruments": {
            bucket: {**models["instruments"].get(bucket, {}), "verify_before_use": True}
            for bucket in profile.targets
        },
        "initial_orders": initial["orders"],
        "initial_unallocated_cash": initial["unallocated_cash"],
        "contribution": {
            "monthly_eur": monthly_contribution,
            "every_months": cadence,
            "pooled_eur": round(pooled, 2),
            "minimum_economic_order_eur": round(fee_model.minimum_economic_order, 2),
        },
        "rules": {
            "rebalance_band_abs": rebalance_band_abs,
            "review_every_months": review_every_months,
            "order_of_preference": [
                "use new cash to buy the most underweight bucket",
                "pause buys on buckets above target",
                "sell only if a bucket is still beyond the band after new cash, at a review",
            ],
            "execution": "MANUAL_ONLY",
        },
        "calendar": build_calendar(start_date, calendar_months, cadence, review_every_months),
        "horizon": {
            "years": horizon_years,
            "months": months_total,
            "contributions_total_eur": round(contributions_total, 2),
            "note": "Contributions only. No return, inflation or tax assumption.",
        },
        "warnings": warnings,
    }
