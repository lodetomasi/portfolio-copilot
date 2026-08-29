import numpy as np
import pandas as pd

from portfolio_copilot.analytics.metrics import (
    annualized_volatility,
    concentration,
    max_drawdown,
    pct_return,
    safe_ratio,
)


def test_max_drawdown():
    s = pd.Series([100, 120, 90, 110])
    assert round(max_drawdown(s), 4) == -0.25


def test_max_drawdown_too_short_returns_none():
    assert max_drawdown(pd.Series([100])) is None


def test_concentration():
    c = concentration([0.5, 0.3, 0.2])
    assert c["top1"] == 0.5
    assert c["top3"] == 1.0
    assert round(c["hhi"], 4) == 0.38


def test_pct_return_normal_case():
    s = pd.Series([100, 105, 110, 121])
    assert round(pct_return(s, 3), 4) == 0.21


def test_pct_return_series_too_short_returns_none():
    s = pd.Series([100, 105])
    assert pct_return(s, 3) is None


def test_pct_return_zero_start_returns_none():
    s = pd.Series([0, 105, 110, 121])
    assert pct_return(s, 3) is None


def test_annualized_volatility_normal_case():
    rng = np.random.default_rng(42)
    prices = pd.Series(100 * np.cumprod(1 + rng.normal(0, 0.01, 40)))
    vol = annualized_volatility(prices)
    assert vol is not None
    assert vol > 0


def test_annualized_volatility_too_few_returns_none():
    s = pd.Series(range(100, 110))
    assert annualized_volatility(s) is None


def test_safe_ratio_finite_value():
    assert safe_ratio(10.0, 5.0, center=0.0) == 2.0


def test_safe_ratio_none_value_returns_none():
    assert safe_ratio(None, 5.0) is None


def test_safe_ratio_non_finite_value_returns_none():
    assert safe_ratio(float("nan"), 5.0) is None
    assert safe_ratio(float("inf"), 5.0) is None
