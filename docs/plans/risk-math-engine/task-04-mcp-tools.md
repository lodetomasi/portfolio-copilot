# Task 04 — Tool MCP simulate_plan_risk + kelly_size [DONE]

**Goal:** i due tool MCP espongono il motore: `simulate_plan_risk` (bootstrap MC del mix,
disclosures complete) e `kelly_size` (sizing con cap dominante). Documentazione allineata.

**File coinvolti:**
- Modifica: `src/portfolio_copilot/server.py` (import + 2 tool in coda ai tool esistenti)
- Crea: `tests/test_server_risk_tools.py`
- Modifica: `tests/test_server_tools.py` (aggiungi i 2 nomi al set dei tool nuovi, riga ~22)
- Modifica: `CLAUDE.md` (conteggio tool 34 → 36 nelle DUE occorrenze: riga "Sessione MCP
  stdio verificata... espone **34 tool**" e riga "Tool MCP (34):", aggiungendo
  `simulate_plan_risk`, `kelly_size` all'elenco)

Dipende da: Task 01, 02, 03.

## Step 1 — Scrivi i test fallenti

Crea `tests/test_server_risk_tools.py`:

```python
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
        tickers_by_bucket=TICKERS, weights=WEIGHTS, monthly_eur=600.0,
        horizon_months=24, n_paths=100, seed=1,
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
```

## Step 2 — Verifica che falliscono

Run: `uv run pytest tests/test_server_risk_tools.py -q`
Output atteso: `AttributeError: module 'portfolio_copilot.server' has no attribute
'simulate_plan_risk'` — rosso confermato.

## Step 3 — Implementa

In `src/portfolio_copilot/server.py`:

3a. Import (rispetta l'ordine isort del blocco esistente):

```python
import numpy as np

from portfolio_copilot.analytics import risk_math
```

e ESTENDI la riga 39 esistente (`validate_targets` NON è ancora importato in server.py):

```python
from portfolio_copilot.portfolio.rebalance import (
    FeeModel,
    allocate_cash_to_targets,
    validate_targets,
)
```

3b. In coda ai tool esistenti (dopo l'ultimo `@mcp.tool()`), aggiungi:

```python
@mcp.tool()
def simulate_plan_risk(
    tickers_by_bucket: dict[str, str],
    weights: dict[str, float],
    monthly_eur: float,
    horizon_months: int,
    n_paths: int = 10000,
    seed: int = 42,
    period: str = "max",
) -> dict:
    """Monte Carlo of the plan mix via stationary bootstrap of JOINT monthly returns:
    max-drawdown distribution (severity convention p95_worst/p99_worst), shortfall vs
    total contributed, historical CVaR (Rockafellar-Uryasev). A replay-based
    simulation, not a forecast; every assumption is in `disclosures`."""
    validate_targets(weights)
    if horizon_months <= 0 or monthly_eur < 0:
        return {"ok": False, "error": "horizon_months must be > 0 and monthly_eur >= 0"}
    closes = provider.get_monthly_closes(tickers_by_bucket, period=period)
    missing = list(closes.attrs.get("missing", []))
    usable = {b: w for b, w in weights.items() if b in closes.columns}
    total = sum(usable.values())
    if not usable or total <= 0:
        return {
            "ok": False,
            "error": "No usable price history for the requested buckets",
            "missing_buckets": missing,
        }
    renormalized = {b: w / total for b, w in usable.items()}
    returns = risk_math.monthly_returns(closes[list(renormalized)])
    n_obs = len(returns)
    mean_block = risk_math.default_mean_block(n_obs)
    paths = risk_math.block_bootstrap_paths(
        returns, months=horizon_months, n_paths=n_paths, seed=seed
    )
    w = np.array([renormalized[b] for b in returns.columns])
    unit = risk_math.unit_value_paths(paths, w)
    pac = risk_math.pac_value_paths(paths, w, monthly_contribution=monthly_eur)
    contributed = monthly_eur * horizon_months
    shortfall = risk_math.shortfall_stats(pac, contributed) if contributed > 0 else None
    cvar_result = risk_math.cvar(returns.to_numpy() @ w, alpha=0.95)
    warnings = []
    if n_obs < 60:
        warnings.append(
            f"percentili di coda poco affidabili: solo {n_obs} mesi di storia"
        )
    window = [str(returns.index.min())[:10], str(returns.index.max())[:10]]
    return {
        "ok": True,
        "drawdown_stats": risk_math.drawdown_stats(unit),
        "shortfall_stats": shortfall,
        "cvar_monthly_95": cvar_result["cvar"],
        "contributed_total_eur": contributed,
        "n_paths": n_paths,
        "seed": seed,
        "source": closes.attrs.get("source"),
        "as_of": closes.attrs.get("as_of"),
        "disclosures": {
            "window": {b: window for b in returns.columns},
            "n_obs": n_obs,
            "mean_block": mean_block,
            "method": (
                f"stationary bootstrap, lunghezza blocco media {mean_block} mesi, "
                "wrap circolare, ribilanciamento mensile"
            ),
            "n_start_indices": n_obs,
            "var_monthly_95": cvar_result["var"],
            "cvar_tail_obs": cvar_result["n_tail_obs"],
            "not_a_forecast": True,
            "warnings": warnings,
            "renormalized_weights": renormalized,
            "missing_buckets": missing,
            "assumption": (
                "nessuna commissione/tassa modellata; ribilanciamento mensile "
                "(Vanguard 2010: la frequenza non cambia materialmente i risultati)"
            ),
        },
    }


@mcp.tool()
def kelly_size(
    p_win: float,
    payoff_ratio: float,
    sleeve_value_eur: float,
    cap_pct: float,
    fraction: float = 0.5,
) -> dict:
    """Half-Kelly position sizing (MacLean-Thorp-Ziemba 2010) for one satellite idea,
    ALWAYS capped by the venue's per-name cap: the cap wins over Kelly, never the
    other way around."""
    if not 0.0 < p_win < 1.0 or payoff_ratio <= 0.0:
        return {"ok": False, "error": "p_win must be in (0, 1) and payoff_ratio > 0"}
    if sleeve_value_eur <= 0.0 or not 0.0 < cap_pct <= 1.0:
        return {"ok": False, "error": "sleeve_value_eur must be > 0 and cap_pct in (0, 1]"}
    kelly = risk_math.kelly_fraction(p_win, payoff_ratio, fraction=fraction)
    applied = min(kelly, cap_pct)
    return {
        "ok": True,
        "kelly_fraction": kelly,
        "cap_pct": cap_pct,
        "applied_fraction": applied,
        "amount_eur": round(applied * sleeve_value_eur, 2),
        "note": "half-Kelly default (MacLean-Thorp-Ziemba 2010); the venue cap always wins",
    }
```

Nota: l'import di `validate_targets` è quello aggiunto al punto 3a (verificato: prima
di questo task server.py importava solo `FeeModel, allocate_cash_to_targets`).

3c. In `tests/test_server_tools.py`, aggiungi `"simulate_plan_risk", "kelly_size"` al
set dei tool nuovi (riga ~22, il commento "# The 12 tools this integration pass adds...").

3d. In `CLAUDE.md`: aggiorna le due occorrenze del conteggio (34 → 36) e aggiungi
`simulate_plan_risk`, `kelly_size` all'elenco "Tool MCP".

## Step 4 — Verifica che passano

Run: `uv run pytest tests/test_server_risk_tools.py tests/test_server_tools.py -q && uv run pytest -q && uv run ruff check .`
Output atteso: file di test verdi, suite intera verde (nota fallimento noto da config
locale), ruff `All checks passed!`

## Step 5 — Commit

```bash
git add src/portfolio_copilot/server.py tests/test_server_risk_tools.py \
  tests/test_server_tools.py CLAUDE.md
git commit -m "feat(server): simulate_plan_risk and kelly_size MCP tools on the risk-math engine"
```

## Criteri di accettazione
- [ ] Payload: drawdown_stats (convenzione severità), shortfall_stats, cvar_monthly_95
      scalare; disclosures con method "stationary bootstrap ... {mean_block} mesi",
      n_obs, var_monthly_95, cvar_tail_obs, not_a_forecast, missing, renormalized
- [ ] cvar_monthly_95 coincide col ricalcolo dal modulo sulla fixture
- [ ] Stesso seed → stessi numeri; pesi che non sommano a 1 → ValueError
- [ ] Bucket mancante → dichiarato e pesi renormalizzati (0.6/0.2 → 0.75/0.25)
- [ ] kelly_size mai sopra il cap (griglia property-style)
- [ ] tools/list include i 2 nomi nuovi; CLAUDE.md aggiornato a 36
- [ ] Suite intera verde, ruff pulito
