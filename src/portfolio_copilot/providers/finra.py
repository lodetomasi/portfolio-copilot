"""FINRA data for penny/micro-cap stocks: Query API (otcMarket group) + Reg SHO CDN.

Zero-signup, keyless (live-verified 2026-08-29). One organisation, two channels:

- Query API ``https://api.finra.org/data/group/otcMarket/name/<dataset>`` — JSON
  records via POST ``compareFilters`` on ``symbolCode``: ``consolidatedShortInterest``
  (bi-monthly short interest incl. OTC), ``otcDailyList`` (corporate actions: reverse
  splits, bankruptcy/delete flags), ``thresholdList`` (Reg SHO threshold securities =
  persistent fails-to-deliver).
- CDN ``https://cdn.finra.org/equity/regsho/daily/<PFX>shvol<YYYYMMDD>.txt`` —
  pipe-delimited daily short-sale volume; ``FORF`` covers OTC (the real penny tape),
  ``CNMS`` the consolidated NMS.

No published rate limit → prudential self-throttle (4 req/s). Tier A (regulator).
Every method returns ``source``/``tier``/``as_of``/``confidence`` and degrades to a
structured ``ok: False`` instead of raising — a symbol absent from a file is declared,
never returned as an invented zero (CLAUDE.md rule 4).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import httpx

from portfolio_copilot.providers.cache import TTLCache
from portfolio_copilot.providers.sec_filings import RateLimiter

QUERY_URL = "https://api.finra.org/data/group/otcMarket/name/{dataset}"
DAILY_URL = "https://cdn.finra.org/equity/regsho/daily/{prefix}shvol{day:%Y%m%d}.txt"
DAILY_PREFIXES = ("FORF", "CNMS")  # OTC first: that is where the pennies live
MAX_WALKBACK_DAYS = 5
MAX_REQUESTS_PER_SECOND = 4.0

# Live-verified 2026-08-29/30 contro gli schemi reali: consolidatedShortInterest filtra
# su ``symbolCode``, thresholdList su ``issueSymbolIdentifier``, otcDailyList su
# ``oldSymbolCode`` (il suo schema non ha issueSymbolIdentifier).
_FILTER_FIELD = {
    "consolidatedShortInterest": "symbolCode",
    "otcDailyList": "oldSymbolCode",
    "thresholdList": "issueSymbolIdentifier",
}


class FINRAProvider:
    """Keyless FINRA client. ``transport``/``clock``/``sleeper`` are injectable so
    tests run offline and the throttle is deterministic."""

    def __init__(
        self,
        timeout: float = 15.0,
        ttl_seconds: float = 6 * 3600,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = httpx.Client(transport=transport, timeout=timeout)
        self._cache = TTLCache(ttl_seconds)
        self._limiter = RateLimiter(MAX_REQUESTS_PER_SECOND, clock=clock, sleeper=sleeper)

    def _envelope(self, extra: dict[str, Any]) -> dict[str, Any]:
        out = {
            "source": "finra",
            "tier": "A",
            "as_of": datetime.now(UTC).isoformat(),
            "confidence": 0.9,
        }
        out.update(extra)
        return out

    def _fail(self, error: str) -> dict[str, Any]:
        return self._envelope({"ok": False, "error": error})

    def _query(self, dataset: str, symbol: str) -> list[dict] | dict:
        """POST the dataset filtered on ``symbolCode``; a non-200 or non-JSON answer
        comes back as an ``ok: False`` dict for the caller to pass through."""
        key = f"{dataset}:{symbol}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        self._limiter.wait()
        response = self._client.post(
            QUERY_URL.format(dataset=dataset),
            json={
                # live-verified 2026-08-30: "limit" è OBBLIGATORIO (senza → HTTP 400)
                # e compareType va MAIUSCOLO ("EQUAL") o il filtro viene ignorato.
                "limit": 200,
                "compareFilters": [
                    {
                        "fieldName": _FILTER_FIELD[dataset],
                        "fieldValue": symbol,
                        "compareType": "EQUAL",
                    }
                ],
            },
            headers={"Accept": "application/json"},
        )
        if response.status_code not in (200, 204):
            return self._fail(f"FINRA {dataset} answered HTTP {response.status_code}")
        if response.status_code == 204 or not response.content.strip():
            # live-verified 2026-08-30: zero righe = HTTP 204 (o 200 a corpo vuoto)
            rows: list[dict] | dict = []
            self._cache.set(key, rows)
            return rows
        try:
            rows = response.json()
        except ValueError:
            return self._fail(f"FINRA {dataset} returned non-JSON content")
        if not isinstance(rows, list):
            rows = rows.get("data", []) if isinstance(rows, dict) else []
        self._cache.set(key, rows)
        return rows

    # -- Query API datasets ------------------------------------------------------

    def short_interest(self, symbol: str) -> dict[str, Any]:
        """Latest bi-monthly consolidated short interest for ``symbol`` (incl. OTC)."""
        symbol = symbol.strip().upper()
        rows = self._query("consolidatedShortInterest", symbol)
        if isinstance(rows, dict):
            return rows
        if not rows:
            return self._fail(f"no short-interest record for {symbol}")
        latest = max(rows, key=lambda r: str(r.get("settlementDate", "")))
        return self._envelope(
            {
                "ok": True,
                "symbol": symbol,
                "short_position": latest.get("currentShortPositionQuantity"),
                "days_to_cover": latest.get("daysToCoverQuantity"),
                "change_percent": latest.get("changePercent"),
                "settlement_date": latest.get("settlementDate"),
                "market_class": latest.get("marketClassCode"),
            }
        )

    def corporate_actions(self, symbol: str) -> dict[str, Any]:
        """OTC daily-list records for ``symbol`` with deterministic flags read from the
        schema's own fields (live-verified 2026-08-30): ``reverseSplitRate`` non-vuoto,
        ``bankruptcyFlag``/``securityDeleteFlag`` == "Y"."""
        symbol = symbol.strip().upper()
        rows = self._query("otcDailyList", symbol)
        if isinstance(rows, dict):
            return rows
        flags = {
            "reverse_split": any(
                row.get("reverseSplitRate") not in (None, "", 0) for row in rows
            ),
            "bankruptcy": any(
                str(row.get("bankruptcyFlag", "")).upper() == "Y" for row in rows
            ),
            "deletion": any(
                str(row.get("securityDeleteFlag", "")).upper() == "Y" for row in rows
            ),
        }
        return self._envelope({"ok": True, "symbol": symbol, "records": rows, **flags})

    def on_threshold_list(self, symbol: str) -> dict[str, Any]:
        """Whether ``symbol`` sits on the Reg SHO threshold list (persistent FTDs)."""
        symbol = symbol.strip().upper()
        rows = self._query("thresholdList", symbol)
        if isinstance(rows, dict):
            return rows
        return self._envelope({"ok": True, "symbol": symbol, "on_list": bool(rows)})

    # -- Reg SHO daily short volume ------------------------------------------------

    def daily_short_volume(self, symbol: str, day: date | None = None) -> dict[str, Any]:
        """Daily short-sale volume for ``symbol``: FORF (OTC) first, then CNMS,
        walking back up to ``MAX_WALKBACK_DAYS`` over weekends/holidays. The day
        actually used is declared in ``as_of_day``."""
        symbol = symbol.strip().upper()
        current = day or datetime.now(UTC).date()
        for _ in range(MAX_WALKBACK_DAYS + 1):
            found_any_file = False
            for prefix in DAILY_PREFIXES:
                text = self._daily_file(prefix, current)
                if text is None:
                    continue
                found_any_file = True
                row = self._find_symbol_row(text, symbol)
                if row is not None:
                    short_vol, total_vol = row
                    ratio = short_vol / total_vol if total_vol else None
                    return self._envelope(
                        {
                            "ok": True,
                            "symbol": symbol,
                            "short_volume": short_vol,
                            "total_volume": total_vol,
                            "short_ratio": ratio,
                            "market_file": prefix,
                            "as_of_day": current.isoformat(),
                        }
                    )
            if found_any_file:
                return self._fail(
                    f"{symbol} not present in FORF/CNMS daily files for {current.isoformat()}"
                )
            current -= timedelta(days=1)
        return self._fail(
            f"no Reg SHO daily file found within {MAX_WALKBACK_DAYS} days of "
            f"{(day or datetime.now(UTC).date()).isoformat()}"
        )

    def _daily_file(self, prefix: str, day: date) -> str | None:
        key = f"daily:{prefix}:{day.isoformat()}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        self._limiter.wait()
        response = self._client.get(DAILY_URL.format(prefix=prefix, day=day))
        if response.status_code != 200:
            return None
        self._cache.set(key, response.text)
        return response.text

    @staticmethod
    def _find_symbol_row(text: str, symbol: str) -> tuple[float, float] | None:
        """I volumi nei file reali sono FLOAT (es. ``39027.690938``, live-verified
        2026-08-29): mai ``int()``, avrebbe scartato righe valide."""
        for line in text.splitlines()[1:]:
            parts = line.split("|")
            if len(parts) >= 5 and parts[1].strip().upper() == symbol:
                try:
                    return float(parts[2]), float(parts[4])
                except ValueError:
                    return None
        return None
