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
scoring/engine.py  (growth/quality/valuation/momentum/revisions/catalysts/risk → 0-100 + confidence)
        │
        ▼
portfolio/picker.py     (rank by potential across the whole universe; tags, never filters)
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
portfolio/snapshots.py  (one dated holdings snapshot per check-in, for later diffs)
portfolio/opportunity.py(regret vs. the whole ranking shown at decision time)
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
| Catalyst / Revisions engines | done: tier B analyst estimates + event-dated rating changes (yfinance) and Yahoo earnings-surprise history, plus tier A Form 4/8-K event counts (US filers), wired into the snapshot before scoring; direction-agnostic catalysts (events ahead/behind, never good/bad news), thin-coverage (< 3 analysts) shrinks revisions toward neutral 50; `available: false` only when the free provider genuinely has no coverage (pure European local lines, no earnings-calendar history, no SEC CIK) | `server.py::_enrich_snapshot_with_free_data`, `providers/yfinance_estimates.py`, `providers/yfinance_surprises.py` |
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
| Discovery (Finviz screener) | done: 3 validated presets (`mode='preset'`), tier C, re-scored before use; default `mode='universe'` samples every market-cap size bucket × style with NO exclusions -- big and small companies in the same net, size/index overlap are informational tags attached later, never a filter | `providers/finviz.py` (`discover_universe`) |
| Stock picker (potential ranking + tags) | done: ranks the WHOLE scored set by potential (score desc, confidence desc, ticker asc) -- never drops a candidate; attaches `size_bucket`, `sector`/`lane`/`core_overlap_note`/`diversification` as information only. Only the caller's risk caps and the red team ever limit how big a resulting BUY is sized | `portfolio/picker.py` (`rank_by_potential`, `annotate`, `shortlist`), tool `rank_candidates` |
| Picker proxy backtest (disclosed) | done: point-in-time-honest proxy (momentum, earnings-surprise track record, as-filed fundamental YoY growth, event-dated rating momentum) replayed at quarterly rebalance dates against a benchmark; NOT the production scorer. Mandatory disclosures always returned: survivorship bias (today's tickers only), Yahoo backfill risk, no transaction costs, event-dated (not true point-in-time consensus) revisions | `portfolio/picker_backtest.py`, tool `backtest_picker`, `scripts/picker_backtest_report.py` → `docs/PICKER_BACKTEST.md` |
| ISIN → ticker resolution | done: free, keyless OpenFIGI `/v3/mapping` (tier A), rate-limited/cached/chunked; `yf_ticker_for` composes a Yahoo-style ticker for a handful of known exchanges. `portfolio/mapping.py::map_holdings` can take an optional resolver so a satellite holding with an ISIN but no ticker still gets a `resolved_ticker` -- never required, never invents one | `providers/openfigi.py`, tool `resolve_isins` |
| Investment plan + calendar + check-in | done | `portfolio/plan.py`, skill `investment-plan` |
| Backtest of the plan rules | done (monthly replay, synthetic-path property tests) | `portfolio/backtest.py` |
| Snapshot store (monthly holdings memory) | done: one dated snapshot per check-in (holdings, bucket, total_value, plan_targets); `diff_snapshots` reports value change per holding/bucket but never splits it into contributions vs market move on its own | `portfolio/snapshots.py`, tools `save_portfolio_snapshot`/`list_portfolio_snapshots`/`compare_snapshots` |
| Opportunity-cost ledger | done: regret of the chosen decision against the *whole* ranking shown at decision time (`log_decision`'s `candidates`), not just the single recorded alternative; min-sample gated like every other engine here | `portfolio/opportunity.py`, surfaced in `review_decisions`'s `opportunity` section |
| Decision calibration (V2) | not built: would compare this user's stated confidence against realized decision alpha (from `portfolio/ledger.py`) to see if confidence is over/under-calibrated. Prerequisite: enough measured decisions with a recorded `confidence` to bin by confidence level (same min-sample gate as `personal_edge`) | — |
| Portfolio autopsy / attribution (V2) | not built: would decompose a period's `compare_snapshots` change into per-bucket/per-holding contribution using intra-period trades, not just start/end value. Prerequisite: a trade log (buy/sell dates and sizes) between two snapshots, which the ledger does not yet capture for buy sizing beyond `log_decision`'s `amount_eur` | — |

## Source tiers and fallback

```text
tier A  official     SEC EDGAR XBRL/filings/Form 4/8-K, ECB reference rates & deposit
                      facility rate, Eurostat HICP/unemployment, a company's own
                      investor-relations page, OpenFIGI ISIN->ticker mapping (keyless)
tier B  aggregator   Yahoo Finance (yfinance, with yahooquery as fallback), Stooq (price
                      history fallback); yfinance analyst estimates, rating-change events
                      and earnings-surprise history feed revisions/catalysts the same way
tier C  crawler      Finviz (finvizfinance) — discovery only (single preset or the
                      no-exclusion universe sampler across sizes/styles), never inside a score
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
  `backtest`, `ledger`, `edge`, `quality`, `mapping`, `orders`, `snapshots`, `opportunity`,
  `picker` (potential ranking + tags), `picker_backtest` (disclosed proxy backtest).
- `providers/yfinance_estimates.py` / `yfinance_surprises.py` — free analyst-estimate,
  event-dated rating-change and earnings-surprise-history proxies feeding revisions/catalysts.
- `providers/openfigi.py` — free, keyless ISIN → ticker/exchange mapping (tier A).
- `server.py` — MCP tools and prompts only.

## Plugin layout (repo root = plugin root)

```text
.claude-plugin/plugin.json, marketplace.json   .mcp.json (one file, project + plugin mode)
skills/<name>/SKILL.md ×7                     agents/red-team.md
hooks/hooks.json, no-broker-access.sh, session-banner.sh
config/portfolio.example.yaml, model_portfolios.yaml, exposure_graph.yaml
data/private/ (git-ignored): investment_plan.json, decisions.jsonl, theses.json, snapshots/*.json
```

## Security boundary

Reads: explicit local files, public web data. Never on the export account: broker/bank login,
cookies, credentials, OTP/PIN, order submission. The `PreToolUse` hook denies any tool call
that touches an authentication surface (`/login`, `/auth`, `area-privata`, auth headers,
credential strings). Explicit user exception (see CLAUDE.md): the user's own eToro account via
the eToro Public API v2 (`brokers/etoro.py`, keys only in `data/private/etoro.env`) — read
always allowed, an order goes out only through `portfolio/execution.py` after the user confirms
that exact plan's token; demo by default, real mode behind `allow_real=True` +
`ETORO_ALLOW_REAL=1`.

## LLM boundary

Claude interprets intent, chooses tools, explains in ≤ 6 lines, runs the red team. Python
calculates, ranks, allocates, validates, estimates fees, measures decisions. Never ask Claude to
compute a weight or a fee.
