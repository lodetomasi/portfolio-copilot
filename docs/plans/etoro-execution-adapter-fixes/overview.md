# Piano: fix difetti adapter eToro (Phase A + interfaccia execution)

Design doc: `docs/plans/2026-08-29-etoro-execution-adapter-fixes-design.md`
Scope: finding 1, 3-15, 17, 19, 20. Finding #2 REFUTATO (probe live 2026-08-29:
`x-user-key` → 200, `user-key` → 401): nessuna modifica header. Phase 0 e Phase B
(governance + wiring server/skill) NON sono in questo piano.

DEVIAZIONE DICHIARATA dall'ordine del design (Phase 0 prima di Phase A): qui si
correggono solo difetti di codice non ancora raggiungibile (zero riferimenti in
`server.py`/skill), quindi nessun tool esposto contraddice manifest o SKILL.md;
Phase 0 resta obbligatoria PRIMA di Phase B.

## Vincoli Globali

- Test offline e deterministici: `httpx.MockTransport`, fake iniettati, `tmp_path`; mai `data/private`.
- TDD: per ogni finding un regression test che fallisce prima del fix e passa dopo.
- Mai inventare dati mancanti: degradare a `None` + dichiararlo; per ordini/denaro preferire rifiuto tipizzato.
- Nessun ordine reale: `mode="real"` resta dietro doppio gate `allow_real=True` + `ETORO_ALLOW_REAL=1`.
- `uv run pytest -q` e `uv run ruff check .` verdi a fine piano (line-length 100, select E,F,I,UP,B).
- Nessun commit senza richiesta esplicita dell'utente.

## Task

| # | File | Stato |
|---|------|-------|
| 01 | task-01-etoro-429-idempotency.md | [DONE] |
| 02 | task-02-venues-floor.md | [DONE] |
| 03 | task-03-sources-position-schema.md | [DONE] |
| 04 | task-04-risk-profile-drawdowns-verdict.md | [DONE] |
| 05 | task-05-ledger-lock-plan-token.md | [DONE] |
| 06 | task-06-execution-client-interface.md | [DONE] |
| 07 | task-07-execution-idempotency-riskprofile.md | [DONE] |
| 08 | task-08-verification.md | [DONE] |
| 09 | task-09-phase0-manifest-skills.md | [DONE] |
| 10 | task-10-phase-b-server-tools.md | [DONE] |
| 11 | task-11-phase-b-skills-flow.md | [DONE] |
| 12 | task-12-final-verification.md | [DONE] |

Estensione 2026-08-29 (sera): Phase 0 punti 2-4 + Phase B (#16, #18) autorizzati
dall'utente ("ok procedi"); CLAUDE.md già aggiornato da sessione parallela — ogni
task rilegge i file da disco prima di modificarli.
