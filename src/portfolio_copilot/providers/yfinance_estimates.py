"""Free analyst-estimate and rating-event data from Yahoo (via yfinance), tier B.

Two different kinds of free data live here, and they are not equally point-in-time:

- *estimate snapshots* (``get_earnings_estimate``, ``get_revenue_estimate``,
  ``get_eps_revisions``, ``get_recommendations_summary``, ``get_analyst_price_targets``,
  ``get_calendar``) are Yahoo's *current* consensus view -- calling them for a past ``as_of``
  still returns today's numbers, never a historical snapshot;
- *rating events* (``Ticker.upgrades_downgrades``) carry a real ``GradeDate`` timestamp per
  row and so can be honestly filtered to "everything known as of ``as_of``" -- but Yahoo only
  populates this for US-listed names and US ADRs; pure European local lines (e.g. ENEL.MI,
  ASML.AS) come back with an empty table.

Neither limitation is hidden: every result carries ``source``/``as_of``/``confidence`` and a
``missing_fields`` list explaining, field by field, what could not be computed and why.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from pydantic import BaseModel

from portfolio_copilot.providers.cache import TTLCache

_CACHE = TTLCache(ttl_seconds=6 * 3600)

_TRACKED_FIELDS = (
    "est_eps_growth_1y",
    "est_revenue_growth_1y",
    "eps_revisions_up_30d",
    "eps_revisions_down_30d",
    "revision_balance",
    "analyst_count",
    "consensus_score",
    "target_upside",
    "next_earnings_date",
    "revision_events_90d",
)


class AnalystEstimates(BaseModel):
    """Free-data proxy for analyst consensus, revisions and upcoming catalysts.

    Every estimate field is ``None`` (never fabricated) when Yahoo does not have it for this
    ticker; ``provenance['confidence']`` reflects how many of the ``_TRACKED_FIELDS`` fields
    actually came back.
    """

    ticker: str
    est_eps_growth_1y: float | None = None
    est_revenue_growth_1y: float | None = None
    eps_revisions_up_30d: int | None = None
    eps_revisions_down_30d: int | None = None
    revision_balance: float | None = None
    analyst_count: int | None = None
    consensus_score: float | None = None
    target_upside: float | None = None
    next_earnings_date: str | None = None
    days_to_next_earnings: int | None = None
    revision_net_90d: int | None = None
    revision_pt_change_90d: float | None = None
    revision_events_90d: int | None = None
    provenance: dict[str, Any]


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
        return value if np.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _s(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return str(value)


def _coerce_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError):
        return None


def _period_value(df: pd.DataFrame | None, column: str, period: str) -> float | None:
    """``df.loc[period, column]`` for a DataFrame indexed by period, NaN-safe."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    if period not in df.index or column not in df.columns:
        return None
    return _f(df.loc[period, column])


def _growth_1y(df: pd.DataFrame | None, column: str) -> float | None:
    """``df[column]['+1y'] / df[column]['0y'] - 1``, only when both base values are > 0."""
    current = _period_value(df, column, "0y")
    forward = _period_value(df, column, "+1y")
    if current is None or forward is None or current <= 0 or forward <= 0:
        return None
    return forward / current - 1.0


def _revisions_sum(df: pd.DataFrame | None, column: str) -> float | None:
    """Sum of ``column`` over periods '0y' and '+1y'; ``None`` if neither is present."""
    if not isinstance(df, pd.DataFrame) or df.empty:
        return None
    total = 0.0
    found = False
    for period in ("0y", "+1y"):
        value = _period_value(df, column, period)
        if value is not None:
            total += value
            found = True
    return total if found else None


def _revision_balance(up: float | None, down: float | None) -> float | None:
    if up is None or down is None:
        return None
    total = up + down
    if total == 0:
        return None
    return (up - down) / total


def _row_for_period(df: pd.DataFrame | None, period: str) -> pd.Series | None:
    """``get_recommendations_summary()`` carries 'period' as a plain column, not the index."""
    if not isinstance(df, pd.DataFrame) or df.empty or "period" not in df.columns:
        return None
    matches = df[df["period"] == period]
    return matches.iloc[0] if not matches.empty else None


def _consensus_score(df: pd.DataFrame | None) -> float | None:
    """Weighted analyst-recommendation balance in ``[-1.0, 1.0]``: +1.0 only for unanimous
    strongBuy, -1.0 only for unanimous strongSell. Normalized by ``2 * total`` (the true
    maximum magnitude of the ``2*strongBuy + buy - sell - 2*strongSell`` numerator), not by
    ``total`` alone -- dividing by ``total`` would let the ratio reach +-2, saturating
    ``scoring.engine``'s ``_linear(..., -1.0, 1.0)`` consumer for many non-unanimous mixes."""
    row = _row_for_period(df, "0m")
    if row is None:
        return None
    counts = {c: _f(row.get(c)) or 0.0 for c in ("strongBuy", "buy", "hold", "sell", "strongSell")}
    total = sum(counts.values())
    if total == 0:
        return None
    numerator = 2 * counts["strongBuy"] + counts["buy"] - counts["sell"] - 2 * counts["strongSell"]
    return numerator / (2 * total)


def _recommendations_total(df: pd.DataFrame | None) -> float | None:
    row = _row_for_period(df, "0m")
    if row is None:
        return None
    counts = [_f(row.get(c)) for c in ("strongBuy", "buy", "hold", "sell", "strongSell")]
    counts = [c for c in counts if c is not None]
    return sum(counts) if counts else None


def _target_upside(targets: dict | None) -> float | None:
    if not isinstance(targets, dict):
        return None
    mean = _f(targets.get("mean"))
    current = _f(targets.get("current"))
    if mean is None or current is None or current == 0:
        return None
    return mean / current - 1.0


def _next_earnings(calendar: dict | None, as_of: date) -> tuple[str | None, int | None]:
    if not isinstance(calendar, dict):
        return None, None
    raw_dates = calendar.get("Earnings Date") or []
    parsed = (_coerce_date(v) for v in raw_dates)
    candidates = sorted(d for d in parsed if d is not None and d >= as_of)
    if not candidates:
        return None, None
    chosen = candidates[0]
    return chosen.isoformat(), (chosen - as_of).days


def _extract_rating_events(t: Any, as_of: date) -> list[dict]:
    df = t.upgrades_downgrades
    if not isinstance(df, pd.DataFrame) or df.empty:
        return []
    events: list[dict] = []
    for grade_date, row in df.iterrows():
        # pd.Timestamp(pd.NaT).date() returns NaT itself, not None -- catch it before
        # _coerce_date so one malformed row is dropped, not the ticker's whole history
        # (comparing NaT > a real date raises TypeError).
        if pd.isna(grade_date):
            continue
        d = _coerce_date(grade_date)
        if d is None or d > as_of:
            continue
        events.append(
            {
                "date": d.isoformat(),
                "firm": _s(row.get("Firm")),
                "action": _s(row.get("Action")),
                "from_grade": _s(row.get("FromGrade")),
                "to_grade": _s(row.get("ToGrade")),
                "pt_action": _s(row.get("priceTargetAction")),
                "pt_prior": _f(row.get("priorPriceTarget")),
                "pt_current": _f(row.get("currentPriceTarget")),
            }
        )
    events.sort(key=lambda e: e["date"], reverse=True)
    return events


def fetch_rating_events(
    ticker: str, as_of: date, ticker_factory: Callable[[str], Any] = yf.Ticker
) -> list[dict]:
    """Point-in-time analyst rating/price-target events (``GradeDate <= as_of``), newest first.

    US-listed names and US ADRs only -- Yahoo does not populate ``upgrades_downgrades`` for
    pure European local lines, which come back as an empty list here rather than an error.
    """
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("Ticker is required")
    t = ticker_factory(symbol)
    try:
        return _extract_rating_events(t, as_of)
    except Exception:
        return []


def derive_revision_momentum(
    events: list[dict], as_of: date, window_days: int = 90
) -> dict[str, float | int | None]:
    """Rating-change momentum over the trailing ``window_days`` ending at ``as_of``.

    ``events`` is expected already point-in-time filtered (see ``fetch_rating_events``); an
    empty ``events`` list means no rating history exists at all (e.g. a non-US/ADR ticker),
    so every field comes back ``None`` -- never a fabricated zero -- letting callers tell "no
    coverage" apart from "covered, nothing happened in the window".
    """
    if not events:
        return {
            "net_upgrades_90d": None,
            "upgrades_90d": None,
            "downgrades_90d": None,
            "pt_change_pct_90d": None,
            "n_events_90d": None,
        }
    window_start = as_of - timedelta(days=window_days)
    in_window = []
    for e in events:
        d = _coerce_date(e.get("date"))
        if d is not None and window_start <= d <= as_of:
            in_window.append(e)
    upgrades = sum(1 for e in in_window if e.get("action") == "up")
    downgrades = sum(1 for e in in_window if e.get("action") == "down")
    pt_changes = [
        e["pt_current"] / e["pt_prior"] - 1.0
        for e in in_window
        if e.get("pt_prior") not in (None, 0) and e.get("pt_current") is not None
    ]
    return {
        "net_upgrades_90d": upgrades - downgrades,
        "upgrades_90d": upgrades,
        "downgrades_90d": downgrades,
        "pt_change_pct_90d": (sum(pt_changes) / len(pt_changes)) if pt_changes else None,
        "n_events_90d": len(in_window),
    }


def _safe_call(
    missing: list[str], label: str, call_name: str, fn: Callable[[], Any]
) -> tuple[Any, bool]:
    """Run one yfinance module call, recording ``label: call_name failed (...)`` in
    ``missing`` on exception. Returns ``(value, failed)`` so callers can skip re-explaining
    an already-logged failure when they check the derived field for ``None``."""
    try:
        return fn(), False
    except Exception as exc:
        missing.append(f"{label}: {call_name} failed ({exc!r})")
        return None, True


def fetch_estimates(
    ticker: str, as_of: date, ticker_factory: Callable[[str], Any] = yf.Ticker
) -> AnalystEstimates:
    """Best-effort analyst-consensus snapshot for ``ticker``, degrading field by field.

    Each underlying yfinance call is wrapped separately (see ``_safe_call``) so one failing
    module (rate limit, missing data, a foreign ticker Yahoo doesn't cover) only takes down
    the fields it feeds -- never the whole result -- and the reason is recorded in
    ``provenance['missing_fields']``.
    """
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("Ticker is required")

    cache_key = f"{symbol}:{as_of.isoformat()}"
    cached = _CACHE.get(cache_key)
    if cached is not None:
        return cached

    t = ticker_factory(symbol)
    missing: list[str] = []
    call_failures: list[bool] = []

    earnings_df, failed = _safe_call(
        missing,
        "est_eps_growth_1y,analyst_count",
        "get_earnings_estimate()",
        t.get_earnings_estimate,
    )
    call_failures.append(failed)
    est_eps_growth_1y = _growth_1y(earnings_df, "avg")
    if est_eps_growth_1y is None and not failed:
        missing.append("est_eps_growth_1y: not available in earnings estimate data")
    analyst_count_earnings = _period_value(earnings_df, "numberOfAnalysts", "+1y")

    revenue_df, failed = _safe_call(
        missing, "est_revenue_growth_1y", "get_revenue_estimate()", t.get_revenue_estimate
    )
    call_failures.append(failed)
    est_revenue_growth_1y = _growth_1y(revenue_df, "avg")
    if est_revenue_growth_1y is None and not failed:
        missing.append("est_revenue_growth_1y: not available in revenue estimate data")

    revisions_df, failed = _safe_call(
        missing,
        "eps_revisions_up_30d,eps_revisions_down_30d",
        "get_eps_revisions()",
        t.get_eps_revisions,
    )
    call_failures.append(failed)
    revisions_up = _revisions_sum(revisions_df, "upLast30days")
    revisions_down = _revisions_sum(revisions_df, "downLast30days")
    if not failed:
        if revisions_up is None:
            missing.append("eps_revisions_up_30d: not available in eps revisions data")
        if revisions_down is None:
            missing.append("eps_revisions_down_30d: not available in eps revisions data")
    revision_balance = _revision_balance(revisions_up, revisions_down)
    if revision_balance is None and revisions_up is not None and revisions_down is not None:
        missing.append("revision_balance: up and down revisions are both zero")

    recs_df, failed = _safe_call(
        missing, "consensus_score", "get_recommendations_summary()", t.get_recommendations_summary
    )
    call_failures.append(failed)
    consensus_score = _consensus_score(recs_df)
    analyst_count_recs = _recommendations_total(recs_df)
    if consensus_score is None and not failed:
        missing.append("consensus_score: not available in recommendations summary")

    analyst_count = (
        analyst_count_earnings if analyst_count_earnings is not None else analyst_count_recs
    )
    if analyst_count is None:
        missing.append(
            "analyst_count: not available from earnings estimate or recommendations summary"
        )

    targets, failed = _safe_call(
        missing, "target_upside", "get_analyst_price_targets()", t.get_analyst_price_targets
    )
    call_failures.append(failed)
    target_upside = _target_upside(targets)
    if target_upside is None and not failed:
        missing.append("target_upside: not available in analyst price targets")

    calendar, failed = _safe_call(missing, "next_earnings_date", "get_calendar()", t.get_calendar)
    call_failures.append(failed)
    try:
        next_earnings_date, days_to_next_earnings = _next_earnings(calendar, as_of)
    except Exception as exc:
        next_earnings_date, days_to_next_earnings = None, None
        missing.append(f"next_earnings_date: malformed calendar payload ({exc!r})")
        call_failures.append(True)
    else:
        if next_earnings_date is None and not failed:
            missing.append("next_earnings_date: no upcoming earnings date in calendar")

    try:
        events = _extract_rating_events(t, as_of)
    except Exception as exc:
        events = []
        missing.append(f"revision_events_90d: upgrades_downgrades failed ({exc!r})")
        call_failures.append(True)
    else:
        call_failures.append(False)
        if not events:
            missing.append(
                "revision_events_90d: no rating-change history available (non-US/ADR ticker "
                "or no coverage)"
            )
    momentum = derive_revision_momentum(events, as_of)

    coverage_values = {
        "est_eps_growth_1y": est_eps_growth_1y,
        "est_revenue_growth_1y": est_revenue_growth_1y,
        "eps_revisions_up_30d": revisions_up,
        "eps_revisions_down_30d": revisions_down,
        "revision_balance": revision_balance,
        "analyst_count": analyst_count,
        "consensus_score": consensus_score,
        "target_upside": target_upside,
        "next_earnings_date": next_earnings_date,
        "revision_events_90d": momentum["n_events_90d"],
    }
    available = sum(1 for name in _TRACKED_FIELDS if coverage_values[name] is not None)

    result = AnalystEstimates(
        ticker=symbol,
        est_eps_growth_1y=est_eps_growth_1y,
        est_revenue_growth_1y=est_revenue_growth_1y,
        eps_revisions_up_30d=round(revisions_up) if revisions_up is not None else None,
        eps_revisions_down_30d=round(revisions_down) if revisions_down is not None else None,
        revision_balance=revision_balance,
        analyst_count=round(analyst_count) if analyst_count is not None else None,
        consensus_score=consensus_score,
        target_upside=target_upside,
        next_earnings_date=next_earnings_date,
        days_to_next_earnings=days_to_next_earnings,
        revision_net_90d=momentum["net_upgrades_90d"],
        revision_pt_change_90d=momentum["pt_change_pct_90d"],
        revision_events_90d=momentum["n_events_90d"],
        provenance={
            "source": "yfinance",
            "tier": "B",
            "as_of": as_of.isoformat(),
            "confidence": round(available / len(_TRACKED_FIELDS), 4),
            "missing_fields": missing,
            "notes": [
                "Rating-change events (upgrades/downgrades, price-target changes) are "
                "genuine event-dated data filtered to as_of; earnings/revenue estimate, "
                "revisions and recommendation snapshots are Yahoo's current consensus and "
                "are NOT strictly point-in-time even when as_of is in the past."
            ],
        },
    )
    # A fully-failed fetch (e.g. a transient rate limit) is not the same as confirmed-empty
    # data: caching it as truth would serve stale zero-signal results for the full TTL
    # instead of letting the next call retry. Only skip the cache write in that all-failed
    # case; a partial or fully-successful result is cached as before.
    if not all(call_failures):
        _CACHE.set(cache_key, result)
    return result
