"""Tests for the multi-source evidence/agreement layer (analytics/evidence.py).

All offline and deterministic: SourceValue instances are constructed by hand, and the
builder tests use synthetic StockSnapshot/company-facts/finviz-row shapes -- no network.
"""

from datetime import UTC, datetime

from portfolio_copilot.analytics.evidence import (
    SourceValue,
    compare_metric,
    evidence_report,
    from_snapshot_and_facts,
)
from portfolio_copilot.models import Provenance, StockSnapshot


def _sv(source: str, tier: str, value: float | None, as_of: str | None = None) -> SourceValue:
    return SourceValue(source=source, tier=tier, value=value, as_of=as_of)


# ---------------------------------------------------------------------------
# compare_metric: statuses
# ---------------------------------------------------------------------------


def test_missing_when_values_list_is_empty():
    out = compare_metric("revenue_growth", [])
    assert out["status"] == "MISSING"
    assert out["chosen_value"] is None
    assert out["chosen_source"] is None
    assert out["chosen_tier"] is None
    assert out["use_in_score"] is False
    assert out["spread"] is None
    assert out["sources"] == []


def test_missing_when_all_values_are_none():
    out = compare_metric("revenue_growth", [_sv("yfinance", "B", None)])
    assert out["status"] == "MISSING"
    assert out["sources"] == []


def test_single_source_is_used_but_flagged_unverified():
    out = compare_metric("revenue_growth", [_sv("yfinance", "B", 0.10, "2026-01-01")])
    assert out["status"] == "SINGLE_SOURCE"
    assert out["chosen_value"] == 0.10
    assert out["chosen_source"] == "yfinance"
    assert out["chosen_tier"] == "B"
    assert out["use_in_score"] is True
    assert out["spread"] == 0.0
    assert len(out["sources"]) == 1


def test_none_values_are_dropped_before_a_single_real_value_is_used():
    out = compare_metric(
        "revenue_growth", [_sv("stooq", "B", None), _sv("yfinance", "B", 0.12)]
    )
    assert out["status"] == "SINGLE_SOURCE"
    assert out["chosen_source"] == "yfinance"


def test_two_sources_within_tolerance_are_verified():
    values = [_sv("yfinance", "B", 0.10), _sv("stooq", "B", 0.11)]
    out = compare_metric("revenue_growth", values, rel_tolerance=0.20, abs_tolerance=0.01)
    assert out["status"] == "VERIFIED"
    assert out["use_in_score"] is True
    assert round(out["spread"], 2) == 0.01


def test_two_sources_outside_tolerance_are_a_conflict_and_unused_without_tier_a():
    values = [_sv("yfinance", "B", 0.10), _sv("stooq", "B", 0.50)]
    out = compare_metric("revenue_growth", values)
    assert out["status"] == "CONFLICT"
    assert out["use_in_score"] is False


def test_conflict_with_an_official_tier_a_source_is_still_flagged_but_used():
    values = [_sv("sec_edgar", "A", 0.30), _sv("yfinance", "B", 0.10)]
    out = compare_metric("revenue_growth", values)
    assert out["status"] == "CONFLICT"
    assert out["chosen_source"] == "sec_edgar"
    assert out["chosen_tier"] == "A"
    assert out["use_in_score"] is True


# ---------------------------------------------------------------------------
# compare_metric: tolerance edges
# ---------------------------------------------------------------------------


def test_tolerance_boundary_is_inclusive():
    at_boundary = [_sv("a", "B", 1.0), _sv("b", "B", 1.5)]
    out = compare_metric("m", at_boundary, rel_tolerance=0.0, abs_tolerance=0.5)
    assert out["status"] == "VERIFIED"

    just_over = [_sv("a", "B", 1.0), _sv("b", "B", 1.6)]
    out_over = compare_metric("m", just_over, rel_tolerance=0.0, abs_tolerance=0.5)
    assert out_over["status"] == "CONFLICT"


def test_relative_tolerance_scales_with_magnitude():
    # 20% of the larger magnitude (115) is 23; a diff of 15 is within that even though it
    # would blow past a tiny absolute tolerance.
    values = [_sv("a", "B", 100.0), _sv("b", "B", 115.0)]
    out = compare_metric("m", values, rel_tolerance=0.20, abs_tolerance=0.01)
    assert out["status"] == "VERIFIED"


# ---------------------------------------------------------------------------
# compare_metric: tier choice and recency tie-break
# ---------------------------------------------------------------------------


def test_highest_tier_wins_regardless_of_list_order():
    values = [_sv("finviz", "C", 9.0), _sv("yfinance", "B", 10.0), _sv("sec_edgar", "A", 20.0)]
    out = compare_metric("forward_pe", values)
    assert out["chosen_source"] == "sec_edgar"
    assert out["chosen_tier"] == "A"


def test_same_tier_ties_broken_by_most_recent_as_of():
    values = [
        _sv("yfinance", "B", 10.0, "2026-01-01"),
        _sv("stooq", "B", 10.5, "2026-06-01"),
    ]
    out = compare_metric("m", values, rel_tolerance=0.20)
    assert out["chosen_source"] == "stooq"


def test_same_tier_no_recency_difference_keeps_the_first_listed():
    same_date = [
        _sv("yfinance", "B", 10.0, "2026-01-01"),
        _sv("stooq", "B", 10.5, "2026-01-01"),
    ]
    out = compare_metric("m", same_date, rel_tolerance=0.20)
    assert out["chosen_source"] == "yfinance"

    no_dates = [_sv("yfinance", "B", 10.0), _sv("stooq", "B", 10.5)]
    out2 = compare_metric("m", no_dates, rel_tolerance=0.20)
    assert out2["chosen_source"] == "yfinance"


def test_spread_is_max_minus_min_across_present_sources():
    values = [_sv("a", "B", 1.0), _sv("b", "B", 1.05), _sv("c", "C", 1.5)]
    out = compare_metric("m", values, rel_tolerance=1.0)  # lax on purpose, focus is on spread
    assert round(out["spread"], 2) == 0.5


# ---------------------------------------------------------------------------
# evidence_report
# ---------------------------------------------------------------------------


def test_evidence_report_tallies_every_status():
    metrics = {
        "revenue_growth": [_sv("sec_edgar", "A", 0.30), _sv("yfinance", "B", 0.10)],  # CONFLICT
        "gross_margin": [_sv("yfinance", "B", 0.40)],  # SINGLE_SOURCE
        "operating_margin": [_sv("yfinance", "B", 0.20), _sv("stooq", "B", 0.205)],  # VERIFIED
        "forward_pe": [],  # MISSING
    }
    report = evidence_report(metrics)
    assert report["counts"] == {"MISSING": 1, "SINGLE_SOURCE": 1, "VERIFIED": 1, "CONFLICT": 1}
    assert report["metrics"]["revenue_growth"]["status"] == "CONFLICT"
    assert report["metrics"]["revenue_growth"]["use_in_score"] is True
    assert report["metrics"]["forward_pe"]["status"] == "MISSING"


def test_evidence_report_on_empty_metrics_dict():
    report = evidence_report({})
    assert report == {
        "metrics": {},
        "counts": {"MISSING": 0, "SINGLE_SOURCE": 0, "VERIFIED": 0, "CONFLICT": 0},
    }


# ---------------------------------------------------------------------------
# from_snapshot_and_facts
# ---------------------------------------------------------------------------


def _snapshot_dict(**overrides) -> dict:
    defaults: dict = dict(
        ticker="ACME",
        revenue_growth=0.12,
        gross_margin=0.55,
        operating_margin=0.22,
        free_cashflow=500_000.0,
        forward_pe=18.5,
        provenance=Provenance(
            source="yfinance",
            as_of=datetime(2026, 6, 1, tzinfo=UTC),
            confidence=0.8,
        ),
    )
    defaults.update(overrides)
    return StockSnapshot(**defaults).model_dump()


def test_builder_combines_all_three_sources_per_metric():
    snapshot = _snapshot_dict()
    facts = {
        "ok": True,
        "as_of": "2026-03-01",
        "revenue_growth": 0.30,
        "free_cashflow": 480_000.0,
        "net_margin": 0.15,  # not one of the tracked metrics -> must be ignored
    }
    finviz_row = {"Ticker": "ACME", "P/E": "20.1"}

    built = from_snapshot_and_facts(snapshot, facts, finviz_row)

    assert {sv.source for sv in built["revenue_growth"]} == {"yfinance", "sec_edgar"}
    assert {sv.source for sv in built["free_cashflow"]} == {"yfinance", "sec_edgar"}
    assert {sv.source for sv in built["forward_pe"]} == {"yfinance", "finviz"}
    assert [sv.source for sv in built["gross_margin"]] == ["yfinance"]
    assert [sv.source for sv in built["operating_margin"]] == ["yfinance"]

    sec_value = next(sv for sv in built["revenue_growth"] if sv.source == "sec_edgar")
    assert sec_value.tier == "A"
    assert sec_value.as_of == "2026-03-01"

    finviz_value = next(sv for sv in built["forward_pe"] if sv.source == "finviz")
    assert finviz_value.tier == "C"
    assert finviz_value.value == 20.1

    yf_value = next(sv for sv in built["revenue_growth"] if sv.source == "yfinance")
    assert yf_value.tier == "B"
    assert yf_value.as_of == "2026-06-01T00:00:00+00:00"


def test_builder_with_only_snapshot_reports_missing_for_absent_fields():
    snapshot = _snapshot_dict(forward_pe=None)
    built = from_snapshot_and_facts(snapshot, None, None)

    assert [sv.source for sv in built["revenue_growth"]] == ["yfinance"]
    assert built["forward_pe"] == []  # snapshot value is None -> no fabricated entry

    report = evidence_report(built)
    assert report["metrics"]["forward_pe"]["status"] == "MISSING"
    assert report["metrics"]["revenue_growth"]["status"] == "SINGLE_SOURCE"


def test_builder_skips_facts_fields_outside_its_known_shape():
    snapshot = _snapshot_dict()
    facts = {"ok": True, "as_of": "2026-03-01", "net_margin": 0.15}
    built = from_snapshot_and_facts(snapshot, facts, None)
    assert [sv.source for sv in built["revenue_growth"]] == ["yfinance"]
    assert [sv.source for sv in built["free_cashflow"]] == ["yfinance"]


def test_builder_ignores_unavailable_facts_and_finviz_inputs():
    snapshot = _snapshot_dict()
    built_no_facts = from_snapshot_and_facts(snapshot, None, None)
    assert [sv.source for sv in built_no_facts["revenue_growth"]] == ["yfinance"]

    built_empty_facts = from_snapshot_and_facts(snapshot, {}, None)
    assert [sv.source for sv in built_empty_facts["revenue_growth"]] == ["yfinance"]


def test_builder_ignores_non_numeric_finviz_pe():
    snapshot = _snapshot_dict()
    finviz_row = {"Ticker": "ACME", "P/E": "-"}  # finvizfinance uses "-" for N/A
    built = from_snapshot_and_facts(snapshot, None, finviz_row)
    assert [sv.source for sv in built["forward_pe"]] == ["yfinance"]


def test_builder_handles_missing_snapshot_provenance_gracefully():
    built = from_snapshot_and_facts({"revenue_growth": 0.05}, None, None)
    assert built["revenue_growth"][0].source == "snapshot"
    assert built["revenue_growth"][0].tier == "B"
    assert built["revenue_growth"][0].as_of is None


# ---------------------------------------------------------------------------
# finding 41: non-finite (NaN/Infinity) values must degrade, never be treated
# as a real reading
# ---------------------------------------------------------------------------


def test_builder_treats_nan_finviz_pe_string_as_missing_not_a_real_reading():
    snapshot = {"forward_pe": 18.5, "provenance": {"source": "yfinance", "tier": "B"}}
    built = from_snapshot_and_facts(snapshot, None, {"P/E": "nan"})
    report = evidence_report(built)
    metric = report["metrics"]["forward_pe"]
    assert metric["status"] == "SINGLE_SOURCE"
    assert metric["chosen_value"] == 18.5
    assert len(metric["sources"]) == 1


def test_builder_treats_infinite_snapshot_value_as_missing():
    snapshot = {"revenue_growth": float("inf"), "provenance": {"source": "yfinance", "tier": "B"}}
    built = from_snapshot_and_facts(snapshot, None, None)
    assert built["revenue_growth"] == []


def test_builder_treats_nan_facts_value_as_missing():
    snapshot = {"provenance": {"source": "yfinance", "tier": "B"}}
    facts = {"ok": True, "revenue_growth": float("nan")}
    built = from_snapshot_and_facts(snapshot, facts, None)
    assert built["revenue_growth"] == []


# ---------------------------------------------------------------------------
# finding 42: a lone tier-C (Finviz) reading must never be usable in the score
# ---------------------------------------------------------------------------


def test_single_source_tier_c_is_never_used_in_score():
    out = compare_metric("forward_pe", [_sv("finviz", "C", 20.1)])
    assert out["status"] == "SINGLE_SOURCE"
    assert out["use_in_score"] is False


def test_single_source_tier_b_is_still_used_in_score():
    out = compare_metric("forward_pe", [_sv("yfinance", "B", 20.1)])
    assert out["status"] == "SINGLE_SOURCE"
    assert out["use_in_score"] is True


# ---------------------------------------------------------------------------
# finding 43: same-tier recency tie-break must compare actual chronological
# time, not raw ISO-8601 strings (which can misorder across UTC offsets)
# ---------------------------------------------------------------------------


def test_same_tier_recency_tiebreak_handles_differing_utc_offsets():
    # src_a: 22:00 UTC (later). src_b: 23:00 in +02:00 == 21:00 UTC (earlier), but its
    # string sorts lexicographically AFTER src_a's "Z"-suffixed string.
    a = _sv("src_a", "B", 10.0, as_of="2026-06-01T22:00:00Z")
    b = _sv("src_b", "B", 10.5, as_of="2026-06-01T23:00:00+02:00")
    out = compare_metric("m", [a, b], rel_tolerance=0.20)
    assert out["chosen_source"] == "src_a"
