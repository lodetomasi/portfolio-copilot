"""Replacement engine: is a current holding still worth its slot, versus a candidate or cash?

A good company is not automatically a good addition (CLAUDE.md: "Una buona società NON
equivale automaticamente a un buon acquisto"); symmetrically, a weakened thesis is not
automatically worth selling, since rotating out costs a round-trip fee. This module turns a
0-100 utility comparison into a HOLD / REPLACE / SELL_TO_CASH decision in fee-aware terms.
Nothing here decides *scores* — that is scoring/engine.py's job.
"""

from __future__ import annotations

from portfolio_copilot.models import OrderSide, SuggestedOrder
from portfolio_copilot.portfolio.rebalance import FeeModel, validate_targets

# Namespaced so it can never collide with a real, tradeable ticker (e.g. NASDAQ: CASH,
# Pathward Financial Corp) that a caller might legitimately pass as a candidate.
CASH_SYMBOL = "__CASH__"


def _normalize_symbol(symbol: str) -> str:
    return str(symbol).strip().upper()


def _validate_range(name: str, value: float, lo: float, hi: float) -> None:
    """Raise ValueError if value is outside [lo, hi] (also rejects NaN, which fails every
    comparison)."""
    if not (lo <= value <= hi):
        raise ValueError(f"{name} must be within [{lo}, {hi}], got {value!r}")


def utility(
    score: float,
    confidence: float,
    fit: float = 1.0,
    thesis_health: float = 1.0,
    risk_penalty: float = 0.0,
) -> float:
    """
    Blend a raw 0-100 score with position-specific context into a single 0-100 utility.

    ``utility`` is not a return forecast. It answers "how attractive is holding or buying
    this right now", once the score's reliability (``confidence``), how well it fits the
    rest of the portfolio (``fit``), whether the original thesis still holds
    (``thesis_health``) and a risk haircut (``risk_penalty``) are folded in:

        utility = score/100 * confidence * fit * thesis_health * (1 - risk_penalty) * 100

    Args:
        score: raw component/composite score, must be in [0, 100].
        confidence: reliability of that score, in [0, 1].
        fit: how well the position fits the rest of the portfolio, in [0, 1].
        thesis_health: whether the original investment thesis still holds, in [0, 1].
        risk_penalty: fraction of utility given up for elevated risk, in [0, 1].

    Returns:
        A float in [0, 100].

    Raises:
        ValueError: if any input is outside its valid range (NaN included).
    """
    _validate_range("score", score, 0.0, 100.0)
    _validate_range("confidence", confidence, 0.0, 1.0)
    _validate_range("fit", fit, 0.0, 1.0)
    _validate_range("thesis_health", thesis_health, 0.0, 1.0)
    _validate_range("risk_penalty", risk_penalty, 0.0, 1.0)

    raw = (score / 100.0) * confidence * fit * thesis_health * (1.0 - risk_penalty) * 100.0
    return max(0.0, min(100.0, raw))


def _hold(utility_improvement: float, reason: str) -> dict:
    return {
        "action": "HOLD",
        "sell": None,
        "buy": None,
        "utility_improvement": round(utility_improvement, 4),
        "fees_eur": 0.0,
        "reason": reason,
    }


def propose_replacement(
    current: dict,
    candidates: list[dict],
    fee_model: FeeModel,
    cash_utility: float = 55.0,
    min_improvement: float = 15.0,
    max_roundtrip_fee_ratio: float = 0.02,
    max_buy_value_by_symbol: dict[str, float] | None = None,
) -> dict:
    """
    Decide whether a current holding should be replaced, sold to cash, or left alone.

    ``current`` is ``{"symbol", "value_eur", "utility"}``; each item of ``candidates`` is
    ``{"symbol", "utility"}``. Cash is always an implicit extra candidate at
    ``cash_utility``, so the portfolio never rotates into a mediocre idea just because that
    was the best one offered.

    best = highest-utility item among candidates + cash.
    - ``best.utility - current.utility < min_improvement`` -> HOLD, gap not worth a trip.
    - best is a real candidate (REPLACE): round-trip fee (sell + fee on reinvested
      proceeds) must be within ``max_roundtrip_fee_ratio`` of current value, and the buy
      must be an economic order size (``fee_model.is_economic``); else HOLD.
    - best is cash (SELL_TO_CASH): requires the stricter
      ``current.utility < cash_utility - min_improvement`` — giving up all future upside
      needs a bigger gap than a mere rotation — plus an economic, in-ratio sell.

    ``max_buy_value_by_symbol`` (optional): symbol -> maximum EUR that can still be bought
    into that symbol without breaching a configured per-stock weight cap (CLAUDE.md:
    "limite per singolo titolo"). When the winning candidate's buy value would exceed its
    own headroom, the replacement is held instead of silently funding an over-concentrated
    position.

    Returns:
        ``{"action": "HOLD"|"REPLACE"|"SELL_TO_CASH", "sell": order-dict|None,
        "buy": order-dict|None, "utility_improvement": float, "fees_eur": float,
        "reason": str}``. Order dicts are ``SuggestedOrder.model_dump()`` shaped.
    """
    sell_value = float(current["value_eur"])
    current_utility = float(current["utility"])
    current_symbol_norm = _normalize_symbol(current["symbol"])

    # A candidate sharing the current holding's symbol can never be a real rotation --
    # selling and immediately rebuying the same ticker changes nothing but pays two fee
    # legs (CLAUDE.md: avoid unnecessary turnover / uneconomic micro-orders).
    pool = [
        {"symbol": c["symbol"], "utility": c["utility"]}
        for c in candidates
        if _normalize_symbol(c["symbol"]) != current_symbol_norm
    ]
    pool.append({"symbol": CASH_SYMBOL, "utility": cash_utility})
    best = max(pool, key=lambda c: c["utility"])

    utility_improvement = best["utility"] - current_utility
    if utility_improvement < min_improvement:
        return _hold(utility_improvement, "Utility improvement below minimum threshold")

    if sell_value <= 0:
        return _hold(utility_improvement, "Current position has no value to trade")

    if best["symbol"] == CASH_SYMBOL:
        if not (current_utility < cash_utility - min_improvement):
            return _hold(
                utility_improvement, "Improvement not large enough to justify moving to cash"
            )
        if not fee_model.is_economic(sell_value):
            return _hold(utility_improvement, "Sell order too small to be economic")
        sell_fee = round(fee_model.fee(sell_value), 2)
        if sell_fee > max_roundtrip_fee_ratio * sell_value + 1e-9:
            return _hold(utility_improvement, "Fees eat the edge")
        sell_order = SuggestedOrder(
            symbol=current["symbol"],
            side=OrderSide.SELL,
            value_eur=round(sell_value, 2),
            estimated_fee_eur=sell_fee,
            fee_ratio=round(sell_fee / sell_value, 6),
            reason=(
                f"Utility too low ({current_utility:.1f}) versus holding cash "
                f"({cash_utility:.1f})"
            ),
        )
        return {
            "action": "SELL_TO_CASH",
            "sell": sell_order.model_dump(),
            "buy": None,
            "utility_improvement": round(utility_improvement, 4),
            "fees_eur": sell_fee,
            "reason": "Utility gap versus cash justifies exiting the position",
        }

    # REPLACE path: proceeds from the sell fund the buy, fees on both legs.
    sell_fee = fee_model.fee(sell_value)
    proceeds = sell_value - sell_fee
    # Buy fee is approximated from gross proceeds rather than solved exactly against the net
    # buy value: exact under the default fixed-fee model, cent-scale approximation with a
    # variable fee component — not worth the extra complexity here (YAGNI).
    buy_fee = fee_model.fee(proceeds) if proceeds > 0 else 0.0
    buy_value = round(proceeds - buy_fee, 2)
    roundtrip_fee = round(sell_fee + buy_fee, 2)

    if roundtrip_fee > max_roundtrip_fee_ratio * sell_value + 1e-9:
        return _hold(utility_improvement, "Fees eat the edge")
    if max_buy_value_by_symbol is not None:
        cap_room = max_buy_value_by_symbol.get(_normalize_symbol(best["symbol"]))
        if cap_room is not None and buy_value > cap_room + 1e-9:
            return _hold(
                utility_improvement,
                f"Replacement buy would exceed the configured single-stock cap for "
                f"{best['symbol']} ({cap_room:.2f} EUR of headroom)",
            )
    # Gate on the same fee actually charged and reported on the order (buy_fee / buy_value),
    # not a smaller fee re-derived from is_economic(buy_value) -- fee_model.fee() is
    # monotonic in order size, so fee(buy_value) < buy_fee whenever variable_fee_pct > 0,
    # which would otherwise admit an order whose own reported fee_ratio already exceeds
    # max_fee_ratio (the exact cap this check exists to enforce).
    if buy_value <= 0 or buy_fee / buy_value > fee_model.max_fee_ratio + 1e-9:
        return _hold(
            utility_improvement, "Replacement buy would be below the minimum economic order"
        )

    sell_order = SuggestedOrder(
        symbol=current["symbol"],
        side=OrderSide.SELL,
        value_eur=round(sell_value, 2),
        estimated_fee_eur=round(sell_fee, 2),
        fee_ratio=round(sell_fee / sell_value, 6),
        reason=f"Rotate into {best['symbol']} for higher utility",
    )
    buy_order = SuggestedOrder(
        symbol=best["symbol"],
        side=OrderSide.BUY,
        value_eur=buy_value,
        estimated_fee_eur=round(buy_fee, 2),
        fee_ratio=round(buy_fee / buy_value, 6),
        reason=f"Replacement for {current['symbol']}",
    )
    return {
        "action": "REPLACE",
        "sell": sell_order.model_dump(),
        "buy": buy_order.model_dump(),
        "utility_improvement": round(utility_improvement, 4),
        "fees_eur": roundtrip_fee,
        "reason": (
            f"{best['symbol']} scores {utility_improvement:.1f} utility points higher than "
            f"{current['symbol']}"
        ),
    }


def _drift_sell_candidates(
    current_values: dict[str, float],
    targets: dict[str, float],
    fee_model: FeeModel,
    rebalance_band_abs: float,
    cash_eur: float,
) -> list[SuggestedOrder]:
    """Shared drift-sell logic behind ``propose_sells`` and ``sell_summary``.

    A bucket is a sell candidate only when its weight (over current_total + cash) exceeds
    target + band; the proposed sell brings it down to exactly target, never below, and is
    dropped if that order would be uneconomic.
    """
    current_total = sum(max(0.0, v) for v in current_values.values())
    final_total = current_total + cash_eur
    if final_total <= 0:
        return []

    candidates: list[SuggestedOrder] = []
    for symbol, value in current_values.items():
        if value <= 0:
            continue
        target = targets.get(symbol, 0.0)
        weight = value / final_total
        if weight <= target + rebalance_band_abs + 1e-12:
            continue  # at or under target + band: never sell an underweight/in-band bucket
        target_value = target * final_total
        sell_value = round(value - target_value, 2)
        if sell_value <= 0 or not fee_model.is_economic(sell_value):
            continue  # skip uneconomic orders
        fee = round(fee_model.fee(sell_value), 2)
        candidates.append(
            SuggestedOrder(
                symbol=symbol,
                side=OrderSide.SELL,
                value_eur=sell_value,
                estimated_fee_eur=fee,
                fee_ratio=round(fee / sell_value, 6),
                reason=f"Drift sell: {symbol} weight {weight:.2%} exceeds target+band",
            )
        )
    return candidates


def propose_sells(
    current_values: dict[str, float],
    targets: dict[str, float],
    fee_model: FeeModel,
    rebalance_band_abs: float = 0.03,
    allow_sells: bool = False,
    cash_eur: float = 0.0,
) -> list[dict]:
    """
    Propose SELL orders for buckets whose drift exceeds the rebalance band.

    Selling is last in the rebalancing preference order (CLAUDE.md: cash first, suspend
    buys on overweights, buy underweights, sell only past a drift/risk threshold or a
    changed thesis) — so this returns ``[]`` unless the caller opts in with
    ``allow_sells=True``. Use ``sell_summary`` to also see how many were suppressed.

    Never sells a bucket at or under target + band; only the excess above it, down to
    target and not below. Uneconomic orders are skipped.

    Raises:
        ValueError: targets don't sum to 1.0 / contain a negative weight, or cash_eur is
            negative — checked before ``allow_sells`` is consulted, so bad config is never
            silently swallowed by the disabled-sells short circuit.
    """
    validate_targets(targets)
    if cash_eur < 0:
        raise ValueError("cash_eur cannot be negative")
    if not allow_sells:
        return []
    candidates = _drift_sell_candidates(
        current_values, targets, fee_model, rebalance_band_abs, cash_eur
    )
    return [o.model_dump() for o in candidates]


def sell_summary(
    current_values: dict[str, float],
    targets: dict[str, float],
    fee_model: FeeModel,
    rebalance_band_abs: float = 0.03,
    allow_sells: bool = False,
    cash_eur: float = 0.0,
) -> dict:
    """
    Companion to ``propose_sells``: always computes drift-sell candidates regardless of
    ``allow_sells``, so a caller can report how many were suppressed instead of just
    getting back ``[]``.

    Returns:
        ``{"orders": ..., "candidate_count": int, "suppressed_count": int}`` — ``orders``
        mirrors ``propose_sells`` (empty when ``allow_sells`` is False); ``candidate_count``
        is the economic drift-sell candidates found regardless of ``allow_sells``;
        ``suppressed_count`` equals that count when sells are disabled, else 0.
    """
    validate_targets(targets)
    if cash_eur < 0:
        raise ValueError("cash_eur cannot be negative")
    candidates = _drift_sell_candidates(
        current_values, targets, fee_model, rebalance_band_abs, cash_eur
    )
    orders = candidates if allow_sells else []
    return {
        "orders": [o.model_dump() for o in orders],
        "candidate_count": len(candidates),
        "suppressed_count": 0 if allow_sells else len(candidates),
    }
