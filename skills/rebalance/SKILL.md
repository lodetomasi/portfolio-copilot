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

- **No broker access on your export account.** Its holdings come only from the local XLSX/CSV export you give me: I never log into it, never ask for credentials/OTP/PIN, never send orders there — manual only. On your own eToro account (only if configured via `data/private/etoro.env`), I read real positions and can send an order ONLY after you confirm the exact plan token I show you; demo by default, real needs your explicit double confirmation. Market data comes from free public sources (Yahoo, SEC EDGAR, ECB, Finviz) with `source` / `as_of` / `confidence`.
- Every number comes from an MCP tool, never from memory or mental math. Missing data is said, not invented.
- Output is a **manual to-do list** for the user (`execution = MANUAL_ONLY`). `HOLD` / `NO_BUY` / "do nothing" are complete answers.
- Rookie in, expert processing, rookie out: ask at most two plain questions, then answer in **≤ 6 lines**. Details only if the user says **"why"**.

## Do

0. Account: a file path given → export account (manual orders only, nothing else changes). No path and eToro configured → eToro: start every answer with `etoro_account`'s banner. Both available and the request names neither → ask "Which account? (eToro | export file)" — never guess.
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

6. Last (eToro account only): `prepare_execution(orders, mode)` → show each line (symbol, EUR, USD), the `token` and every blocker, then ask: "Confirm sending these N orders to eToro DEMO? Reply with the token." Call `execute_plan(plan, token)` only when the user replies with that exact token, then report sent/failed with broker order ids. Real mode also needs `allow_real=True` + `ETORO_ALLOW_REAL=1` (never set them yourself). Export account: no execution step, manual to-do only.

## Answer (≤ 6 lines)

```
Status: <all within ±3% → NO ACTION | out of band: <bucket +x%>, <bucket -y%>>.
Do now: <BUY <bucket> <EUR> (fee <EUR>) | nothing>.
Sells: <SELL <bucket> <EUR> (fee <EUR>) — reason | none (allow_sells=false, <n> suppressed) | none needed>.
Cost: <EUR> total, <x%> turnover.
Cash left: <EUR>.
Next check: <date from plan | in 3 months>.
```
