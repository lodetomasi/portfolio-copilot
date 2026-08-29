# PRD — Portfolio Copilot

## 1. Problema

L'utente vuole concentrare il patrimonio sul broker ma non vuole:
- scegliere azioni casualmente;
- pagare fee elevate a servizi di autopilot;
- fare ribilanciamenti manuali complessi;
- perdere visibilità su concentrazione, leva e costi.

Serve un copilot locale, gratuito nella V1, che combini:
- portfolio analytics;
- stock discovery;
- stock ranking;
- rebalancing;
- cash deployment;
- order planning.

## 2. Utente target

Investitore retail tecnicamente competente, con:
- ETF core;
- una quota satellite di azioni singole;
- possibile uso limitato di prodotti a leva;
- PAC mensile;
- broker.

## 3. Jobs to be done

### Portfolio review
"Dimmi cosa possiedo davvero, dove sono concentrato e cosa è ridondante."

### Stock picker
"Non so che azioni comprare: cercami opportunità con metodo."

### Deploy cash
"Ho X euro nuovi: dove li metto senza creare trading inutile?"

### Rebalance
"Riporta il portafoglio verso i target minimizzando vendite e commissioni."

### Position review
"Questo titolo è ancora coerente con la mia tesi e il mio portafoglio?"

## 4. Output standard

Ogni decisione deve distinguere:

- `BUY`
- `BUY_SMALL`
- `HOLD`
- `WATCH`
- `REDUCE`
- `SELL`
- `NO_BUY`

e contenere:
- motivazione;
- metriche usate;
- confidence;
- rischio;
- size massima;
- costo stimato;
- impatto sul portafoglio.

## 5. Stock score

### Componenti
- Growth 20
- Quality 20
- Valuation 15
- Momentum 15
- Revisions 10
- Catalysts 10
- Risk 10

### Regola missing data
Non imputare valori ottimistici.
Ripesare solo i componenti disponibili e riportare coverage/confidence.

### Categorie
- Quality / Compounder
- Growth / Momentum
- Asymmetric / High Risk

## 6. Portfolio constraints

Configurabili:
- max single stock;
- max high-risk stock;
- max sector;
- max speculative bucket;
- max nominal leveraged bucket;
- min cash;
- target ETF buckets;
- transaction cost cap;
- rebalance band.

## 7. Rebalancing

### Cash-flow first
La V1 deve preferire l'uso dei nuovi versamenti rispetto alle vendite.

### Drift
Nessuna operazione se la deviazione è dentro la banda.

### Costi
Non generare ordine se `fee / order_value` supera soglia, salvo override esplicito.

## 8. Broker export import

Input:
- CSV;
- XLSX;
- mapping manuale fallback.

Campi normalizzati:
- symbol / isin
- name
- asset_type
- currency
- quantity
- avg_cost
- market_price
- market_value
- pnl_value
- pnl_pct
- leverage

## 9. MVP tools

1. `parse_portfolio_export(path)`
2. `analyze_stock(ticker)`
3. `screen_stocks(tickers, min_score)`
4. `portfolio_risk(path)`
5. `rebalance_portfolio(path, targets, cash)`
6. `allocate_cash(path, cash, targets)`
7. `generate_order_plan(path, cash, targets)`
8. `position-review` skill (not a standalone tool) -- composes `parse_portfolio_export`, `portfolio_risk`, `analyze_stock`

## 10. Non-goals V1

- execution trading;
- broker login;
- tax return automation;
- options strategy;
- intraday signals;
- HFT;
- price prediction by LLM;
- guaranteed alpha.

## 11. Acceptance criteria

### Portfolio
- totale valorizzato coerente entro rounding;
- pesi sommano a ~100%;
- leva separata;
- concentrazione top 1/3/5.

### Stock
- ticker invalidi gestiti;
- source/as_of inclusi;
- score riproducibile a parità di dati.

### Rebalance
- nessun ordine sotto minimum economic order;
- cash non diventa negativo;
- target sum validata;
- se tutti i drift sono dentro banda => NO ACTION.

### Resilience
- timeout web;
- provider failure => errore leggibile / fallback;
- nessuna decisione basata su dato `None`.
