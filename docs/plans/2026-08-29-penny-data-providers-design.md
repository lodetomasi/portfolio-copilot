# Design — Provider dati penny-stock (FINRA + SEC penny signals) e tool `penny_flags`

Data: 2026-08-29 · Complessità: Media · SP: Umano 4 / Augmented 1.5 — split: provider
FINRA + test 1.5/0.55; provider SEC penny + test 1.5/0.55; tool `penny_flags` + wiring +
test 1.0/0.4.

## Contesto

Goal utente (2026-08-29): più quantità e qualità di dati GRATUITI per le penny stock.
Ricerca live (agente, 2026-08-29, curl-verificata) ha confermato 6 fonti keyless; le
implementiamo nelle 2 a massimo valore/effort, tutte tier A (regolatori):

- **FINRA Query API** `https://api.finra.org/data/group/otcMarket/name/<dataset>`
  (keyless): `consolidatedShortInterest` (short interest bimensile incl. OTC, campi
  `currentShortPositionQuantity`, `daysToCoverQuantity`, `changePercent`,
  `settlementDate`), `otcDailyList` (corporate action: reverse split, bankruptcy flag,
  delete flag), `thresholdList` (Reg SHO threshold = FTD persistenti). GET con
  `?limit=N` o POST `{"compareFilters":[{"fieldName":"symbolCode","fieldValue":"X",
  "compareType":"equal"}]}` (verificato funzionante). Nessun rate limit dichiarato →
  self-throttle prudenziale.
- **FINRA CDN Reg SHO daily** `https://cdn.finra.org/equity/regsho/daily/
  <PFX>shvol<YYYYMMDD>.txt` (pipe-delimited; `CNMS` consolidato NMS, `FORF` = OTC,
  gli unici due che usiamo): short volume ratio giornaliero.
- **SEC EDGAR full-text search** `https://efts.sec.gov/LATEST/search-index?q=...&
  forms=...` (JSON; hit con `display_names` ticker+CIK, `file_date`): S-1/424B/S-3 e
  query "equity line of credit"/"at-the-market" = **dilution in arrivo**.
- **SEC XBRL companyconcept** `https://data.sec.gov/api/xbrl/companyconcept/
  CIK<10cifre>/dei/EntityCommonStockSharesOutstanding.json`: serie del numero di
  azioni = **diluizione avvenuta**, misurata.
- **SEC trading suspensions RSS** `https://www.sec.gov/enforcement-litigation/
  trading-suspensions/rss` (200 verificato): sospensione = kill switch.

Scartate e documentate: OTC Markets (403/Akamai, come Stooq), StockPromotionTracker
(a pagamento), OpenBB Platform (dipendenza pesante per dati già raggiungibili con 6
GET diretti — YAGNI).

## Approcci valutati

1. **Due provider nuovi + un tool aggregatore `penny_flags` (SCELTO).** Rispetta il
   confine "un file per fonte" (FINRA = un'organizzazione/due canali → un file; SEC ha
   già `sec_edgar.py`/`sec_filings.py` per funzione → terzo file per i penny signal).
   I segnali NON entrano nello score (regola: pesi dello scoring stabili, Finviz-like
   data mai nello score): alimentano dossier/red team/falsificatori delle tesi.
2. Estendere `sec_filings.py` e creare solo FINRA. Contro: `sec_filings.py` è già
   grande e ha un altro scopo (sezioni 10-K, Form 4); mescolare confonde il confine.
3. Adottare OpenBB come dipendenza. Contro: albero di dipendenze enorme per 6 endpoint
   HTTP; viola KISS. Scartato.

## Design

### `src/portfolio_copilot/providers/finra.py`
Classe `FINRAProvider(timeout=15.0, transport=None, clock/sleeper iniettabili)`:
- Riusa `RateLimiter` importandolo da `providers/sec_filings.py` (già iniettabile e
  testato; AHA: niente duplicazione) con `max_per_second=4.0` prudenziale.
- `TTLCache(6*3600)` come Finviz (dati che cambiano al più giornalmente).
- `short_interest(symbol) -> dict`: POST `consolidatedShortInterest` con
  compareFilter su `symbolCode`; ritorna `{short_position, days_to_cover,
  change_percent, settlement_date, ...envelope}` (ultima settlement date disponibile).
- `daily_short_volume(symbol, day: date | None = None) -> dict`: scarica
  `FORF` e `CNMS` del giorno (default: ultimo giorno feriale), parse pipe-delimited,
  riga del simbolo → `{short_volume, total_volume, short_ratio}`; simbolo assente in
  entrambi i file → `ok: False` con spiegazione (mai inventare zero).
- `corporate_actions(symbol) -> dict`: POST `otcDailyList` filtrato → lista eventi
  (reverse split, bankruptcy/delete flag) con date.
- `on_threshold_list(symbol) -> dict`: POST `thresholdList` filtrato → `{on_list:
  bool, as_of}`.
- Envelope标准: `source="finra"`, `tier="A"`, `as_of` ISO UTC, `confidence=0.9`.
- HTTP non-200 → `ok: False` strutturato (mai eccezione al chiamante); niente nuovo
  `except Exception`.

### `src/portfolio_copilot/providers/sec_penny.py`
Classe `SECPennyProvider(edgar: SECEdgarProvider | None = None, timeout, transport)`:
riusa CIK resolution + User-Agent SEC da `SECEdgarProvider` (come fa `sec_filings.py`),
`RateLimiter(8.0)`, `TTLCache(24*3600)`.
- `dilution_filings(ticker, days=365) -> dict`: EFTS full-text search, due query:
  `forms=S-1,S-3` e `q="equity line of credit" OR "at-the-market"` limitate al CIK
  del ticker e alla finestra; ritorna `{filings: [{form, date, adsh}], count}`.
- `shares_outstanding(ticker) -> dict`: XBRL companyconcept
  `dei/EntityCommonStockSharesOutstanding` → serie (ultimi 8 punti) +
  `change_12m_pct` calcolato dai due punti a ~12 mesi di distanza; serie assente →
  `ok: False` dichiarato.
- `trading_suspension(ticker, company_name=None) -> dict`: fetch RSS sospensioni,
  match case-insensitive su ticker (word boundary) e, se dato, sul nome; ritorna
  `{hit: bool, items: [...]}`. Il match sul solo ticker può dare falsi positivi su
  ticker corti → l'esito porta `match_type: "ticker"|"name"` e il chiamante lo mostra.
- Envelope: `source="sec_efts"|"sec_xbrl"|"sec_rss"`, `tier="A"`, `confidence=0.95`.

### Tool MCP `penny_flags(ticker)` in `server.py` (43° tool)
Provider FINRA e SECPenny module-level (come gli altri). Chiama le 6 letture,
ognuna degradabile: campo `None` + voce in `missing` se la fonte non risponde (regola
4: mai inventare). Output:
```
{ok, ticker, short_interest: {...}|None, days_to_cover, daily_short_ratio,
 on_threshold_list, corporate_actions: [...], dilution_filings_12m,
 shares_outstanding_change_12m_pct, trading_suspension: {...},
 red_flags: [stringhe deterministiche], missing: [...], sources: [...], as_of}
```
`red_flags` (regole deterministiche, non LLM): suspension hit; reverse split < 12
mesi; dilution_filings_12m >= 2; shares_outstanding_change_12m_pct > 15;
on_threshold_list; days_to_cover > 5. Ogni flag cita il numero che la genera.
NON tocca lo scoring: consumato dai dossier autopilot, dal red team e come
falsificatori quantitativi delle tesi.

## Flusso dati
autopilot dossier step c → `penny_flags(ticker)` → nel fascicolo del finalista e nel
prompt del red team; `save_thesis` usa i numeri (es. "falsifier: shares outstanding
+>10% o nuovo S-1") come falsificatori.

## Errori
Nessun nuovo `except Exception`. Timeout/HTTP error → `ok: False` con `error`
leggibile; il tool aggrega e dichiara `missing` per fonte. Input vuoto/ticker
non-CIK → `ok: False` (SEC) ma le parti FINRA possono comunque rispondere.

## Rischi e mitigazioni
- **Endpoint FINRA non documentati come keyless**: potrebbero chiudere → ogni metodo
  degrada a `ok: False`; il tool dichiara `missing`, il sistema continua (stesso
  pattern Stooq). Self-throttle 4 req/s.
- **RSS/EFTS shape drift**: parser difensivi (get() ovunque), test su fixture salvate
  dalla forma reale verificata oggi; drift → test rossi, mai crash runtime.
- **Falsi positivi ticker corti nel match sospensioni**: `match_type` esposto,
  red flag solo con match su nome o ticker >= 4 caratteri.
- **Giorno festivo per il daily short volume**: fallback fino a 5 giorni indietro,
  data usata dichiarata in `as_of`.

## Testing (offline, deterministico — httpx.MockTransport, pattern test_etoro_client)
- FINRA: short_interest happy + simbolo assente; daily FORF/CNMS parse + ratio +
  simbolo mancante + fallback giorno precedente; corporate actions reverse split;
  threshold sì/no; 500 → ok False.
- SEC penny: dilution 2 filing; 0 filing; shares outstanding serie → change_12m_pct
  esatto su fixture nota; serie assente; suspension hit per nome e non-hit;
  match_type ticker corto non genera red flag.
- Tool: tutte le fonti ok → red_flags attesi esatti su fixture costruita (reverse
  split + dilution 2 + shares +20% → 3 flag); FINRA giù → missing dichiarato e
  ok True con campi None; ticker senza CIK → parti SEC missing.
- `tools/list` include `penny_flags` (aggiunta a NEW_TOOL_NAMES).

## File coinvolti

Questo è il design di punta del branch `feature/evidence-caps-risk-math`, che integra
quattro design approvati nella stessa directory (questo, `2026-08-29-evidence-caps-
enforcement-design.md`, `2026-08-29-risk-math-engine-design.md`,
`2026-08-29-etoro-execution-adapter-fixes-design.md`). File del branch per design di
provenienza:

Questo design (penny data):
- `src/portfolio_copilot/providers/finra.py`
- `src/portfolio_copilot/providers/sec_penny.py`
- `tests/test_finra.py`
- `tests/test_sec_penny.py`
- `tests/test_server_penny_flags.py`
- `src/portfolio_copilot/server.py`
- `tests/test_server_tools.py`
- `CLAUDE.md`

Design evidence-caps-enforcement (approvato, stesso branch):
- `src/portfolio_copilot/portfolio/execution.py`
- `src/portfolio_copilot/portfolio/picker.py`
- `tests/test_execution.py`
- `tests/test_picker.py`
- `skills/stock-picker/SKILL.md`

Design risk-math-engine (approvato, stesso branch):
- `src/portfolio_copilot/analytics/risk_math.py`
- `tests/test_risk_math.py`
- `tests/fixtures/risk_math_closes.csv`
- `tests/test_server_risk_tools.py`
- `skills/investment-plan/SKILL.md`

Design etoro-execution-adapter (approvato, stesso branch; Eccezione eToro in CLAUDE.md):
- `src/portfolio_copilot/brokers/__init__.py`
- `src/portfolio_copilot/brokers/etoro.py`
- `src/portfolio_copilot/portfolio/venues.py`
- `src/portfolio_copilot/portfolio/sources.py`
- `src/portfolio_copilot/portfolio/risk_profile.py`
- `src/portfolio_copilot/portfolio/ledger.py`
- `tests/test_etoro_client.py`
- `tests/test_venues.py`
- `tests/test_sources.py`
- `tests/test_risk_profile.py`
- `tests/test_ledger.py`
- `tests/test_server_etoro.py`
- `tests/test_plugin.py`
- `tests/fixtures/drawdown_history_sample.json`
- `skills/deploy-cash/SKILL.md`
- `skills/position-review/SKILL.md`
- `skills/rebalance/SKILL.md`
- `skills/start/SKILL.md`
- `.claude-plugin/plugin.json`
- `.claude-plugin/marketplace.json`
- `README.md`
- `docs/ARCHITECTURE.md`
- `config/model_portfolios.yaml`

## Criteri di accettazione
1. `penny_flags("X")` su fixture completa ritorna i red_flags deterministici attesi
   e ogni numero citato nel flag (test).
2. Ogni fonte giù degrada a `missing` dichiarato, mai eccezione, mai zero inventato
   (test per FINRA giù e per ticker senza CIK).
3. `uv run pytest` verde (nuovi inclusi), `uv run ruff check .` pulito,
   `tools/list` = 43 tool (CLAUDE.md aggiornato nelle due occorrenze 42 → 43).
4. Nessuna modifica a `scoring/engine.py` né ai pesi (i segnali non entrano nello
   score).
5. Prompt autopilot aggiornato: dossier step include `penny_flags` per ogni finalista.
