# Task 01 — Cap high-risk per nome in build_plan [DONE]

**Goal:** un ordine buy marcato `is_high_risk: True` che porta il peso post-plan del
simbolo oltre `caps["max_high_risk_stock_weight"]` produce un blocker (e quindi
`execute` lo rifiuta, senza modifiche a `execute`).

**File coinvolti:**
- Modifica: `src/portfolio_copilot/portfolio/execution.py` (docstring di `build_plan` +
  blocco caps, righe ~246-312)
- Modifica: `tests/test_execution.py` (nuovi test in coda alla sezione build_plan)

## Step 1 — Scrivi i test fallenti

Aggiungi in `tests/test_execution.py`, dopo `test_build_plan_token_is_deterministic_and_changes_with_content`:

```python
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
```

## Step 2 — Verifica che falliscono

Run: `uv run pytest tests/test_execution.py -k high_risk -q`
Output atteso: `2 failed, 2 passed` (`blocks_high_risk_buy_over_cap` e
`allows_high_risk_buy_under_cap` falliscono — il primo perché nessun blocker viene
prodotto, il secondo sull'assenza del check; gli altri due passano già per assenza
della feature: è il rosso che conta sui primi due).

## Step 3 — Implementa

In `src/portfolio_copilot/portfolio/execution.py`, dentro `build_plan`:

3a. Nel docstring, DOPO la fine del paragrafo che elenca i campi degli ordini
(execution.py righe 111-115, termina con `-- falls back to
``red_team_by_symbol[symbol]`` when absent).` a riga 115 — non spezzare la frase a
metà), aggiungi come nuovo paragrafo:

```
        is_high_risk (default False) -- marks the order for the tighter
        ``caps["max_high_risk_stock_weight"]`` per-name cap. Caller rule (OR, any
        signal is enough, from ``picker.annotate`` output):
        ``(lane == "speculative") or ("Asymmetric" in category) or
        ("High Risk" in category) or (size_bucket in {"nano", "micro"})``.
```

3b. Nel blocco `if buy_lines:` → ramo `else` (equity > 0), dopo la costruzione di
`sector_by_symbol` / `net_by_sector`, aggiungi la mappa:

```python
            high_risk_symbols = {
                str(order.get("symbol", "")).strip().upper()
                for order in suggested_orders
                if order.get("is_high_risk") is True
            }
```

3c. Dentro il ciclo `for line in buy_lines:` esistente, dopo il blocco
`if max_single is not None:` e prima di `sector = sector_by_symbol.get(...)`:

```python
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
```

## Step 4 — Verifica che passano

Run: `uv run pytest tests/test_execution.py -q && uv run pytest -q && uv run ruff check .`
Output atteso: file di test verde, poi suite intera verde (vedi nota in overview.md sul
fallimento noto da `config/portfolio.yaml` locale), ruff `All checks passed!`

## Step 5 — Commit

```bash
git add src/portfolio_copilot/portfolio/execution.py tests/test_execution.py
git commit -m "feat(execution): enforce max_high_risk_stock_weight per-name cap in build_plan"
```

## Criteri di accettazione
- [ ] Buy high-risk oltre il cap → blocker con `max_high_risk_stock_weight` nel testo
- [ ] Buy high-risk sotto il cap → nessun blocker, check presente
- [ ] `caps` senza la chiave → nessun check/blocker high-risk (comportamento invariato)
- [ ] Buy non marcato → mai valutato contro il cap high-risk
- [ ] Suite intera verde, ruff pulito
