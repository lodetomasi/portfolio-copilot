"""Offline, deterministic tests for portfolio.execution (eToro plan build + send).

``FakeClient`` mirrors ``EToroClient``'s REAL method names, signatures and lowercase
statuses -- the original fake codified a wrong interface (design findings #17/#19/#20)
and hid it from every test. The end-to-end test at the bottom drives the real
``EToroClient`` through ``execute`` via ``httpx.MockTransport`` so the interface can
never silently drift again.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx
import pytest

from portfolio_copilot.brokers.etoro import Credentials, EToroClient
from portfolio_copilot.portfolio.execution import ExecutionPlan, build_plan, execute
from portfolio_copilot.portfolio.ledger import DecisionRecord, load_decisions, record_decision

FX_EUR_PER_USD = 0.92  # 1 USD = 0.92 EUR


@dataclass(frozen=True)
class FakeFeeModel:
    minimum_economic_order: float = 10.0
    fixed_fee: float = 0.0

    def fee(self, amount: float) -> float:
        return self.fixed_fee


def _order(**overrides) -> dict:
    base = {
        "symbol": "aapl",
        "side": "buy",
        "amount_eur": 100.0,
        "instrument_id": 1001,
        "min_position_exposure": 10.0,
        "red_team": "passed",
        "sector": "tech",
        "reason": "top pick",
        "decision_id": "dec-1",
    }
    base.update(overrides)
    return base


def _account(cash=1000.0, equity=1000.0) -> dict:
    return {"cash_available": cash, "equity": equity}


def _plan(**overrides):
    kwargs = dict(
        suggested_orders=[_order()],
        account=_account(),
        positions=[],
        caps={"max_single_stock_weight": 0.25, "max_sector_weight": 0.40},
        fee_model=FakeFeeModel(),
        fx_rate_eur_per_ccy=FX_EUR_PER_USD,
        mode="demo",
        as_of="2026-08-29T00:00:00Z",
    )
    kwargs.update(overrides)
    return build_plan(**kwargs)


# ---------------------------------------------------------------------------
# build_plan
# ---------------------------------------------------------------------------


def test_build_plan_happy_path_has_no_blockers_and_converts_currency():
    plan = _plan()
    assert plan.blockers == []
    assert plan.mode == "demo"
    assert plan.account_label == "etoro-demo"
    line = plan.lines[0]
    assert line.symbol == "AAPL"
    assert line.amount_eur == 100.0
    assert line.amount_account_ccy == pytest.approx(100.0 / FX_EUR_PER_USD)
    assert plan.token and len(plan.token) == 16


def test_build_plan_token_is_deterministic_and_changes_with_content():
    plan_a = _plan()
    plan_b = _plan()
    assert plan_a.token == plan_b.token
    plan_c = _plan(suggested_orders=[_order(amount_eur=101.0)])
    assert plan_c.token != plan_a.token


def test_build_plan_blocks_high_risk_buy_over_cap():
    plan = _plan(
        suggested_orders=[_order(is_high_risk=True, amount_eur=50.0)],
        caps={
            "max_single_stock_weight": 0.25,
            "max_sector_weight": 0.40,
            "max_high_risk_stock_weight": 0.02,
        },
    )
    # 50 EUR / 0.92 = 54.35 USD su equity 1000 = 5.4% > 2%
    assert any("max_high_risk_stock_weight" in b for b in plan.blockers)


def test_build_plan_allows_high_risk_buy_under_cap():
    plan = _plan(
        suggested_orders=[_order(is_high_risk=True, amount_eur=15.0)],
        caps={
            "max_single_stock_weight": 0.25,
            "max_sector_weight": 0.40,
            "max_high_risk_stock_weight": 0.02,
        },
    )
    # 15 EUR / 0.92 = 16.30 USD su equity 1000 = 1.63% < 2%
    assert plan.blockers == []
    assert any("high-risk cap for AAPL" in c for c in plan.checks)


def test_build_plan_high_risk_without_cap_key_adds_no_check_or_blocker():
    plan = _plan(suggested_orders=[_order(is_high_risk=True, amount_eur=50.0)])
    assert plan.blockers == []
    assert not any("high-risk" in c for c in plan.checks)


def test_build_plan_normal_buy_ignores_high_risk_cap():
    plan = _plan(
        caps={
            "max_single_stock_weight": 0.25,
            "max_sector_weight": 0.40,
            "max_high_risk_stock_weight": 0.02,
        },
    )
    # ordine default (100 EUR = 10.9% di equity) NON marcato is_high_risk: mai bloccato
    assert plan.blockers == []


def test_build_plan_blocks_on_missing_red_team():
    plan = _plan(suggested_orders=[_order(red_team=None)])
    assert any("red_team" in b for b in plan.blockers)


def test_build_plan_uses_red_team_by_symbol_fallback():
    plan = _plan(
        suggested_orders=[_order(red_team=None)],
        red_team_by_symbol={"AAPL": "passed"},
    )
    assert plan.blockers == []


def test_build_plan_blocks_on_missing_min_position_exposure():
    plan = _plan(suggested_orders=[_order(min_position_exposure=None)])
    assert any("min_position_exposure" in b for b in plan.blockers)


def test_build_plan_blocks_below_min_position_exposure():
    plan = _plan(suggested_orders=[_order(min_position_exposure=10_000.0)])
    assert any("minimum position exposure" in b for b in plan.blockers)


def test_build_plan_blocks_below_minimum_economic_order():
    plan = _plan(
        suggested_orders=[_order(amount_eur=1.0, min_position_exposure=0.5)],
        fee_model=FakeFeeModel(minimum_economic_order=50.0),
    )
    assert any("minimum economic" in b for b in plan.blockers)


def test_build_plan_blocks_on_duplicate_symbol():
    plan = _plan(suggested_orders=[_order(), _order(decision_id="dec-2")])
    assert any("duplicate symbol" in b for b in plan.blockers)


def test_build_plan_blocks_when_cash_insufficient():
    plan = _plan(account=_account(cash=50.0, equity=1000.0))
    assert any("exceeds" in b and "cash" in b.lower() for b in plan.blockers)


def test_build_plan_blocks_when_single_stock_cap_breached():
    plan = _plan(
        suggested_orders=[_order(amount_eur=300.0)],
        account=_account(cash=1000.0, equity=400.0),
        caps={"max_single_stock_weight": 0.10, "max_sector_weight": 0.90},
    )
    assert any("max_single_stock_weight" in b for b in plan.blockers)


def test_build_plan_blocks_when_sector_cap_breached():
    plan = _plan(
        suggested_orders=[_order(amount_eur=100.0, sector="tech")],
        positions=[{"symbol": "MSFT", "amount": 300.0, "sector": "tech"}],
        account=_account(cash=1000.0, equity=400.0),
        caps={"max_single_stock_weight": 0.99, "max_sector_weight": 0.10},
    )
    assert any("max_sector_weight" in b for b in plan.blockers)


def test_build_plan_sell_requires_position_id():
    plan = _plan(
        suggested_orders=[
            {"symbol": "MSFT", "side": "sell", "amount_eur": 50.0, "reason": "thesis broken"}
        ]
    )
    assert any("position_id" in b for b in plan.blockers)


def test_build_plan_sell_line_is_only_ever_explicit():
    plan = _plan(
        suggested_orders=[
            {
                "symbol": "MSFT",
                "side": "sell",
                "amount_eur": 50.0,
                "position_id": 77,
                "instrument_id": 2002,
                "reason": "thesis broken",
            }
        ]
    )
    assert plan.blockers == []
    assert plan.lines[0].side == "sell"
    assert plan.lines[0].position_id == 77


def test_build_plan_rejects_invalid_mode():
    with pytest.raises(ValueError):
        _plan(mode="paper")


def test_build_plan_rejects_non_positive_fx_rate():
    with pytest.raises(ValueError):
        _plan(fx_rate_eur_per_ccy=0.0)


def test_build_plan_rejects_none_fx_rate():
    with pytest.raises(ValueError):
        _plan(fx_rate_eur_per_ccy=None)


def test_build_plan_rejects_missing_symbol():
    with pytest.raises(ValueError):
        _plan(suggested_orders=[{"side": "buy", "amount_eur": 10.0}])


def test_build_plan_blocks_buy_without_instrument_id():
    plan = _plan(suggested_orders=[_order(instrument_id=None)])
    assert any("instrument_id" in b for b in plan.blockers)


def test_build_plan_blocks_leveraged_order():
    plan = _plan(suggested_orders=[_order(leverage=5)])
    assert any("leverage" in b for b in plan.blockers)


def test_build_plan_blocks_when_speculative_cap_exceeded():
    plan = _plan(
        suggested_orders=[_order(amount_eur=276.0)],  # 300 USD at 0.92
        account=_account(cash=1000.0, equity=1000.0),
        caps={"max_single_stock_weight": 0.99, "max_sector_weight": 0.99},
        risk_profile={"answers": {"speculative_share_pct": 25}},
    )
    assert any("risk profile" in b for b in plan.blockers)


def test_build_plan_speculative_cap_ignores_unmarked_positions():
    # Positions NOT explicitly marked is_stock=True (ETF, bond, cash) never count as
    # speculative: no spurious blocker on a legitimate plan.
    plan = _plan(
        suggested_orders=[_order(amount_eur=92.0)],  # 100 USD -> 10% of equity
        positions=[{"symbol": "VWCE", "amount": 800.0, "sector": "broad"}],
        account=_account(cash=1000.0, equity=1000.0),
        caps={"max_single_stock_weight": 0.99, "max_sector_weight": 0.99},
        risk_profile={"answers": {"speculative_share_pct": 25}},
    )
    assert plan.blockers == []


def test_build_plan_without_risk_profile_behaves_as_before():
    plan = _plan()
    assert plan.blockers == []


def test_build_plan_exposes_estimated_fees():
    plan = _plan(fee_model=FakeFeeModel(minimum_economic_order=10.0, fixed_fee=7.5))
    assert plan.estimated_fees == pytest.approx(7.5)


# ---------------------------------------------------------------------------
# execute
# ---------------------------------------------------------------------------


class FakeClient:
    """Mirrors ``EToroClient``'s real interface: ``account()``,
    ``open_market_order(instrument_id, amount=..., side=..., leverage=..., ...)``,
    ``close_position(position_id, instrument_id, units=None)``,
    ``wait_for_fill(order_id, *, kind, position_id=None)`` with LOWERCASE statuses."""

    def __init__(
        self,
        cash=1000.0,
        fail_instrument: int | None = None,
        reject_instrument: int | None = None,
        wait_raises: bool = False,
    ):
        self.cash = cash
        self.fail_instrument = fail_instrument
        self.reject_instrument = reject_instrument
        self.wait_raises = wait_raises
        self.opened: list[dict] = []
        self.closed: list[dict] = []
        self._instrument_by_order: dict[str, int | None] = {}

    def account(self) -> dict:
        return {"cash_available": self.cash, "source": "etoro_api", "mode": "demo"}

    def open_market_order(
        self,
        instrument_id,
        amount=None,
        side="buy",
        leverage=1,
        units=None,
        stop_loss=None,
        take_profit=None,
        settlement_type="real",
    ) -> dict:
        if instrument_id == self.fail_instrument:
            raise RuntimeError("network exploded")
        order_id = f"order-{instrument_id}"
        self.opened.append(
            {
                "instrument_id": instrument_id,
                "amount": amount,
                "side": side,
                "leverage": leverage,
                "settlement_type": settlement_type,
            }
        )
        self._instrument_by_order[order_id] = instrument_id
        return {"order_id": order_id, "reference_id": f"ref-{instrument_id}", "token": "t"}

    def close_position(self, position_id, instrument_id, units=None) -> dict:
        order_id = f"close-{position_id}"
        self.closed.append(
            {"position_id": position_id, "instrument_id": instrument_id, "units": units}
        )
        self._instrument_by_order[order_id] = instrument_id
        return {"order_id": order_id, "position_id": position_id}

    def wait_for_fill(self, order_id, *, kind="open", position_id=None, polls=10, interval_s=1.0):
        if self.wait_raises:
            raise RuntimeError("poll blew up")
        if self._instrument_by_order.get(order_id) == self.reject_instrument:
            return {"status": "rejected"}
        return {"status": "filled", "price": 123.45}


def test_execute_refuses_on_token_mismatch(tmp_path):
    plan = _plan()
    result = execute(plan, "not-the-real-token", FakeClient(), ledger_home=tmp_path)
    assert result["sent"] == []
    assert result["failed"]["error"] == "token_mismatch"
    assert result["skipped"] == ["AAPL"]
    assert result["ledger_ids"] == []
    assert load_decisions(tmp_path) == []


def test_execute_refuses_when_blockers_present(tmp_path):
    plan = _plan(suggested_orders=[_order(red_team=None)])
    result = execute(plan, plan.token, FakeClient(), ledger_home=tmp_path)
    assert result["failed"]["error"] == "blockers_present"
    assert result["sent"] == []


def test_execute_refuses_real_mode_without_double_gate(tmp_path, monkeypatch):
    monkeypatch.delenv("ETORO_ALLOW_REAL", raising=False)
    plan = _plan(mode="real")
    result = execute(plan, plan.token, FakeClient(), ledger_home=tmp_path, allow_real=False)
    assert result["failed"]["error"] == "real_mode_not_confirmed"
    assert result["sent"] == []


def test_execute_refuses_real_mode_when_only_flag_set(tmp_path):
    plan = _plan(mode="real")
    result = execute(
        plan,
        plan.token,
        FakeClient(),
        ledger_home=tmp_path,
        allow_real=False,
        env={"ETORO_ALLOW_REAL": "1"},
    )
    assert result["failed"]["error"] == "real_mode_not_confirmed"


def test_execute_refuses_real_mode_when_only_argument_set(tmp_path):
    plan = _plan(mode="real")
    result = execute(plan, plan.token, FakeClient(), ledger_home=tmp_path, allow_real=True, env={})
    assert result["failed"]["error"] == "real_mode_not_confirmed"


def test_execute_allows_real_mode_with_both_gates(tmp_path):
    plan = _plan(mode="real")
    result = execute(
        plan,
        plan.token,
        FakeClient(),
        ledger_home=tmp_path,
        allow_real=True,
        env={"ETORO_ALLOW_REAL": "1"},
    )
    assert result["failed"] is None
    assert result["sent"] == ["AAPL"]


def test_execute_refuses_when_cash_dropped_since_plan_was_built(tmp_path):
    plan = _plan()  # needs ~108.7 USD
    client = FakeClient(cash=1.0)
    result = execute(plan, plan.token, client, ledger_home=tmp_path)
    assert result["failed"]["error"] == "cash_dropped"
    assert result["sent"] == []
    assert client.opened == []


def test_execute_cash_recheck_includes_estimated_fees(tmp_path):
    # Plan built with plenty of cash; at send time the account holds 112 USD:
    # above the 108.70 buy total, below buy + 10 fee. Must refuse.
    plan = _plan(fee_model=FakeFeeModel(minimum_economic_order=10.0, fixed_fee=10.0))
    client = FakeClient(cash=112.0)
    result = execute(plan, plan.token, client, ledger_home=tmp_path)
    assert result["failed"]["error"] == "cash_dropped"
    assert client.opened == []


def test_execute_happy_path_sends_and_records_ledger(tmp_path):
    plan = _plan()
    client = FakeClient(cash=1000.0)
    result = execute(plan, plan.token, client, ledger_home=tmp_path)
    assert result["sent"] == ["AAPL"]
    assert result["failed"] is None
    assert result["skipped"] == []
    assert result["already_sent"] == []
    assert len(result["ledger_ids"]) == 1
    assert client.opened[0]["instrument_id"] == 1001
    assert client.opened[0]["side"] == "buy"
    assert client.opened[0]["settlement_type"] == "real"
    assert client.opened[0]["leverage"] == 1

    decisions = load_decisions(tmp_path)
    assert len(decisions) == 1
    rec = decisions[0]
    assert rec.symbol == "AAPL"
    assert rec.action.value == "BUY"
    assert rec.broker == "etoro"
    assert rec.broker_order_id == "order-1001"
    assert rec.mode == "demo"
    assert rec.price == 123.45
    assert rec.plan_token == plan.token


def test_execute_is_idempotent_on_resend_of_the_same_plan(tmp_path):
    plan = _plan()
    client = FakeClient(cash=1000.0)
    first = execute(plan, plan.token, client, ledger_home=tmp_path)
    assert first["sent"] == ["AAPL"]

    second = execute(plan, plan.token, client, ledger_home=tmp_path)
    assert second["sent"] == []
    assert second["already_sent"] == ["AAPL"]
    assert second["failed"] is None
    assert len(client.opened) == 1  # no second order ever reached the client
    assert len(load_decisions(tmp_path)) == 1


def test_execute_records_ledger_when_wait_for_fill_blows_up_after_send(tmp_path):
    plan = _plan()
    client = FakeClient(cash=1000.0, wait_raises=True)
    result = execute(plan, plan.token, client, ledger_home=tmp_path)
    assert result["failed"]["error"] == "fill_status_unknown"
    assert result["sent"] == []
    # The order DID leave: the ledger must say so, so a re-run cannot double-send.
    decisions = load_decisions(tmp_path)
    assert len(decisions) == 1
    assert decisions[0].broker_order_id == "order-1001"
    assert decisions[0].price is None
    assert "fill status unknown" in decisions[0].reason
    assert result["ledger_ids"] == [decisions[0].id]

    resend = execute(plan, plan.token, client, ledger_home=tmp_path)
    assert resend["already_sent"] == ["AAPL"]
    assert len(client.opened) == 1


def test_execute_stops_at_first_failure_and_skips_the_rest(tmp_path):
    plan = _plan(
        suggested_orders=[
            _order(symbol="AAPL", decision_id="d1"),
            _order(symbol="MSFT", instrument_id=2002, decision_id="d2", sector="tech"),
        ]
    )
    client = FakeClient(cash=10_000.0, fail_instrument=2002)
    result = execute(plan, plan.token, client, ledger_home=tmp_path)
    assert result["sent"] == ["AAPL"]
    assert result["failed"]["symbol"] == "MSFT"
    assert result["failed"]["error"] == "client_exception"
    assert result["skipped"] == ["MSFT"]
    assert len(result["ledger_ids"]) == 1
    assert len(load_decisions(tmp_path)) == 1


def test_execute_treats_rejected_status_as_failure_not_sent(tmp_path):
    plan = _plan()
    client = FakeClient(cash=1000.0, reject_instrument=1001)
    result = execute(plan, plan.token, client, ledger_home=tmp_path)
    assert result["sent"] == []
    assert result["failed"]["error"] == "not_filled"
    assert result["skipped"] == ["AAPL"]
    assert load_decisions(tmp_path) == []


def test_execute_sell_line_calls_close_position_not_open_order(tmp_path):
    plan = _plan(
        suggested_orders=[
            {
                "symbol": "MSFT",
                "side": "sell",
                "amount_eur": 50.0,
                "position_id": 77,
                "instrument_id": 2002,
                "reason": "thesis broken",
            }
        ]
    )
    client = FakeClient(cash=1000.0)
    result = execute(plan, plan.token, client, ledger_home=tmp_path)
    assert result["sent"] == ["MSFT"]
    assert client.opened == []
    assert client.closed[0]["position_id"] == 77
    assert client.closed[0]["instrument_id"] == 2002

    decisions = load_decisions(tmp_path)
    assert decisions[0].action.value == "SELL"


def test_execute_does_not_refetch_cash_when_disabled(tmp_path):
    plan = _plan()

    class NoAccountClient(FakeClient):
        def account(self):
            raise AssertionError("should not be called when refetch_account=False")

    client = NoAccountClient(cash=1000.0)
    result = execute(plan, plan.token, client, ledger_home=tmp_path, refetch_account=False)
    assert result["failed"] is None
    assert result["sent"] == ["AAPL"]


def test_execute_drives_the_real_etoro_client_end_to_end(tmp_path):
    """The one test findings #17/#19/#20 needed: the REAL EToroClient, mocked at the
    HTTP layer only, driven through execute()."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/trading/info/demo/pnl":
            return httpx.Response(200, json={"clientPortfolio": {"credit": 5000.0}})
        if path == "/api/v2/trading/execution/demo/orders":
            return httpx.Response(
                200, json={"orderId": 999, "referenceId": "ref-1", "token": "t"}
            )
        if path == "/api/v2/trading/info/demo/orders:lookup":
            return httpx.Response(200, json={"orderId": 999, "status": {"id": 3}})
        raise AssertionError(f"unexpected call: {request.method} {path}")

    client = EToroClient(
        Credentials(api_key="fake-key", user_key="fake-user"),
        mode="demo",
        transport=httpx.MockTransport(handler),
    )
    plan = _plan()
    result = execute(plan, plan.token, client, ledger_home=tmp_path)
    assert result["failed"] is None
    assert result["sent"] == ["AAPL"]
    decisions = load_decisions(tmp_path)
    assert decisions[0].broker_order_id == "999"
    assert decisions[0].price is None  # the lookup payload carries no price: never invented


# ---------------------------------------------------------------------------
# ledger.py optional broker fields (backward compatible)
# ---------------------------------------------------------------------------


def test_decision_record_broker_fields_default_to_none_for_backward_compatibility():
    rec = DecisionRecord(
        id="x", date="2026-01-01", symbol="AAPL", action="BUY", reason="r"
    )
    assert rec.broker is None
    assert rec.broker_order_id is None
    assert rec.mode is None


def test_record_decision_accepts_broker_fields(tmp_path):
    rec = record_decision(
        {
            "symbol": "AAPL",
            "action": "BUY",
            "reason": "r",
            "broker": "etoro",
            "broker_order_id": "order-1",
            "mode": "demo",
        },
        home=tmp_path,
    )
    assert rec.broker == "etoro"
    assert rec.broker_order_id == "order-1"
    assert rec.mode == "demo"
    reloaded = load_decisions(tmp_path)
    assert reloaded[0].broker == "etoro"


def test_execution_plan_is_a_pydantic_model_round_trips_json():
    plan = _plan()
    dumped = plan.model_dump_json()
    reloaded = ExecutionPlan.model_validate_json(dumped)
    assert reloaded.token == plan.token
    assert reloaded.lines[0].symbol == "AAPL"
