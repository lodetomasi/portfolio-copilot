"""Offline, deterministic tests for providers.finra (FINRA Query API + Reg SHO CDN).

``httpx.MockTransport`` fixtures mirror the shapes live-verified on 2026-08-29:
Query API datasets answer JSON lists of records; the Reg SHO daily files are
pipe-delimited text. No network, no keys.
"""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest

from portfolio_copilot.providers.finra import FINRAProvider

SHORT_INTEREST_ROWS = [
    {
        "symbolCode": "GBUX",
        "currentShortPositionQuantity": 1500000,
        "daysToCoverQuantity": 6.4,
        "changePercent": 12.5,
        "settlementDate": "2026-08-15",
        "marketClassCode": "OTC",
    }
]

THRESHOLD_ROWS = [{"symbolCode": "GBUX", "tradeDate": "2026-08-28"}]

DAILY_HEADER = "Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market"
DAILY_FORF = f"{DAILY_HEADER}\n20260828|GBUX|60000|0|100000|ORF\n20260828|OTHR|1|0|2|ORF"
DAILY_CNMS = f"{DAILY_HEADER}\n20260828|AAPL|100|0|400|B,Q,N"

OTC_DAILY_ROWS = [
    {
        "issueSymbolIdentifier": "GBUX",
        "actionDescription": "Reverse Split 1:20",
        "dailyListDatetime": "2026-07-01",
    }
]


def _transport(short_rows=None, threshold_rows=None, forf=DAILY_FORF, cnms=DAILY_CNMS,
               otc_rows=None, status=200):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if status != 200:
            return httpx.Response(status, text="down")
        if "consolidatedShortInterest" in url:
            return httpx.Response(200, json=short_rows if short_rows is not None else [])
        if "thresholdList" in url:
            return httpx.Response(200, json=threshold_rows if threshold_rows is not None else [])
        if "otcDailyList" in url:
            return httpx.Response(200, json=otc_rows if otc_rows is not None else [])
        if "regsho/daily/FORF" in url:
            return httpx.Response(200, text=forf) if forf is not None else httpx.Response(404)
        if "regsho/daily/CNMS" in url:
            return httpx.Response(200, text=cnms) if cnms is not None else httpx.Response(404)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def _provider(**kw) -> FINRAProvider:
    transport = kw.pop("transport")
    return FINRAProvider(transport=transport, sleeper=lambda s: None, **kw)


def test_short_interest_happy_path():
    p = _provider(transport=_transport(short_rows=SHORT_INTEREST_ROWS))
    out = p.short_interest("gbux")
    assert out["ok"] is True
    assert out["short_position"] == 1500000
    assert out["days_to_cover"] == pytest.approx(6.4)
    assert out["change_percent"] == pytest.approx(12.5)
    assert out["settlement_date"] == "2026-08-15"
    assert out["source"] == "finra" and out["tier"] == "A" and out["as_of"]


def test_short_interest_symbol_absent_is_declared():
    p = _provider(transport=_transport(short_rows=[]))
    out = p.short_interest("NOPE")
    assert out["ok"] is False
    assert "NOPE" in out["error"]


def test_daily_short_volume_found_in_forf_with_ratio():
    p = _provider(transport=_transport())
    out = p.daily_short_volume("GBUX", day=date(2026, 8, 28))
    assert out["ok"] is True
    assert out["short_volume"] == 60000
    assert out["total_volume"] == 100000
    assert out["short_ratio"] == pytest.approx(0.6)
    assert out["market_file"] == "FORF"


def test_daily_short_volume_falls_back_to_cnms():
    p = _provider(transport=_transport())
    out = p.daily_short_volume("AAPL", day=date(2026, 8, 28))
    assert out["ok"] is True
    assert out["short_ratio"] == pytest.approx(0.25)
    assert out["market_file"] == "CNMS"


def test_daily_short_volume_symbol_missing_everywhere_is_declared():
    p = _provider(transport=_transport())
    out = p.daily_short_volume("GHOST", day=date(2026, 8, 28))
    assert out["ok"] is False
    assert "GHOST" in out["error"]


def test_daily_short_volume_walks_back_over_holidays():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        calls.append(url)
        if "20260830" in url or "20260829" in url:
            return httpx.Response(404)
        if "regsho/daily/FORF" in url and "20260828" in url:
            return httpx.Response(200, text=DAILY_FORF)
        return httpx.Response(404)

    p = FINRAProvider(transport=httpx.MockTransport(handler), sleeper=lambda s: None)
    out = p.daily_short_volume("GBUX", day=date(2026, 8, 30))
    assert out["ok"] is True
    assert out["as_of_day"] == "2026-08-28"


def test_corporate_actions_flags_reverse_split():
    p = _provider(transport=_transport(otc_rows=OTC_DAILY_ROWS))
    out = p.corporate_actions("GBUX")
    assert out["ok"] is True
    assert out["reverse_split"] is True
    assert out["bankruptcy"] is False
    assert len(out["records"]) == 1


def test_threshold_list_membership():
    p = _provider(transport=_transport(threshold_rows=THRESHOLD_ROWS))
    assert p.on_threshold_list("GBUX")["on_list"] is True
    p2 = _provider(transport=_transport(threshold_rows=[]))
    assert p2.on_threshold_list("GBUX")["on_list"] is False


def test_http_error_degrades_to_structured_result():
    p = _provider(transport=_transport(status=500))
    out = p.short_interest("GBUX")
    assert out["ok"] is False and "500" in out["error"]


def test_symbol_filter_is_sent_in_post_body():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if "consolidatedShortInterest" in str(request.url):
            seen.update(json.loads(request.content.decode()))
            return httpx.Response(200, json=SHORT_INTEREST_ROWS)
        return httpx.Response(404)

    p = FINRAProvider(transport=httpx.MockTransport(handler), sleeper=lambda s: None)
    p.short_interest("GBUX")
    assert seen["compareFilters"][0]["fieldValue"] == "GBUX"
