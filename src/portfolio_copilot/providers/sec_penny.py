"""SEC penny-stock signals: incoming dilution (EDGAR full-text search), realized
dilution (XBRL shares-outstanding series) and trading suspensions (enforcement RSS).

Zero-signup (live-verified 2026-08-29). Tier A. Reuses ``SECEdgarProvider`` for CIK
resolution and the SEC-mandated User-Agent (same pattern as ``sec_filings.py``), plus
its own throttle. Every method returns ``source``/``tier``/``as_of``/``confidence``
and degrades to ``ok: False`` with a readable reason instead of raising — a missing
series is declared, never returned as an invented value (CLAUDE.md rule 4).

Endpoints:
- ``https://efts.sec.gov/LATEST/search-index?q=...&forms=...&ciks=...`` — JSON hits
  for S-1/S-3/424B filings in a window: dilution IN ARRIVO.
- ``https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}/dei/
  EntityCommonStockSharesOutstanding.json`` — share-count series: dilution AVVENUTA.
- ``https://www.sec.gov/enforcement-litigation/trading-suspensions/rss`` — kill switch.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from portfolio_copilot.providers.cache import TTLCache
from portfolio_copilot.providers.sec_edgar import SECEdgarProvider
from portfolio_copilot.providers.sec_filings import RateLimiter

EFTS_URL = "https://efts.sec.gov/LATEST/search-index"
SHARES_URL = (
    "https://data.sec.gov/api/xbrl/companyconcept/CIK{cik:010d}"
    "/dei/EntityCommonStockSharesOutstanding.json"
)
SUSPENSIONS_RSS_URL = "https://www.sec.gov/enforcement-litigation/trading-suspensions/rss"
DILUTION_FORMS = "S-1,S-3,424B1,424B2,424B3,424B4,424B5"
MAX_REQUESTS_PER_SECOND = 8.0

_RSS_ITEM_TITLE_RE = re.compile(r"<item>.*?<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)


class SECPennyProvider:
    """Keyless SEC penny-signal client; ``transport``/``clock``/``sleeper`` injectable."""

    def __init__(
        self,
        edgar: SECEdgarProvider | None = None,
        timeout: float = 15.0,
        ttl_seconds: float = 24 * 3600,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._edgar = edgar or SECEdgarProvider()
        self._client = httpx.Client(transport=transport, timeout=timeout)
        self._cache = TTLCache(ttl_seconds)
        self._limiter = RateLimiter(MAX_REQUESTS_PER_SECOND, clock=clock, sleeper=sleeper)

    def _envelope(self, source: str, extra: dict[str, Any]) -> dict[str, Any]:
        out = {
            "source": source,
            "tier": "A",
            "as_of": datetime.now(UTC).isoformat(),
            "confidence": 0.95,
        }
        out.update(extra)
        return out

    def _fail(self, source: str, error: str) -> dict[str, Any]:
        return self._envelope(source, {"ok": False, "error": error})

    def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        self._limiter.wait()
        return self._client.get(
            url, params=params, headers={"User-Agent": self._edgar.user_agent}
        )

    def dilution_filings(self, ticker: str, days: int = 365) -> dict[str, Any]:
        """S-1/S-3/424B filings for ``ticker`` in the last ``days`` — dilution ahead."""
        ticker = ticker.strip().upper()
        cik = self._edgar.cik_for_ticker(ticker)
        if cik is None:
            return self._fail("sec_efts", f"no CIK found for {ticker} (not an SEC filer)")
        key = f"efts:{cik}:{days}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        end = datetime.now(UTC).date()
        start = end - timedelta(days=days)
        response = self._get(
            EFTS_URL,
            params={
                "q": f'"{ticker}"',
                "forms": DILUTION_FORMS,
                "ciks": f"{cik:010d}",
                "startdt": start.isoformat(),
                "enddt": end.isoformat(),
            },
        )
        if response.status_code != 200:
            return self._fail("sec_efts", f"EFTS answered HTTP {response.status_code}")
        hits = ((response.json() or {}).get("hits") or {}).get("hits") or []
        filings = []
        for hit in hits:
            src = hit.get("_source") or {}
            forms = src.get("root_forms") or []
            filings.append(
                {
                    "form": forms[0] if forms else None,
                    "date": src.get("file_date"),
                    "adsh": hit.get("_id"),
                }
            )
        filings.sort(key=lambda f: str(f.get("date")))
        result = self._envelope(
            "sec_efts",
            {"ok": True, "ticker": ticker, "filings": filings, "count": len(filings)},
        )
        self._cache.set(key, result)
        return result

    def shares_outstanding(self, ticker: str) -> dict[str, Any]:
        """Share-count series (dei/EntityCommonStockSharesOutstanding) and the
        12-month percentage change — realized dilution, measured not inferred."""
        ticker = ticker.strip().upper()
        cik = self._edgar.cik_for_ticker(ticker)
        if cik is None:
            return self._fail("sec_xbrl", f"no CIK found for {ticker} (not an SEC filer)")
        response = self._get(SHARES_URL.format(cik=cik))
        if response.status_code != 200:
            return self._fail(
                "sec_xbrl", f"no shares-outstanding series (HTTP {response.status_code})"
            )
        points = ((response.json() or {}).get("units") or {}).get("shares") or []
        dated = sorted(
            (p for p in points if p.get("end") and p.get("val") is not None),
            key=lambda p: p["end"],
        )
        if not dated:
            return self._fail("sec_xbrl", "shares-outstanding series is empty")
        latest = dated[-1]
        latest_date = datetime.fromisoformat(latest["end"]).date()
        target = latest_date - timedelta(days=365)
        year_ago = min(
            dated, key=lambda p: abs(datetime.fromisoformat(p["end"]).date() - target)
        )
        change_12m = (
            (latest["val"] / year_ago["val"] - 1.0) * 100.0 if year_ago["val"] else None
        )
        return self._envelope(
            "sec_xbrl",
            {
                "ok": True,
                "ticker": ticker,
                "latest": latest["val"],
                "latest_date": latest["end"],
                "compared_to": year_ago["end"],
                "change_12m_pct": change_12m,
                "series": dated[-8:],
            },
        )

    def trading_suspension(
        self, ticker: str, company_name: str | None = None
    ) -> dict[str, Any]:
        """Whether ``ticker`` (word-boundary match) or ``company_name`` (substring)
        appears in the SEC trading-suspensions RSS. ``match_type`` says which matched:
        short tickers can false-positive, so the caller shows it."""
        ticker = ticker.strip().upper()
        text = self._cache.get("suspensions_rss")
        if text is None:
            response = self._get(SUSPENSIONS_RSS_URL)
            if response.status_code != 200:
                return self._fail(
                    "sec_rss", f"suspensions RSS answered HTTP {response.status_code}"
                )
            text = response.text
            self._cache.set("suspensions_rss", text)
        titles = _RSS_ITEM_TITLE_RE.findall(text)
        ticker_re = re.compile(rf"\b{re.escape(ticker)}\b")
        hits, match_type = [], None
        for title in titles:
            if ticker_re.search(title.upper()):
                hits.append(title.strip())
                match_type = match_type or "ticker"
            elif company_name and company_name.lower() in title.lower():
                hits.append(title.strip())
                match_type = match_type or "name"
        return self._envelope(
            "sec_rss",
            {
                "ok": True,
                "ticker": ticker,
                "hit": bool(hits),
                "match_type": match_type,
                "items": hits,
            },
        )
