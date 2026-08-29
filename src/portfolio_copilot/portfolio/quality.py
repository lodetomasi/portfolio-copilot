"""Decision quality rubric: did this decision follow good process, independent of whether it
made money? Pairs with ``portfolio.ledger.decision_alpha`` (the outcome) via
``decision_outcome_matrix`` to separate "good process" from "good luck".

Works on a single plain dict shaped like ``DecisionRecord.model_dump()`` (plus the optional
``cap_eur`` a caller may attach from ``portfolio.config`` risk limits) -- no ledger.py changes
needed. A missing field never gets guessed at: it simply scores 0 on that criterion, with an
explanation saying so.
"""

from __future__ import annotations

MIN_CONFIDENCE = 0.5
MIN_REASON_LENGTH = 40
GOOD_QUALITY_THRESHOLD = 60.0
STABLE_THESIS_STATUSES = {"STABLE", "STRENGTHENING"}


def _sources_criterion(record: dict) -> dict:
    sources = record.get("sources") or []
    ok = len(sources) >= 1
    return {
        "points": 20 if ok else 0,
        "max_points": 20,
        "explanation": f"{len(sources)} source(s) recorded" if ok else "no sources recorded",
    }


def _confidence_criterion(record: dict) -> dict:
    confidence = record.get("confidence")
    ok = confidence is not None and confidence >= MIN_CONFIDENCE
    return {
        "points": 15 if ok else 0,
        "max_points": 15,
        "explanation": (
            f"confidence {confidence} >= {MIN_CONFIDENCE}"
            if ok
            else f"confidence {confidence!r} missing or below {MIN_CONFIDENCE}"
        ),
    }


def _red_team_criterion(record: dict) -> dict:
    ok = record.get("red_team") == "passed"
    return {
        "points": 15 if ok else 0,
        "max_points": 15,
        "explanation": "red team passed" if ok else f"red_team={record.get('red_team')!r}",
    }


def _reason_length_criterion(record: dict) -> dict:
    reason = record.get("reason") or ""
    ok = len(reason) >= MIN_REASON_LENGTH
    return {
        "points": 10 if ok else 0,
        "max_points": 10,
        "explanation": (
            f"reason is {len(reason)} chars (>= {MIN_REASON_LENGTH})"
            if ok
            else f"reason is only {len(reason)} chars (< {MIN_REASON_LENGTH})"
        ),
    }


def _alternative_recorded_criterion(record: dict) -> dict:
    ok = bool(record.get("alternative"))
    return {
        "points": 10 if ok else 0,
        "max_points": 10,
        "explanation": "alternative recorded" if ok else "no alternative recorded",
    }


def _amount_within_cap_criterion(record: dict) -> dict:
    amount = record.get("amount_eur")
    cap = record.get("cap_eur")
    if amount is None or cap is None:
        return {
            "points": 0,
            "max_points": 15,
            "explanation": "unknown: amount_eur/cap_eur not both recorded",
        }
    within = amount <= cap
    return {
        "points": 15 if within else 0,
        "max_points": 15,
        "explanation": f"amount_eur {amount} {'within' if within else 'exceeds'} cap_eur {cap}",
    }


def _price_recorded_criterion(record: dict) -> dict:
    ok = record.get("price") is not None
    return {
        "points": 5 if ok else 0,
        "max_points": 5,
        "explanation": "price recorded" if ok else "no price recorded",
    }


def _thesis_status_criterion(record: dict) -> dict:
    if "thesis_status" not in record:
        return {"points": 0, "max_points": 10, "explanation": "thesis_status not recorded"}
    status = record["thesis_status"]
    ok = status in STABLE_THESIS_STATUSES
    return {
        "points": 10 if ok else 0,
        "max_points": 10,
        "explanation": f"thesis_status={status!r}",
    }


_CRITERIA = {
    "sources": _sources_criterion,
    "confidence": _confidence_criterion,
    "red_team": _red_team_criterion,
    "reason_length": _reason_length_criterion,
    "alternative_recorded": _alternative_recorded_criterion,
    "amount_within_cap": _amount_within_cap_criterion,
    "price_recorded": _price_recorded_criterion,
    "thesis_status": _thesis_status_criterion,
}

# Criteria that are structurally inapplicable to a bucket/index fill: deploy-cash's own
# workflow never invokes the red team for bucket-only orders, there is no "alternative"
# concept for filling the bucket itself, thesis.py is stock-specific (no bucket thesis
# engine), and amount_within_cap's cap comes from a per-stock risk limit, not a
# diversified bucket. Scoring a bucket fill against them would make the safest, most
# CLAUDE.md-preferred rebalancing action (buy an underweight core bucket with new cash)
# permanently unable to reach GOOD_QUALITY_THRESHOLD.
_BUCKET_INAPPLICABLE_CRITERIA = frozenset(
    {"red_team", "alternative_recorded", "amount_within_cap", "thesis_status"}
)


def decision_quality(record: dict) -> dict:
    """Score a single decision 0..100 on process quality, criterion by criterion.

    This is not a return forecast and never looks at the outcome -- only at whether the
    decision was made with sources, adequate confidence, a red-team pass, a documented reason,
    a recorded alternative, an amount inside the configured cap, a recorded price and a
    non-deteriorating thesis. Any criterion whose input is missing scores 0 with an explanation
    rather than being skipped, so an incomplete record cannot look better than it is.

    When ``record["decision_kind"] == "bucket"`` (a bucket/index fill, not a single-stock
    pick), the criteria in ``_BUCKET_INAPPLICABLE_CRITERIA`` are marked not applicable
    (0/0 points, excluded from the denominator too) and the score is renormalized to 0..100
    over the criteria that actually apply -- otherwise this rubric would rate CLAUDE.md's
    own preferred rebalancing action ("buy an underweight core bucket") as permanently
    unable to be a "good decision", regardless of how well it was executed.
    """
    criteria = {name: fn(record) for name, fn in _CRITERIA.items()}
    if record.get("decision_kind") == "bucket":
        for name in _BUCKET_INAPPLICABLE_CRITERIA:
            criteria[name] = {
                "points": 0,
                "max_points": 0,
                "explanation": "not applicable to a bucket/index fill",
            }
        applicable_max = sum(c["max_points"] for c in criteria.values())
        raw_points = sum(c["points"] for c in criteria.values())
        score = round(raw_points / applicable_max * 100) if applicable_max else 0
        return {"score": score, "criteria": criteria}
    return {"score": sum(c["points"] for c in criteria.values()), "criteria": criteria}


def decision_outcome_matrix(quality: float, decision_alpha: float | None) -> str:
    """Classify a decision on the process/outcome matrix: was it a good decision, and did it
    work out?

    ``decision_alpha`` of ``None`` (outcome not yet measurable, e.g. too recent or the
    alternative could not be priced) always returns ``'not yet measurable'`` regardless of
    quality -- a decision cannot be called lucky or unlucky before there is an outcome.
    """
    if decision_alpha is None:
        return "not yet measurable"
    good_decision = quality >= GOOD_QUALITY_THRESHOLD
    good_outcome = decision_alpha > 0
    if good_decision and good_outcome:
        return "good decision, good outcome"
    if good_decision and not good_outcome:
        return "good decision, bad outcome"
    if not good_decision and good_outcome:
        return "bad decision, lucky outcome"
    return "bad decision, bad outcome"
