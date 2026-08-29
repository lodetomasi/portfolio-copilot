"""Offline tests for the free Yahoo earnings-surprise track record provider."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from portfolio_copilot.providers import yfinance_surprises
from portfolio_copilot.providers.cache import TTLCache
from portfolio_copilot.providers.yfinance_surprises import (
    SurpriseQuarter,
    derive_surprise_stats,
    fetch_surprise_history,
)


@pytest.fixture(autouse=True)
def _clean_cache():
    """The module-level TTL cache must never leak one test's fake data into the next."""
    yfinance_surprises._cache._store.clear()


def _df(rows: list[tuple[str, float, float, float]], tz: str | None = "America/New_York"):
    """Build a fake ``get_earnings_dates()`` frame. rows: (date, est, reported, surprise%)."""
    index = pd.DatetimeIndex([r[0] for r in rows], name="Earnings Date")
    if tz:
        index = index.tz_localize(tz)
    return pd.DataFrame(
        {
            "EPS Estimate": [r[1] for r in rows],
            "Reported EPS": [r[2] for r in rows],
            "Surprise(%)": [r[3] for r in rows],
        },
        index=index,
    )


class _FakeTicker:
    """Stands in for yf.Ticker(...); records calls so cache behaviour is testable."""

    def __init__(self, df: pd.DataFrame | None = None, error: Exception | None = None):
        self.df = df
        self.error = error
        self.calls = 0

    def factory(self, symbol: str) -> _FakeTicker:
        self.symbol = symbol
        return self

    def get_earnings_dates(self, limit=100):
        self.calls += 1
        self.limit = limit
        if self.error is not None:
            raise self.error
        return self.df


# 8 reported quarters, descending (as real Yahoo returns), surprises chosen so
# mean/share/streak are exact: ascending order is 2%, -4%, 3%, 2%, 4%, 3%, 12%, 5%.
EIGHT_QUARTERS_DESC = [
    ("2025-10-30", 1.75, 1.84, 5.0),
    ("2025-07-31", 1.40, 1.57, 12.0),
    ("2025-05-01", 1.60, 1.65, 3.0),
    ("2025-01-30", 2.30, 2.40, 4.0),
    ("2024-10-31", 0.95, 0.97, 2.0),
    ("2024-08-01", 1.30, 1.35, 3.0),
    ("2024-05-01", 1.50, 1.40, -4.0),
    ("2024-02-01", 2.00, 2.05, 2.0),
]


def test_fetch_surprise_history_parses_and_sorts_tz_aware_rows():
    fake = _FakeTicker(df=_df(EIGHT_QUARTERS_DESC))
    history = fetch_surprise_history("aapl", as_of=date(2026, 1, 1), ticker_factory=fake.factory)

    assert history.ticker == "AAPL"
    assert fake.symbol == "AAPL"
    assert [q.earnings_date for q in history.quarters] == [
        date(2024, 2, 1),
        date(2024, 5, 1),
        date(2024, 8, 1),
        date(2024, 10, 31),
        date(2025, 1, 30),
        date(2025, 5, 1),
        date(2025, 7, 31),
        date(2025, 10, 30),
    ]
    # Surprise(%) 5.0 -> fraction 0.05
    assert history.quarters[-1].surprise_pct == pytest.approx(0.05)
    assert history.quarters[-1].reported_eps == pytest.approx(1.84)


def test_fetch_surprise_history_deduplicates_repeated_earnings_date_rows():
    """finding 16: a duplicated/reissued row for the same quarter must not inflate
    quarters_available or double-count that quarter in the derived stats."""
    rows = [
        ("2025-01-30", 2.30, 2.40, 4.0),
        ("2025-05-01", 1.60, 1.65, 3.0),
        ("2025-07-31", 1.40, 1.57, 12.0),
        ("2025-10-30", 1.75, 1.84, 5.0),
        ("2025-10-30", 1.75, 1.84, 5.0),  # duplicate/reissued row for the same quarter
    ]
    fake = _FakeTicker(df=_df(rows))
    history = fetch_surprise_history("DUPQ", as_of=date(2026, 1, 1), ticker_factory=fake.factory)

    dates = [q.earnings_date for q in history.quarters]
    assert dates == sorted(set(dates))  # no repeated date
    assert history.quarters_available == 4  # 4 distinct quarters, not 5 raw rows


def test_fetch_surprise_history_computes_confidence_06_and_derived_stats_at_8_quarters():
    fake = _FakeTicker(df=_df(EIGHT_QUARTERS_DESC))
    history = fetch_surprise_history("AAPL", as_of=date(2026, 1, 1), ticker_factory=fake.factory)

    assert history.quarters_available == 8
    assert history.surprise_mean_8q == pytest.approx(0.03375)
    assert history.surprise_positive_share_8q == pytest.approx(7 / 8)
    assert history.surprise_streak == 6
    assert history.provenance.confidence == pytest.approx(0.6)
    assert history.provenance.source == "yfinance_earnings_dates"
    assert history.provenance.tier == "B"
    assert history.note == "Yahoo can backfill past rows; not strict point-in-time"
    assert history.provenance.as_of == pd.Timestamp("2026-01-01", tz="UTC").to_pydatetime()


def test_fetch_surprise_history_excludes_future_and_unreported_rows():
    rows = [*EIGHT_QUARTERS_DESC, ("2026-01-29", 2.10, np.nan, np.nan)]
    fake = _FakeTicker(df=_df(rows))
    history = fetch_surprise_history("AAPL", as_of=date(2026, 1, 1), ticker_factory=fake.factory)

    assert len(history.quarters) == 8
    assert all(q.earnings_date <= date(2026, 1, 1) for q in history.quarters)
    assert all(q.reported_eps is not None for q in history.quarters)


def test_fetch_surprise_history_nan_surprise_counts_toward_quarters_but_not_mean():
    rows = [
        ("2024-02-01", 2.00, 2.05, np.nan),  # reported, but no computable surprise
        ("2024-05-01", 1.50, 1.40, -4.0),
        ("2024-08-01", 1.30, 1.35, 3.0),
        ("2024-10-31", 0.95, 0.97, 2.0),
    ]
    fake = _FakeTicker(df=_df(rows))
    history = fetch_surprise_history("AAPL", as_of=date(2026, 1, 1), ticker_factory=fake.factory)

    assert history.quarters_available == 4
    assert history.quarters[0].surprise_pct is None
    # mean/share computed only over the 3 quarters with a real surprise_pct
    assert history.surprise_mean_8q == pytest.approx((-4.0 + 3.0 + 2.0) / 100 / 3)
    assert history.surprise_positive_share_8q == pytest.approx(2 / 3)


def test_fetch_surprise_history_returns_none_derived_stats_below_4_quarters():
    rows = EIGHT_QUARTERS_DESC[-2:]  # only 2 reported quarters
    fake = _FakeTicker(df=_df(rows))
    history = fetch_surprise_history("AAPL", as_of=date(2026, 1, 1), ticker_factory=fake.factory)

    assert len(history.quarters) == 2  # the raw quarters are still returned
    assert history.quarters_available is None
    assert history.surprise_mean_8q is None
    assert history.surprise_positive_share_8q is None
    assert history.surprise_streak is None
    assert history.provenance.confidence == 0.0
    assert history.provenance.missing_fields == []


def test_fetch_surprise_history_confidence_04_for_4_to_7_quarters():
    rows = EIGHT_QUARTERS_DESC[-5:]  # 5 reported quarters
    fake = _FakeTicker(df=_df(rows))
    history = fetch_surprise_history("AAPL", as_of=date(2026, 1, 1), ticker_factory=fake.factory)

    assert history.quarters_available == 5
    assert history.provenance.confidence == pytest.approx(0.4)


def test_fetch_surprise_history_handles_exception_without_crashing():
    fake = _FakeTicker(error=RuntimeError("HTTP 429"))
    history = fetch_surprise_history("AAPL", as_of=date(2026, 1, 1), ticker_factory=fake.factory)

    assert history.quarters == []
    assert history.quarters_available is None
    assert history.provenance.confidence == 0.0
    assert any("HTTP 429" in m for m in history.provenance.missing_fields)


def test_fetch_surprise_history_empty_result_is_labelled_not_fabricated():
    fake = _FakeTicker(df=_df([]))
    history = fetch_surprise_history("ZZZZ", as_of=date(2026, 1, 1), ticker_factory=fake.factory)

    assert history.quarters == []
    assert history.provenance.missing_fields == ["no_reported_quarters"]


def test_fetch_surprise_history_uses_ttl_cache_across_different_as_of():
    fake = _FakeTicker(df=_df(EIGHT_QUARTERS_DESC))
    fetch_surprise_history("AAPL", as_of=date(2024, 6, 1), ticker_factory=fake.factory)
    second = fetch_surprise_history("AAPL", as_of=date(2026, 1, 1), ticker_factory=fake.factory)

    assert fake.calls == 1  # second call reused the cached raw rows
    assert second.quarters_available == 8  # but re-derived stats for the new as_of


def test_fetch_surprise_history_rejects_blank_ticker():
    with pytest.raises(ValueError):
        fetch_surprise_history("  ", as_of=date(2026, 1, 1))


def test_fetch_surprise_history_negative_caches_a_failed_fetch_briefly(monkeypatch):
    """finding 15: an exception must be briefly negative-cached (so a large universe loop
    doesn't hammer a persistently-failing ticker every single call) but must self-heal
    once that short TTL elapses -- unlike a confirmed-empty/successful result's full 24h."""
    clock = {"t": 0.0}
    fake_cache = TTLCache(ttl_seconds=24 * 3600, clock=lambda: clock["t"])
    monkeypatch.setattr(yfinance_surprises, "_cache", fake_cache)

    fake = _FakeTicker(error=RuntimeError("HTTP 429"))
    fetch_surprise_history("FLAKY", as_of=date(2026, 1, 1), ticker_factory=fake.factory)
    assert fake.calls == 1

    # immediately again -- suppressed by the short negative-cache TTL, no hammering
    fetch_surprise_history("FLAKY", as_of=date(2026, 1, 1), ticker_factory=fake.factory)
    assert fake.calls == 1

    # after the negative-cache TTL elapses (well under the 24h success TTL), retry happens
    clock["t"] += 15 * 60
    fetch_surprise_history("FLAKY", as_of=date(2026, 1, 1), ticker_factory=fake.factory)
    assert fake.calls == 2


def test_fetch_surprise_history_tz_naive_index_also_parses():
    fake = _FakeTicker(df=_df(EIGHT_QUARTERS_DESC, tz=None))
    history = fetch_surprise_history("AAPL", as_of=date(2026, 1, 1), ticker_factory=fake.factory)
    assert history.quarters_available == 8


def test_derive_surprise_stats_as_of_filters_out_a_backfilled_future_row():
    """A quarter dated after as_of but already carrying a reported EPS (Yahoo backfill
    reaching past the backtest cursor) must not leak into a point-in-time computation."""
    quarters = [
        SurpriseQuarter(earnings_date=date(2024, 1, 1), reported_eps=1.0, surprise_pct=0.02),
        SurpriseQuarter(earnings_date=date(2024, 4, 1), reported_eps=1.0, surprise_pct=0.03),
        SurpriseQuarter(earnings_date=date(2024, 7, 1), reported_eps=1.0, surprise_pct=0.04),
        SurpriseQuarter(earnings_date=date(2024, 10, 1), reported_eps=1.0, surprise_pct=-0.01),
        # "future" relative to as_of, but already reported in Yahoo's current record
        SurpriseQuarter(earnings_date=date(2025, 1, 1), reported_eps=1.0, surprise_pct=0.99),
    ]
    stats = derive_surprise_stats(quarters, as_of=date(2024, 11, 1))

    assert stats["quarters_available"] == 4
    assert stats["surprise_mean_8q"] == pytest.approx((0.02 + 0.03 + 0.04 - 0.01) / 4)
    assert stats["surprise_streak"] == 0  # latest usable quarter (2024-10-01) is negative


def test_derive_surprise_stats_empty_input():
    stats = derive_surprise_stats([], as_of=date(2026, 1, 1))
    assert stats == {
        "surprise_mean_8q": None,
        "surprise_positive_share_8q": None,
        "surprise_streak": None,
        "quarters_available": None,
    }


def test_derive_surprise_stats_streak_stops_at_first_non_positive_from_the_end():
    quarters = [
        SurpriseQuarter(earnings_date=date(2024, 1, 1), reported_eps=1.0, surprise_pct=0.10),
        SurpriseQuarter(earnings_date=date(2024, 4, 1), reported_eps=1.0, surprise_pct=-0.02),
        SurpriseQuarter(earnings_date=date(2024, 7, 1), reported_eps=1.0, surprise_pct=0.01),
        SurpriseQuarter(earnings_date=date(2024, 10, 1), reported_eps=1.0, surprise_pct=0.03),
    ]
    stats = derive_surprise_stats(quarters, as_of=date(2026, 1, 1))
    assert stats["surprise_streak"] == 2  # last two (0.01, 0.03) are positive
