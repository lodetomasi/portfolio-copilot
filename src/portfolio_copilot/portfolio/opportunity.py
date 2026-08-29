"""Opportunity-cost measurement: after the fact, was the chosen decision actually the best
use of that capital, compared with the other candidates the capital auction (or stock
picker) was ranking at the time?

This is a sharper lens than ``portfolio.ledger.evaluate_decisions``: that module compares the
chosen symbol against a single recorded ``alternative``; this module compares it against the
*whole* ranking shown at decision time (``DecisionRecord.candidates``), including the implicit
"do nothing, keep cash" option. Pure arithmetic, no LLM math, no invented prices: any leg
without both a decision-time and a current price is reported as unmeasurable by name rather
than defaulted to zero or silently dropped.
"""

from __future__ import annotations

import math
import statistics
from datetime import date

from portfolio_copilot.models import Decision
from portfolio_copilot.portfolio.ledger import CandidateAtDecision, DecisionRecord

#: regret <= this counts as "close enough to the best available" for share_within_1pp.
REGRET_TOLERANCE = 0.01


def _lookup_current(
    symbol: str, price_symbol: str | None, current_prices: dict[str, float | None]
) -> float | None:
    """Current price for one leg: the raw symbol first, then its pricing proxy (e.g. a
    bucket's ETF ticker) if the symbol itself is not a key in ``current_prices``."""
    price = current_prices.get(symbol)
    if price is not None:
        return price
    if price_symbol is not None:
        return current_prices.get(price_symbol)
    return None


def _leg_return(price_then: float | None, price_now: float | None) -> float | None:
    """Simple return of one leg, or ``None`` if either price is missing, non-finite or
    non-positive. NaN satisfies neither ``is None`` nor ``<= 0`` (NaN comparisons are
    always False), so it must be checked explicitly or it silently poisons regret/median
    stats with NaN instead of degrading that one leg to unmeasurable."""
    if (
        price_then is None
        or price_now is None
        or not math.isfinite(price_then)
        or not math.isfinite(price_now)
        or price_then <= 0
        or price_now <= 0
    ):
        return None
    return price_now / price_then - 1.0


def opportunity_cost(decision: DecisionRecord, current_prices: dict[str, float | None]) -> dict:
    """Regret for one decision: chosen return vs. the best of the candidates shown at the time.

    For a BUY/HOLD/etc. decision the "chosen" leg is ``decision.symbol`` priced at
    ``decision.price`` then and looked up in ``current_prices`` now. For a SELL, the money
    did not stay in the sold symbol -- it moved to ``decision.alternative`` (where the
    proceeds went), so that is the chosen leg instead, and the sold symbol itself re-enters
    the comparison as a "kept it" candidate (what if you had not sold?).

    ``best_available`` is the max return across every candidate that has both a decision-time
    and a current price (a ``cash`` candidate always contributes exactly ``0.0``, needing no
    price). ``regret = best_available - chosen_return`` can be negative -- the chosen decision
    beat everything else that was measurable, which is a good sign, not an error.

    Never guesses a price: a candidate missing either price is dropped into
    ``unmeasurable_candidates`` by name instead of being scored.
    """
    is_sell = decision.action == Decision.SELL

    if is_sell:
        chosen_symbol = decision.alternative
        chosen_price_then = decision.alternative_price
    else:
        chosen_symbol = decision.symbol
        chosen_price_then = decision.price

    # Resolve a price_symbol proxy for the chosen leg the same way regardless of action --
    # a bucket (BUY's chosen symbol, or a SELL's reinvestment target) is priced only via
    # its proxy ETF ticker, carried on the matching entry in decision.candidates.
    chosen_candidate = (
        next((c for c in decision.candidates if c.symbol == chosen_symbol), None)
        if chosen_symbol is not None
        else None
    )
    chosen_price_symbol = chosen_candidate.price_symbol if chosen_candidate else None
    chosen_price_now = (
        _lookup_current(chosen_symbol, chosen_price_symbol, current_prices)
        if chosen_symbol is not None
        else None
    )

    chosen_return = _leg_return(chosen_price_then, chosen_price_now)
    base = {"id": decision.id, "chosen": chosen_symbol}
    empty = {
        "chosen_return": None,
        "candidates": [],
        "unmeasurable_candidates": [],
        "best_available": None,
        "regret": None,
        "chosen_rank": None,
    }

    if chosen_symbol is None:
        return {
            **base,
            **empty,
            "status": "unmeasurable",
            "why": "SELL has no recorded alternative",
        }
    if chosen_return is None:
        bad_then = chosen_price_then is None or chosen_price_then <= 0
        why = f"chosen ({chosen_symbol}): {'no price then' if bad_then else 'no price now'}"
        return {**base, **empty, "status": "unmeasurable", "why": why}

    pool: list[tuple[CandidateAtDecision, str | None]] = [(c, None) for c in decision.candidates]
    if is_sell:
        valid_kinds = ("bucket", "stock", "cash")
        kept_kind = decision.decision_kind if decision.decision_kind in valid_kinds else "stock"
        kept_candidate = next(
            (c for c in decision.candidates if c.symbol == decision.symbol), None
        )
        kept_price_symbol = kept_candidate.price_symbol if kept_candidate else None
        pool.append(
            (
                CandidateAtDecision(
                    symbol=decision.symbol,
                    kind=kept_kind,
                    price=decision.price,
                    price_symbol=kept_price_symbol,
                ),
                "kept it",
            )
        )

    candidates: list[dict] = []
    unmeasurable_candidates: list[dict] = []
    for cand, note in pool:
        if cand.kind == "cash":
            row = {"symbol": cand.symbol, "kind": "cash", "candidate_return": 0.0}
            if note:
                row["note"] = note
            candidates.append(row)
            continue
        price_now = _lookup_current(cand.symbol, cand.price_symbol, current_prices)
        ret = _leg_return(cand.price, price_now)
        if ret is None:
            bad_then = cand.price is None or cand.price <= 0
            entry = {"symbol": cand.symbol, "why": "no price then" if bad_then else "no price now"}
            if note:
                entry["note"] = note
            unmeasurable_candidates.append(entry)
            continue
        row = {"symbol": cand.symbol, "kind": cand.kind, "candidate_return": ret}
        if note:
            row["note"] = note
        candidates.append(row)

    if not candidates:
        return {
            **base,
            **empty,
            "chosen_return": chosen_return,
            "unmeasurable_candidates": unmeasurable_candidates,
            "status": "unmeasurable",
            "why": "no priced candidates to compare against",
        }

    best_available = max(row["candidate_return"] for row in candidates)
    chosen_rank = sum(1 for row in candidates if row["candidate_return"] > chosen_return) + 1

    return {
        **base,
        "status": "measured",
        "chosen_return": chosen_return,
        "candidates": candidates,
        "unmeasurable_candidates": unmeasurable_candidates,
        "best_available": best_available,
        "regret": best_available - chosen_return,
        "chosen_rank": chosen_rank,
    }


def opportunity_report(
    decisions: list[DecisionRecord],
    current_prices: dict[str, float | None],
    as_of: date,
    min_days: int = 90,
    min_sample: int = 10,
) -> dict:
    """Aggregate regret across the ledger, gated on sample size like every other engine here.

    Only decisions at least ``min_days`` old are considered (too-recent decisions have not
    had time to play out). Below ``min_sample`` measured decisions the verdict says plainly
    that it is not yet distinguishable from luck instead of pretending to be conclusive.
    """
    rows: list[dict] = []
    for d in decisions:
        try:
            decision_date = date.fromisoformat(d.date)
        except ValueError:
            rows.append(
                {"id": d.id, "status": "unmeasurable", "why": f"invalid date: {d.date!r}"}
            )
            continue
        age = (as_of - decision_date).days
        if age < min_days:
            continue
        row = opportunity_cost(d, current_prices)
        row["days"] = age
        rows.append(row)

    measured = [r for r in rows if r["status"] == "measured"]
    n_measured = len(measured)
    n_unmeasurable = len(rows) - n_measured
    regrets = [r["regret"] for r in measured]

    mean_regret = sum(regrets) / n_measured if n_measured else None
    median_regret = statistics.median(regrets) if regrets else None
    share_chosen_was_best = (
        sum(1 for r in measured if r["chosen_rank"] == 1) / n_measured if n_measured else None
    )
    share_within_1pp = (
        sum(1 for r in regrets if r <= REGRET_TOLERANCE) / n_measured if n_measured else None
    )

    if n_measured < min_sample:
        verdict = (
            f"insufficient_sample: not yet distinguishable from luck "
            f"(n={n_measured} < {min_sample})"
        )
    elif mean_regret is not None and mean_regret <= 0 and (share_within_1pp or 0) >= 0.5:
        verdict = "skill_signal"
    elif mean_regret is not None and mean_regret > 0.03:
        verdict = "review_process"
    else:
        verdict = "neutral"

    return {
        "as_of": as_of.isoformat(),
        "min_days": min_days,
        "min_sample": min_sample,
        "decisions_total": len(rows),
        "n_measured": n_measured,
        "n_unmeasurable": n_unmeasurable,
        "mean_regret": mean_regret,
        "median_regret": median_regret,
        "share_chosen_was_best": share_chosen_was_best,
        "share_within_1pp": share_within_1pp,
        "verdict": verdict,
        "rows": rows,
    }
