"""Capital auction: rank BUY candidates (buckets, stocks, cash) by marginal utility and
allocate available cash to the winners, one economic order at a time.

This module does not read the portfolio or fetch data on its own. It is a pure allocation
layer: callers build a list of :class:`Candidate` from whatever bucket-deficit / stock-score
information they already have (e.g. ``scoring.engine`` for stocks, ``portfolio.config`` targets
for buckets) and hand it to :func:`capital_auction` together with the cash to deploy.

Design notes (CLAUDE.md-aligned):
- deterministic Python, no LLM math;
- cash is never forced to be spent: "keep cash" (``decision == "NO_BUY"``) is a valid outcome;
- a stock with ``confidence < 0.5`` can never win the auction, regardless of its edge;
- an underweight core bucket gets a bonus so it beats a merely-mediocre stock on ties;
- every skip/exclusion is recorded in ``reasons`` instead of silently dropped.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from portfolio_copilot.portfolio.rebalance import FeeModel

#: Utility assigned to "do nothing, keep the cash" — the auction's reservation price.
DEFAULT_CASH_UTILITY = 55.0

#: A stock candidate below this confidence can never be bought, no matter its edge.
STOCK_CONFIDENCE_FLOOR = 0.5

#: Max bonus (utility points) awarded to a bucket for being underweight vs. target.
BUCKET_DEFICIT_BONUS = 20.0


class Candidate(BaseModel):
    """One thing the auction can spend cash on: a portfolio bucket, a single stock, or cash
    itself (the implicit "do nothing" option).

    ``edge`` is not a return forecast — it is a 0..1 conviction signal (e.g. ``score / 100``
    from the scoring engine, or ``0.5`` for a core bucket sitting exactly at target). ``risk``
    and ``confidence`` independently discount that conviction: low confidence should exclude a
    stock outright (see ``STOCK_CONFIDENCE_FLOOR``), while risk only dampens its utility.
    """

    symbol: str
    kind: Literal["bucket", "stock", "cash"]
    edge: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    thesis_health: float = Field(default=1.0, ge=0.0, le=1.0)
    fit: float = Field(default=1.0, ge=0.0, le=1.0)
    risk: float = Field(default=0.0, ge=0.0, le=1.0)
    current_weight: float = Field(ge=0.0, le=1.0)
    cap_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    deficit_eur: float = Field(default=0.0, ge=0.0)


def marginal_utility(
    candidate: Candidate,
    total_value_eur: float = 0.0,
    cash_utility: float = DEFAULT_CASH_UTILITY,
) -> float:
    """Deterministic 0..100 marginal-utility score for one auction candidate.

    ``cash`` candidates always score ``cash_utility`` (they have no cap and cannot be
    "outbid" by their own fields). A ``stock`` below :data:`STOCK_CONFIDENCE_FLOOR`
    confidence always scores ``0`` -- low confidence is a hard exclusion, not a discount.
    Otherwise: ``base = edge * confidence * thesis_health * fit * (1 - risk) * 100``, and a
    ``bucket`` gets up to ``BUCKET_DEFICIT_BONUS`` extra points, scaled by how underweight
    it is relative to its OWN target value (``deficit_eur / (current_value + deficit_eur)``,
    capped at 1.0) -- not relative to the entire portfolio, which would let a bucket whose
    target is a small slice of the portfolio never earn a meaningful bonus no matter how
    completely unfunded it is. A bucket at 0% of a fully-unfunded target gets the full
    bonus; a bucket already half-funded toward its own target gets half of it.
    """
    if candidate.kind == "cash":
        return float(cash_utility)
    if candidate.kind == "stock" and candidate.confidence < STOCK_CONFIDENCE_FLOOR:
        return 0.0

    base = (
        candidate.edge
        * candidate.confidence
        * candidate.thesis_health
        * candidate.fit
        * (1.0 - candidate.risk)
        * 100.0
    )
    if candidate.kind == "bucket":
        current_value = candidate.current_weight * total_value_eur
        target_value = current_value + candidate.deficit_eur
        deficit_share = candidate.deficit_eur / target_value if target_value > 0 else 0.0
        base += BUCKET_DEFICIT_BONUS * min(1.0, deficit_share)

    return max(0.0, min(100.0, base))


def _size_order(
    fee_model: FeeModel, cap_eur: float, remaining_cash: float
) -> tuple[float, float] | None:
    """Size one economic BUY order within ``cap_eur``, never spending more than
    ``remaining_cash`` (order value + fee). Returns ``None`` when nothing economic fits.
    """
    if cap_eur <= 0 or remaining_cash <= 0:
        return None

    value = round(min(cap_eur, max(0.0, remaining_cash - fee_model.fixed_fee_eur)), 2)
    if value <= 0 or not fee_model.is_economic(value):
        return None
    fee = round(fee_model.fee(value), 2)
    if fee / value > fee_model.max_fee_ratio + 1e-9:
        return None

    if value + fee > remaining_cash + 1e-9:
        value = round(max(0.0, remaining_cash - fee), 2)
        if value <= 0 or not fee_model.is_economic(value):
            return None
        fee = round(fee_model.fee(value), 2)
        if fee / value > fee_model.max_fee_ratio + 1e-9:
            return None

    # The retry above re-derives `fee` from a smaller, rounded `value`; with a variable
    # fee component, two independent cent-roundings can still leave value + fee a
    # fraction of a cent over remaining_cash. Shave a cent at a time (bounded -- each step
    # strictly shrinks the shortfall) until the order genuinely fits, rather than silently
    # returning an order that overspends what is actually available.
    guard = 0
    while value > 0 and value + fee > remaining_cash + 1e-9 and guard < 1000:
        value = round(value - 0.01, 2)
        if value <= 0 or not fee_model.is_economic(value):
            return None
        fee = round(fee_model.fee(value), 2)
        if fee / value > fee_model.max_fee_ratio + 1e-9:
            return None
        guard += 1
    if value <= 0 or value + fee > remaining_cash + 1e-9:
        return None

    return value, fee


def capital_auction(
    cash_eur: float,
    candidates: list[Candidate],
    fee_model: FeeModel,
    total_value_eur: float,
    min_utility_gap: float = 5.0,
    chunk: float | None = None,
) -> dict:
    """Rank candidates by marginal utility and greedily allocate ``cash_eur`` to the winners.

    A candidate only receives an order while its utility clears
    ``DEFAULT_CASH_UTILITY + min_utility_gap`` (the reservation price for keeping the cash);
    ranking is descending by utility from that point on, so as soon as one candidate falls
    below the threshold every candidate after it (all lower-ranked) does too and allocation
    stops. Each winner gets at most one order, sized as
    ``min(cap_weight room, deficit_eur if bucket else unlimited, chunk if given)`` and then
    trimmed to an economic size (``fee_model.is_economic``); a candidate that cannot produce
    an economic order is skipped (not a stop) so a smaller, lower-ranked candidate still gets
    a chance. Cash itself (``kind == "cash"``) is ranked but never receives an order.

    Returns ``{"ranking": [...], "orders": [...], "cash_kept_eur": float,
    "decision": "BUY" | "NO_BUY", "reasons": [...]}``.
    """
    if cash_eur < 0:
        raise ValueError("cash_eur cannot be negative")
    if total_value_eur < 0:
        raise ValueError("total_value_eur cannot be negative")

    reasons: list[str] = []
    scored: list[tuple[Candidate, float]] = []
    for candidate in candidates:
        utility = marginal_utility(candidate, total_value_eur=total_value_eur)
        if candidate.kind == "stock" and candidate.confidence < STOCK_CONFIDENCE_FLOOR:
            reasons.append(
                f"{candidate.symbol}: confidence {candidate.confidence:.2f} below "
                f"{STOCK_CONFIDENCE_FLOOR:.2f} floor, excluded from the auction."
            )
        scored.append((candidate, utility))

    # Descending utility; ties broken by symbol for a fully deterministic order.
    scored.sort(key=lambda item: (-item[1], item[0].symbol))
    ranking = [{"symbol": c.symbol, "utility": round(u, 4), "kind": c.kind} for c, u in scored]

    threshold = DEFAULT_CASH_UTILITY + min_utility_gap
    orders: list[dict] = []
    spent = 0.0
    # Tracks EUR already awarded THIS run per symbol, so two Candidate rows sharing a
    # symbol (e.g. from two independent discovery paths) can never jointly be awarded
    # more than cap_weight -- each row's own current_weight only reflects the
    # pre-auction state, not what earlier rows in this same auction already bought.
    awarded_by_symbol: dict[str, float] = {}

    for candidate, utility in scored:
        if candidate.kind == "cash":
            continue
        if utility < threshold:
            reasons.append(
                f"{candidate.symbol}: utility {utility:.1f} below cash-utility threshold "
                f"({threshold:.1f}); keeping remaining cash."
            )
            break

        current_value = (
            candidate.current_weight * total_value_eur
            + awarded_by_symbol.get(candidate.symbol, 0.0)
        )
        cap_room = candidate.cap_weight * (total_value_eur + cash_eur) - current_value
        if cap_room <= 0:
            reasons.append(f"{candidate.symbol}: already at or above cap_weight, skipped.")
            continue

        deficit_cap = candidate.deficit_eur if candidate.kind == "bucket" else float("inf")
        cap_eur = min(cap_room, deficit_cap)
        if chunk is not None:
            cap_eur = min(cap_eur, chunk)
        if cap_eur <= 0:
            reasons.append(f"{candidate.symbol}: no deficit room left, skipped.")
            continue

        remaining_cash = cash_eur - spent
        sized = _size_order(fee_model, cap_eur, remaining_cash)
        if sized is None:
            reasons.append(f"{candidate.symbol}: no economic order size available, skipped.")
            continue

        value, fee = sized
        orders.append(
            {
                "symbol": candidate.symbol,
                "value_eur": value,
                "fee_eur": fee,
                "fee_ratio": round(fee / value, 6),
                "reason": f"Highest marginal utility ({utility:.1f}) with room under cap/deficit.",
            }
        )
        spent += value + fee
        awarded_by_symbol[candidate.symbol] = awarded_by_symbol.get(candidate.symbol, 0.0) + value

    cash_kept_eur = round(max(0.0, cash_eur - spent), 2)
    decision: Literal["BUY", "NO_BUY"] = "BUY" if orders else "NO_BUY"
    if decision == "NO_BUY" and not reasons:
        reasons.append("No candidate cleared the cash-utility threshold; keeping cash.")

    return {
        "ranking": ranking,
        "orders": orders,
        "cash_kept_eur": cash_kept_eur,
        "decision": decision,
        "reasons": reasons,
    }
