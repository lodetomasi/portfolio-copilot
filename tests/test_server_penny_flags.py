"""Offline tests for the penny_flags MCP tool (both providers faked)."""

from __future__ import annotations

import pytest

from portfolio_copilot import server

FINRA_OK = {
    "short_interest": {
        "ok": True, "short_position": 1_500_000, "days_to_cover": 6.4,
        "change_percent": 12.5, "settlement_date": "2026-08-15",
        "source": "finra", "as_of": "2026-08-29T00:00:00+00:00",
    },
    "daily": {
        "ok": True, "short_volume": 60000, "total_volume": 100000,
        "short_ratio": 0.6, "market_file": "FORF", "as_of_day": "2026-08-28",
        "source": "finra",
    },
    "actions": {
        "ok": True, "records": [{"actionDescription": "Reverse Split 1:20"}],
        "reverse_split": True, "bankruptcy": False, "deletion": False, "source": "finra",
    },
    "threshold": {"ok": True, "on_list": True, "source": "finra"},
}

SEC_OK = {
    "dilution": {
        "ok": True, "count": 2,
        "filings": [{"form": "S-1", "date": "2026-05-02", "adsh": "x"}], "source": "sec_efts",
    },
    "shares": {
        "ok": True, "latest": 130_000_000, "change_12m_pct": 30.0,
        "series": [], "source": "sec_xbrl",
    },
    "suspension": {
        "ok": True, "hit": False, "match_type": None, "items": [], "source": "sec_rss",
    },
}


class FakeFinra:
    def __init__(self, data=None, down=False):
        self._d = data or FINRA_OK
        self._down = down

    def _get(self, key):
        if self._down:
            return {"ok": False, "error": "FINRA down (HTTP 500)", "source": "finra"}
        return self._d[key]

    def short_interest(self, symbol):
        return self._get("short_interest")

    def daily_short_volume(self, symbol, day=None):
        return self._get("daily")

    def corporate_actions(self, symbol):
        return self._get("actions")

    def on_threshold_list(self, symbol):
        return self._get("threshold")


class FakeSecPenny:
    def __init__(self, data=None, no_cik=False):
        self._d = data or SEC_OK
        self._no_cik = no_cik

    def _get(self, key, source):
        if self._no_cik:
            return {"ok": False, "error": "no CIK found for X", "source": source}
        return self._d[key]

    def dilution_filings(self, ticker, days=365):
        return self._get("dilution", "sec_efts")

    def shares_outstanding(self, ticker):
        return self._get("shares", "sec_xbrl")

    def trading_suspension(self, ticker, company_name=None):
        return self._get("suspension", "sec_rss")


def _patch(monkeypatch, finra=None, sec=None):
    monkeypatch.setattr(server, "finra_provider", finra or FakeFinra())
    monkeypatch.setattr(server, "sec_penny_provider", sec or FakeSecPenny())


def test_penny_flags_full_fixture_yields_expected_red_flags(monkeypatch):
    _patch(monkeypatch)
    out = server.penny_flags("GBUX")
    assert out["ok"] is True
    assert out["days_to_cover"] == pytest.approx(6.4)
    assert out["daily_short_ratio"] == pytest.approx(0.6)
    assert out["shares_outstanding_change_12m_pct"] == pytest.approx(30.0)
    assert out["missing"] == []
    flags = " | ".join(out["red_flags"])
    # 5 flag deterministici, ognuno col numero che lo genera
    assert "reverse split" in flags
    assert "2 dilution filings" in flags
    assert "+30.0%" in flags
    assert "threshold list" in flags
    assert "days-to-cover 6.4" in flags
    assert len(out["red_flags"]) == 5


def test_penny_flags_clean_name_has_no_flags(monkeypatch):
    clean_finra = dict(FINRA_OK)
    clean_finra["actions"] = {**FINRA_OK["actions"], "reverse_split": False, "records": []}
    clean_finra["threshold"] = {"ok": True, "on_list": False, "source": "finra"}
    clean_finra["short_interest"] = {**FINRA_OK["short_interest"], "days_to_cover": 1.2}
    clean_sec = dict(SEC_OK)
    clean_sec["dilution"] = {"ok": True, "count": 0, "filings": [], "source": "sec_efts"}
    clean_sec["shares"] = {**SEC_OK["shares"], "change_12m_pct": 2.0}
    _patch(monkeypatch, finra=FakeFinra(clean_finra), sec=FakeSecPenny(clean_sec))
    out = server.penny_flags("MSFT")
    assert out["ok"] is True
    assert out["red_flags"] == []


def test_penny_flags_suspension_is_a_flag(monkeypatch):
    sec = dict(SEC_OK)
    sec["suspension"] = {
        "ok": True, "hit": True, "match_type": "name",
        "items": ["In the Matter of X Corp (GBUX)"], "source": "sec_rss",
    }
    _patch(monkeypatch, sec=FakeSecPenny(sec))
    out = server.penny_flags("GBUX")
    assert any("suspension" in f for f in out["red_flags"])


def test_penny_flags_short_ticker_suspension_match_needs_name(monkeypatch):
    # match solo su ticker di 2 lettere -> nessun red flag (falsi positivi)
    sec = dict(SEC_OK)
    sec["suspension"] = {
        "ok": True, "hit": True, "match_type": "ticker", "items": ["x"], "source": "sec_rss",
    }
    _patch(monkeypatch, sec=FakeSecPenny(sec))
    out = server.penny_flags("GO")
    assert not any("suspension" in f for f in out["red_flags"])


def test_penny_flags_finra_down_declares_missing_but_stays_ok(monkeypatch):
    _patch(monkeypatch, finra=FakeFinra(down=True))
    out = server.penny_flags("GBUX")
    assert out["ok"] is True
    assert out["short_interest"] is None
    assert out["daily_short_ratio"] is None
    assert set(out["missing"]) >= {"short_interest", "daily_short_volume",
                                   "corporate_actions", "threshold_list"}
    # i flag SEC restano calcolabili
    assert any("dilution" in f for f in out["red_flags"])


def test_penny_flags_no_cik_declares_sec_missing(monkeypatch):
    _patch(monkeypatch, sec=FakeSecPenny(no_cik=True))
    out = server.penny_flags("GBUX")
    assert out["ok"] is True
    assert set(out["missing"]) >= {"dilution_filings", "shares_outstanding",
                                   "trading_suspension"}
