# Backtest & performance report

Generated 2026-08-29 02:45 UTC by `scripts/backtest_report.py`.

> **Replay, not forecast.** Each row replays the plan rules (cash-flow-first waterfall + top-up, fee 2.95 EUR/order, max fee ratio 1%, band ±3%, 5000 EUR initial + 300 EUR/month, never sells) on past monthly prices from free sources. Past prices say nothing about future returns; the useful KPIs are fees paid, months out of band and idle cash — those measure the RULES. `period` is what was requested; `from → to` is the common window actually available for every bucket (some UCITS ETF share classes have short listings, so a 10y request may replay fewer months).

## Model portfolios replayed

| profile | period | from → to | months | contributed € | final € | gain € | fees € (% of contrib.) | orders | max drawdown | months out of band | cash left € | sources |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| cautious | 5y | 2021-09-30 → 2026-08-31 | 60 | 22,700 | 26,739 | 4,039 | 179.95 (0.79%) | 61 | -2.1% | 0% | 0.00 | global_equity: yfinance, global_bonds_hedged: yfinance |
| cautious | 10y | 2020-02-29 → 2026-08-31 | 79 | 28,400 | 34,867 | 6,467 | 236.00 (0.83%) | 80 | -2.8% | 0% | 0.00 | global_equity: yfinance, global_bonds_hedged: yfinance |
| balanced | 5y | 2021-09-30 → 2026-08-31 | 60 | 22,700 | 30,069 | 7,369 | 182.90 (0.81%) | 62 | -4.4% | 3% | 0.00 | global_equity: yfinance, small_cap: yfinance, emerging_markets: yfinance, global_bonds_hedged: yfinance |
| balanced | 10y | 2020-02-29 → 2026-08-31 | 79 | 28,400 | 40,946 | 12,546 | 238.95 (0.84%) | 81 | -5.8% | 3% | 0.00 | global_equity: yfinance, small_cap: yfinance, emerging_markets: yfinance, global_bonds_hedged: yfinance |
| growth | 5y | 2021-09-30 → 2026-08-31 | 60 | 22,700 | 33,835 | 11,135 | 182.90 (0.81%) | 62 | -8.8% | 0% | 0.00 | global_equity: yfinance, small_cap: yfinance, emerging_markets: yfinance |
| growth | 10y | 2020-02-29 → 2026-08-31 | 79 | 28,400 | 48,225 | 19,825 | 236.00 (0.83%) | 80 | -10.2% | 4% | 0.00 | global_equity: yfinance, small_cap: yfinance, emerging_markets: yfinance |

Reading the table: `fees %` should stay ≤ 1% (the cap the engine enforces per order); `cash left` should be below one minimum economic order (295 €); `months out of band` shows how often drift exceeded ±3% before new cash pulled it back — the engine never sells, so long trends keep a bucket out of band until contributions catch up.

## Performance benchmarks (deterministic engines, this machine)

| engine | seconds | detail |
|---|---:|---|
| parser (1000 rows) | 0.030 | 1000 holdings |
| allocator (1000 random scenarios) | 0.008 | 0.01 ms/scenario |
| backtest (240 months, 3 buckets) | 0.005 | synthetic seeded path |

Median engine call: 0.008 s. All engines are pure Python/pandas; no network in the benchmark rows.
