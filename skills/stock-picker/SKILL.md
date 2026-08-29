---
name: stock-picker
description: >
  Finds and ranks stock ideas for a rookie: with no tickers it runs a Finviz discovery
  screen (public, no account), then re-scores every candidate 0-100 with Yahoo + audited SEC
  data, checks the top idea's filings and portfolio fit, and red-teams it before saying
  BUY_SMALL / WATCH / NO_BUY. Use whenever the user asks what stock to buy, "che azioni
  compro", "cercami opportunità", "ranka", or names tickers to compare.
argument-hint: "[TICKER,...] [export-path] [preset: quality_growth|quality_value|momentum]"
---

# Stock picker

Arguments: `$ARGUMENTS` → optional tickers, optional export path, optional preset.
With no tickers ask one thing: "Steady companies (quality_growth), cheap ones
(quality_value) or what is going up (momentum)?" Default `quality_growth`.

## Guardrails (always)

- **No broker access.** Your holdings come only from the local XLSX/CSV export you give me. I never log into a bank or broker, never ask for credentials/OTP/PIN, never send orders. Market data comes from free public sources (Yahoo, SEC EDGAR, ECB, Finviz) with `source` / `as_of` / `confidence`.
- Every number comes from an MCP tool, never from memory or mental math. Missing data is said, not invented.
- Output is a **manual to-do list** for the user (`execution = MANUAL_ONLY`). `HOLD` / `NO_BUY` / "do nothing" are complete answers.
- Rookie in, expert processing, rookie out: ask at most two plain questions, then answer in **≤ 6 lines**. Details only if the user says **"why"**.

## Do

1. No tickers → `discover_stocks(preset, limit=40)` (tier C, discovery only). If
   `ok: false`, say Finviz is unavailable and ask for tickers.
2. `screen_stocks(tickers, min_score=60)` on the candidates → ranked; failed tickers are
   reported, not dropped.
3. Top 5 → `analyze_stock(ticker)` (Yahoo tier B + SEC tier A overrides; read
   `provenance.overrides`, `as_of`, `missing_fields`, and `evidence` for any metric flagged
   `CONFLICT`).
4. With an export: `portfolio_risk(path)` → existing weight, sector, speculative bucket,
   leverage, minimum economic order. Caps from `get_portfolio_config().risk_limits`:
   quality `max_single_stock_weight`, growth `max_growth_stock_weight`, high-risk
   `max_high_risk_stock_weight`. Also `portfolio_exposure(path)` → flag if the top idea's
   sector/theme already sits inside a large existing driver — a good score is not
   automatically a good addition. Also `capital_auction(path, cash_eur=0,
   candidate_tickers=<the top 5>)` → its `candidates_for_ledger` (ranking + prices), kept
   only for `log_decision` below, never to size an order (that stays `deploy-cash`'s job).
5. For the **top idea only**: `filing_sections(ticker, form="10-K", items=["1A","7"])`
   (Risk Factors + MD&A) and `insider_activity(ticker, days=90)` → what management claims
   vs. what the numbers/insider filings actually show, **2 lines max**.
   `investor_relations_links(ticker)` is optional, only if the user wants the source pages.
6. `confidence < 0.5` → at most `WATCH`. High score alone is never `BUY`.
7. Before presenting any candidate as `BUY_SMALL`, invoke the `red-team` agent (Task tool)
   with its score/confidence, provenance, evidence conflicts and portfolio-risk numbers.
   `rejected` → downgrade to `WATCH`/`NO_BUY` and give the red team's reason instead. Never
   called for `WATCH`/`NO_BUY`.
8. `log_decision(symbol, action, reason, score, confidence, red_team=<verdict>,
   alternative=<the portfolio's core bucket ETF>, category=<preset or sector>, candidates=
   <top 5 of step 4's `candidates_for_ledger`, when an export was given>)` for every
   `BUY_SMALL` — the alternative is always "buy more of the core" so `review_decisions`/
   `personal_edge`/its `opportunity` section can measure the pick against the index and
   everything else that was ranked.

## Answer (≤ 6 lines + one line per idea, max 3 ideas)

```
Screened <n> candidates (<preset>, Finviz <as_of>), scored <n> with Yahoo/SEC.
1. <TICKER> <score>/100, conf <0.xx> — <category> — <action> <max EUR> — <reason>; filings: <mgmt claim> vs <numbers/insiders>.
2. ...
3. ...
Everything else: NO_BUY / WATCH. Scores describe quality and price, not future returns.
Say "why <TICKER>" for the component breakdown, exposure fit and sources.
```
