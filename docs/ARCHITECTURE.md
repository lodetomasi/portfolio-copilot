# Architecture

Broker-agnostic, local-first. Two kinds of input, never mixed up:

- **your holdings** → only from a LOCAL XLSX/CSV export you give the copilot (no broker login, ever);
- **market data** → only from free public sources with no account or API key.

```text
PUBLIC DATA (no signup)             YOUR FILE
Yahoo (yfinance+yahooquery) tier B  broker export XLSX/CSV
SEC EDGAR XBRL/filings tier A               │
ECB eurofxref/rates    tier A               ▼
Eurostat HICP/UNE      tier A     parsers/broker_export.py
Stooq                  tier B               │
Finviz crawler         tier C               ▼
Company IR page        tier A     portfolio/risk.py  (weights, HHI, leverage)
        │                                   │
        ▼                                   ▼
providers/*  (TTL cache + provenance; timeout everywhere except yfinance/finviz, which use their libraries' own defaults)
        │
        ▼
analytics/merge.py   ── tier A overrides tier B, every override recorded ──┐
analytics/evidence.py ── multi-source agreement (VERIFIED/CONFLICT/SINGLE_SOURCE) ┤
        │                                                                  │
        ▼                                                                  ▼
scoring/engine.py  (growth/quality/valuation/momentum/risk → 0-100 + confidence)
        │
        ▼
portfolio/exposure.py   (hidden theme/driver graph, config/exposure_graph.yaml)
portfolio/thesis.py     (falsifiers, save_thesis/check_thesis, STABLE..BROKEN)
portfolio/auction.py    (marginal-utility ranking of buckets + stocks + cash)
portfolio/replacement.py(HOLD/REPLACE/SELL_TO_CASH, fee-aware)
portfolio/rebalance.py  (cash-flow-first waterfall + top-up, fee-aware; sells opt-in)
portfolio/plan.py       (rookie inputs → profile, targets, cadence, calendar)
portfolio/backtest.py   (replay of the plan on past prices — not a forecast)
portfolio/ledger.py     (decision ledger + shadow portfolio → decision alpha)
portfolio/edge.py       (personal edge by category/theme)
portfolio/quality.py    (decision-quality rubric, independent of outcome)
        │
        ▼
server.py  (MCP tools + prompts only)  ──►  skills/  (rookie in → expert → rookie out)
                                              agents/red-team.md (attacks every BUY)
        │
        ▼
SUGGESTED MANUAL ORDERS → the user → their broker
```

## Engine map (reference design vs. what exists)

| Engine (reference design) | Status | Where |
|---|---|---|
| Data layer, zero signup | done: Yahoo (yfinance + yahooquery fallback), SEC XBRL/filings, ECB FX/rates, Eurostat, Stooq, Finviz, IR crawler | `providers/` |
| Evidence layer / source precedence | done: tier A (SEC) overrides tier B (Yahoo) for revenue growth & FCF (`provenance.overrides`); multi-source agreement flag (VERIFIED/CONFLICT/SINGLE_SOURCE/MISSING), a CONFLICT not resolved by a tier-A source is excluded from the score | `analytics/merge.py`, `analytics/evidence.py` |
| Growth / Quality / Valuation / Momentum / Risk engines | done (linear normalisation, missing → excluded, weights renormalised) | `scoring/engine.py` |
| Catalyst / Revisions engines | V2 — no free deterministic source wired; components stay `available: false` | — |
| Insider / Macro engines | done: Form 4/4-A filing-count activity signal (not a buy/sell tally); macro regime from Eurostat HICP + ECB deposit rate | `providers/sec_filings.py`, `providers/macro.py` |
| Stock scoring | done (0-100 + confidence = f(coverage, provider confidence)) | `scoring/engine.py` |
| Thesis engine (falsifiers, strengthening/weakening) | done: claims + quantitative falsifiers, deterministic status (STABLE/STRENGTHENING/WEAKENING/BROKEN/UNVERIFIABLE), no LLM judgement | `portfolio/thesis.py` |
| Portfolio engine | done: weights, top1/3/5, HHI, leveraged nominal & equivalent exposure, hidden-exposure theme/driver graph | `portfolio/risk.py`, `portfolio/exposure.py` |
| Capital allocation ("auction") | done: marginal-utility ranking across underweight buckets, screened stocks (fit + thesis-discounted) and cash, greedy fee-aware allocation | `portfolio/auction.py` |
| Replacement engine (sell only if something is better) | done: utility-based HOLD/REPLACE/SELL_TO_CASH, round-trip fee gated; `rebalance_portfolio`'s drift sells are still opt-in (`allow_sells`) | `portfolio/replacement.py` |
| Red team | done as a read-only plugin agent invoked by skills before any BUY; now also gates on evidence CONFLICT and a BROKEN thesis | `agents/red-team.md` |
| Decision ledger | done (append-only JSONL, local, git-ignored; optional category/theme/thesis_status/cap_eur) | `portfolio/ledger.py` |
| Shadow portfolio / decision alpha | done (real vs recorded alternative, min 90 days, refuses conclusions < 10 decisions) | `portfolio/ledger.py` |
| Personal edge / decision quality | done: mean alpha/hit-rate by category/theme (min-sample gated) and a 0-100 process-quality rubric independent of outcome | `portfolio/edge.py`, `portfolio/quality.py` |
| Discovery (Finviz screener) | done: 3 validated presets, tier C, re-scored before use | `providers/finviz.py` |
| Investment plan + calendar + check-in | done | `portfolio/plan.py`, skill `investment-plan` |
| Backtest of the plan rules | done (monthly replay, synthetic-path property tests) | `portfolio/backtest.py` |

## Source tiers and fallback

```text
tier A  official     SEC EDGAR XBRL/filings, ECB reference rates & deposit facility rate,
                      Eurostat HICP/unemployment, a company's own investor-relations page
tier B  aggregator   Yahoo Finance (yfinance, with yahooquery as fallback), Stooq (price
                      history fallback)
tier C  crawler      Finviz (finvizfinance) — discovery only, never inside a score
```

Rules: A overrides B (recorded); a multi-source CONFLICT not resolved by a tier-A pick is
excluded from the score, never averaged away; C never enters a score. Price history:
yfinance → yahooquery/stooq → report missing. Fundamentals: Yahoo snapshot → SEC facts
override where present → `None` otherwise. Everything fetched carries `source`, `as_of`,
`confidence`, `missing_fields`; SEC calls declare a User-Agent
(`PORTFOLIO_COPILOT_SEC_USER_AGENT`) and are cached 24 h; crawlers hit public pages only,
respecting `robots.txt` (IR page crawler).

## Modules

- `models.py` — Pydantic contracts. `Provenance` carries `tier`, `overrides`, `secondary_sources`.
- `parsers/broker_export.py` — header-row auto-detection (page exports have summary rows first),
  Italian/English column aliases, `4.380,74` decimals, ticker on the first line of the name cell,
  `Totale` row skipped, leverage from `5X` in the name.
- `providers/` — one file per source, `cache.py` TTL cache, every call with timeout except yfinance and finviz (both rely on their underlying library's own default, no explicit `timeout=`; see CLAUDE.md).
- `analytics/metrics.py` — pure math; `analytics/merge.py` — source precedence;
  `analytics/evidence.py` — multi-source agreement (VERIFIED/CONFLICT/SINGLE_SOURCE/MISSING).
- `scoring/engine.py` — pure scoring on normalised snapshots.
- `portfolio/` — `risk`, `exposure`, `thesis`, `auction`, `replacement`, `rebalance`, `plan`,
  `backtest`, `ledger`, `edge`, `quality`, `mapping`, `orders`.
- `server.py` — MCP tools and prompts only.

## Plugin layout (repo root = plugin root)

```text
.claude-plugin/plugin.json, marketplace.json   .mcp.json (one file, project + plugin mode)
skills/<name>/SKILL.md ×7                     agents/red-team.md
hooks/hooks.json, no-broker-access.sh, session-banner.sh
config/portfolio.example.yaml, model_portfolios.yaml, exposure_graph.yaml
data/private/ (git-ignored): investment_plan.json, decisions.jsonl, theses.json
```

## Security boundary

Reads: explicit local files, public web data. Never: broker/bank login, cookies, credentials,
OTP/PIN, order submission. The `PreToolUse` hook denies any tool call that touches an
authentication surface (`/login`, `/auth`, `area-privata`, auth headers, credential strings).

## LLM boundary

Claude interprets intent, chooses tools, explains in ≤ 6 lines, runs the red team. Python
calculates, ranks, allocates, validates, estimates fees, measures decisions. Never ask Claude to
compute a weight or a fee.
