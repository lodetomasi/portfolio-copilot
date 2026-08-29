"""Personal edge: do *this user's* past decisions actually beat the recorded alternative,
broken down by category/theme -- and is there enough sample to trust the answer?

Works on plain dicts shaped like the ``rows`` produced by ``portfolio.ledger.evaluate_decisions``
(``decision_alpha`` present, ``None`` when the alternative could not be priced) plus an optional
``category`` or ``theme`` key the caller may attach when replaying decisions for this report.
Nothing here re-measures decisions or touches the ledger; it only aggregates numbers it is
handed, so a caller with zero or a handful of decisions gets an honest "not enough data" instead
of a confident-looking number.
"""

from __future__ import annotations

import math

DEFAULT_MIN_SAMPLE = 10
UNCATEGORIZED = "uncategorized"

# Thresholds for nudging how much evidence should be required before acting again on a
# given category, based on this user's own track record in it -- never a return forecast.
_RAISE_MEAN_ALPHA = -0.05
_RAISE_HIT_RATE = 0.4
_LOWER_MEAN_ALPHA = 0.05
_LOWER_HIT_RATE = 0.6


def _group_key(row: dict) -> str:
    category = row.get("category")
    if category:
        return str(category)
    theme = row.get("theme")
    if theme:
        return str(theme)
    return UNCATEGORIZED


def _is_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    return not math.isnan(value)


def _adjust_for(mean_alpha: float, hit_rate: float) -> str:
    if mean_alpha < _RAISE_MEAN_ALPHA or hit_rate < _RAISE_HIT_RATE:
        return "raise"
    if mean_alpha > _LOWER_MEAN_ALPHA and hit_rate > _LOWER_HIT_RATE:
        return "lower"
    return "keep"


def _stats_for(alphas: list[float], *, min_sample: int) -> dict:
    n = len(alphas)
    mean_alpha = (sum(alphas) / n) if n else None
    hit_rate = (sum(1 for a in alphas if a > 0) / n) if n else None

    if n == 0 or n < min_sample:
        return {
            "n": n,
            "mean_alpha": mean_alpha,
            "hit_rate": hit_rate,
            "evidence_threshold_adjust": "insufficient_sample",
            "warning": (
                f"Only {n} measured decision(s) (< {min_sample}): do not adjust evidence "
                "thresholds on this sample."
            ),
        }

    return {
        "n": n,
        "mean_alpha": mean_alpha,
        "hit_rate": hit_rate,
        "evidence_threshold_adjust": _adjust_for(mean_alpha, hit_rate),
        "warning": None,
    }


def personal_edge(measured_rows: list[dict], min_sample: int = DEFAULT_MIN_SAMPLE) -> dict:
    """Aggregate decision alpha by category/theme, plus an overall figure.

    Each row contributes to its stats only when ``decision_alpha`` is a real number -- a row
    whose alternative could never be priced (``decision_alpha`` is ``None``) is excluded rather
    than treated as a zero, so it cannot silently pull the mean toward "no edge".

    ``evidence_threshold_adjust`` is only ever ``'raise'``, ``'lower'`` or ``'keep'`` once a
    category/overall has at least ``min_sample`` measured decisions; below that it is
    ``'insufficient_sample'`` and a human-readable ``warning`` explains why, so a thin sample
    never gets to look like a verdict.
    """
    grouped: dict[str, list[float]] = {}
    all_alphas: list[float] = []
    for row in measured_rows:
        alpha = row.get("decision_alpha")
        if not _is_number(alpha):
            continue
        grouped.setdefault(_group_key(row), []).append(float(alpha))
        all_alphas.append(float(alpha))

    by_category = {
        category: _stats_for(alphas, min_sample=min_sample)
        for category, alphas in grouped.items()
    }
    overall = _stats_for(all_alphas, min_sample=min_sample)

    return {"by_category": by_category, "overall": overall}
