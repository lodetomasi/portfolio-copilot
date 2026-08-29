"""ISIN -> ticker/exchange mapping via the free, keyless OpenFIGI mapping API.

Most European broker exports identify holdings by ISIN; the rest of this codebase
(yfinance, Finviz, SEC EDGAR) works from tickers. This module bridges the two with
OpenFIGI's public ``/v3/mapping`` endpoint, which needs no signup or API key for
anonymous use (25 requests/minute, up to 10 jobs per request).

Tier A source (reference/identifier data, not a market quote): a mapping result carries a
confidence of 1.0 on a hit and 0.0 on a miss, never an invented ticker. A miss or a
malformed response degrades to ``None`` for that ISIN with the reason recorded in
``OpenFIGIProvider.errors``; a rate-limited (HTTP 429) or otherwise failed response raises
``httpx.HTTPStatusError`` rather than being swallowed, so callers can see and back off.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import httpx

from portfolio_copilot.providers.cache import TTLCache

API_URL = "https://api.openfigi.com/v3/mapping"

# Yahoo Finance ticker suffix for each OpenFIGI exchCode. US-style codes take no suffix;
# unknown codes are deliberately absent so lookups fail closed rather than guess.
EXCHANGE_TO_YF_SUFFIX: dict[str, str] = {
    "US": "",
    "UN": "",
    "UW": "",
    "UA": "",
    "MI": ".MI",  # Borsa Italiana
    "GY": ".DE",  # Xetra
    "GR": ".DE",  # Xetra
    "LN": ".L",  # London
    "NA": ".AS",  # Euronext Amsterdam
    "FP": ".PA",  # Euronext Paris
}

_MISS = object()  # cache sentinel distinguishing "looked up, no match" from "not cached"


def _chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


class OpenFIGIProvider:
    """Anonymous OpenFIGI mapping client: chunked, rate-limited, cached, never fabricated."""

    source_name = "openfigi"

    def __init__(
        self,
        timeout: float = 10.0,
        ttl_seconds: float = 7 * 24 * 3600,
        max_jobs_per_request: int = 10,
        min_interval_s: float = 2.5,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_jobs_per_request <= 0:
            raise ValueError("max_jobs_per_request must be > 0")
        if min_interval_s < 0:
            raise ValueError("min_interval_s must be >= 0")
        self.timeout = timeout
        self.max_jobs_per_request = max_jobs_per_request
        self.min_interval_s = min_interval_s
        self._clock = clock
        self._sleep = sleeper
        self._last_call: float | None = None
        self._cache = TTLCache(ttl_seconds, clock=clock)
        self.errors: dict[str, str] = {}
        # Remembers, per (normalized) ISIN, the exch_code it was last looked up under --
        # lets provenance_for(isin) without an explicit exch_code resolve the right cache
        # entry instead of under-reporting a genuine hit as a miss (finding 18).
        self._last_exch_code: dict[str, str | None] = {}

    def _wait_for_rate_limit(self) -> None:
        """Leaky-bucket throttle: sleep just enough to keep POSTs >= min_interval_s apart."""
        now = self._clock()
        if self._last_call is None:
            self._last_call = now
            return
        next_allowed = self._last_call + self.min_interval_s
        if now < next_allowed:
            self._sleep(next_allowed - now)
            self._last_call = next_allowed
        else:
            self._last_call = now

    @staticmethod
    def _cache_key(isin: str, exch_code: str | None) -> str:
        return f"{isin}|{exch_code or ''}"

    @staticmethod
    def _job(isin: str, exch_code: str | None) -> dict:
        job: dict = {"idType": "ID_ISIN", "idValue": isin}
        if exch_code:
            job["exchCode"] = exch_code
        return job

    def _parse_item(self, isin: str, item: dict, exch_code: str | None) -> dict | None:
        if not isinstance(item, dict):
            self.errors[isin] = f"unexpected response shape: {type(item).__name__}"
            return None
        if "error" in item:
            self.errors[isin] = str(item["error"])
            return None
        if "warning" in item:
            self.errors[isin] = str(item["warning"])
            return None
        rows = item.get("data") or []
        if not rows:
            self.errors[isin] = "no data returned"
            return None
        if exch_code:
            row = next((c for c in rows if c.get("exchCode") == exch_code), None)
            if row is None:
                # OpenFIGI has a hit, just not on the requested exchange -- a miss for
                # this exchange, never a fabricated cross-exchange ticker (findings 17/19).
                self.errors[isin] = f"no match on exchange {exch_code}"
                return None
        else:
            row = rows[0]
        self.errors.pop(isin, None)
        return {
            "ticker": row.get("ticker"),
            "exch_code": row.get("exchCode"),
            "name": row.get("name"),
            "security_type": row.get("securityType"),
            "market_sector": row.get("marketSector"),
            "figi": row.get("figi"),
        }

    def map_isins(self, isins: list[str], exch_code: str | None = None) -> dict[str, dict | None]:
        """Map ISINs to ``{ticker, exch_code, name, security_type, market_sector, figi}``.

        Requests are chunked to at most ``max_jobs_per_request`` jobs and spaced by at
        least ``min_interval_s`` seconds (OpenFIGI's anonymous limit is 25 req/min).
        Results are cached per ``(isin, exch_code)`` for the provider's TTL. An ISIN that
        OpenFIGI can't resolve ('No identifier found', a malformed row, ...) maps to
        ``None`` with the reason recorded in ``self.errors[isin]``; a non-2xx HTTP
        response (e.g. 429 when the rate limit is exceeded) raises
        ``httpx.HTTPStatusError``.
        """
        results: dict[str, dict | None] = {}
        pending: list[str] = []
        seen: set[str] = set()
        for raw_isin in isins:
            isin = raw_isin.strip().upper()
            if not isin or isin in seen:
                continue
            seen.add(isin)
            self._last_exch_code[isin] = exch_code
            cached = self._cache.get(self._cache_key(isin, exch_code))
            if cached is None:
                pending.append(isin)
            else:
                results[isin] = None if cached is _MISS else cached

        for chunk in _chunks(pending, self.max_jobs_per_request):
            jobs = [self._job(isin, exch_code) for isin in chunk]
            self._wait_for_rate_limit()
            response = httpx.post(
                API_URL,
                json=jobs,
                timeout=self.timeout,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
            if len(payload) != len(chunk):
                # Upstream truncation/proxy anomaly: degrade every ISIN in this chunk to a
                # recorded miss instead of crashing the whole batch (finding 20).
                for isin in chunk:
                    self.errors[isin] = "malformed response (length mismatch)"
                    results[isin] = None
                continue
            for isin, item in zip(chunk, payload, strict=True):
                parsed = self._parse_item(isin, item, exch_code)
                results[isin] = parsed
                cache_value = _MISS if parsed is None else parsed
                self._cache.set(self._cache_key(isin, exch_code), cache_value)

        return results

    def provenance_for(self, isin: str, exch_code: str | None = None) -> dict:
        """Provenance for one ISIN's mapping outcome; call after ``map_isins``.

        An ISIN never looked up is treated as a miss (confidence 0.0) -- this reads the
        cache, it never triggers a network call. When ``exch_code`` is omitted, falls
        back to the exch_code this ISIN was last looked up under (if any), so a caller
        that mapped with one and later asks without it still resolves the right cache
        entry instead of under-reporting a genuine hit as a miss.
        """
        isin = isin.strip().upper()
        lookup_exch_code = exch_code if exch_code is not None else self._last_exch_code.get(isin)
        cached = self._cache.get(self._cache_key(isin, lookup_exch_code))
        hit = cached is not None and cached is not _MISS
        return {
            "source": self.source_name,
            "tier": "A",
            "as_of": datetime.now(UTC).isoformat(),
            "confidence": 1.0 if hit else 0.0,
        }

    def yf_ticker_for(self, isin: str, exch_code: str = "MI") -> str | None:
        """Compose a yfinance-style ticker for ``isin`` on ``exch_code``.

        Maps the ISIN via OpenFIGI restricted to that exchange, then appends the Yahoo
        Finance suffix for it (table-driven, see ``EXCHANGE_TO_YF_SUFFIX``). Returns
        ``None`` when the exchange is unknown or the mapping misses -- never a guess.
        """
        suffix = EXCHANGE_TO_YF_SUFFIX.get(exch_code.upper())
        if suffix is None:
            return None
        normalized_isin = isin.strip().upper()
        result = self.map_isins([isin], exch_code=exch_code).get(normalized_isin)
        ticker = result.get("ticker") if result else None
        if not ticker:
            return None
        return f"{ticker}{suffix}"
