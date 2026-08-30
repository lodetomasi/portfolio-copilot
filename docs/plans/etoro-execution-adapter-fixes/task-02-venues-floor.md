# Task 02 — venues.py: floor senza errore float (finding #14)

## File
- `src/portfolio_copilot/portfolio/venues.py` (`size_order`)
- `tests/test_venues.py`

## Difetto
`units = float(amount // price)` perde un'unità per errore float (verificato:
`4784.65 // 4.33 == 1104.0` mentre il floor matematico è 1105, dato che
4.33 × 1105 = 4784.65 esatti).

## Fix
`from decimal import ROUND_FLOOR, Decimal` in testa; sostituisci la riga con
`units = float((Decimal(str(amount)) / Decimal(str(price))).to_integral_value(rounding=ROUND_FLOOR))`
(floor esatto sul quoziente decimale, senza epsilon assoluti che su prezzi molto
piccoli arrotonderebbero per eccesso oltre il cash).

## Test (rosso prima, verde dopo)
- `test_size_order_export_floor_does_not_lose_a_unit_to_float_error`:
  `size_order(4784.65, 4.33, EXPORT, min_order=0.0)` → `units == 1105.0`,
  `amount == pytest.approx(4784.65)`, `dropped_reason is None`
  (rosso prima: `//` dà 1104).
- Invariati: tutti i test esistenti di `tests/test_venues.py` (il floor resta
  floor: `test_size_order_export_never_rounds_up` continua a dare 1 unità per 199/100).

## Verifica
`uv run pytest tests/test_venues.py -q`
