# Task 03 — sources.py: schema posizioni reale, short, valore mancante, fx (finding #11, #12, #13, #15)

## File
- `src/portfolio_copilot/portfolio/sources.py` (`portfolio_from_etoro`, `_native_market_value`)
- `tests/test_sources.py`

## Difetti
- #12: la funzione legge `current_rate`/`market_value` ma `EToroClient.positions()`
  emette `units`, `open_rate`, `amount`, `pnl`, `is_buy` → ogni posizione reale vale 0.0.
- #13: `is_buy=False` (short) ignorato → quantità con lo stesso segno di un long.
- #11: quantità nota ma prezzo/valore assenti → `market_value` azzerato in silenzio.
- #15: `fx_rate_eur_per_ccy <= 0` mai validato.

## Fix
1. In testa a `portfolio_from_etoro`: se `fx_rate_eur_per_ccy is not None and
   fx_rate_eur_per_ccy <= 0` → `raise ValueError(f"fx_rate_eur_per_ccy must be > 0, got {fx_rate_eur_per_ccy!r}")`.
2. Quantità: `units = _as_float(position.get("units")) or 0.0`; se
   `position.get("is_buy") is False` → `quantity = -units`, altrimenti `quantity = units`.
3. Valore nativo, in `_native_market_value(position, quantity, market_price)` con
   precedenza esplicita (mai inventare):
   a. `market_value` esplicito se presente;
   b. `abs(quantity) * market_price` se `market_price` (da `current_rate`) presente;
   c. `amount + pnl` se ENTRAMBI presenti (capitale investito + P/L non realizzato
      = valore corrente della posizione, chiavi reali di `EToroClient.positions()`);
   d. altrimenti `None`.
4. Valore mancante con quantità nota: la Holding resta (coverage mai persa) con
   `market_value=0.0` (il modello richiede float) MA il simbolo finisce in una nuova
   lista `missing_value_symbols` ritornata dalla funzione. Nuova firma:
   `return portfolio, cash_available_eur, missing_value_symbols` (3-tupla).
   Aggiorna TUTTI gli unpacking nei test esistenti a 3 elementi.
   DEVIAZIONE DICHIARATA dal design #11 ("market_value=None"): `Holding.market_value`
   è `float` obbligatorio in `models.py` e cambiarlo toccherebbe tutto il repo;
   con 0.0 `Portfolio.total_value` sottostima — per questo il chiamante DEVE
   propagare `missing_value_symbols` e dichiararlo (documentato nella docstring).
5. `market_price` resta `_as_float(position.get("current_rate"))` (None per le
   posizioni reali: il payload pnl non porta il prezzo corrente — mai inventarlo
   da `open_rate`).

## Test (rossi prima, verdi dopo)
- `test_portfolio_from_etoro_reads_real_client_position_keys`: posizione con
  chiavi reali `{"symbol": "AAPL", "units": 2.0, "open_rate": 150.0, "amount": 300.0,
  "pnl": 20.0, "is_buy": True, "leverage": 1.0}`, account USD, fx 0.92 →
  `market_value == pytest.approx((300.0 + 20.0) * 0.92)`, `quantity == 2.0`,
  `missing == []`.
- `test_portfolio_from_etoro_short_position_gets_negative_quantity`: stessa
  posizione con `is_buy=False` → `quantity == -2.0`, valore ancora
  `pytest.approx(294.4)`.
- `test_portfolio_from_etoro_known_quantity_without_any_value_is_flagged_not_zeroed`:
  `{"symbol": "XYZ", "units": 3.0}` → holding presente, `market_value == 0.0`,
  `missing == ["XYZ"]`.
- `test_portfolio_from_etoro_rejects_non_positive_fx_rate`:
  `pytest.raises(ValueError)` con `fx_rate_eur_per_ccy=0.0` e con `-1.0`.
- Aggiorna gli esistenti: unpacking a 3-tupla;
  `test_portfolio_from_etoro_missing_fields_become_none_never_invented` ora
  attende `missing == ["XYZ"]` per la posizione senza valore.

## Verifica
`uv run pytest tests/test_sources.py -q`
