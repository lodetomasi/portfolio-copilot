# Task 10 — Phase B: 6 tool MCP eToro in server.py (design finding #16)

Prima di modificare, rileggere la coda di `server.py` da disco (lavoro parallelo).

## File
- `src/portfolio_copilot/server.py`
- `tests/test_server_etoro.py` (nuovo, offline)

## Modifiche a server.py
1. Import: `from portfolio_copilot.brokers.etoro import EToroClient, load_credentials`,
   `from portfolio_copilot.portfolio import execution as execution_module`,
   `from portfolio_copilot.portfolio.risk_profile import load_risk_profile`,
   `from portfolio_copilot.portfolio.sources import account_banner`.
2. Factory a livello modulo (mai errori a import time):
   ```python
   _etoro_clients: dict[str, EToroClient] = {}

   def _etoro_client(mode: str | None = None) -> EToroClient | None:
       resolved = (mode or os.environ.get("ETORO_MODE") or "demo").strip().lower()
       if resolved not in ("demo", "real"):
           raise ValueError(f"ETORO_MODE must be 'demo' or 'real', got {resolved!r}")
       creds = load_credentials()
       if creds is None:
           return None
       if resolved not in _etoro_clients:
           _etoro_clients[resolved] = EToroClient(creds, mode=resolved)
       return _etoro_clients[resolved]
   ```
   La cache per modo preserva rate-limiter e cache strumenti tra i tool call.
3. Helper `_etoro_unconfigured() -> dict`: `{"ok": False, "error": "eToro is not
   configured: set ETORO_API_KEY / ETORO_USER_KEY or data/private/etoro.env"}`.
4. Sei tool `@mcp.tool()` (tutti: client None → `_etoro_unconfigured()`; ogni risposta
   include `banner: account_banner("etoro", mode=client.mode)`):
   - `etoro_account() -> dict`: `client.account()` + banner.
   - `etoro_positions() -> dict`: `client.positions()`; per ogni posizione con
     `symbol is None` e `instrument_id` noto chiama `client.instrument(iid)` (una volta
     per id distinto, cache del client) e riempie `symbol`/`name` nel dict ritornato;
     un errore di lookup lascia `None` (mai inventare) e finisce in `lookup_errors`.
   - `etoro_orders() -> dict`: `client.orders()` + banner.
   - `etoro_search_instrument(query: str) -> dict`: `client.search_instruments(query)`
     + banner (come tutti gli altri).
   - `prepare_execution(orders: list[dict], mode: str = "demo",
     red_team_by_symbol: dict[str, str] | None = None) -> dict`:
     a. `client = _etoro_client(mode)`; None → `_etoro_unconfigured()`;
        account = `client.account()`;
        positions raw = `client.positions()["positions"]` mappate per build_plan in
        `{"symbol", "amount": (amount + pnl se entrambi presenti, altrimenti amount),
        "is_stock": True}` — assunzione dichiarata NELLA DOCSTRING del tool: sul conto
        eToro ogni posizione conta come single stock ai fini del cap speculativo.
     b. Per ogni ordine buy senza `min_position_exposure` e con `instrument_id`:
        `client.eligibility(instrument_id)` → riempie `min_position_exposure`; un
        errore lascia `None` (il blocker di build_plan scatta, mai inventare).
     c. `caps`: da `_load_portfolio_config()`: `max_single_stock_weight` via
        `_stock_cap_weight(cfg)` (helper reale, server.py:112), `max_sector_weight` da
        `cfg.get("risk_limits", {}).get("max_sector_weight")`.
     d. `fee_model = FeeModel(fixed_fee_eur=0.0, variable_fee_pct=0.0)` (eToro: zero
        commissioni su stock/ETF real, `minimum_economic_order` 0 — il minimo vero è
        l'eligibility; commento con riferimento a `portfolio/venues.py::ETORO`).
     e. FX: `_fx_rates_or_none()`; `usd_per_eur = rates["rates"].get("USD")`;
        `fx_rate_eur_per_ccy = 1.0 / usd_per_eur`; rates None o USD mancante →
        `{"ok": False, "error": ...}` (mai inventare un tasso).
     f. `risk_profile = load_risk_profile()` (None se mai compilato).
     g. `plan = execution_module.build_plan(orders, account, positions, caps, fee_model,
        fx_rate_eur_per_ccy, mode, red_team_by_symbol, as_of=<UTC now iso>,
        risk_profile=risk_profile)`.
     h. Ritorna `{"ok": True, "banner": ..., "plan": plan.model_dump(),
        "fx": {"rate_eur_per_usd": ..., "source": rates["source"],
        "as_of": rates["as_of"]}}`.
   - `execute_plan(plan: dict, token: str, allow_real: bool = False) -> dict`:
     `plan_model = execution_module.ExecutionPlan.model_validate(plan)`;
     `client = _etoro_client(plan_model.mode)`; None → `_etoro_unconfigured()`;
     ritorna `{"ok": failed is None, "banner": ...,
     **execution_module.execute(plan_model, token, client, allow_real=allow_real)}`.
     Il doppio gate real resta dentro `execute` (mai replicato/attenuato qui).

## tests/test_server_etoro.py (offline, deterministico)
Fake client con la stessa interfaccia di `EToroClient` (come in tests/test_execution.py)
+ `monkeypatch.setattr(server, "_etoro_client", lambda mode=None: fake)` e
`monkeypatch.setattr(server, "_fx_rates_or_none", lambda: ({"rates": {"USD": 1.0},
"source": "ecb", "as_of": "2026-08-29"}, None))`; ledger su tmp_path via
`monkeypatch.setenv("PORTFOLIO_COPILOT_HOME", str(tmp_path))`. Test:
- `test_etoro_tools_degrade_when_unconfigured`: factory → None ⇒ ogni tool ritorna
  `ok is False` con "not configured" nell'errore, nessuna eccezione.
- `test_etoro_account_returns_banner_and_data`.
- `test_etoro_positions_resolves_symbols_via_instrument_lookup`.
- `test_prepare_execution_builds_a_plan_with_token`: 1 ordine buy (instrument_id,
  min_position_exposure, red_team="passed") ⇒ `ok True`, `plan["token"]` di 16 char,
  `blockers == []`, `lines[0]["amount_account_ccy"] == pytest.approx(amount_eur / 1.0)`
  con USD=1.0 ⇒ fx 1.0.
- `test_prepare_execution_fetches_eligibility_when_missing`: ordine senza
  min_position_exposure ⇒ il fake registra la chiamata eligibility e il plan non ha
  il blocker min_position_exposure.
- `test_prepare_execution_refuses_without_fx`: `_fx_rates_or_none` → (None, "boom") ⇒
  `ok False`.
- `test_execute_plan_happy_path_and_ledger`: prepare + execute col token giusto ⇒
  `ok True`, `sent == ["AAPL"]`, ledger in tmp_path con `broker == "etoro"` e
  `plan_token == plan["token"]`.
- `test_execute_plan_refuses_wrong_token`: `ok False` e `failed["error"] ==
  "token_mismatch"`.
- `test_execute_plan_real_mode_needs_double_gate`: piano mode="real", allow_real=True
  ma env senza ETORO_ALLOW_REAL (monkeypatch.delenv) ⇒ `failed["error"] ==
  "real_mode_not_confirmed"`.

## Verifica
`uv run pytest tests/test_server_etoro.py tests/test_execution.py -q`
