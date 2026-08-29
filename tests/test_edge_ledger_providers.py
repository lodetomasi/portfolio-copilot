"""Offline, deterministic edge-case tests for the decision ledger and the free data providers.

CLAUDE.md non-negotiables exercised here:
- rule 6: missing/unusable data must degrade (or raise loudly), never be invented or
  silently swallowed;
- "nessun except Exception: pass": a provider or the ledger must fail loud, not quiet;
- every external datum carries source/as_of/confidence -- shape drift in an upstream
  payload must not turn into a wrong-but-plausible answer.

The SEC company_tickers.json shape-drift defects found during the audit are covered by
real regression tests below (`test_sec_company_tickers_*`); the provider now raises a
readable ValueError and the MCP tool degrades to a structured result.
"""

from __future__ import annotations

import json
import os
import stat
from datetime import date

import httpx
import pytest

from portfolio_copilot.portfolio.ledger import (
    evaluate_decisions,
    ledger_path,
    load_decisions,
    record_decision,
)
from portfolio_copilot.providers.cache import TTLCache
from portfolio_copilot.providers.ecb_fx import ECBFXProvider, convert_to_eur, parse_ecb_xml
from portfolio_copilot.providers.sec_edgar import SECEdgarProvider
from portfolio_copilot.providers.stooq import StooqProvider, parse_stooq_csv

# ---------------------------------------------------------------------------
# Ledger: corrupted decisions.jsonl
# ---------------------------------------------------------------------------


def test_load_decisions_raises_on_syntactically_corrupted_line(tmp_path):
    """A line that is not valid JSON must blow up loudly, never be skipped in silence --
    a silently-dropped decision would understate `decisions_total` without any signal."""
    record_decision(
        {"symbol": "MU", "action": "BUY", "reason": "r", "date": "2026-01-01"}, home=tmp_path
    )
    with (tmp_path / "decisions.jsonl").open("a", encoding="utf-8") as fh:
        fh.write("{this is not json\n")
    with pytest.raises(json.JSONDecodeError):
        load_decisions(tmp_path)


def test_load_decisions_raises_on_schema_violating_line(tmp_path):
    """A structurally-valid JSON line that violates the DecisionRecord schema (e.g. an
    action outside the Decision enum) must raise, not be coerced or dropped."""
    record_decision(
        {"symbol": "MU", "action": "BUY", "reason": "r", "date": "2026-01-01"}, home=tmp_path
    )
    bad = {
        "id": "x",
        "date": "2026-01-01",
        "symbol": "BAD",
        "action": "NOT_A_VALID_ACTION",
        "reason": "r",
    }
    with (tmp_path / "decisions.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(bad) + "\n")
    with pytest.raises(ValueError):  # pydantic.ValidationError is a ValueError subclass
        load_decisions(tmp_path)


# ---------------------------------------------------------------------------
# Ledger: future-dated decision
# ---------------------------------------------------------------------------


def test_evaluate_decisions_excludes_future_dated_decision_without_crashing(tmp_path):
    """A decision dated after `as_of` yields a negative age, which is always < min_days.
    It must be excluded from the report exactly like a too-recent decision (counted in
    the total, absent from `rows`), and must never raise or be reported as measured."""
    record_decision(
        {"symbol": "FUT", "action": "BUY", "price": 100, "reason": "r", "date": "2026-12-01"},
        home=tmp_path,
    )
    report = evaluate_decisions(
        load_decisions(tmp_path),
        {"FUT": 110.0},
        as_of=date(2026, 8, 28),
        min_days=90,
    )
    assert report["decisions_total"] == 1
    assert report["decisions_measured"] == 0
    assert report["decisions_unmeasurable"] == 0
    assert report["rows"] == []


# ---------------------------------------------------------------------------
# Ledger: evaluate_decisions with alternative == symbol
# ---------------------------------------------------------------------------


def test_evaluate_decisions_self_referential_alternative_computes_deterministically(tmp_path):
    """`alternative` equal to `symbol` is a degenerate but well-defined input: the "shadow"
    leg uses the same current price as the real leg (same lookup key) but its own recorded
    `alternative_price` as the entry price. The arithmetic must stay pure and deterministic,
    not special-cased into None or an error."""
    record_decision(
        {
            "symbol": "MU",
            "action": "BUY",
            "price": 100.0,
            "alternative": "MU",
            "alternative_price": 90.0,
            "reason": "r",
            "date": "2026-01-01",
        },
        home=tmp_path,
    )
    report = evaluate_decisions(
        load_decisions(tmp_path),
        {"MU": 150.0},
        as_of=date(2026, 8, 28),
        min_days=90,
    )
    assert report["decisions_measured"] == 1
    row = report["rows"][0]
    assert row["real_return"] == pytest.approx(0.5)  # 150/100 - 1
    assert row["alternative_return"] == pytest.approx(150.0 / 90.0 - 1.0)
    assert row["decision_alpha"] == pytest.approx(0.5 - (150.0 / 90.0 - 1.0))


# ---------------------------------------------------------------------------
# Ledger: PORTFOLIO_COPILOT_HOME pointing to a non-writable path
# ---------------------------------------------------------------------------


def test_record_decision_raises_when_home_directory_is_not_writable(tmp_path):
    """An existing but read-only PORTFOLIO_COPILOT_HOME must surface a clear OS error when
    appending, never silently drop the decision (rule: never invent, never lose data)."""
    home = tmp_path / "nowrite"
    home.mkdir()
    os.chmod(home, stat.S_IRUSR | stat.S_IXUSR)  # r-x, no write
    try:
        with pytest.raises(PermissionError):
            record_decision({"symbol": "X", "action": "BUY", "reason": "r"}, home=home)
    finally:
        os.chmod(home, stat.S_IRWXU)  # restore so tmp_path cleanup can remove it


def test_ledger_path_raises_when_parent_of_home_is_not_writable(tmp_path, monkeypatch):
    """PORTFOLIO_COPILOT_HOME set via env var to a not-yet-existing directory whose parent
    is read-only must fail at mkdir time with a clear PermissionError, not silently fall
    back to a different location."""
    parent = tmp_path / "readonly_parent"
    parent.mkdir()
    os.chmod(parent, stat.S_IRUSR | stat.S_IXUSR)  # r-x, no write => cannot create children
    home = parent / "sub"
    monkeypatch.setenv("PORTFOLIO_COPILOT_HOME", str(home))
    try:
        with pytest.raises(PermissionError):
            ledger_path(None)
    finally:
        os.chmod(parent, stat.S_IRWXU)  # restore so tmp_path cleanup can remove it


# ---------------------------------------------------------------------------
# Providers: HTTP 500 / 404 must raise httpx.HTTPStatusError, never be swallowed
# ---------------------------------------------------------------------------


def _error_response(url: str, status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("GET", url), text=f"error {status}")


@pytest.mark.parametrize("status", [500, 404])
def test_sec_provider_raises_http_status_error_on_server_and_client_errors(monkeypatch, status):
    def fake_get(url, timeout, headers, follow_redirects):
        return _error_response(url, status)

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        SECEdgarProvider().get_company_facts("ACME")
    assert str(status) in str(excinfo.value)


@pytest.mark.parametrize("status", [500, 404])
def test_ecb_provider_raises_http_status_error_on_server_and_client_errors(monkeypatch, status):
    def fake_get(url, timeout, follow_redirects):
        return _error_response(url, status)

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        ECBFXProvider().get_rates()
    assert str(status) in str(excinfo.value)


@pytest.mark.parametrize("status", [500, 404])
def test_stooq_provider_raises_http_status_error_on_server_and_client_errors(monkeypatch, status):
    def fake_get(url, timeout, follow_redirects):
        return _error_response(url, status)

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        StooqProvider().get_closes("vwce.de")
    assert str(status) in str(excinfo.value)


# ---------------------------------------------------------------------------
# Providers: timeout exceptions propagate (never swallowed at the raw-provider layer)
# ---------------------------------------------------------------------------


def _raise_read_timeout(*args, **kwargs):
    raise httpx.ReadTimeout("timed out")


def test_sec_provider_propagates_timeout(monkeypatch):
    monkeypatch.setattr(httpx, "get", _raise_read_timeout)
    with pytest.raises(httpx.ReadTimeout):
        SECEdgarProvider().get_company_facts("ACME")


def test_ecb_provider_propagates_timeout(monkeypatch):
    monkeypatch.setattr(httpx, "get", _raise_read_timeout)
    with pytest.raises(httpx.ReadTimeout):
        ECBFXProvider().get_rates()


def test_stooq_provider_propagates_timeout(monkeypatch):
    monkeypatch.setattr(httpx, "get", _raise_read_timeout)
    with pytest.raises(httpx.ReadTimeout):
        StooqProvider().get_closes("vwce.de")


# ---------------------------------------------------------------------------
# SEC: company_tickers.json with an unexpected shape (regression, audit 2026-08-28)
# ---------------------------------------------------------------------------


def _sec_get_returning(body):
    def fake_get(url, timeout, headers, follow_redirects):
        return httpx.Response(200, request=httpx.Request("GET", url), json=body)

    return fake_get


@pytest.mark.parametrize("body", [["not", "a", "dict"], {"0": "just a string"}])
def test_sec_company_tickers_shape_drift_raises_readable_value_error(monkeypatch, body):
    from portfolio_copilot.providers.sec_edgar import SECEdgarProvider

    monkeypatch.setattr(httpx, "get", _sec_get_returning(body))
    with pytest.raises(ValueError, match="unexpected shape"):
        SECEdgarProvider().get_company_facts("MU")


@pytest.mark.parametrize("body", [["not", "a", "dict"], {"0": "just a string"}])
def test_sec_company_tickers_shape_drift_degrades_in_mcp_tool(monkeypatch, body):
    """The company_facts MCP tool must never surface an AttributeError: it degrades to a
    structured 'unavailable' result (CLAUDE.md rule 6)."""
    import portfolio_copilot.server as server

    monkeypatch.setattr(httpx, "get", _sec_get_returning(body))
    server.sec_provider._cache._store.clear()
    out = server.company_facts("MU")
    assert isinstance(out, dict)
    assert out.get("ok") is False
    assert "unexpected shape" in json.dumps(out)


# ---------------------------------------------------------------------------
# ECB: XML with no USD rate
# ---------------------------------------------------------------------------

_ECB_XML_NO_USD = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01"
                  xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
  <Cube><Cube time="2026-08-27"><Cube currency="GBP" rate="0.86"/></Cube></Cube>
</gesmes:Envelope>"""


def test_parse_ecb_xml_without_usd_still_parses_other_currencies():
    """A day's fixing that happens to omit USD (or any single currency) is not malformed
    XML: the file still has rates, just not that one. Parsing must succeed."""
    parsed = parse_ecb_xml(_ECB_XML_NO_USD)
    assert parsed["rates"] == {"GBP": 0.86}
    assert "USD" not in parsed["rates"]


def test_convert_to_eur_returns_none_for_currency_missing_from_ecb_rates():
    """Converting an amount in a currency ECB didn't publish today must degrade to None
    (declared as unknown), never raise and never invent a rate (CLAUDE.md rules 4 and 6)."""
    parsed = parse_ecb_xml(_ECB_XML_NO_USD)
    assert convert_to_eur(100.0, "USD", parsed["rates"]) is None


def test_ecb_provider_get_rates_without_usd(monkeypatch):
    def fake_get(url, timeout, follow_redirects):
        return httpx.Response(200, request=httpx.Request("GET", url), text=_ECB_XML_NO_USD)

    monkeypatch.setattr(httpx, "get", fake_get)
    result = ECBFXProvider().get_rates()
    assert "ok" not in result  # no forced failure key just because one currency is absent
    assert "USD" not in result["rates"]
    assert result["rates"]["GBP"] == pytest.approx(0.86)


# ---------------------------------------------------------------------------
# Stooq: CSV missing the Close column
# ---------------------------------------------------------------------------


def test_parse_stooq_csv_raises_value_error_when_close_column_missing():
    """A CSV with a Date column but no Close column must raise ValueError naming the
    columns actually present, never silently return an empty/garbage series."""
    csv_without_close = "Date,Open,High,Low,Volume\n2025-01-01,100,101,99,1000\n"
    with pytest.raises(ValueError, match="Date/Close"):
        parse_stooq_csv(csv_without_close)


def test_stooq_get_closes_raises_when_response_has_no_close_column(monkeypatch):
    csv_without_close = "Date,Open,High,Low,Volume\n2025-01-01,100,101,99,1000\n"

    def fake_get(url, timeout, follow_redirects):
        return httpx.Response(200, request=httpx.Request("GET", url), text=csv_without_close)

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(ValueError, match="Date/Close"):
        StooqProvider().get_closes("vwce.de")


# ---------------------------------------------------------------------------
# TTLCache with ttl=0
# ---------------------------------------------------------------------------


def test_ttl_cache_zero_ttl_never_serves_a_stored_value():
    """ttl=0 means every entry is already expired at (or before) the moment it is read
    back: it must behave like caching is disabled, not raise and not serve stale data."""
    cache = TTLCache(ttl_seconds=0, clock=lambda: 100.0)
    cache.set("k", "v")
    assert cache.get("k") is None


def test_ttl_cache_zero_ttl_does_not_accumulate_dead_entries_forever():
    """A read of an expired key evicts it from the internal store (not just hides it),
    so a ttl=0 cache used in a hot loop doesn't leak memory."""
    cache = TTLCache(ttl_seconds=0, clock=lambda: 100.0)
    cache.set("k", "v")
    assert cache.get("k") is None
    assert "k" not in cache._store
