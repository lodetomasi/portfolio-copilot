from datetime import UTC, datetime

from portfolio_copilot.analytics.merge import apply_evidence_report, apply_official_overrides
from portfolio_copilot.models import Provenance, StockSnapshot


def _snap(**kw):
    return StockSnapshot(
        ticker="ACME",
        revenue_growth=0.05,
        free_cashflow=None,
        provenance=Provenance(
            source="yfinance", as_of=datetime.now(UTC), confidence=0.75,
            missing_fields=["freeCashflow"],
        ),
        **kw,
    )


def test_official_sec_values_override_yahoo_and_are_recorded():
    facts = {"ok": True, "fiscal_year": 2025, "as_of": "2026-03-01",
             "revenue_growth": 0.28, "free_cashflow": -150000.0}
    out = apply_official_overrides(_snap(), facts)
    assert out.revenue_growth == 0.28
    assert out.free_cashflow == -150000.0
    assert out.provenance.tier == "B"
    assert out.provenance.confidence == 0.85
    assert "revenue_growth: sec_edgar FY2025 replaces yfinance" in out.provenance.overrides
    assert out.provenance.missing_fields == ["freeCashflow"]  # yahoo key untouched, value now set
    assert any("FY2025" in s for s in out.provenance.secondary_sources)


def test_missing_sec_values_never_overwrite_with_none():
    facts = {"ok": True, "fiscal_year": 2025, "as_of": "x", "revenue_growth": None,
             "free_cashflow": None}
    out = apply_official_overrides(_snap(), facts)
    assert out.revenue_growth == 0.05 and out.provenance.overrides == []
    assert out.provenance.confidence == 0.75


def test_apply_evidence_report_excludes_conflict_without_official_tiebreaker():
    """yfinance (tier B) and Finviz (tier C) disagree wildly on forward_pe with no tier-A
    reading to arbitrate: the metric must be excluded from the score (set to None) and the
    exclusion recorded in provenance, per CLAUDE.md rule 6."""
    snap = _snap(forward_pe=20.0)
    out, report = apply_evidence_report(snap, facts=None, finviz_row={"P/E": 5.0})
    assert out.forward_pe is None
    assert report["metrics"]["forward_pe"]["status"] == "CONFLICT"
    assert report["metrics"]["forward_pe"]["chosen_tier"] == "B"
    assert any("forward_pe" in note for note in out.provenance.secondary_sources)
    assert report["counts"]["CONFLICT"] == 1


def test_apply_evidence_report_keeps_conflict_resolved_by_an_official_source():
    """yfinance (B) and SEC EDGAR (A) disagree on revenue_growth: since an official tier-A
    reading exists, A always wins and the field is never nulled out."""
    snap = _snap()  # revenue_growth=0.05 by default
    facts = {"ok": True, "fiscal_year": 2025, "as_of": "2026-01-01",
              "revenue_growth": 0.30, "free_cashflow": None}
    out, report = apply_evidence_report(snap, facts)
    assert out.revenue_growth == 0.05  # apply_evidence_report never overwrites, only excludes
    assert report["metrics"]["revenue_growth"]["status"] == "CONFLICT"
    assert report["metrics"]["revenue_growth"]["chosen_tier"] == "A"
    assert out.provenance.secondary_sources == []


def test_apply_evidence_report_single_source_metric_is_never_touched():
    snap = _snap()  # gross_margin/operating_margin unset -> MISSING, not a false CONFLICT
    out, report = apply_evidence_report(snap, facts=None, finviz_row=None)
    assert out.revenue_growth == 0.05
    assert report["metrics"]["revenue_growth"]["status"] == "SINGLE_SOURCE"
    assert report["counts"]["CONFLICT"] == 0


def test_unavailable_sec_leaves_snapshot_unchanged_but_noted():
    out = apply_official_overrides(_snap(), {"ok": False, "error": "Ticker not found in SEC list"})
    assert out.revenue_growth == 0.05
    assert out.provenance.secondary_sources == [
        "sec_edgar: unavailable (Ticker not found in SEC list)"
    ]
    none = apply_official_overrides(_snap(), None)
    assert none.provenance.secondary_sources == ["sec_edgar: not queried"]


def test_apply_evidence_report_after_override_compares_against_the_pre_override_value():
    """analyze_stock calls apply_official_overrides() BEFORE apply_evidence_report(): if
    evidence-building re-reads the metric off the already-overridden snapshot, the
    "yfinance" and "sec_edgar" readings become numerically identical by construction and
    the cross-check this module exists for can never actually fire. A real disagreement
    (yfinance: strong 30% growth; SEC: a wildly different -50%) must still surface as a
    conflict, using the raw pre-override yfinance value passed via `raw_snapshot`."""
    snapshot = StockSnapshot(
        ticker="ACME",
        revenue_growth=0.30,
        provenance=Provenance(
            source="yfinance", as_of=datetime.now(UTC), confidence=0.75,
        ),
    )
    facts = {"ok": True, "fiscal_year": 2025, "as_of": "2026-03-01", "revenue_growth": -0.50}
    overridden = apply_official_overrides(snapshot, facts)
    assert overridden.revenue_growth == -0.50  # override applied as usual

    _, report = apply_evidence_report(overridden, facts, raw_snapshot=snapshot)
    metric = report["metrics"]["revenue_growth"]
    assert metric["status"] == "CONFLICT"
    yfinance_reading = next(s for s in metric["sources"] if s["source"] == "yfinance")
    assert yfinance_reading["value"] == 0.30  # the real, un-overridden yfinance reading
    assert metric["chosen_tier"] == "A"
    assert metric["chosen_value"] == -0.50
