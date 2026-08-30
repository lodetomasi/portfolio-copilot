# Design — Enforcement dei cap evidence-based (high-risk, glide, quality gate)

Data: 2026-08-29 · Complessità: Media · Rev 3 (spec-review: APPROVED_WITH_WARNINGS, 3 iterazioni, 0 BLOCK residui)
SP totali: Umano 3 / Augmented 1 — split: cap high-risk + test 1.0/0.33; glide gate +
test 1.0/0.33; quality_gate + test 1.0/0.34 (tre modifiche indipendenti, stessa taglia,
pattern esistenti da rispecchiare).

## Prerequisito di conformità (risolve BLOCK-1 della spec review)

`execution.py`/`brokers/etoro.py` inviano ordini reali su eToro e nominano il broker: è
l'**Eccezione eToro** decisa dall'utente il 2026-08-29 e ora documentata in CLAUDE.md
(sezione "Non negoziabile", dopo la regola 10). Questo design costruisce enforcement
DENTRO quella pipeline sancita — non estende il perimetro della deroga.

## Contesto

Le regole decise il 2026-08-29 ("voglio spingere", evidenza da Bali-Cakici-Whitelaw 2011,
Kumar 2009, Bessembinder 2018, AFP QMJ 2019) vivono solo come parametri in
`data/private/investment_plan.json`. Nessun motore le impone:

- `max_high_risk_stock_weight` (0.02 in `config/portfolio.yaml::risk_limits`) è letto solo
  da `picker.py::_risk_cap_pct` come **tag informativo** (`risk_cap_pct`), mai come blocker
  in `execution.py::build_plan` (che impone solo single/sector/speculative).
- Il glide del satellite (`no_new_high_risk_after: 2030-09-01`) non esiste in alcun codice.
- Il filtro "quality" dello slot core (score ≥ 70, confidence ≥ 0.6, nessun CONFLICT non
  risolto) sarebbe oggi un giudizio LLM — vietato da CLAUDE.md regola 8.

## Approcci valutati

1. **Enforcement in `build_plan` + funzione pura `quality_gate` nel picker (SCELTO).**
   Pro: `build_plan` è il choke point prima dell'invio (ogni ordine passa di lì), i nuovi
   check rispecchiano quelli esistenti (stesso pattern blocker/checks), diff minimo,
   offline-testabile. Contro: il chiamante deve marcare `is_high_risk` (contratto
   documentato nel docstring, come già avviene per `is_stock`).
2. Enforcement nella sizing del picker/auction. Contro: ordini costruiti a mano
   bypasserebbero il cap; nessun choke point unico. Scartato.
3. Modulo centrale `risk_gates.py` che rifattorizza tutti i cap. Contro: refactor di
   check funzionanti e testati, diff ampio, astrazione prematura (AHA). Scartato.

## Design

### 1. Cap high-risk per nome in `execution.py::build_plan`
- `caps` accetta la chiave opzionale `max_high_risk_stock_weight`.
- Un ordine può portare `is_high_risk: bool` (default `False`). Regola booleana esatta a
  carico del chiamante (OR semplice, nessuna precedenza — basta un segnale):
  `is_high_risk = (lane == "speculative") or ("Asymmetric" in category) or
  ("High Risk" in category) or (size_bucket in {"nano", "micro"})`
  con `lane`/`category`/`size_bucket` presi dall'output di `picker.annotate`. La regola
  vive nel docstring di `build_plan` come contratto documentato (stesso stile di
  `is_stock`).
- Per ogni buy line con `is_high_risk=True`: peso post-plan del simbolo
  `(esposizione esistente + net plan) / equity` confrontato con il cap → `checks` sempre,
  `blockers` se sopra. Stesso pattern del check `max_single_stock_weight` esistente.

### 2. Glide gate in `execution.py::build_plan`
- Nuovo parametro opzionale `glide: dict | None` con chiave `no_new_high_risk_after`
  (data ISO). La data "oggi" è presa da `as_of` (già parametro di `build_plan`, test
  deterministici) e degrada a `date.today()` solo se `as_of` è vuoto.
- Se `as_of >= no_new_high_risk_after` e la line è buy + `is_high_risk` → blocker
  `"<symbol>: glide gate: new high-risk buys are blocked since <date>"`.
- `glide=None` (default) = comportamento identico a oggi, nessun impatto sui call site
  esistenti.

### 3. `picker.py::quality_gate(analysis, min_score=70.0, min_confidence=0.6) -> dict`
- **Input: l'output di `analyze_stock`** (risolve BLOCK-2 della spec review): è l'UNICO
  flusso che produce il report `evidence` (via `apply_evidence_report`, con override SEC
  tier A); `screen_stocks`/`rank_candidates` non lo popolano mai e NON vengono modificati.
- Flusso dello slot `quality_stocks` (documentato nel docstring e nella skill):
  `rank_candidates` → primi 5 candidati con "Quality" nella categoria →
  `analyze_stock(ticker)` per ciascuno (5 fetch singoli, dentro i rate limit) →
  `quality_gate(analysis)` → red team sul superstite. Nessun nuovo tool MCP.
- Lettura campi (verificata su `server.py:343-346` e `models.py:130-137` — `StockScore.
  model_dump()` appiattisce alla radice): `score = analysis["score"]` (float 0-100),
  `confidence = analysis["confidence"]` (float 0-1); metriche evidence da
  `analysis["evidence"]["metrics"]` (dict nome-metrica → `{status, use_in_score, ...}`,
  forma di `analytics/evidence.py::evidence_report`, righe 171-184);
  `analysis["evidence"]["counts"]` è il riepilogo aggregato e resta ESCLUSO dal
  criterio (c) — iterare solo su `["metrics"]`.
- Funzione pura: `{"passed": bool, "reasons": list[str]}`; `reasons` elenca OGNI criterio
  fallito (mai solo il primo).
- Criteri (dal piano, tutti dichiarati):
  a. `score >= min_score`;
  b. `confidence >= min_confidence`;
  c. nessuna metrica evidence con `status == "CONFLICT"` e `use_in_score == False`
     (CONFLICT non risolto da fonte tier A);
  d. evidence assente/`None`/vuota → `passed=False` con reason esplicita ("evidence
     report missing") — mai inventare che sia pulito (CLAUDE.md regola 4).
- NON rimuove nulla dal ranking: si applica solo quando il chiamante riempie lo slot
  `quality_stocks` del conto core. Il principio no-exclusion del ranking resta intatto.

## Flusso dati
picker (tags: lane/size_bucket) → skill costruisce `suggested_orders` con `is_high_risk`
→ `build_plan(caps + glide)` → blockers → `execute` rifiuta se blockers presenti (già
esistente, nessuna modifica a `execute`). Slot quality: `rank_candidates` →
`analyze_stock` per finalista → `quality_gate` → red team → ordine manuale sul core.

## Rischi e mitigazioni
- **Provenienza di `evidence`** (era il rischio non dichiarato): risolto vincolando
  `quality_gate` all'output di `analyze_stock`; il test usa una fixture con la forma
  REALE di quell'output (campi piatti `score`/`confidence` alla radice + `evidence =
  {"metrics": {...}, "counts": {...}}`, come da `server.py:343-346` e
  `evidence.py::evidence_report`), così una divergenza futura rompe il test, non
  l'utente.
- **Confronto date del glide**: `as_of` può essere vuoto o ISO datetime completo →
  parsing con `date.fromisoformat(as_of[:10])`, vuoto → `date.today()`, malformato →
  `ValueError` (testato).
- **Chiamante che non marca `is_high_risk`**: il default `False` non può bloccare a
  sproposito; la regola OR è nel docstring e nella skill — stesso rischio già accettato
  per `is_stock` (pattern esistente).
- **Regressioni**: parametri nuovi tutti opzionali con default neutro; criterio di
  accettazione 5 dedicato.

## Errori
Nessun nuovo `except Exception`. Input malformati (`glide` senza chiave, data non-ISO)
→ `ValueError` esplicito, mai silenzio.

## Testing (offline, deterministico)
- `tests/test_execution.py`: high-risk sopra/sotto cap; high-risk senza cap in `caps`
  (nessun blocker, check assente); glide prima/dopo la data (via `as_of`); glide su buy
  non-high-risk (mai bloccato); `glide=None` invariato; data glide malformata → ValueError.
- `tests/test_picker.py` (o file esistente dei test picker): quality_gate pass; fail per
  score; fail per confidence; fail per CONFLICT non risolto; CONFLICT risolto tier A passa;
  evidence mancante fail; reasons multiple cumulate.

## Criteri di accettazione
1. Un buy `is_high_risk` che porta il peso post-plan oltre 0.02 di equity produce un
   blocker e `execute` lo rifiuta (test).
2. Dopo `no_new_high_risk_after`, ogni nuovo buy high-risk è bloccato (test).
3. `quality_gate` è deterministico e motiva ogni bocciatura (test).
4. `uv run pytest` tutto verde (1362 esistenti + nuovi), `uv run ruff check .` pulito.
5. Nessun call site esistente cambia comportamento con i nuovi parametri assenti.
