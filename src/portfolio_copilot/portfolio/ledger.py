"""Decision ledger + shadow portfolio: append-only record of every suggested decision and a
deterministic counterfactual ("what if I had bought the alternative instead").

Storage: one JSON object per line under ``PORTFOLIO_COPILOT_HOME`` (default ``data/private``,
git-ignored). Nothing here trades or forecasts; it measures decisions after the fact.
"""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from portfolio_copilot.models import Decision

DEFAULT_HOME = Path(__file__).resolve().parents[3] / "data" / "private"


def ledger_path(home: Path | str | None = None) -> Path:
    base = Path(home or os.environ.get("PORTFOLIO_COPILOT_HOME") or DEFAULT_HOME)
    base.mkdir(parents=True, exist_ok=True)
    return base / "decisions.jsonl"


class CandidateAtDecision(BaseModel):
    """One candidate the capital auction (or stock picker) showed at decision time, with the
    price it had then. This is the raw material for after-the-fact opportunity-cost
    measurement (``portfolio.opportunity``): "what else could I have bought, and what would
    it be worth now?".

    ``price_symbol`` is the yfinance ticker actually used to price this candidate when its
    own ``symbol`` is not directly priceable (e.g. a bucket like ``global_equity`` priced via
    its proxy ETF ``VWCE.MI``); ``None`` for a candidate that had no price at all (unpriceable
    at decision time, or ``cash``, which needs no price).
    """

    symbol: str
    kind: Literal["bucket", "stock", "cash"]
    utility: float | None = None
    price: float | None = None
    price_symbol: str | None = None

    @field_validator("price")
    @classmethod
    def _price_must_be_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError(f"price must be a finite number, got {value!r}")
        return value


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
    # The ranking shown at decision time (capital auction / stock picker), for
    # portfolio.opportunity's after-the-fact regret measurement. Empty by default so
    # every existing decisions.jsonl line (recorded before this field existed) still loads.
    candidates: list[CandidateAtDecision] = Field(default_factory=list)

    @field_validator("price", "alternative_price")
    @classmethod
    def _price_fields_must_be_finite(cls, value: float | None, info) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError(f"{info.field_name} must be a finite number, got {value!r}")
        return value


def record_decision(record: dict, home: Path | str | None = None) -> DecisionRecord:
    """Validate and append one decision. The id is deterministic: date + symbol + action.

    Refuses to append a decision whose id already exists in the ledger: a replayed
    log_decision call (agent retry, or a skill re-run same-day for the same symbol) would
    otherwise silently double-count that one decision's weight in every aggregate stat and
    could cross the min_sample gate off of a single real decision.
    """
    payload = dict(record)
    payload.setdefault("date", date.today().isoformat())
    payload.setdefault("id", f"{payload['date']}:{payload['symbol'].upper()}:{payload['action']}")
    payload["symbol"] = payload["symbol"].upper()
    rec = DecisionRecord(**payload)
    existing_ids = {d.id for d in load_decisions(home)}
    if rec.id in existing_ids:
        raise ValueError(
            f"A decision with id {rec.id!r} is already recorded. Decisions are keyed by "
            "date+symbol+action; recording the same one twice would double-count it in "
            "every aggregate. Change the date, symbol or action if this is genuinely a "
            "second, distinct decision."
        )
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

    Pure arithmetic. None when a leg is missing: never guess the counterfactual. A NaN/inf
    leg is treated the same as a missing one -- it satisfies neither ``is None`` nor
    ``<= 0`` (NaN comparisons are always False), so it must be checked explicitly or it
    would otherwise silently poison the return with NaN instead of degrading to None.
    """
    if not math.isfinite(price_then) or not math.isfinite(price_now):
        raise ValueError("prices must be finite")
    if price_then <= 0 or price_now <= 0:
        raise ValueError("prices must be positive")
    real = price_now / price_then - 1.0
    if (
        alt_then is None
        or alt_now is None
        or not math.isfinite(alt_then)
        or not math.isfinite(alt_now)
        or alt_then <= 0
        or alt_now <= 0
    ):
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
        try:
            decision_date = date.fromisoformat(d.date)
        except ValueError:
            rows.append(
                {"id": d.id, "status": "unmeasurable", "why": f"invalid date: {d.date!r}"}
            )
            continue
        age = (today - decision_date).days
        if age < min_days:
            continue
        # For a SELL, the money did not stay in `symbol` -- it moved into `alternative`
        # (where the proceeds went), so `alternative` is the real (chosen) leg and
        # `symbol`'s post-sale move is the foregone counterfactual. This mirrors
        # portfolio.opportunity.opportunity_cost's SELL handling; getting this backwards
        # inverts the sign of decision_alpha/hit_rate for every SELL.
        if d.action == Decision.SELL:
            real_then = d.alternative_price
            real_now = current_prices.get(d.alternative) if d.alternative else None
            alt_then = d.price
            alt_now = current_prices.get(d.symbol)
        else:
            real_then = d.price
            real_now = current_prices.get(d.symbol)
            alt_then = d.alternative_price
            alt_now = current_prices.get(d.alternative) if d.alternative else None
        if (
            real_then is None
            or real_now is None
            or not math.isfinite(real_then)
            or not math.isfinite(real_now)
            or real_then <= 0
            or real_now <= 0
        ):
            rows.append(
                {"id": d.id, "status": "unmeasurable", "why": "missing decision or current price"}
            )
            continue
        result = decision_alpha(real_then, real_now, alt_then, alt_now)
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
