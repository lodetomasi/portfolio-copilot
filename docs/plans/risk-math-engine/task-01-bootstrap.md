# Task 01 — Modulo risk_math: returns + stationary bootstrap [DONE]

**Goal:** `analytics/risk_math.py` nasce con `monthly_returns`, `default_mean_block`,
`block_bootstrap_paths` (stationary bootstrap, wrap circolare, PCG64), testati offline.

**File coinvolti:**
- Crea: `tests/fixtures/risk_math_closes.csv` (fixture sintetica, comando sotto)
- Crea: `src/portfolio_copilot/analytics/risk_math.py`
- Crea: `tests/test_risk_math.py`

## Step 0 — Genera la fixture (una tantum, deterministica)

```bash
uv run python - <<'EOF'
import numpy as np
import pandas as pd

rng = np.random.Generator(np.random.PCG64(7))
z = rng.standard_normal((120, 3))
returns = pd.DataFrame(
    {
        "eq": 0.006 + 0.04 * z[:, 0],
        "sc": 0.007 + 0.7 * (0.04 * z[:, 0]) + 0.03 * z[:, 1],
        "th": 0.008 + 0.06 * z[:, 2],
    },
    index=pd.date_range("2010-01-31", periods=120, freq="ME"),
)
closes = 100.0 * (1.0 + returns).cumprod()
start = pd.DataFrame(
    {"eq": [100.0], "sc": [100.0], "th": [100.0]},
    index=pd.date_range("2009-12-31", periods=1, freq="ME"),
)
pd.concat([start, closes]).round(6).to_csv("tests/fixtures/risk_math_closes.csv")
print("rows:", len(closes) + 1)
EOF
```

Output atteso: `rows: 121`.

## Step 1 — Scrivi i test fallenti

Crea `tests/test_risk_math.py`:

```python
"""Offline, deterministic tests for analytics.risk_math (pure math, no I/O)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from portfolio_copilot.analytics.risk_math import (
    block_bootstrap_paths,
    default_mean_block,
    monthly_returns,
)

FIXTURE = Path(__file__).parent / "fixtures" / "risk_math_closes.csv"


def _closes() -> pd.DataFrame:
    return pd.read_csv(FIXTURE, index_col=0, parse_dates=True)


def _returns() -> pd.DataFrame:
    return monthly_returns(_closes())


def test_monthly_returns_shape_and_first_value():
    closes = _closes()
    returns = monthly_returns(closes)
    assert len(returns) == 120
    expected = closes.iloc[1]["eq"] / closes.iloc[0]["eq"] - 1.0
    assert returns.iloc[0]["eq"] == pytest.approx(expected)


def test_monthly_returns_drops_all_nan_column_and_declares_it():
    closes = _closes()
    closes["dead"] = np.nan
    returns = monthly_returns(closes)
    assert "dead" not in returns.columns
    assert returns.attrs["dropped"] == ["dead"]


def test_monthly_returns_insufficient_history_raises():
    with pytest.raises(ValueError, match="insufficient"):
        monthly_returns(_closes().head(20))


def test_default_mean_block_follows_cube_root_rule_with_clamp():
    assert default_mean_block(68) == 4
    assert default_mean_block(300) == 7
    assert default_mean_block(8) == 2       # clamp basso
    assert default_mean_block(5000) == 12   # clamp alto


def test_bootstrap_shape_and_determinism():
    returns = _returns()
    a = block_bootstrap_paths(returns, months=36, n_paths=50, seed=42)
    b = block_bootstrap_paths(returns, months=36, n_paths=50, seed=42)
    c = block_bootstrap_paths(returns, months=36, n_paths=50, seed=43)
    assert a.shape == (50, 36, 3)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_bootstrap_samples_only_joint_source_rows():
    returns = _returns()
    source = {tuple(row) for row in returns.to_numpy()}
    paths = block_bootstrap_paths(returns, months=24, n_paths=20, seed=1)
    sampled = {tuple(row) for row in paths.reshape(-1, 3)}
    assert sampled <= source


def test_bootstrap_blocks_are_contiguous_with_wrap():
    n_obs = 60
    encoded = pd.DataFrame(
        {"a": np.arange(n_obs, dtype=float), "b": np.arange(n_obs, dtype=float)}
    )
    paths = block_bootstrap_paths(encoded, months=200, n_paths=30, seed=5, mean_block=4)
    idx = paths[:, :, 0]
    continuations = (idx[:, 1:] == (idx[:, :-1] + 1) % n_obs).mean()
    # p_restart = 1/4: attesi ~75% passi contigui (il seed fisso rende il valore stabile)
    assert 0.65 <= continuations <= 0.85


def test_bootstrap_invalid_inputs_raise():
    returns = _returns()
    with pytest.raises(ValueError):
        block_bootstrap_paths(returns, months=0, n_paths=10, seed=1)
    with pytest.raises(ValueError):
        block_bootstrap_paths(returns, months=12, n_paths=0, seed=1)
    with pytest.raises(ValueError):
        block_bootstrap_paths(returns, months=12, n_paths=10, seed=1, mean_block=0)
    broken = returns.copy()
    broken.iloc[3, 1] = np.nan
    with pytest.raises(ValueError):
        block_bootstrap_paths(broken, months=12, n_paths=10, seed=1)
```

## Step 2 — Verifica che falliscono

Run: `uv run pytest tests/test_risk_math.py -q`
Output atteso: errore di collezione `ModuleNotFoundError: No module named
'portfolio_copilot.analytics.risk_math'` — rosso confermato.

## Step 3 — Implementa

Crea `src/portfolio_copilot/analytics/risk_math.py`:

```python
"""Advanced risk math: stationary-bootstrap Monte Carlo, drawdown/shortfall
distributions, discrete CVaR, fractional Kelly.

Pure math on pandas/numpy inputs, zero I/O (same boundary as ``analytics/metrics.py``).
Parameter sources (verified 2026-08-29 against the primary PDFs):

- Stationary bootstrap: Politis & Romano 1994; mean block length rule ``n ** (1/3)``
  clamped to [2, 12] per Patton, Politis & White 2009 (optimal-rate correction of
  Politis & White 2004) -- for monthly equity returns the optimum is ~2-4, NOT 12.
- Discrete CVaR estimator: Rockafellar & Uryasev 2000 (``lambda * VaR +
  (1 - lambda) * CVaR+``); small-sample tail caveat: Yamai & Yoshiba 2002.
- Fractional Kelly (default 0.5): MacLean, Thorp & Ziemba 2010; estimation-error
  asymmetry: Chopra & Ziemba 1993.
- Quantile MC standard error (10k paths for a p99): Dong & Nakayama 2020 / Glasserman 2003.
- Monthly-rebalancing simulation assumption: Jaconetti, Kinniry & Zilbering (Vanguard) 2010.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MIN_JOINT_OBSERVATIONS = 24


def monthly_returns(closes: pd.DataFrame) -> pd.DataFrame:
    """Joint monthly simple returns from a closes frame.

    All-NaN columns are dropped and listed in ``result.attrs["dropped"]``; rows with
    any remaining NaN are dropped so the history stays JOINT (cross-asset correlations
    need aligned rows) and their COUNT is declared in ``result.attrs["rows_dropped"]``
    (design: "righe con NaN scartate e conteggiate" -- never silently ignored).
    Fewer than ``MIN_JOINT_OBSERVATIONS`` joint rows raises ``ValueError`` --
    simulating on insufficient history would invent precision that is not there.
    """
    if closes is None or closes.empty:
        raise ValueError("closes is empty")
    dropped = [col for col in closes.columns if closes[col].dropna().empty]
    frame = closes.drop(columns=dropped)
    if frame.empty:
        raise ValueError("closes has no usable columns")
    raw = frame.pct_change().iloc[1:]
    returns = raw.dropna(how="any")
    if len(returns) < MIN_JOINT_OBSERVATIONS:
        raise ValueError(
            f"insufficient joint history: {len(returns)} monthly observations "
            f"(< {MIN_JOINT_OBSERVATIONS})"
        )
    returns.attrs["dropped"] = dropped
    returns.attrs["rows_dropped"] = int(len(raw) - len(returns))
    return returns


def default_mean_block(n_obs: int) -> int:
    """Mean block length ``clamp(round(n_obs ** (1/3)), 2, 12)`` -- the N^(1/3)
    optimal-rate rule (Patton-Politis-White 2009)."""
    return int(min(12, max(2, round(n_obs ** (1.0 / 3.0)))))


def block_bootstrap_paths(
    returns: pd.DataFrame,
    months: int,
    n_paths: int,
    seed: int,
    mean_block: int | None = None,
) -> np.ndarray:
    """Stationary bootstrap (Politis & Romano 1994) of joint monthly return rows.

    Index recursion: with probability ``1 - 1/mean_block`` the next month continues
    the current block (previous index + 1, circular wrap), otherwise it restarts at a
    uniform index -- geometric block lengths with the given mean, rows always sampled
    JOINTLY so cross-asset correlation survives. Returns an array of shape
    ``(n_paths, months, n_assets)``. Same seed, same output (PCG64).
    """
    if months <= 0:
        raise ValueError(f"months must be > 0, got {months}")
    if n_paths <= 0:
        raise ValueError(f"n_paths must be > 0, got {n_paths}")
    values = returns.to_numpy(dtype=float)
    n_obs = values.shape[0]
    if n_obs < MIN_JOINT_OBSERVATIONS:
        raise ValueError(
            f"insufficient joint history: {n_obs} rows (< {MIN_JOINT_OBSERVATIONS})"
        )
    if np.isnan(values).any():
        raise ValueError("returns contain NaN: pass the output of monthly_returns")
    block = default_mean_block(n_obs) if mean_block is None else int(mean_block)
    if block < 1:
        raise ValueError(f"mean_block must be >= 1, got {mean_block}")

    rng = np.random.Generator(np.random.PCG64(seed))
    p_restart = 1.0 / block
    starts = rng.integers(0, n_obs, size=(n_paths, months))
    keep = rng.random((n_paths, months)) >= p_restart
    idx = np.empty((n_paths, months), dtype=np.int64)
    idx[:, 0] = starts[:, 0]
    for t in range(1, months):
        idx[:, t] = np.where(keep[:, t], (idx[:, t - 1] + 1) % n_obs, starts[:, t])
    return values[idx]
```

## Step 4 — Verifica che passano

Run: `uv run pytest tests/test_risk_math.py -q && uv run pytest -q && uv run ruff check .`
Output atteso: file di test verde, suite intera verde (vedi nota fallimento noto da
`config/portfolio.yaml` locale in overview.md del piano gemello), ruff `All checks passed!`

## Step 5 — Commit

```bash
git add src/portfolio_copilot/analytics/risk_math.py tests/test_risk_math.py \
  tests/fixtures/risk_math_closes.csv
git commit -m "feat(risk-math): joint monthly returns + stationary bootstrap (PPW 2009 block rule)"
```

## Criteri di accettazione
- [ ] Fixture 121 righe committabile e rigenerabile col comando dello Step 0
- [ ] `default_mean_block`: 68→4, 300→7, clamp [2, 12]
- [ ] Stesso seed → array identico; seed diverso → diverso
- [ ] Ogni riga campionata è una riga congiunta della sorgente
- [ ] Input invalidi (months/n_paths/mean_block/NaN/storia < 24) → `ValueError`
- [ ] Suite intera verde, ruff pulito
