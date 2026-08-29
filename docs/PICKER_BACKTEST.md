# Stock-picker PROXY backtest

Generated 2026-08-29 12:26 UTC by `scripts/picker_backtest_report.py`.

> **Disclosed PROXY, not the production scorer.** This replays a simplified, point-in-time-honest proxy of `scoring/engine.py` -- price momentum, an as-filed fundamental-growth signal, an earnings-surprise track record, and analyst rating-change momentum -- on free data only. It is a REPLAY, not a forecast, and it is not the real V1 scorer (no quality/valuation/catalysts components here). See `portfolio/picker_backtest.py` for exactly what each proxy component measures.

## Disclosures (verbatim from the engine)

- Survivorship bias: the universe is today's tickers, not the historically investable set at each rebalance date -- delisted/acquired/renamed names are absent.
- Yahoo backfill risk: earnings-surprise history can be silently revised by Yahoo after the fact; historical rows reflect Yahoo's current record of that quarter, not a strictly point-in-time snapshot.
- Transaction costs, taxes and slippage are excluded from every forward return.
- revision_momentum is derived from analyst rating-CHANGE events (upgrades/downgrades), not from a true point-in-time analyst-consensus revision feed -- IBES/FactSet/Estimize are paid or account-gated and out of scope for a free provider.
- revision_momentum is shrunk toward neutral below 3 trailing rating-change events, but even at full weight it can rest on very few events for a thinly-covered name -- unlike a market-cap or index filter, this is not a floor on which names can be scored.

## Universe

Benchmark: `ACWI`.

Scored: 60/60 tickers -- AAPL, ABBV, ADBE, ALB, AMT, AMZN, AWK, AXP, BAC, BLK, CAT, CHWY, CMCSA, COST, CRM, CROX, CVS, DE, DECK, DIS, DVN, ETSY, FANG, FIVE, GOOGL, GS, HD, HON, ISRG, JNJ, JPM, LLY, LMT, LULU, META, MRK, MSFT, NEE, NVDA, O, ORCL, PFE, PG, PLD, PLNT, POOL, QCOM, RH, SBUX, SPG, TGT, TMUS, UNH, UPS, V, VZ, WFC, WSM, XOM, YUM.

## Aggregates

| metric | value |
|---|---:|
| rebalance dates attempted | 60 |
| periods with a computable excess return | 60 |
| mean excess return (top quantile equal-weight vs benchmark) | 3.70% |
| hit rate (share of periods beating the benchmark) | 66.67% |
| t-stat of excess return | 3.40 |

## Per-rebalance detail

| date | n scored | n top | n skipped | top return | benchmark return | excess | hit |
|---|---:|---:|---:|---:|---:|---:|---|
| 2011-04-01 | 52 | 10 | 8 | -7.46% | -18.76% | 11.30% | yes |
| 2011-07-01 | 52 | 10 | 8 | -8.75% | -12.80% | 4.05% | yes |
| 2011-10-01 | 52 | 10 | 8 | 22.33% | 22.00% | 0.33% | yes |
| 2012-01-01 | 52 | 10 | 8 | 12.05% | 5.47% | 6.58% | yes |
| 2012-04-01 | 52 | 10 | 8 | -7.10% | 0.83% | -7.92% | no |
| 2012-07-01 | 53 | 11 | 7 | 3.54% | 10.69% | -7.15% | no |
| 2012-10-01 | 54 | 11 | 6 | 3.21% | 8.40% | -5.19% | no |
| 2013-01-01 | 56 | 11 | 4 | 5.42% | 5.99% | -0.57% | no |
| 2013-04-01 | 57 | 11 | 3 | 13.39% | 9.28% | 4.12% | yes |
| 2013-07-01 | 57 | 11 | 3 | 22.62% | 15.46% | 7.16% | yes |
| 2013-10-01 | 57 | 11 | 3 | 14.77% | 8.62% | 6.15% | yes |
| 2014-01-01 | 57 | 11 | 3 | 13.57% | 6.85% | 6.72% | yes |
| 2014-04-01 | 57 | 11 | 3 | 7.14% | 0.65% | 6.49% | yes |
| 2014-07-01 | 57 | 11 | 3 | -0.39% | -2.82% | 2.43% | yes |
| 2014-10-01 | 57 | 11 | 3 | 9.17% | 4.46% | 4.71% | yes |
| 2015-01-01 | 57 | 11 | 3 | 5.43% | 3.44% | 1.99% | yes |
| 2015-04-01 | 57 | 11 | 3 | -0.51% | -9.14% | 8.64% | yes |
| 2015-07-01 | 58 | 12 | 2 | 2.30% | -5.46% | 7.76% | yes |
| 2015-10-01 | 59 | 12 | 1 | 10.12% | 4.97% | 5.15% | yes |
| 2016-01-01 | 59 | 12 | 1 | 11.86% | 2.28% | 9.58% | yes |
| 2016-04-01 | 59 | 12 | 1 | 16.73% | 6.89% | 9.84% | yes |
| 2016-07-01 | 59 | 12 | 1 | 9.44% | 5.98% | 3.46% | yes |
| 2016-10-01 | 59 | 12 | 1 | 15.88% | 8.03% | 7.85% | yes |
| 2017-01-01 | 59 | 12 | 1 | 14.62% | 11.91% | 2.71% | yes |
| 2017-04-01 | 59 | 12 | 1 | 13.62% | 10.00% | 3.62% | yes |
| 2017-07-01 | 59 | 12 | 1 | 23.88% | 11.10% | 12.78% | yes |
| 2017-10-01 | 59 | 12 | 1 | 20.74% | 5.15% | 15.59% | yes |
| 2018-01-01 | 59 | 12 | 1 | 28.69% | -0.25% | 28.94% | yes |
| 2018-04-01 | 59 | 12 | 1 | 32.79% | 5.01% | 27.77% | yes |
| 2018-07-01 | 59 | 12 | 1 | -6.23% | -8.89% | 2.66% | yes |
| 2018-10-01 | 59 | 12 | 1 | 0.20% | -0.96% | 1.16% | yes |
| 2019-01-01 | 59 | 12 | 1 | 24.37% | 17.25% | 7.12% | yes |
| 2019-04-01 | 59 | 12 | 1 | -1.15% | 1.08% | -2.23% | no |
| 2019-07-01 | 60 | 12 | 0 | 4.63% | 7.97% | -3.34% | no |
| 2019-10-01 | 60 | 12 | 0 | -11.63% | -17.12% | 5.48% | yes |
| 2020-01-01 | 60 | 12 | 0 | 7.50% | -5.49% | 12.99% | yes |
| 2020-04-01 | 60 | 12 | 0 | 54.15% | 36.02% | 18.13% | yes |
| 2020-07-01 | 60 | 12 | 0 | 21.96% | 23.10% | -1.14% | no |
| 2020-10-01 | 60 | 12 | 0 | 19.41% | 20.64% | -1.23% | no |
| 2021-01-01 | 60 | 12 | 0 | 16.85% | 12.81% | 4.04% | yes |
| 2021-04-01 | 60 | 12 | 0 | 25.09% | 5.29% | 19.80% | yes |
| 2021-07-01 | 60 | 12 | 0 | 9.27% | 5.19% | 4.09% | yes |
| 2021-10-01 | 60 | 12 | 0 | -7.07% | 0.71% | -7.78% | no |
| 2022-01-01 | 60 | 12 | 0 | -25.09% | -19.39% | -5.69% | no |
| 2022-04-01 | 60 | 12 | 0 | -17.48% | -21.78% | 4.30% | yes |
| 2022-07-01 | 60 | 12 | 0 | 7.47% | 1.25% | 6.22% | yes |
| 2022-10-01 | 60 | 12 | 0 | 20.86% | 18.03% | 2.83% | yes |
| 2023-01-01 | 60 | 12 | 0 | 1.01% | 14.18% | -13.18% | no |
| 2023-04-01 | 60 | 12 | 0 | -4.80% | 2.36% | -7.17% | no |
| 2023-07-01 | 60 | 12 | 0 | 8.05% | 7.09% | 0.96% | yes |
| 2023-10-01 | 60 | 12 | 0 | 37.45% | 20.08% | 17.38% | yes |
| 2024-01-01 | 60 | 12 | 0 | 5.76% | 11.56% | -5.80% | no |
| 2024-04-01 | 60 | 12 | 0 | 8.66% | 9.03% | -0.37% | no |
| 2024-07-01 | 60 | 12 | 0 | 12.32% | 5.28% | 7.05% | yes |
| 2024-10-01 | 60 | 12 | 0 | -1.56% | -0.81% | -0.75% | no |
| 2025-01-01 | 60 | 12 | 0 | 2.14% | 10.23% | -8.09% | no |
| 2025-04-01 | 60 | 12 | 0 | 12.76% | 19.87% | -7.12% | no |
| 2025-07-01 | 60 | 12 | 0 | 10.49% | 11.05% | -0.56% | no |
| 2025-10-01 | 60 | 12 | 0 | -3.04% | 1.41% | -4.45% | no |
| 2026-01-01 | 60 | 12 | 0 | 2.76% | 11.06% | -8.29% | no |

