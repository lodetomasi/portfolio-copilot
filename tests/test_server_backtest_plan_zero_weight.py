"""Regression test: backtest_plan must not crash with a raw ZeroDivisionError when the
only bucket(s) with usable price history carry a target weight of 0.0.

server.backtest_plan renormalizes ``targets`` over the buckets whose ticker actually
returned price data (``usable``). If a non-zero-weight bucket's ticker fails to return
data (typo, delisting, provider outage) and gets dropped from ``closes.columns`` while a
zero-weight bucket's data is present, ``usable`` ends up containing only the zero-weight
bucket, so ``sum(usable.values()) == 0`` and the renormalization divides by zero. The
guard before renormalizing must also catch this case and return the existing
``{"ok": False, ...}`` shape, matching CLAUDE.md's mandate to degrade and declare missing
data rather than crash raw.
"""

from __future__ import annotations

import pandas as pd

import portfolio_copilot.server as server


def _fake_monthly_closes_missing_equity(tickers, period="5y"):
    # Only "bond" ticker returned data; "equity" ticker failed and was dropped.
    idx = pd.date_range("2024-01-31", periods=3, freq="ME")
    df = pd.DataFrame({"bond": [100.0, 101.0, 102.0]}, index=idx)
    df.attrs.update(
        {"missing": ["equity"], "source": "fake", "as_of": "2024-03-31T00:00:00+00:00"}
    )
    return df


def test_backtest_plan_degrades_when_usable_buckets_sum_to_zero_weight(monkeypatch):
    monkeypatch.setattr(
        server.provider, "get_monthly_closes", _fake_monthly_closes_missing_equity
    )

    # "bond" has target weight 0.0 (being phased out); "equity" (weight 1.0) is the
    # bucket that actually matters, but its ticker failed to return data.
    result = server.backtest_plan(
        tickers_by_bucket={"bond": "AGGH.MI", "equity": "TYPO_TICKER"},
        targets={"bond": 0.0, "equity": 1.0},
        initial_cash=1000.0,
        monthly_contribution=100.0,
    )

    assert result["ok"] is False
    assert "missing_buckets" in result
    assert result["missing_buckets"] == ["equity"]
