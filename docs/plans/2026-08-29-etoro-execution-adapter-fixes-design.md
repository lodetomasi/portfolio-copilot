# eToro execution adapter — fix confirmed defects and wire it up

## Context

The eToro execution adapter (`brokers/etoro.py`, `portfolio/execution.py`,
`portfolio/risk_profile.py`, `portfolio/sources.py`, `portfolio/venues.py`) was built
by a multi-agent workflow without a prior design doc. Its own adversarial review pass
(2 lenses, verified 2x per finding) confirmed 20 defects, several high-severity and
money-affecting. Separately, nothing in this adapter is reachable: `server.py` and all
four money-relevant skills (`deploy-cash`, `rebalance`, `position-review`, `start`)
have zero references to eToro. All files are currently untracked in the working tree —
nothing has been committed.

Non-negotiable project rules that bound every fix below (`CLAUDE.md`): never send an
order without the user's explicit per-plan confirmation token; demo is the default
mode; real execution requires both `allow_real=True` and `ETORO_ALLOW_REAL=1`; never
invent missing data (degrade to `None` + say so); offline deterministic tests only
(`httpx.MockTransport`/monkeypatch, never touch real `data/private`).

## Decisions

- **Fix in place, no new abstraction layer.** The interface mismatch between
  `execution.py` and `EToroClient` is a same-file signature/casing fix, not a design
  flaw — a wrapper class would be unjustified indirection (KISS/YAGNI).
- **Three ordered phases in one plan**: Phase 0 (reconcile `CLAUDE.md`/manifest/skill
  text with the already-authorized eToro exception) lands first, then Phase A
  (correctness, findings #1-15), then Phase B (integration, #16-20) — wiring broken
  execution logic, or a manifest that still claims blanket no-order-execution, into a
  live MCP tool would be worse than not wiring it at all.
- **Bias toward refuse/typed-error over silent degradation** for anything touching
  order safety or money amounts (this is stricter than the project's general "degrade,
  never invent" rule, because here silence can mean an unlogged real trade).

## Phase 0 — reconcile the project's constitution with the already-authorized eToro exception

**Why this phase exists.** `CLAUDE.md`'s non-negotiable rules 1/3/10 ("never connect to
a bank/broker", "never send orders — MANUAL_ONLY", "no broker name in code") predate
the eToro adapter and were never updated when the user authorized the exception. Today
`.claude-plugin/plugin.json`'s description, all four money-relevant `SKILL.md` files,
and `tests/test_plugin.py` still assert the *old*, narrower invariant and are green —
they would go **red**, correctly, the moment Phase B wires a real order-sending tool
into the server, because the code would then contradict its own manifest/skill text.
This phase updates the source of truth *first*, as its own reviewed, tested step —
not "on the fly" during the other 20 fixes.

**Authorization.** The user explicitly changed this rule in chat on 2026-08-29
("le cambiamo le regole"), recorded in this project's own persisted memory
(`rookie-expert-rookie-and-no-broker-names.md`, point 6): the copilot may execute on
the user's own eToro account via the eToro Public API v2, credentials supplied by the
user and living only in `data/private/etoro.env`, always demo-first, real execution
behind an explicit double gate, no autonomous or auto-SELL orders, and the export
account (the user's other broker) stays separate and manual-only. This phase is the
implementation of that already-made decision, not a new one.

**Exact changes:**

1. `CLAUDE.md` "Non negoziabile", rules 1, 2, 3, 10 rewritten to:
   - Rule 1: connecting to the **export account** (bank/broker behind the local
     XLSX/CSV) via login/scraping/cookies stays forbidden; market data stays
     public/keyless. **Explicit exception**: the copilot may read (always) and execute
     (gated) on the user's own eToro account via the eToro Public API v2 — direct
     authenticated API calls only, never a web login/cookie/scrape.
   - Rule 2: credentials for the export account stay forbidden to ask/read/store, as
     today. eToro credentials are supplied by the user, live only in
     `data/private/etoro.env` (git-ignored, chmod 600), are never logged and never
     appear in repr/exceptions/tool output.
   - Rule 3: no order is ever sent without the user's explicit confirmation of that
     exact plan (the existing sha256 token). The export account stays `MANUAL_ONLY`
     forever — no automatic execution there, ever. On eToro: demo is the default;
     real execution requires both `allow_real=True` and `ETORO_ALLOW_REAL=1`; no
     autonomous order and no automatic SELL — a SELL is sent only as an explicit line
     of the confirmed plan.
   - Rule 10: no name for the **export account's** broker anywhere in code — unchanged.
     eToro is named explicitly (`brokers/etoro.py`) because it is a first-class,
     user-authorized integration; this carve-out applies to eToro only.
2. `.claude-plugin/plugin.json` `description` updated so it stays truthful once Phase B
   ships, e.g. (implementer may wordsmith, invariant is fixed): *"...no order
   execution on your export account (MANUAL_ONLY); on your own eToro account, orders
   execute only after you confirm that exact plan, demo by default."*
   `tests/test_plugin.py::test_plugin_and_marketplace_manifests_agree`'s assertion
   changes from `"no order execution" in description` to
   `"no order execution on your export account" in description` (still a single
   substring check, still enforces the invariant, now scoped correctly).
3. Each of the four money-relevant `SKILL.md` files (`deploy-cash`, `rebalance`,
   `position-review`, `start`) gets its guardrail paragraph extended, e.g.: *"No
   broker access on your export account: I never log into it, never ask for
   credentials/OTP/PIN, never send orders there — manual only. On your own eToro
   account (only if configured), I read your real positions and can send orders, but
   only demo by default, one plan at a time, only after you confirm the exact token I
   show you; real execution needs your explicit double confirmation."*
   `tests/test_plugin.py::test_every_skill_states_no_broker_access_and_stays_short`
   keeps checking for `"no broker access"` and `"manual"` (both still literally
   present, now scoped to the export account) and gains one more assertion that the
   eToro exception text is present (e.g. `"etoro" in body`) — still `< 120` lines and
   still contains the literal `"≤ 6 lines"` rookie-out contract, which may require
   trimming other narrative in the same file to fit (see Risks).
4. `docs/ARCHITECTURE.md` and `README.md`'s "Perimetro"/"Cosa NON fa" sections get the
   same scoped update (documentation only, no test enforces their wording today).

This phase has its own small test set (updated assertions above) and must be green,
committed via `siae-git-workflow` (feature branch + PR, per this session's established
flow for this repo), **before** Phase A begins — Phase A's fixes touch files whose
behavior Phase 0's rules govern, and Phase B's new tools would otherwise contradict a
manifest/skill text that still says "no order execution" / lacks the eToro carve-out.

## Findings and fixes (most severe first within each phase)

### Phase A — correctness (existing modules, no server.py/skill changes)

1. **[high] `brokers/etoro.py:369`** — 429-retry resends the identical order with a
   fresh idempotency id (double-send risk). Fix: retry-after backoff must reuse the
   *same* `x-request-id`, or refuse to auto-retry write calls at all and surface
   `RateLimited` to the caller instead. Test: MockTransport returns 429 then 200 on a
   write call; assert the id is unchanged across the two attempts (or that no retry
   happens and `RateLimited` propagates).
2. **[medium] `brokers/etoro.py:374`** — ~~user-key header sent as `x-user-key`; the
   project's own live-probed fact says `user-key`. Fix: correct the header name
   constant. Test: assert the exact header name on a captured request.~~
   **REFUTATO (live probe 2026-08-29, demo pnl endpoint):** `x-user-key` → HTTP 200
   (con x-request-id) / 422 RequestIdRequired (senza); `user-key` → 401 Unauthorized.
   L'header corrente `x-user-key` è corretto: nessuna modifica.
3. **[high] `execution.py:420`** — `record_decision()` after a real fill is
   unprotected; re-running `execute()` on an already-sent plan double-sends. Fix:
   `execute()` must check the ledger for an existing record with this plan's token
   before sending each line, and skip (not resend) an already-recorded line.
4. **[medium] `execution.py:349`** — pre-send cash re-check omits estimated fees
   (`build_plan`'s check includes them). Fix: recompute the same fee-inclusive total.
5. **[high] `execution.py:391`** — an order accepted by the broker is reported
   'skipped' (never ledgered) if `wait_for_fill` errors after a successful open/close.
   Fix: on a `wait_for_fill` exception, still attempt to record a `pending`/`unknown`
   ledger entry with the broker order id rather than silently dropping it.
6. **[medium] `execution.py:126`** — `fx_rate_eur_per_ccy=None` raises unhandled
   `TypeError`. Fix: explicit `None`/non-positive guard raising `ValueError`.
7. **[medium] `ledger.py:108`** — duplicate-id guard is a read-then-write race, no file
   lock. Fix: an `fcntl`/`msvcrt`-free portable file lock (e.g. an atomic
   create-exclusive lock file) around the read-check-append sequence.
8. **[medium] `risk_profile.py:82`** — safety checks computed but never consulted by
   any execution path. Fix: `build_plan` must load and consult the stored risk profile
   (leverage rejection, speculative cap) as additional blockers.
9. **[high] `risk_profile.py:217`** — `observed_drawdowns` silently reports 0% for a
   bucket that actually crashed -53% (trusts an already-inner-joined frame). Fix:
   detect and surface the truncation (missing dates) instead of computing on the
   truncated frame.
10. **[medium] `risk_profile.py:190`** — `fits()` verdict text contradicts its own
    booleans when stress drawdown is milder than observed. Fix: derive the text from
    the same comparison the booleans use.
11. **[medium] `sources.py:143`** — silently zeroes `market_value` for a position with
    known quantity but no price. Fix: leave `market_value=None` and flag it.
12. **[high] `sources.py:126`** — expected position schema doesn't match
    `EtoroClient.positions()`'s real output → every real position values at 0.0 EUR.
    Fix: read the actual normalized keys (`instrument_id`, `units`, `open_rate`, ...).
13. **[high] `sources.py:94`** — position direction (`is_buy`) dropped entirely,
    folding a short into the same sign as an equal-size long. Fix: negate quantity (or
    a `side` field) for short positions.
14. **[high] `venues.py:79`** — whole-unit floor uses `amount // price`, losing a unit
    to float error on realistic amounts. Fix: use `math.floor(amount / price + eps)`
    or `Decimal`-based floor.
15. **[high] `sources.py:118`** — `fx_rate_eur_per_ccy` never validated positive,
    unlike `execution.py`'s same-named parameter. Fix: same guard as #6.

### Phase B — integration (server.py + skills)

16. **[high] `server.py`** — eToro execution not wired into the MCP server at all. Fix:
    a module-level `etoro_client()` factory returning an `EToroClient` built from
    `load_credentials()` in the mode from env `ETORO_MODE` (`'demo'` default), or
    `None` when unconfigured (never raises at import). Six new MCP tools:
    - `etoro_account()` / `etoro_positions()` — read-only, each response includes the
      account banner (see #18) and standard provenance (source, as_of, confidence,
      tier='A').
    - `etoro_search_instrument(query: str)` — wraps `EToroClient.search_instruments`.
    - `prepare_execution(orders: list[dict], mode: Literal['demo','real']='demo',
      red_team_by_symbol: dict[str, str] | None = None) -> dict` — assembles account/
      positions from the client, caps from `get_portfolio_config`, fee model, FX from
      `providers/ecb_fx` (USD→EUR, with provenance), calls `execution.build_plan`, and
      returns the `ExecutionPlan` as JSON (lines, checks, blockers, token).
    - `execute_plan(plan: dict, token: str, allow_real: bool = False) -> dict` — calls
      `execution.execute`, returns the sent/failed/skipped/ledger_ids report.
    - `etoro_orders()` — wraps `EToroClient.orders`.
17. **[high] `execution.py:366`** — `execute()`'s expected client interface doesn't
    match `EToroClient`'s real signatures. Fix: call `client.account()["cash_available"]`,
    `client.open_market_order(instrument_id=..., amount=..., side="buy", ...)`,
    `client.wait_for_fill(order_id, kind="open"|"close", position_id=...)`.
18. **[high] skills** — none of `deploy-cash`/`rebalance`/`position-review`/`start`
    implement the eToro-vs-export disambiguation, mode banner, or confirmation-token
    flow. Fix, concretely:
    - `start`: detect the account (a local file path given? else is eToro
      configured?) and state which in the first line.
    - Every answer's first line is the account banner: `"Account: eToro DEMO
      (virtual)"` / `"Account: eToro REAL"` / `"Account: export file <name> (manual
      orders only)"`.
    - `deploy-cash` / `rebalance` / `position-review`: when the account is eToro,
      after the plan/answer, add the execution step — call `prepare_execution`, show
      the lines + token in ≤ 6 lines, ask *"Confirm sending these N orders to eToro
      DEMO? Reply with the token."*, and only after the user replies with the
      matching token call `execute_plan(plan, token)` and report sent/failed with
      broker order ids. For the export account, nothing changes (still manual-only,
      no execution step).
    - When both a local file path and configured eToro credentials are available and
      the request doesn't say which, the skill must ask *"Which account? (eToro |
      export file)"* before sizing — never guess (matches `portfolio/sources.py`'s
      `resolve_source`, already built).
19. **[high] `execution.py:346`** — same interface-mismatch root cause as #17
    (`get_cash_available` doesn't exist). Fixed together with #17.
20. **[high] `execution.py:400`** — case-sensitive `!= "Filled"` vs the client's always-
    lowercase `"filled"`. Fix: `str(status).lower() != "filled"`.

## Testing

Every finding gets a regression test that fails before the fix and passes after
(red-green-refactor via `siae-tdd`). Phase B adds `tests/test_server_etoro.py`
(currently missing, offline, fake client via monkeypatch) and one test that wires the
*real* `EToroClient` through `execution.execute()` via `httpx.MockTransport`
end-to-end, per the original review's own suggested fix — this is the one test that
would have caught #17/#19/#20 together. Final gate: `uv run pytest -q`,
`uv run ruff check .`, `claude plugin validate --strict .`/skills/agents, a live MCP
stdio session (`tools/list` includes the 6 new eToro tools), then a live DEMO smoke
test (account/positions read, one small BUY + close, `orders()`) using the real demo
credentials already in `data/private/etoro.env` — read-only calls first, the one
demo BUY+close last, never REAL mode. If the demo environment is unreachable, the
gate reports the read-only results and marks the smoke test partial rather than
failing the whole gate or silently skipping it (see Risks).

## Acceptance criteria

- All 20 findings have a passing regression test; full suite green; ruff clean.
- `execute()` never double-sends: re-running on an already-sent plan is a no-op for
  the already-sent lines.
- A real short position values with the correct sign; a real position with a known
  price values correctly in EUR (not 0.0).
- `tools/list` over a live MCP stdio session includes the six new eToro tools.
- Live DEMO smoke test: account/positions read, one small BUY + close, all logged to
  the ledger with `broker='etoro'` and the real broker order id.
- No real-money order is ever sent without both `allow_real=True` and
  `ETORO_ALLOW_REAL=1`, verified by a test.
- `CLAUDE.md`, `.claude-plugin/plugin.json`, all four money-relevant `SKILL.md` files
  and `tests/test_plugin.py` are mutually consistent about the eToro exception (Phase
  0) — no manifest/skill text still claims blanket "no order execution" once Phase B
  ships a tool that can send one.

## Risks and mitigations

- **Constitutional conflict** (this design doc's own spec-review BLOCKED on it):
  `CLAUDE.md`/manifest/skill text asserted a blanket no-order-execution invariant that
  Phase B would otherwise silently violate. Mitigation: Phase 0, done and merged
  first, with its own updated tests.
- **Live-demo-environment dependency for the final gate**: the gate's smoke test needs
  eToro's demo API to be reachable. Mitigation: read-only calls run and are reported
  first; if the environment is unreachable, the gate reports a partial result (which
  calls succeeded) rather than failing outright or silently skipping — and it must
  never fall back to REAL mode to compensate.
- **Regression on existing tools reading a new `source='etoro_api'`** (e.g.
  `map_holdings_to_targets`, `portfolio_risk`, `capital_auction`, `save_portfolio_snapshot`
  when called without a file path): mitigation is a dedicated test per tool asserting
  the eToro-sourced `Portfolio` produces the same shape as a file-sourced one, plus the
  existing `resolve_source`/`portfolio_from_etoro` tests already built for `sources.py`
  (finding #12/#13 fix them; new tests confirm the callers consume the corrected shape).
- **Skill line-budget** (`< 120` lines, `≤ 6 lines` answers): adding the eToro
  guardrail sentence and the confirm-with-token step may not fit alongside existing
  narrative in some `SKILL.md` files. Mitigation: trim narrative elsewhere in the same
  file first; only if that is insufficient, flag it back to the user rather than
  silently exceeding the budget or weakening the `< 120`/`≤ 6 lines` tests.
- **Discovery of further defects while writing the Phase A/B regression tests** (this
  code has never run in production): mitigation is the SP buffer below and treating
  any newly-discovered defect the same way as the 20 already confirmed (test first).

## Story points

Phase 0: ~0.5 day (mostly text, 2 file categories of tests to update). Phase A: ~20
small TDD units across 6 files, mostly single-file, ~1-1.5 days. Phase B: 6 new tools +
4 skill updates + 1 new test file + the real-client-through-MockTransport end-to-end
test, ~0.5-1 day. Total human-equivalent: ~2-3 days, with the buffer above for
newly-discovered defects. No JIRA ticket (this repo has no issue tracker in use,
established this session).
