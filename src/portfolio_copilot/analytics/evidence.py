"""Multi-source agreement layer: reconcile the same metric across providers.

Every external datum in this project carries `source`/`as_of`/`confidence` (CLAUDE.md).
This module goes one step further: when more than one free source reports the same
metric (e.g. revenue growth from yfinance and from SEC EDGAR), it says whether they
agree, and -- if they don't -- whether the disagreement is safe to ignore (an official
tier-A filing outranks a tier-B/C aggregator) or must be surfaced instead of silently
averaged away. Pure functions only: no I/O, no network, nothing invented.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime
from itertools import combinations
from typing import Literal

from pydantic import BaseModel

Tier = Literal["A", "B", "C"]
Status = Literal["MISSING", "SINGLE_SOURCE", "VERIFIED", "CONFLICT"]

_TIER_RANK: dict[str, int] = {"A": 0, "B": 1, "C": 2}

# StockSnapshot fields this layer cross-checks, and the company_facts (SEC EDGAR) keys
# that speak to the same concept. Only these fields ever get built by
# `from_snapshot_and_facts` -- e.g. SEC's `net_margin` is a different metric from
# `operating_margin` and is never conflated with it.
_SNAPSHOT_METRICS: tuple[str, ...] = (
    "revenue_growth",
    "gross_margin",
    "operating_margin",
    "free_cashflow",
    "forward_pe",
)
_FACTS_METRICS: dict[str, str] = {
    "revenue_growth": "revenue_growth",
    "free_cashflow": "free_cashflow",
}


class SourceValue(BaseModel):
    """One provider's reading of one metric, tagged with its authority tier and recency.

    `tier` follows the project-wide convention (see `models.Provenance`): A = official
    filing (SEC, ECB), B = aggregator (Yahoo, Stooq), C = crawler (Finviz).
    """

    source: str
    tier: Tier
    value: float | None = None
    as_of: str | None = None


def _agrees(a: float, b: float, rel_tolerance: float, abs_tolerance: float) -> bool:
    """True if two readings are close enough, in absolute terms or relative to their size."""
    tolerance = max(abs_tolerance, rel_tolerance * max(abs(a), abs(b)))
    return abs(a - b) <= tolerance


def _parse_as_of(value: str | None) -> datetime | None:
    """Best-effort ISO-8601 parse, normalized to UTC. ``None`` if not parseable -- the
    caller falls back to a raw string comparison in that case."""
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo is not None else parsed


def _is_more_recent(candidate_as_of: str | None, best_as_of: str | None) -> bool:
    """True if `candidate_as_of` is chronologically after `best_as_of`.

    Compares actual parsed timestamps (normalized to UTC) when both parse as ISO-8601, so
    two same-tier readings with different UTC offsets (``...22:00:00Z`` vs
    ``...23:00:00+02:00``) are ordered correctly instead of by raw string comparison,
    which can misorder them. Falls back to the original string comparison when either
    value isn't a parseable ISO-8601 timestamp.
    """
    if candidate_as_of is None:
        return False
    if best_as_of is None:
        return True
    candidate_dt, best_dt = _parse_as_of(candidate_as_of), _parse_as_of(best_as_of)
    if candidate_dt is not None and best_dt is not None:
        return candidate_dt > best_dt
    return candidate_as_of > best_as_of


def _choose(candidates: list[SourceValue]) -> SourceValue:
    """Pick the value to actually use: highest tier; ties -> most recent `as_of`; else first."""
    best = candidates[0]
    for candidate in candidates[1:]:
        if _TIER_RANK[candidate.tier] < _TIER_RANK[best.tier]:
            best = candidate
        elif _TIER_RANK[candidate.tier] == _TIER_RANK[best.tier]:
            if _is_more_recent(candidate.as_of, best.as_of):
                best = candidate
    return best


def compare_metric(
    metric: str,
    values: list[SourceValue],
    rel_tolerance: float = 0.20,
    abs_tolerance: float = 0.01,
) -> dict:
    """Reconcile one metric across whatever sources reported it.

    Never invents a number: a metric nobody reported comes back `MISSING`, not defaulted.
    With exactly one reading it is used but flagged `SINGLE_SOURCE` (nothing to cross-check
    against). With two or more, every pair is compared within tolerance: `VERIFIED` if they
    all agree, `CONFLICT` otherwise. The chosen value is always the highest-tier source
    (ties broken by the most recent `as_of`, else the first listed) -- and `use_in_score`
    is False for an unresolved conflict among non-official sources (an official tier-A
    reading is used even inside a flagged conflict) and for a lone tier-C (crawler, e.g.
    Finviz) reading with nothing to corroborate it -- tier C is discovery-only and never
    enters a score on its own (see docs/ARCHITECTURE.md's source-tier rules).
    """
    present = [v for v in values if v.value is not None]
    sources = [v.model_dump() for v in present]

    if not present:
        return {
            "metric": metric,
            "status": "MISSING",
            "chosen_value": None,
            "chosen_source": None,
            "chosen_tier": None,
            "spread": None,
            "use_in_score": False,
            "sources": sources,
        }

    if len(present) == 1:
        only = present[0]
        return {
            "metric": metric,
            "status": "SINGLE_SOURCE",
            "chosen_value": only.value,
            "chosen_source": only.source,
            "chosen_tier": only.tier,
            "spread": 0.0,
            "use_in_score": only.tier != "C",
            "sources": sources,
        }

    numbers = [v.value for v in present if v.value is not None]
    spread = max(numbers) - min(numbers)
    agree = all(
        _agrees(a.value, b.value, rel_tolerance, abs_tolerance)  # type: ignore[arg-type]
        for a, b in combinations(present, 2)
    )
    status: Status = "VERIFIED" if agree else "CONFLICT"
    chosen = _choose(present)
    use_in_score = status != "CONFLICT" or chosen.tier == "A"
    return {
        "metric": metric,
        "status": status,
        "chosen_value": chosen.value,
        "chosen_source": chosen.source,
        "chosen_tier": chosen.tier,
        "spread": spread,
        "use_in_score": use_in_score,
        "sources": sources,
    }


def evidence_report(
    metrics: dict[str, list[SourceValue]],
    rel_tolerance: float = 0.20,
    abs_tolerance: float = 0.01,
) -> dict:
    """Run `compare_metric` over many metrics and tally the outcome by status."""
    per_metric = {
        name: compare_metric(name, values, rel_tolerance, abs_tolerance)
        for name, values in metrics.items()
    }
    counts: dict[str, int] = {"MISSING": 0, "SINGLE_SOURCE": 0, "VERIFIED": 0, "CONFLICT": 0}
    for result in per_metric.values():
        counts[result["status"]] += 1
    return {"metrics": per_metric, "counts": counts}


def _finite_float(value: object) -> float | None:
    """Coerce ``value`` to a finite float, or ``None`` -- a NaN/Infinity (a real float, a
    numeric string like ``"nan"``, or anything unparsable) is never a real measurement and
    must never be silently accepted as a source's reading (it would corrupt `spread`/
    `chosen_value` and, once JSON-encoded, is not even valid JSON per RFC 8259)."""
    if value is None:
        return None
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _as_of_str(value: object) -> str | None:
    """Normalize a snapshot/facts timestamp (datetime, ISO string, or None) to `str | None`."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    isoformat = getattr(value, "isoformat", None)
    return isoformat() if callable(isoformat) else str(value)


def from_snapshot_and_facts(
    snapshot: dict, facts: dict | None, finviz_row: dict | None
) -> dict[str, list[SourceValue]]:
    """Build per-metric `SourceValue` lists from a snapshot dump, SEC facts and a Finviz row.

    `snapshot` is a `StockSnapshot.model_dump()` (its `provenance.source`/`tier`/`as_of`
    identify the reading); `facts` is a `SECEdgarProvider.get_company_facts` result
    (`revenue_growth`/`free_cashflow` are the only overlapping concepts -- its `net_margin`
    is a different metric from `operating_margin` and is never mapped onto it); `finviz_row`
    is one row from a Finviz screener result (`'P/E'`, mapped to `forward_pe`). Any of the
    three may be `None`/empty, and a source only contributes a point for a metric it
    actually has a non-null value for -- nothing is fabricated to fill a gap.
    """
    result: dict[str, list[SourceValue]] = {metric: [] for metric in _SNAPSHOT_METRICS}

    provenance = (snapshot or {}).get("provenance") or {}
    snap_source = provenance.get("source") or "snapshot"
    snap_tier: Tier = provenance.get("tier") or "B"
    snap_as_of = _as_of_str(provenance.get("as_of"))
    for metric in _SNAPSHOT_METRICS:
        value = _finite_float(snapshot.get(metric)) if snapshot else None
        if value is not None:
            result[metric].append(
                SourceValue(source=snap_source, tier=snap_tier, value=value, as_of=snap_as_of)
            )

    if facts:
        facts_as_of = _as_of_str(facts.get("as_of"))
        for metric, key in _FACTS_METRICS.items():
            value = _finite_float(facts.get(key))
            if value is not None:
                result[metric].append(
                    SourceValue(source="sec_edgar", tier="A", value=value, as_of=facts_as_of)
                )

    if finviz_row:
        pe_value = _finite_float(finviz_row.get("P/E"))
        if pe_value is not None:
            result["forward_pe"].append(SourceValue(source="finviz", tier="C", value=pe_value))

    return result
