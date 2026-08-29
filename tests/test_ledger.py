from datetime import date

import pytest

from portfolio_copilot.portfolio.ledger import (
    CandidateAtDecision,
    DecisionRecord,
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


def test_record_decision_rejects_a_replayed_identical_id(tmp_path):
    """A retried log_decision call (agent retry, or a skill re-run same-day for the same
    symbol) with the same deterministic id (date+symbol+action) must never silently double
    count -- it would inflate that one decision's weight in every aggregate stat and could
    cross the min_sample gate off of exactly one real decision."""
    record_decision(
        {"symbol": "MU", "action": "BUY", "reason": "r", "date": "2026-01-01"}, home=tmp_path
    )
    with pytest.raises(ValueError):
        record_decision(
            {"symbol": "MU", "action": "BUY", "reason": "r again", "date": "2026-01-01"},
            home=tmp_path,
        )
    # the failed replay must not have appended a second line
    assert len(load_decisions(tmp_path)) == 1


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


def test_candidates_field_defaults_to_empty_list_for_pre_existing_ledger_lines(tmp_path):
    """A decision recorded before `candidates` existed (no such key in the payload) must
    still load cleanly, defaulting to an empty list."""
    record_decision(
        {"symbol": "OLD", "action": "HOLD", "reason": "before candidates existed"},
        home=tmp_path,
    )
    loaded = load_decisions(tmp_path)[0]
    assert loaded.candidates == []


def test_candidates_field_round_trips_through_record_and_load(tmp_path):
    record_decision(
        {
            "symbol": "MU",
            "action": "BUY",
            "reason": "auction ranking recorded at decision time",
            "candidates": [
                {"symbol": "MU", "kind": "stock", "utility": 80.0, "price": 100.0},
                {
                    "symbol": "global_equity",
                    "kind": "bucket",
                    "utility": 60.0,
                    "price": 100.0,
                    "price_symbol": "VWCE.MI",
                },
                {"symbol": "cash", "kind": "cash", "utility": 55.0},
            ],
        },
        home=tmp_path,
    )
    loaded = load_decisions(tmp_path)[0]
    assert [c.symbol for c in loaded.candidates] == ["MU", "global_equity", "cash"]
    assert loaded.candidates[1].price_symbol == "VWCE.MI"
    assert loaded.candidates[2].price is None
    assert loaded.candidates[2].kind == "cash"


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


def test_decision_alpha_treats_nan_alternative_prices_as_missing_not_a_silent_nan():
    """NaN satisfies neither `is None` nor `<= 0` (NaN comparisons are always False), so it
    used to slip through as a 'valid' alternative price and poison decision_alpha with NaN
    instead of degrading to None like a genuinely missing alternative price does."""
    out = decision_alpha(100.0, 118.0, float("nan"), 130.0)
    assert out["alternative_return"] is None
    assert out["decision_alpha"] is None
    out2 = decision_alpha(100.0, 118.0, 120.0, float("nan"))
    assert out2["alternative_return"] is None
    assert out2["decision_alpha"] is None


def test_decision_alpha_rejects_nan_or_infinite_real_leg_prices():
    with pytest.raises(ValueError):
        decision_alpha(float("nan"), 118.0, None, None)
    with pytest.raises(ValueError):
        decision_alpha(100.0, float("inf"), None, None)


def test_decision_record_rejects_non_finite_price():
    with pytest.raises(ValueError):
        DecisionRecord(
            id="x", date="2026-01-01", symbol="MU", action="BUY", reason="r",
            price=float("nan"),
        )


def test_decision_record_rejects_non_finite_alternative_price():
    with pytest.raises(ValueError):
        DecisionRecord(
            id="x", date="2026-01-01", symbol="MU", action="BUY", reason="r",
            price=100.0, alternative="VWCE.MI", alternative_price=float("inf"),
        )


def test_candidate_at_decision_rejects_non_finite_price():
    with pytest.raises(ValueError):
        CandidateAtDecision(symbol="MU", kind="stock", price=float("nan"))


def test_load_decisions_raises_on_nan_price_instead_of_silently_loading_it(tmp_path):
    """A hand-edited/legacy line with a literal NaN price (a valid token to Python's
    stdlib json.loads by default) must fail DecisionRecord validation loudly, never load
    silently and propagate NaN into every downstream aggregate."""
    (tmp_path / "decisions.jsonl").write_text(
        '{"id":"x","date":"2024-01-01","symbol":"MU","action":"BUY","reason":"t","price":NaN}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_decisions(tmp_path)


def test_evaluate_decisions_nan_current_price_is_unmeasurable_not_a_poisoned_nan_alpha(
    tmp_path,
):
    """A NaN current price (e.g. from a flaky provider) for one decision's real leg must
    make that one row unmeasurable, never compute a NaN decision_alpha that then poisons
    mean_decision_alpha/hit_rate for the whole report."""
    record_decision(
        {"symbol": "GOOD", "action": "BUY", "price": 100.0, "alternative": "ALTG",
         "alternative_price": 100.0, "reason": "r", "date": "2026-01-01"},
        home=tmp_path,
    )
    record_decision(
        {"symbol": "BADPRICE", "action": "BUY", "price": 100.0, "alternative": "ALTB",
         "alternative_price": 100.0, "reason": "r", "date": "2026-01-01"},
        home=tmp_path,
    )
    report = evaluate_decisions(
        load_decisions(tmp_path),
        {"GOOD": 120.0, "ALTG": 110.0, "BADPRICE": float("nan"), "ALTB": 105.0},
        as_of=date(2026, 8, 28),
        min_days=90,
    )
    assert report["decisions_measured"] == 1
    assert report["decisions_unmeasurable"] == 1
    assert report["mean_decision_alpha"] == pytest.approx(0.10)
    assert report["hit_rate"] == 1.0


def test_evaluate_decisions_sell_treats_alternative_as_the_real_leg(tmp_path):
    """For a SELL, the money left `symbol` and moved into `alternative` -- `alternative` is
    the real (chosen) leg and `symbol`'s post-sale move is the foregone counterfactual,
    exactly like portfolio.opportunity's opportunity_cost already implements. A sell that
    exits a faller and rotates into a rally must score a POSITIVE decision_alpha."""
    record_decision(
        {"symbol": "OLDCO", "action": "SELL", "price": 50.0, "reason": "r",
         "alternative": "VWCE.MI", "alternative_price": 100.0, "date": "2026-01-01"},
        home=tmp_path,
    )
    report = evaluate_decisions(
        load_decisions(tmp_path),
        {"OLDCO": 40.0, "VWCE.MI": 130.0},
        as_of=date(2026, 8, 29),
        min_days=90,
    )
    row = report["rows"][0]
    assert row["status"] == "measured"
    assert row["real_return"] == pytest.approx(0.30)  # 130/100 - 1: the chosen leg (VWCE.MI)
    assert row["alternative_return"] == pytest.approx(-0.20)  # 40/50 - 1: the foregone OLDCO
    assert row["decision_alpha"] == pytest.approx(0.50)
    assert report["hit_rate"] == 1.0


def test_evaluate_decisions_bad_date_is_unmeasurable_not_a_crash(tmp_path):
    """One row with a non-ISO date (hand-edited, or written by a different format) must
    not abort the whole report -- every other, perfectly good decision must still be
    measured."""
    record_decision(
        {"symbol": "GOOD", "action": "BUY", "price": 100.0, "reason": "r",
         "date": "2026-01-01"},
        home=tmp_path,
    )
    (tmp_path / "decisions.jsonl").open("a", encoding="utf-8").write(
        '{"id":"bad","date":"01/02/2026","symbol":"BAD","action":"BUY","reason":"r",'
        '"price":10.0}\n'
    )
    report = evaluate_decisions(
        load_decisions(tmp_path),
        {"GOOD": 120.0, "BAD": 11.0},
        as_of=date(2026, 8, 29),
        min_days=90,
    )
    assert report["decisions_total"] == 2
    assert report["decisions_measured"] == 1
    bad_row = next(r for r in report["rows"] if r["id"] == "bad")
    assert bad_row["status"] == "unmeasurable"


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
