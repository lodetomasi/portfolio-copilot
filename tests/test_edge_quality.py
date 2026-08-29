"""Tests for portfolio.edge (personal edge by category) and portfolio.quality
(decision quality rubric + outcome matrix).

All inputs are plain dicts shaped like ``DecisionRecord.model_dump()`` plus an optional
``category``/``theme`` and the ``evaluate_decisions`` row fields (``real_return``,
``alternative_return``, ``decision_alpha``) -- no ledger.py changes needed to exercise
either module. Everything here is pure/offline/deterministic.
"""

from __future__ import annotations

from portfolio_copilot.portfolio.edge import personal_edge
from portfolio_copilot.portfolio.quality import decision_outcome_matrix, decision_quality


def _row(category=None, theme=None, alpha=None, **extra) -> dict:
    row = {"id": "r", "status": "measured", "decision_alpha": alpha}
    if category is not None:
        row["category"] = category
    if theme is not None:
        row["theme"] = theme
    row.update(extra)
    return row


# ---------------------------------------------------------------------------
# personal_edge
# ---------------------------------------------------------------------------


def test_personal_edge_empty_input_is_insufficient_and_has_no_categories():
    result = personal_edge([])

    assert result["by_category"] == {}
    assert result["overall"]["n"] == 0
    assert result["overall"]["mean_alpha"] is None
    assert result["overall"]["hit_rate"] is None
    assert result["overall"]["evidence_threshold_adjust"] == "insufficient_sample"
    assert isinstance(result["overall"]["warning"], str)


def test_personal_edge_groups_by_category_with_fallback_uncategorized():
    rows = [
        _row(category="growth", alpha=0.1),
        _row(category="growth", alpha=-0.1),
        _row(alpha=0.2),  # no category, no theme
    ]

    result = personal_edge(rows, min_sample=1)

    assert set(result["by_category"]) == {"growth", "uncategorized"}
    assert result["by_category"]["growth"]["n"] == 2
    assert result["by_category"]["uncategorized"]["n"] == 1


def test_personal_edge_uses_theme_when_category_absent():
    rows = [_row(theme="value-trap", alpha=0.05), _row(theme="value-trap", alpha=-0.05)]

    result = personal_edge(rows, min_sample=1)

    assert set(result["by_category"]) == {"value-trap"}
    assert result["by_category"]["value-trap"]["n"] == 2


def test_personal_edge_category_takes_precedence_over_theme_when_both_present():
    rows = [_row(category="growth", theme="value-trap", alpha=0.05)]

    result = personal_edge(rows, min_sample=1)

    assert set(result["by_category"]) == {"growth"}


def test_personal_edge_rows_with_none_decision_alpha_are_excluded_from_stats():
    rows = [
        _row(category="growth", alpha=0.1),
        _row(category="growth", alpha=None),  # unmeasurable alternative, must not count
    ]

    result = personal_edge(rows, min_sample=1)

    assert result["by_category"]["growth"]["n"] == 1
    assert result["by_category"]["growth"]["mean_alpha"] == 0.1


def test_personal_edge_below_min_sample_reports_insufficient_and_warning():
    rows = [_row(category="growth", alpha=0.1) for _ in range(5)]

    result = personal_edge(rows, min_sample=10)

    cat = result["by_category"]["growth"]
    assert cat["n"] == 5
    assert cat["evidence_threshold_adjust"] == "insufficient_sample"
    assert isinstance(cat["warning"], str) and "5" in cat["warning"]


def test_personal_edge_default_min_sample_is_ten():
    rows = [_row(category="growth", alpha=0.1) for _ in range(9)]

    result = personal_edge(rows)

    assert result["by_category"]["growth"]["evidence_threshold_adjust"] == "insufficient_sample"


def test_personal_edge_raise_when_mean_alpha_very_negative():
    rows = [_row(category="growth", alpha=-0.1) for _ in range(10)]

    result = personal_edge(rows, min_sample=10)

    cat = result["by_category"]["growth"]
    assert cat["mean_alpha"] < -0.05
    assert cat["evidence_threshold_adjust"] == "raise"
    assert cat.get("warning") is None


def test_personal_edge_raise_when_hit_rate_low_even_if_mean_alpha_ok():
    # 3 big winners, 7 small losers -> mean_alpha positive-ish but hit_rate well below 0.4
    rows = (
        [_row(category="growth", alpha=0.5) for _ in range(3)]
        + [_row(category="growth", alpha=-0.01) for _ in range(7)]
    )

    result = personal_edge(rows, min_sample=10)

    cat = result["by_category"]["growth"]
    assert cat["hit_rate"] < 0.4
    assert cat["evidence_threshold_adjust"] == "raise"


def test_personal_edge_lower_when_mean_alpha_high_and_hit_rate_high():
    rows = [_row(category="growth", alpha=0.1) for _ in range(7)] + [
        _row(category="growth", alpha=-0.01) for _ in range(3)
    ]

    result = personal_edge(rows, min_sample=10)

    cat = result["by_category"]["growth"]
    assert cat["mean_alpha"] > 0.05
    assert cat["hit_rate"] > 0.6
    assert cat["evidence_threshold_adjust"] == "lower"


def test_personal_edge_keep_when_neither_extreme():
    rows = [_row(category="growth", alpha=0.01) for _ in range(6)] + [
        _row(category="growth", alpha=-0.01) for _ in range(4)
    ]

    result = personal_edge(rows, min_sample=10)

    cat = result["by_category"]["growth"]
    assert cat["evidence_threshold_adjust"] == "keep"


def test_personal_edge_overall_aggregates_across_categories():
    rows = [_row(category="growth", alpha=0.1) for _ in range(5)] + [
        _row(category="value", alpha=-0.1) for _ in range(5)
    ]

    result = personal_edge(rows, min_sample=10)

    assert result["overall"]["n"] == 10
    assert result["overall"]["mean_alpha"] == 0.0


def test_personal_edge_is_deterministic_and_pure():
    rows = [_row(category="growth", alpha=0.03), _row(category="growth", alpha=-0.02)]

    first = personal_edge(rows, min_sample=1)
    second = personal_edge(rows, min_sample=1)

    assert first == second
    # inputs untouched
    assert rows[0]["decision_alpha"] == 0.03


def test_personal_edge_hit_rate_counts_strictly_positive_alpha_only():
    rows = [_row(category="growth", alpha=0.0), _row(category="growth", alpha=0.0)]

    result = personal_edge(rows, min_sample=1)

    assert result["by_category"]["growth"]["hit_rate"] == 0.0


# ---------------------------------------------------------------------------
# decision_quality
# ---------------------------------------------------------------------------


def _full_record(**overrides) -> dict:
    record = {
        "sources": ["yfinance", "sec_edgar"],
        "confidence": 0.8,
        "red_team": "passed",
        "reason": "x" * 40,
        "alternative": "MSFT",
        "amount_eur": 500.0,
        "cap_eur": 1000.0,
        "price": 123.45,
        "thesis_status": "STABLE",
    }
    record.update(overrides)
    return record


def test_decision_quality_full_score_when_everything_present():
    result = decision_quality(_full_record())

    assert result["score"] == 100


def test_decision_quality_empty_record_scores_zero():
    result = decision_quality({})

    assert result["score"] == 0


def test_decision_quality_sources_criterion_needs_at_least_one():
    with_source = decision_quality(_full_record(sources=["yfinance"]))
    no_source = decision_quality(_full_record(sources=[]))
    missing_key = decision_quality(_full_record(sources=None))

    assert with_source["criteria"]["sources"]["points"] == 20
    assert no_source["criteria"]["sources"]["points"] == 0
    assert missing_key["score"] < with_source["score"]


def test_decision_quality_confidence_below_threshold_scores_zero():
    low = decision_quality(_full_record(confidence=0.49))
    high = decision_quality(_full_record(confidence=0.5))
    missing = decision_quality(_full_record(confidence=None))

    assert low["criteria"]["confidence"]["points"] == 0
    assert high["criteria"]["confidence"]["points"] == 15
    assert missing["criteria"]["confidence"]["points"] == 0


def test_decision_quality_red_team_must_equal_passed():
    rejected = decision_quality(_full_record(red_team="rejected: too speculative"))
    passed = decision_quality(_full_record(red_team="passed"))
    missing = decision_quality(_full_record(red_team=None))

    assert rejected["criteria"]["red_team"]["points"] == 0
    assert passed["criteria"]["red_team"]["points"] == 15
    assert missing["criteria"]["red_team"]["points"] == 0


def test_decision_quality_reason_length_threshold_is_forty_chars():
    short = decision_quality(_full_record(reason="x" * 39))
    exact = decision_quality(_full_record(reason="x" * 40))

    assert short["criteria"]["reason_length"]["points"] == 0
    assert exact["criteria"]["reason_length"]["points"] == 10


def test_decision_quality_alternative_recorded():
    recorded = decision_quality(_full_record(alternative="MSFT"))
    empty = decision_quality(_full_record(alternative=""))
    missing = decision_quality(_full_record(alternative=None))

    assert recorded["criteria"]["alternative_recorded"]["points"] == 10
    assert empty["criteria"]["alternative_recorded"]["points"] == 0
    assert missing["criteria"]["alternative_recorded"]["points"] == 0


def test_decision_quality_amount_within_cap_scores_full_points():
    result = decision_quality(_full_record(amount_eur=500.0, cap_eur=1000.0))

    assert result["criteria"]["amount_within_cap"]["points"] == 15


def test_decision_quality_amount_exceeding_cap_scores_zero():
    result = decision_quality(_full_record(amount_eur=1500.0, cap_eur=1000.0))

    assert result["criteria"]["amount_within_cap"]["points"] == 0


def test_decision_quality_amount_exactly_at_cap_counts_as_within():
    result = decision_quality(_full_record(amount_eur=1000.0, cap_eur=1000.0))

    assert result["criteria"]["amount_within_cap"]["points"] == 15


def test_decision_quality_amount_unknown_when_either_field_missing():
    no_cap = decision_quality(_full_record(amount_eur=500.0, cap_eur=None))
    no_amount = decision_quality(_full_record(amount_eur=None, cap_eur=1000.0))
    neither = {k: v for k, v in _full_record().items() if k not in ("amount_eur", "cap_eur")}
    missing_keys = decision_quality(neither)

    for result in (no_cap, no_amount, missing_keys):
        assert result["criteria"]["amount_within_cap"]["points"] == 0
        assert "unknown" in result["criteria"]["amount_within_cap"]["explanation"].lower()


def test_decision_quality_price_recorded():
    present = decision_quality(_full_record(price=99.9))
    missing = decision_quality(_full_record(price=None))

    assert present["criteria"]["price_recorded"]["points"] == 5
    assert missing["criteria"]["price_recorded"]["points"] == 0


def test_decision_quality_thesis_status_stable_and_strengthening_score_full():
    stable = decision_quality(_full_record(thesis_status="STABLE"))
    strengthening = decision_quality(_full_record(thesis_status="STRENGTHENING"))

    assert stable["criteria"]["thesis_status"]["points"] == 10
    assert strengthening["criteria"]["thesis_status"]["points"] == 10


def test_decision_quality_thesis_status_other_value_scores_zero():
    weakening = decision_quality(_full_record(thesis_status="WEAKENING"))

    assert weakening["criteria"]["thesis_status"]["points"] == 0


def test_decision_quality_thesis_status_missing_key_scores_zero_with_note():
    record = {k: v for k, v in _full_record().items() if k != "thesis_status"}

    result = decision_quality(record)

    assert result["criteria"]["thesis_status"]["points"] == 0
    assert "not recorded" in result["criteria"]["thesis_status"]["explanation"].lower()


def test_decision_quality_score_is_deterministic():
    record = _full_record(confidence=0.62)

    first = decision_quality(record)
    second = decision_quality(record)

    assert first == second


def test_decision_quality_criteria_points_sum_to_score():
    record = _full_record(confidence=0.3, red_team="rejected: nah", amount_eur=2000.0)

    result = decision_quality(record)

    assert sum(c["points"] for c in result["criteria"].values()) == result["score"]


# ---------------------------------------------------------------------------
# decision_outcome_matrix
# ---------------------------------------------------------------------------


def test_decision_outcome_matrix_good_decision_good_outcome():
    assert decision_outcome_matrix(75.0, 0.05) == "good decision, good outcome"


def test_decision_outcome_matrix_good_decision_bad_outcome_on_zero_alpha():
    assert decision_outcome_matrix(75.0, 0.0) == "good decision, bad outcome"


def test_decision_outcome_matrix_good_decision_bad_outcome_on_negative_alpha():
    assert decision_outcome_matrix(60.0, -0.02) == "good decision, bad outcome"


def test_decision_outcome_matrix_bad_decision_lucky_outcome():
    assert decision_outcome_matrix(59.9, 0.02) == "bad decision, lucky outcome"


def test_decision_outcome_matrix_bad_decision_bad_outcome():
    assert decision_outcome_matrix(10.0, -0.1) == "bad decision, bad outcome"


def test_decision_outcome_matrix_bad_decision_bad_outcome_on_zero_alpha():
    assert decision_outcome_matrix(0.0, 0.0) == "bad decision, bad outcome"


def test_decision_outcome_matrix_alpha_none_is_not_yet_measurable_regardless_of_quality():
    assert decision_outcome_matrix(90.0, None) == "not yet measurable"
    assert decision_outcome_matrix(5.0, None) == "not yet measurable"


# --- finding 25/27: min_sample <= 0 must degrade gracefully, never crash --------------


def test_personal_edge_zero_min_sample_with_empty_ledger_does_not_crash():
    result = personal_edge([], min_sample=0)
    assert result["overall"]["evidence_threshold_adjust"] == "insufficient_sample"
    assert result["overall"]["n"] == 0


def test_personal_edge_negative_min_sample_with_empty_ledger_does_not_crash():
    result = personal_edge([], min_sample=-1)
    assert result["overall"]["evidence_threshold_adjust"] == "insufficient_sample"


# --- finding 26: a bucket/index fill must be scoreable as "good decision" on the
# criteria that actually apply to it -- red_team/alternative/thesis_status/
# amount_within_cap are structurally inapplicable to buying an underweight bucket ------


def test_decision_quality_bucket_fill_can_reach_good_quality_threshold():
    bucket_fill = {
        "symbol": "SWDA.MI",
        "action": "BUY",
        "reason": "Fills underweight core equity bucket per target allocation, " * 2,
        "amount_eur": 500.0,
        "price": 92.31,
        "sources": ["target_allocation"],
        "confidence": 0.9,
        "decision_kind": "bucket",
    }
    result = decision_quality(bucket_fill)
    assert result["score"] >= 60.0


def test_decision_quality_bucket_fill_ignores_inapplicable_criteria():
    bucket_fill = {
        "reason": "x" * 40,
        "sources": ["target_allocation"],
        "confidence": 0.9,
        "price": 100.0,
        "decision_kind": "bucket",
    }
    result = decision_quality(bucket_fill)
    for name in ("red_team", "alternative_recorded", "thesis_status", "amount_within_cap"):
        assert result["criteria"][name]["max_points"] == 0


def test_decision_quality_stock_buy_still_uses_the_full_rubric_by_default():
    # decision_kind omitted (or "stock"): the original, stricter rubric must be unchanged.
    result = decision_quality(_full_record())
    assert result["score"] == 100
    assert result["criteria"]["amount_within_cap"]["max_points"] == 15
