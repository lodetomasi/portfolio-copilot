---
name: position-review
description: >
  For one stock the user already owns: fresh score with Yahoo + SEC data, weight vs size
  cap, trend, drawdown and thesis health, then a plain HOLD / WATCH / REDUCE / SELL with
  one reason — never SELL unless something is actually better. Use whenever the user asks
  about a single holding, "tengo o vendo", "è ancora buona", "position review", or names a
  ticker they own.
argument-hint: "<TICKER> [export-path]"
---

# Position review

Arguments: `$ARGUMENTS` → `$1` ticker (ask if missing), `$2` export path (ask; without
it the weight check is skipped and said so).

## Guardrails (always)

- **No broker access on your export account.** Its holdings come only from the local XLSX/CSV export you give me: I never log into it, never ask for credentials/OTP/PIN, never send orders there — manual only. On your own eToro account (only if configured via `data/private/etoro.env`), I read real positions and can send an order ONLY after you confirm the exact plan token I show you; demo by default, real needs your explicit double confirmation. Market data comes from free public sources (Yahoo, SEC EDGAR, ECB, Finviz) with `source` / `as_of` / `confidence`.
- Every number comes from an MCP tool, never from memory or mental math. Missing data is said, not invented.
- Output is a **manual to-do list** for the user (`execution = MANUAL_ONLY`). `HOLD` / `NO_BUY` / "do nothing" are complete answers.
- Rookie in, expert processing, rookie out: ask at most two plain questions, then answer in **≤ 6 lines**. Details only if the user says **"why"**.

## Do

0. Account: a file path given → export account (manual orders only, nothing else changes). No path and eToro configured → eToro: start every answer with `etoro_account`'s banner. Both available and the request names neither → ask "Which account? (eToro | export file)" — never guess.
1. `parse_portfolio_export(path)` → find the holding by symbol/ISIN/name.
2. `portfolio_risk(path)` → its weight, portfolio concentration, leverage.
3. `analyze_stock(ticker)` → score, confidence, components, `vol_1y`, `max_drawdown_1y`,
   `above_sma200`, `distance_52w_high`, provenance (SEC overrides if any).
4. Compare weight with the category cap from `get_portfolio_config().risk_limits`
   (quality `max_single_stock_weight`, growth `max_growth_stock_weight`, high-risk
   `max_high_risk_stock_weight`). Leveraged certificate → say `value × leverage` exposure.
5. Thesis: no thesis saved for this ticker yet → `save_thesis` with 2-3 claims and 2-3
   quantitative falsifiers derived from step 3's score components (e.g. `revenue_growth <
   0`, `free_cashflow < 0`, `distance_52w_high < -0.3`). Then always `check_thesis(ticker)`
   → report status and delta (new/unchanged/improved/worsened), never re-litigate from memory.
6. P/L is informational only; never the reason to sell or keep.
7. Before suggesting REDUCE or SELL: `propose_replacement(current_symbol=ticker,
   current_value_eur=<its market value>, candidate_tickers=[] or any alternative the user
   names, holdings=<parse_portfolio_export's holdings>)`. Only REDUCE/SELL when it returns
   `REPLACE`/`SELL_TO_CASH`; otherwise `HOLD` — sell only if something is better, else HOLD.
8. For a SELL (or REDUCE): `capital_auction(path, cash_eur=<the sold value_eur>,
   candidate_tickers=[])` shows where the freed cash goes best; its top-ranked bucket is
   `alternative` (the bucket the proceeds go to) and that same bucket's entry in
   `candidates_for_ledger` gives `alternative_price`. `log_decision(symbol=ticker, action,
   reason, score, confidence, price, amount_eur=<sold value_eur>, alternative=<that
   bucket>, alternative_price=<that bucket's price from candidates_for_ledger>,
   candidates=<top 5 of its `candidates_for_ledger`>)`. The sold ticker itself is added to
   the comparison automatically -- do not add it again.

9. Last (eToro account only): `prepare_execution(orders, mode)` → show each line (symbol, EUR, USD), the `token` and every blocker, then ask: "Confirm sending these N orders to eToro DEMO? Reply with the token." Call `execute_plan(plan, token)` only when the user replies with that exact token, then report sent/failed with broker order ids. Real mode also needs `allow_real=True` + `ETORO_ALLOW_REAL=1` (never set them yourself). Export account: no execution step, manual to-do only.

## Answer (≤ 6 lines)

```
<TICKER>: <x%> of portfolio (cap <x%>). Score <nn>/100, confidence <0.xx> (<source(s)>, <as_of>).
Trend: <above/below SMA200>, <x%> from 52-week high. Risk: vol <x%>, worst drawdown <x%>.
Thesis: <STABLE|STRENGTHENING|WEAKENING|BROKEN|UNVERIFIABLE|new> — <one clause>.
Decision: <HOLD | WATCH | REDUCE to <x%> | SELL> — <one reason, from propose_replacement if REDUCE/SELL>.
If selling/reducing: <EUR> order, fee <EUR>, manual on your broker.
Missing data: <fields or none>. Say "why" for the full breakdown.
```
