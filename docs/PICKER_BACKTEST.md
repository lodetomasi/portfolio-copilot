# Stock-picker PROXY backtest

Generated 2026-08-29 11:57 UTC by `scripts/picker_backtest_report.py`.

> **Disclosed PROXY, not the production scorer.** This replays a simplified, point-in-time-honest proxy of `scoring/engine.py` -- price momentum, an as-filed fundamental-growth signal, an earnings-surprise track record, and analyst rating-change momentum -- on free data only. It is a REPLAY, not a forecast, and it is not the real V1 scorer (no quality/valuation/catalysts components here). See `portfolio/picker_backtest.py` for exactly what each proxy component measures.

## Disclosures (verbatim from the engine)

- Survivorship bias: the universe is today's tickers, not the historically investable set at each rebalance date -- delisted/acquired/renamed names are absent.
- Yahoo backfill risk: earnings-surprise history can be silently revised by Yahoo after the fact; historical rows reflect Yahoo's current record of that quarter, not a strictly point-in-time snapshot.
- Transaction costs, taxes and slippage are excluded from every forward return.
- revision_momentum is derived from analyst rating-CHANGE events (upgrades/downgrades), not from a true point-in-time analyst-consensus revision feed -- IBES/FactSet/Estimize are paid or account-gated and out of scope for a free provider.
- revision_momentum is shrunk toward neutral below 3 trailing rating-change events, but even at full weight it can rest on very few events for a thinly-covered name -- unlike a market-cap or index filter, this is not a floor on which names can be scored.

## Universe

Benchmark: `VWCE.MI`.

Scored: 20/20 tickers -- AAPL, AMZN, CAT, COST, CROX, DE, ETSY, GOOGL, HD, JNJ, JPM, LULU, META, MSFT, NVDA, PG, PLNT, UNH, V, XOM.

## Aggregates

| metric | value |
|---|---:|
| rebalance dates attempted | 20 |
| periods with a computable excess return | 20 |
| mean excess return (top quantile equal-weight vs benchmark) | 1.33% |
| hit rate (share of periods beating the benchmark) | 50.00% |
| t-stat of excess return | 0.39 |

## Per-rebalance detail

| date | n scored | n top | n skipped | top return | benchmark return | excess | hit |
|---|---:|---:|---:|---:|---:|---:|---|
| 2021-04-01 | 20 | 4 | 0 | 28.28% | 6.35% | 21.93% | yes |
| 2021-07-01 | 20 | 4 | 0 | 12.39% | 10.78% | 1.61% | yes |
| 2021-10-01 | 20 | 4 | 0 | -11.98% | 6.11% | -18.08% | no |
| 2022-01-01 | 20 | 4 | 0 | -27.20% | -13.59% | -13.61% | no |
| 2022-04-01 | 20 | 4 | 0 | -14.28% | -9.97% | -4.31% | no |
| 2022-07-01 | 20 | 4 | 0 | 7.68% | -0.26% | 7.94% | yes |
| 2022-10-01 | 20 | 4 | 0 | 38.96% | 4.34% | 34.62% | yes |
| 2023-01-01 | 20 | 4 | 0 | 3.94% | 11.62% | -7.68% | no |
| 2023-04-01 | 20 | 4 | 0 | -7.48% | 6.10% | -13.58% | no |
| 2023-07-01 | 20 | 4 | 0 | 18.28% | 5.62% | 12.66% | yes |
| 2023-10-01 | 20 | 4 | 0 | 40.92% | 16.97% | 23.95% | yes |
| 2024-01-01 | 20 | 4 | 0 | -9.71% | 14.92% | -24.63% | no |
| 2024-04-01 | 20 | 4 | 0 | 10.16% | 6.05% | 4.12% | yes |
| 2024-07-01 | 20 | 4 | 0 | 4.11% | 9.06% | -4.95% | no |
| 2024-10-01 | 20 | 4 | 0 | -0.56% | 1.75% | -2.32% | no |
| 2025-01-01 | 20 | 4 | 0 | 5.96% | -3.01% | 8.97% | yes |
| 2025-04-01 | 20 | 4 | 0 | 16.77% | 10.10% | 6.67% | yes |
| 2025-07-01 | 20 | 4 | 0 | 25.97% | 12.22% | 13.75% | yes |
| 2025-10-01 | 20 | 4 | 0 | -8.07% | 3.11% | -11.18% | no |
| 2026-01-01 | 20 | 4 | 0 | 4.83% | 14.09% | -9.26% | no |

