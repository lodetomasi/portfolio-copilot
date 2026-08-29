"""Offline, deterministic tests for providers.sec_penny (EFTS dilution search,
XBRL shares outstanding, trading-suspension RSS). Shapes mirror the live-verified
responses of 2026-08-29; no network, no keys."""

from __future__ import annotations

import httpx
import pytest

from portfolio_copilot.providers.sec_penny import SECPennyProvider

EFTS_HITS = {
    "hits": {
        "hits": [
            {"_id": "0001-s1", "_source": {"file_date": "2026-05-02", "root_forms": ["S-1"]}},
            {"_id": "0002-424", "_source": {"file_date": "2026-07-11", "root_forms": ["424B5"]}},
        ]
    }
}

SHARES_SERIES = {
    "units": {
        "shares": [
            {"end": "2025-06-30", "val": 100_000_000},
            {"end": "2025-09-30", "val": 105_000_000},
            {"end": "2025-12-31", "val": 110_000_000},
            {"end": "2026-03-31", "val": 118_000_000},
            {"end": "2026-06-30", "val": 130_000_000},
        ]
    }
}

RSS = """<?xml version="1.0"?><rss><channel>
<item><title>In the Matter of GreenBux Holdings, Inc. (GBUX)</title>
<pubDate>Fri, 28 Aug 2026 10:00:00 EDT</pubDate></item>
<item><title>In the Matter of Other Corp (OTHR)</title>
<pubDate>Mon, 03 Aug 2026 10:00:00 EDT</pubDate></item>
</channel></rss>"""


class FakeEdgar:
    user_agent = "test-agent (test@example.com)"

    def cik_for_ticker(self, ticker: str) -> int | None:
        return 1234567 if ticker.upper() in {"GBUX", "MSFT"} else None


def _transport(efts=EFTS_HITS, shares=SHARES_SERIES, rss=RSS, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if status != 200:
            return httpx.Response(status, text="down")
        if "efts.sec.gov" in url:
            return httpx.Response(200, json=efts)
        if "companyconcept" in url:
            return httpx.Response(200, json=shares) if shares is not None else httpx.Response(404)
        if "trading-suspensions" in url:
            return httpx.Response(200, text=rss)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _provider(**kw) -> SECPennyProvider:
    transport = kw.pop("transport")
    return SECPennyProvider(
        edgar=FakeEdgar(), transport=transport, sleeper=lambda s: None, **kw
    )


def test_dilution_filings_counts_and_lists():
    p = _provider(transport=_transport())
    out = p.dilution_filings("GBUX", days=365)
    assert out["ok"] is True
    assert out["count"] == 2
    assert out["filings"][0]["form"] == "S-1"
    assert out["filings"][0]["date"] == "2026-05-02"
    assert out["tier"] == "A" and out["source"] == "sec_efts"


def test_dilution_filings_unknown_ticker_declared():
    p = _provider(transport=_transport())
    out = p.dilution_filings("NOPE")
    assert out["ok"] is False and "CIK" in out["error"]


def test_shares_outstanding_change_12m():
    p = _provider(transport=_transport())
    out = p.shares_outstanding("GBUX")
    assert out["ok"] is True
    assert out["latest"] == 130_000_000
    # punto ~12 mesi prima dell'ultimo: 2025-06-30 = 100M -> +30%
    assert out["change_12m_pct"] == pytest.approx(30.0)
    assert len(out["series"]) == 5


def test_shares_outstanding_missing_series_declared():
    p = _provider(transport=_transport(shares=None))
    out = p.shares_outstanding("GBUX")
    assert out["ok"] is False


def test_trading_suspension_hit_by_ticker():
    p = _provider(transport=_transport())
    out = p.trading_suspension("GBUX")
    assert out["ok"] is True
    assert out["hit"] is True
    assert out["match_type"] == "ticker"
    assert "GreenBux" in out["items"][0]


def test_trading_suspension_no_hit():
    p = _provider(transport=_transport())
    out = p.trading_suspension("MSFT")
    assert out["ok"] is True and out["hit"] is False


def test_trading_suspension_name_match():
    p = _provider(transport=_transport())
    out = p.trading_suspension("ZZZZ", company_name="Other Corp")
    assert out["hit"] is True and out["match_type"] == "name"


def test_http_error_degrades():
    p = _provider(transport=_transport(status=500))
    out = p.dilution_filings("GBUX")
    assert out["ok"] is False and "500" in out["error"]
