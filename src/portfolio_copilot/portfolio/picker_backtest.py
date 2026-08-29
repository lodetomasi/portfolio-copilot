"""Disclosed PROXY backtest of the stock-picker's scoring logic.

This is **not** the production scorer (``scoring/engine.py``). It answers a narrower
question offline and deterministically: on past data, would ranking stocks by a
*point-in-time-honest* proxy of growth/quality/momentum/revisions have picked names that
then outperformed a benchmark? Every input is filtered to what was actually knowable on
the rebalance date ``D`` -- no value dated after ``D`` may influence the score for ``D``.

Proxy components (each 0..100, ``None`` when the ticker has no usable data for it). Bounds
are copied verbatim from ``scoring.engine`` so this proxy tracks the shape of the real
scorer as closely as free, point-in-time-honest data allows:

- ``momentum``: price returns over the 3/6/12 months ending at ``D`` (same bounds as
  ``scoring.engine.score_snapshot``'s momentum sub-indicators).
- ``track_record``: beat-rate and average magnitude of earnings surprises reported on or
  before ``D`` -- built on ``yfinance_surprises.derive_surprise_stats`` (same >=4-quarter
  floor and 8-quarter window as the free-data revisions component in scoring.engine).
- ``fundamental_momentum``: YoY growth of revenue/EPS computed from the most recent
  as-filed fundamentals whose SEC ``filed`` date is on or before ``D`` -- a strictly
  point-in-time fundamental signal (no restated/backfilled numbers leak in).
- ``revision_momentum``: net analyst rating upgrades vs downgrades in the 90 days before
  ``D`` -- built on ``yfinance_estimates.derive_revision_momentum``, the same event-dated
  rating-change signal ``scoring.engine`` uses as ``revision_net_90d``. This is an
  EVENT-dated proxy (upgrade/downgrade actions), not a true point-in-time
  analyst-CONSENSUS revision feed (IBES/FactSet/Estimize are paid/gated and out of scope
  for a free provider) -- see the ``disclosures`` on every backtest run.

Components with no data are excluded from the weighted average and the score is
renormalised over the available weight, mirroring ``scoring.engine.score_snapshot``.

Nothing here touches the network. Callers assemble ``prices``/``surprises``/
``fundamentals``/``rating_events`` (e.g. from yfinance + SEC EDGAR, see
``scripts/picker_backtest_report.py``) and pass them in as plain data.
"""

from __future__ import annotations

import math
from statistics import mean
from typing import Any

import pandas as pd

from portfolio_copilot.providers.yfinance_estimates import derive_revision_momentum
from portfolio_copilot.providers.yfinance_surprises import SurpriseQuarter, derive_surprise_stats

# Weights are a simplified proxy of scoring.engine.DEFAULT_WEIGHTS: momentum and
# fundamental_momentum roughly cover growth+momentum, track_record stands in for
# quality/estimate reliability, revision_momentum stands in for revisions/catalysts.
# Absolute values don't matter (the score is a weighted mean re-normalised over whatever
# is available); only their relative proportions do.
DEFAULT_PROXY_WEIGHTS: dict[str, float] = {
    "momentum": 35,
    "fundamental_momentum": 25,
    "track_record": 20,
    "revision_momentum": 20,
}

_REVISION_WINDOW_DAYS = 90
_YOY_TOLERANCE_DAYS = 45
_PRICE_TOLERANCE_DAYS = 10
# Below this many trailing rating-change events, revision_momentum has no more statistical
# weight than track_record's below-4-quarters floor -- shrink it toward the neutral
# midpoint proportionally, rather than letting a single stale-but-in-window grade action
# from one obscure firm fully drive the score (finding 22).
_REVISION_MIN_EVENTS = 3


def _clamp(x: float) -> float:
    return max(0.0, min(100.0, float(x)))


def _linear(value: float | None, bad: float, good: float) -> float | None:
    """Same convention as scoring.engine._linear: clamp((value-bad)/(good-bad)*100, 0, 100)."""
    if value is None:
        return None
    if good == bad:
        return 50.0
    return _clamp((value - bad) / (good - bad) * 100.0)


def _avg(values: list[float | None]) -> float | None:
    present = [v for v in values if v is not None]
    return mean(present) if present else None


def _to_ts(value: Any) -> pd.Timestamp:
    """Parse to a naive Timestamp. Missing/unparsable input becomes NaT.

    NaT compares False against any bound (``NaT <= D`` is False), so a row with a
    missing or malformed date is naturally excluded from every point-in-time filter
    below rather than raising or being silently assumed "current".
    """
    if value is None:
        return pd.NaT
    try:
        ts = pd.Timestamp(value)
    except (ValueError, TypeError):
        return pd.NaT
    if ts is pd.NaT:
        return ts
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts


def _prepare_prices(prices: pd.Series | None) -> pd.Series:
    """Naive-tz, sorted, NaN-free copy. Never mutates the caller's Series."""
    if prices is None or len(prices) == 0:
        return pd.Series(dtype=float, index=pd.DatetimeIndex([]))
    out = prices.dropna().copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    if out.index.tz is not None:
        out.index = out.index.tz_localize(None)
    return out.sort_index()


def _price_asof(prices: pd.Series, target: pd.Timestamp, tolerance_days: int) -> float | None:
    """Last known price at or before ``target``, only if within ``tolerance_days`` of it.

    The tolerance rejects stale matches (e.g. a price series that ends long before the
    target date) instead of silently returning an unrelated old price.
    """
    at_or_before = prices[prices.index <= target]
    if at_or_before.empty:
        return None
    actual = at_or_before.index[-1]
    if (target - actual).days > tolerance_days:
        return None
    return float(at_or_before.iloc[-1])


def _return_over_months(prices: pd.Series, as_of: pd.Timestamp, months: int) -> float | None:
    end_price = _price_asof(prices, as_of, _PRICE_TOLERANCE_DAYS)
    if end_price is None:
        return None
    start_price = _price_asof(prices, as_of - pd.DateOffset(months=months), _PRICE_TOLERANCE_DAYS)
    if start_price is None or start_price == 0:
        return None
    return end_price / start_price - 1.0


def _momentum_component(prices: pd.Series, as_of: pd.Timestamp) -> float | None:
    clean = prices[prices.index <= as_of]
    return _avg(
        [
            _linear(_return_over_months(clean, as_of, 3), -0.20, 0.30),
            _linear(_return_over_months(clean, as_of, 6), -0.30, 0.50),
            _linear(_return_over_months(clean, as_of, 12), -0.40, 0.80),
        ]
    )


def _track_record_component(surprises: list[dict] | None, as_of: pd.Timestamp) -> float | None:
    """Beat-rate and average surprise magnitude, via ``yfinance_surprises.derive_surprise_stats``.

    ``surprises`` entries: ``{"earnings_date": date-like, "surprise_pct": float | None,
    ...}`` -- the ``SurpriseQuarter`` shape (a fraction, e.g. 0.05 for a 5% beat). A row
    that doesn't validate as a ``SurpriseQuarter`` is dropped rather than raising. The
    shared helper already enforces point-in-time filtering (``earnings_date <= as_of``)
    and requires at least 4 usable quarters, same as the free-data revisions component.
    """
    if pd.isna(as_of):
        return None
    quarters: list[SurpriseQuarter] = []
    for s in surprises or []:
        if isinstance(s, SurpriseQuarter):
            quarters.append(s)
            continue
        try:
            quarters.append(SurpriseQuarter(**s))
        except (TypeError, ValueError):
            continue
    stats = derive_surprise_stats(quarters, as_of.date())
    return _avg(
        [
            _linear(stats["surprise_positive_share_8q"], 0.25, 0.9),
            _linear(stats["surprise_mean_8q"], -0.05, 0.10),
        ]
    )


def _yoy_growth(fundamentals: list[dict] | None, as_of: pd.Timestamp) -> tuple[
    float | None, float | None
]:
    """YoY revenue/EPS growth from the latest as-filed rows knowable by ``as_of``.

    ``fundamentals`` entries: ``{"end": date-like, "filed": date-like, "revenue": float |
    None, "eps": float | None}``. Only rows with ``filed <= as_of`` are considered
    (strict point-in-time); the "prior year" row is the one whose ``end`` is closest to
    (latest end - 12 months), within ``_YOY_TOLERANCE_DAYS``.
    """
    rows = []
    for row in fundamentals or []:
        filed = _to_ts(row.get("filed"))
        end = _to_ts(row.get("end"))
        if filed <= as_of and not pd.isna(end):
            rows.append({**row, "_end_ts": end})
    if not rows:
        return None, None
    rows.sort(key=lambda r: r["_end_ts"], reverse=True)
    latest = rows[0]
    target_prior = latest["_end_ts"] - pd.DateOffset(months=12)
    candidates = [
        r for r in rows[1:] if abs((r["_end_ts"] - target_prior).days) <= _YOY_TOLERANCE_DAYS
    ]
    if not candidates:
        return None, None
    prior = min(candidates, key=lambda r: abs((r["_end_ts"] - target_prior).days))

    def _growth(field: str) -> float | None:
        cur, prev = latest.get(field), prior.get(field)
        if cur is None or prev is None or prev == 0:
            return None
        return cur / prev - 1.0

    return _growth("revenue"), _growth("eps")


def _fundamental_momentum_component(
    fundamentals: list[dict] | None, as_of: pd.Timestamp
) -> float | None:
    revenue_growth, eps_growth = _yoy_growth(fundamentals, as_of)
    return _avg([_linear(revenue_growth, -0.10, 0.30), _linear(eps_growth, -0.20, 0.40)])


def _revision_momentum_component(
    rating_events: list[dict] | None, as_of: pd.Timestamp
) -> float | None:
    """Net upgrades minus downgrades in the trailing window, via ``derive_revision_momentum``.

    ``rating_events`` entries: ``{"date": date-like, "action": "up" | "down" | ...}`` -- the
    shape ``yfinance_estimates.fetch_rating_events`` returns (Action: main/up/down/init/reit;
    only "up"/"down" count). ``None`` (no data at all) only when the ticker has no rating
    history whatsoever (e.g. a non-US/ADR ticker); an empty window with real coverage scores
    a neutral 50.0, exactly as ``scoring.engine``'s ``revision_net_90d`` sub-indicator does.

    Below ``_REVISION_MIN_EVENTS`` trailing events, the raw value is shrunk toward the
    neutral 50 proportionally to how many events actually happened -- a single grade
    action from one firm is as statistically thin as 1-3 quarters of earnings history,
    which ``track_record`` correctly refuses to trust at full weight.
    """
    if pd.isna(as_of):
        return None
    momentum = derive_revision_momentum(rating_events or [], as_of.date(), _REVISION_WINDOW_DAYS)
    net = momentum["net_upgrades_90d"]
    if net is None:
        return None
    value = _linear(net, -4, 4)
    n_events = momentum["n_events_90d"] or 0
    if n_events < _REVISION_MIN_EVENTS:
        value = 50.0 + (value - 50.0) * n_events / _REVISION_MIN_EVENTS
    return value


def proxy_score_at(
    date: Any,
    prices: pd.Series | None,
    surprises: list[dict] | None,
    fundamentals: list[dict] | None,
    rating_events: list[dict] | None = None,
    weights: dict[str, float] | None = None,
) -> dict:
    """Point-in-time proxy score for one ticker as of ``date``.

    Every input is filtered internally to what was knowable on or before ``date`` --
    callers may pass full histories; nothing after ``date`` can influence the result.

    Returns ``{"as_of", "score" (0..100), "components" (name -> 0..100, 50.0 fallback
    when unavailable), "available" (name -> bool)}``.
    """
    as_of = _to_ts(date)
    weights = weights or DEFAULT_PROXY_WEIGHTS
    clean_prices = _prepare_prices(prices)

    raw = {
        "momentum": _momentum_component(clean_prices, as_of),
        "track_record": _track_record_component(surprises, as_of),
        "fundamental_momentum": _fundamental_momentum_component(fundamentals, as_of),
        "revision_momentum": _revision_momentum_component(rating_events, as_of),
    }

    components: dict[str, float] = {}
    available: dict[str, bool] = {}
    weighted_sum = 0.0
    available_weight = 0.0
    for name, weight in weights.items():
        value = raw.get(name)
        if value is None:
            components[name] = 50.0
            available[name] = False
            continue
        components[name] = _clamp(value)
        available[name] = True
        weighted_sum += value * weight
        available_weight += weight

    score = weighted_sum / available_weight if available_weight else 50.0
    return {
        "as_of": as_of.date().isoformat() if not pd.isna(as_of) else None,
        "score": _clamp(score),
        "components": components,
        "available": available,
    }


def _forward_return(
    prices: pd.Series | None, as_of: pd.Timestamp, horizon_months: int
) -> float | None:
    """Equal-weight-friendly forward return from ``as_of`` to ``as_of + horizon_months``.

    ``None`` when either endpoint is missing or too far (> ``_PRICE_TOLERANCE_DAYS``) from
    an actual data point -- never a return computed against a stale/unrelated price.
    """
    clean = _prepare_prices(prices)
    start_price = _price_asof(clean, as_of, _PRICE_TOLERANCE_DAYS)
    if start_price is None or start_price == 0:
        return None
    target = as_of + pd.DateOffset(months=horizon_months)
    future = clean[clean.index > as_of]
    if future.empty:
        return None
    at_or_before_target = future[future.index <= target]
    if at_or_before_target.empty:
        return None
    end_date = at_or_before_target.index[-1]
    if (target - end_date).days > _PRICE_TOLERANCE_DAYS:
        return None
    return float(at_or_before_target.iloc[-1]) / start_price - 1.0


def _t_stat(values: list[float]) -> float | None:
    """One-sample t-statistic of ``values`` against 0.

    ``None`` if undefined (fewer than 2 values, or zero variance).
    """
    n = len(values)
    if n < 2:
        return None
    m = mean(values)
    variance = sum((x - m) ** 2 for x in values) / (n - 1)
    if variance == 0:
        return None
    se = math.sqrt(variance / n)
    return m / se


_MANDATORY_DISCLOSURES = [
    "Survivorship bias: the universe is today's tickers, not the historically investable "
    "set at each rebalance date -- delisted/acquired/renamed names are absent.",
    "Yahoo backfill risk: earnings-surprise history can be silently revised by Yahoo after "
    "the fact; historical rows reflect Yahoo's current record of that quarter, not a "
    "strictly point-in-time snapshot.",
    "Transaction costs, taxes and slippage are excluded from every forward return.",
    "revision_momentum is derived from analyst rating-CHANGE events (upgrades/downgrades), "
    "not from a true point-in-time analyst-consensus revision feed -- IBES/FactSet/Estimize "
    "are paid or account-gated and out of scope for a free provider.",
    "revision_momentum is shrunk toward neutral below 3 trailing rating-change events, but "
    "even at full weight it can rest on very few events for a thinly-covered name -- unlike "
    "a market-cap or index filter, this is not a floor on which names can be scored.",
]


def run_proxy_backtest(
    universe: dict[str, dict],
    benchmark_prices: pd.Series,
    rebalance_dates: list[Any],
    horizon_months: int,
    top_quantile: float = 0.2,
    weights: dict[str, float] | None = None,
) -> dict:
    """Rank ``universe`` by the proxy score at each rebalance date, hold the top quantile.

    ``universe``: ``ticker -> {"prices": pd.Series, "surprises": [...], "fundamentals":
    [...], "rating_events": [...] | omitted}``. A ticker with no usable component data, or
    with no computable forward return, is skipped for that date and counted in
    ``n_skipped`` -- it never raises and never silently drops out of the count.

    Returns ``{"rows": [...], "mean_excess", "hit_rate", "n_periods", "t_stat",
    "disclosures"}``. ``disclosures`` is always non-empty; a sample-size warning is added
    when ``n_periods < 8`` (too few independent periods to trust a t-stat).
    """
    rows: list[dict] = []
    for raw_date in rebalance_dates:
        as_of = _to_ts(raw_date)
        scored: list[tuple[str, float, float]] = []
        n_skipped = 0
        for ticker, data in universe.items():
            try:
                result = proxy_score_at(
                    as_of,
                    data.get("prices"),
                    data.get("surprises", []),
                    data.get("fundamentals", []),
                    data.get("rating_events"),
                    weights=weights,
                )
            except (KeyError, ValueError, TypeError, AttributeError):
                n_skipped += 1
                continue
            if not any(result["available"].values()):
                n_skipped += 1
                continue
            fwd = _forward_return(data.get("prices"), as_of, horizon_months)
            if fwd is None:
                n_skipped += 1
                continue
            scored.append((ticker, result["score"], fwd))

        scored.sort(key=lambda t: (-t[1], t[0]))
        n_scored = len(scored)
        n_top = max(1, round(n_scored * top_quantile)) if n_scored else 0
        top = scored[:n_top]
        top_return = mean(r for _, _, r in top) if top else None
        benchmark_return = _forward_return(benchmark_prices, as_of, horizon_months)
        excess = (
            top_return - benchmark_return
            if top_return is not None and benchmark_return is not None
            else None
        )
        hit = excess > 0 if excess is not None else None

        rows.append(
            {
                "date": as_of.date().isoformat() if not pd.isna(as_of) else None,
                "n_scored": n_scored,
                "n_top": n_top,
                "n_skipped": n_skipped,
                "top_return": top_return,
                "benchmark_return": benchmark_return,
                "excess": excess,
                "hit": hit,
            }
        )

    excesses = [r["excess"] for r in rows if r["excess"] is not None]
    hits = [r["hit"] for r in rows if r["hit"] is not None]
    n_periods = len(excesses)

    disclosures = list(_MANDATORY_DISCLOSURES)
    if n_periods < 8:
        disclosures.append(
            f"Only {n_periods} period(s) with a computable excess return: not "
            "distinguishable from luck (too small a sample for a reliable t-stat)."
        )

    return {
        "rows": rows,
        "mean_excess": mean(excesses) if excesses else None,
        "hit_rate": (sum(1 for h in hits if h) / len(hits)) if hits else None,
        "n_periods": n_periods,
        "t_stat": _t_stat(excesses) if n_periods >= 8 else None,
        "disclosures": disclosures,
    }
