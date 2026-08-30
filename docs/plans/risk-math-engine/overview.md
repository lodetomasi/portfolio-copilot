# Motore risk-math — Piano Implementativo

> **Per Claude:** REQUIRED SUB-SKILL: Usa `siae-subagent-development`
> per implementare questo piano task per task.

**Goal:** matematica finanziaria avanzata nel copilot: stationary-bootstrap Monte Carlo
(distribuzione max drawdown, shortfall vs contribuito), CVaR discreto di
Rockafellar-Uryasev, sizing half-Kelly con cap dominante, esposti come tool MCP.
**Architettura:** nuovo modulo puro `analytics/risk_math.py` (zero I/O, confine identico
a `analytics/metrics.py`); wiring in `server.py` con il `provider` module-level esistente
(riga 65) e il pattern bucket-mancanti/renormalizzazione di `backtest_plan` (righe
559-575). Nessun altro modulo cambia.
**Stack:** numpy (già dipendenza), pandas, pytest offline.
**SP:** Umano 5 / Augmented 2 (split nel design doc).
**Design doc:** `docs/plans/2026-08-29-risk-math-engine-design.md` (Rev 3, APPROVED).

## Vincoli Globali

- TDD: test rosso PRIMA dell'implementazione; `uv run ruff check .` pulito
  (E, F, I, UP, B; line-length 100); tutti i test esistenti verdi.
- `analytics/risk_math.py` è matematica pura: nessun import di provider, nessun I/O.
- Generatore random SOLO `np.random.Generator(np.random.PCG64(seed))`, `seed` esplicito.
- Convenzione severità drawdown: valori firmati negativi; `p95_worst =
  np.percentile(dd, 5)`, `p99_worst = np.percentile(dd, 1)`.
- `mean_block` default = `clamp(round(n_obs ** (1/3)), 2, 12)` (Patton-Politis-White
  2009); stationary bootstrap con wrap circolare (Politis & Romano 1994).
- CVaR = estimatore discreto `λ·VaR + (1−λ)·CVaR⁺` (Rockafellar & Uryasev 2000),
  riportato in termini di RENDIMENTO (numeri negativi), alpha default 0.95.
- Kelly frazionario default 0.5 (MacLean-Thorp-Ziemba 2010); il cap del venue vince
  sempre su Kelly; edge negativo → 0.0, mai size negativa.
- Storia congiunta < 24 osservazioni mensili → `ValueError`; 24-59 → warning testuale
  nelle disclosures. Nessun nuovo `except Exception`.
- Disclosures del tool sempre complete: metodo f-string con il `mean_block` reale
  ("stationary bootstrap, lunghezza blocco media {mean_block} mesi, wrap circolare,
  ribilanciamento mensile"), n_obs, `var_monthly_95`, `cvar_tail_obs`,
  "not a forecast", assunzione niente commissioni/tasse.
- `simulate_plan_risk` default `n_paths=10000`, `seed=42`; stesso seed → stessi numeri.

---

## Indice Task

| # | Task | File | Stato |
|---|------|------|-------|
| 1 | Modulo risk_math: returns + stationary bootstrap | `task-01-bootstrap.md` | [DONE] |
| 2 | Path di valore, drawdown_stats, shortfall_stats | `task-02-paths-stats.md` | [DONE] |
| 3 | cvar (λ-estimator) + kelly_fraction | `task-03-cvar-kelly.md` | [DONE] |
| 4 | Tool MCP simulate_plan_risk + kelly_size | `task-04-mcp-tools.md` | [DONE] |
| 5 | Integrazione skill (solo testo) | `task-05-skill-integration.md` | [DONE] |

NOTA fallimento noto e pre-esistente in questo checkout:
`test_get_portfolio_config_returns_the_repo_example_by_default` fallisce per il
`config/portfolio.yaml` personale git-ignored (documentato in CLAUDE.md, "Stato
verificato") — non è una regressione di questo piano.

## Dipendenze

- Task 2 dipende da Task 1 (usa i path del bootstrap, la fixture e appende a
  `tests/test_risk_math.py` creato dal Task 1).
- Task 3 dipende da Task 1 (appende allo stesso modulo e allo stesso file di test);
  eseguire dopo il 2 per evitare conflitti di append.
- Task 4 dipende da 1, 2 e 3 (importa tutte le funzioni).
- Task 5 dipende da 4 (documenta nelle skill i tool creati).
