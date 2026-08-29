# Task 06 — execution.py: interfaccia client reale, fx, fee nel re-check (finding #4, #6, #17, #19, #20)

## File
- `src/portfolio_copilot/portfolio/execution.py` (`build_plan`, `ExecutionPlan`, `execute`)
- `tests/test_execution.py` (FakeClient + test end-to-end col client reale)

## Difetti
- #17/#19: `execute` chiama `client.get_cash_available()`,
  `open_market_order(symbol=..., ...)`, `wait_for_fill(order=..., side=...)` —
  nessuno di questi esiste su `EToroClient` (firme reali:
  `account() -> {"cash_available": ...}`,
  `open_market_order(instrument_id, amount=None, side="buy", leverage=1, units=None,
  ..., settlement_type="real") -> {"order_id", "reference_id", ...}`,
  `close_position(position_id, instrument_id, units=None) -> {"order_id", ...}`,
  `wait_for_fill(order_id, kind="open"|"close", position_id=None, ...) -> {"status": lowercase}`).
- #20: `execute` confronta `status != "Filled"` ma il client normalizza in minuscolo.
- #6: `fx_rate_eur_per_ccy=None` → `TypeError` non gestito in `build_plan`.
- #4: il re-check cash pre-invio esclude le fee stimate (il check di `build_plan` le include).

## Fix
1. `build_plan`: guardia esplicita
   `if fx_rate_eur_per_ccy is None or fx_rate_eur_per_ccy <= 0: raise ValueError(...)`.
2. `build_plan`: un BUY senza `instrument_id` → blocker
   `f"{symbol}: buy missing instrument_id"` (il client reale non può inviare senza).
   NOTA: aggiunta oltre i 20 finding del design, resa necessaria da #17 (la firma
   reale `open_market_order(instrument_id, ...)` fallirebbe a runtime).
3b. `PlanLine.position_id` diventa `int | str | None` e viene passato al client
   così com'è: il payload pnl di eToro porta `positionID` int, e un confronto
   str-vs-int in `_poll_close_status` farebbe sembrare chiusa una posizione ancora
   aperta. `build_plan` NON converte (mai inventare tipi).
3. `ExecutionPlan`: nuovo campo `estimated_fees: float = 0.0`, valorizzato in
   `build_plan` con la somma già calcolata per il cash check.
4. `execute`, re-fetch cash: `account = client.account()`;
   `cash_now = account.get("cash_available")`; eccezione → refusal
   `cash_refetch_failed`; `cash_now is None` → refusal `cash_unknown`;
   `cash_now < total_buy_needed + plan.estimated_fees` → refusal `cash_dropped`.
5. `execute`, invio BUY:
   `order_response = client.open_market_order(line.instrument_id,
   amount=line.amount_account_ccy, side="buy", leverage=1, settlement_type="real")`;
   `order_id = order_response.get("order_id") or order_response.get("reference_id")`;
   `fill = client.wait_for_fill(order_id, kind="open")`.
6. `execute`, invio SELL:
   `order_response = client.close_position(line.position_id, line.instrument_id,
   units=line.units)`; `order_id = order_response.get("order_id")`;
   `fill = client.wait_for_fill(order_id, kind="close", position_id=line.position_id)`.
7. Stato: `status = str(fill.get("status") or "").lower()`; `status != "filled"` →
   failure `not_filled`. Prezzo: `fill.get("price")` se non None, altrimenti
   `fill.get("avg_price")`, altrimenti None (mai inventato).
   `broker_order_id = str(order_id or "")`.
8. Riscrivi `FakeClient` nei test con l'interfaccia REALE del punto sopra (stessi
   nomi/kwargs di `EToroClient`, status minuscoli `"filled"`/`"rejected"`).

## Test (rossi prima, verdi dopo)
- `test_build_plan_rejects_none_fx_rate`: `pytest.raises(ValueError)` con
  `fx_rate_eur_per_ccy=None`.
- `test_build_plan_blocks_buy_without_instrument_id`: ordine buy con
  `instrument_id=None` → blocker con `"instrument_id"`.
- `test_execute_cash_recheck_includes_estimated_fees`: fee model con
  `fee(amount) -> 10.0` fisso e `minimum_economic_order = 10.0`; il piano si
  costruisce con `account={"cash_available": 1000.0, "equity": 1000.0}` (nessun
  blocker al build: 108.70 + 10 < 1000), poi `execute` con un client il cui
  `account()` ritorna `cash_available = 112.0` (108.70 < 112 < 118.70) → refusal
  `cash_dropped` (rosso prima del fix: senza fee 108.70 < 112 passerebbe).
- `test_execute_drives_the_real_etoro_client_end_to_end`: `EToroClient` vero con
  `httpx.MockTransport` passato a `execute` su un piano buy da 1 riga costruito con
  `build_plan` (il fee model fake espone `fee()` e `minimum_economic_order=10.0`).
  Handler: GET pnl demo → 200 con `{"clientPortfolio": {"credit": 5000.0, ...}}`
  (≥ buy+fee, così il re-check passa); POST ordine demo → 200 con
  `{"orderId": 999, "referenceId": "ref-1", "token": "t"}`; GET orders:lookup →
  200 con `{"orderId": 999, "status": {"id": 3}}` (filled). `execute` NON chiama
  `eligibility` (il `min_position_exposure` è già nel suggested order). Assert:
  `sent == ["AAPL"]`, ledger con `broker_order_id == "999"`. Questo test da solo
  copre #17/#19/#20.
- Aggiornati: tutti i test `execute` esistenti passano al nuovo FakeClient
  (status `"filled"`/`"rejected"` minuscoli, `account()` al posto di
  `get_cash_available`, kwargs reali in `opened`/`closed`).

## Verifica
`uv run pytest tests/test_execution.py -q`
