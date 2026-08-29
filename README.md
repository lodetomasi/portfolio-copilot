# Portfolio Copilot

> **Hai dei soldi da investire e non sai da dove partire?** Portfolio Copilot è un plugin per
> Claude Code che ti fa da consulente metodico: tu parli da principiante, lui elabora come un
> esperto usando solo dati pubblici e ti risponde in poche righe — *compra questo, per questo
> importo, in questa data*. Nessun ordine viene eseguito: li fai tu, a mano, sul tuo broker.

*English abstract — Portfolio Copilot is a Claude Code plugin + local MCP server for retail
investors: investment plan with calendar, portfolio review, cash deployment, fee-aware
rebalancing and stock picking from a local broker export. Zero signup data sources (Yahoo, SEC
EDGAR, ECB, Eurostat, Finviz), deterministic Python engines, 1092 offline tests, suggested
orders only — never trades, never logs into a broker.*

---

## Il problema che risolve

Chi inizia a investire si trova davanti a tre muri: *cosa* comprare, *quanto* e *quando*, e come
non farsi mangiare il risultato dalle commissioni e dalle proprie emozioni. Le alternative sono
un consulente a pagamento, un robo-advisor con fee ricorrenti, o "chiedere a ChatGPT" e ricevere
un papiro senza numeri verificabili.

Portfolio Copilot fa una cosa diversa: **tutti i calcoli sono deterministici in Python** (pesi,
drift, commissioni, ordine minimo economico, calendario, backtest), **ogni dato esterno porta
fonte, data e confidenza**, e Claude si limita a capire cosa vuoi, chiamare gli strumenti giusti e
tradurre il risultato in un'istruzione semplice. Se un dato manca, lo dice; `HOLD` e
`NO_BUY` sono risposte complete.

## Use case: dal primo euro al check-in trimestrale

```text
tu:   /portfolio-copilot:start
lui:  Cosa vuoi fare? 1 piano da zero · 2 review del portafoglio · 3 soldi nuovi · 4 pesi · 5 un titolo

tu:   1 — ho 5.000 € oggi, 100 € al mese, 15 anni, se scende del 30% compro ancora
lui:  Profile: growth. Buy now (manual): Vanguard FTSE All-World 4.000 €, iShares MSCI World
      Small Cap 500 €, Vanguard FTSE EM 491 €. Fees ≈ 8,85 €. Keep 0 € in cash.
      Then: invest 300 € every 3 months into the most underweight bucket (100 €/mese non
      conviene: la fee da 2,95 € supererebbe l'1%).
      Calendar: next buy 2026-11-28, first review 2026-11-28, annual review 2027-08-28.
      Verify the ISINs on your broker first. Say "why" for the reasoning.

... tre mesi dopo, con l'export aggiornato del broker ...

tu:   /portfolio-copilot:investment-plan checkin ~/Downloads/export.xlsx
lui:  As of 2026-11-28: portfolio 5.310 €, contributions so far 5.300 €.
      Drift: small_cap -1,2% — in band. Do now: BUY global_equity 297 € (fee 2,95 €).
      Outside the plan: none. Next: contribute 2027-02-28.
```

Le sei skill coprono l'intero ciclo di vita:

| ho bisogno di… | skill | mi chiede solo |
|---|---|---|
| un piano da zero con calendario e check-in | `investment-plan` | quanto oggi, quanto al mese, quanti anni, come reagirei a −30% |
| capire cosa non va nel mio portafoglio | `portfolio-review` | il file export |
| impiegare soldi nuovi senza fare danni | `deploy-cash` | export, importo |
| controllare se sono fuori dai pesi | `rebalance` | export |
| idee di azioni (anche senza sapere i ticker) | `stock-picker` | opzionale: ticker, export |
| tenere o vendere un titolo che ho | `position-review` | ticker, export |

Risposte in **≤ 6 righe**; i dettagli arrivano solo se scrivi `why`. Ogni `BUY` passa prima da
un agente **red team** che cerca il motivo per non comprare.

## Cosa NON fa (per scelta)

- **Non si collega a nessuna banca o broker.** Niente login, credenziali, OTP, ordini. Un hook
  blocca qualsiasi chiamata verso superfici di autenticazione.
- **Non usa servizi con registrazione o API key.** Solo fonti pubbliche: Yahoo Finance
  (`yfinance` + `yahooquery` di riserva), SEC EDGAR (XBRL 10-K, filing, Form 4), BCE (cambi e
  tasso sui depositi), Eurostat (inflazione, disoccupazione), Finviz (crawler open source, solo
  per la scoperta), pagine investor-relations pubbliche.
- **Non inventa dati** e non prevede rendimenti: lo score 0-100 descrive qualità, prezzo e
  momentum, non il futuro; i backtest sono replay del passato, mai proiezioni.
- **Non contiene il nome di alcun broker** nel codice: il parser legge export XLSX/CSV generici
  (intestazioni su più righe, decimali italiani, riga "Totale", ticker nel nome, leva `5X`).

## Come funziona sotto

```text
il tuo export XLSX/CSV ──► parser ──► pesi, concentrazione, leva, esposizioni nascoste
                                          │
dati pubblici (tier A/B/C) ──► provider ──► evidence layer (SEC batte Yahoo, conflitti segnalati)
                                          │
                              score 0-100 + confidence · tesi con falsificatori
                                          │
                      asta del capitale (bucket vs azioni vs cash) · ribilanciamento fee-aware
                                          │
                        red team ──► ordini SUGGERITI ──► tu ──► il tuo broker
                                          │
                       decision ledger ──► shadow portfolio ──► personal edge (dopo ≥10 decisioni)
```

Motori deterministici (Python, `src/portfolio_copilot/`): parser, scoring, allocatore
cash-flow-first (waterfall sul bucket più sottopeso + top-up entro banda, mai sotto l'ordine
minimo economico = fee / 1%), piano con cadenza versamenti, backtest mensile, thesis engine,
replacement engine (vendi solo se c'è di meglio, fee comprese), hidden-exposure graph, capital
auction, decision ledger + shadow portfolio, personal edge, decision quality, macro regime,
snapshot store e opportunity-cost ledger. Mappa completa con stato per motore:
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

Due cose in più che il copilot si ricorda per te: ad ogni check-in salva una "foto" del
portafoglio (quanto vale, come è diviso nei bucket), così al check-in dopo ti dice quanto è
cambiato in totale — sapendo però che quel numero è versamenti *più* mercato insieme, mai
uno dei due da solo. E ogni volta che logghi una decisione, si ricorda anche le altre opzioni
che aveva scartato in quel momento: dopo abbastanza decisioni ti dice se avresti fatto
meglio a scegliere qualcos'altro, o se è ancora troppo presto per saperlo.

## Numeri, non promesse

| cosa | valore | dove |
|---|---|---|
| test automatici (tutti offline e deterministici) | **1092 passed**, 0 skipped, 0 xfail | [`docs/TEST_REPORT.md`](docs/TEST_REPORT.md) — KPI di ogni singolo test |
| coverage di riga (`src/portfolio_copilot`) | **~94 %** | idem, per modulo |
| lint / manifest | `ruff` pulito · `claude plugin validate --strict` ok su plugin, skill, agent | idem |
| tool MCP esposti | **31** + 4 prompt | `docs/ARCHITECTURE.md` |
| backtest reali (3 profili × 5/10 anni, dati Yahoo) | commissioni 0,79–0,84 % dei versamenti, cash inattivo 0 €, fuori banda 0–4 % dei mesi | [`docs/BACKTEST.md`](docs/BACKTEST.md) |
| performance motori | parser 1000 righe 0,04 s · 1000 scenari di allocazione 0,01 s · backtest 240 mesi 0,004 s | idem |

Il backtest ha già fatto il suo mestiere: la prima versione dell'allocatore (ripartizione
proporzionale) lasciava fino a 2.300 € inattivi su 25.600 versati; la versione attuale li
investe tutti restando sotto il tetto di commissioni.

## Installazione

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh                 # se non hai uv
git clone https://github.com/lodetomasi/portfolio-copilot && cd portfolio-copilot
uv sync --extra dev && uv run pytest -q                          # 1092 passed
claude plugin marketplace add . && claude plugin install portfolio-copilot@portfolio-copilot
```

Poi in Claude Code: `/reload-plugins` (o riavvia) e `/portfolio-copilot:start`. Per lo
sviluppo locale basta `claude --plugin-dir .`.

Configurazione opzionale: `cp config/portfolio.example.yaml config/portfolio.yaml` (commissioni,
banda, limiti, target). I modelli di portafoglio sono in `config/model_portfolios.yaml` (ISIN da
verificare sul broker prima di ogni ordine). Piano, tesi e ledger vivono in `data/private/`
(git-ignored). SEC EDGAR richiede uno User-Agent con contatto: il default funziona (verificato
live); se SEC lo bloccasse, imposta `PORTFOLIO_COPILOT_SEC_USER_AGENT="tua-app tuo@contatto"`.

## Sviluppo e verifica

```bash
uv run pytest -q                                   # suite completa
uv run ruff check .                                # lint
uv run --with pytest-cov python scripts/test_report.py   # rigenera docs/TEST_REPORT.md
uv run python scripts/backtest_report.py           # rigenera docs/BACKTEST.md (rete)
uv run mcp dev src/portfolio_copilot/server.py     # MCP Inspector
```

Regole di lavoro per Claude Code in [`CLAUDE.md`](CLAUDE.md); requisiti in
[`docs/PRD.md`](docs/PRD.md); formule in [`docs/FINANCIAL_LOGIC.md`](docs/FINANCIAL_LOGIC.md).

## Disclaimer

Questo software produce analisi e ordini *suggeriti* a scopo informativo. Non è consulenza
finanziaria, non esegue operazioni e non garantisce alcun rendimento. Le decisioni e la loro
esecuzione restano interamente dell'utente.
