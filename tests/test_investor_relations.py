"""Offline tests for the investor-relations crawler (public pages only, robots-aware)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from portfolio_copilot.providers.investor_relations import (
    DEFAULT_USER_AGENT,
    MAX_REQUESTS,
    IRProvider,
    candidate_ir_urls,
    extract_ir_links,
    robots_allows,
)

FIXTURES = Path(__file__).parent / "fixtures"
IR_HTML = (FIXTURES / "ir_page_sample.html").read_text()
ROBOTS_TXT = (FIXTURES / "robots_sample.txt").read_text()


def _response(url: str, status_code: int = 200, **kwargs) -> httpx.Response:
    return httpx.Response(status_code, request=httpx.Request("GET", url), **kwargs)


# ---------------------------------------------------------------------------
# candidate_ir_urls
# ---------------------------------------------------------------------------


def test_candidate_ir_urls_covers_paths_and_subdomains():
    urls = candidate_ir_urls("https://www.example.com")
    assert urls == [
        "https://www.example.com/investors",
        "https://www.example.com/investor-relations",
        "https://www.example.com/investor",
        "https://www.example.com/ir",
        "https://ir.example.com",
        "https://investors.example.com",
    ]


def test_candidate_ir_urls_accepts_website_without_scheme():
    urls = candidate_ir_urls("example.com")
    assert urls[0] == "https://example.com/investors"
    assert "https://ir.example.com" in urls
    assert "https://investors.example.com" in urls


def test_candidate_ir_urls_ignores_path_and_query():
    urls = candidate_ir_urls("http://example.com/en/home?x=1")
    assert urls[0] == "https://example.com/investors"


def test_candidate_ir_urls_rejects_empty_website():
    with pytest.raises(ValueError):
        candidate_ir_urls("   ")


# ---------------------------------------------------------------------------
# robots_allows
# ---------------------------------------------------------------------------


def test_robots_allows_default_agent_from_fixture():
    assert robots_allows(ROBOTS_TXT, "/investors") is True
    assert robots_allows(ROBOTS_TXT, "/admin") is False
    assert robots_allows(ROBOTS_TXT, "/admin/users") is False
    assert robots_allows(ROBOTS_TXT, "/checkout") is False


def test_robots_allows_falls_back_to_star_for_unnamed_agent():
    assert robots_allows(ROBOTS_TXT, "/investors", agent="portfolio-copilot") is True


def test_robots_allows_uses_named_group_over_star():
    assert robots_allows(ROBOTS_TXT, "/anything", agent="BadBot") is False
    assert robots_allows(ROBOTS_TXT, "/anything", agent="badbot") is False  # case-insensitive


def test_robots_allows_longest_match_wins_on_conflict():
    txt = "User-agent: *\nDisallow: /investors\nAllow: /investors/public\n"
    assert robots_allows(txt, "/investors/public") is True
    assert robots_allows(txt, "/investors/private") is False
    assert robots_allows(txt, "/other") is True


def test_robots_allows_empty_disallow_means_allow_everything():
    txt = "User-agent: *\nDisallow:\n"
    assert robots_allows(txt, "/anything") is True


def test_robots_allows_no_groups_means_allowed():
    assert robots_allows("", "/investors") is True
    assert robots_allows("Sitemap: https://example.com/sitemap.xml\n", "/investors") is True


def test_robots_allows_path_without_leading_slash():
    assert robots_allows(ROBOTS_TXT, "admin") is False


# ---------------------------------------------------------------------------
# extract_ir_links
# ---------------------------------------------------------------------------


def test_extract_ir_links_classifies_kinds_and_dates():
    links = extract_ir_links(IR_HTML, "https://www.example.com/investors")
    by_title = {link["title"]: link for link in links}

    earnings = by_title["Q2 2025 Earnings Release - August 5, 2025"]
    assert earnings["kind"] == "earnings_release"
    assert earnings["date"] == "August 5, 2025"
    assert earnings["url"] == "https://www.example.com/docs/q2-2025-earnings-release.pdf"

    presentation = by_title["Investor Presentation, August 2025"]
    assert presentation["kind"] == "presentation"
    assert presentation["date"] == "2025"  # no day stated -> falls back to the bare year

    annual = by_title["Annual Report 2024"]
    assert annual["kind"] == "annual_report"
    assert annual["date"] == "2024"

    quarterly = by_title["Form 10-Q for the quarter ended March 31, 2025"]
    assert quarterly["kind"] == "quarterly_report"
    assert quarterly["date"] == "March 31, 2025"

    guidance = by_title["Example Corp Raises Full-Year Guidance"]
    assert guidance["kind"] == "guidance"
    assert guidance["date"] is None
    assert guidance["url"] == "https://newsroom.example.com/2025/07/example-corp-raises-guidance"

    press = by_title["Example Corp Announces New Partnership (Press Release)"]
    assert press["kind"] == "press_release"

    other = by_title["Contact Investor Relations"]
    assert other["kind"] == "other"
    assert other["date"] is None


def test_extract_ir_links_skips_javascript_and_mailto_links():
    links = extract_ir_links(IR_HTML, "https://www.example.com/investors")
    urls = {link["url"] for link in links}
    assert not any(u.startswith("javascript:") for u in urls)
    assert not any(u.startswith("mailto:") for u in urls)


def test_extract_ir_links_deduplicates_repeated_hrefs():
    html = '<a href="/x">First</a><a href="/x">Second</a>'
    links = extract_ir_links(html, "https://example.com")
    assert len(links) == 1
    assert links[0]["title"] == "First"


def test_extract_ir_links_empty_page():
    assert extract_ir_links("<html><body>no links here</body></html>", "https://example.com") == []


# ---------------------------------------------------------------------------
# IRProvider.investor_relations
# ---------------------------------------------------------------------------


def test_investor_relations_finds_first_working_candidate(monkeypatch):
    calls = []

    def fake_get(url, timeout, headers, follow_redirects):
        calls.append(url)
        assert headers["User-Agent"] == DEFAULT_USER_AGENT
        if url.endswith("/robots.txt"):
            return _response(url, status_code=404)
        if url == "https://www.example.com/investors":
            return _response(url, text=IR_HTML)
        return _response(url, status_code=404)

    monkeypatch.setattr(httpx, "get", fake_get)
    provider = IRProvider()
    result = provider.investor_relations("https://www.example.com")

    assert result["ok"] is True
    assert result["ir_url"] == "https://www.example.com/investors"
    assert result["source"] == "company_ir"
    assert result["tier"] == "A"
    assert len(result["links"]) <= 25
    # the fixture has 6 distinct real kinds, 4 of them dated -> confidence 0.8;
    # "guidance" and "press_release" match a keyword but their one link carries no date,
    # so they still count as missing (a resolved, dated document, not just a mention).
    assert result["confidence"] == 0.8
    assert set(result["missing"]) == {"guidance", "press_release"}


def test_investor_relations_low_kind_diversity_gives_low_confidence(monkeypatch):
    sparse_html = '<a href="/contact">Contact us</a><a href="/about">About</a>'

    def fake_get(url, timeout, headers, follow_redirects):
        if url.endswith("/robots.txt"):
            return _response(url, status_code=404)
        if url == "https://www.example.com/investors":
            return _response(url, text=sparse_html)
        return _response(url, status_code=404)

    monkeypatch.setattr(httpx, "get", fake_get)
    result = IRProvider().investor_relations("https://www.example.com")
    assert result["ok"] is True
    assert result["confidence"] == 0.4
    assert set(result["missing"]) == {
        "annual_report",
        "quarterly_report",
        "earnings_release",
        "guidance",
        "presentation",
        "press_release",
    }


def test_investor_relations_skips_disallowed_path_and_tries_next_candidate(monkeypatch):
    """robots.txt for the main host blocks everything; the subdomain guess is allowed."""

    def fake_get(url, timeout, headers, follow_redirects):
        if url == "https://www.example.com/robots.txt":
            return _response(url, text="User-agent: *\nDisallow: /\n")
        if url == "https://ir.example.com/robots.txt":
            return _response(url, status_code=404)
        if url == "https://ir.example.com":
            return _response(url, text=IR_HTML)
        return _response(url, status_code=404)

    monkeypatch.setattr(httpx, "get", fake_get)
    result = IRProvider().investor_relations("https://www.example.com")

    assert result["ok"] is True
    assert result["ir_url"] == "https://ir.example.com"
    skipped = result["skipped"]
    assert skipped["https://www.example.com/investors"] == "disallowed by robots.txt"
    assert skipped["https://www.example.com/investor-relations"] == "disallowed by robots.txt"
    assert skipped["https://www.example.com/investor"] == "disallowed by robots.txt"
    assert skipped["https://www.example.com/ir"] == "disallowed by robots.txt"


def test_investor_relations_all_404_returns_readable_result(monkeypatch):
    def fake_get(url, timeout, headers, follow_redirects):
        return _response(url, status_code=404)

    monkeypatch.setattr(httpx, "get", fake_get)
    result = IRProvider().investor_relations("https://www.example.com")

    assert result["ok"] is False
    assert result["ir_url"] is None
    assert result["links"] == []
    assert result["confidence"] == 0.0
    assert result["error"]
    assert result["source"] == "company_ir"
    assert result["tier"] == "A"
    assert "as_of" in result


def test_investor_relations_never_exceeds_request_cap(monkeypatch):
    calls = []

    def fake_get(url, timeout, headers, follow_redirects):
        calls.append(url)
        return _response(url, status_code=404)

    monkeypatch.setattr(httpx, "get", fake_get)
    IRProvider().investor_relations("https://www.example.com")
    assert len(calls) <= MAX_REQUESTS


def test_investor_relations_accepts_website_without_scheme(monkeypatch):
    def fake_get(url, timeout, headers, follow_redirects):
        if url.endswith("/robots.txt"):
            return _response(url, status_code=404)
        if url == "https://example.com/investors":
            return _response(url, text=IR_HTML)
        return _response(url, status_code=404)

    monkeypatch.setattr(httpx, "get", fake_get)
    result = IRProvider().investor_relations("example.com")
    assert result["ir_url"] == "https://example.com/investors"


def test_investor_relations_uses_ttl_cache(monkeypatch):
    calls = []

    def fake_get(url, timeout, headers, follow_redirects):
        calls.append(url)
        if url.endswith("/robots.txt"):
            return _response(url, status_code=404)
        if url == "https://www.example.com/investors":
            return _response(url, text=IR_HTML)
        return _response(url, status_code=404)

    monkeypatch.setattr(httpx, "get", fake_get)
    provider = IRProvider()
    first = provider.investor_relations("https://www.example.com")
    second = provider.investor_relations("https://www.example.com")
    assert second is first
    # robots.txt + the one winning candidate on the first call; the second call is a cache hit
    assert len(calls) == 2


def test_investor_relations_network_error_on_a_candidate_is_recorded_and_skipped(monkeypatch):
    def fake_get(url, timeout, headers, follow_redirects):
        if url.endswith("/robots.txt"):
            return _response(url, status_code=404)
        if url == "https://www.example.com/investors":
            raise httpx.ConnectError("boom")
        if url == "https://www.example.com/investor-relations":
            return _response(url, text=IR_HTML)
        return _response(url, status_code=404)

    monkeypatch.setattr(httpx, "get", fake_get)
    result = IRProvider().investor_relations("https://www.example.com")
    assert result["ok"] is True
    assert result["ir_url"] == "https://www.example.com/investor-relations"
    assert "boom" in result["skipped"]["https://www.example.com/investors"]


# ---------------------------------------------------------------------------
# finding 38: confidence must reflect actual dated documents, not just how many
# keyword categories appear in link text/href
# ---------------------------------------------------------------------------


def test_investor_relations_nav_only_page_with_no_dates_is_low_confidence(monkeypatch):
    nav_only_html = (
        '<a href="/ir/annual-reports">Annual Reports</a>'
        '<a href="/ir/quarterly-reports">Quarterly Reports</a>'
        '<a href="/ir/press">Press Releases</a>'
    )

    def fake_get(url, timeout, headers, follow_redirects):
        if url.endswith("/robots.txt"):
            return _response(url, status_code=404)
        if url == "https://www.example.com/investors":
            return _response(url, text=nav_only_html)
        return _response(url, status_code=404)

    monkeypatch.setattr(httpx, "get", fake_get)
    result = IRProvider().investor_relations("https://www.example.com")
    assert result["ok"] is True
    assert all(link["date"] is None for link in result["links"])
    # Zero actual dated documents were found -- this must not read as tier-A high
    # confidence corroboration, even though three distinct keyword categories matched.
    assert result["confidence"] <= 0.4
