"""Tests for portfolio/picker.py: potential ranking and informational tagging.

User principle under test (CLAUDE.md, binding): rank by potential across the whole
universe, no exclusion by size/index-membership/overlap/confidence -- overlap,
concentration and size are information (tags/notes), never filters. All fixtures are
built via the real Pydantic models (StockScore/StockSnapshot/ScoreComponent) dumped with
``model_dump(mode="json")``, matching exactly what scoring/engine.py hands the picker; no
network, no randomness.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from portfolio_copilot.models import Provenance, ScoreComponent, StockScore, StockSnapshot
from portfolio_copilot.portfolio.picker import (
    SHORTLIST_NOTE,
    _size_bucket,
    annotate,
    rank_by_potential,
    shortlist,
)

_AS_OF = datetime(2026, 8, 29, tzinfo=UTC)

CAPS = {
    "max_single_stock_weight": 0.05,
    "max_growth_stock_weight": 0.04,
    "max_high_risk_stock_weight": 0.02,
    "max_speculative_bucket_weight": 0.15,
}

_COMPONENT_NAMES = (
    "growth",
    "quality",
    "valuation",
    "momentum",
    "revisions",
    "catalysts",
    "risk",
)


def _components(available_names: tuple[str, ...] = _COMPONENT_NAMES) -> list[ScoreComponent]:
    return [
        ScoreComponent(name=name, score=60.0, weight=10, available=name in available_names)
        for name in _COMPONENT_NAMES
    ]


def _prov(confidence: float = 0.9) -> Provenance:
    return Provenance(source="test", as_of=_AS_OF, confidence=confidence)


def _snapshot(
    ticker: str,
    market_cap: float | None = None,
    sector: str | None = None,
    industry: str | None = None,
) -> StockSnapshot:
    return StockSnapshot(
        ticker=ticker,
        market_cap=market_cap,
        sector=sector,
        industry=industry,
        provenance=_prov(),
    )


def _scored(
    ticker: str,
    score: float,
    confidence: float,
    category: str = "Quality / Compounder",
    market_cap: float | None = None,
    sector: str | None = None,
    industry: str | None = None,
    available_components: tuple[str, ...] = _COMPONENT_NAMES,
) -> dict:
    stock_score = StockScore(
        ticker=ticker,
        score=score,
        confidence=confidence,
        category=category,
        components=_components(available_components),
        snapshot=_snapshot(ticker, market_cap, sector, industry),
    )
    return stock_score.model_dump(mode="json")


# --- rank_by_potential ---------------------------------------------------------------


def test_rank_by_potential_orders_by_score_desc():
    scored = [
        _scored("A", score=50.0, confidence=0.9),
        _scored("B", score=80.0, confidence=0.5),
        _scored("C", score=65.0, confidence=0.9),
    ]
    ranked = rank_by_potential(scored)
    assert [item["ticker"] for item in ranked] == ["B", "C", "A"]


def test_rank_by_potential_breaks_score_ties_by_confidence_desc():
    scored = [
        _scored("A", score=70.0, confidence=0.4),
        _scored("B", score=70.0, confidence=0.9),
    ]
    ranked = rank_by_potential(scored)
    assert [item["ticker"] for item in ranked] == ["B", "A"]


def test_rank_by_potential_breaks_full_ties_by_ticker_asc():
    scored = [
        _scored("ZZZ", score=70.0, confidence=0.5),
        _scored("AAA", score=70.0, confidence=0.5),
        _scored("MMM", score=70.0, confidence=0.5),
    ]
    ranked = rank_by_potential(scored)
    assert [item["ticker"] for item in ranked] == ["AAA", "MMM", "ZZZ"]


def test_rank_by_potential_never_drops_low_confidence_items():
    scored = [
        _scored("HUGE", score=95.0, confidence=0.9),
        _scored("TINY", score=10.0, confidence=0.1),
    ]
    ranked = rank_by_potential(scored, min_confidence=0.5)
    tickers = [item["ticker"] for item in ranked]
    assert tickers == ["HUGE", "TINY"]  # still ranked purely by score, nothing removed
    assert len(ranked) == len(scored)

    tiny = next(item for item in ranked if item["ticker"] == "TINY")
    huge = next(item for item in ranked if item["ticker"] == "HUGE")
    assert "low_confidence" in tiny["tags"]
    assert "low_confidence" not in huge["tags"]


def test_rank_by_potential_no_min_confidence_tags_nothing():
    scored = [_scored("X", score=10.0, confidence=0.01)]
    ranked = rank_by_potential(scored)  # default min_confidence=0.0
    assert ranked[0]["tags"] == []


def test_rank_by_potential_does_not_mutate_input():
    scored = [_scored("A", score=50.0, confidence=0.5)]
    original_keys = set(scored[0].keys())
    rank_by_potential(scored, min_confidence=0.9)
    assert set(scored[0].keys()) == original_keys  # no "tags" leaked into the source dict


def test_rank_by_potential_is_deterministic():
    scored = [
        _scored("B", score=70.0, confidence=0.5),
        _scored("A", score=70.0, confidence=0.5),
    ]
    first = rank_by_potential(scored)
    second = rank_by_potential(scored)
    assert first == second


# --- annotate: size buckets -----------------------------------------------------------


def test_annotate_size_bucket_mega():
    item = _scored("MEGA", score=80, confidence=0.9, market_cap=250e9)
    result = annotate(item, exposure=None, caps=CAPS)
    assert result["size_bucket"] == "mega"


def test_annotate_size_bucket_large():
    item = _scored("LARGE", score=80, confidence=0.9, market_cap=50e9)
    assert annotate(item, exposure=None, caps=CAPS)["size_bucket"] == "large"


def test_annotate_size_bucket_mid():
    item = _scored("MID", score=80, confidence=0.9, market_cap=5e9)
    assert annotate(item, exposure=None, caps=CAPS)["size_bucket"] == "mid"


def test_annotate_size_bucket_small():
    item = _scored("SMALL", score=80, confidence=0.9, market_cap=500e6)
    assert annotate(item, exposure=None, caps=CAPS)["size_bucket"] == "small"


def test_annotate_size_bucket_micro():
    item = _scored("MICRO", score=80, confidence=0.9, market_cap=50e6)
    assert annotate(item, exposure=None, caps=CAPS)["size_bucket"] == "micro"


def test_annotate_size_bucket_nano():
    # True penny-stock territory (<$50mln): must not be understated as "micro".
    item = _scored("NANO", score=80, confidence=0.9, market_cap=10e6)
    assert annotate(item, exposure=None, caps=CAPS)["size_bucket"] == "nano"


def test_annotate_size_bucket_boundaries_are_inclusive():
    exactly_mega = _scored("EM", score=1, confidence=1, market_cap=200e9)
    exactly_large = _scored("EL", score=1, confidence=1, market_cap=10e9)
    exactly_mid = _scored("EMD", score=1, confidence=1, market_cap=2e9)
    exactly_small = _scored("ES", score=1, confidence=1, market_cap=300e6)
    assert annotate(exactly_mega, None, CAPS)["size_bucket"] == "mega"
    assert annotate(exactly_large, None, CAPS)["size_bucket"] == "large"
    assert annotate(exactly_mid, None, CAPS)["size_bucket"] == "mid"
    assert annotate(exactly_small, None, CAPS)["size_bucket"] == "small"


def test_annotate_size_bucket_none_when_market_cap_unknown():
    item = _scored("UNKNOWN", score=80, confidence=0.9, market_cap=None)
    result = annotate(item, exposure=None, caps=CAPS)
    assert result["size_bucket"] is None
    assert result["core_overlap_note"] is None


def test_size_bucket_nan_market_cap_is_none_not_micro():
    # finding 12: NaN must degrade to unknown, never a fabricated "micro" label.
    assert _size_bucket(float("nan")) is None


def test_annotate_nan_market_cap_size_bucket_is_none():
    item = _scored("NANCAP", score=80, confidence=0.9, market_cap=float("nan"))
    result = annotate(item, exposure=None, caps=CAPS)
    assert result["size_bucket"] is None


# --- annotate: risk cap mapping --------------------------------------------------------


def test_annotate_risk_cap_pct_quality_maps_to_single_stock_cap():
    item = _scored("Q", score=80, confidence=0.9, category="Quality / Compounder")
    assert annotate(item, None, CAPS)["risk_cap_pct"] == CAPS["max_single_stock_weight"]


def test_annotate_risk_cap_pct_growth_maps_to_growth_cap():
    item = _scored("G", score=80, confidence=0.9, category="Growth / Momentum")
    assert annotate(item, None, CAPS)["risk_cap_pct"] == CAPS["max_growth_stock_weight"]


def test_annotate_risk_cap_pct_asymmetric_maps_to_high_risk_cap():
    item = _scored("H", score=80, confidence=0.9, category="Asymmetric / High Risk")
    assert annotate(item, None, CAPS)["risk_cap_pct"] == CAPS["max_high_risk_stock_weight"]


def test_annotate_risk_cap_pct_unrated_is_none():
    item = _scored("U", score=50, confidence=0.35, category="UNRATED / NO DATA")
    assert annotate(item, None, CAPS)["risk_cap_pct"] is None


def test_annotate_risk_cap_pct_missing_caps_key_degrades_to_none():
    item = _scored("Q", score=80, confidence=0.9, category="Quality / Compounder")
    result = annotate(item, None, caps={})  # no keys at all -- never invent a number
    assert result["risk_cap_pct"] is None


# --- annotate: core overlap note --------------------------------------------------------


def test_annotate_core_overlap_note_present_for_mega():
    item = _scored("MEGA", score=80, confidence=0.9, market_cap=500e9)
    result = annotate(item, None, CAPS)
    assert "index ETF" in result["core_overlap_note"]


def test_annotate_core_overlap_note_absent_for_non_mega():
    item = _scored("SMALL", score=80, confidence=0.9, market_cap=1e9)
    result = annotate(item, None, CAPS)
    assert result["core_overlap_note"] is None


def test_annotate_core_overlap_note_suppressed_when_exposure_shows_no_overlap():
    # finding 11: when real exposure evidence says diversification=1.0 (no overlap), the
    # static "you already hold this" heuristic must not contradict it.
    exposure = {"themes": {}, "drivers": {}}
    item = _scored(
        "MEGA", score=80, confidence=0.9, market_cap=900e9, sector=None, industry=None
    )
    result = annotate(item, exposure, CAPS)
    assert result["diversification"] == 1.0
    assert result["lane"] == "diversifying"
    assert result["core_overlap_note"] is None


def test_annotate_core_overlap_note_present_when_exposure_confirms_overlap():
    exposure = {
        "themes": {"semiconductors": 0.6},
        "drivers": {"semiconductor_cycle": 0.6, "ai_capex": 0.6, "china_demand": 0.6},
    }
    item = _scored(
        "NVDA", score=80, confidence=0.9, market_cap=3_000e9,
        sector="Technology", industry="Semiconductors",
    )
    result = annotate(item, exposure, CAPS)
    assert result["diversification"] < 0.5
    assert "index ETF" in result["core_overlap_note"]


# --- annotate: exposure / diversification / lanes --------------------------------------


def test_annotate_exposure_none_path_gives_no_overlap_data():
    item = _scored("Q", score=80, confidence=0.9, market_cap=300e9, sector="Technology",
                    industry="Semiconductors")
    result = annotate(item, exposure=None, caps=CAPS)
    assert result["themes"] == []
    assert result["drivers"] == []
    assert result["diversification"] is None
    # No overlap evidence available -> falls through to the non-core-like lane.
    assert result["lane"] == "diversifying"


def test_annotate_lane_core_like_for_mega_with_heavy_overlap():
    exposure = {
        "themes": {"semiconductors": 0.6},
        "drivers": {"semiconductor_cycle": 0.6, "ai_capex": 0.6, "china_demand": 0.6},
    }
    item = _scored(
        "NVDA", score=80, confidence=0.9, category="Quality / Compounder",
        market_cap=3_000e9, sector="Technology", industry="Semiconductors",
    )
    result = annotate(item, exposure, CAPS)
    assert result["diversification"] is not None
    assert result["diversification"] < 0.5
    assert result["lane"] == "core-like"
    assert result["themes"] == ["semiconductors"]
    assert result["drivers"] == ["ai_capex", "china_demand", "semiconductor_cycle"]


def test_annotate_lane_diversifying_for_mega_with_no_overlap():
    exposure = {"themes": {}, "drivers": {}}
    item = _scored(
        "MEGA", score=80, confidence=0.9, category="Quality / Compounder",
        market_cap=900e9, sector=None, industry=None,
    )
    result = annotate(item, exposure, CAPS)
    assert result["diversification"] == 1.0
    assert result["lane"] == "diversifying"


def test_annotate_lane_speculative_for_high_risk_category_non_mega():
    exposure = {"themes": {}, "drivers": {}}
    item = _scored(
        "SPEC", score=60, confidence=0.4, category="Asymmetric / High Risk",
        market_cap=1e9, sector=None, industry=None,
    )
    result = annotate(item, exposure, CAPS)
    assert result["lane"] == "speculative"


def test_annotate_lane_priority_mega_overlap_beats_high_risk_category():
    # Documented priority: mega + heavy overlap reads as core-like even for a category
    # that would otherwise be "speculative" -- size/overlap describe *how* it lands.
    exposure = {
        "themes": {"semiconductors": 0.6},
        "drivers": {"semiconductor_cycle": 0.6, "ai_capex": 0.6, "china_demand": 0.6},
    }
    item = _scored(
        "RISKYMEGA", score=60, confidence=0.4, category="Asymmetric / High Risk",
        market_cap=1_000e9, sector="Technology", industry="Semiconductors",
    )
    result = annotate(item, exposure, CAPS)
    assert result["lane"] == "core-like"


def test_annotate_never_removes_the_item():
    item = _scored("X", score=1, confidence=0.01, category="UNRATED / NO DATA")
    result = annotate(item, exposure=None, caps={})
    assert result["ticker"] == "X"
    assert result["score"] == 1


# --- shortlist ---------------------------------------------------------------------------


def test_shortlist_ranks_and_bounds_by_top_n():
    scored = [_scored(f"T{i}", score=float(i), confidence=0.9) for i in range(20)]
    result = shortlist(scored, exposure=None, caps=CAPS, top_n=5)
    assert len(result["ranked"]) == 5
    assert [item["ticker"] for item in result["ranked"]] == ["T19", "T18", "T17", "T16", "T15"]


def test_shortlist_top_n_does_not_shrink_below_available_candidates():
    scored = [_scored("A", score=1, confidence=1), _scored("B", score=2, confidence=1)]
    result = shortlist(scored, exposure=None, caps=CAPS, top_n=10)
    assert len(result["ranked"]) == 2


def test_shortlist_includes_fixed_note():
    result = shortlist([], exposure=None, caps=CAPS)
    assert result["summary"]["note"] == SHORTLIST_NOTE


def test_shortlist_sector_concentration_warns_when_majority():
    scored = [
        _scored("A", score=90, confidence=0.9, sector="Technology"),
        _scored("B", score=80, confidence=0.9, sector="Technology"),
        _scored("C", score=70, confidence=0.9, sector="Technology"),
        _scored("D", score=60, confidence=0.9, sector="Healthcare"),
    ]
    result = shortlist(scored, exposure=None, caps=CAPS, top_n=10)
    concentration = result["summary"]["sector_concentration"]
    assert concentration["sector"] == "Technology"
    assert concentration["share"] == 0.75
    assert concentration["warning"] is not None
    assert "Technology" in concentration["warning"]


def test_shortlist_sector_concentration_no_warning_when_balanced():
    scored = [
        _scored("A", score=90, confidence=0.9, sector="Technology"),
        _scored("B", score=80, confidence=0.9, sector="Healthcare"),
    ]
    result = shortlist(scored, exposure=None, caps=CAPS, top_n=10)
    concentration = result["summary"]["sector_concentration"]
    assert concentration["share"] == 0.5
    assert concentration["warning"] is None


def test_shortlist_sector_concentration_handles_no_sector_data():
    scored = [_scored("A", score=90, confidence=0.9, sector=None)]
    result = shortlist(scored, exposure=None, caps=CAPS, top_n=10)
    concentration = result["summary"]["sector_concentration"]
    assert concentration["sector"] is None
    assert concentration["share"] == 0.0
    assert concentration["warning"] is None


def test_shortlist_size_mix_counts_including_unknown():
    scored = [
        _scored("A", score=90, confidence=0.9, market_cap=300e9),  # mega
        _scored("B", score=80, confidence=0.9, market_cap=5e9),  # mid
        _scored("C", score=70, confidence=0.9, market_cap=None),  # unknown
    ]
    result = shortlist(scored, exposure=None, caps=CAPS, top_n=10)
    size_mix = result["summary"]["size_mix"]
    assert size_mix["mega"] == 1
    assert size_mix["mid"] == 1
    assert size_mix["unknown"] == 1


def test_shortlist_available_components_stats():
    scored = [
        _scored("A", score=90, confidence=0.9, available_components=_COMPONENT_NAMES),
        _scored("B", score=80, confidence=0.9, available_components=("growth", "quality")),
    ]
    result = shortlist(scored, exposure=None, caps=CAPS, top_n=10)
    stats = result["summary"]["available_components"]
    assert stats["growth"] == {"available": 2, "total": 2}
    assert stats["revisions"] == {"available": 1, "total": 2}


def test_shortlist_nothing_is_ever_excluded_from_the_full_ranking():
    scored = [_scored(f"T{i}", score=float(i), confidence=0.01) for i in range(3)]
    result = shortlist(scored, exposure=None, caps=CAPS, top_n=1)
    # Display is bounded, but the underlying ranking (what a caller would page through)
    # still contains every candidate -- nothing is filtered out upstream.
    full_ranking = rank_by_potential(scored)
    assert len(full_ranking) == len(scored)
    assert len(result["ranked"]) == 1


def test_shortlist_threads_min_confidence_to_low_confidence_tag():
    # findings 10/14: shortlist() must be able to surface the low_confidence tag -- it
    # cannot be dead code reachable only via rank_by_potential called directly.
    thin = _scored("THIN", score=95, confidence=0.35, available_components=("growth",))
    solid = _scored("SOLID", score=90, confidence=0.95)
    result = shortlist([thin, solid], exposure=None, caps=CAPS, top_n=10, min_confidence=0.5)
    by_ticker = {item["ticker"]: item for item in result["ranked"]}
    assert "low_confidence" in by_ticker["THIN"]["tags"]
    assert "low_confidence" not in by_ticker["SOLID"]["tags"]


def test_shortlist_default_min_confidence_preserves_current_behavior():
    thin = _scored("THIN", score=95, confidence=0.35, available_components=("growth",))
    result = shortlist([thin], exposure=None, caps=CAPS, top_n=10)
    assert result["ranked"][0].get("tags", []) == []


def test_shortlist_error_placeholder_is_labeled_and_excluded_from_summary():
    # finding 13: a screen_stocks() failure placeholder must not masquerade as a real,
    # if data-poor, candidate in the summary stats.
    error_item = {"ticker": "BADTICKER", "error": "HTTPError: 404 not found", "score": None,
                  "confidence": 0.0}
    good = _scored("GOOD", score=55.0, confidence=0.6, sector="Industrials", market_cap=1e9)

    result = shortlist([error_item, good], exposure=None, caps=CAPS, top_n=10)

    by_ticker = {item["ticker"]: item for item in result["ranked"]}
    assert by_ticker["BADTICKER"]["lane"] == "error"
    assert by_ticker["BADTICKER"]["size_bucket"] is None

    assert result["summary"]["size_mix"] == {"small": 1}
    assert result["summary"]["sector_concentration"]["sector"] == "Industrials"


def test_shortlist_summary_covers_the_full_scored_list_beyond_top_n():
    # finding 27: sector_concentration/size_mix must reflect the WHOLE ranked universe,
    # not just the top_n display slice.
    scored = [
        _scored("A", score=90, confidence=0.9, sector="Tech"),
        _scored("B", score=89, confidence=0.9, sector="Tech"),
        _scored("C", score=10, confidence=0.9, sector="Energy"),
        _scored("D", score=9, confidence=0.9, sector="Energy"),
        _scored("E", score=8, confidence=0.9, sector="Energy"),
    ]
    result = shortlist(scored, exposure=None, caps=CAPS, top_n=2)
    concentration = result["summary"]["sector_concentration"]
    assert concentration["sector"] == "Energy"
    assert concentration["share"] == pytest.approx(0.6)


def test_shortlist_is_deterministic():
    scored = [
        _scored("B", score=70.0, confidence=0.5, sector="Technology"),
        _scored("A", score=70.0, confidence=0.5, sector="Technology"),
        _scored("C", score=90.0, confidence=0.9, sector="Healthcare"),
    ]
    exposure = {"themes": {}, "drivers": {}}
    first = shortlist(scored, exposure, CAPS, top_n=10)
    second = shortlist(scored, exposure, CAPS, top_n=10)
    assert first == second
