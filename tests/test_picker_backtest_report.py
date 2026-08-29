"""Offline, deterministic tests for the pure/mockable helpers in
``scripts/picker_backtest_report.py`` -- NOT the script's ``main()`` (which needs network
for prices/benchmark and is deliberately excluded from the suite, per that file's own
docstring). ``fetch_fundamentals`` promises "never raises" and is tested here against a
fake provider with no network call at all.

The script lives outside ``src/`` (not on ``pythonpath``), so it is loaded directly by
file path rather than via a normal import.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "picker_backtest_report.py"
_spec = importlib.util.spec_from_file_location("picker_backtest_report", _SCRIPT_PATH)
picker_backtest_report = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("picker_backtest_report", picker_backtest_report)
assert _spec.loader is not None
_spec.loader.exec_module(picker_backtest_report)

fetch_fundamentals = picker_backtest_report.fetch_fundamentals


class _KeyErrorProvider:
    """Stands in for SECEdgarProvider.cik_for_ticker raising KeyError on a malformed row
    (e.g. SEC's company_tickers.json missing 'cik_str' on some entry) -- a real shape
    ``cik_for_ticker`` can raise, distinct from the (httpx.HTTPError, ValueError) the
    caller currently guards against."""

    timeout = 15.0
    user_agent = "test-agent"

    def cik_for_ticker(self, ticker: str) -> str | None:
        raise KeyError("cik_str")


def test_fetch_fundamentals_never_raises_on_a_malformed_cik_lookup():
    # finding 23: fetch_fundamentals's docstring promises "[] on any failure (never
    # raises)" but only guarded (httpx.HTTPError, ValueError) -- a KeyError from
    # cik_for_ticker must degrade to [], not propagate and abort the whole report run.
    result = fetch_fundamentals("AAPL", _KeyErrorProvider())
    assert result == []
