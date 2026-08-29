"""Offline tests for the free public data sources (ECB, SEC EDGAR, Stooq) and the TTL cache."""

import json
import logging
import re
from pathlib import Path

import httpx
import pytest

from portfolio_copilot.providers.cache import TTLCache
from portfolio_copilot.providers.ecb_fx import ECBFXProvider, convert_to_eur, parse_ecb_xml
from portfolio_copilot.providers.sec_edgar import (
    DEFAULT_USER_AGENT,
    SECEdgarProvider,
    summarize_company_facts,
)
from portfolio_copilot.providers.stooq import StooqProvider, parse_stooq_csv

FIXTURES = Path(__file__).parent / "fixtures"


def test_ttl_cache_expires_with_clock():
    now = [100.0]
    cache = TTLCache(ttl_seconds=10, clock=lambda: now[0])
    cache.set("k", "v")
    assert cache.get("k") == "v"
    now[0] = 109.9
    assert cache.get("k") == "v"
    now[0] = 110.0
    assert cache.get("k") is None


def test_parse_ecb_xml_and_convert():
    parsed = parse_ecb_xml((FIXTURES / "ecb_eurofxref_sample.xml").read_text())
    assert parsed["as_of"] == "2026-08-27"
    assert parsed["rates"]["USD"] == 1.165
    assert convert_to_eur(116.5, "usd", parsed["rates"]) == pytest.approx(100.0)
    assert convert_to_eur(50, "EUR", parsed["rates"]) == 50.0
    assert convert_to_eur(50, "XXX", parsed["rates"]) is None


def test_parse_ecb_xml_rejects_garbage():
    with pytest.raises(ValueError):
        parse_ecb_xml("<a><b/></a>")


def _response(url: str, **kwargs) -> httpx.Response:
    return httpx.Response(200, request=httpx.Request("GET", url), **kwargs)


def test_ecb_provider_uses_cache_and_timeout(monkeypatch):
    calls = []

    def fake_get(url, timeout, follow_redirects):
        calls.append((url, timeout))
        return _response(url, text=(FIXTURES / "ecb_eurofxref_sample.xml").read_text())

    monkeypatch.setattr(httpx, "get", fake_get)
    provider = ECBFXProvider(timeout=3.0)
    first = provider.get_rates()
    second = provider.get_rates()
    assert first["source"] == "ecb_eurofxref" and first["rates"]["GBP"] == 0.86
    assert second is first
    assert calls == [("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml", 3.0)]


def test_sec_summary_latest_two_years_and_derived_metrics():
    facts = json.loads((FIXTURES / "sec_companyfacts_sample.json").read_text())
    out = summarize_company_facts(facts)
    assert out["entity"] == "ACME ROBOTICS INC"
    assert out["fiscal_year"] == 2025
    assert out["revenue"] == 1_500_000
    assert out["revenue_growth"] == pytest.approx(0.5)  # restated prior-year row must be ignored
    assert out["net_margin"] == pytest.approx(-0.1)
    assert out["free_cashflow"] == -150_000  # CFO -100k minus capex 50k
    assert out["equity"] == 2_000_000  # FY value, not the 10-Q one
    assert out["long_term_debt"] is None
    assert "long_term_debt" in out["missing_fields"]


def test_sec_summary_without_us_gaap_facts_reports_everything_missing():
    out = summarize_company_facts({"cik": 1, "entityName": "FOREIGN ADR", "facts": {}})
    assert out["revenue"] is None and out["free_cashflow"] is None
    assert set(out["missing_fields"]) >= {"revenue", "net_income", "operating_cash_flow"}


def test_sec_provider_resolves_cik_and_sets_user_agent(monkeypatch):
    seen = {}

    def fake_get(url, timeout, headers, follow_redirects):
        seen[url] = headers["User-Agent"]
        if url.endswith("company_tickers.json"):
            body = {"0": {"cik_str": 1234567, "ticker": "ACME", "title": "ACME ROBOTICS INC"}}
        else:
            body = json.loads((FIXTURES / "sec_companyfacts_sample.json").read_text())
        return _response(url, json=body)

    monkeypatch.setattr(httpx, "get", fake_get)
    provider = SECEdgarProvider()
    out = provider.get_company_facts("acme")
    assert out["ok"] is True and out["ticker"] == "ACME"
    assert out["source"] == "sec_edgar" and out["as_of"] == "2026-03-01"
    assert 0 < out["confidence"] < 1
    assert "CIK0001234567.json" in " ".join(seen)
    assert all(ua.startswith("portfolio-copilot") for ua in seen.values())

    unknown = provider.get_company_facts("NOPE")
    assert unknown["ok"] is False and unknown["confidence"] == 0.0


def test_default_user_agent_satisfies_sec_fair_access_policy():
    """SEC EDGAR returns HTTP 403 for any User-Agent that has no identifiable app + contact
    (verified live against https://www.sec.gov/files/company_tickers.json). The shipped
    default must carry an email-like contact so tier-A SEC cross-checks work out of the box,
    without a user having to know to set PORTFOLIO_COPILOT_SEC_USER_AGENT first."""
    assert DEFAULT_USER_AGENT.startswith("portfolio-copilot")
    assert re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", DEFAULT_USER_AGENT), (
        f"DEFAULT_USER_AGENT has no contact email pattern, SEC EDGAR 403s it: "
        f"{DEFAULT_USER_AGENT!r}"
    )


def test_sec_403_raises_clear_actionable_error(monkeypatch):
    """A 403 from SEC (User-Agent rejected) must surface as a short, actionable message that
    names the fix (the PORTFOLIO_COPILOT_SEC_USER_AGENT env var) -- not the raw multi-line
    httpx exception text, which buries the actual cause."""

    def fake_get(url, timeout, headers, follow_redirects):
        return httpx.Response(
            403, request=httpx.Request("GET", url), text="request forbidden by SEC"
        )

    monkeypatch.setattr(httpx, "get", fake_get)
    provider = SECEdgarProvider()
    with pytest.raises(httpx.HTTPStatusError) as excinfo:
        provider.get_company_facts("ACME")
    message = str(excinfo.value)
    assert "403" in message
    assert "PORTFOLIO_COPILOT_SEC_USER_AGENT" in message
    assert "\n" not in message


def test_parse_stooq_csv_and_no_data():
    series = parse_stooq_csv((FIXTURES / "stooq_sample.csv").read_text())
    assert len(series) == 4 and series.iloc[-1] == 104.0
    with pytest.raises(ValueError):
        parse_stooq_csv("No data")


def test_stooq_monthly_closes_reports_missing_buckets(monkeypatch):
    def fake_get(url, timeout, follow_redirects):
        if "s=bad" in url:
            return _response(url, text="No data")
        return _response(url, text=(FIXTURES / "stooq_sample.csv").read_text())

    monkeypatch.setattr(httpx, "get", fake_get)
    df = StooqProvider().get_monthly_closes({"core": "vwce.de", "bad": "bad"}, period="max")
    assert list(df.columns) == ["core"]
    assert df.attrs["missing"] == ["bad"] and df.attrs["source"] == "stooq"


def test_stooq_monthly_closes_accepts_uppercase_period(monkeypatch):
    def fake_get(url, timeout, follow_redirects):
        return _response(url, text=(FIXTURES / "stooq_sample.csv").read_text())

    monkeypatch.setattr(httpx, "get", fake_get)
    df = StooqProvider().get_monthly_closes({"core": "vwce.de"}, period="5Y")
    assert list(df.columns) == ["core"]
    assert len(df) == 4


def test_stooq_monthly_closes_logs_failure_reason(monkeypatch, caplog):
    """A bucket that fails should log its symbol + underlying reason at warning level,
    not just vanish into df.attrs['missing'] with no diagnosable trace."""

    def fake_get(url, timeout, follow_redirects):
        if "s=bad" in url:
            return _response(url, text="No data")
        return _response(url, text=(FIXTURES / "stooq_sample.csv").read_text())

    monkeypatch.setattr(httpx, "get", fake_get)
    with caplog.at_level(logging.WARNING, logger="portfolio_copilot.providers.stooq"):
        df = StooqProvider().get_monthly_closes({"core": "vwce.de", "bad": "bad"}, period="max")

    assert df.attrs["missing"] == ["bad"]
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("bad" in msg for msg in warnings), warnings
    assert any("Stooq returned no data" in msg for msg in warnings), warnings
