from __future__ import annotations

from statistics import mean

from portfolio_copilot.models import ScoreComponent, StockScore, StockSnapshot

DEFAULT_WEIGHTS = {
    "growth": 20,
    "quality": 20,
    "valuation": 15,
    "momentum": 15,
    "revisions": 10,
    "catalysts": 10,
    "risk": 10,
}


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, float(x)))


def _linear(value: float | None, bad: float, good: float, reverse: bool = False) -> float | None:
    if value is None:
        return None
    if good == bad:
        return 50.0
    s = (value - bad) / (good - bad) * 100.0
    s = _clamp(s)
    return 100.0 - s if reverse else s


def _avg(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return mean(present) if present else None


def score_snapshot(snapshot: StockSnapshot) -> StockScore:
    growth = _avg(
        [
            _linear(snapshot.revenue_growth, -0.10, 0.30),
            _linear(snapshot.earnings_growth, -0.20, 0.40),
        ]
    )

    quality = _avg(
        [
            _linear(snapshot.gross_margin, 0.10, 0.70),
            _linear(snapshot.operating_margin, -0.10, 0.30),
            _linear(snapshot.roe, -0.05, 0.30),
            _linear(snapshot.current_ratio, 0.6, 2.0),
            _linear(snapshot.debt_to_equity, 250, 20, reverse=False)
            if snapshot.debt_to_equity is not None
            else None,
        ]
    )

    # Simple V1 heuristic. Sector-relative valuation belongs in V2.
    valuation = _avg(
        [
            _linear(snapshot.forward_pe, 60, 12, reverse=False)
            if snapshot.forward_pe is not None
            else None,
            _linear(snapshot.price_to_sales, 15, 2, reverse=False)
            if snapshot.price_to_sales is not None
            else None,
            _linear(snapshot.enterprise_to_ebitda, 35, 8, reverse=False)
            if snapshot.enterprise_to_ebitda is not None
            else None,
        ]
    )

    momentum = _avg(
        [
            _linear(snapshot.ret_3m, -0.20, 0.30),
            _linear(snapshot.ret_6m, -0.30, 0.50),
            _linear(snapshot.ret_12m, -0.40, 0.80),
            65.0 if snapshot.above_sma50 else 35.0 if snapshot.above_sma50 is not None else None,
            70.0
            if snapshot.above_sma200
            else 30.0
            if snapshot.above_sma200 is not None
            else None,
        ]
    )

    risk_quality = _avg(
        [
            _linear(snapshot.vol_1y, 1.20, 0.20, reverse=False)
            if snapshot.vol_1y is not None
            else None,
            _linear(snapshot.max_drawdown_1y, -0.75, -0.10)
            if snapshot.max_drawdown_1y is not None
            else None,
        ]
    )

    raw = {
        "growth": growth,
        "quality": quality,
        "valuation": valuation,
        "momentum": momentum,
        "revisions": None,
        "catalysts": None,
        "risk": risk_quality,
    }

    components: list[ScoreComponent] = []
    weighted_sum = 0.0
    available_weight = 0.0

    for name, weight in DEFAULT_WEIGHTS.items():
        value = raw[name]
        if value is None:
            components.append(
                ScoreComponent(
                    name=name,
                    score=50.0,
                    weight=weight,
                    available=False,
                    reasons=["Data unavailable in free V1 provider"],
                )
            )
            continue
        components.append(
            ScoreComponent(name=name, score=_clamp(value), weight=weight, available=True)
        )
        weighted_sum += value * weight
        available_weight += weight

    final = weighted_sum / available_weight if available_weight else 50.0
    coverage = available_weight / sum(DEFAULT_WEIGHTS.values())
    confidence = min(snapshot.provenance.confidence, 0.35 + 0.65 * coverage)

    category = "Quality / Compounder"
    if growth is not None and momentum is not None and growth >= 70 and momentum >= 70:
        category = "Growth / Momentum"
    if risk_quality is not None and risk_quality < 35:
        category = "Asymmetric / High Risk"
    if available_weight == 0:
        # No component had usable data (e.g. invalid/unknown ticker): never present this
        # as a plausible real category. CLAUDE.md #6: degrade the score and declare it.
        category = "UNRATED / NO DATA"

    reasons = [
        f"data coverage {coverage:.0%}",
        f"provider confidence {snapshot.provenance.confidence:.0%}",
    ]
    if not any(c.available for c in components):
        reasons.append("Insufficient data: do not use this score for a decision")

    return StockScore(
        ticker=snapshot.ticker,
        score=_clamp(final),
        confidence=_clamp(confidence * 100) / 100,
        category=category,
        components=components,
        reasons=reasons,
        snapshot=snapshot,
    )
