---
name: deploy-cash
description: >
  Tells a rookie exactly what to buy with new cash (PAC, bonus, transfer) using their LOCAL
  broker export and their targets, ranking every use of the cash — underweight buckets,
  screened candidate stocks, plain cash — by marginal utility. Use whenever the user
  mentions new money, "ho X euro", "dove li metto", "cosa compro con", PAC, or asks to
  invest a specific amount.
argument-hint: "[export-path] [cash-eur] [TICKER,...]"
---

# Deploy cash

Arguments: `$ARGUMENTS` → `$1` export path, `$2` cash EUR, `$3` optional candidate
tickers. Ask only for what is missing: "How much cash, and where is your export file?"

## Guardrails (always)

- **No broker access.** Your holdings come only from the local XLSX/CSV export you give me. I never log into a bank or broker, never ask for credentials/OTP/PIN, never send orders. Market data comes from free public sources (Yahoo, SEC EDGAR, ECB, Finviz) with `source` / `as_of` / `confidence`.
- Every number comes from an MCP tool, never from memory or mental math. Missing data is said, not invented.
- Output is a **manual to-do list** for the user (`execution = MANUAL_ONLY`). `HOLD` / `NO_BUY` / "do nothing" are complete answers.
- Rookie in, expert processing, rookie out: ask at most two plain questions, then answer in **≤ 6 lines**. Details only if the user says **"why"**.

## Do

1. `map_holdings_to_targets(path)` → every holding mapped to a target bucket
   (`get_portfolio_config()`'s targets, matched by ISIN then name); satellite/certificate/
   leveraged positions are listed separately, never dropped from coverage.
2. `capital_auction(path, cash_eur, candidate_tickers)` ranks every use of the cash —
   underweight buckets, each candidate ticker (scored via `analyze_stock`, fit against the
   portfolio's own hidden exposure, discounted if its saved thesis is WEAKENING/BROKEN) and
   plain cash — by marginal utility, then allocates `cash_eur` to the winners one economic
   order at a time. `orders` is what to buy now; `decision: NO_BUY` means keep the cash;
   `ranking` is every candidate's marginal utility, highest first.
3. A stock candidate with `confidence < 0.5` never wins (the auction excludes it outright);
   report it as `WATCH`/`NO_BUY` with the reason from `reasons`, not as a funded order.
4. Before presenting any stock order as `BUY_SMALL`, invoke the `red-team` agent (Task
   tool) with its score/confidence, provenance and portfolio-risk numbers. `rejected` →
   downgrade to `WATCH`/`NO_BUY` and give the red team's reason instead. Never called for
   bucket-only orders or for `WATCH`/`NO_BUY`.
5. `log_decision(symbol, action, reason, score, confidence, amount_eur, red_team=<verdict>,
   category=<the bucket it fills, or the stock's dominant exposure theme>, candidates=
   capital_auction's `candidates_for_ledger` top 5 by utility)` for every funded order, so
   `personal_edge` groups by bucket/theme and `review_decisions`'s `opportunity` section can
   later measure regret against everything else the auction was ranking.

## Answer (≤ 6 lines)

```
Buy now (manual): <symbol> <EUR> (fee <EUR>), <symbol> <EUR> (fee <EUR>).
Keep in cash: <EUR> — <top reason from capital_auction.reasons, or "everything cleared">.
Candidates not funded: <TICKER: BUY_SMALL <EUR> | WATCH | NO_BUY — reason> | none asked.
After this: <bucket> <x%> vs target <x%>, all within ±<band>.
Next: <date from plan | "re-run when the next cash arrives">.
```
On "why": list the top-3 marginal utilities from `ranking` (symbol, utility) plus every
skipped candidate's reason from `capital_auction.reasons`.
