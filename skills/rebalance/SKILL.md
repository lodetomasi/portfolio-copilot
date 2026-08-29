---
name: rebalance
description: >
  Checks a LOCAL broker export against target weights and tells a rookie whether to do
  nothing, buy the underweight bucket with cash, or (rarely) sell — fee-aware and
  cash-flow-first. Use whenever the user asks to rebalance, "ribilancia", "sono fuori
  banda", "riporta ai target", or asks if they should sell something to fix weights.
argument-hint: "[export-path] [cash-eur]"
---

# Rebalance

Arguments: `$ARGUMENTS` → `$1` export path, `$2` cash EUR (default 0).
Ask only for the export path if missing.

## Guardrails (always)

- **No broker access.** Your holdings come only from the local XLSX/CSV export you give me. I never log into a bank or broker, never ask for credentials/OTP/PIN, never send orders. Market data comes from free public sources (Yahoo, SEC EDGAR, ECB, Finviz) with `source` / `as_of` / `confidence`.
- Every number comes from an MCP tool, never from memory or mental math. Missing data is said, not invented.
- Output is a **manual to-do list** for the user (`execution = MANUAL_ONLY`). `HOLD` / `NO_BUY` / "do nothing" are complete answers.
- Rookie in, expert processing, rookie out: ask at most two plain questions, then answer in **≤ 6 lines**. Details only if the user says **"why"**.

## Do

1. `parse_portfolio_export(path)` + `portfolio_risk(path)`.
2. Targets and `rebalancing.band_abs` / `min_cash_eur`: saved plan → `get_portfolio_config()`
   → ask. Targets must sum to 1.0; if a tool raises, report it verbatim. `allow_sells`
   comes from `get_portfolio_config().rebalancing.allow_sells` (default `false`) — pass it
   straight through, never decide it yourself.
3. `rebalance_portfolio(current_values, targets, cash_eur, fixed_fee_eur, variable_fee_pct,
   max_fee_ratio, rebalance_band_abs, allow_sells)` → BUY orders funded by cash (V1's only
   engine-generated orders). When `allow_sells=true` and a bucket is still beyond the band
   after cash, `sell_proposals` lists it with its fee; with `allow_sells=false` a `warnings`
   entry says how many drift sells were suppressed instead of silently dropping them.
4. Show `sell_proposals` only when non-empty. Never invent or "tidy up" a sell yourself.
5. Everything in band, no cash and no `sell_proposals` → **NO ACTION**.

## Answer (≤ 6 lines)

```
Status: <all within ±3% → NO ACTION | out of band: <bucket +x%>, <bucket -y%>>.
Do now: <BUY <bucket> <EUR> (fee <EUR>) | nothing>.
Sells: <SELL <bucket> <EUR> (fee <EUR>) — reason | none (allow_sells=false, <n> suppressed) | none needed>.
Cost: <EUR> total, <x%> turnover.
Cash left: <EUR>.
Next check: <date from plan | in 3 months>.
```
