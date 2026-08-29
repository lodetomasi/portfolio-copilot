from datetime import date

import pytest

from portfolio_copilot.portfolio.ledger import (
    decision_alpha,
    evaluate_decisions,
    load_decisions,
    record_decision,
)


def test_record_and_load_roundtrip(tmp_path):
    rec = record_decision(
        {"symbol": "mu", "action": "BUY", "score": 86, "confidence": 0.81, "price": 100.0,
         "amount_eur": 300, "reason": "HBM growth", "alternative": "VWCE.MI",
         "alternative_price": 120.0, "red_team": "passed", "date": "2026-05-01"},
        home=tmp_path,
    )
    assert rec.id == "2026-05-01:MU:BUY" and rec.symbol == "MU"
    record_decision({"symbol": "ABC", "action": "HOLD", "reason": "nothing better"}, home=tmp_path)
    loaded = load_decisions(tmp_path)
    assert [d.symbol for d in loaded] == ["MU", "ABC"]
    assert loaded[0].alternative == "VWCE.MI"
    assert (tmp_path / "decisions.jsonl").read_text().count("\n") == 2


def test_record_rejects_invalid_action_or_confidence(tmp_path):
    with pytest.raises(ValueError):
        record_decision({"symbol": "X", "action": "YOLO", "reason": "r"}, home=tmp_path)
    with pytest.raises(ValueError):
        record_decision(
            {"symbol": "X", "action": "BUY", "reason": "r", "confidence": 1.5}, home=tmp_path
        )


def test_load_empty_ledger(tmp_path):
    assert load_decisions(tmp_path) == []


def test_optional_enrichment_fields_default_to_none_and_are_backward_compatible(tmp_path):
    """A decision recorded before category/theme/thesis_status/cap_eur existed (no such
    keys in the payload) must still load cleanly with all four defaulting to None."""
    record_decision({"symbol": "OLD", "action": "HOLD", "reason": "pre-existing shape"},
                     home=tmp_path)
    loaded = load_decisions(tmp_path)[0]
    assert loaded.category is None
    assert loaded.theme is None
    assert loaded.thesis_status is None
    assert loaded.cap_eur is None


def test_optional_enrichment_fields_round_trip_through_record_and_load(tmp_path):
    record_decision(
        {
            "symbol": "NEW",
            "action": "BUY",
            "reason": "personal_edge/decision_quality enrichment",
            "category": "semiconductors",
            "theme": "ai_capex",
            "thesis_status": "STABLE",
            "cap_eur": 500.0,
        },
        home=tmp_path,
    )
    loaded = load_decisions(tmp_path)[0]
    assert loaded.category == "semiconductors"
    assert loaded.theme == "ai_capex"
    assert loaded.thesis_status == "STABLE"
    assert loaded.cap_eur == 500.0


def test_decision_alpha_arithmetic_and_missing_alternative():
    out = decision_alpha(100, 118, 120, 127.2)
    assert out["real_return"] == pytest.approx(0.18)
    assert out["alternative_return"] == pytest.approx(0.06)
    assert out["decision_alpha"] == pytest.approx(0.12)
    assert decision_alpha(100, 90, None, None)["decision_alpha"] is None
    with pytest.raises(ValueError):
        decision_alpha(0, 10, None, None)


def test_evaluate_decisions_respects_min_days_and_marks_unmeasurable(tmp_path):
    record_decision({"symbol": "MU", "action": "BUY", "price": 100, "reason": "r",
                     "alternative": "VWCE", "alternative_price": 100, "date": "2026-01-01"},
                    home=tmp_path)
    record_decision({"symbol": "NEW", "action": "BUY", "price": 50, "reason": "r",
                     "date": "2026-08-20"}, home=tmp_path)  # too recent
    record_decision({"symbol": "GONE", "action": "BUY", "price": 10, "reason": "r",
                     "date": "2026-02-01"}, home=tmp_path)  # no current price
    report = evaluate_decisions(
        load_decisions(tmp_path),
        {"MU": 90.0, "VWCE": 105.0, "NEW": 60.0, "GONE": None},
        as_of=date(2026, 8, 28),
        min_days=90,
    )
    assert report["decisions_total"] == 3
    assert report["decisions_measured"] == 1
    assert report["decisions_unmeasurable"] == 1
    measured = next(r for r in report["rows"] if r["status"] == "measured")
    assert measured["id"] == "2026-01-01:MU:BUY"
    assert measured["decision_alpha"] == pytest.approx(-0.10 - 0.05)
    assert report["hit_rate"] == 0.0
    assert report["sample_warning"] is not None


def test_evaluate_decisions_marks_nonpositive_price_unmeasurable_without_crashing(tmp_path):
    """A single zero/negative decision or current price must not abort the whole report."""
    record_decision(
        {"symbol": "OOPS", "action": "BUY", "price": 0.0, "reason": "r", "date": "2026-01-01"},
        home=tmp_path,
    )
    record_decision(
        {"symbol": "BANKRUPT", "action": "BUY", "price": 10, "reason": "r", "date": "2026-01-01"},
        home=tmp_path,
    )
    record_decision(
        {"symbol": "GOOD", "action": "BUY", "price": 100.0, "reason": "r", "date": "2026-01-01"},
        home=tmp_path,
    )
    report = evaluate_decisions(
        load_decisions(tmp_path),
        {"OOPS": 5.0, "BANKRUPT": 0.0, "GOOD": 120.0},
        as_of=date(2026, 8, 28),
        min_days=90,
    )
    assert report["decisions_total"] == 3
    assert report["decisions_measured"] == 1
    assert report["decisions_unmeasurable"] == 2
    measured = next(r for r in report["rows"] if r["status"] == "measured")
    assert measured["id"] == "2026-01-01:GOOD:BUY"
    assert measured["real_return"] == pytest.approx(0.20)
