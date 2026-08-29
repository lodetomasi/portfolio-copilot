"""Offline, deterministic tests for the thesis engine (falsifiers + status transitions).

CLAUDE.md non-negotiables exercised here: never invent data (missing metrics degrade a
falsifier to "unavailable", never to a guessed trip/no-trip); status derivation is pure
Python, never an LLM judgement call; persistence round-trips through a local JSON file
under a caller-controlled home directory, never a broker/cloud store.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from portfolio_copilot.portfolio.thesis import (
    Falsifier,
    Thesis,
    ThesisCheck,
    _status_delta,
    check_thesis,
    evaluate_thesis,
    load_theses,
    save_thesis,
    theses_path,
)


def _thesis(**overrides) -> Thesis:
    payload = {
        "symbol": "MU",
        "claims": ["HBM demand keeps growing", "margins expand with mix shift"],
        "falsifiers": [
            {
                "metric": "revenue_growth",
                "op": "<",
                "threshold": 0.05,
                "label": "revenue growth stalls below 5%",
            },
            {
                "metric": "gross_margin",
                "op": "<",
                "threshold": 0.30,
                "label": "gross margin drops below 30%",
            },
        ],
        "created": "2026-01-01",
        "history": [],
    }
    payload.update(overrides)
    return Thesis(**payload)


# --- status branches ---------------------------------------------------------------


def test_stable_when_no_falsifier_trips_and_no_history():
    thesis = _thesis()
    check = evaluate_thesis(thesis, {"revenue_growth": 0.20, "gross_margin": 0.40}, "2026-02-01")
    assert check.status == "STABLE"
    assert check.tripped == []
    assert check.checked == 2
    assert check.unavailable == []


def test_strengthening_when_previous_check_had_trips_and_now_none_trip():
    previous = ThesisCheck(
        date="2026-01-15", status="WEAKENING", tripped=["revenue growth stalls below 5%"],
        checked=2, unavailable=[],
    )
    thesis = _thesis(history=[previous])
    check = evaluate_thesis(thesis, {"revenue_growth": 0.20, "gross_margin": 0.40}, "2026-02-01")
    assert check.status == "STRENGTHENING"
    assert check.tripped == []


def test_weakening_when_fewer_than_half_of_checkable_trip():
    thesis = _thesis(
        falsifiers=[
            {"metric": "revenue_growth", "op": "<", "threshold": 0.05, "label": "growth stalls"},
            {"metric": "gross_margin", "op": "<", "threshold": 0.30, "label": "margin drops"},
            {"metric": "debt_to_equity", "op": ">", "threshold": 2.0, "label": "leverage spikes"},
        ]
    )
    metrics = {"revenue_growth": 0.01, "gross_margin": 0.40, "debt_to_equity": 0.5}
    check = evaluate_thesis(thesis, metrics, "2026-02-01")
    assert check.checked == 3
    assert check.tripped == ["growth stalls"]
    assert check.status == "WEAKENING"


def test_broken_when_half_or_more_of_checkable_trip():
    thesis = _thesis()  # two falsifiers
    metrics = {"revenue_growth": 0.01, "gross_margin": 0.10}
    check = evaluate_thesis(thesis, metrics, "2026-02-01")
    assert check.checked == 2
    assert len(check.tripped) == 2
    assert check.status == "BROKEN"


def test_broken_at_exactly_half_boundary():
    thesis = _thesis(
        falsifiers=[
            {"metric": "revenue_growth", "op": "<", "threshold": 0.05, "label": "growth stalls"},
            {"metric": "gross_margin", "op": "<", "threshold": 0.30, "label": "margin drops"},
        ]
    )
    metrics = {"revenue_growth": 0.01, "gross_margin": 0.40}  # exactly 1 of 2 trips == 50%
    check = evaluate_thesis(thesis, metrics, "2026-02-01")
    assert check.checked == 2
    assert len(check.tripped) == 1
    assert check.status == "BROKEN"


def test_unverifiable_when_no_metric_available():
    thesis = _thesis()
    check = evaluate_thesis(thesis, {}, "2026-02-01")
    assert check.status == "UNVERIFIABLE"
    assert check.checked == 0
    assert sorted(check.unavailable) == ["gross_margin", "revenue_growth"]


def test_partial_unavailable_metrics_only_count_available_ones():
    thesis = _thesis()
    check = evaluate_thesis(thesis, {"revenue_growth": 0.20}, "2026-02-01")
    assert check.checked == 1
    assert check.unavailable == ["gross_margin"]
    assert check.status == "STABLE"


# --- purity --------------------------------------------------------------------------


def test_evaluate_thesis_is_pure_same_inputs_same_output_and_no_mutation():
    thesis = _thesis()
    metrics = {"revenue_growth": 0.01, "gross_margin": 0.40}
    first = evaluate_thesis(thesis, metrics, "2026-02-01")
    second = evaluate_thesis(thesis, metrics, "2026-02-01")
    assert first == second
    assert thesis.history == []  # evaluate_thesis never mutates the thesis it is given


# --- validation ------------------------------------------------------------------------


def test_invalid_op_rejected():
    with pytest.raises(ValidationError):
        Falsifier(metric="revenue_growth", op="!=", threshold=0.05, label="bad op")


# --- persistence -----------------------------------------------------------------------


def test_save_and_load_roundtrip(tmp_path):
    saved = save_thesis(
        {
            "symbol": "mu",
            "claims": ["HBM demand keeps growing"],
            "falsifiers": [
                {"metric": "revenue_growth", "op": "<", "threshold": 0.05, "label": "growth stalls"}
            ],
            "created": "2026-01-01",
        },
        home=tmp_path,
    )
    assert saved.symbol == "MU"
    assert (tmp_path / "theses.json").exists()
    loaded = load_theses(tmp_path)
    assert set(loaded) == {"MU"}
    assert loaded["MU"].claims == ["HBM demand keeps growing"]
    assert loaded["MU"].falsifiers[0].op == "<"


def test_save_thesis_upserts_by_symbol(tmp_path):
    save_thesis(
        {"symbol": "MU", "claims": ["a"], "falsifiers": [], "created": "2026-01-01"},
        home=tmp_path,
    )
    save_thesis(
        {"symbol": "MU", "claims": ["a", "updated"], "falsifiers": [], "created": "2026-01-01"},
        home=tmp_path,
    )
    save_thesis(
        {"symbol": "AAPL", "claims": ["b"], "falsifiers": [], "created": "2026-01-02"},
        home=tmp_path,
    )
    loaded = load_theses(tmp_path)
    assert set(loaded) == {"MU", "AAPL"}
    assert loaded["MU"].claims == ["a", "updated"]


def test_load_theses_returns_empty_dict_when_file_missing(tmp_path):
    assert load_theses(tmp_path) == {}


def test_theses_path_creates_home_directory(tmp_path):
    home = tmp_path / "nested" / "dir"
    path = theses_path(home)
    assert path == home / "theses.json"
    assert home.exists()


# --- check_thesis (load + evaluate + append history + persist) -------------------------


def test_check_thesis_full_flow_appends_history_and_reports_delta(tmp_path):
    save_thesis(
        {
            "symbol": "MU",
            "claims": ["HBM demand keeps growing"],
            "falsifiers": [
                {
                    "metric": "revenue_growth", "op": "<", "threshold": 0.05,
                    "label": "growth stalls",
                },
                {
                    "metric": "gross_margin", "op": "<", "threshold": 0.30,
                    "label": "margin drops",
                },
            ],
            "created": "2026-01-01",
        },
        home=tmp_path,
    )

    first = check_thesis(
        "mu", {"revenue_growth": 0.01, "gross_margin": 0.10}, "2026-02-01", home=tmp_path
    )
    assert first["symbol"] == "MU"
    assert first["previous_status"] is None
    assert first["status"] == "BROKEN"
    assert first["delta"] == "new"

    second = check_thesis(
        "MU", {"revenue_growth": 0.20, "gross_margin": 0.40}, "2026-03-01", home=tmp_path
    )
    assert second["previous_status"] == "BROKEN"
    assert second["status"] == "STRENGTHENING"
    assert second["delta"] == "improved"

    persisted = load_theses(tmp_path)["MU"]
    assert [c.date for c in persisted.history] == ["2026-02-01", "2026-03-01"]
    assert persisted.history[0].status == "BROKEN"
    assert persisted.history[1].status == "STRENGTHENING"


def test_check_thesis_unknown_symbol_raises(tmp_path):
    with pytest.raises(ValueError):
        check_thesis("NOPE", {"revenue_growth": 0.1}, "2026-02-01", home=tmp_path)


def test_check_thesis_worsened_delta(tmp_path):
    save_thesis(
        {
            "symbol": "MU",
            "claims": ["c"],
            "falsifiers": [
                {
                    "metric": "revenue_growth", "op": "<", "threshold": 0.05,
                    "label": "growth stalls",
                },
                {
                    "metric": "gross_margin", "op": "<", "threshold": 0.30,
                    "label": "margin drops",
                },
            ],
            "created": "2026-01-01",
        },
        home=tmp_path,
    )
    check_thesis("MU", {"revenue_growth": 0.20, "gross_margin": 0.40}, "2026-02-01", home=tmp_path)
    second = check_thesis(
        "MU", {"revenue_growth": 0.01, "gross_margin": 0.10}, "2026-03-01", home=tmp_path
    )
    assert second["previous_status"] == "STABLE"
    assert second["status"] == "BROKEN"
    assert second["delta"] == "worsened"


def test_theses_json_is_plain_readable_json(tmp_path):
    save_thesis(
        {"symbol": "MU", "claims": ["a"], "falsifiers": [], "created": "2026-01-01"},
        home=tmp_path,
    )
    raw = json.loads((tmp_path / "theses.json").read_text(encoding="utf-8"))
    assert "MU" in raw
    assert raw["MU"]["symbol"] == "MU"


# --- finding 1: a previously-tripped falsifier going missing must not read as STRENGTHENING ---


def test_strengthening_requires_all_previously_tripped_falsifiers_to_be_reverified():
    previous = ThesisCheck(
        date="2026-01-15", status="BROKEN",
        tripped=["revenue growth stalls below 5%", "gross margin drops below 30%"],
        checked=2, unavailable=[],
    )
    thesis = _thesis(history=[previous])
    # revenue_growth (one of the two previously-tripped metrics) is simply absent this run;
    # gross_margin looks fine. Nothing was actually verified to have improved.
    check = evaluate_thesis(thesis, {"gross_margin": 0.40}, "2026-02-01")
    assert check.status == "UNVERIFIABLE"
    assert check.tripped == []
    assert check.unavailable == ["revenue_growth"]


def test_strengthening_still_applies_when_all_previously_tripped_metrics_are_reverified():
    previous = ThesisCheck(
        date="2026-01-15", status="BROKEN",
        tripped=["revenue growth stalls below 5%", "gross margin drops below 30%"],
        checked=2, unavailable=[],
    )
    thesis = _thesis(history=[previous])
    check = evaluate_thesis(
        thesis, {"revenue_growth": 0.20, "gross_margin": 0.40}, "2026-02-01"
    )
    assert check.status == "STRENGTHENING"


# --- finding 2: a full data blackout right after BROKEN must not read as "improved" -------


def test_status_delta_blackout_after_broken_is_not_improved():
    assert _status_delta("BROKEN", "UNVERIFIABLE") == "unchanged"


def test_status_delta_blackout_after_weakening_is_not_improved():
    assert _status_delta("WEAKENING", "UNVERIFIABLE") == "unchanged"


def test_status_delta_unverifiable_after_stable_is_still_worsened():
    # STABLE is better than UNVERIFIABLE, so losing data here is a real degradation.
    assert _status_delta("STABLE", "UNVERIFIABLE") == "worsened"


def test_check_thesis_blackout_after_broken_reports_unchanged_not_improved(tmp_path):
    save_thesis(
        {
            "symbol": "MU", "claims": ["c"],
            "falsifiers": [
                {"metric": "gross_margin", "op": "<", "threshold": 0.30, "label": "margin drops"}
            ],
            "created": "2026-01-01",
        },
        home=tmp_path,
    )
    first = check_thesis("MU", {"gross_margin": 0.10}, "2026-02-01", home=tmp_path)
    assert first["status"] == "BROKEN"
    second = check_thesis("MU", {}, "2026-03-01", home=tmp_path)  # total blackout
    assert second["status"] == "UNVERIFIABLE"
    assert second["delta"] == "unchanged"


# --- finding 3: a NaN metric must degrade to "unavailable", never "checked, did not trip" --


def test_nan_metric_is_treated_as_unavailable_not_as_did_not_trip():
    thesis = _thesis()
    check = evaluate_thesis(
        thesis, {"revenue_growth": float("nan"), "gross_margin": 0.40}, "2026-02-01"
    )
    assert check.checked == 1
    assert check.unavailable == ["revenue_growth"]
    assert check.status == "STABLE"


def test_nan_threshold_is_rejected_by_falsifier_validation():
    with pytest.raises(ValidationError):
        Falsifier(metric="revenue_growth", op="<", threshold=float("nan"), label="bad threshold")


def test_infinite_threshold_is_rejected_by_falsifier_validation():
    with pytest.raises(ValidationError):
        Falsifier(metric="revenue_growth", op="<", threshold=float("inf"), label="bad threshold")


# --- finding 4: corrupted theses.json degrades cleanly, and writes are atomic --------------


def test_load_theses_raises_clear_value_error_on_corrupted_json(tmp_path):
    (tmp_path / "theses.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_theses(tmp_path)


def test_load_theses_raises_clear_value_error_on_invalid_schema(tmp_path):
    (tmp_path / "theses.json").write_text(
        json.dumps({"MU": {"symbol": "MU"}}), encoding="utf-8"
    )  # missing required fields (claims, created)
    with pytest.raises(ValueError):
        load_theses(tmp_path)


def test_write_theses_is_atomic_no_leftover_temp_file(tmp_path):
    save_thesis(
        {"symbol": "MU", "claims": ["a"], "falsifiers": [], "created": "2026-01-01"},
        home=tmp_path,
    )
    files = {p.name for p in tmp_path.iterdir()}
    assert files == {"theses.json"}  # no stray .tmp/.bak file left behind


# --- finding 5: whitespace in a symbol must not orphan a thesis -----------------------------


def test_save_thesis_strips_whitespace_from_symbol(tmp_path):
    saved = save_thesis(
        {"symbol": " MU", "claims": ["a"], "falsifiers": [], "created": "2026-01-01"},
        home=tmp_path,
    )
    assert saved.symbol == "MU"
    assert set(load_theses(tmp_path)) == {"MU"}


def test_check_thesis_finds_thesis_saved_with_stray_whitespace(tmp_path):
    save_thesis(
        {"symbol": " MU", "claims": ["a"], "falsifiers": [], "created": "2026-01-01"},
        home=tmp_path,
    )
    result = check_thesis("MU", {}, "2026-02-01", home=tmp_path)
    assert result["symbol"] == "MU"


def test_check_thesis_strips_whitespace_from_lookup_symbol(tmp_path):
    save_thesis(
        {"symbol": "MU", "claims": ["a"], "falsifiers": [], "created": "2026-01-01"},
        home=tmp_path,
    )
    result = check_thesis(" mu ", {}, "2026-02-01", home=tmp_path)
    assert result["symbol"] == "MU"


def test_write_theses_failure_never_corrupts_existing_file(tmp_path, monkeypatch):
    save_thesis(
        {"symbol": "MU", "claims": ["a"], "falsifiers": [], "created": "2026-01-01"},
        home=tmp_path,
    )
    original = (tmp_path / "theses.json").read_text(encoding="utf-8")

    import portfolio_copilot.portfolio.thesis as thesis_module

    def failing_replace(src, dst):
        raise OSError("simulated crash before the atomic rename completes")

    monkeypatch.setattr(thesis_module.os, "replace", failing_replace)
    with pytest.raises(OSError):
        save_thesis(
            {"symbol": "AAPL", "claims": ["b"], "falsifiers": [], "created": "2026-01-02"},
            home=tmp_path,
        )

    assert (tmp_path / "theses.json").read_text(encoding="utf-8") == original  # untouched
