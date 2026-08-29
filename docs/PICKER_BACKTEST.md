# Stock-picker PROXY backtest

Generated 2026-08-29 12:20 UTC by `scripts/picker_backtest_report.py`.

> **Disclosed PROXY, not the production scorer.** This replays a simplified, point-in-time-honest proxy of `scoring/engine.py` -- price momentum, an as-filed fundamental-growth signal, an earnings-surprise track record, and analyst rating-change momentum -- on free data only. It is a REPLAY, not a forecast, and it is not the real V1 scorer (no quality/valuation/catalysts components here). See `portfolio/picker_backtest.py` for exactly what each proxy component measures.

## Disclosures (verbatim from the engine)

- Survivorship bias: the universe is today's tickers, not the historically investable set at each rebalance date -- delisted/acquired/renamed names are absent.
- Yahoo backfill risk: earnings-surprise history can be silently revised by Yahoo after the fact; historical rows reflect Yahoo's current record of that quarter, not a strictly point-in-time snapshot.
- Transaction costs, taxes and slippage are excluded from every forward return.
- revision_momentum is derived from analyst rating-CHANGE events (upgrades/downgrades), not from a true point-in-time analyst-consensus revision feed -- IBES/FactSet/Estimize are paid or account-gated and out of scope for a free provider.
- revision_momentum is shrunk toward neutral below 3 trailing rating-change events, but even at full weight it can rest on very few events for a thinly-covered name -- unlike a market-cap or index filter, this is not a floor on which names can be scored.

## Universe

Benchmark: `VWCE.MI`.

Scored: 40/40 tickers -- AAPL, ABBV, ALB, AMZN, AWK, CAT, CHWY, COST, CROX, CVS, DE, DECK, DVN, ETSY, FANG, FIVE, GOOGL, GS, HD, HON, JNJ, JPM, LMT, LULU, META, MSFT, NEE, NVDA, PG, PLNT, POOL, RH, SBUX, TGT, UNH, UPS, V, WSM, XOM, YUM.
Note: 8 of 32 attempted rebalance dates predate `VWCE.MI`'s own price history -- no benchmark forward return is computable for them, so they are excluded from the aggregates below (but still show the picker's own top-quantile return in the detail table).

## Aggregates

| metric | value |
|---|---:|
| rebalance dates attempted | 32 |
| periods with a computable excess return | 24 |
| mean excess return (top quantile equal-weight vs benchmark) | 4.92% |
| hit rate (share of periods beating the benchmark) | 62.50% |
| t-stat of excess return | 1.76 |

## Per-rebalance detail

| date | n scored | n top | n skipped | top return | benchmark return | excess | hit |
|---|---:|---:|---:|---:|---:|---:|---|
| 2018-04-01 | 39 | 8 | 1 | 37.56% | n/a | n/a | n/a |
| 2018-07-01 | 39 | 8 | 1 | -7.82% | n/a | n/a | n/a |
| 2018-10-01 | 39 | 8 | 1 | 2.59% | n/a | n/a | n/a |
| 2019-01-01 | 39 | 8 | 1 | 24.94% | n/a | n/a | n/a |
| 2019-04-01 | 39 | 8 | 1 | -0.51% | n/a | n/a | n/a |
| 2019-07-01 | 40 | 8 | 0 | 6.23% | n/a | n/a | n/a |
| 2019-10-01 | 40 | 8 | 0 | -23.50% | n/a | n/a | n/a |
| 2020-01-01 | 40 | 8 | 0 | 11.56% | n/a | n/a | n/a |
| 2020-04-01 | 40 | 8 | 0 | 66.76% | 24.74% | 42.02% | yes |
| 2020-07-01 | 40 | 8 | 0 | 27.66% | 13.45% | 14.21% | yes |
| 2020-10-01 | 40 | 8 | 0 | 28.54% | 20.17% | 8.37% | yes |
| 2021-01-01 | 40 | 8 | 0 | 20.63% | 16.39% | 4.24% | yes |
| 2021-04-01 | 40 | 8 | 0 | 24.28% | 6.35% | 17.93% | yes |
| 2021-07-01 | 40 | 8 | 0 | 14.32% | 10.78% | 3.55% | yes |
| 2021-10-01 | 40 | 8 | 0 | 0.49% | 6.11% | -5.61% | no |
| 2022-01-01 | 40 | 8 | 0 | -26.56% | -13.59% | -12.97% | no |
| 2022-04-01 | 40 | 8 | 0 | -13.76% | -9.97% | -3.79% | no |
| 2022-07-01 | 40 | 8 | 0 | 8.09% | -0.26% | 8.35% | yes |
| 2022-10-01 | 40 | 8 | 0 | 31.00% | 4.34% | 26.66% | yes |
| 2023-01-01 | 40 | 8 | 0 | 4.18% | 11.62% | -7.44% | no |
| 2023-04-01 | 40 | 8 | 0 | -5.53% | 6.10% | -11.63% | no |
| 2023-07-01 | 40 | 8 | 0 | 11.66% | 5.62% | 6.04% | yes |
| 2023-10-01 | 40 | 8 | 0 | 49.11% | 16.97% | 32.14% | yes |
| 2024-01-01 | 40 | 8 | 0 | 12.24% | 14.92% | -2.68% | no |
| 2024-04-01 | 40 | 8 | 0 | 10.21% | 6.05% | 4.16% | yes |
| 2024-07-01 | 40 | 8 | 0 | 12.75% | 9.06% | 3.69% | yes |
| 2024-10-01 | 40 | 8 | 0 | -6.78% | 1.75% | -8.53% | no |
| 2025-01-01 | 40 | 8 | 0 | 1.51% | -3.01% | 4.52% | yes |
| 2025-04-01 | 40 | 8 | 0 | 15.86% | 10.10% | 5.76% | yes |
| 2025-07-01 | 40 | 8 | 0 | 13.63% | 12.22% | 1.40% | yes |
| 2025-10-01 | 40 | 8 | 0 | -0.94% | 3.11% | -4.05% | no |
| 2026-01-01 | 40 | 8 | 0 | 5.83% | 14.09% | -8.27% | no |

