"""Source precedence: official data (tier A: SEC, ECB) overrides aggregators (tier B: Yahoo).

Pure functions. Every override is recorded in ``provenance.overrides`` so Claude can show
"revenue_growth: sec_edgar FY2025 replaces yfinance".
"""

from __future__ import annotations

from portfolio_copilot.analytics.evidence import evidence_report, from_snapshot_and_facts
from portfolio_copilot.models import StockSnapshot

TIERS = {"sec_edgar": "A", "ecb_eurofxref": "A", "yfinance": "B", "stooq": "B", "finviz": "C"}

# snapshot field -> SEC company_facts field
_OFFICIAL_FIELDS = {"revenue_growth": "revenue_growth", "free_cashflow": "free_cashflow"}


def apply_official_overrides(snapshot: StockSnapshot, facts: dict | None) -> StockSnapshot:
    """Return a copy of ``snapshot`` where audited SEC values replace Yahoo values.

    Only fields present (non-null) in ``facts`` are replaced. If ``facts`` is missing or
    ``ok`` is false, the snapshot is returned unchanged except for a note in
    ``provenance.secondary_sources``.
    """
    prov = snapshot.provenance.model_copy(deep=True)
    prov.tier = prov.tier or TIERS.get(prov.source)
    if not facts:
        prov.secondary_sources.append("sec_edgar: not queried")
        return snapshot.model_copy(update={"provenance": prov})
    if not facts.get("ok"):
        reason = facts.get("error") or "no us-gaap facts (foreign filer or ADR)"
        prov.secondary_sources.append(f"sec_edgar: unavailable ({reason})")
        return snapshot.model_copy(update={"provenance": prov})

    updates: dict = {}
    fy = facts.get("fiscal_year")
    for field, source_field in _OFFICIAL_FIELDS.items():
        value = facts.get(source_field)
        if value is None:
            continue
        updates[field] = float(value)
        prov.overrides.append(f"{field}: sec_edgar FY{fy} replaces {snapshot.provenance.source}")
    prov.secondary_sources.append(f"sec_edgar: FY{fy} filed {facts.get('as_of')}")
    if updates:
        prov.confidence = min(1.0, prov.confidence + 0.10)
        prov.missing_fields = [m for m in prov.missing_fields if m not in updates]
    return snapshot.model_copy(update={**updates, "provenance": prov})


def apply_evidence_report(
    snapshot: StockSnapshot,
    facts: dict | None,
    finviz_row: dict | None = None,
    *,
    raw_snapshot: StockSnapshot | None = None,
) -> tuple[StockSnapshot, dict]:
    """Cross-check the snapshot's metrics against SEC facts (and, optionally, a Finviz row)
    via ``analytics/evidence.py``.

    When two or more sources report the same metric and disagree (``status: CONFLICT``)
    and the chosen reading is not tier A, that metric is unreliable enough to exclude from
    scoring: it is set to ``None`` on the returned snapshot and the exclusion is recorded in
    ``provenance.secondary_sources`` (CLAUDE.md rule 6: degrade the score, never invent). A
    conflict resolved in favour of an official tier-A source is left as-is -- A always wins.

    ``raw_snapshot``: when the caller already applied ``apply_official_overrides`` to
    ``snapshot`` before calling this (as ``analyze_stock`` does, so overridden metrics are
    used for scoring), pass the ORIGINAL, pre-override snapshot here. Without it, the
    "yfinance" reading built from the already-overridden ``snapshot`` would just equal the
    SEC value that replaced it -- silently defeating this exact cross-check. Defaults to
    ``snapshot`` itself when omitted (no override happened, or the caller doesn't need this).

    Returns the (possibly amended) snapshot and the full evidence report, so a caller can
    both score the cleaned snapshot and show the report to the user under the score's
    ``"evidence"`` key.
    """
    evidence_snapshot = raw_snapshot if raw_snapshot is not None else snapshot
    metrics = from_snapshot_and_facts(evidence_snapshot.model_dump(mode="json"), facts, finviz_row)
    report = evidence_report(metrics)

    updates: dict = {}
    notes: list[str] = []
    for metric, result in report["metrics"].items():
        if result["status"] != "CONFLICT" or result["chosen_tier"] == "A":
            continue
        if getattr(snapshot, metric, None) is None:
            continue
        updates[metric] = None
        notes.append(
            f"{metric}: excluded from score (source conflict, spread={result['spread']:.4g})"
        )

    if not updates:
        return snapshot, report

    prov = snapshot.provenance.model_copy(deep=True)
    prov.secondary_sources.extend(notes)
    return snapshot.model_copy(update={**updates, "provenance": prov}), report
