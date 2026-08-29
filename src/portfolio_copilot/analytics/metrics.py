from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def pct_return(prices: pd.Series, periods: int) -> float | None:
    clean = prices.dropna()
    if len(clean) <= periods:
        return None
    start = float(clean.iloc[-periods - 1])
    end = float(clean.iloc[-1])
    if start == 0:
        return None
    return end / start - 1.0


def annualized_volatility(prices: pd.Series) -> float | None:
    rets = prices.dropna().pct_change().dropna()
    if len(rets) < 20:
        return None
    return float(rets.std(ddof=1) * math.sqrt(TRADING_DAYS))


def max_drawdown(prices: pd.Series) -> float | None:
    clean = prices.dropna()
    if len(clean) < 2:
        return None
    running_max = clean.cummax()
    # Drawdown is undefined before any capital has ever been at risk (running_max <= 0,
    # e.g. an all-zero backtest value series with nothing invested yet): dividing by a
    # zero/negative peak yields NaN or a meaningless ratio, not a real drawdown. Mask
    # those points out and report None if no positive peak was ever reached, rather than
    # leaking NaN (CLAUDE.md: never invent/leak an undefined datum).
    valid = running_max > 0
    if not valid.any():
        return None
    dd = clean[valid] / running_max[valid] - 1.0
    return float(dd.min())


def hhi(weights: list[float]) -> float:
    arr = np.asarray(weights, dtype=float)
    return float(np.sum(arr**2))


def concentration(weights: list[float]) -> dict[str, float]:
    ordered = sorted(weights, reverse=True)
    return {
        "top1": float(sum(ordered[:1])),
        "top3": float(sum(ordered[:3])),
        "top5": float(sum(ordered[:5])),
        "hhi": hhi(ordered),
    }


def safe_ratio(value: float | None, scale: float, center: float = 0.0) -> float | None:
    if value is None or not np.isfinite(value):
        return None
    return float((value - center) / scale)
