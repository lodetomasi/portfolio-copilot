# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Missione

Plugin Claude Code + MCP locale (stdio), **broker-agnostico**, per chi ha soldi da investire e non sa da dove partire: piano con calendario, portfolio review, deploy cash, rebalancing, stock picking. Principio d'uso: **rookie in → elaborazione da esperto → rookie out** (risposte ≤ 6 righe, dettagli solo su richiesta). Il software produce **analisi e ordini suggeriti, mai ordini reali**.

## Non negoziabile

1. MAI collegarsi a banche o broker: niente login, scraping di aree private, cookie. Le holding entrano SOLO dall'export XLSX/CSV locale fornito dall'utente; i dati di mercato SOLO da fonti pubbliche senza account/API key.
2. MAI chiedere, leggere o memorizzare password, OTP, PIN o credenziali broker.
3. MAI inviare ordini. Ogni piano ordini è `MANUAL_ONLY`.
4. MAI inventare dati finanziari mancanti: usa `None`, degrada lo score, dichiaralo.
5. Ogni dato esterno porta `Provenance` (`source`, `as_of`, `confidence`, `missing_fields`).
6. `HOLD`, `WAIT`, `NO_BUY` sono risultati validi. Niente turnover inutile, niente micro-ordini antieconomici.
7. I test della logica finanziaria sono offline e deterministici (fixture sintetiche, mai export reali).
8. Nessun calcolo che può essere deterministico in Python va delegato all'LLM (i prompt MCP orchestrano tool, non fanno aritmetica).
9. Nessuna API a pagamento senza richiesta esplicita.
10. Non committare dati personali: `config/portfolio.yaml`, `data/private/` (piano, ledger), `*.xlsx`, `export*.csv` sono in `.gitignore`. Nessun nome di broker nel codice, nemmeno negli adapter.

**Eccezione eToro (decisione esplicita dell'utente, 2026-08-29 — deroga puntuale e SOLO a questo perimetro delle regole 1, 2, 3 e 10):** il copilot può leggere ed eseguire ordini sul conto eToro personale dell'utente via eToro Public API v2 (`src/portfolio_copilot/brokers/etoro.py`). Credenziali SOLO in `data/private/etoro.env` (git-ignored, chmod 600; mai chieste in chat, mai loggate, mai committate, `repr` sempre redatto). Pipeline unica e obbligatoria: motori decisionali → `portfolio/execution.py::build_plan` (token deterministico sul piano esatto, blockers) → `execute` (rifiuta su token mismatch/blockers). Demo è il default; il conto reale richiede il doppio gate `allow_real=True` + `ETORO_ALLOW_REAL=1` e conferma dell'utente. Sul DEMO è autorizzato l'autopilot full-auto in prova (decisione utente 2026-08-29, "mi fido di te... ti voglio far provare"); sul REALE l'autopilot prepara il piano e si ferma alla conferma. Il nome "eToro" può comparire solo in `brokers/`, `portfolio/execution.py`, `portfolio/venues.py`, test relativi e dati privati; il broker dell'export resta senza nome ovunque (la scansione del punto "Stato verificato" riguarda lui). Tutto il resto delle regole 1-10 è invariato: l'export XLSX/CSV resta l'unica fonte per l'altro conto, mai scraping o login web, mai altre integrazioni broker.

## Comandi

```bash
uv sync --extra dev                      # install (dev deps: pytest, pytest-asyncio, ruff)
uv run pytest                            # tutti i test (offline, deterministici)
uv run pytest tests/test_rebalance.py    # un file
uv run pytest tests/test_rebalance.py::test_fee_minimum_economic_order   # un test
uv run pytest -m "not network"          # marker `network` (nessun test lo usa ancora; non escluso di default)
uv run ruff check .                      # lint (select: E, F, I, UP, B; line-length 100) — deve restare pulito
uv run ruff check . --fix                # autofix
uv run mcp dev src/portfolio_copilot/server.py   # server + MCP Inspector
uv run python -m portfolio_copilot.server        # server stdio (come in .mcp.json)
uv run portfolio-copilot parse|risk|stock <arg>  # CLI typer di debug (cli.py)
claude plugin validate . && claude plugin validate skills && claude plugin validate agents
claude --plugin-dir .                    # prova il plugin in questa repo; /reload-plugins dopo modifiche
```

`make install|test|lint|dev` sono alias dei comandi sopra.
`pythonpath = ["src"]` è configurato in pytest: i test importano `portfolio_copilot` senza install editable.

## Stato verificato (2026-08-29)

- MCP Python SDK **2.1.1** (`from mcp.server import MCPServer`, decoratori `@mcp.tool()` / `@mcp.prompt()`).
- `uv run pytest`: **1362 test verdi** (verificato 2026-08-29), tutti offline (fixture sintetiche, provider mockati, backtest su prezzi seeded); coverage di riga ~94% (`scripts/test_report.py` → `docs/TEST_REPORT.md`, una riga per test — rigenerare dopo modifiche rilevanti). Backtest reali e benchmark: `scripts/backtest_report.py` → `docs/BACKTEST.md`; backtest proxy del picker: `scripts/picker_backtest_report.py` → `docs/PICKER_BACKTEST.md` (20/20 ticker, 20 rebalance, mean_excess 1.33%, hit_rate 50.00%). Nota: un `config/portfolio.yaml` locale (personale, gitignored) fa fallire `test_get_portfolio_config_returns_the_repo_example_by_default` nel checkout di chi lo ha creato — non è un bug, è l'ambiente locale che smentisce l'assunzione "nessun config utente"; il conteggio sopra è con quel file spostato temporaneamente.
- `uv run ruff check .`: **pulito**. Tenerlo così.
- `claude plugin validate --strict .` / `skills` / `agents`: passano tutti e tre. SEC EDGAR risponde 200 con lo User-Agent di default (verificato live 2026-08-29); Stooq è bloccato da un anti-bot e non è un fallback funzionante; Eurostat `une_rt_m` non ha l'aggregato EA20 (usare `EU27_2020`). Attenzione: in `SKILL.md` gli `argument-hint` che iniziano con `[` vanno tra virgolette o il frontmatter YAML fallisce silenziosamente.
- Sessione MCP stdio verificata end-to-end: `initialize` risponde, `tools/list` espone **43 tool** (incl. `parse_portfolio_export`, `get_portfolio_config`, `map_holdings_to_targets`, `save_portfolio_snapshot`, `rank_candidates`, `backtest_picker`, `resolve_isins`, `simulate_plan_risk`, `kelly_size`, `penny_flags`, i 4 `etoro_*` read-only e `prepare_execution`/`execute_plan`), `prompts/list` espone i **4 prompt** (`portfolio_review`, `stock_picker`, `rebalance`, `deploy_cash`); `tools/call map_holdings_to_targets` sulla fixture `tests/fixtures/broker_export_page_layout.csv` e `tools/call get_portfolio_config` rispondono correttamente.
- La scansione case-insensitive del nome del broker in tutto il repo (esclusi `.venv`, `.git`, `.pytest_cache`, `.ruff_cache`) non produce corrispondenze. `data/private` contiene solo `.gitkeep`.
- eToro live (2026-08-29/30): letture account/positions/orders verificate su demo E reale (200); ordini di CLOSE reali inviati e accettati (statusID 11, pending a mercati chiusi — fill atteso 2026-08-31); smoke test BUY+close su demo = **partial**: mercati chiusi il sabato (`tradable=false` su ogni strumento), da completare alla prima sessione di mercato aperto. `penny_flags` live-verificato su GLBS/SHIP/EVER (FINRA + SEC reali).
- Se l'SDK installato differisce dal codice, adegua il codice alla versione installata e aggiorna README; niente downgrade alla cieca.

## Architettura: flussi, non solo cartelle

Tutto sta in `src/portfolio_copilot/`. `server.py` è solo esposizione MCP e orchestrazione leggera; la logica vive nei moduli sottostanti e deve restare importabile/testabile senza MCP.

**Flusso portafoglio**
`parsers/broker_export.py::parse_portfolio_export` → `models.Portfolio` (lista di `Holding`) → `portfolio/risk.py::summarize_portfolio_risk` → dict con pesi, `concentration` (top1/3/5, HHI da `analytics/metrics.py`) e blocco leva. Il parser trova da solo la riga header (gli export "pagina" hanno righe di riepilogo prima), scarta la riga `Totale`, estrae il ticker dalla prima riga della cella nome.

**Flusso singolo titolo**
`providers/yfinance_provider.py::YFinanceProvider.get_stock_snapshot` (tier B, fallback `providers/yahooquery_provider.py` via `providers/fallback.py::FallbackMarketData` su rate limit/outage) → `analytics/merge.py::apply_official_overrides` con `providers/sec_edgar.py` (tier A: revenue growth e FCF certificati sovrascrivono Yahoo, registrato in `provenance.overrides`) → `analytics/merge.py::apply_evidence_report` (`analytics/evidence.py`: multi-fonte VERIFIED/CONFLICT/SINGLE_SOURCE/MISSING; un CONFLICT non risolto da una fonte tier A è escluso dallo score) → `scoring/engine.py::score_snapshot` → `models.StockScore`. Discovery senza ticker: `providers/finviz.py` (tier C, preset validati offline; i numeri Finviz non entrano mai nello score).
`screen_stocks` è un loop su questo flusso che cattura le eccezioni per ticker e ordina per score.

**Flusso cash / rebalance / ordini**
Un solo motore: `portfolio/rebalance.py::allocate_cash_to_targets(current_values, targets, cash_eur, FeeModel, rebalance_band_abs)`.
I tool `allocate_cash`, `rebalance_portfolio`, `generate_order_plan` in `server.py` sono wrapper dello stesso motore, usato anche da `portfolio/plan.py` (ordini iniziali) e `portfolio/backtest.py` (replay mensile). `rebalance_portfolio` accetta anche `allow_sells` (default `False`): con `True` aggiunge `sell_proposals` da `portfolio/replacement.py::sell_summary` per i drift oltre banda, mai attivo di default. Modifiche alla logica di allocazione vanno fatte lì, una volta.
Il tool `capital_auction` (`portfolio/auction.py`) è un motore separato: ordina bucket sottopeso, titoli candidati (score via `analyze_stock`, fit da `portfolio/exposure.py`, sconto se la tesi salvata è WEAKENING/BROKEN) e il cash stesso per utilità marginale, poi alloca greedy — usato dalla skill `deploy-cash` al posto della mappatura manuale.

**Flusso piano / misura**
`portfolio/plan.py::build_investment_plan` (profilo da orizzonte + tolleranza, target da `config/model_portfolios.yaml`, cadenza versamenti = ceil(ordine minimo / mensile), calendario 12 mesi) → la skill salva `data/private/investment_plan.json` e lo rilegge nel `checkin`. `portfolio/ledger.py`: `record_decision` (JSONL append-only, ora con `category`/`theme`/`thesis_status`/`cap_eur` opzionali) → `evaluate_decisions` (shadow portfolio: reale vs alternativa dopo ≥ 90 giorni, nessuna conclusione sotto 10 decisioni). Da lì: `portfolio/edge.py::personal_edge` (alpha/hit-rate per categoria/tema, min-sample) e `portfolio/quality.py::decision_quality` (rubrica di processo 0-100, indipendente dall'esito).

**Flusso tesi / rotazione / esposizione nascosta**
`portfolio/thesis.py`: `save_thesis` registra claim + falsifier quantitativi per simbolo (`data/private/theses.json`); `check_thesis` li rivaluta su uno snapshot fresco → STABLE/STRENGTHENING/WEAKENING/BROKEN/UNVERIFIABLE, mai giudizio LLM. `portfolio/replacement.py::propose_replacement` confronta l'utilità (score × confidence × fit × salute-tesi) della posizione attuale contro candidati e cash → HOLD/REPLACE/SELL_TO_CASH, fee-aware; usato da `position-review` prima di ogni REDUCE/SELL. `portfolio/exposure.py::portfolio_exposure`/`fit_score` (`config/exposure_graph.yaml`) rivelano driver tematici condivisi non visibili dai soli settori, e alimentano il `fit` sia di `capital_auction` sia di `propose_replacement`.

**Confini**
- `providers/`: unico posto dove compaiono chiavi specifiche del provider. Un file per fonte (`yfinance_provider`, `sec_edgar`, `ecb_fx`, `stooq`, `finviz`), `cache.py` TTL, timeout esplicito tranne yfinance/finviz (vedi sotto), mai account/API key. Fuori circolano solo `StockSnapshot`/dict con `source`, `as_of`, `confidence`.
- `parsers/`: unico posto con specificità del formato export (alias colonne it/en in `ALIASES`, numeri `4.380,74`, leva dedotta da `"5X"` nel nome). Nessun nome di broker.
- `analytics/metrics.py`: matematica pura su `pd.Series`/liste, senza I/O.
- `models.py`: contratti Pydantic per ogni confine I/O; `Decision` enum include `BUY_SMALL` e `NO_BUY`.

## Regole di scoring (come implementate in `scoring/engine.py`)

Pesi `DEFAULT_WEIGHTS`: growth 20, quality 20, valuation 15, momentum 15, revisions 10, catalysts 10, risk 10.

- Ogni componente è la media di `_linear(value, bad, good)` sui sotto-indicatori disponibili; sotto-indicatori `None` sono esclusi dalla media.
- Componente interamente `None`: `ScoreComponent(score=50, available=False)` ed **escluso dalla media pesata**; i pesi restanti vengono rinormalizzati. `revisions`/`catalysts` non sono più sempre `None`: `server.py::_enrich_snapshot_with_free_data` li riempie da dati gratuiti (stime/rating-event `providers/yfinance_estimates.py`, storico sorprese `providers/yfinance_surprises.py`, conteggi Form 4/8-K `providers/sec_filings.py` per i filer SEC) quando esistono per quel ticker; con copertura sottile (`analyst_count < 3`) `revisions` si comprime verso il neutro 50. Restano `available=False` solo quando il free provider non ha proprio dati (titoli europei non-ADR per i rating event, ticker senza storico earnings, nessun CIK SEC).
- `confidence = min(provenance.confidence, 0.35 + 0.65 * coverage)` dove `coverage` = quota di peso disponibile.
- Lo score non è una previsione di rendimento. Una società buona non è automaticamente un `BUY`: prima di `BUY` vanno controllati peso esistente, settore, correlazione, bucket speculativo, leva, costo ordine, liquidità residua, limite per singolo titolo (`config/portfolio.example.yaml::risk_limits`).

## Regole di rebalancing (come implementate in `portfolio/rebalance.py`)

- `validate_targets`: i target devono sommare a 1.0 (tolleranza 1e-6) e non essere negativi → altrimenti `ValueError` esplicito.
- Cash-flow first, due passaggi: (1) **waterfall** sui deficit verso il target, il più grande per primo e per intero (una ripartizione proporzionale creava fette sotto l'ordine minimo → cash inattivo per mesi, visto nel backtest); (2) **top-up**: se il residuo è ancora un ordine economico va al bucket più sottopeso senza superare target + banda. Drift dentro `rebalance_band_abs` (0.03) → nessun deficit.
- `FeeModel(fixed_fee_eur=2.95, variable_fee_pct=0.0, max_fee_ratio=0.01)`: `minimum_economic_order = fixed / (max_ratio - variable)` (= 295 EUR con i default). Ordini sotto soglia vengono scartati, non ridotti; il cash resta per il versamento successivo (il piano ne deriva la cadenza: 100 €/mese ⇒ ogni 3 mesi).
- Il cash non va mai negativo: se l'ultimo ordine non ci sta, viene ridimensionato e riverificato per economicità.
- Ordine di preferenza generale: nuova liquidità → sospendere acquisti sui sovrappeso → comprare i sottopeso → vendere solo se drift/rischio supera soglia o tesi cambiata. **La V1 non genera `SELL`**: implementare la logica sell solo con test e vincoli espliciti nel piano.

## Leva

`Holding.leverage` (default 1.0; da colonna `leva` o regex `\d+x` sul nome). In `summarize_portfolio_risk` gli strumenti con `|leverage| > 1` contribuiscono a `leveraged_nominal_value` e `leveraged_equivalent_exposure = nominale × |leva|`. È una metrica indicativa, separata dal peso nominale: **non presentarla come VaR**.

## Convenzioni di codice

- Funzioni pure per scoring/rebalancing/metrics; docstring sulle funzioni pubbliche.
- Nessun `except Exception: pass`. Gli `except Exception` esistenti servono tutti a degradare a un risultato strutturato invece di propagare: `analyze_stock`, lo screening per-ticker in `screen_stocks`, il fetch prezzi per-simbolo in `review_decisions`, `FinvizProvider.screen` e `YFinanceProvider.get_monthly_closes`. Il fallback multi-encoding del parser è altrove e più stretto: `parsers/broker_export.py::_read_rows` cattura `UnicodeDecodeError`, non `Exception`; `_read_table` non ha except clause e solleva `ValueError` diretto. Non aggiungerne di nuovi senza motivo.
- Chiamate web con timeout e `providers/cache.py` (TTL: FX 6 h, SEC 24 h, Stooq/Finviz 6 h, yfinance 5 min; yfinance e finviz ancora senza timeout esplicito, usano il default della libreria).
- Test obbligatori sugli edge case: NaN, ticker non valido, currency mismatch, portfolio vuoto, commissioni > ordine.
- Test con rete: marker `@pytest.mark.network`. Non c'è `addopts` che li escluda: se ne aggiungi, aggiungi anche `addopts = "-m 'not network'"` in `pyproject.toml` così `uv run pytest` resta offline.

## Gap noti / roadmap (vedi tabella motori in `docs/ARCHITECTURE.md`)

- I tool rebalance/allocate prendono `current_values: dict`: la mappatura holding → bucket target la fa `portfolio/mapping.py` (tool `map_holdings_to_targets`, per ISIN poi per parole chiave del nome); certificati/leva/singoli titoli restano satellite, mai persi dalla coverage.
- `config/portfolio.yaml` è letto dal tool MCP `get_portfolio_config` (fallback su `config/portfolio.example.yaml`, flag `is_example`); le skill lo chiamano e passano i valori come parametri, mai lette a mano dal file.
- `rebalance_portfolio` genera `SELL` solo se `allow_sells=True` (mai di default); il `replacement engine` (`propose_replacement`) può proporre `SELL_TO_CASH`/`REPLACE` indipendentemente, gated da fee di andata e ritorno. Thesis engine, personal edge, decision quality, hidden-exposure graph, insider/macro: implementati (vedi tabella motori in `docs/ARCHITECTURE.md`). Catalyst/revisions: implementati su dati gratuiti (tier B stime/rating-event yfinance + tier A Form 4/8-K SEC) via `server.py::_enrich_snapshot_with_free_data`; restano `V2` solo un vero feed di consensus point-in-time (IBES/FactSet/Estimize sono a pagamento) e il bulk Form 3/4/5 SEC per un segnale insider realmente point-in-time.
- Discovery non esclude più per taglia: `discover_stocks(mode='universe')` (default) campiona ogni size bucket × stile via `FinvizProvider.discover_universe`, senza filtri; `mode='preset'` resta il vecchio screen singolo. `portfolio/picker.py::rank_by_potential`/`shortlist` ordinano l'intero universo per potenziale (score poi confidence poi ticker), mai un filtro — solo tag informativi (`size_bucket`, `lane`, `core_overlap_note`, `diversification`); solo i risk cap e il red team dimensionano un `BUY`. Tool `rank_candidates` fa screen+shortlist in un colpo; `resolve_isins` mappa ISIN→ticker via OpenFIGI (tier A, keyless); `backtest_picker` esegue `portfolio/picker_backtest.py::run_proxy_backtest` su dati live (sopravvivenza dell'universo odierno, backfill Yahoo, nessun costo di transazione, revisioni event-dated non consensus — sempre dichiarati in `disclosures`).
- Evidence layer: precedenza A > B su due campi (`analytics/merge.py`) più il flag di conflitto multi-fonte (`analytics/evidence.py`, tool `analyze_stock`'s campo `evidence`); un CONFLICT non risolto da una fonte tier A è escluso dallo score.
- yahooquery (fallback prezzi), Eurostat (macro), SEC filing sections/Form 4 (`providers/sec_filings.py`), crawler IR (`providers/investor_relations.py`): implementati sotto la stessa regola zero-signup. Nessun candidato V2 rimasto in questa lista.
- L'XLSX reale del broker non è mai stato letto dal parser (solo il layout osservato, replicato in fixture sintetiche); quando arriva, aggiornare le fixture senza committare valori reali.

## Prima di modificare

1. Leggi `docs/PRD.md` (requisiti, acceptance criteria), `docs/ARCHITECTURE.md` (confini moduli, regole dati), `docs/FINANCIAL_LOGIC.md` (formule), `docs/IMPLEMENTATION_PLAN.md` (fasi e backlog V2).
2. `uv run pytest` e `uv run ruff check .` prima e dopo.
3. Task più piccolo possibile, con test aggiornati.

## Plugin Claude Code (il repo è anche il plugin)

- `.claude-plugin/plugin.json` + `marketplace.json` (`source: "./"`); versioni allineate (test).
- `skills/`: `start` (entry point unico, instrada), `investment-plan` (new + checkin), `portfolio-review`, `deploy-cash`, `rebalance`, `stock-picker`, `position-review`. In inglese, formato fisso: guardrail → "ask at most two questions" → tool in ordine → risposta ≤ 6 righe → "why" per i dettagli. Test: ogni skill contiene "No broker access", "manual", "≤ 6 lines", < 120 righe.
- `agents/red-team.md`: reviewer read-only che attacca ogni BUY (evidenza, conflitto fonti tier, tesi rotta, fit di portafoglio, costo, fragilità) e risponde passed/rejected in 4 righe.
- `hooks/hooks.json`: `SessionStart` → banner del perimetro; `PreToolUse` (Bash/WebFetch/Read/Write/Edit) → `no-broker-access.sh` nega URL di login/auth/area privata, header di autenticazione, stringhe credenziali (test via subprocess).
- `.mcp.json` unico: `uv run --directory ${CLAUDE_PLUGIN_ROOT:-.}`; stesso nome server nei due scope → Claude Code ne carica uno solo.
- Tool MCP (43): `parse_portfolio_export`, `get_portfolio_config`, `portfolio_risk`, `portfolio_exposure`, `map_holdings_to_targets`, `analyze_stock`, `screen_stocks`, `discover_stocks`, `rank_candidates`, `backtest_picker`, `resolve_isins`, `company_facts`, `filing_sections`, `insider_activity`, `investor_relations_links`, `penny_flags`, `fx_rates`, `convert_amount_to_eur`, `macro_snapshot`, `allocate_cash`, `rebalance_portfolio`, `generate_order_plan`, `capital_auction`, `build_investment_plan`, `backtest_plan`, `simulate_plan_risk`, `kelly_size`, `save_thesis`, `check_thesis`, `propose_replacement`, `log_decision`, `review_decisions`, `personal_edge`, `decision_quality`, `save_portfolio_snapshot`, `list_portfolio_snapshots`, `compare_snapshots`, `etoro_account`, `etoro_positions`, `etoro_orders`, `etoro_search_instrument`, `prepare_execution`, `execute_plan` (gli ultimi 6 solo per il conto eToro dell'utente, vedi Eccezione eToro). Prompt: `portfolio_review`, `stock_picker`, `rebalance`, `deploy_cash`. `capital_auction` ritorna anche `candidates_for_ledger` (ranking con prezzo/price_symbol, pronto per `log_decision(candidates=...)`); `review_decisions` include una sezione `opportunity` (`portfolio/opportunity.py`: regret contro l'intera ranking vista al momento della decisione, non solo la singola `alternative`); `analyze_stock` include anche `estimates` (`providers/yfinance_estimates.py::AnalystEstimates`, con provenance).

## Formato export osservato

Export "pagina Portafoglio" di un broker italiano. Righe di riepilogo (Portafoglio, Dossier, Valorizzazione…) prima della tabella, riga `Totale` in coda. Colonne: `Titolo` (ticker sulla prima riga della cella), `Strumento` (Azione / ETF / Certificate → `asset_type`), `Valuta`, `Quantità`, `P.zo medio di carico`, `P.zo di mercato`, `Val di mercato € (Margine)`, `Var €`, `Var %`. Header su più righe (gestiti da `_norm_col`), decimali italiani `4.380,74`, segni `+/-`, `%` nel Var %. **`Val di mercato` è sempre in EUR** anche per strumenti in USD (`Holding.currency` = valuta dello strumento, `market_value` = EUR). Fixture sintetiche: `tests/fixtures/broker_export_sample.csv`, `broker_export_page_layout.csv`. Non ancora visto: l'XLSX reale.
