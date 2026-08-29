# Task 05 — ledger.py: lock portabile + campo plan_token (finding #7, prerequisito #3)

## File
- `src/portfolio_copilot/portfolio/ledger.py` (`DecisionRecord`, `record_decision`)
- `tests/test_ledger.py` (i test del ledger vivono lì, non in test_execution.py)

## Difetti
- #7: il guard anti-duplicato in `record_decision` è read-then-write senza lock:
  due processi concorrenti possono appendere lo stesso id.
- Per il finding #3 (task 07) serve legare ogni record eseguito al token del piano.

## Fix
1. `DecisionRecord`: nuovo campo `plan_token: str | None = None` (commento: token
   sha256 del piano di esecuzione eToro che ha prodotto il record; None per il
   flusso manuale) accanto a broker/broker_order_id/mode.
2. Lock portabile (niente fcntl/msvcrt) in `ledger.py`:
   - costante `_LOCK_TIMEOUT_S = 5.0`, `_LOCK_POLL_S = 0.05`;
   - funzione `_exclusive_lock(path: Path)` context manager: crea
     `path.with_name(path.name + ".lock")` con
     `os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)` in loop; su
     `FileExistsError` attende `_LOCK_POLL_S` fino a `_LOCK_TIMEOUT_S` poi solleva
     `TimeoutError` con il percorso del lock nel messaggio; in `finally` chiude il
     fd e fa `unlink(missing_ok=True)`. IMPORTANTE: `_LOCK_TIMEOUT_S`/`_LOCK_POLL_S`
     vanno letti a runtime DENTRO il corpo della funzione (mai come default di
     parametro), così `monkeypatch.setattr` sul modulo funziona nei test.
3. `record_decision`: la sequenza leggi-controlla-appendi (da `load_decisions` alla
   `fh.write`) va dentro `with _exclusive_lock(ledger_path(home)):`.

## Test (in `tests/test_ledger.py`, rossi prima, verdi dopo)
- `test_record_decision_releases_the_lock_file`: dopo un `record_decision` andato a
  buon fine `not (tmp_path / "decisions.jsonl.lock").exists()`.
- `test_record_decision_times_out_on_stale_lock`: crea a mano
  `tmp_path / "decisions.jsonl.lock"`, `monkeypatch.setattr(ledger, "_LOCK_TIMEOUT_S", 0.1)`
  → `pytest.raises(TimeoutError)` e il ledger resta vuoto.
- `test_decision_record_plan_token_defaults_to_none`: `DecisionRecord(id="x",
  date="2026-01-01", symbol="AAPL", action="BUY", reason="r").plan_token is None`
  (retrocompatibilità con le righe jsonl esistenti).

## Verifica
`uv run pytest tests/test_ledger.py -q`
