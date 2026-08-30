# Task 09 — Phase 0: manifest, test_plugin, 4 SKILL.md, docs (design Phase 0, punti 2-4)

Nota: il punto 1 di Phase 0 (CLAUDE.md) è GIÀ FATTO da una sessione parallela
(paragrafo "Eccezione eToro" dopo le regole non negoziabili). Non toccare CLAUDE.md.
Prima di modificare OGNI file di questo task, rileggerlo da disco (lavoro parallelo
in corso).

## File
- `.claude-plugin/plugin.json` (solo `description`)
- `tests/test_plugin.py`
- `skills/start/SKILL.md`, `skills/deploy-cash/SKILL.md`, `skills/rebalance/SKILL.md`,
  `skills/position-review/SKILL.md`
- `README.md`, `docs/ARCHITECTURE.md` (sezioni perimetro, senza test che le vincolino)

## Modifiche
1. `plugin.json.description`: sostituisci "No broker login, no broker access, no order
   execution: suggested orders only (MANUAL_ONLY)." con "No broker login, no broker
   access, no order execution on your export account: suggested orders only
   (MANUAL_ONLY). On your own eToro account (only if you configure it), orders are sent
   only after you confirm that exact plan, demo by default."
   Stessa modifica alla `description` in `.claude-plugin/marketplace.json` se contiene
   "no order execution" non scopato (nessun test la vincola, ma il manifest pubblico
   non deve contraddire il comportamento).
2. `tests/test_plugin.py::test_plugin_and_marketplace_manifests_agree`: l'assert
   `"no order execution" in plugin["description"].lower()` diventa
   `"no order execution on your export account" in plugin["description"].lower()`.
3. `tests/test_plugin.py::test_every_skill_states_no_broker_access_and_stays_short`:
   dopo l'assert su `"manual"`, aggiungi
   `if path.parent.name in {"start", "deploy-cash", "rebalance", "position-review"}:`
   → `assert "etoro" in body, path` (le altre 3 skill non toccano denaro eseguibile).
   Gli assert esistenti (`"no broker access"`, `"manual"`, `"≤ 6 lines"`, `< 120`
   righe) restano invariati.
4. In OGNUNA delle 4 skill, il primo bullet dei Guardrails
   "**No broker access.** Your holdings come only from the local XLSX/CSV export..."
   diventa: "**No broker access on your export account.** Its holdings come only from
   the local XLSX/CSV export you give me: I never log into it, never ask for
   credentials/OTP/PIN, never send orders there — manual only. On your own eToro
   account (only if configured via `data/private/etoro.env`), I read real positions
   and can send an order ONLY after you confirm the exact plan token I show you; demo
   by default, real needs your explicit double confirmation. Market data comes from
   free public sources (Yahoo, SEC EDGAR, ECB, Finviz) with `source` / `as_of` /
   `confidence`."
5. `skills/start/SKILL.md`, dopo "## Ask exactly one question": aggiungi la riga di
   rilevamento account: "State the account first: a file path in the message means the
   export account; otherwise, if eToro credentials are configured, say `Account: eToro
   DEMO (virtual)` (or REAL) and use it."
6. `README.md` / `docs/ARCHITECTURE.md`: nelle sezioni di perimetro ("Cosa NON fa" o
   equivalenti) scopare il divieto ordini all'export account e citare l'eccezione
   eToro (una frase ciascuno, stesso contenuto del punto 1).

## Test
`uv run pytest tests/test_plugin.py -q` — rosso al punto 3 finché le 4 skill non
citano eToro, poi verde; `claude plugin validate --strict .` deve restare PASS.
