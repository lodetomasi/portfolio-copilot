# Task 04 — risk_profile.py: drawdown non troncati + verdetto coerente (finding #9, #10)

## File
- `src/portfolio_copilot/portfolio/risk_profile.py` (`observed_drawdowns`, `fits`)
- `tests/test_risk_profile.py`

## Difetti
- #9: `observed_drawdowns` chiama il provider con TUTTI i bucket in una volta;
  `YFinanceProvider.get_monthly_closes` fa `pd.DataFrame(frames).dropna()` (inner
  join sulle date): un bucket con storia corta tronca la storia degli altri e un
  crash (-53%) sparisce silenziosamente (drawdown ~0%).
- #10: in `fits`, quando `stress` è più mite di `observed` il ramo `else` produce
  un testo che contraddice `fits_stress=True`.

## Fix
1. `observed_drawdowns`: una chiamata provider PER bucket —
   `df = provider.get_monthly_closes({bucket: ticker}, period=period)` dentro il
   loop; per ogni bucket: `None` se il bucket è in `df.attrs["missing"]`, se `df`
   non è un DataFrame, se la colonna manca o se `df[bucket].dropna()` è vuota;
   altrimenti `max_drawdown(df[bucket].dropna())`. Così nessun inner join
   cross-bucket può troncare la storia. (Il caching per-ticker del provider reale
   rende le N chiamate equivalenti a una.)
2. `fits`: aggiungi il ramo mancante prima dell'`else`:
   `elif fits_stress and not fits_observed:` con verdetto
   `f"your {stated_pct} does not hold in a 2020-type crash (observed ≈ {observed * 100:.0f}%), only in the 2008-type stress estimate (≈ {stress * 100:.0f}%)."`

## Test (rossi prima, verdi dopo)
- `test_observed_drawdowns_not_truncated_by_short_sibling_bucket`: fake provider
  che replica il join reale (`pd.DataFrame({b: serie_indicizzata_per_data}).dropna()`
  su TUTTI i bucket richiesti in una chiamata): bucket `crash` con storia lunga
  indicizzata 2020-01..2020-12 che passa da 100 a 47 nei primi mesi, bucket
  `recent` presente solo 2020-10..2020-12. Chiamata con entrambi i bucket:
  assert `out["crash"] == pytest.approx(-0.53)` (il vecchio codice, con la storia
  troncata a ottobre-dicembre, riporta ~0).
- `test_fits_verdict_consistent_when_stress_milder_than_observed`:
  `fits({"observed": -0.40, "observed_missing_buckets": [], "stress": -0.30,
  "stress_missing_buckets": []}, max_drawdown_pct=35)` →
  `fits_observed is False`, `fits_stress is True`, e il verdetto contiene
  `"only in the 2008-type stress estimate"`.
- Invariati: i test esistenti su `observed_drawdowns` (il `_FakeProvider` del file
  funziona anche chiamato bucket per bucket) e su `fits`.

## Verifica
`uv run pytest tests/test_risk_profile.py -q`
