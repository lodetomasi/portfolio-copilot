"""Edge-case coverage for scoring/merge/metrics: missing data, NaN, extreme magnitudes,
zero-as-a-value overrides, degenerate series and score reproducibility.

Offline and deterministic: no network, no provider objects instantiated, only the pure
functions in analytics/merge.py, analytics/metrics.py and scoring/engine.py, plus the
``_f`` NaN-guard helper from providers/yfinance_provider.py (imported, never called
against the network).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from portfolio_copilot.analytics.merge import apply_official_overrides
from portfolio_copilot.analytics.metrics import (
    annualized_volatility,
    concentration,
    hhi,
    max_drawdown,
    pct_return,
)
from portfolio_copilot.models import Provenance, StockSnapshot
from portfolio_copilot.providers.yfinance_provider import _f
from portfolio_copilot.scoring.engine import score_snapshot

_AS_OF = datetime(2026, 1, 1, tzinfo=UTC)


def _prov(confidence: float = 0.75, source: str = "yfinance", **kw) -> Provenance:
    return Provenance(source=source, as_of=_AS_OF, confidence=confidence, **kw)


def _snap(**kw) -> StockSnapshot:
    kw.setdefault("ticker", "EDGE")
    kw.setdefault("provenance", _prov())
    return StockSnapshot(**kw)


# --------------------------------------------------------------------------------------
# snapshot with every scoring field None
# --------------------------------------------------------------------------------------


def test_all_fields_none_snapshot_scores_50_confidence_is_floored_and_warns():
    """CLAUDE.md rule 6: absent data must degrade the score and declare it. A snapshot
    with no usable component data must not be indistinguishable from a genuine
    mid-range 50 result with normal confidence -- the confidence must be capped down
    regardless of how confident the provider claims to be, and the reasons must say
    the score is unusable."""
    snap = _snap(provenance=_prov(confidence=0.9))
    score = score_snapshot(snap)

    assert score.score == 50.0
    assert score.confidence == 0.35  # min(0.9, 0.35 + 0.65 * 0.0) -- zero coverage caps it
    assert score.category == "UNRATED / NO DATA"
    assert not any(c.available for c in score.components)
    assert score.reasons == [
        "data coverage 0%",
        "provider confidence 90%",
        "Insufficient data: do not use this score for a decision",
    ]


# --------------------------------------------------------------------------------------
# NaN handling via the provider's _f guard
# --------------------------------------------------------------------------------------


def test_provider_f_converts_nan_and_inf_to_none():
    assert _f(float("nan")) is None
    assert _f(float("inf")) is None
    assert _f(float("-inf")) is None
    assert _f(None) is None


def test_nan_ret_field_via_f_is_excluded_from_momentum_average_not_propagated():
    """A provider value that arrives as NaN (e.g. yfinance returning nan for a return
    series) must, once passed through ``_f``, become None and simply drop out of the
    momentum average -- it must never turn the component or the final score into NaN."""
    nan_ret = _f(float("nan"))
    assert nan_ret is None

    snap = _snap(
        ret_3m=nan_ret,
        ret_6m=0.10,
        ret_12m=0.20,
        above_sma50=True,
        above_sma200=True,
    )
    score = score_snapshot(snap)
    momentum = next(c for c in score.components if c.name == "momentum")

    assert momentum.available is True
    assert momentum.score == 58.75
    assert score.score == score.score  # not NaN (NaN != NaN would fail this)
    assert 0.0 <= score.score <= 100.0


# --------------------------------------------------------------------------------------
# extreme out-of-range magnitudes must clamp, never crash or escape [0, 100]
# --------------------------------------------------------------------------------------


def test_extreme_magnitude_inputs_clamp_to_valid_bounds():
    """revenue_growth=50.0 (5000% YoY), debt_to_equity=1e6 and vol_1y=5.0 (500%
    annualized) are absurd but must not break _linear/_clamp: each component score
    must still land inside [0, 100] (enforced by ScoreComponent's own Field bounds --
    a broken clamp would raise a pydantic ValidationError here) and the extreme risk
    must be reflected in the category."""
    snap = _snap(revenue_growth=50.0, debt_to_equity=1e6, vol_1y=5.0)
    score = score_snapshot(snap)

    by_name = {c.name: c for c in score.components}
    assert by_name["growth"].score == 100.0  # saturates the good end
    assert by_name["quality"].score == 0.0  # saturates the bad end
    assert by_name["risk"].score == 0.0  # saturates the bad end
    for component in score.components:
        assert 0.0 <= component.score <= 100.0

    assert score.score == 40.0
    assert score.category == "Asymmetric / High Risk"


# --------------------------------------------------------------------------------------
# negative price: not a scoring input, must not affect the result
# --------------------------------------------------------------------------------------


def test_negative_price_does_not_alter_score_since_price_is_not_a_score_input():
    """score_snapshot never reads snapshot.price directly (it scores forward_pe,
    price_to_sales, etc. as independently-provided ratios), so a corrupted/negative
    price must not change the outcome or raise -- it is purely descriptive metadata."""
    common = {
        "revenue_growth": 0.10,
        "forward_pe": 20.0,
        "ret_3m": 0.05,
    }
    positive = score_snapshot(_snap(price=100.0, **common))
    negative = score_snapshot(_snap(price=-100.0, **common))
    missing = score_snapshot(_snap(price=None, **common))

    assert positive.score == negative.score == missing.score
    assert positive.model_dump(exclude={"snapshot"}) == negative.model_dump(exclude={"snapshot"})


# --------------------------------------------------------------------------------------
# metrics on empty / single-element / constant series
# --------------------------------------------------------------------------------------


def test_pct_return_on_empty_and_single_element_series_returns_none():
    assert pct_return(pd.Series(dtype=float), 3) is None
    assert pct_return(pd.Series([100.0]), 1) is None


def test_annualized_volatility_on_empty_series_returns_none():
    assert annualized_volatility(pd.Series(dtype=float)) is None


def test_annualized_volatility_on_constant_series_is_zero_not_none():
    """A flat price series has zero return dispersion -- the result must be the exact
    number 0.0 (real, usable data), not None (data unavailable); conflating the two
    would make a genuinely quiet stock look like a data gap."""
    flat = pd.Series([100.0] * 30)
    vol = annualized_volatility(flat)
    assert vol is not None
    assert vol == 0.0


def test_max_drawdown_on_empty_and_single_element_series_returns_none():
    assert max_drawdown(pd.Series(dtype=float)) is None
    assert max_drawdown(pd.Series([100.0])) is None


def test_max_drawdown_on_constant_series_is_zero_not_none():
    assert max_drawdown(pd.Series([100.0, 100.0, 100.0])) == 0.0


def test_concentration_on_empty_weights_returns_all_zero():
    assert concentration([]) == {"top1": 0.0, "top3": 0.0, "top5": 0.0, "hhi": 0.0}


def test_hhi_on_empty_weights_is_zero():
    assert hhi([]) == 0.0


# --------------------------------------------------------------------------------------
# merge: 0.0 is a value, must override; missing fiscal_year must not block an override
# --------------------------------------------------------------------------------------


def test_merge_zero_revenue_growth_from_facts_overrides_existing_estimate():
    """0.0 (e.g. flat YoY revenue) is a legitimate SEC-reported value, not 'no data'.
    A naive truthiness check (`if value:`) would silently drop it and leave the stale
    Yahoo estimate in place; the merge must key off `is None`, not truthiness."""
    snap = _snap(revenue_growth=0.20, provenance=_prov(confidence=0.75))
    facts = {
        "ok": True,
        "fiscal_year": 2025,
        "as_of": "2026-01-01",
        "revenue_growth": 0.0,
        "free_cashflow": None,
    }
    out = apply_official_overrides(snap, facts)

    assert out.revenue_growth == 0.0
    assert "revenue_growth: sec_edgar FY2025 replaces yfinance" in out.provenance.overrides
    assert out.provenance.confidence == 0.85


def test_merge_with_ok_facts_but_missing_fiscal_year_still_overrides_and_bumps_confidence():
    """SEC facts can be usable (ok=True, real values) even when the fiscal_year field
    itself is missing -- the override and the confidence bump must not be silently
    skipped just because one metadata field is absent."""
    snap = _snap(revenue_growth=0.20, free_cashflow=None, provenance=_prov(confidence=0.75))
    facts = {
        "ok": True,
        "fiscal_year": None,
        "as_of": "2026-01-01",
        "revenue_growth": 0.15,
        "free_cashflow": 1000.0,
    }
    out = apply_official_overrides(snap, facts)

    assert out.revenue_growth == 0.15
    assert out.free_cashflow == 1000.0
    assert out.provenance.confidence == 0.85
    assert any(
        o.startswith("revenue_growth: sec_edgar FY") and o.endswith("replaces yfinance")
        for o in out.provenance.overrides
    )
    assert any(
        s.startswith("sec_edgar: FY") and "2026-01-01" in s
        for s in out.provenance.secondary_sources
    )


# --------------------------------------------------------------------------------------
# reproducibility: score_snapshot is a pure function
# --------------------------------------------------------------------------------------


def test_score_snapshot_is_pure_and_json_reproducible():
    snap = _snap(
        revenue_growth=0.12,
        earnings_growth=0.18,
        gross_margin=0.5,
        forward_pe=22.0,
        ret_3m=0.05,
        vol_1y=0.3,
        max_drawdown_1y=-0.2,
        above_sma50=True,
        provenance=_prov(confidence=0.75),
    )

    first = score_snapshot(snap)
    second = score_snapshot(snap)
    assert first.model_dump_json() == second.model_dump_json()

    # Rebuilding an equal-but-distinct snapshot object must yield the same JSON too --
    # nothing in score_snapshot may depend on object identity or hidden mutable state.
    third = score_snapshot(snap.model_copy(deep=True))
    assert first.model_dump_json() == third.model_dump_json()
