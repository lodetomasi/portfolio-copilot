"""Earnings-surprise track record from Yahoo's free earnings calendar.

``yf.Ticker(ticker).get_earnings_dates()`` is a scrape of Yahoo's HTML earnings calendar,
not a paid point-in-time consensus database (IBES/Zacks/FactSet/Estimize are all paid or
account-gated). It is the best free proxy available: 5-12 years of quarterly EPS
estimate/actual/surprise for well-covered US names, thinner for small caps and European
tickers. Two caveats apply to everything this module returns:

* Yahoo can silently backfill past rows, so a historical row reflects "Yahoo's current
  record of that quarter", not a strict point-in-time snapshot -- confidence is capped
  accordingly (never above 0.6) and the caveat travels with every result as ``note``.
* the endpoint is fragile (HTML scrape, HTTP 429 possible), so every fetch is wrapped and
  degrades to an empty, clearly-labelled history rather than raising or fabricating rows.

Tier B source (Yahoo aggregator, like the rest of ``yfinance_provider.py``). Results are
cached 24h per ``(ticker, limit)`` -- the raw, unfiltered rows are what gets cached, so a
caller sweeping many ``as_of`` dates against the same ticker (e.g. a backtest) reuses one
fetch and re-derives stats per date via :func:`derive_surprise_stats`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pandas as pd
import yfinance as yf
from pydantic import BaseModel, Field

from portfolio_copilot.models import Provenance
from portfolio_copilot.providers.cache import TTLCache

SOURCE = "yfinance_earnings_dates"
TIER = "B"
NOTE = "Yahoo can backfill past rows; not strict point-in-time"

_cache = TTLCache(ttl_seconds=24 * 3600)
# A raised exception (rate limit, transient scrape failure) is not "confirmed no data" --
# negative-cache it far more briefly than a successful/empty fetch so a persistently-bad
# ticker in a large universe screen isn't re-queried on every call, but still self-heals.
_NEGATIVE_CACHE_TTL_SECONDS = 15 * 60


def _f(value: Any) -> float | None:
    """NaN/None/unparseable -> None; otherwise a finite float."""
    if value is None:
        return None
    try:
        value = float(value)
        return value if np.isfinite(value) else None
    except (TypeError, ValueError):
        return None


class SurpriseQuarter(BaseModel):
    """One quarter from Yahoo's earnings calendar."""

    earnings_date: date
    eps_estimate: float | None = None
    reported_eps: float | None = None
    surprise_pct: float | None = None  # fraction, e.g. 0.0674 for a 6.74% beat


class SurpriseHistory(BaseModel):
    """Point-in-time-filterable earnings-surprise track record for one ticker.

    ``quarters`` only ever holds reported quarters (``reported_eps`` present) with
    ``earnings_date <= as_of``, sorted ascending. The four derived stats are ``None``
    together when fewer than 4 such quarters are available -- not degraded individually,
    since a mean/share/streak over 1-3 data points is not a usable signal.
    """

    ticker: str
    quarters: list[SurpriseQuarter] = Field(default_factory=list)
    surprise_mean_8q: float | None = None
    surprise_positive_share_8q: float | None = None
    surprise_streak: int | None = None
    quarters_available: int | None = None
    note: str = NOTE
    provenance: Provenance


def _point_in_time(quarters: list[SurpriseQuarter], as_of: date) -> list[SurpriseQuarter]:
    """Reported quarters with ``earnings_date <= as_of``, sorted ascending."""
    return sorted(
        (q for q in quarters if q.earnings_date <= as_of and q.reported_eps is not None),
        key=lambda q: q.earnings_date,
    )


def derive_surprise_stats(quarters: list[SurpriseQuarter], as_of: date) -> dict:
    """Point-in-time surprise stats over already-fetched quarters.

    Pure and reusable: :func:`fetch_surprise_history` calls it on freshly-fetched rows,
    and a backtest can call it again on the same rows for a different ``as_of`` without
    re-fetching. Filters to ``earnings_date <= as_of`` with a reported EPS, keeps the
    trailing window of up to 8 of those, and returns ``None`` for every derived stat
    (including ``quarters_available``) when fewer than 4 usable quarters remain.
    """
    usable = _point_in_time(quarters, as_of)
    n = len(usable)
    if n < 4:
        return {
            "surprise_mean_8q": None,
            "surprise_positive_share_8q": None,
            "surprise_streak": None,
            "quarters_available": None,
        }

    window = usable[-8:]
    pct_values = [q.surprise_pct for q in window if q.surprise_pct is not None]
    mean = sum(pct_values) / len(pct_values) if pct_values else None
    positive_share = sum(1 for v in pct_values if v > 0) / len(pct_values) if pct_values else None

    streak = 0
    for q in reversed(usable):
        if q.surprise_pct is not None and q.surprise_pct > 0:
            streak += 1
        else:
            break

    return {
        "surprise_mean_8q": mean,
        "surprise_positive_share_8q": positive_share,
        "surprise_streak": streak,
        "quarters_available": n,
    }


def _quarters_from_dataframe(df: pd.DataFrame | None) -> list[SurpriseQuarter]:
    """Parse yfinance's ``get_earnings_dates()`` frame into ``SurpriseQuarter`` rows.

    Handles a tz-aware (or tz-naive) ``DatetimeIndex``, NaN cells (unreported/estimate
    missing), and converts Yahoo's ``Surprise(%)`` (a percent, e.g. ``6.74``) to a
    fraction (``0.0674``) for consistency with the rest of this module's stats. A
    duplicated/reissued row for the same ``GradeDate`` (Yahoo's scrape is not guaranteed
    to avoid this) is deduplicated, keeping the last occurrence, so it cannot inflate
    ``quarters_available`` or double-count that quarter in the derived stats.
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return []
    df = df[~df.index.duplicated(keep="last")]
    rows: list[SurpriseQuarter] = []
    for ts, row in df.iterrows():
        if pd.isna(ts):
            continue
        surprise = _f(row.get("Surprise(%)"))
        rows.append(
            SurpriseQuarter(
                earnings_date=pd.Timestamp(ts).date(),
                eps_estimate=_f(row.get("EPS Estimate")),
                reported_eps=_f(row.get("Reported EPS")),
                surprise_pct=(surprise / 100.0 if surprise is not None else None),
            )
        )
    return sorted(rows, key=lambda q: q.earnings_date)


def fetch_surprise_history(
    ticker: str,
    as_of: date,
    ticker_factory: Callable[[str], Any] = yf.Ticker,
    limit: int = 100,
) -> SurpriseHistory:
    """Point-in-time earnings-surprise history for ``ticker`` as of ``as_of``.

    ``ticker_factory`` defaults to ``yf.Ticker`` and is injectable for tests/backtests.
    A raw fetch is never point-in-time filtered before caching (24h TTL, keyed by
    ``ticker``+``limit``) so repeated calls for different ``as_of`` values reuse it; any
    exception from yfinance (rate limit, scrape failure, unknown ticker) degrades to an
    empty history with the reason recorded in ``provenance.missing_fields``, never raised.
    """
    symbol = ticker.strip().upper()
    if not symbol:
        raise ValueError("Ticker is required")

    cache_key = f"surprises:{symbol}:{limit}"
    all_quarters = _cache.get(cache_key)
    fetch_error: str | None = None
    if all_quarters is None:
        try:
            df = ticker_factory(symbol).get_earnings_dates(limit=limit)
            all_quarters = _quarters_from_dataframe(df)
            _cache.set(cache_key, all_quarters)
        except Exception as exc:  # yfinance can raise anything from HTTP to parsing errors
            all_quarters = []
            fetch_error = f"{type(exc).__name__}: {exc}"
            _cache.set(cache_key, all_quarters, ttl=_NEGATIVE_CACHE_TTL_SECONDS)

    quarters = _point_in_time(all_quarters, as_of)
    stats = derive_surprise_stats(all_quarters, as_of)

    missing_fields: list[str] = []
    if fetch_error:
        missing_fields.append(fetch_error)
    elif not quarters:
        missing_fields.append("no_reported_quarters")

    n = stats["quarters_available"] or len(quarters)
    confidence = 0.6 if n >= 8 else (0.4 if n >= 4 else 0.0)

    return SurpriseHistory(
        ticker=symbol,
        quarters=quarters,
        surprise_mean_8q=stats["surprise_mean_8q"],
        surprise_positive_share_8q=stats["surprise_positive_share_8q"],
        surprise_streak=stats["surprise_streak"],
        quarters_available=stats["quarters_available"],
        provenance=Provenance(
            source=SOURCE,
            as_of=datetime(as_of.year, as_of.month, as_of.day, tzinfo=UTC),
            confidence=confidence,
            tier=TIER,
            missing_fields=missing_fields,
        ),
    )
