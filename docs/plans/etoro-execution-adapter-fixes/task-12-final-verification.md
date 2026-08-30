# Task 12 — verifica finale Phase 0+B

1. Rileggere `git status` PRIMA della verifica: se una sessione parallela ha toccato
   gli stessi file, rileggerli e ri-verificare che le modifiche convivano.
2. `uv run pytest -q` — unico fallimento tollerato: quello ambientale documentato
   (`test_get_portfolio_config_returns_the_repo_example_by_default`).
3. `uv run ruff check .` — zero violazioni.
4. `claude plugin validate --strict .` e `claude plugin validate --strict skills`.
5. Sessione MCP stdio: `tools/list` deve includere i 6 tool nuovi (`etoro_account`,
   `etoro_positions`, `etoro_orders`, `etoro_search_instrument`, `prepare_execution`,
   `execute_plan`) — driver Python con subprocess su
   `uv run python -m portfolio_copilot.server` (initialize → tools/list).
6. Smoke test live DEMO (facoltativo, dal design: read-only prima; se l'ambiente non
   risponde, riportare parziale, MAI passare a REAL): `etoro_account` e
   `etoro_positions` con le credenziali reali demo. Nessun BUY live in questo task —
   il design lo prevede solo su richiesta esplicita al gate finale.
7. Nessun commit senza richiesta esplicita dell'utente.
