# Task 11 — Phase B: flusso eToro nelle skill money-relevant (design finding #18)

Prima di modificare, rileggere OGNI SKILL.md da disco (lavoro parallelo). Budget:
< 120 righe per file, il contratto "≤ 6 lines" resta letterale nel testo.

## File
- `skills/start/SKILL.md` (banner/rilevamento: già nel task 09, punto 5 — qui solo verifica)
- `skills/deploy-cash/SKILL.md`, `skills/rebalance/SKILL.md`,
  `skills/position-review/SKILL.md`

## Modifiche (per deploy-cash, rebalance, position-review)
1. In cima alla sezione "## Do", aggiungi il passo 0 di disambiguazione:
   "0. Account: a file path given → export account (manual orders only, nothing else
   changes). No path and eToro configured → eToro; start every answer with
   `etoro_account`'s banner. Both available and the request names neither → ask
   \"Which account? (eToro | export file)\" — never guess."
2. In coda alla sezione "## Do", aggiungi il passo di esecuzione (solo conto eToro):
   "Last (eToro account only): `prepare_execution(orders, mode)` → show each line
   (symbol, EUR, USD) plus the `token` and every blocker, then ask: \"Confirm sending
   these N orders to eToro DEMO? Reply with the token.\" Only when the user replies
   with that exact token call `execute_plan(plan, token)` and report sent/failed with
   broker order ids. Real mode additionally needs `allow_real=True` and
   `ETORO_ALLOW_REAL=1` (never set them yourself). For the export account: no
   execution step, manual to-do only."
3. Non toccare i passi esistenti né il blocco "## Answer (≤ 6 lines)" oltre a: nel
   template Answer, la prima riga diventa l'account banner quando il conto è eToro
   (esempio già presente nel banner di `sources.account_banner`).

## Test
Coperti da `tests/test_plugin.py` (task 09: "etoro" nel body, < 120 righe, contratti
letterali invariati). `claude plugin validate --strict skills` deve restare PASS.
