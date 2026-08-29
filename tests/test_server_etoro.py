"""Offline, deterministic tests for the six eToro MCP tools in server.py.

No network, no real credentials: the client factory and the ECB FX fetch are
monkeypatched; the ledger is redirected to tmp_path via PORTFOLIO_COPILOT_HOME.
"""

from __future__ import annotations

import pytest

import portfolio_copilot.server as server


class FakeEToroClient:
    """Same interface as brokers.etoro.EToroClient, deterministic and offline."""

    def __init__(self, cash=1000.0, positions=None, mode="demo"):
        self.mode = mode
        self.cash = cash
        self._positions = positions or []
        self.eligibility_calls: list[int] = []
        self.opened: list[dict] = []

    def account(self):
        return {
            "cash_available": self.cash,
            "equity": None,
            "source": "etoro_api",
            "tier": "A",
            "mode": self.mode,
            "as_of": "2026-08-29T00:00:00+00:00",
        }

    def positions(self):
        return {"positions": list(self._positions), "source": "etoro_api", "mode": self.mode}

    def orders(self):
        return {"orders": {"orders": []}, "source": "etoro_api", "mode": self.mode}

    def search_instruments(self, query):
        return {"items": [{"instrument_id": 1001, "symbol": query.upper()}]}

    def instrument(self, instrument_id):
        return {"instrument_id": instrument_id, "symbol": f"SYM{instrument_id}", "name": "Name"}

    def eligibility(self, instrument_id):
        self.eligibility_calls.append(instrument_id)
        return {"instrument_id": instrument_id, "min_position_exposure": 5.0, "tradable": True}

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
    ):
        self.opened.append({"instrument_id": instrument_id, "amount": amount})
        return {"order_id": f"order-{instrument_id}", "reference_id": "ref-1"}

    def close_position(self, position_id, instrument_id, units=None):
        return {"order_id": f"close-{position_id}", "position_id": position_id}

    def wait_for_fill(self, order_id, *, kind="open", position_id=None, polls=10, interval_s=1.0):
        return {"status": "filled", "price": 111.0}


@pytest.fixture()
def fake_client(monkeypatch, tmp_path):
    client = FakeEToroClient()
    monkeypatch.setattr(server, "_etoro_client", lambda mode=None: client)
    monkeypatch.setattr(
        server,
        "_fx_rates_or_none",
        lambda: ({"rates": {"USD": 1.0}, "source": "ecb", "as_of": "2026-08-29"}, None),
    )
    # Deterministic caps regardless of any local (git-ignored) config/portfolio.yaml.
    monkeypatch.setattr(
        server,
        "_load_portfolio_config",
        lambda: {"risk_limits": {"max_single_stock_weight": 0.25, "max_sector_weight": 0.40}},
    )
    monkeypatch.setenv("PORTFOLIO_COPILOT_HOME", str(tmp_path))
    return client


def _order(**overrides) -> dict:
    base = {
        "symbol": "AAPL",
        "side": "buy",
        "amount_eur": 100.0,
        "instrument_id": 1001,
        "min_position_exposure": 10.0,
        "red_team": "passed",
        "reason": "top pick",
    }
    base.update(overrides)
    return base


def test_etoro_tools_degrade_when_unconfigured(monkeypatch):
    monkeypatch.setattr(server, "_etoro_client", lambda mode=None: None)
    for tool in (server.etoro_account, server.etoro_positions, server.etoro_orders):
        result = tool()
        assert result["ok"] is False
        assert "not configured" in result["error"]
    assert server.etoro_search_instrument("AAPL")["ok"] is False
    assert server.prepare_execution([_order()])["ok"] is False
    plan_stub = {
        "account_label": "etoro-demo",
        "mode": "demo",
        "created": "",
        "lines": [],
        "checks": [],
        "blockers": [],
        "token": "x" * 16,
    }
    assert server.execute_plan(plan_stub, "x" * 16)["ok"] is False


def test_etoro_account_returns_banner_and_data(fake_client):
    result = server.etoro_account()
    assert result["ok"] is True
    assert result["banner"] == "Account: eToro DEMO (virtual)"
    assert result["cash_available"] == 1000.0


def test_etoro_positions_resolves_symbols_via_instrument_lookup(fake_client):
    fake_client._positions = [
        {"position_id": 1, "instrument_id": 42, "symbol": None, "name": None, "units": 2.0}
    ]
    result = server.etoro_positions()
    assert result["ok"] is True
    assert result["positions"][0]["symbol"] == "SYM42"
    assert result["positions"][0]["name"] == "Name"


def test_prepare_execution_builds_a_plan_with_token(fake_client):
    result = server.prepare_execution([_order()])
    assert result["ok"] is True
    plan = result["plan"]
    assert plan["blockers"] == []
    assert len(plan["token"]) == 16
    # USD per EUR = 1.0 -> fx_rate_eur_per_ccy = 1.0 -> same amount in account currency.
    assert plan["lines"][0]["amount_account_ccy"] == pytest.approx(100.0)
    assert result["fx"]["rate_eur_per_usd"] == pytest.approx(1.0)


def test_prepare_execution_fetches_eligibility_when_missing(fake_client):
    result = server.prepare_execution([_order(min_position_exposure=None)])
    assert result["ok"] is True
    assert fake_client.eligibility_calls == [1001]
    assert not any("min_position_exposure" in b for b in result["plan"]["blockers"])


def test_prepare_execution_refuses_without_fx(fake_client, monkeypatch):
    monkeypatch.setattr(server, "_fx_rates_or_none", lambda: (None, "boom"))
    result = server.prepare_execution([_order()])
    assert result["ok"] is False
    assert "boom" in result["error"]


def test_execute_plan_happy_path_and_ledger(fake_client, tmp_path):
    prepared = server.prepare_execution([_order()])
    plan = prepared["plan"]
    result = server.execute_plan(plan, plan["token"])
    assert result["ok"] is True
    assert result["sent"] == ["AAPL"]
    from portfolio_copilot.portfolio.ledger import load_decisions

    decisions = load_decisions(tmp_path)
    assert decisions[0].broker == "etoro"
    assert decisions[0].plan_token == plan["token"]


def test_execute_plan_refuses_wrong_token(fake_client):
    prepared = server.prepare_execution([_order()])
    result = server.execute_plan(prepared["plan"], "wrong-token")
    assert result["ok"] is False
    assert result["failed"]["error"] == "token_mismatch"


def test_execute_plan_real_mode_needs_double_gate(fake_client, monkeypatch):
    monkeypatch.delenv("ETORO_ALLOW_REAL", raising=False)
    prepared = server.prepare_execution([_order()], mode="real")
    result = server.execute_plan(prepared["plan"], prepared["plan"]["token"], allow_real=True)
    assert result["ok"] is False
    assert result["failed"]["error"] == "real_mode_not_confirmed"
    assert fake_client.opened == []
