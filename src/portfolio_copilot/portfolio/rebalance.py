from __future__ import annotations

from dataclasses import dataclass

from portfolio_copilot.models import OrderSide, SuggestedOrder


@dataclass(frozen=True)
class FeeModel:
    fixed_fee_eur: float = 2.95
    variable_fee_pct: float = 0.0
    max_fee_ratio: float = 0.01

    def fee(self, order_value: float) -> float:
        return float(self.fixed_fee_eur + abs(order_value) * self.variable_fee_pct)

    def is_economic(self, order_value: float) -> bool:
        if order_value <= 0:
            return False
        return self.fee(order_value) / order_value <= self.max_fee_ratio

    @property
    def minimum_economic_order(self) -> float:
        if self.max_fee_ratio <= self.variable_fee_pct:
            return float("inf")
        return self.fixed_fee_eur / (self.max_fee_ratio - self.variable_fee_pct)


def validate_targets(targets: dict[str, float], tolerance: float = 1e-6) -> None:
    if any(v < 0 for v in targets.values()):
        raise ValueError("Targets cannot be negative")
    total = sum(targets.values())
    if abs(total - 1.0) > tolerance:
        raise ValueError(f"Targets must sum to 1.0, got {total:.6f}")


def allocate_cash_to_targets(
    current_values: dict[str, float],
    targets: dict[str, float],
    cash_eur: float,
    fee_model: FeeModel | None = None,
    rebalance_band_abs: float = 0.03,
) -> dict:
    """
    Cash-flow-first allocator. It never sells.

    New cash goes to buckets below target (outside the band), largest deficit first, one
    economic order at a time. Orders whose fee ratio would exceed ``max_fee_ratio`` are not
    generated; the cash stays in ``unallocated_cash`` for the next contribution.
    """
    validate_targets(targets)
    if cash_eur < 0:
        raise ValueError("cash_eur cannot be negative")

    fee_model = fee_model or FeeModel()
    current_total = sum(max(0.0, v) for v in current_values.values())
    final_total = current_total + cash_eur
    if final_total <= 0:
        return {"orders": [], "unallocated_cash": cash_eur, "target_values": {}}

    target_values = {k: final_total * w for k, w in targets.items()}
    deficits = {
        k: max(0.0, target_values[k] - current_values.get(k, 0.0))
        for k in targets
    }

    # Ignore tiny drift already inside the band. A bucket that holds no position at all
    # is always treated as out-of-band: it has not received its first contribution yet,
    # so a small target weight happening to fall within the band must not zero its
    # deficit and starve it (CLAUDE.md: "compra asset sottopeso").
    for k, target_w in targets.items():
        if current_values.get(k, 0.0) <= 0.0:
            continue
        current_w = current_values.get(k, 0.0) / current_total if current_total > 0 else 0.0
        if abs(current_w - target_w) <= rebalance_band_abs:
            deficits[k] = 0.0

    orders: list[SuggestedOrder] = []
    spent = 0.0
    ordered: dict[str, float] = dict.fromkeys(targets, 0.0)

    def _rounded_fee_within_cap(value: float, fee: float) -> bool:
        # is_economic() checks the unrounded fee/value ratio, but the order returned to
        # the caller reports fee_ratio from the *rounded* (cent-precision) fee. With a
        # variable fee component, rounding up can push that reported ratio past
        # max_fee_ratio even though the unrounded check passed. Re-check on the rounded
        # values -- with a tiny epsilon for float noise -- so the cap documented on the
        # returned order is never silently breached.
        return fee / value <= fee_model.max_fee_ratio + 1e-9

    def _try_order(symbol: str, cap: float, reason: str) -> None:
        nonlocal spent
        remaining = cash_eur - spent
        value = round(min(cap, max(0.0, remaining - fee_model.fixed_fee_eur)), 2)
        if value <= 0 or not fee_model.is_economic(value):
            return
        fee = round(fee_model.fee(value), 2)
        if not _rounded_fee_within_cap(value, fee):
            return
        if spent + value + fee > cash_eur + 1e-9:
            value = round(max(0.0, remaining - fee), 2)
            if value <= 0 or not fee_model.is_economic(value):
                return
            fee = round(fee_model.fee(value), 2)
            if not _rounded_fee_within_cap(value, fee):
                return
        orders.append(
            SuggestedOrder(
                symbol=symbol,
                side=OrderSide.BUY,
                value_eur=value,
                estimated_fee_eur=fee,
                fee_ratio=fee / value,
                reason=reason,
            )
        )
        spent += value + fee
        ordered[symbol] += value

    if cash_eur > 0:
        # Pass 1 — waterfall on deficits: fill the largest deficit first, in full, then the
        # next. A proportional split creates slices below the minimum economic order that
        # get dropped and leave cash idle for months (seen in backtests).
        positive = {k: v for k, v in deficits.items() if v > 0}
        for symbol, deficit in sorted(positive.items(), key=lambda kv: kv[1], reverse=True):
            _try_order(symbol, deficit, "Cash-flow rebalance toward target (largest deficit first)")

        # Pass 2 — top-up: if what is left is still an economic order, invest it in the most
        # underweight bucket without pushing it beyond target + band. Cash is not a target.
        if cash_eur - spent >= fee_model.minimum_economic_order + fee_model.fixed_fee_eur:
            def drift(symbol: str) -> float:
                value = current_values.get(symbol, 0.0) + ordered[symbol]
                return value / final_total - targets[symbol]

            for symbol in sorted(targets, key=drift):
                room = (targets[symbol] + rebalance_band_abs) * final_total - (
                    current_values.get(symbol, 0.0) + ordered[symbol]
                )
                _try_order(symbol, room, "Invest remaining cash within band (most underweight)")

    return {
        "orders": [o.model_dump() for o in orders],
        "unallocated_cash": round(max(0.0, cash_eur - spent), 2),
        "target_values": target_values,
        "minimum_economic_order": round(fee_model.minimum_economic_order, 2),
    }
