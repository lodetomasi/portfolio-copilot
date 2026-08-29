"""Tests for the revisions and catalysts scoring components (free-data proxies).

Offline and deterministic: pure StockSnapshot fixtures through score_snapshot, no
network, no provider objects.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from portfolio_copilot.models import Provenance, StockSnapshot
from portfolio_copilot.scoring.engine import DEFAULT_WEIGHTS, score_snapshot

_AS_OF = datetime(2026, 1, 1, tzinfo=UTC)


def _prov(confidence: float = 0.75) -> Provenance:
    return Provenance(source="yfinance", as_of=_AS_OF, confidence=confidence)


def _snap(**kw) -> StockSnapshot:
    kw.setdefault("ticker", "REV")
    kw.setdefault("provenance", _prov())
    return StockSnapshot(**kw)


def _component(score, name):
    return next(c for c in score.components if c.name == name)


# --------------------------------------------------------------------------------------
# existing weights untouched
# --------------------------------------------------------------------------------------


def test_default_weights_unchanged():
    assert DEFAULT_WEIGHTS == {
        "growth": 20,
        "quality": 20,
        "valuation": 15,
        "momentum": 15,
        "revisions": 10,
        "catalysts": 10,
        "risk": 10,
    }


# --------------------------------------------------------------------------------------
# all-None snapshot: unchanged behaviour (score 50 / insufficient data)
# --------------------------------------------------------------------------------------


def test_all_none_snapshot_revisions_and_catalysts_unavailable_score_50():
    snap = _snap()
    score = score_snapshot(snap)

    revisions = _component(score, "revisions")
    catalysts = _component(score, "catalysts")

    assert revisions.available is False
    assert revisions.score == 50.0
    assert catalysts.available is False
    assert catalysts.score == 50.0

    assert score.score == 50.0
    assert score.category == "UNRATED / NO DATA"
    assert score.reasons == [
        "data coverage 0%",
        "provider confidence 75%",
        "Insufficient data: do not use this score for a decision",
    ]


# --------------------------------------------------------------------------------------
# revisions availability and values
# --------------------------------------------------------------------------------------


def test_revisions_available_with_single_sub_indicator():
    snap = _snap(est_eps_growth_1y=0.40)  # saturates the good end: -0.10..0.40
    score = score_snapshot(snap)
    revisions = _component(score, "revisions")

    assert revisions.available is True
    assert revisions.score == 100.0


def test_revisions_is_mean_of_available_sub_indicators():
    # est_eps_growth_1y=0.40 -> 100 ; target_upside=-0.20 -> 0 ; mean == 50
    snap = _snap(est_eps_growth_1y=0.40, target_upside=-0.20)
    score = score_snapshot(snap)
    revisions = _component(score, "revisions")

    assert revisions.available is True
    assert revisions.score == 50.0


def test_revisions_uses_all_documented_sub_indicators():
    snap = _snap(
        est_eps_growth_1y=0.15,
        est_revenue_growth_1y=0.125,
        revision_balance=0.0,
        consensus_score=0.0,
        target_upside=0.10,
        revision_net_90d=0,
        revision_pt_change_90d=0.0,
        surprise_mean_8q=0.025,
        surprise_positive_share_8q=0.575,
    )
    score = score_snapshot(snap)
    revisions = _component(score, "revisions")

    # every sub-indicator sits at the midpoint of its (bad, good) band -> ~50
    assert revisions.available is True
    assert 49.0 <= revisions.score <= 51.0


# --------------------------------------------------------------------------------------
# thin analyst coverage shrink
# --------------------------------------------------------------------------------------


def test_thin_analyst_coverage_shrinks_revisions_toward_50_and_flags_reason():
    snap = _snap(est_eps_growth_1y=0.40, analyst_count=1)  # raw would be 100
    score = score_snapshot(snap)
    revisions = _component(score, "revisions")

    # 50 + (100 - 50) * 1 / 3, same evaluation order as the engine
    assert revisions.score == 50.0 + (100.0 - 50.0) * 1 / 3.0
    assert "thin analyst coverage" in revisions.reasons


def test_analyst_count_of_zero_fully_shrinks_to_neutral():
    snap = _snap(est_eps_growth_1y=0.40, analyst_count=0)
    score = score_snapshot(snap)
    revisions = _component(score, "revisions")

    assert revisions.score == 50.0
    assert "thin analyst coverage" in revisions.reasons


def test_analyst_count_of_three_or_more_does_not_shrink():
    snap = _snap(est_eps_growth_1y=0.40, analyst_count=3)
    score = score_snapshot(snap)
    revisions = _component(score, "revisions")

    assert revisions.score == 100.0
    assert "thin analyst coverage" not in revisions.reasons


def test_thin_coverage_with_no_revisions_data_stays_unavailable_no_reason():
    snap = _snap(analyst_count=1)
    score = score_snapshot(snap)
    revisions = _component(score, "revisions")

    assert revisions.available is False
    assert revisions.reasons == ["Data unavailable in free V1 provider"]


# --------------------------------------------------------------------------------------
# catalysts: event density, direction-agnostic
# --------------------------------------------------------------------------------------


def test_catalysts_earnings_proximity_high_score_when_earnings_imminent():
    snap = _snap(days_to_next_earnings=5)
    score = score_snapshot(snap)
    catalysts = _component(score, "catalysts")

    assert catalysts.available is True
    assert catalysts.score == 95.0  # 100 - min(100, 5)
    assert "events ahead/behind, not a direction" in catalysts.reasons


def test_catalysts_earnings_far_away_scores_low():
    snap = _snap(days_to_next_earnings=90)
    score = score_snapshot(snap)
    catalysts = _component(score, "catalysts")

    assert catalysts.score == 10.0  # 100 - min(100, 90)


def test_catalysts_available_from_insider_activity_alone():
    snap = _snap(insider_form4_90d=6)  # saturates good end of 0..6
    score = score_snapshot(snap)
    catalysts = _component(score, "catalysts")

    assert catalysts.available is True
    assert catalysts.score == 100.0


def test_catalysts_available_from_filings_flow_alone():
    snap = _snap(filings_8k_90d=0)  # saturates bad end of 0..6
    score = score_snapshot(snap)
    catalysts = _component(score, "catalysts")

    assert catalysts.available is True
    assert catalysts.score == 0.0


def test_catalysts_is_mean_of_all_three_sub_indicators_when_present():
    # earnings proximity = 100 - 30 = 70 ; insider = _linear(3,0,6) = 50 ; filings = same = 50
    snap = _snap(days_to_next_earnings=30, insider_form4_90d=3, filings_8k_90d=3)
    score = score_snapshot(snap)
    catalysts = _component(score, "catalysts")

    assert catalysts.score == (70.0 + 50.0 + 50.0) / 3


def test_catalysts_reasons_never_imply_direction():
    snap = _snap(days_to_next_earnings=5)
    score = score_snapshot(snap)
    catalysts = _component(score, "catalysts")

    assert catalysts.reasons == ["events ahead/behind, not a direction"]


# --------------------------------------------------------------------------------------
# coverage / confidence rise when the new components are present
# --------------------------------------------------------------------------------------


def test_coverage_and_confidence_rise_when_revisions_and_catalysts_present():
    base = _snap(provenance=_prov(confidence=1.0))
    enriched = _snap(
        est_eps_growth_1y=0.15,
        days_to_next_earnings=10,
        provenance=_prov(confidence=1.0),
    )

    base_score = score_snapshot(base)
    enriched_score = score_snapshot(enriched)

    base_coverage = float(base_score.reasons[0].split()[-1].rstrip("%"))
    enriched_coverage = float(enriched_score.reasons[0].split()[-1].rstrip("%"))

    assert enriched_coverage > base_coverage
    assert enriched_score.confidence > base_score.confidence


def test_top_level_reasons_list_available_components():
    snap = _snap(est_eps_growth_1y=0.15, days_to_next_earnings=10)
    score = score_snapshot(snap)

    reasons_line = next(r for r in score.reasons if r.startswith("available components:"))
    assert "revisions" in reasons_line
    assert "catalysts" in reasons_line


# --------------------------------------------------------------------------------------
# determinism
# --------------------------------------------------------------------------------------


# --------------------------------------------------------------------------------------
# thin-coverage shrink must not punish event/history-based sub-indicators (finding 4)
# --------------------------------------------------------------------------------------


def test_thin_analyst_count_does_not_shrink_purely_event_based_revisions():
    # revision_net_90d and surprise_mean_8q are event/history-based, not tied to how many
    # analysts currently cover the name -- a thin analyst_count must not shrink them.
    snap = _snap(revision_net_90d=4, surprise_mean_8q=0.10, analyst_count=1)
    score = score_snapshot(snap)
    revisions = _component(score, "revisions")

    assert revisions.score == 100.0
    assert "thin analyst coverage" not in revisions.reasons


def test_thin_analyst_count_shrinks_only_the_opinion_based_share():
    # est_eps_growth_1y (opinion) saturates 100; revision_net_90d (event) also saturates 100.
    # Only the opinion half should be shrunk toward 50 by thin coverage.
    snap = _snap(est_eps_growth_1y=0.40, revision_net_90d=4, analyst_count=1)
    score = score_snapshot(snap)
    revisions = _component(score, "revisions")

    shrunk_opinion = 50.0 + (100.0 - 50.0) * 1 / 3.0
    expected = (shrunk_opinion * 1 + 100.0 * 1) / 2
    assert revisions.score == pytest.approx(expected)
    assert "thin analyst coverage" in revisions.reasons


# --------------------------------------------------------------------------------------
# confidence must not be lifted as much by a single thin opinion as by broad coverage
# (finding 5)
# --------------------------------------------------------------------------------------


def test_confidence_rises_less_for_a_single_thin_opinion_than_full_coverage():
    base = _snap(
        revenue_growth=0.1,
        earnings_growth=0.1,
        gross_margin=0.3,
        operating_margin=0.1,
        roe=0.1,
        current_ratio=1.5,
        ret_3m=0.05,
        ret_6m=0.05,
        ret_12m=0.1,
        vol_1y=0.3,
        provenance=_prov(confidence=1.0),
    )
    thin_opinion = base.model_copy(update={"target_upside": 0.40, "analyst_count": 1})
    broad_coverage = base.model_copy(
        update={"target_upside": 0.40, "revision_net_90d": 2, "analyst_count": 10}
    )

    base_score = score_snapshot(base)
    thin_score = score_snapshot(thin_opinion)
    broad_score = score_snapshot(broad_coverage)

    thin_gain = thin_score.confidence - base_score.confidence
    broad_gain = broad_score.confidence - base_score.confidence
    assert 0.0 < thin_gain < broad_gain


# --------------------------------------------------------------------------------------
# earnings_proximity must be lower-bounded like every other sub-indicator (finding 6)
# --------------------------------------------------------------------------------------


def test_catalysts_negative_days_to_next_earnings_is_clamped_not_over_100():
    snap = _snap(days_to_next_earnings=-30, insider_form4_90d=0, filings_8k_90d=0)
    score = score_snapshot(snap)
    catalysts = _component(score, "catalysts")

    # earnings_proximity clamped to 100 (not 130), averaged with insider=0 and filings=0
    assert catalysts.score == pytest.approx((100.0 + 0.0 + 0.0) / 3)


# --------------------------------------------------------------------------------------
# surprise_streak must feed the score, not sit unused (finding 7)
# --------------------------------------------------------------------------------------


def test_surprise_streak_feeds_the_revisions_component():
    without_streak = _snap(est_eps_growth_1y=0.15)
    with_streak = _snap(est_eps_growth_1y=0.15, surprise_streak=6)

    score_without = score_snapshot(without_streak)
    score_with = score_snapshot(with_streak)

    revisions_without = _component(score_without, "revisions")
    revisions_with = _component(score_with, "revisions")

    # surprise_streak=6 saturates _linear(6, 0, 6) == 100, pulling the mean up.
    assert revisions_with.score > revisions_without.score


def test_score_snapshot_with_revisions_and_catalysts_is_deterministic():
    snap = _snap(
        est_eps_growth_1y=0.15,
        est_revenue_growth_1y=0.10,
        revision_balance=0.2,
        consensus_score=0.1,
        target_upside=0.15,
        revision_net_90d=2,
        revision_pt_change_90d=0.05,
        surprise_mean_8q=0.02,
        surprise_positive_share_8q=0.6,
        analyst_count=8,
        days_to_next_earnings=20,
        insider_form4_90d=2,
        filings_8k_90d=1,
    )

    first = score_snapshot(snap)
    second = score_snapshot(snap)
    assert first.model_dump_json() == second.model_dump_json()

    third = score_snapshot(snap.model_copy(deep=True))
    assert first.model_dump_json() == third.model_dump_json()
