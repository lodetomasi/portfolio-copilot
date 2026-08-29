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


def _revisions_component(snapshot: StockSnapshot) -> tuple[float | None, list[str], float]:
    """Analyst-estimate / revision signal: mean of every available free-data sub-
    indicator, split into two groups that are not equally sensitive to today's
    analyst headcount:

    - *opinion-based* (current sell-side estimate growth, revision balance,
      consensus rating, target upside): reflects how many analysts are covering
      the name right now, so thin coverage (fewer than 3 analysts) shrinks this
      half toward the neutral midpoint 50 so a single opinionated analyst cannot
      swing the score;
    - *event/history-based* (event-dated rating-change momentum and price-target
      change, historical earnings-surprise mean/share/streak): real past events,
      unaffected by how many analysts happen to be covering the stock today.

    Returns ``(value, reasons, weight_factor)`` where ``weight_factor`` (<=1.0)
    tells the caller how much of this component's nominal scoring weight should
    count toward overall confidence/coverage -- discounted only by the thin,
    opinion-based share, so a component built from one thin opinion cannot lift
    reported confidence as much as one backed by broad coverage or hard events.
    """
    opinion_indicators = [
        _linear(snapshot.est_eps_growth_1y, -0.10, 0.40),
        _linear(snapshot.est_revenue_growth_1y, -0.05, 0.30),
        _linear(snapshot.revision_balance, -1.0, 1.0),
        _linear(snapshot.consensus_score, -1.0, 1.0),
        _linear(snapshot.target_upside, -0.20, 0.40),
    ]
    event_indicators = [
        _linear(snapshot.revision_net_90d, -4, 4),
        _linear(snapshot.revision_pt_change_90d, -0.15, 0.15),
        _linear(snapshot.surprise_mean_8q, -0.05, 0.10),
        _linear(snapshot.surprise_positive_share_8q, 0.25, 0.9),
        _linear(snapshot.surprise_streak, 0, 6),
    ]
    opinion_avg = _avg(opinion_indicators)
    event_avg = _avg(event_indicators)
    n_opinion = sum(1 for v in opinion_indicators if v is not None)
    n_event = sum(1 for v in event_indicators if v is not None)

    reasons: list[str] = []
    shrink_ratio = 1.0
    thin = snapshot.analyst_count is not None and snapshot.analyst_count < 3
    if opinion_avg is not None and thin:
        shrink_ratio = snapshot.analyst_count / 3.0
        opinion_avg = 50.0 + (opinion_avg - 50.0) * snapshot.analyst_count / 3.0
        reasons.append("thin analyst coverage")

    total_n = n_opinion + n_event
    if total_n == 0:
        return None, reasons, 1.0

    value = ((opinion_avg or 0.0) * n_opinion + (event_avg or 0.0) * n_event) / total_n
    opinion_share = n_opinion / total_n
    weight_factor = 1.0 - opinion_share * (1.0 - shrink_ratio)
    return value, reasons, weight_factor


def _catalysts_component(snapshot: StockSnapshot) -> tuple[float | None, list[str]]:
    """Event-density signal: how much is scheduled/has recently happened around this
    name (earnings proximity, insider Form 4 filings, 8-K flow). Deliberately
    direction-agnostic: it says events are ahead or behind, never whether they are
    good or bad news."""
    earnings_proximity = (
        100.0 - min(100.0, max(0.0, float(snapshot.days_to_next_earnings)))
        if snapshot.days_to_next_earnings is not None
        else None
    )
    value = _avg(
        [
            earnings_proximity,
            _linear(snapshot.insider_form4_90d, 0, 6),
            _linear(snapshot.filings_8k_90d, 0, 6),
        ]
    )
    reasons: list[str] = []
    if value is not None:
        reasons.append("events ahead/behind, not a direction")
    return value, reasons


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

    revisions, revisions_reasons, revisions_weight_factor = _revisions_component(snapshot)
    catalysts, catalysts_reasons = _catalysts_component(snapshot)
    weight_factors = {"revisions": revisions_weight_factor}

    raw = {
        "growth": growth,
        "quality": quality,
        "valuation": valuation,
        "momentum": momentum,
        "revisions": revisions,
        "catalysts": catalysts,
        "risk": risk_quality,
    }
    component_reasons = {
        "revisions": revisions_reasons,
        "catalysts": catalysts_reasons,
    }

    components: list[ScoreComponent] = []
    weighted_sum = 0.0
    available_weight = 0.0
    confidence_weight = 0.0

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
        clamped = _clamp(value)
        components.append(
            ScoreComponent(
                name=name,
                score=clamped,
                weight=weight,
                available=True,
                reasons=component_reasons.get(name, []),
            )
        )
        weighted_sum += clamped * weight
        available_weight += weight
        confidence_weight += weight * weight_factors.get(name, 1.0)

    final = weighted_sum / available_weight if available_weight else 50.0
    coverage = confidence_weight / sum(DEFAULT_WEIGHTS.values())
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
    available_names = [c.name for c in components if c.available]
    if available_names:
        reasons.append("available components: " + ", ".join(available_names))
    else:
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
