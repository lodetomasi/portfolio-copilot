# Implementation plan for Claude Code

## Phase 0 — Verify scaffold

1. `uv sync`
2. `uv run pytest`
3. `uv run ruff check .`
4. start MCP inspector:
   `uv run mcp dev src/portfolio_copilot/server.py`

Fix SDK compatibility before adding features.

## Phase 1 — il broker parser

- obtain one sanitized broker export from user;
- add fixture in `tests/fixtures/` with synthetic/anonymized data;
- map real column names;
- preserve generic mapping fallback;
- test decimals with comma and thousands separators;
- test EUR/USD assets;
- test missing ISIN/ticker.

Definition of done:
- parsed rows match expected quantities and market values.

## Phase 2 — Market provider

Harden yfinance adapter:
- retries;
- timeouts where possible;
- normalize `None`/NaN;
- no provider-specific keys outside adapter;
- provenance.

Add integration tests marked `@pytest.mark.network`, disabled by default.

## Phase 3 — Stock analysis

Implement:
- market snapshot;
- 1/3/6/12m momentum;
- quality/growth/valuation fields;
- risk diagnostics;
- composite score with coverage/confidence.

Tests must use synthetic normalized inputs.

## Phase 4 — Stock screener

Input:
- explicit tickers initially;
- later add universe loaders.

Return:
- ranking;
- category;
- score;
- confidence;
- reason codes.

Do not screen the entire global market in V1.

## Phase 5 — Portfolio risk

- weights;
- top concentration;
- sector exposure when available;
- leveraged nominal + equivalent exposure;
- optional historical covariance.

## Phase 6 — Rebalancing

- validate target sum;
- cash-flow-first;
- bands;
- max position;
- minimum economic order;
- fee-aware rounding.

Property tests recommended:
- no negative cash;
- no order > available capital;
- target errors fail loudly.

## Phase 7 — MCP UX

Expose tools + prompts.
Prompts should orchestrate tools rather than contain hidden arithmetic.

## Phase 8 — Optional dashboard

Only after MCP is stable:
- Streamlit;
- upload broker export;
- portfolio dashboard;
- stock picker;
- deploy cash;
- orders table.

## Backlog V2

- SEC EDGAR filing summaries;
- earnings calendar;
- analyst estimate revisions from a free/reliable source if available;
- Black-Litterman / HRP;
- tax-lot aware planning;
- multi-currency FX provider;
- backtesting with transaction costs;
- persistent SQLite cache;
- alerts.
