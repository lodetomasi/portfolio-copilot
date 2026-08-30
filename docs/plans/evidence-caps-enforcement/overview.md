# Enforcement cap evidence-based — Piano Implementativo

> **Per Claude:** REQUIRED SUB-SKILL: Usa `siae-subagent-development`
> per implementare questo piano task per task.

**Goal:** imporre in codice le tre regole oggi solo dichiarate nel piano d'investimento:
cap per-nome sui titoli high-risk, glide gate temporale, quality gate deterministico.
**Architettura:** i primi due check entrano nel choke point `execution.py::build_plan`
(stesso pattern blocker/checks dei cap esistenti); il terzo è una funzione pura in
`picker.py` che consuma l'output di `analyze_stock`. Nessun altro modulo cambia.
**Stack:** Python 3, Pydantic, pytest (offline, fixture sintetiche).
**SP:** Umano 3 / Augmented 1 (split 1.0+1.0+1.0 / 0.33+0.33+0.34).
**Design doc:** `docs/plans/2026-08-29-evidence-caps-enforcement-design.md` (Rev 3,
APPROVED_WITH_WARNINGS).

## Vincoli Globali

- TDD obbligatorio: test rosso PRIMA dell'implementazione, poi verde, poi commit.
- `uv run ruff check .` deve restare pulito (select E, F, I, UP, B; line-length 100).
- Tutti i test esistenti restano verdi (1533 collezionati in questo checkout: 1362
  committati + i file di test nuovi non ancora committati). NOTA fallimento noto e
  pre-esistente: `test_get_portfolio_config_returns_the_repo_example_by_default`
  fallisce in questo checkout per il `config/portfolio.yaml` personale git-ignored
  (documentato in CLAUDE.md, "Stato verificato") — non è una regressione di questo
  piano. Nessun call site esistente cambia comportamento con i nuovi parametri
  assenti (default neutri).
- Nessun nuovo `except Exception`; input malformati → `ValueError` esplicito.
- Funzioni pure con docstring sulle funzioni pubbliche.
- Regola booleana `is_high_risk` (contratto del chiamante, documentata nel docstring di
  `build_plan`): `is_high_risk = (lane == "speculative") or ("Asymmetric" in category)
  or ("High Risk" in category) or (size_bucket in {"nano", "micro"})`.
- `quality_gate` legge SOLO la forma reale di `analyze_stock`: `score`/`confidence`
  piatti alla radice; metriche in `evidence["metrics"]`; `evidence["counts"]` escluso.
- `screen_stocks`, `rank_candidates`, `execute` NON vengono modificati.

---

## Indice Task

| # | Task | File | Stato |
|---|------|------|-------|
| 1 | Cap high-risk per nome in build_plan | `task-01-high-risk-cap.md` | [DONE] |
| 2 | Glide gate temporale in build_plan | `task-02-glide-gate.md` | [DONE] |
| 3 | quality_gate puro in picker | `task-03-quality-gate.md` | [DONE] |
| 4 | Documentazione regola OR e flusso quality nella skill | `task-04-skill-docs.md` | [DONE] |

## Dipendenze

- Task 2 dipende da Task 1 (stesso file `execution.py`, il glide riusa `is_high_risk`
  sugli ordini; eseguire in ordine evita conflitti di merge).
- Task 3 è indipendente da 1 e 2 (file diversi).
- Task 4 dipende da 1 e 3 (documenta nella skill ciò che quei task implementano).
