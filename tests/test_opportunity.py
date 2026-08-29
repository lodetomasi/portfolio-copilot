from datetime import date

import pytest

from portfolio_copilot.portfolio.ledger import DecisionRecord, load_decisions, record_decision
from portfolio_copilot.portfolio.opportunity import opportunity_cost, opportunity_report


def _rec(**kwargs) -> DecisionRecord:
    payload = {
        "id": "id1",
        "date": "2026-01-01",
        "symbol": "MU",
        "action": "BUY",
        "reason": "r",
        "price": 100.0,
    }
    payload.update(kwargs)
    return DecisionRecord(**payload)


# --- BUY: measured -------------------------------------------------------------------


def test_buy_measured_computes_regret_best_available_and_rank():
    rec = _rec(
        candidates=[
            {"symbol": "MU", "kind": "stock", "utility": 80.0, "price": 100.0},
            {
                "symbol": "global_equity",
                "kind": "bucket",
                "utility": 60.0,
                "price": 100.0,
                "price_symbol": "VWCE.MI",
            },
            {"symbol": "cash", "kind": "cash", "utility": 55.0},
        ]
    )
    result = opportunity_cost(rec, {"MU": 118.0, "VWCE.MI": 106.0})
    assert result["status"] == "measured"
    assert result["chosen"] == "MU"
    assert result["chosen_return"] == pytest.approx(0.18)
    by_symbol = {c["symbol"]: c["candidate_return"] for c in result["candidates"]}
    assert by_symbol["MU"] == pytest.approx(0.18)
    assert by_symbol["global_equity"] == pytest.approx(0.06)
    assert by_symbol["cash"] == 0.0
    assert result["best_available"] == pytest.approx(0.18)
    assert result["regret"] == pytest.approx(0.0)
    assert result["chosen_rank"] == 1
    assert result["unmeasurable_candidates"] == []


def test_cash_candidate_contributes_zero_return_without_needing_a_price():
    rec = _rec(candidates=[{"symbol": "cash", "kind": "cash"}])
    result = opportunity_cost(rec, {"MU": 90.0})  # chosen lost money
    cash_row = next(c for c in result["candidates"] if c["symbol"] == "cash")
    assert cash_row["candidate_return"] == 0.0
    assert result["best_available"] == 0.0
    assert result["regret"] == pytest.approx(0.10)  # keeping cash beat the -10% buy


# --- BUY: unmeasurable ----------------------------------------------------------------


def test_buy_unmeasurable_when_chosen_has_no_current_price():
    rec = _rec(candidates=[{"symbol": "MU", "kind": "stock", "price": 100.0}])
    result = opportunity_cost(rec, {"VWCE.MI": 106.0})
    assert result["status"] == "unmeasurable"
    assert "no price now" in result["why"]
    assert result["regret"] is None
    assert result["candidates"] == []


def test_buy_unmeasurable_when_chosen_has_no_decision_time_price():
    rec = _rec(price=None)
    result = opportunity_cost(rec, {"MU": 100.0})
    assert result["status"] == "unmeasurable"
    assert "no price then" in result["why"]


def test_buy_unmeasurable_when_no_candidates_are_priced():
    rec = _rec(candidates=[{"symbol": "GHOST", "kind": "stock", "price": None}])
    result = opportunity_cost(rec, {"MU": 118.0})
    assert result["status"] == "unmeasurable"
    assert result["why"] == "no priced candidates to compare against"
    assert result["chosen_return"] == pytest.approx(0.18)  # known, just nothing to compare to
    assert result["unmeasurable_candidates"] == [{"symbol": "GHOST", "why": "no price then"}]


def test_unmeasurable_candidates_are_listed_by_name_with_reason():
    rec = _rec(
        candidates=[
            {"symbol": "MU", "kind": "stock", "price": 100.0},
            {"symbol": "NOPRICE_THEN", "kind": "stock", "price": None},
            {"symbol": "NOPRICE_NOW", "kind": "stock", "price": 50.0},
        ]
    )
    result = opportunity_cost(rec, {"MU": 118.0})
    assert result["status"] == "measured"  # MU alone is enough to measure
    reasons = {u["symbol"]: u["why"] for u in result["unmeasurable_candidates"]}
    assert reasons == {"NOPRICE_THEN": "no price then", "NOPRICE_NOW": "no price now"}


# --- SELL semantics ---------------------------------------------------------------------


def test_sell_chosen_is_the_alternative_and_sold_symbol_becomes_kept_it_candidate():
    rec = _rec(
        symbol="OLDCO",
        action="SELL",
        price=50.0,
        alternative="VWCE.MI",
        alternative_price=100.0,
    )
    result = opportunity_cost(rec, {"OLDCO": 40.0, "VWCE.MI": 130.0})
    assert result["chosen"] == "VWCE.MI"
    assert result["chosen_return"] == pytest.approx(0.30)
    kept = next(c for c in result["candidates"] if c["symbol"] == "OLDCO")
    assert kept["note"] == "kept it"
    assert kept["candidate_return"] == pytest.approx(-0.20)
    # "kept it" is the only candidate here and it lost to selling: negative regret means
    # the decision beat the one alternative that was measurable.
    assert result["best_available"] == pytest.approx(-0.20)
    assert result["regret"] == pytest.approx(-0.50)
    assert result["chosen_rank"] == 1


def test_sell_regret_is_positive_when_keeping_the_position_would_have_won():
    rec = _rec(
        symbol="OLDCO",
        action="SELL",
        price=50.0,
        alternative="VWCE.MI",
        alternative_price=100.0,
    )
    result = opportunity_cost(rec, {"OLDCO": 90.0, "VWCE.MI": 105.0})
    assert result["chosen_return"] == pytest.approx(0.05)
    assert result["best_available"] == pytest.approx(0.8)
    assert result["regret"] == pytest.approx(0.75)
    assert result["chosen_rank"] == 2


def test_sell_chosen_leg_resolves_a_price_symbol_proxy_like_the_buy_branch():
    """The BUY branch resolves a price_symbol proxy for the chosen leg from
    decision.candidates (e.g. a bucket priced via its ETF ticker); the SELL branch hard
    coded `None` instead, so a SELL whose alternative is a bucket could never be measured
    even when its proxy's price was available in current_prices."""
    rec = _rec(
        symbol="OLDCO",
        action="SELL",
        price=50.0,
        alternative="global_equity",
        alternative_price=100.0,
        candidates=[
            {"symbol": "global_equity", "kind": "bucket", "price": 100.0,
             "price_symbol": "VWCE.MI"},
        ],
    )
    result = opportunity_cost(rec, {"OLDCO": 40.0, "VWCE.MI": 130.0})
    assert result["status"] == "measured"
    assert result["chosen_return"] == pytest.approx(0.30)  # 130/100 - 1, via the proxy


def test_sell_kept_it_candidate_resolves_a_price_symbol_proxy_too():
    """The reconstructed 'kept it' candidate (what if the sold bucket had not been sold)
    must also resolve a price_symbol proxy from decision.candidates, mirroring the BUY
    chosen-leg lookup -- otherwise a sold bucket's own counterfactual can never be
    measured regardless of what current_prices contains."""
    rec = _rec(
        symbol="global_equity",
        action="SELL",
        price=100.0,
        decision_kind="bucket",
        alternative="SGOV",
        alternative_price=90.0,
        candidates=[
            {"symbol": "global_equity", "kind": "bucket", "price": 105.0,
             "price_symbol": "VWCE.MI"},
        ],
    )
    result = opportunity_cost(rec, {"SGOV": 99.0, "VWCE.MI": 130.0})
    assert result["unmeasurable_candidates"] == []
    kept = next(c for c in result["candidates"] if c.get("note") == "kept it")
    assert kept["candidate_return"] == pytest.approx(130.0 / 100.0 - 1.0)


def test_sell_without_recorded_alternative_is_unmeasurable():
    rec = _rec(symbol="OLDCO", action="SELL", price=50.0, alternative=None)
    result = opportunity_cost(rec, {"OLDCO": 40.0})
    assert result["status"] == "unmeasurable"
    assert result["chosen"] is None
    assert result["why"] == "SELL has no recorded alternative"


# --- rank ties ----------------------------------------------------------------------------


def test_rank_ties_when_multiple_candidates_share_the_best_return():
    rec = _rec(
        candidates=[
            {"symbol": "MU", "kind": "stock", "price": 100.0},
            {"symbol": "TWIN_A", "kind": "stock", "price": 100.0},
            {"symbol": "TWIN_B", "kind": "stock", "price": 100.0},
        ]
    )
    result = opportunity_cost(rec, {"MU": 120.0, "TWIN_A": 120.0, "TWIN_B": 90.0})
    assert result["chosen_rank"] == 1  # tied for best: nothing strictly beats it
    assert result["regret"] == pytest.approx(0.0)


# --- NaN handling (finding 15) ---------------------------------------------------------


def test_nan_current_price_is_unmeasurable_not_a_silent_nan_regret():
    """A NaN current price for the chosen leg satisfies neither `is None` nor `<= 0`, so it
    must be treated as unmeasurable, never silently produce a NaN chosen_return/regret."""
    rec = _rec(candidates=[{"symbol": "MU", "kind": "stock", "price": 100.0}])
    result = opportunity_cost(rec, {"MU": float("nan")})
    assert result["status"] == "unmeasurable"
    assert "no price now" in result["why"]


def test_nan_candidate_price_is_dropped_as_unmeasurable_not_a_silent_nan():
    rec = _rec(
        candidates=[
            {"symbol": "MU", "kind": "stock", "price": 100.0},
            {"symbol": "NANNY", "kind": "stock", "price": 100.0},
        ]
    )
    result = opportunity_cost(rec, {"MU": 118.0, "NANNY": float("nan")})
    assert result["status"] == "measured"
    reasons = {u["symbol"]: u["why"] for u in result["unmeasurable_candidates"]}
    assert reasons == {"NANNY": "no price now"}


# --- determinism ----------------------------------------------------------------------------


def test_opportunity_cost_is_deterministic():
    rec = _rec(candidates=[{"symbol": "MU", "kind": "stock", "price": 100.0}])
    prices = {"MU": 110.0}
    assert opportunity_cost(rec, prices) == opportunity_cost(rec, prices)


# --- backward-compatible ledger round trip ---------------------------------------------


def test_ledger_round_trip_preserves_candidates_for_opportunity_cost(tmp_path):
    record_decision(
        {
            "symbol": "MU",
            "action": "BUY",
            "reason": "r",
            "price": 100.0,
            "date": "2026-01-01",
            "candidates": [
                {"symbol": "MU", "kind": "stock", "price": 100.0},
                {"symbol": "cash", "kind": "cash"},
            ],
        },
        home=tmp_path,
    )
    record_decision(
        {"symbol": "OLD", "action": "HOLD", "reason": "pre-existing", "price": 50.0,
         "date": "2026-01-01"},
        home=tmp_path,
    )
    loaded = load_decisions(tmp_path)
    assert loaded[0].candidates != []
    assert loaded[1].candidates == []  # recorded before this field existed: still loads fine

    mu_result = opportunity_cost(loaded[0], {"MU": 120.0})
    assert mu_result["status"] == "measured"

    old_result = opportunity_cost(loaded[1], {"OLD": 999.0})
    assert old_result["status"] == "unmeasurable"
    assert old_result["why"] == "no priced candidates to compare against"


# --- opportunity_report: bad date guard (finding 10) ------------------------------------


def test_report_bad_date_row_is_unmeasurable_not_a_crash():
    """A single row with a non-ISO date must not abort date.fromisoformat for the whole
    ledger -- every other decision must still be measured."""
    good = _rec(id="good", date="2026-01-01",
                candidates=[{"symbol": "MU", "kind": "stock", "price": 100.0}])
    bad = _rec(id="bad", date="01/02/2026", symbol="MU",
               candidates=[{"symbol": "MU", "kind": "stock", "price": 100.0}])
    report = opportunity_report(
        [good, bad], {"MU": 110.0}, as_of=date(2026, 8, 28), min_days=90
    )
    assert report["decisions_total"] == 2
    bad_row = next(r for r in report["rows"] if r["id"] == "bad")
    assert bad_row["status"] == "unmeasurable"
    good_row = next(r for r in report["rows"] if r["id"] == "good")
    assert good_row["status"] == "measured"


# --- opportunity_report: min_days filter ------------------------------------------------


def test_report_min_days_filters_recent_decisions():
    old = _rec(id="old", date="2026-01-01",
               candidates=[{"symbol": "MU", "kind": "stock", "price": 100.0}])
    recent = _rec(id="recent", date="2026-08-01",
                  candidates=[{"symbol": "MU", "kind": "stock", "price": 100.0}])
    report = opportunity_report([old, recent], {"MU": 110.0}, as_of=date(2026, 8, 28), min_days=90)
    assert report["decisions_total"] == 1
    assert report["rows"][0]["id"] == "old"


# --- opportunity_report: min_sample gate -------------------------------------------------


def test_report_min_sample_gate_wording():
    decisions = [
        _rec(id=f"d{i}", date="2026-01-01",
             candidates=[{"symbol": "MU", "kind": "stock", "price": 100.0}])
        for i in range(3)
    ]
    report = opportunity_report(
        decisions, {"MU": 110.0}, as_of=date(2026, 8, 28), min_days=90, min_sample=10
    )
    assert report["n_measured"] == 3
    assert report["verdict"] == "insufficient_sample: not yet distinguishable from luck (n=3 < 10)"


# --- opportunity_report: verdicts ---------------------------------------------------------


def test_report_skill_signal_when_regret_is_low_and_mostly_within_tolerance():
    decisions = [
        _rec(id=f"d{i}", date="2026-01-01",
             candidates=[{"symbol": "MU", "kind": "stock", "price": 100.0}])
        for i in range(10)
    ]
    report = opportunity_report(
        decisions, {"MU": 110.0}, as_of=date(2026, 8, 28), min_days=90, min_sample=10
    )
    assert report["mean_regret"] == pytest.approx(0.0)
    assert report["share_within_1pp"] == 1.0
    assert report["share_chosen_was_best"] == 1.0
    assert report["n_unmeasurable"] == 0
    assert report["verdict"] == "skill_signal"


def test_report_review_process_when_mean_regret_is_high():
    decisions = [
        _rec(
            id=f"d{i}",
            date="2026-01-01",
            symbol="MU",
            price=100.0,
            candidates=[
                {"symbol": "MU", "kind": "stock", "price": 100.0},
                {"symbol": "WINNER", "kind": "stock", "price": 100.0},
            ],
        )
        for i in range(10)
    ]
    report = opportunity_report(
        decisions,
        {"MU": 100.0, "WINNER": 200.0},
        as_of=date(2026, 8, 28),
        min_days=90,
        min_sample=10,
    )
    assert report["mean_regret"] == pytest.approx(1.0)
    assert report["verdict"] == "review_process"


def test_report_neutral_when_regret_moderate():
    # regret of 0.02 per decision: > tolerance (0.01) but well under review_process (0.03)
    decisions = [
        _rec(
            id=f"d{i}",
            date="2026-01-01",
            candidates=[
                {"symbol": "MU", "kind": "stock", "price": 100.0},
                {"symbol": "SLIGHT_WINNER", "kind": "stock", "price": 100.0},
            ],
        )
        for i in range(10)
    ]
    report = opportunity_report(
        decisions,
        {"MU": 110.0, "SLIGHT_WINNER": 112.0},
        as_of=date(2026, 8, 28),
        min_days=90,
        min_sample=10,
    )
    assert report["mean_regret"] == pytest.approx(0.02)
    assert report["verdict"] == "neutral"
