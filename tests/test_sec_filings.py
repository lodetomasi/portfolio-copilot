"""Offline tests for SEC EDGAR filings listing, item extraction and insider-activity counts."""

import json
from pathlib import Path

import httpx
import pytest

from portfolio_copilot.providers import sec_filings
from portfolio_copilot.providers.sec_edgar import SECEdgarProvider
from portfolio_copilot.providers.sec_filings import (
    RateLimiter,
    extract_items,
    filing_sections,
    filing_url,
    insider_activity,
    list_filings,
)

FIXTURES = Path(__file__).parent / "fixtures"
SUBMISSIONS = json.loads((FIXTURES / "sec_submissions_sample.json").read_text())
TEN_K_HTML = (FIXTURES / "sec_10k_sample.html").read_text()
TICKERS_BODY = {"0": {"cik_str": 1234567, "ticker": "ACME", "title": "ACME ROBOTICS INC"}}


@pytest.fixture(autouse=True)
def _fast_rate_limiter_and_clean_caches(monkeypatch):
    """Every test shares module-level singletons: swap in a non-sleeping limiter and clear
    the TTL caches so one test's mocked responses never leak into the next."""
    monkeypatch.setattr(sec_filings, "_rate_limiter", RateLimiter(max_per_second=1_000_000))
    sec_filings._submissions_cache._store.clear()
    sec_filings._document_cache._store.clear()
    yield


def _response(url: str, **kwargs) -> httpx.Response:
    return httpx.Response(200, request=httpx.Request("GET", url), **kwargs)


def _fake_get(tickers_body=TICKERS_BODY, submissions_body=SUBMISSIONS, html_text=None):
    """A drop-in for httpx.get that answers the three endpoints this module calls."""

    def fake_get(url, timeout, headers, follow_redirects):
        assert headers["User-Agent"]  # SEC requires a non-empty identifiable User-Agent
        if url.endswith("company_tickers.json"):
            return _response(url, json=tickers_body)
        if "data.sec.gov/submissions/" in url:
            return _response(url, json=submissions_body)
        return _response(url, text=html_text or TEN_K_HTML)

    return fake_get


# --- RateLimiter -------------------------------------------------------------------------


def test_rate_limiter_sleeps_only_when_calls_are_too_close(monkeypatch):
    now = [0.0]
    sleeps = []
    limiter = RateLimiter(max_per_second=8.0, clock=lambda: now[0], sleeper=sleeps.append)

    limiter.wait()  # first call: never waits
    assert sleeps == []

    now[0] = 0.01  # 10ms later, well inside the 125ms minimum interval
    limiter.wait()
    assert sleeps == [pytest.approx(0.115)]

    now[0] = 10.0  # plenty of real time has passed since
    limiter.wait()
    assert sleeps == [pytest.approx(0.115)]  # unchanged: no extra sleep needed


def test_rate_limiter_rejects_non_positive_rate():
    with pytest.raises(ValueError):
        RateLimiter(max_per_second=0)


# --- extract_items -------------------------------------------------------------------------


def test_extract_items_finds_1a_and_7_and_misses_9_gracefully():
    out = extract_items(TEN_K_HTML, items=("1A", "7", "9"))
    assert "competitive pressure" in out["1A"]
    assert "supply chain" in out["1A"]
    assert "Revenue for fiscal year 2025" in out["7"]
    assert "Item 7A" not in out["7"]  # boundary must stop before the next heading
    assert out["9"] == ""
    assert "_notes" in out and "Item 9" in out["_notes"]


def test_extract_items_distinguishes_7_from_7a_and_caps_length():
    out = extract_items(TEN_K_HTML, items=("7A", "8"))
    assert "foreign currency risk" in out["7A"]
    assert "Financial Statements and Supplementary Data" not in out["7A"]
    assert "Report of Independent Registered Public Accounting Firm" in out["8"]
    assert all(len(section) <= sec_filings.MAX_SECTION_CHARS for section in out.values())


def test_extract_items_strips_scripts_and_styles():
    out = extract_items(TEN_K_HTML, items=("1A",))
    assert "trackPage" not in out["1A"]
    assert "font-family" not in out["1A"]


# --- filing_url --------------------------------------------------------------------------


def test_filing_url_strips_dashes_from_accession():
    url = filing_url(1234567, "0001234567-26-000010", "acme-20251231.htm")
    assert url == "https://www.sec.gov/Archives/edgar/data/1234567/000123456726000010/acme-20251231.htm"


# --- list_filings --------------------------------------------------------------------------


def test_list_filings_filters_by_form_and_sorts_newest_first(monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get())
    rows = list_filings("acme", forms=("10-K", "10-Q"), limit=10)
    assert [r["form"] for r in rows] == ["10-K", "10-Q", "10-Q"]
    assert rows[0]["filing_date"] == "2026-03-02"
    assert rows[0]["accession_number"] == "0001234567-26-000010"
    assert rows[1]["filing_date"] == "2025-11-05" and rows[2]["filing_date"] == "2025-08-06"


def test_list_filings_default_forms_excludes_form4_and_respects_limit(monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get())
    rows = list_filings("acme", limit=2)
    assert len(rows) == 2
    assert all(r["form"] in {"10-K", "10-Q", "8-K"} for r in rows)
    assert rows[0]["filing_date"] == "2026-03-02"  # the 10-K is the single most recent filing


def test_list_filings_unknown_ticker_returns_empty_not_an_error(monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get())
    assert list_filings("NOPE") == []


def test_list_filings_rejects_non_positive_limit():
    with pytest.raises(ValueError):
        list_filings("ACME", limit=0)


# --- filing_sections -----------------------------------------------------------------------


def test_filing_sections_happy_path_has_provenance_and_sections(monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get())
    out = filing_sections("acme", form="10-K", items=("1A", "7"))
    assert out["ok"] is True
    assert out["source"] == "sec_edgar_filings" and out["tier"] == "A"
    assert out["as_of"] == "2026-03-02"
    assert out["cik"] == 1234567
    assert out["missing_fields"] == []
    assert out["confidence"] == pytest.approx(0.9)
    assert out["url"] == filing_url(1234567, "0001234567-26-000010", "acme-20251231.htm")
    assert "competitive pressure" in out["sections"]["1A"]


def test_filing_sections_foreign_filer_with_no_10k_is_readable_not_a_crash(monkeypatch):
    foreign = {
        "cik": "9999999",
        "name": "FOREIGN WIDGETS PLC",
        "filings": {
            "recent": {
                "accessionNumber": ["0009999999-26-000001"],
                "filingDate": ["2026-02-01"],
                "form": ["20-F"],
                "primaryDocument": ["foreign20f.htm"],
            },
            "files": [],
        },
    }
    tickers = {"0": {"cik_str": 9999999, "ticker": "FRGN", "title": "FOREIGN WIDGETS PLC"}}
    monkeypatch.setattr(httpx, "get", _fake_get(tickers_body=tickers, submissions_body=foreign))
    out = filing_sections("frgn", form="10-K")
    assert out["ok"] is False
    assert out["confidence"] == 0.0
    assert "No 10-K filing found" in out["error"]
    assert "sections" not in out


def test_filing_sections_unknown_ticker_is_readable_not_a_crash(monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get())
    out = filing_sections("NOPE")
    assert out["ok"] is False and out["confidence"] == 0.0
    assert "Ticker not found" in out["error"]


# --- insider_activity ----------------------------------------------------------------------


def test_insider_activity_counts_form4_within_window_inclusive(monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get())
    out = insider_activity("acme", days=90, as_of="2026-06-01")
    assert out["ok"] is True
    assert out["window_days"] == 90 and out["as_of"] == "2026-06-01"
    assert out["filing_count"] == 4
    assert out["filing_dates"] == ["2026-05-20", "2026-05-12", "2026-05-10", "2026-03-03"]
    assert any("does not parse" in note for note in out["limitations"])


def test_insider_activity_accepts_date_object_as_of(monkeypatch):
    from datetime import date

    monkeypatch.setattr(httpx, "get", _fake_get())
    out = insider_activity("acme", days=90, as_of=date(2026, 6, 1))
    assert out["filing_count"] == 4


def test_insider_activity_unknown_ticker_is_readable_not_a_crash(monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get())
    out = insider_activity("NOPE", as_of="2026-06-01")
    assert out["ok"] is False
    assert out["filing_count"] is None and out["filing_dates"] == []
    assert "Ticker not found" in out["error"]


def test_insider_activity_rejects_non_positive_days():
    with pytest.raises(ValueError):
        insider_activity("ACME", days=0)


def test_insider_activity_default_as_of_uses_today_without_crashing(monkeypatch):
    """No fixed assertion on the count: 'today' is real wall-clock time, so only the shape
    of the result -- not a count against fixture dates from a fixed year -- is checked here."""
    monkeypatch.setattr(httpx, "get", _fake_get())
    out = insider_activity("acme", days=90)
    assert out["ok"] is True
    assert isinstance(out["as_of"], str) and len(out["as_of"]) == 10
    assert isinstance(out["filing_count"], int)


def test_uses_sec_edgar_provider_user_agent(monkeypatch):
    """Confirms the SEC-mandated User-Agent handling is reused, not reimplemented."""
    seen = []

    def fake_get(url, timeout, headers, follow_redirects):
        seen.append(headers["User-Agent"])
        if url.endswith("company_tickers.json"):
            return _response(url, json=TICKERS_BODY)
        return _response(url, json=SUBMISSIONS)

    monkeypatch.setattr(httpx, "get", fake_get)
    provider = SECEdgarProvider()
    list_filings("acme", provider=provider)
    assert seen and all(ua == provider.user_agent for ua in seen)


# --- finding 35: insider_activity confidence must reflect whether the SEC 'recent'
# window actually reaches back far enough to cover the requested trailing-days period ----


def test_insider_activity_confidence_stays_high_when_window_fully_covered(monkeypatch):
    monkeypatch.setattr(httpx, "get", _fake_get())
    out = insider_activity("acme", days=90, as_of="2026-06-01")
    assert out["confidence"] == 0.9


def test_insider_activity_confidence_degrades_when_recent_window_is_shallow(monkeypatch):
    shallow = {
        "filings": {
            "recent": {
                "form": ["8-K", "8-K", "4"],
                "filingDate": ["2026-08-27", "2026-08-25", "2026-08-24"],
                "accessionNumber": ["", "", ""],
                "primaryDocument": ["", "", ""],
            }
        }
    }
    monkeypatch.setattr(httpx, "get", _fake_get(submissions_body=shallow))
    out = insider_activity("acme", days=90, as_of="2026-08-28")
    assert out["ok"] is True
    assert out["confidence"] < 0.9
    assert any(
        "window" in note.lower() or "recent" in note.lower() for note in out["limitations"]
    )


# --- finding 37: a non-dict submissions payload must degrade to a clear ValueError,
# never an AttributeError from deep inside .get() chains ------------------------------


def test_list_filings_raises_clear_error_on_non_dict_submissions_payload(monkeypatch):
    def fake_get(url, timeout, headers, follow_redirects):
        if url.endswith("company_tickers.json"):
            return _response(url, json=TICKERS_BODY)
        if "data.sec.gov/submissions/" in url:
            return _response(url, json=["unexpected", "list", "shape"])
        return _response(url, text=TEN_K_HTML)

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(ValueError, match="[Mm]alformed"):
        list_filings("acme")


def test_insider_activity_raises_clear_error_on_non_dict_submissions_payload(monkeypatch):
    def fake_get(url, timeout, headers, follow_redirects):
        if url.endswith("company_tickers.json"):
            return _response(url, json=TICKERS_BODY)
        if "data.sec.gov/submissions/" in url:
            return _response(url, json=["unexpected", "list", "shape"])
        return _response(url, text=TEN_K_HTML)

    monkeypatch.setattr(httpx, "get", fake_get)
    with pytest.raises(ValueError, match="[Mm]alformed"):
        insider_activity("acme")
