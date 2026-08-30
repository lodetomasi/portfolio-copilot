# Task 03 — cvar (λ-estimator) + kelly_fraction [DONE]

**Goal:** CVaR storico con l'estimatore discreto esatto di Rockafellar-Uryasev 2000
(non la media semplice della coda) e Kelly frazionario con edge negativo → 0.

**File coinvolti:**
- Modifica: `src/portfolio_copilot/analytics/risk_math.py` (append)
- Modifica: `tests/test_risk_math.py` (append)

Dipende da: Task 01 (stesso modulo; eseguire dopo il Task 02 per evitare conflitti di
append). Nessuna dipendenza funzionale da 02.

## Step 1 — Scrivi i test fallenti

Aggiungi in coda a `tests/test_risk_math.py` (estendi l'import con `cvar, kelly_fraction`):

```python
def test_cvar_uses_rockafellar_uryasev_lambda_estimator():
    # perdite 0.01..0.30 (rendimenti -0.01..-0.30), n=30, alpha=0.95:
    # k = ceil(28.5) = 29 -> VaR_loss = 0.29, psi = 29/30, lambda = 1/3,
    # coda = {0.30} -> CVaR_loss = (1/3)*0.29 + (2/3)*0.30 = 0.2966667
    returns = np.array([-(i / 100.0) for i in range(1, 31)])
    result = cvar(returns, alpha=0.95)
    assert result["var"] == pytest.approx(-0.29)
    assert result["cvar"] == pytest.approx(-0.2966667, rel=1e-5)
    assert result["n_tail_obs"] == 1
    # la media semplice della coda (CVaR+) darebbe -0.30: l'estimatore giusto differisce
    assert result["cvar"] != pytest.approx(-0.30)


def test_cvar_lambda_zero_when_alpha_hits_an_atom():
    # n=20, alpha=0.95: k = 19, psi = 19/20 = alpha -> lambda = 0 -> CVaR = CVaR+
    returns = np.array([-(i / 100.0) for i in range(1, 21)])
    result = cvar(returns, alpha=0.95)
    assert result["var"] == pytest.approx(-0.19)
    assert result["cvar"] == pytest.approx(-0.20)


def test_cvar_invalid_inputs_raise():
    with pytest.raises(ValueError):
        cvar(np.array([]))
    with pytest.raises(ValueError):
        cvar(np.array([0.01, np.nan]))
    with pytest.raises(ValueError):
        cvar(np.array([0.01, -0.02]), alpha=1.0)


def test_kelly_fraction_worked_examples():
    assert kelly_fraction(0.6, 2.0, fraction=1.0) == pytest.approx(0.40)
    assert kelly_fraction(0.6, 2.0) == pytest.approx(0.20)  # half-Kelly default


def test_kelly_fraction_negative_edge_is_zero_never_negative():
    assert kelly_fraction(0.3, 1.0) == 0.0


def test_kelly_fraction_invalid_inputs_raise():
    with pytest.raises(ValueError):
        kelly_fraction(0.0, 2.0)
    with pytest.raises(ValueError):
        kelly_fraction(1.0, 2.0)
    with pytest.raises(ValueError):
        kelly_fraction(0.6, 0.0)
    with pytest.raises(ValueError):
        kelly_fraction(0.6, 2.0, fraction=0.0)
```

## Step 2 — Verifica che falliscono

Run: `uv run pytest tests/test_risk_math.py -q`
Output atteso: `ImportError` su `cvar`/`kelly_fraction` — rosso confermato.

## Step 3 — Implementa

Appendi a `src/portfolio_copilot/analytics/risk_math.py`:

```python
def cvar(returns_monthly: np.ndarray, alpha: float = 0.95) -> dict:
    """Historical Expected Shortfall of monthly returns, reported in RETURN terms
    (negative numbers), with the exact discrete estimator of Rockafellar & Uryasev
    2000: ``CVaR = lambda * VaR + (1 - lambda) * CVaR+`` where ``lambda =
    (psi(VaR) - alpha) / (1 - alpha)`` -- the plain tail mean is CVaR+ and is wrong
    whenever alpha splits an atom of the empirical distribution.

    Returns ``{"cvar", "var", "n_tail_obs", "alpha"}``; ``n_tail_obs`` (how many
    observations sit beyond VaR) belongs next to the number wherever it is shown --
    with 60-300 monthly observations the tail holds 3-15 points (Yamai & Yoshiba
    2002), so the figure is an estimate with declared support, never false precision.
    """
    arr = np.asarray(returns_monthly, dtype=float)
    if arr.size == 0:
        raise ValueError("returns_monthly is empty")
    if np.isnan(arr).any():
        raise ValueError("returns_monthly contains NaN")
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")

    losses = -arr
    n = losses.size
    k = int(np.ceil(alpha * n))
    var_loss = float(np.sort(losses)[k - 1])
    psi = float(np.mean(losses <= var_loss))
    lam = (psi - alpha) / (1.0 - alpha)
    tail = losses[losses > var_loss]
    n_tail = int(tail.size)
    cvar_plus = float(tail.mean()) if n_tail else var_loss
    cvar_loss = lam * var_loss + (1.0 - lam) * cvar_plus
    return {"cvar": -cvar_loss, "var": -var_loss, "n_tail_obs": n_tail, "alpha": alpha}


def kelly_fraction(p_win: float, payoff_ratio: float, fraction: float = 0.5) -> float:
    """Fractional Kelly: ``max(0, p - (1 - p) / payoff_ratio) * fraction``.

    Default 0.5 (half-Kelly): 75% of full-Kelly growth with P(double before halving)
    0.89 vs 0.67 (MacLean-Thorp-Ziemba 2010), and estimated means carry ~10x the
    error weight of variances (Chopra & Ziemba 1993) -- over-betting costs growth AND
    safety, so the venue cap must always win over Kelly at the call site. A negative
    edge returns 0.0: never a negative size.
    """
    if not 0.0 < p_win < 1.0:
        raise ValueError(f"p_win must be in (0, 1), got {p_win}")
    if payoff_ratio <= 0.0:
        raise ValueError(f"payoff_ratio must be > 0, got {payoff_ratio}")
    if not 0.0 < fraction <= 1.0:
        raise ValueError(f"fraction must be in (0, 1], got {fraction}")
    full = p_win - (1.0 - p_win) / payoff_ratio
    return max(0.0, full * fraction)
```

## Step 4 — Verifica che passano

Run: `uv run pytest tests/test_risk_math.py -q && uv run pytest -q && uv run ruff check .`
Output atteso: file di test verde, suite intera verde (nota fallimento noto da config
locale), ruff `All checks passed!`

## Step 5 — Commit

```bash
git add src/portfolio_copilot/analytics/risk_math.py tests/test_risk_math.py
git commit -m "feat(risk-math): Rockafellar-Uryasev discrete CVaR and fractional Kelly"
```

## Criteri di accettazione
- [ ] Caso 30 osservazioni: cvar ≈ −0.2966667 (≠ −0.30 della media semplice), var −0.29,
      n_tail_obs 1
- [ ] Caso atomo esatto (n=20): λ=0 → cvar = CVaR⁺
- [ ] Kelly: (0.6, 2.0) → 0.40 pieno / 0.20 half; edge negativo → 0.0
- [ ] Input invalidi → `ValueError`
- [ ] Suite intera verde, ruff pulito
