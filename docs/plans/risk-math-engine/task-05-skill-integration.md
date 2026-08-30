# Task 05 — Integrazione skill (solo testo) [DONE]

**Goal:** le skill `investment-plan` e `stock-picker` citano i nuovi tool così il
check-in mostra la probabilità di shortfall e il satellite usa il sizing Kelly-cap.

**File coinvolti:**
- Modifica: `skills/investment-plan/SKILL.md` (1 riga nel flusso checkin)
- Modifica: `skills/stock-picker/SKILL.md` (1 riga dopo lo step 7b)

Dipende da: Task 04 (i tool devono esistere, il test skill-vs-tool li verifica).

## Step 1 — Edit investment-plan

In `skills/investment-plan/SKILL.md`, sezione "Mode: checkin", dopo lo step 5
(`allocate_cash(...)`), aggiungi:

```
5b. `simulate_plan_risk(tickers_by_bucket=<plan instruments yf_ticker>, weights=
   plan.targets, monthly_eur=plan.contribution.monthly_eur, horizon_months=60)` →
   one line in the answer: "5y risk: P(final < contributed) <x%>, worst-5% drawdown
   <y%> (bootstrap replay, not a forecast)".
```

## Step 2 — Edit stock-picker

In `skills/stock-picker/SKILL.md`, dopo il capoverso 7b (quality gate), aggiungi:

```
7c. Satellite sizing: `kelly_size(p_win=<from hit-rate or 0.5 if no track record>,
   payoff_ratio=<thesis upside/downside>, sleeve_value_eur=<satellite value>,
   cap_pct=<0.12 penny / 0.25 standard>)` — the cap always wins over Kelly.
```

## Step 3 — Verifica

Run: `wc -l skills/investment-plan/SKILL.md skills/stock-picker/SKILL.md && uv run pytest tests/ -q -k skill && uv run ruff check .`
Output atteso: entrambe le skill < 120 righe; test skill verdi (il test
backticked-tool-call ora trova `simulate_plan_risk`/`kelly_size` in server.py, quindi
passa); ruff `All checks passed!`

Run: `claude plugin validate skills`
Output atteso: validazione passata.

## Step 4 — Commit

```bash
git add skills/investment-plan/SKILL.md skills/stock-picker/SKILL.md
git commit -m "docs(skills): wire simulate_plan_risk and kelly_size into checkin and picker flows"
```

## Criteri di accettazione
- [ ] Il check-in mostra la riga di rischio a 5 anni con il caveat "not a forecast"
- [ ] Il picker documenta il sizing Kelly con cap dominante
- [ ] Entrambe le skill < 120 righe, test skill verdi, validate ok
