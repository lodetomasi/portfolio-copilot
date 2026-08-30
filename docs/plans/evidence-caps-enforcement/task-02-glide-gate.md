# Task 02 — Glide gate temporale in build_plan [DONE]

**Goal:** con `glide={"no_new_high_risk_after": "YYYY-MM-DD"}` passato a `build_plan`,
ogni buy `is_high_risk` con data piano (da `as_of`) uguale o successiva alla soglia
produce un blocker; `glide=None` (default) lascia tutto invariato.

**File coinvolti:**
- Modifica: `src/portfolio_copilot/portfolio/execution.py` (firma + docstring di
  `build_plan`, parsing prima del ciclo ordini, check nel ciclo)
- Modifica: `tests/test_execution.py`

Dipende da: Task 01 (stesso file; riusa il campo ordine `is_high_risk`).

## Step 1 — Scrivi i test fallenti

Aggiungi in `tests/test_execution.py` dopo i test del Task 01:

```python
def test_build_plan_glide_blocks_high_risk_buy_on_and_after_date():
    plan = _plan(
        suggested_orders=[_order(is_high_risk=True, amount_eur=15.0)],
        glide={"no_new_high_risk_after": "2030-09-01"},
        as_of="2030-09-01T00:00:00Z",
    )
    assert any("glide gate" in b for b in plan.blockers)


def test_build_plan_glide_allows_high_risk_buy_before_date():
    plan = _plan(
        suggested_orders=[_order(is_high_risk=True, amount_eur=15.0)],
        glide={"no_new_high_risk_after": "2030-09-01"},
        as_of="2030-08-31T23:59:59Z",
    )
    assert not any("glide gate" in b for b in plan.blockers)


def test_build_plan_glide_never_blocks_non_high_risk_buys():
    plan = _plan(
        glide={"no_new_high_risk_after": "2020-01-01"},
        as_of="2030-09-01T00:00:00Z",
    )
    assert plan.blockers == []


def test_build_plan_glide_default_none_keeps_behaviour():
    plan = _plan(suggested_orders=[_order(is_high_risk=True, amount_eur=15.0)])
    assert not any("glide" in b for b in plan.blockers)


def test_build_plan_glide_missing_key_raises():
    with pytest.raises(ValueError, match="no_new_high_risk_after"):
        _plan(glide={})


def test_build_plan_glide_malformed_date_raises():
    with pytest.raises(ValueError):
        _plan(glide={"no_new_high_risk_after": "settembre 2030"})
```

## Step 2 — Verifica che falliscono

Run: `uv run pytest tests/test_execution.py -k glide -x -q`
Output atteso: il primo test fallisce con `TypeError: build_plan() got an unexpected
keyword argument 'glide'` — rosso confermato.

## Step 3 — Implementa

In `src/portfolio_copilot/portfolio/execution.py`:

3a. Firma di `build_plan`: dopo `risk_profile: dict | None = None,` aggiungi:

```python
    glide: dict | None = None,
```

3b. Docstring, dopo il paragrafo su `risk_profile`:

```
    ``glide``: optional ``{"no_new_high_risk_after": "YYYY-MM-DD"}`` gate. From that
        date on (plan date taken from ``as_of``, falling back to today when ``as_of``
        is empty) every ``is_high_risk`` buy is blocked -- the satellite's 5-year
        horizon spends its final stretch harvesting, not adding tail risk.
        A ``glide`` dict without the key, or an unparsable date, raises ``ValueError``.
```

3c. Subito dopo la validazione di `fx_rate_eur_per_ccy` (prima del ciclo ordini):

```python
    glide_after: date | None = None
    if glide is not None:
        raw_glide = glide.get("no_new_high_risk_after")
        if raw_glide is None:
            raise ValueError("glide requires 'no_new_high_risk_after' (ISO date)")
        glide_after = date.fromisoformat(str(raw_glide)[:10])
        plan_date = date.fromisoformat(as_of[:10]) if as_of else date.today()
```

(`date` è già importato a inizio file: `from datetime import date`.)

3d. Dentro il ciclo `for order in suggested_orders:`, subito dopo il blocco che valida
`side`, aggiungi:

```python
        if (
            glide_after is not None
            and side == "buy"
            and order.get("is_high_risk") is True
            and plan_date >= glide_after
        ):
            blockers.append(
                f"{symbol}: glide gate: new high-risk buys are blocked since "
                f"{glide_after.isoformat()}"
            )
```

Nota: il blocco va DOPO l'estrazione di `symbol` (già disponibile nel ciclo).

## Step 4 — Verifica che passano

Run: `uv run pytest tests/test_execution.py -q && uv run pytest -q && uv run ruff check .`
Output atteso: file di test verde, poi suite intera verde (vedi nota in overview.md sul
fallimento noto da `config/portfolio.yaml` locale), ruff `All checks passed!`

## Step 5 — Commit

```bash
git add src/portfolio_copilot/portfolio/execution.py tests/test_execution.py
git commit -m "feat(execution): optional glide gate blocks new high-risk buys after a date"
```

## Criteri di accettazione
- [ ] Buy high-risk con `as_of` ≥ soglia → blocker "glide gate"
- [ ] Buy high-risk prima della soglia → nessun blocker glide
- [ ] Buy non high-risk → mai bloccato dal glide, a qualsiasi data
- [ ] `glide=None` → comportamento identico a prima (token inclusi)
- [ ] `glide` malformato (chiave assente o data non-ISO) → `ValueError`
- [ ] Suite intera verde, ruff pulito
