"""Decision ledger + shadow portfolio: append-only record of every suggested decision and a
deterministic counterfactual ("what if I had bought the alternative instead").

Storage: one JSON object per line under ``PORTFOLIO_COPILOT_HOME`` (default ``data/private``,
git-ignored). Nothing here trades or forecasts; it measures decisions after the fact.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from portfolio_copilot.models import Decision

DEFAULT_HOME = Path(__file__).resolve().parents[3] / "data" / "private"


def ledger_path(home: Path | str | None = None) -> Path:
    base = Path(home or os.environ.get("PORTFOLIO_COPILOT_HOME") or DEFAULT_HOME)
    base.mkdir(parents=True, exist_ok=True)
    return base / "decisions.jsonl"


class DecisionRecord(BaseModel):
    id: str
    date: str
    symbol: str
    action: Decision
    score: float | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    price: float | None = None
    amount_eur: float | None = None
    reason: str
    alternative: str | None = None  # the shadow: what you would have bought instead
    alternative_price: float | None = None
    red_team: str | None = None  # "passed" | "rejected: <why>" | None
    sources: list[str] = Field(default_factory=list)
    # Optional enrichment for portfolio.edge/portfolio.quality; all default to None so
    # existing decisions.jsonl lines (and every caller that predates them) stay valid.
    category: str | None = None  # groups rows for personal_edge (precedence over theme)
    theme: str | None = None  # personal_edge grouping fallback when no category is set
    thesis_status: str | None = None  # ThesisCheck.status at decision time, for decision_quality
    cap_eur: float | None = None  # per-position EUR cap this decision was checked against
    decision_kind: str | None = None  # "bucket" for an index/bucket fill, else a stock pick


def record_decision(record: dict, home: Path | str | None = None) -> DecisionRecord:
    """Validate and append one decision. The id is deterministic: date + symbol + action."""
    payload = dict(record)
    payload.setdefault("date", date.today().isoformat())
    payload.setdefault("id", f"{payload['date']}:{payload['symbol'].upper()}:{payload['action']}")
    payload["symbol"] = payload["symbol"].upper()
    rec = DecisionRecord(**payload)
    with ledger_path(home).open("a", encoding="utf-8") as fh:
        fh.write(rec.model_dump_json() + "\n")
    return rec


def load_decisions(home: Path | str | None = None) -> list[DecisionRecord]:
    path = ledger_path(home)
    if not path.exists():
        return []
    out: list[DecisionRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(DecisionRecord(**json.loads(line)))
    return out


def decision_alpha(
    price_then: float, price_now: float, alt_then: float | None, alt_now: float | None
) -> dict:
    """Return of the real choice, of the alternative, and their difference (decision alpha).

    Pure arithmetic. None when a leg is missing: never guess the counterfactual.
    """
    if price_then <= 0 or price_now <= 0:
        raise ValueError("prices must be positive")
    real = price_now / price_then - 1.0
    if alt_then is None or alt_now is None or alt_then <= 0 or alt_now <= 0:
        return {"real_return": real, "alternative_return": None, "decision_alpha": None}
    alt = alt_now / alt_then - 1.0
    return {"real_return": real, "alternative_return": alt, "decision_alpha": real - alt}


def evaluate_decisions(
    decisions: list[DecisionRecord],
    current_prices: dict[str, float | None],
    *,
    as_of: date | None = None,
    min_days: int = 90,
) -> dict:
    """Shadow-portfolio report over decisions at least ``min_days`` old.

    ``current_prices``: symbol -> latest price (None if unavailable). Missing prices make
    that decision 'unmeasurable' instead of being skipped silently.
    """
    today = as_of or datetime.now(UTC).date()
    rows: list[dict] = []
    alphas: list[float] = []
    for d in decisions:
        age = (today - date.fromisoformat(d.date)).days
        if age < min_days:
            continue
        price_now = current_prices.get(d.symbol)
        alt_now = current_prices.get(d.alternative) if d.alternative else None
        if d.price is None or price_now is None or d.price <= 0 or price_now <= 0:
            rows.append(
                {"id": d.id, "status": "unmeasurable", "why": "missing decision or current price"}
            )
            continue
        result = decision_alpha(d.price, price_now, d.alternative_price, alt_now)
        row = {"id": d.id, "status": "measured", "days": age, "action": d.action.value, **result}
        if result["decision_alpha"] is not None:
            alphas.append(result["decision_alpha"])
        rows.append(row)
    measured = [r for r in rows if r["status"] == "measured"]
    return {
        "as_of": today.isoformat(),
        "min_days": min_days,
        "decisions_total": len(decisions),
        "decisions_measured": len(measured),
        "decisions_unmeasurable": len(rows) - len(measured),
        "mean_decision_alpha": (sum(alphas) / len(alphas)) if alphas else None,
        "hit_rate": (sum(1 for a in alphas if a > 0) / len(alphas)) if alphas else None,
        "sample_warning": (
            "Fewer than 10 measured decisions: do not change behaviour on this sample."
            if len(alphas) < 10
            else None
        ),
        "rows": rows,
    }
