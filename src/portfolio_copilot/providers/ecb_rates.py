"""ECB Data Portal deposit facility rate (free, no key) -- the floor of the rate corridor.

Paired with the Eurostat HICP series to read a deterministic monetary "regime": how far the
policy rate sits above, or below, current inflation. One SDMX-CSV row, no signup, no key.
"""

from __future__ import annotations

import csv
import io
from typing import Any

import httpx

from portfolio_copilot.providers.cache import TTLCache

ECB_DFR_URL = (
    "https://data-api.ecb.europa.eu/service/data/FM/B.U2.EUR.4F.KR.DFR.LEV"
    "?format=csvdata&lastNObservations=1"
)


def parse_ecb_csv(text: str) -> tuple[str, float]:
    """Return (TIME_PERIOD, OBS_VALUE) for the most recent row of an SDMX-CSV body.

    Rows with an empty OBS_VALUE (ECB suppresses some observations) are skipped rather than
    coerced into a number.
    """
    reader = csv.DictReader(io.StringIO(text))
    rows = [
        row for row in reader if row.get("TIME_PERIOD") and row.get("OBS_VALUE") not in (None, "")
    ]
    if not rows:
        raise ValueError("ECB Data Portal CSV: no observations found")
    latest = max(rows, key=lambda row: row["TIME_PERIOD"])
    return latest["TIME_PERIOD"], float(latest["OBS_VALUE"])


class ECBRatesProvider:
    source_name = "ecb_data_portal"

    def __init__(self, timeout: float = 10.0, ttl_seconds: float = 24 * 3600) -> None:
        self.timeout = timeout
        self._cache = TTLCache(ttl_seconds)

    def deposit_facility_rate(self) -> dict[str, Any]:
        """Current ECB deposit facility rate, or a degraded dict if unavailable.

        Never raises: a network failure or a malformed CSV degrades `value` to None with
        `confidence=0.0` instead of bubbling up, per the "never invent missing data" rule.
        Only a successful read is cached, so a transient failure is retried next call.
        """
        cached = self._cache.get("dfr")
        if cached is not None:
            return cached
        try:
            response = httpx.get(ECB_DFR_URL, timeout=self.timeout, follow_redirects=True)
            response.raise_for_status()
            as_of, value = parse_ecb_csv(response.text)
        except (httpx.HTTPError, ValueError) as exc:
            return {
                "value": None,
                "as_of": None,
                "source": self.source_name,
                "tier": "A",
                "confidence": 0.0,
                "error": str(exc),
            }
        result = {
            "value": value,
            "as_of": as_of,
            "source": self.source_name,
            "tier": "A",
            "confidence": 1.0,
            "note": "ECB deposit facility rate (DFR), floor of the euro-area rate corridor.",
        }
        self._cache.set("dfr", result)
        return result
