# Task 01 — brokers/etoro.py: retry 429 idempotente (finding #1)

## File
- `src/portfolio_copilot/brokers/etoro.py` (`EToroClient._request`)
- `tests/test_etoro_client.py`

## Difetto
Il retry su 429 rigenera `x-request-id` e per le chiamate write (`write=True`)
rispedisce un ordine identico con id nuovo → rischio double-send.

## Fix
In `_request`:
1. Genera `request_id = str(uuid.uuid4())` UNA volta, prima del loop; il loop lo riusa.
2. Il retry automatico su 429 avviene solo per le letture: condizione
   `if response.status_code == 429 and attempt == 0 and not write:`. Per `write=True`
   il 429 non viene mai ritentato: `_parse_or_raise` solleva subito `RateLimited`.
3. Correggi la stringa non bilanciata in `open_market_order`:
   `"side must be 'buy' or 'sellShort' (this endpoint has no plain 'sell')"`.

## Test (rossi prima, verdi dopo)
- `test_429_read_retry_reuses_the_same_request_id`: handler cattura
  `x-request-id`; risponde 429 poi 200 su `client.account()`; assert due chiamate
  HTTP con lo stesso request id.
- `test_429_on_write_never_retries_and_raises_rate_limited`: handler conta le
  chiamate e risponde sempre 429 su `client.eligibility(1001)` (write=True);
  assert `pytest.raises(RateLimited)`, `calls == 1`, `sleeper.calls == []`.
- Invariati: `test_429_retries_once_after_retry_after_then_succeeds`,
  `test_429_twice_raises_rate_limited_with_retry_after` (sono letture),
  `test_headers_present_and_request_id_unique_per_call` (id diversi tra chiamate distinte).

## Verifica
`uv run pytest tests/test_etoro_client.py -q`
