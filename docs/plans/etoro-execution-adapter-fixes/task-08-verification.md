# Task 08 — verifica finale

## Comandi (tutti devono essere verdi)
1. `uv run pytest -q` — l'unico fallimento tollerato è
   `test_get_portfolio_config_returns_the_repo_example_by_default`, ambientale
   (esiste un `config/portfolio.yaml` locale gitignored; documentato in CLAUDE.md).
2. `uv run ruff check .` — zero violazioni.
3. Conteggio regression test nuovi ≥ 14 (uno o più per finding: 1, 3, 4, 5, 6, 7,
   8, 9, 10, 11, 12, 13, 14, 15, 17/19/20).

## Non incluso (resta nel backlog del design doc)
- Phase 0 (riscrittura regole CLAUDE.md / manifest / SKILL.md) e Phase B
  (tool MCP `etoro_*`, `prepare_execution`, `execute_plan`, aggiornamento skill).
- Smoke test live demo (il design lo prevede al gate di Phase B).
- Nessun commit: l'utente non lo ha richiesto.
