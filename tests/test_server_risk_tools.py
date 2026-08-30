"""Offline tests for the simulate_plan_risk / kelly_size MCP tools (provider mocked)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from portfolio_copilot import server
from portfolio_copilot.analytics import risk_math

FIXTURE = Path(__file__).parent / "fixtures" / "risk_math_closes.csv"


class FakeProvider:
    def __init__(self, closes: pd.DataFrame, missing: list[str] | None = None):
        self._closes = closes
        self._missing = missing or []

    def get_monthly_closes(self, tickers: dict, period: str = "max") -> pd.DataFrame:
        frame = self._closes[[c for c in self._closes.columns if c in tickers]].copy()
        frame.attrs["missing"] = list(self._missing)
        frame.attrs["source"] = "fixture"
        frame.attrs["as_of"] = "2026-08-29"
        return frame


def _fixture_closes() -> pd.DataFrame:
    return pd.read_csv(FIXTURE, index_col=0, parse_dates=True)


WEIGHTS = {"eq": 0.6, "sc": 0.2, "th": 0.2}
TICKERS = {"eq": "EQ.X", "sc": "SC.X", "th": "TH.X"}


def _simulate(monkeypatch, **overrides):
    monkeypatch.setattr(server, "provider", FakeProvider(_fixture_closes()))
    kwargs = dict(
        tickers_by_bucket=TICKERS,
        weights=WEIGHTS,
        monthly_eur=600.0,
        horizon_months=60,
        n_paths=200,
        seed=42,
    )
    kwargs.update(overrides)
    return server.simulate_plan_risk(**kwargs)


def test_simulate_plan_risk_payload_and_disclosures(monkeypatch):
    result = _simulate(monkeypatch)
    assert result["ok"] is True
    stats = result["drawdown_stats"]
    assert set(stats) == {"p50", "p95_worst", "p99_worst", "prob_worse_than"}
    assert result["shortfall_stats"]["prob_final_below_contributed"] >= 0.0
    disclosures = result["disclosures"]
    assert "stationary bootstrap" in disclosures["method"]
    assert str(disclosures["mean_block"]) in disclosures["method"]
    assert disclosures["n_obs"] == 120
    assert disclosures["not_a_forecast"] is True
    assert "var_monthly_95" in disclosures and "cvar_tail_obs" in disclosures


def test_simulate_plan_risk_cvar_matches_module_recomputation(monkeypatch):
    result = _simulate(monkeypatch)
    returns = risk_math.monthly_returns(_fixture_closes())
    w = np.array([WEIGHTS[b] for b in returns.columns])
    expected = risk_math.cvar(returns.to_numpy() @ w, alpha=0.95)
    assert result["cvar_monthly_95"] == pytest.approx(expected["cvar"])
    assert result["disclosures"]["var_monthly_95"] == pytest.approx(expected["var"])
    assert result["disclosures"]["cvar_tail_obs"] == expected["n_tail_obs"]


def test_simulate_plan_risk_same_seed_same_numbers(monkeypatch):
    a = _simulate(monkeypatch)
    b = _simulate(monkeypatch)
    assert a["drawdown_stats"] == b["drawdown_stats"]
    assert a["shortfall_stats"] == b["shortfall_stats"]


def test_simulate_plan_risk_invalid_weights_raise(monkeypatch):
    with pytest.raises(ValueError):
        _simulate(monkeypatch, weights={"eq": 0.5, "sc": 0.2, "th": 0.2})


def test_simulate_plan_risk_missing_bucket_declared_and_renormalized(monkeypatch):
    closes = _fixture_closes()[["eq", "sc"]]
    monkeypatch.setattr(server, "provider", FakeProvider(closes, missing=["th"]))
    result = server.simulate_plan_risk(
        tickers_by_bucket=TICKERS,
        weights=WEIGHTS,
        monthly_eur=600.0,
        horizon_months=24,
        n_paths=100,
        seed=1,
    )
    assert result["ok"] is True
    assert result["disclosures"]["missing_buckets"] == ["th"]
    renorm = result["disclosures"]["renormalized_weights"]
    assert renorm["eq"] == pytest.approx(0.75)
    assert renorm["sc"] == pytest.approx(0.25)


def test_simulate_plan_risk_zero_monthly_skips_shortfall(monkeypatch):
    result = _simulate(monkeypatch, monthly_eur=0.0)
    assert result["ok"] is True
    assert result["shortfall_stats"] is None


def test_kelly_size_cap_always_wins():
    for p_win in (0.55, 0.65, 0.8):
        for payoff in (1.5, 2.0, 3.0):
            result = server.kelly_size(
                p_win=p_win, payoff_ratio=payoff, sleeve_value_eur=1000.0, cap_pct=0.12
            )
            assert result["ok"] is True
            assert result["applied_fraction"] <= 0.12
            assert result["amount_eur"] <= 120.0


def test_kelly_size_invalid_inputs_return_structured_error():
    assert server.kelly_size(1.5, 2.0, 1000.0, 0.12)["ok"] is False
    assert server.kelly_size(0.6, 2.0, 0.0, 0.12)["ok"] is False
    assert server.kelly_size(0.6, 2.0, 1000.0, 0.0)["ok"] is False
