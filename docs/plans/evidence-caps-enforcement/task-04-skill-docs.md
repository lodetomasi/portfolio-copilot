# Task 04 — Documentazione regola OR e flusso quality nella skill [DONE]

**Goal:** la regola booleana `is_high_risk` e il flusso dello slot `quality_stocks`
(richiesti dal design §3 e sezione Rischi: "nel docstring E nella skill") compaiono in
`skills/stock-picker/SKILL.md`, restando sotto le 120 righe imposte dai test di formato.

**File coinvolti:**
- Modifica: `skills/stock-picker/SKILL.md` (73 righe attuali; le aggiunte sotto ne
  aggiungono 9 → 82, sotto il limite di 120)

Dipende da: Task 01 (la regola OR esiste in `build_plan`) e Task 03 (`quality_gate` esiste).

## Step 1 — Edit 1: regola OR nel punto dei caps (step 4 della skill)

In `skills/stock-picker/SKILL.md`, dopo la riga:

```
   `max_high_risk_stock_weight`. Also `capital_auction(path, cash_eur=0,
```

il paragrafo dello step 4 termina con `(that stays `deploy-cash`'s job).` — SUBITO DOPO
quella riga inserisci questo nuovo capoverso:

```
   When handing a BUY to the execution pipeline (`portfolio.execution.build_plan`), mark
   `is_high_risk = (lane == "speculative") or ("Asymmetric" in category) or
   ("High Risk" in category) or (size_bucket in {"nano", "micro"})` — the tighter
   high-risk cap and the satellite's glide gate key off that flag.
```

## Step 2 — Edit 2: flusso dello slot quality (dopo lo step 7 della skill)

Dopo la riga che termina con `Never called for `WATCH`/`NO_BUY`.` (fine step 7) e prima
della riga `8. `log_decision(...`, inserisci:

```
7b. Core `quality_stocks` slot only: run `quality_gate(<analyze_stock output>)`
   (`portfolio.picker`, deterministic: score ≥ 70, confidence ≥ 0.6, no unresolved
   CONFLICT) on each finalist; only a `passed` candidate may fill the slot — then the
   red team as usual.
```

## Step 3 — Verifica

Run: `wc -l skills/stock-picker/SKILL.md && uv run pytest -q && uv run ruff check .`
Output atteso: `82 skills/stock-picker/SKILL.md` (comunque < 120); suite verde (vedi
nota in overview.md sul fallimento noto da `config/portfolio.yaml` locale — i test di
formato skill che verificano "No broker access"/"manual"/"≤ 6 lines"/< 120 righe devono
restare verdi); ruff `All checks passed!`

Run: `claude plugin validate skills`
Output atteso: validazione passata (il frontmatter non è stato toccato).

## Step 4 — Commit

```bash
git add skills/stock-picker/SKILL.md
git commit -m "docs(skills): document is_high_risk OR rule and quality_stocks gate flow"
```

## Criteri di accettazione
- [ ] La regola OR `is_high_risk` è testualmente nella skill, identica al docstring di
      `build_plan`
- [ ] Il flusso quality slot (analyze_stock → quality_gate → red team) è nella skill
- [ ] SKILL.md resta < 120 righe e i test di formato skill passano
- [ ] `claude plugin validate skills` passa
