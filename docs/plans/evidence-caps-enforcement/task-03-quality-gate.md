# Task 03 — quality_gate puro in picker [DONE]

**Goal:** funzione pura `quality_gate(analysis)` in `src/portfolio_copilot/portfolio/picker.py`
che decide deterministicamente se un candidato può riempire lo slot `quality_stocks`
del conto core (mai giudizio LLM — CLAUDE.md regola 8), motivando OGNI criterio fallito.

**File coinvolti:**
- Modifica: `src/portfolio_copilot/portfolio/picker.py` (nuova funzione in coda al modulo)
- Modifica: `tests/test_picker.py` (nuova sezione in coda)

Indipendente dai Task 01-02.

## Step 1 — Scrivi i test fallenti

Aggiungi in coda a `tests/test_picker.py` (l'import esistente del modulo va esteso con
`quality_gate`):

```python
def _analysis(**overrides) -> dict:
    """Fixture con la forma REALE dell'output di analyze_stock (server.py:343-346):
    campi StockScore piatti alla radice + evidence = {"metrics", "counts"}."""
    base = {
        "ticker": "MSFT",
        "score": 82.0,
        "confidence": 0.8,
        "category": "Quality compounder",
        "evidence": {
            "metrics": {
                "revenue_growth_yoy": {"status": "VERIFIED", "use_in_score": True},
                "free_cash_flow": {"status": "SINGLE_SOURCE", "use_in_score": True},
            },
            "counts": {"MISSING": 0, "SINGLE_SOURCE": 1, "VERIFIED": 1, "CONFLICT": 0},
        },
    }
    base.update(overrides)
    return base


def test_quality_gate_passes_clean_analysis():
    result = quality_gate(_analysis())
    assert result == {"passed": True, "reasons": []}


def test_quality_gate_fails_below_min_score():
    result = quality_gate(_analysis(score=69.9))
    assert result["passed"] is False
    assert any("score" in r for r in result["reasons"])


def test_quality_gate_fails_below_min_confidence():
    result = quality_gate(_analysis(confidence=0.59))
    assert result["passed"] is False
    assert any("confidence" in r for r in result["reasons"])


def test_quality_gate_fails_on_unresolved_conflict():
    analysis = _analysis()
    analysis["evidence"]["metrics"]["free_cash_flow"] = {
        "status": "CONFLICT",
        "use_in_score": False,
    }
    result = quality_gate(analysis)
    assert result["passed"] is False
    assert any("free_cash_flow" in r for r in result["reasons"])


def test_quality_gate_passes_conflict_resolved_by_tier_a():
    analysis = _analysis()
    analysis["evidence"]["metrics"]["free_cash_flow"] = {
        "status": "CONFLICT",
        "use_in_score": True,
    }
    assert quality_gate(analysis)["passed"] is True


def test_quality_gate_fails_on_missing_evidence():
    result = quality_gate(_analysis(evidence=None))
    assert result["passed"] is False
    assert "evidence report missing" in result["reasons"]


def test_quality_gate_accumulates_every_failed_criterion():
    result = quality_gate(_analysis(score=10.0, confidence=0.1, evidence=None))
    assert result["passed"] is False
    assert len(result["reasons"]) == 3


def test_quality_gate_ignores_counts_key():
    # counts non è una metrica: non deve né crashare né generare reason spurie
    assert quality_gate(_analysis())["reasons"] == []


def test_quality_gate_custom_thresholds():
    assert quality_gate(_analysis(score=65.0), min_score=60.0)["passed"] is True
```

## Step 2 — Verifica che falliscono

Run: `uv run pytest tests/test_picker.py -k quality_gate -x -q`
Output atteso: `ImportError` (o `NameError`) su `quality_gate` — rosso confermato.

## Step 3 — Implementa

In coda a `src/portfolio_copilot/portfolio/picker.py`:

```python
def quality_gate(
    analysis: dict,
    min_score: float = 70.0,
    min_confidence: float = 0.6,
) -> dict:
    """Deterministic pass/fail for the core account's ``quality_stocks`` slot.

    ``analysis`` is the dict returned by the ``analyze_stock`` MCP tool: the
    ``StockScore`` fields flat at the root (``score`` 0-100, ``confidence`` 0-1,
    see ``server.py``) plus ``evidence`` shaped
    ``{"metrics": {name: {"status", "use_in_score", ...}}, "counts": {...}}``
    (``analytics/evidence.py::evidence_report``). ``counts`` is an aggregate tally,
    never iterated as a metric.

    Criteria (every failed one is reported, not just the first): score >= min_score;
    confidence >= min_confidence; no metric with an unresolved source conflict
    (``status == "CONFLICT"`` and ``use_in_score`` False); a missing/empty evidence
    report fails explicitly ("evidence report missing") -- a clean report is never
    invented (CLAUDE.md rule 4).

    Never applied to the ranking (no-exclusion principle): only the caller filling
    the core ``quality_stocks`` slot uses it, after ``analyze_stock`` on each
    finalist and before the red team.
    """
    reasons: list[str] = []

    score = analysis.get("score")
    if score is None or score < min_score:
        reasons.append(f"score {score!r} below minimum {min_score}")

    confidence = analysis.get("confidence")
    if confidence is None or confidence < min_confidence:
        reasons.append(f"confidence {confidence!r} below minimum {min_confidence}")

    evidence = analysis.get("evidence")
    metrics = evidence.get("metrics") if isinstance(evidence, dict) else None
    if not metrics:
        reasons.append("evidence report missing")
    else:
        for name in sorted(metrics):
            metric = metrics[name]
            if metric.get("status") == "CONFLICT" and metric.get("use_in_score") is False:
                reasons.append(f"unresolved source conflict on {name}")

    return {"passed": not reasons, "reasons": reasons}
```

## Step 4 — Verifica che passano

Run: `uv run pytest tests/test_picker.py -q && uv run pytest -q && uv run ruff check .`
Output atteso: file di test verde, poi suite intera verde (vedi nota in overview.md sul
fallimento noto da `config/portfolio.yaml` locale), ruff `All checks passed!`

## Step 5 — Commit

```bash
git add src/portfolio_copilot/portfolio/picker.py tests/test_picker.py
git commit -m "feat(picker): deterministic quality_gate for the core quality_stocks slot"
```

## Criteri di accettazione
- [ ] Analisi pulita → `{"passed": True, "reasons": []}`
- [ ] Ogni criterio fallito produce la sua reason; le reason si accumulano
- [ ] CONFLICT risolto da tier A (`use_in_score: True`) passa; non risolto boccia
- [ ] Evidence assente/vuota → bocciato con "evidence report missing"
- [ ] `counts` mai trattato come metrica
- [ ] Suite intera verde, ruff pulito
