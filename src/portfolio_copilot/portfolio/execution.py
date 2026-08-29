"""eToro execution flow: turn suggested orders into a confirmed, one-by-one execution.

Pure orchestration against an *injected* client (never imported here, never constructed
here) so this module stays offline-testable with a fake. The client is expected to expose:

    get_cash_available() -> float
        Current available cash in the account's own currency (USD for eToro).
    open_market_order(*, symbol, instrument_id, amount, settlement_type, leverage) -> dict
        Places a market BUY. Returns at least an order/reference id (e.g. ``orderId``).
    close_position(*, position_id, instrument_id, units=None) -> dict
        Closes (fully or partially) an open position. Returns at least an order id.
    wait_for_fill(*, order, side, symbol=None, instrument_id=None, position_id=None) -> dict
        Polls until the order/close reaches a terminal state and returns at least
        ``{"status": "Filled" | "Rejected" | ...}``, plus ``price``/``avg_price`` when known.
        Bounded polling (e.g. 10 x 1s) and the demo/real, open/close branching described in
        the eToro API notes are the client's responsibility, not this module's.

Two steps, matching CLAUDE.md's "never invent an order, never send silently" rule:

1. ``build_plan`` turns already-decided ``suggested_orders`` (from the auction/picker/
   replacement engines, never re-derived here) into an :class:`ExecutionPlan` with EUR
   amounts converted to the account currency, every pre-trade check run, and a
   deterministic ``token`` binding the user's confirmation to this *exact* plan.
2. ``execute`` refuses on a token mismatch, on any blocker, and on real-mode without the
   explicit double gate; otherwise it sends each line one by one, stops at the first
   failure, and records only what was actually filled in the decision ledger.

Nothing here decides *what* to buy or sell -- that is the auction/picker/replacement
engines' job. Nothing here talks to any HTTP endpoint -- that is the injected client's job.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from portfolio_copilot.models import Decision
from portfolio_copilot.portfolio.ledger import load_decisions, record_decision

_MODE_TO_ACCOUNT_LABEL = {"demo": "etoro-demo", "real": "etoro-real"}


class PlanLine(BaseModel):
    """One order in an execution plan, already sized in both currencies."""

    symbol: str
    instrument_id: int | None = None
    side: Literal["buy", "sell"]
    amount_eur: float
    amount_account_ccy: float
    units: float | None = None
    # Passed through to the client as given: eToro's pnl payload carries positionID as an
    # int, and a str-vs-int comparison in the close poll would misread an open position.
    position_id: int | str | None = None
    reason: str = ""
    red_team: str | None = None
    decision_id: str | None = None

    @field_validator("symbol")
    @classmethod
    def _symbol_upper(cls, value: str) -> str:
        value = str(value).strip().upper()
        if not value:
            raise ValueError("symbol cannot be empty")
        return value


class ExecutionPlan(BaseModel):
    """A confirmed-or-not plan to send to eToro: what, checks run, and any blocker."""

    account_label: Literal["etoro-demo", "etoro-real"]
    mode: str
    created: str
    lines: list[PlanLine] = Field(default_factory=list)
    checks: list[str] = Field(default_factory=list)
    blockers: list[str] = Field(default_factory=list)
    estimated_fees: float = 0.0  # account currency; the pre-send cash re-check reuses it
    token: str


def _canonical_token(mode: str, lines: list[PlanLine]) -> str:
    """Deterministic token over (mode, lines): the same plan always yields the same token,
    and editing a single field (amount, symbol, side...) changes it -- that is the whole
    point of binding the user's confirmation to *this exact* plan."""
    payload = {"mode": mode, "lines": [line.model_dump(mode="json") for line in lines]}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def build_plan(
    suggested_orders: list[dict],
    account: dict,
    positions: list[dict],
    caps: dict,
    fee_model: Any,
    fx_rate_eur_per_ccy: float,
    mode: str,
    red_team_by_symbol: dict[str, str] | None = None,
    as_of: str = "",
    risk_profile: dict | None = None,
) -> ExecutionPlan:
    """Build an :class:`ExecutionPlan` from already-decided orders. Never derives a SELL:
    a line is a sell only if ``suggested_orders`` already says ``side: "sell"``.

    ``suggested_orders`` items (fields read, all optional unless noted):
        symbol (required), side ("buy" default | "sell"), amount_eur (required for buy),
        instrument_id, position_id (required-by-blocker for sell), units, reason,
        decision_id, is_stock (default True), sector, min_position_exposure (account
        currency, from the eligibility check), red_team ("passed" | "rejected: ..." | None
        -- falls back to ``red_team_by_symbol[symbol]`` when absent).

        is_high_risk (default False) -- marks the order for the tighter
        ``caps["max_high_risk_stock_weight"]`` per-name cap. Caller rule (OR, any
        signal is enough, from ``picker.annotate`` output):
        ``(lane == "speculative") or ("Asymmetric" in category) or
        ("High Risk" in category) or (size_bucket in {"nano", "micro"})``.

    ``account``: {"cash_available": float, "equity": float | None} in account currency.
    ``positions``: current account positions, each {"symbol", "amount" (account currency,
        exposure), "sector"}.
    ``caps``: {"max_single_stock_weight": float | None, "max_sector_weight": float | None},
        evaluated as (existing exposure + net plan exposure) / equity.
    ``fee_model``: any object exposing ``.fee(amount) -> float`` and
        ``.minimum_economic_order`` (account currency), e.g. ``portfolio.rebalance.FeeModel``
        configured for the venue's own fee schedule.
    ``fx_rate_eur_per_ccy``: EUR value of one unit of the account currency (must be > 0);
        ``amount_account_ccy = amount_eur / fx_rate_eur_per_ccy``.
    ``mode``: "demo" | "real".
    ``risk_profile``: the dict persisted by ``portfolio.risk_profile.save_risk_profile``
        (``{"answers": {...}, ...}``), or ``None`` to skip profile checks. When given and
        ``answers.speculative_share_pct`` is present, the post-plan single-stock share of
        equity is capped; only positions EXPLICITLY marked ``is_stock: True`` count as
        speculative (the caller marks them -- an unmarked ETF/bond/cash position must
        never trigger a spurious blocker).
    """
    if mode not in _MODE_TO_ACCOUNT_LABEL:
        raise ValueError(f"mode must be 'demo' or 'real', got {mode!r}")
    if fx_rate_eur_per_ccy is None or fx_rate_eur_per_ccy <= 0:
        raise ValueError(f"fx_rate_eur_per_ccy must be > 0, got {fx_rate_eur_per_ccy!r}")

    red_team_by_symbol = red_team_by_symbol or {}
    checks: list[str] = []
    blockers: list[str] = []
    lines: list[PlanLine] = []
    seen_symbols: set[str] = set()

    for order in suggested_orders:
        symbol = str(order.get("symbol", "")).strip().upper()
        if not symbol:
            raise ValueError(f"suggested order missing 'symbol': {order!r}")
        side = order.get("side", "buy")
        if side not in ("buy", "sell"):
            raise ValueError(f"{symbol}: side must be 'buy' or 'sell', got {side!r}")

        if symbol in seen_symbols:
            blockers.append(f"{symbol}: duplicate symbol in plan")
        seen_symbols.add(symbol)

        leverage = order.get("leverage")
        if leverage is not None and float(leverage) > 1:
            blockers.append(
                f"{symbol}: leverage {leverage} requested but leveraged products are "
                "excluded by design"
            )

        amount_eur = order.get("amount_eur")
        if side == "buy":
            if amount_eur is None or amount_eur <= 0:
                blockers.append(f"{symbol}: buy missing a positive amount_eur")
                amount_eur = 0.0
        else:
            if order.get("position_id") is None:
                blockers.append(f"{symbol}: sell missing position_id")
            amount_eur = float(amount_eur) if amount_eur is not None else 0.0
        amount_account_ccy = float(amount_eur) / fx_rate_eur_per_ccy

        red_team = order.get("red_team") or red_team_by_symbol.get(symbol)
        is_stock = order.get("is_stock", True)
        if side == "buy" and is_stock and red_team != "passed":
            blockers.append(f"{symbol}: buy missing red_team=='passed' (got {red_team!r})")
            checks.append(f"red_team check for {symbol}: FAILED ({red_team!r})")
        elif side == "buy" and is_stock:
            checks.append(f"red_team check for {symbol}: passed")

        if side == "buy" and order.get("instrument_id") is None:
            # Beyond the design's 20 findings, required by #17: the real client cannot
            # send an order without the instrument id.
            blockers.append(f"{symbol}: buy missing instrument_id")

        if side == "buy":
            min_exposure = order.get("min_position_exposure")
            if min_exposure is None:
                blockers.append(f"{symbol}: missing min_position_exposure (eligibility unknown)")
            elif amount_account_ccy < min_exposure:
                blockers.append(
                    f"{symbol}: amount {amount_account_ccy:.2f} below instrument minimum "
                    f"position exposure {min_exposure:.2f}"
                )
            minimum_economic_order = getattr(fee_model, "minimum_economic_order", 0.0)
            if amount_account_ccy < minimum_economic_order:
                blockers.append(
                    f"{symbol}: amount {amount_account_ccy:.2f} below minimum economic "
                    f"order {minimum_economic_order:.2f}"
                )
            checks.append(
                f"minimum-order check for {symbol}: amount={amount_account_ccy:.2f} "
                f"vs min_economic={minimum_economic_order:.2f} "
                f"min_exposure={min_exposure!r}"
            )

        lines.append(
            PlanLine(
                symbol=symbol,
                instrument_id=order.get("instrument_id"),
                side=side,
                amount_eur=float(amount_eur),
                amount_account_ccy=amount_account_ccy,
                units=order.get("units"),
                position_id=order.get("position_id"),
                reason=order.get("reason") or "",
                red_team=red_team,
                decision_id=order.get("decision_id"),
            )
        )

    # Cash check: total buy amount + estimated fees must fit in available cash.
    buy_lines = [line for line in lines if line.side == "buy"]
    total_buy = sum(line.amount_account_ccy for line in buy_lines)
    fee_fn = getattr(fee_model, "fee", None)
    estimated_fees = (
        sum(fee_fn(line.amount_account_ccy) for line in buy_lines) if fee_fn else 0.0
    )
    cash_available = account.get("cash_available")
    if cash_available is None:
        blockers.append("account cash_available is unknown")
    else:
        checks.append(
            f"cash check: buy total {total_buy:.2f} + fees {estimated_fees:.2f} "
            f"vs available {cash_available:.2f}"
        )
        if total_buy + estimated_fees > cash_available:
            blockers.append(
                f"buy total {total_buy:.2f} + fees {estimated_fees:.2f} exceeds "
                f"available cash {cash_available:.2f}"
            )

    # Concentration caps, evaluated on account equity (existing exposure + net plan move).
    if buy_lines:
        equity = account.get("equity")
        if equity is None:
            equity = float(account.get("cash_available") or 0.0) + sum(
                float(p.get("amount", 0.0)) for p in positions
            )
        if equity <= 0:
            blockers.append("cannot evaluate concentration caps: account equity <= 0")
        else:
            existing_by_symbol: dict[str, float] = {}
            existing_by_sector: dict[str, float] = {}
            for p in positions:
                sym = str(p.get("symbol", "")).strip().upper()
                amt = float(p.get("amount", 0.0))
                if sym:
                    existing_by_symbol[sym] = existing_by_symbol.get(sym, 0.0) + amt
                sector = p.get("sector")
                if sector:
                    existing_by_sector[sector] = existing_by_sector.get(sector, 0.0) + amt

            net_by_symbol: dict[str, float] = {}
            net_by_sector: dict[str, float] = {}
            sector_by_symbol: dict[str, str] = {}
            for order in suggested_orders:
                symbol = str(order.get("symbol", "")).strip().upper()
                sign = 1.0 if order.get("side", "buy") == "buy" else -1.0
                amt_eur = order.get("amount_eur") or 0.0
                amt_ccy = float(amt_eur) / fx_rate_eur_per_ccy
                net_by_symbol[symbol] = net_by_symbol.get(symbol, 0.0) + sign * amt_ccy
                sector = order.get("sector")
                if sector:
                    sector_by_symbol[symbol] = sector
                    net_by_sector[sector] = net_by_sector.get(sector, 0.0) + sign * amt_ccy

            high_risk_symbols = {
                str(order.get("symbol", "")).strip().upper()
                for order in suggested_orders
                if order.get("is_high_risk") is True
            }
            max_single = caps.get("max_single_stock_weight")
            max_sector = caps.get("max_sector_weight")
            for line in buy_lines:
                if max_single is not None:
                    exposure = existing_by_symbol.get(line.symbol, 0.0) + net_by_symbol.get(
                        line.symbol, 0.0
                    )
                    weight = exposure / equity
                    checks.append(
                        f"single-stock cap for {line.symbol}: weight={weight:.4f} "
                        f"vs max={max_single:.4f}"
                    )
                    if weight > max_single:
                        blockers.append(
                            f"{line.symbol}: post-plan weight {weight:.4f} exceeds "
                            f"max_single_stock_weight {max_single:.4f}"
                        )
                max_high_risk = caps.get("max_high_risk_stock_weight")
                if max_high_risk is not None and line.symbol in high_risk_symbols:
                    exposure = existing_by_symbol.get(line.symbol, 0.0) + net_by_symbol.get(
                        line.symbol, 0.0
                    )
                    weight = exposure / equity
                    checks.append(
                        f"high-risk cap for {line.symbol}: weight={weight:.4f} "
                        f"vs max={max_high_risk:.4f}"
                    )
                    if weight > max_high_risk:
                        blockers.append(
                            f"{line.symbol}: post-plan weight {weight:.4f} exceeds "
                            f"max_high_risk_stock_weight {max_high_risk:.4f}"
                        )
                sector = sector_by_symbol.get(line.symbol)
                if max_sector is not None and sector is not None:
                    exposure = existing_by_sector.get(sector, 0.0) + net_by_sector.get(
                        sector, 0.0
                    )
                    weight = exposure / equity
                    checks.append(
                        f"sector cap for {sector} (via {line.symbol}): weight={weight:.4f} "
                        f"vs max={max_sector:.4f}"
                    )
                    if weight > max_sector:
                        blockers.append(
                            f"{sector}: post-plan weight {weight:.4f} exceeds "
                            f"max_sector_weight {max_sector:.4f}"
                        )

            # Risk-profile speculative cap: post-plan single-stock share of equity.
            spec_cap_pct = ((risk_profile or {}).get("answers") or {}).get(
                "speculative_share_pct"
            )
            if spec_cap_pct is not None:
                spec_cap = float(spec_cap_pct) / 100.0
                stock_positions = [p for p in positions if p.get("is_stock") is True]
                spec_existing = sum(float(p.get("amount", 0.0)) for p in stock_positions)
                spec_net = 0.0
                for order in suggested_orders:
                    if not order.get("is_stock", True):
                        continue
                    sign = 1.0 if order.get("side", "buy") == "buy" else -1.0
                    spec_net += sign * float(order.get("amount_eur") or 0.0) / fx_rate_eur_per_ccy
                spec_weight = (spec_existing + spec_net) / equity
                checks.append(
                    f"speculative cap: post-plan single-stock weight={spec_weight:.4f} "
                    f"vs max={spec_cap:.4f} ({len(stock_positions)} existing positions "
                    "counted as stock)"
                )
                if spec_weight > spec_cap:
                    blockers.append(
                        f"plan pushes single-stock share to {spec_weight:.4f}, above the "
                        f"risk profile's {spec_cap:.4f}"
                    )

    token = _canonical_token(mode, lines)
    return ExecutionPlan(
        account_label=_MODE_TO_ACCOUNT_LABEL[mode],
        mode=mode,
        created=as_of,
        lines=lines,
        checks=checks,
        blockers=blockers,
        estimated_fees=estimated_fees,
        token=token,
    )


def _refusal(reason: str, detail: str, plan: ExecutionPlan) -> dict:
    return {
        "sent": [],
        "failed": {"error": reason, "detail": detail},
        "skipped": [line.symbol for line in plan.lines],
        "already_sent": [],
        "ledger_ids": [],
    }


def execute(
    plan: ExecutionPlan,
    token: str,
    client: Any,
    ledger_home: Any = None,
    allow_real: bool = False,
    env: Any = None,
    refetch_account: bool = True,
) -> dict:
    """Send ``plan`` one line at a time, stopping at the first failure.

    ``client`` is an ``EToroClient`` (or a fake with the same interface): ``account()``,
    ``open_market_order(instrument_id, amount=..., side=..., leverage=..., settlement_type=...)``,
    ``close_position(position_id, instrument_id, units=None)`` and
    ``wait_for_fill(order_id, kind="open"|"close", position_id=None)`` with lowercase
    terminal statuses.

    Refuses outright (no line sent) when: ``token`` does not match ``plan.token`` (the plan
    was edited after being shown to the user); ``plan.blockers`` is non-empty; or
    ``plan.mode == "real"`` without both ``allow_real=True`` and ``env["ETORO_ALLOW_REAL"]
    == "1"`` -- real execution is never a default and never inferred.

    Never double-sends: every ledgered line carries ``plan_token``, and a line whose
    symbol is already recorded for this exact plan is skipped (reported under
    ``already_sent``), so re-running ``execute`` on the same plan is a no-op for the
    lines that already left. An order that was accepted but whose fill poll failed is
    still ledgered (price ``None``, reason marked) -- silence there could hide a real
    trade.

    Returns ``{"sent": [symbol, ...], "failed": {"symbol"?, "error", "detail"} | None,
    "skipped": [symbol, ...], "already_sent": [symbol, ...],
    "ledger_ids": [decision_id, ...]}``.
    """
    env = os.environ if env is None else env

    if token != plan.token:
        return _refusal("token_mismatch", "the confirmation token does not match this plan", plan)
    if plan.blockers:
        return _refusal("blockers_present", "; ".join(plan.blockers), plan)
    if plan.mode == "real" and not (allow_real and env.get("ETORO_ALLOW_REAL") == "1"):
        return _refusal(
            "real_mode_not_confirmed",
            "real execution requires allow_real=True and ETORO_ALLOW_REAL=1",
            plan,
        )

    already_sent = sorted(
        {r.symbol for r in load_decisions(ledger_home) if r.plan_token == plan.token}
    )
    pending_lines = [line for line in plan.lines if line.symbol not in already_sent]

    if refetch_account and pending_lines:
        try:
            cash_now = client.account().get("cash_available")
        except Exception as exc:  # noqa: BLE001 -- degrade to a typed refusal, never propagate
            return {**_refusal("cash_refetch_failed", str(exc), plan), "already_sent": already_sent}
        if cash_now is None:
            return {
                **_refusal("cash_unknown", "the account did not report cash_available", plan),
                "already_sent": already_sent,
            }
        total_buy_needed = sum(
            line.amount_account_ccy for line in pending_lines if line.side == "buy"
        )
        if cash_now < total_buy_needed + plan.estimated_fees:
            return {
                **_refusal(
                    "cash_dropped",
                    f"available cash {cash_now:.2f} is now below the plan's need "
                    f"{total_buy_needed:.2f} + estimated fees {plan.estimated_fees:.2f}",
                    plan,
                ),
                "already_sent": already_sent,
            }

    def _ledger_id(symbol: str, action: Decision) -> str:
        # Unique per plan: two different plans on the same day/symbol/action must not
        # collide on the ledger's duplicate-id guard after an order already left.
        return f"{date.today().isoformat()}:{symbol}:{action.value}:{plan.token[:8]}"

    sent: list[str] = []
    ledger_ids: list[str] = []
    for idx, line in enumerate(plan.lines):
        if line.symbol in already_sent:
            continue
        remaining = [
            later.symbol
            for later in plan.lines[idx + 1 :]
            if later.symbol not in already_sent
        ]
        action = Decision.BUY if line.side == "buy" else Decision.SELL
        try:
            if line.side == "buy":
                order_response = client.open_market_order(
                    line.instrument_id,
                    amount=line.amount_account_ccy,
                    side="buy",
                    leverage=1,
                    settlement_type="real",
                )
            else:
                order_response = client.close_position(
                    line.position_id, line.instrument_id, units=line.units
                )
        except Exception as exc:  # noqa: BLE001 -- stop at first failure, never retry silently
            return {
                "sent": sent,
                "failed": {"symbol": line.symbol, "error": "client_exception", "detail": str(exc)},
                "skipped": [line.symbol, *remaining],
                "already_sent": already_sent,
                "ledger_ids": ledger_ids,
            }

        order_id = order_response.get("order_id") or order_response.get("reference_id")
        broker_order_id = str(order_id or "")

        try:
            if line.side == "buy":
                fill = client.wait_for_fill(order_id, kind="open")
            else:
                fill = client.wait_for_fill(
                    order_id, kind="close", position_id=line.position_id
                )
        except Exception as exc:  # noqa: BLE001 -- the order DID leave: ledger it, then stop
            record = record_decision(
                {
                    "id": _ledger_id(line.symbol, action),
                    "symbol": line.symbol,
                    "action": action.value,
                    "amount_eur": line.amount_eur,
                    "price": None,
                    "reason": f"{line.reason} [fill status unknown: wait_for_fill failed]",
                    "sources": ["etoro_api"],
                    "broker": "etoro",
                    "broker_order_id": broker_order_id,
                    "mode": plan.mode,
                    "plan_token": plan.token,
                },
                home=ledger_home,
            )
            ledger_ids.append(record.id)
            return {
                "sent": sent,
                "failed": {
                    "symbol": line.symbol,
                    "error": "fill_status_unknown",
                    "detail": str(exc),
                },
                "skipped": remaining,
                "already_sent": already_sent,
                "ledger_ids": ledger_ids,
            }

        status = str(fill.get("status") or "").lower()
        if status != "filled":
            return {
                "sent": sent,
                "failed": {
                    "symbol": line.symbol,
                    "error": "not_filled",
                    "detail": f"status={fill.get('status')!r}",
                },
                "skipped": [line.symbol, *remaining],
                "already_sent": already_sent,
                "ledger_ids": ledger_ids,
            }

        price = fill.get("price") if fill.get("price") is not None else fill.get("avg_price")
        record = record_decision(
            {
                "id": _ledger_id(line.symbol, action),
                "symbol": line.symbol,
                "action": action.value,
                "amount_eur": line.amount_eur,
                "price": price,
                "reason": line.reason,
                "sources": ["etoro_api"],
                "broker": "etoro",
                "broker_order_id": broker_order_id,
                "mode": plan.mode,
                "plan_token": plan.token,
            },
            home=ledger_home,
        )
        ledger_ids.append(record.id)
        sent.append(line.symbol)

    return {
        "sent": sent,
        "failed": None,
        "skipped": [],
        "already_sent": already_sent,
        "ledger_ids": ledger_ids,
    }
