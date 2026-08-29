"""Official ECB euro reference rates (free, no key). One XML file, all currencies vs EUR."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime

import httpx

from portfolio_copilot.providers.cache import TTLCache

ECB_DAILY_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
_NS = {"ex": "http://www.ecb.int/vocabulary/2002-08-01/eurofxref"}


def parse_ecb_xml(text: str) -> dict:
    """Return {"as_of": "YYYY-MM-DD", "rates": {"USD": 1.08, ...}} (units of currency per 1 EUR)."""
    root = ET.fromstring(text)
    day = root.find(".//ex:Cube[@time]", _NS)
    if day is None:
        raise ValueError("ECB XML: no dated Cube element")
    rates = {
        c.attrib["currency"]: float(c.attrib["rate"])
        for c in day.findall("ex:Cube", _NS)
        if "currency" in c.attrib and "rate" in c.attrib
    }
    if not rates:
        raise ValueError("ECB XML: no rates found")
    return {"as_of": day.attrib["time"], "rates": rates}


def convert_to_eur(amount: float, currency: str, rates: dict[str, float]) -> float | None:
    """Convert ``amount`` in ``currency`` to EUR using ECB rates. None if the pair is unknown."""
    code = currency.upper()
    if code == "EUR":
        return float(amount)
    rate = rates.get(code)
    if not rate:
        return None
    return float(amount) / rate


class ECBFXProvider:
    source_name = "ecb_eurofxref"

    def __init__(self, timeout: float = 10.0, ttl_seconds: float = 6 * 3600) -> None:
        self.timeout = timeout
        self._cache = TTLCache(ttl_seconds)

    def get_rates(self) -> dict:
        cached = self._cache.get("daily")
        if cached is not None:
            return cached
        response = httpx.get(ECB_DAILY_URL, timeout=self.timeout, follow_redirects=True)
        response.raise_for_status()
        parsed = parse_ecb_xml(response.text)
        result = {
            **parsed,
            "source": self.source_name,
            "fetched_at": datetime.now(UTC).isoformat(),
            "confidence": 1.0,
            "note": "ECB reference rates are indicative daily fixings, not tradable quotes.",
        }
        self._cache.set("daily", result)
        return result
