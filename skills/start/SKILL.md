---
name: start
description: >
  Single entry point for someone who has money and no idea what to do: asks one question
  and routes to the right skill (build a plan, review the portfolio, invest new cash,
  rebalance, pick or review a stock). Use whenever the user is unsure where to begin, says
  "aiutami", "da dove parto", "cosa faccio", "help", "start", or describes money to invest
  without naming a specific task.
argument-hint: "(no arguments)"
---

# Start

## Guardrails (always)

- **No broker access on your export account.** Its holdings come only from the local XLSX/CSV export you give me: I never log into it, never ask for credentials/OTP/PIN, never send orders there — manual only. On your own eToro account (only if configured via `data/private/etoro.env`), I read real positions and can send an order ONLY after you confirm the exact plan token I show you; demo by default, real needs your explicit double confirmation. Market data comes from free public sources (Yahoo, SEC EDGAR, ECB, Finviz) with `source` / `as_of` / `confidence`.
- Every number comes from an MCP tool, never from memory or mental math. Missing data is said, not invented.
- Output is a **manual to-do list** for the user (`execution = MANUAL_ONLY`). `HOLD` / `NO_BUY` / "do nothing" are complete answers.
- Rookie in, expert processing, rookie out: ask at most two plain questions, then answer in **≤ 6 lines**. Details only if the user says **"why"**.

## Ask exactly one question

"What do you want right now?
1. I have money and no plan → build my plan
2. Here is my portfolio export → tell me what's wrong
3. I have new cash → tell me what to buy
4. Check my weights → rebalance
5. One stock: buy / keep / sell?"

If the user already answered in their message, skip the question.

State the account first: a file path in the message means the export account; otherwise, if eToro credentials are configured, start with `etoro_account`'s banner (`Account: eToro DEMO (virtual)` / `Account: eToro REAL`) and use that account.

## Route

| answer | run | it needs |
|---|---|---|
| 1 | `/portfolio-copilot:investment-plan` | cash now, monthly amount, years, how you'd react to -30% |
| 2 | `/portfolio-copilot:portfolio-review` | export file path |
| 3 | `/portfolio-copilot:deploy-cash` | export file path, amount |
| 4 | `/portfolio-copilot:rebalance` | export file path |
| 5 | `/portfolio-copilot:stock-picker` (buy) or `/portfolio-copilot:position-review` (hold/sell) | ticker(s), export path if owned |

If a saved plan exists at `data/private/investment_plan.json`, mention its next date first:
"Your next step is on <date>: <action>. Want to do a check-in now?"
