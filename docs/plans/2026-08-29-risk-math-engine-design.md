# Design — Motore risk-math: bootstrap Monte Carlo, shortfall, CVaR, Kelly

Data: 2026-08-29 · Complessità: Alta · Rev 3 (spec-review: APPROVED, 3 iterazioni, 0 BLOCK residui)
SP totali: Umano 5 / Augmented 2 — split: modulo matematico + fixture 2.0/0.8;
worked-test dei quantili e determinismo 1.0/0.4; wiring 2 tool MCP + test con provider
mockato 1.5/0.6; aggiornamento skill (solo testo) 0.5/0.2.

## Contesto

Le lenti di rischio attuali sono somme pesate di drawdown per bucket
(`portfolio/risk_profile.py::drawdown_budget`): ignorano le correlazioni tra bucket, non
producono distribuzioni né probabilità, e non rispondono alle domande del piano a due conti
("il −35% regge?", "che rischio ha il satellite a 5 anni?", "quanto metto su un titolo
high-risk?"). Evidenza a supporto: Bessembinder 2018 Tab. 1 (shortfall a 5 anni),
Bali-Cakici-Whitelaw 2011 (sizing dei lottery stock). Il modello a 16 motori dell'utente
prevede analisi quantitative da esperto dietro output da rookie.

## Approcci valutati

1. **Block bootstrap storico congiunto + CVaR storico + half-Kelly (SCELTO).**
   Pro: non parametrico — cattura correlazioni e code grasse direttamente dalla storia
   congiunta dei rendimenti mensili; deterministico con seed; zero nuove dipendenze
   (numpy via pandas). Contro: limitato dalla finestra storica disponibile (dichiarata
   nelle disclosures, mai nascosta).
2. Monte Carlo gaussiano multivariato (media+covarianza). Pro: funziona con poca storia.
   Contro: sottostima sistematicamente le code (2008-type) — esattamente ciò che serve
   misurare. Scartato come motore primario.
3. Ottimizzatore mean-variance / Black-Litterman. Contro: cambia la filosofia del
   prodotto (i target sono scelti dall'utente da model portfolio, non ottimizzati);
   stima di rendimenti attesi = garbage-in. Scartato (YAGNI).

## Design

### Modulo nuovo `src/portfolio_copilot/analytics/risk_math.py` (matematica pura, zero I/O)

- `monthly_returns(closes: pd.DataFrame) -> pd.DataFrame` — variazioni percentuali
  mensili; righe con NaN scartate e conteggiate; < 24 osservazioni congiunte →
  `ValueError` esplicito (mai simulare su storia insufficiente).
- `block_bootstrap_paths(returns, months, n_paths, seed, mean_block: int | None = None)
  -> np.ndarray` di forma `(n_paths, months, n_assets)`: **stationary bootstrap**
  (Politis & Romano 1994) — blocchi contigui di righe congiunte con lunghezza geometrica
  di media `mean_block`, wrap circolare; preserva correlazioni cross-asset e
  autocorrelazione senza il problema di giunzione dei blocchi fissi. Default
  `mean_block = clamp(round(n_obs ** (1/3)), 2, 12)`: regola del tasso ottimale
  N^(1/3) (Patton-Politis-White 2009, correzione di Politis-White 2004 — per rendimenti
  azionari mensili con ρ₁≈0-0.1 e N=60-300 l'ottimo è ≈ 2-4; un blocco fisso 12 NON è
  ottimale, la ricerca online 2026-08-29 lo ha smentito). `seed` obbligatorio, generatore
  `np.random.Generator(PCG64(seed))` → stessi input, stesso output (test deterministici).
- `unit_value_paths(asset_paths, weights) -> np.ndarray (n_paths, months)` — indice di
  valore a quota 1 con ribilanciamento mensile ai pesi (assunzione dichiarata).
- `pac_value_paths(asset_paths, weights, monthly_contribution, initial=0.0)` — valore
  del piano con versamenti a inizio mese (per lo shortfall vs contribuito).
- `drawdown_stats(unit_paths) -> dict` — sul max drawdown per path (valori FIRMATI,
  negativi, es. −0.55). **Convenzione di severità, fissata qui (risolve BLOCK-2):**
  `p50 = np.percentile(dd, 50)`; `p95_worst = np.percentile(dd, 5)` = il drawdown
  superato in severità solo dal 5% dei path; `p99_worst = np.percentile(dd, 1)`.
  Le chiavi si chiamano `p50`/`p95_worst`/`p99_worst` proprio perché il suffisso
  renda impossibile l'interpretazione opposta. In più
  `prob_worse_than = {"-35%": frazione di path con dd <= -0.35, "-50%": idem}`.
- `shortfall_stats(pac_paths, contributed_total) -> dict` —
  `{"prob_final_below_contributed": .., "final_p5": .., "final_p50": .., "final_p95": ..}`.
- `cvar(returns_monthly, alpha=0.95) -> dict` — expected shortfall storico mensile con
  l'**estimatore discreto esatto di Rockafellar & Uryasev 2000** (la media semplice
  della coda è il CVaR⁺ e sbaglia quando alpha "spezza un atomo"):
  `CVaR = λ·VaR + (1−λ)·CVaR⁺` con `λ = (Ψ(VaR) − α)/(1 − α)`.
  Ritorna `{"cvar": .., "var": .., "n_tail_obs": ..}` — `n_tail_obs` va nelle
  disclosures perché con 60-300 osservazioni mensili la coda al 95% ha 3-15 punti
  (Yamai-Yoshiba 2002: l'ES su campioni piccoli va dichiarato, non spacciato per stima
  puntuale precisa). Alpha default 0.95 (retail/accademico; il 97.5 di Basel MAR33.3 è
  pensato per dati giornalieri bancari e qui lascerebbe 1-7 punti in coda).
  Array vuoto/NaN → `ValueError`.
- `kelly_fraction(p_win, payoff_ratio, fraction=0.5) -> float` — Kelly frazionario:
  `f = p − (1−p)/payoff_ratio`, scalato per `fraction` (default half-Kelly); edge
  negativo → `0.0` (mai size negativa); `p_win` fuori da (0,1) o `payoff_ratio <= 0` →
  `ValueError`.

### Wiring MCP in `server.py`

- Tool `simulate_plan_risk(tickers: dict[bucket, yf_ticker], weights: dict[bucket, float],
  monthly_eur: float, horizon_months: int, n_paths: int = 10000, seed: int = 42,
  period: str = "max")`: `n_paths` default 10.000 perché il payload espone `p99_worst`
  — a 2.000 path la SE del quantile 99% è ≈ 0.08σ (inutilizzabile), a 10.000 ≈ 0.04σ
  (CLT del quantile campionario, Dong-Nakayama 2020 su Glasserman 2003); prende i
  closes mensili dal provider esistente (fallback-aware),
  valida `weights` con la stessa regola di `validate_targets` (somma 1.0), esegue il
  motore e ritorna (risolve BLOCK-1: il CVaR è parte del payload, non una funzione
  orfana): `drawdown_stats` (p50/p95_worst/p99_worst/prob_worse_than),
  `shortfall_stats`, **`cvar_monthly_95`** = lo SCALARE `cvar` ritornato da `cvar()`
  (expected shortfall storico dei rendimenti mensili del portafoglio ai pesi dati,
  calcolato sulla storia reale congiunta — non sui path simulati); `var` e `n_tail_obs`
  dello stesso dict finiscono nelle `disclosures` come `var_monthly_95` e
  `cvar_tail_obs` (destinazione dichiarata, niente campo scartato in silenzio).
  `disclosures` obbligatorie: finestra per bucket, n osservazioni, `mean_block` usato,
  metodo (f-string coerente col metodo reale: "stationary bootstrap, lunghezza blocco
  media {mean_block} mesi, wrap circolare, ribilanciamento mensile" — col wrap
  circolare ogni indice di partenza 0..n_obs−1 è valido, quindi il conteggio riportato
  è semplicemente `n_obs`, non `n_obs − block + 1`), "not a forecast", warning testuale
  se n_obs < 60 ("percentili di coda poco affidabili: solo N mesi di storia").
  Bucket senza dati → escluso e dichiarato in `missing`, mai inventato. Il test del
  tool verifica anche il testo del metodo nella disclosure (criterio di accettazione 7).
- Tool `kelly_size(p_win, payoff_ratio, sleeve_value_eur, cap_pct, fraction=0.5)`
  (parametri senza default PRIMA di quello con default — firma Python valida):
  ritorna la frazione Kelly e l'importo in EUR già tagliato al cap del venue
  (`min(kelly, cap_pct) * sleeve_value_eur`) — il cap vince sempre su Kelly.

### Integrazione skill (nessun'altra modifica di codice)

`investment-plan` check-in e `stock-picker` passano al tool i ticker/pesi del piano; il
numero "probabilità di finire sotto il versato a 5 anni" entra nella risposta rookie-out
del satellite. Le lenti esistenti (`drawdown_budget`) restano: lente semplice dichiarata,
non sostituita (nessuna regressione).

## Flusso dati
provider closes mensili → `monthly_returns` → `block_bootstrap_paths` →
`unit_value_paths`/`pac_value_paths` → `drawdown_stats`/`shortfall_stats` → tool MCP →
skill (rookie-out con disclosures).

## Errori
Nessun nuovo `except Exception`. Storia insufficiente, pesi che non sommano a 1, NaN,
parametri Kelly invalidi → `ValueError` espliciti. Il tool MCP degrada come gli altri
(envelope con `missing`/`disclosures`), mai numeri inventati.

## Testing (offline, deterministico)
- Fixture sintetica: 120 mesi × 3 asset con correlazione nota (generata con seed fisso,
  salvata in `tests/fixtures/`).
- Determinismo: stesso seed → output identico; seed diverso → diverso.
- Bootstrap: ogni riga campionata esiste nella storia sorgente (join-preservation:
  le righe multi-asset restano congiunte); i blocchi sono contigui nella sorgente
  (con wrap circolare); `mean_block` default = clamp(round(n_obs**(1/3)), 2, 12)
  verificato su n_obs noti (68 → 4; 300 → 7); path lunghi `months` esatti anche quando
  l'ultimo blocco va troncato.
- `drawdown_stats`: path costruito a mano con DD noto (−50%) → p50 esatto; worked-test
  sui quantili di severità: 100 path costruiti con dd_i = −i/100 (i = 1..100) →
  `p95_worst` ≈ −0.95 e `p99_worst` ≈ −0.99 (mai ≈ −0.05: il test inchioda la
  convenzione di segno).
- `shortfall_stats`: path deterministici sopra/sotto il contribuito → probabilità 0/1.
- `cvar`: vettore noto in cui alpha spezza un atomo → il risultato coincide con la
  formula λ di Rockafellar-Uryasev calcolata a mano E differisce dalla media semplice
  della coda (il test inchioda l'estimatore giusto); `n_tail_obs` corretto.
- `kelly_fraction`: (0.6, 2.0) → 0.40 full / 0.20 half; edge negativo → 0.0;
  input invalidi → ValueError.
- Tool MCP: provider mockato (nessuna rete), weights invalidi → errore strutturato,
  bucket mancante dichiarato.
- Edge: < 24 osservazioni → ValueError; colonna tutta NaN → esclusa e dichiarata.

## Rischi e mitigazioni
- **Determinismo cross-versione numpy**: il generatore è `np.random.Generator(PCG64(seed))`;
  il test di determinismo confronta due run nello stesso processo (stesso seed → identici)
  e un test separato inchioda i quantili attesi della fixture con `atol=1e-9`, marcato con
  commento "rigenerare se un major bump di numpy cambia PCG64" — il determinismo
  same-run non dipende dalla versione, il valore assoluto sì ed è dichiarato.
- **Coda poco affidabile con storia corta**: sotto 24 osservazioni il modulo rifiuta
  (`ValueError`); tra 24 e 59 il tool produce output ma la disclosure quantifica
  n_obs e n blocchi distinti e avvisa esplicitamente — mai un numero di coda senza il
  suo caveat accanto.
- **Assunzione di ribilanciamento mensile**: dichiarata nelle disclosures; l'evidenza
  (Jaconetti-Kinniry-Zilbering, Vanguard 2010: risk-adjusted return "not meaningfully
  different" tra mensile/trimestrale/annuale su 60/40 1926-2009) dice che la frequenza
  cambia poco i risultati, quindi l'assunzione è comoda ma non distorsiva — citata nel
  docstring insieme al caveat "nessuna commissione/tassa modellata".
- **CVaR su coda piccola**: `n_tail_obs` sempre nel payload e nelle disclosures
  (Yamai-Yoshiba 2002); mai presentato come stima puntuale precisa.
- **Fonti dei parametri** (ricerca online 2026-08-29, verificate sui PDF primari):
  Politis & Romano 1994 (stationary bootstrap); Patton-Politis-White 2009 (block length
  ottimale ∝ N^(1/3)); Rockafellar & Uryasev 2000 (estimatore CVaR discreto); Yamai &
  Yoshiba 2002 (affidabilità ES campioni piccoli); MacLean-Thorp-Ziemba 2010 (half-Kelly:
  75% della crescita, P(raddoppio prima di dimezzamento) 0.89 vs 0.67 del full Kelly;
  Chopra-Ziemba 1993: errori di stima media:varianza:covarianza ≈ 20:2:1); Dong-Nakayama
  2020/Glasserman 2003 (SE quantili MC); Vanguard 2010 (frequenza ribilanciamento).

## Criteri di accettazione
1. `simulate_plan_risk` sul mix del piano ritorna `p50`/`p95_worst`/`p99_worst` del max
   drawdown, `prob_worse_than -35%`, e shortfall a orizzonte, con disclosures complete
   (test con provider mockato).
2. Stesso seed → stessi numeri nello stesso processo (test con doppia run).
3. `kelly_size` non supera mai `cap_pct` (test property-style su griglia di input).
4. `uv run pytest` tutto verde (esistenti + nuovi), `uv run ruff check .` pulito.
5. `drawdown_budget` e ogni call site esistente invariati.
6. `cvar_monthly_95` (scalare) è presente nel payload di `simulate_plan_risk` e
   coincide col calcolo a mano sulla fixture (test con provider mockato);
   `var_monthly_95` e `cvar_tail_obs` presenti nelle disclosures.
7. La disclosure `metodo` contiene "stationary bootstrap" e il `mean_block`
   effettivamente usato — mai un testo fisso che descrive un metodo diverso (test
   sul testo della disclosure con provider mockato).

## Fuori scope (registrato, non dimenticato)
Decision calibration (≥30 decisioni) e portfolio autopsy/Brinson+fattori (≥24 mesi di
storia ledger): restano i prossimi della coda approvata nel modello a 16 motori; oggi
non hanno dati per produrre output non banali.
