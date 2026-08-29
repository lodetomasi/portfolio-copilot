---
name: investment-plan
description: >
  Turns "I have X now and Y per month, no idea what to buy" into a concrete plan: profile,
  target ETFs to verify, first manual orders, how often to invest so fees stay under 1%, a
  12-month calendar, and a check-in mode that re-evaluates the plan against a fresh export
  plus this user's own track record so far. Use whenever the user asks what to invest in,
  how to start, mentions a monthly amount or PAC, "quanto/cosa investo", "piano",
  "calendario", or wants to re-check an existing plan.
argument-hint: "<cash-now> <monthly> <years> [low|medium|high]  |  checkin <export-path>"
---

# Investment plan

Arguments: `$ARGUMENTS`. Mode **new** when `$1` is a number; mode **checkin** when
`$1` is `checkin` (`$2` = export path).

## Guardrails (always)

- **No broker access.** Your holdings come only from the local XLSX/CSV export you give me. I never log into a bank or broker, never ask for credentials/OTP/PIN, never send orders. Market data comes from free public sources (Yahoo, SEC EDGAR, ECB, Finviz) with `source` / `as_of` / `confidence`.
- Every number comes from an MCP tool, never from memory or mental math. Missing data is said, not invented.
- Output is a **manual to-do list** for the user (`execution = MANUAL_ONLY`). `HOLD` / `NO_BUY` / "do nothing" are complete answers.
- Rookie in, expert processing, rookie out: ask at most two plain questions, then answer in **≤ 6 lines**. Details only if the user says **"why"**.

## Mode: new

Ask only what is missing, in plain words:
1. "How much can you invest today, and how much per month?"
2. "For how many years can you leave it alone?"
3. "If it dropped 30% in a year, would you sell (low), hold (medium) or buy more (high)?"

Then:
1. `get_portfolio_config()` for fees (`fixed_fee_eur`/`variable_fee_pct`/`max_fee_ratio`),
   then `build_investment_plan(cash_now, monthly_contribution, horizon_years, risk_tolerance,
   fixed_fee_eur, variable_fee_pct, max_fee_ratio)`. It returns profile, targets, example
   instruments (`verify_before_use`), initial orders, contribution cadence, calendar, warnings.
2. Optional, only if the user asks "how did this behave in the past": `backtest_plan` with
   the instruments' `yf_ticker` (fallback `price_source="stooq"`). Say it is a replay,
   not a forecast, and report missing buckets.
3. Save the plan JSON to `data/private/investment_plan.json` (Write tool; the folder is
   git-ignored). Add `"created": <today>`, `"history": []`.

Answer (≤ 6 lines):
```
Profile: <name> — <one clause>.
Buy now (manual, on your broker): <ISIN/name> <EUR>, <ISIN/name> <EUR>. Fees ≈ <EUR>. Keep <EUR> in cash.
Then: invest <pooled EUR> every <n> month(s) into the most underweight bucket.
Calendar: next buy <date>, first review <date>, annual review <date>.
Verify the ISINs on your broker first. Say "why" for the reasoning, "check-in" when you have a new export.
```
Include every `warnings` item as one extra line.

## Mode: checkin

1. Read `data/private/investment_plan.json` (if missing: "No plan saved — run the plan first").
2. `parse_portfolio_export(path)`, `portfolio_risk(path)`; map holdings to plan buckets by
   ISIN/name; anything unmapped is listed as "outside the plan".
3. `allocate_cash(current_values, plan.targets, cash_eur=<ask: "cash available now?">,
   rebalance_band_abs=plan.rules.rebalance_band_abs)`.
4. `review_decisions(min_days=90)`; if `decisions_measured >= 1`, also `personal_edge(
   min_days=90)` (overall mean alpha/hit-rate) and `decision_quality(decision_id)` on the
   most recent measured row → fold into one summary line. With 0 measured decisions, omit
   the line entirely — never show a track record on no data.
5. Append `{date, total_value, drift_by_bucket, orders}` to `history` and save.

Answer (≤ 6 lines):
```
As of <today>: portfolio <EUR>, contributions so far <EUR>.
Drift: <bucket +x% / -y%> — <in band | out of band>.
Do now: <BUY <bucket> <EUR> ... | nothing>. Fees ≈ <EUR>.
Outside the plan: <holdings or none>.
Track record: <n> measured decisions, alpha <+x%|-x%>, hit rate <x%>, quality <nn>/100 | not shown yet.
Next: <contribute|review> on <date>.
```
