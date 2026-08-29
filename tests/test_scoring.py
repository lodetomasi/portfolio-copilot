import re
from datetime import UTC, datetime
from pathlib import Path

from portfolio_copilot.models import Provenance, StockSnapshot
from portfolio_copilot.scoring.engine import score_snapshot

_REPO_ROOT = Path(__file__).resolve().parents[1]


def test_score_is_bounded_and_has_confidence():
    snap = StockSnapshot(
        ticker="TEST",
        price=100,
        revenue_growth=0.20,
        earnings_growth=0.25,
        gross_margin=0.60,
        operating_margin=0.20,
        current_ratio=1.8,
        roe=0.20,
        forward_pe=25,
        price_to_sales=5,
        ret_3m=0.12,
        ret_6m=0.20,
        ret_12m=0.35,
        vol_1y=0.35,
        max_drawdown_1y=-0.18,
        above_sma50=True,
        above_sma200=True,
        provenance=Provenance(
            source="fixture",
            as_of=datetime.now(UTC),
            confidence=0.9,
        ),
    )
    score = score_snapshot(snap)
    assert 0 <= score.score <= 100
    assert 0 < score.confidence <= 1
    assert score.ticker == "TEST"


def test_zero_coverage_snapshot_is_flagged_unrated_not_a_real_category():
    """When every score component is unavailable (e.g. an invalid/unknown ticker), the
    result must be flagged as an explicit unrated state instead of defaulting to a
    plausible-looking real category like 'Quality / Compounder' at score 50.0 -- CLAUDE.md
    rule #6 requires degrading the score AND declaring it when data is absent, not
    producing something indistinguishable from a genuine mid-range result."""
    snap = StockSnapshot(
        ticker="NOTATICKER123",
        provenance=Provenance(
            source="fixture",
            as_of=datetime.now(UTC),
            confidence=0.35,
        ),
    )
    score = score_snapshot(snap)
    assert not any(c.available for c in score.components)
    assert score.category == "UNRATED / NO DATA"
    assert score.category != "Quality / Compounder"


def test_prd_score_categories_are_all_reachable_in_engine():
    """docs/PRD.md's '### Categorie' list must only document score categories that
    score_snapshot can actually assign. A category present only in the doc is dead
    documentation that misleads readers about real behaviour (CLAUDE.md: don't invent
    behaviour that isn't there)."""
    engine_src = (_REPO_ROOT / "src/portfolio_copilot/scoring/engine.py").read_text()
    reachable = set(re.findall(r'category = "([^"]+)"', engine_src))

    prd_text = (_REPO_ROOT / "docs/PRD.md").read_text()
    section = prd_text.split("### Categorie", 1)[1].split("\n##", 1)[0]
    documented = {
        line.strip().lstrip("- ").strip()
        for line in section.strip().splitlines()
        if line.strip().startswith("-")
    }

    assert documented, "expected at least one documented category"
    undocumented_but_reachable_extras = documented - reachable
    assert not undocumented_but_reachable_extras, (
        f"PRD.md documents categories score_snapshot never produces: "
        f"{undocumented_but_reachable_extras}"
    )
