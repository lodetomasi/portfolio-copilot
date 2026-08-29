---
name: portfolio-review
description: >
  Reads a LOCAL broker export (XLSX/CSV) and tells a rookie, in a few lines, what is wrong
  with the portfolio: concentration, leverage, redundant funds, hidden shared exposure,
  positions to watch. Use whenever the user shares or mentions their portfolio file, asks
  "cosa non torna", "review", "dove sono concentrato", "quanta leva ho", or asks how their
  portfolio looks.
argument-hint: "[export-path] [base-currency]"
---

# Portfolio review

Arguments: `$ARGUMENTS` → `$1` export path, `$2` base currency (default EUR).
If no path: "Drop your broker export here (XLSX/CSV) or give me its path."

## Guardrails (always)

- **No broker access.** Your holdings come only from the local XLSX/CSV export you give me. I never log into a bank or broker, never ask for credentials/OTP/PIN, never send orders. Market data comes from free public sources (Yahoo, SEC EDGAR, ECB, Finviz) with `source` / `as_of` / `confidence`.
- Every number comes from an MCP tool, never from memory or mental math. Missing data is said, not invented.
- Output is a **manual to-do list** for the user (`execution = MANUAL_ONLY`). `HOLD` / `NO_BUY` / "do nothing" are complete answers.
- Rookie in, expert processing, rookie out: ask at most two plain questions, then answer in **≤ 6 lines**. Details only if the user says **"why"**.

## Do

1. `parse_portfolio_export(path, base_currency)`. On a column-mapping error, show the
   detected columns and ask how to map them.
2. `portfolio_risk(path, base_currency)` → weights, `concentration` (top1/3/5, HHI),
   leveraged nominal and equivalent exposure.
3. `portfolio_exposure(path, base_currency)` → hidden theme/driver rollup: two
   sector-unrelated holdings can lean on the same driver (e.g. "AI compute"). Report only
   the single largest driver weight; skip the line if nothing stands out.
4. For USD holdings, `fx_rates` only if you need to explain a currency effect.
5. Bucket by parser fields only: **core** (broad ETFs), **satellite** (single stocks,
   thematic ETFs), **leveraged** (`leverage > 1`). Compare with `risk_limits` from
   `get_portfolio_config()` (`is_example: true` → say these are the shipped defaults, not
   the user's own limits).
6. Only if the user asks **"why"**: `macro_snapshot()` for one line on the regime
   (restrictive/neutral/accommodative/unknown, Eurostat HICP + ECB deposit rate) — never in
   the default answer, it explains context, not this portfolio's numbers.

## Answer (≤ 6 lines)

```
Total <EUR>, <n> positions. Core <x%> / satellite <x%> / leveraged <x%>.
Biggest risk: <one sentence, with the number — e.g. "79% in one ETF (fine if that is your core)">.
Hidden exposure: <largest shared driver> <x%> across unrelated holdings | none notable.
Leverage: <EUR> nominal = <EUR> equivalent exposure (indicative, not a VaR) | none.
Watch: <positions with a reason> | nothing.
Do now: <one action or "nothing — HOLD everything">.
Missing data: <fields or none>. Say "why" for the full table and macro regime.
```
