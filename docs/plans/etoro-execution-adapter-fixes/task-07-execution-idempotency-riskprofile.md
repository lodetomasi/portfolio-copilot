# Task 07 — execution.py: no double-send, fill ignoto ledgerato, risk profile (finding #3, #5, #8)

## File
- `src/portfolio_copilot/portfolio/execution.py` (`build_plan`, `execute`)
- `tests/test_execution.py`

## Difetti
- #3: rieseguire `execute` su un piano già inviato rimanda gli stessi ordini.
- #5: se `wait_for_fill` solleva DOPO un open/close riuscito, l'ordine accettato
  dal broker non viene mai ledgerato ("skipped" silenzioso).
- #8: `build_plan` non consulta mai il risk profile salvato (leva, quota speculativa).

## Fix
1. (#3) In `execute`, dopo i gate e prima del loop:
   `already_sent = {r.symbol for r in load_decisions(ledger_home) if r.plan_token == plan.token}`
   (import `load_decisions` da `portfolio_copilot.portfolio.ledger`). Nel loop, una
   riga con `line.symbol in already_sent` viene saltata senza chiamare il client e
   finisce nella nuova lista `result["already_sent"]`. Ogni `record_decision` in
   `execute` include `"plan_token": plan.token` E un id esplicito
   `f"{date.today().isoformat()}:{line.symbol}:{action.value}:{plan.token[:8]}"`
   (import `date` da `datetime`): due piani diversi stesso giorno/simbolo/azione non
   collidono mai sul guard anti-duplicato del ledger, e un `ValueError` da id
   duplicato non può più scattare DOPO un ordine già inviato.
2. (#5) Nel loop, separa l'invio dal poll: prima `order_response = client.open_market_order(...)` /
   `client.close_position(...)` (eccezione qui → failure `client_exception`, riga
   MAI inviata, come oggi). Poi `fill = client.wait_for_fill(...)` in un proprio
   try/except: su eccezione, registra comunque
   `record_decision({..., "price": None, "reason": line.reason +
   " [fill status unknown: wait_for_fill failed]", "plan_token": plan.token,
   "broker": "etoro", "broker_order_id": ..., "mode": plan.mode}, home=ledger_home)`
   e ritorna failure `{"error": "fill_status_unknown", "symbol": ...,
   "detail": str(exc)}` con l'id nel `ledger_ids` (l'ordine È partito: il ledger
   deve dirlo, e l'idempotency guard del punto 1 impedirà il re-invio).
3. (#8) `build_plan` nuovo parametro keyword `risk_profile: dict | None = None`
   (lo shape è quello persistito da `portfolio.risk_profile.save_risk_profile`:
   `{"answers": {...}, ...}`). Blocker aggiunti:
   - qualunque ordine con `leverage` presente e `float(leverage) > 1` → blocker
     `f"{symbol}: leverage {leverage} requested but leveraged products are excluded by design"`
     (incondizionato: i piani escludono la leva per regola di progetto);
   - se `risk_profile` è dato, `answers.speculative_share_pct` presente ed
     equity > 0: `speculative_weight = (somma amount delle positions marcate
     ESPLICITAMENTE con p.get("is_stock") is True + net buy delle righe del piano
     con is_stock True) / equity`; se `> speculative_share_pct / 100` → blocker
     `f"plan pushes single-stock share to {weight:.4f}, above the risk profile's {cap:.4f}"`.
     Le positions senza chiave `is_stock` NON contano come speculative (mai un
     blocker spurio su ETF/bond/cash: è il chiamante — wiring Phase B — a marcare
     le posizioni azionarie; documentalo nella docstring di `build_plan`).
     Aggiungi la riga di check in `checks` in entrambi i casi, indicando quante
     positions sono state contate come speculative.

## Test (rossi prima, verdi dopo)
- `test_execute_is_idempotent_on_resend_of_the_same_plan`: primo `execute` →
  `sent == ["AAPL"]`; secondo `execute` identico su stesso `ledger_home` →
  `sent == []`, `already_sent == ["AAPL"]`, client senza nuove chiamate open,
  ledger ancora a 1 record.
- `test_execute_records_ledger_when_wait_for_fill_blows_up_after_send`: fake client
  il cui `wait_for_fill` solleva `RuntimeError` → result failure
  `fill_status_unknown`, `len(load_decisions(tmp_path)) == 1`, record con
  `broker_order_id` valorizzato e `price is None`.
- `test_build_plan_blocks_leveraged_order`: ordine con `leverage=5` → blocker con
  `"leverage"`.
- `test_build_plan_blocks_when_speculative_cap_exceeded`: risk_profile
  `{"answers": {"speculative_share_pct": 25}}`, equity 1000, buy stock da 300 USD
  equivalenti → blocker con `"risk profile"`.
- `test_build_plan_without_risk_profile_behaves_as_before`: nessun `risk_profile`
  → nessun blocker nuovo sul piano felice.

## Verifica
`uv run pytest tests/test_execution.py -q`
