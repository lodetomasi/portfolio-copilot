# Task 02 — Path di valore, drawdown_stats, shortfall_stats [DONE]

**Goal:** dal tensore dei rendimenti bootstrappati a: indice di valore ribilanciato
mensilmente, valore del PAC con versamenti, distribuzione del max drawdown
(convenzione di severità `p95_worst`/`p99_worst`) e statistiche di shortfall.

**File coinvolti:**
- Modifica: `src/portfolio_copilot/analytics/risk_math.py` (append delle funzioni)
- Modifica: `tests/test_risk_math.py` (append dei test)

Dipende da: Task 01.

## Step 1 — Scrivi i test fallenti

Aggiungi in coda a `tests/test_risk_math.py` (estendi l'import da
`portfolio_copilot.analytics.risk_math` con `drawdown_stats, max_drawdown_per_path,
pac_value_paths, portfolio_monthly_returns, shortfall_stats, unit_value_paths`):

```python
def test_portfolio_monthly_returns_is_weighted_sum():
    asset_paths = np.array([[[0.10, -0.02], [0.00, 0.04]]])  # 1 path, 2 mesi, 2 asset
    port = portfolio_monthly_returns(asset_paths, np.array([0.5, 0.5]))
    assert port == pytest.approx(np.array([[0.04, 0.02]]))


def test_portfolio_monthly_returns_weight_mismatch_raises():
    asset_paths = np.zeros((1, 2, 3))
    with pytest.raises(ValueError):
        portfolio_monthly_returns(asset_paths, np.array([0.5, 0.5]))


def test_unit_value_paths_compounds_from_one():
    asset_paths = np.array([[[0.10], [0.10]]])  # 1 path, 2 mesi, 1 asset
    unit = unit_value_paths(asset_paths, np.array([1.0]))
    assert unit == pytest.approx(np.array([[1.10, 1.21]]))


def test_pac_value_paths_contributes_at_month_start():
    asset_paths = np.array([[[0.10], [0.10]]])
    pac = pac_value_paths(asset_paths, np.array([1.0]), monthly_contribution=100.0)
    # (0+100)*1.1 = 110; (110+100)*1.1 = 231
    assert pac == pytest.approx(np.array([[110.0, 231.0]]))


def test_max_drawdown_per_path_prepends_the_unit_start():
    rising = np.array([[1.1, 1.2]])
    assert max_drawdown_per_path(rising) == pytest.approx(np.array([0.0]))
    falling = np.array([[0.9]])
    assert max_drawdown_per_path(falling) == pytest.approx(np.array([-0.1]))


def test_drawdown_stats_severity_convention_worked_example():
    # 100 path con max drawdown noto dd_i = -i/100 (i = 1..100)
    unit_paths = np.array([[1.0 - i / 100.0] for i in range(1, 101)])
    stats = drawdown_stats(unit_paths)
    assert stats["p50"] == pytest.approx(-0.505)
    assert stats["p95_worst"] == pytest.approx(-0.9505)   # MAI ~ -0.05
    assert stats["p99_worst"] == pytest.approx(-0.9901)
    assert stats["prob_worse_than"]["-35%"] == pytest.approx(0.66)
    assert stats["prob_worse_than"]["-50%"] == pytest.approx(0.51)


def test_shortfall_stats_worked_example():
    pac_paths = np.array([[1000.0], [1300.0], [1100.0]])
    stats = shortfall_stats(pac_paths, contributed_total=1200.0)
    assert stats["prob_final_below_contributed"] == pytest.approx(2.0 / 3.0)
    assert stats["final_p50"] == pytest.approx(1100.0)


def test_shortfall_stats_non_positive_contributed_raises():
    with pytest.raises(ValueError):
        shortfall_stats(np.array([[1.0]]), contributed_total=0.0)
```

## Step 2 — Verifica che falliscono

Run: `uv run pytest tests/test_risk_math.py -q`
Output atteso: `ImportError` sui nuovi nomi — rosso confermato.

## Step 3 — Implementa

Appendi a `src/portfolio_copilot/analytics/risk_math.py`:

```python
def portfolio_monthly_returns(asset_paths: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Portfolio monthly return per path/month under MONTHLY REBALANCING to fixed
    ``weights`` (declared assumption; Vanguard 2010: frequency does not materially
    change risk-adjusted outcomes): the weighted sum of asset returns each month.
    ``weights`` must be 1-D and match the asset axis."""
    w = np.asarray(weights, dtype=float)
    if w.ndim != 1 or asset_paths.shape[2] != w.size:
        raise ValueError(
            f"weights length {w.size} does not match n_assets {asset_paths.shape[2]}"
        )
    return asset_paths @ w


def unit_value_paths(asset_paths: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Value index paths starting at 1.0 (pure market movement, no flows)."""
    port = portfolio_monthly_returns(asset_paths, weights)
    return np.cumprod(1.0 + port, axis=1)


def pac_value_paths(
    asset_paths: np.ndarray,
    weights: np.ndarray,
    monthly_contribution: float,
    initial: float = 0.0,
) -> np.ndarray:
    """Plan value paths: the contribution lands at month START, then the month's
    portfolio return applies. Used for shortfall vs total contributed."""
    port = portfolio_monthly_returns(asset_paths, weights)
    n_paths, months = port.shape
    values = np.empty((n_paths, months))
    current = np.full(n_paths, float(initial))
    for t in range(months):
        current = (current + monthly_contribution) * (1.0 + port[:, t])
        values[:, t] = current
    return values


def max_drawdown_per_path(unit_paths: np.ndarray) -> np.ndarray:
    """Max drawdown of each unit-value path, INCLUDING the implicit 1.0 start
    (a path that only falls from day one must not read as 0 drawdown). Signed
    negative values (e.g. -0.55)."""
    padded = np.concatenate(
        [np.ones((unit_paths.shape[0], 1)), np.asarray(unit_paths, dtype=float)], axis=1
    )
    peaks = np.maximum.accumulate(padded, axis=1)
    drawdowns = padded / peaks - 1.0
    return drawdowns.min(axis=1)


def drawdown_stats(unit_paths: np.ndarray) -> dict:
    """Severity convention, fixed here and in the key names: ``p95_worst =
    np.percentile(dd, 5)`` is the drawdown only 5% of paths exceed in severity
    (values are signed negatives), ``p99_worst = np.percentile(dd, 1)``."""
    dd = max_drawdown_per_path(unit_paths)
    return {
        "p50": float(np.percentile(dd, 50)),
        "p95_worst": float(np.percentile(dd, 5)),
        "p99_worst": float(np.percentile(dd, 1)),
        "prob_worse_than": {
            "-35%": float(np.mean(dd <= -0.35)),
            "-50%": float(np.mean(dd <= -0.50)),
        },
    }


def shortfall_stats(pac_paths: np.ndarray, contributed_total: float) -> dict:
    """Final plan value vs total contributed, across paths."""
    if contributed_total <= 0:
        raise ValueError(f"contributed_total must be > 0, got {contributed_total}")
    final = np.asarray(pac_paths, dtype=float)[:, -1]
    return {
        "prob_final_below_contributed": float(np.mean(final < contributed_total)),
        "final_p5": float(np.percentile(final, 5)),
        "final_p50": float(np.percentile(final, 50)),
        "final_p95": float(np.percentile(final, 95)),
    }
```

## Step 4 — Verifica che passano

Run: `uv run pytest tests/test_risk_math.py -q && uv run pytest -q && uv run ruff check .`
Output atteso: file di test verde, suite intera verde (nota fallimento noto da config
locale), ruff `All checks passed!`

## Step 5 — Commit

```bash
git add src/portfolio_copilot/analytics/risk_math.py tests/test_risk_math.py
git commit -m "feat(risk-math): value paths, drawdown severity stats, shortfall stats"
```

## Criteri di accettazione
- [ ] Worked example dei quantili: p95_worst ≈ −0.9505 e p99_worst ≈ −0.9901 (mai ≈ −0.05)
- [ ] PAC: versamento a inizio mese ((0+100)·1.1=110; (110+100)·1.1=231)
- [ ] Il drawdown include la partenza implicita a 1.0
- [ ] `contributed_total <= 0` → `ValueError`
- [ ] Suite intera verde, ruff pulito
