"""Eurostat JSON-stat 2.0 macro series (free, no key): euro-area HICP and unemployment.

Two monthly series feed the macro regime read: `prc_hicp_manr` (HICP annual rate of change)
and `une_rt_m` (unemployment rate). Both are requested pre-filtered to a single geo, so every
non-time dimension has exactly one category and the sparse JSON-stat `value` map ends up
keyed by the flat time index alone.
"""

from __future__ import annotations

from typing import Any

import httpx

from portfolio_copilot.providers.cache import TTLCache

EUROSTAT_URL = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/{dataset}"


def parse_jsonstat(payload: dict[str, Any]) -> list[tuple[str, float | None]]:
    """Flatten a JSON-stat 2.0 payload with one varying "time" dimension into (period, value).

    Sorted by period ascending. A period absent from the sparse `value` map, or holding an
    explicit `null`, comes back as `value=None` -- never guessed or interpolated.
    """
    dimension = payload.get("dimension") or {}
    if "time" not in dimension:
        raise ValueError("JSON-stat payload has no 'time' dimension")
    ids: list[str] = payload.get("id") or list(dimension.keys())
    if "time" not in ids:
        raise ValueError("JSON-stat 'id' list does not include 'time'")
    sizes: list[int] = payload.get("size") or [
        len((dimension.get(d) or {}).get("category", {}).get("index") or {"_": 0}) for d in ids
    ]
    time_pos = ids.index("time")
    time_index: dict[str, int] = (dimension["time"].get("category") or {}).get("index") or {}
    if not time_index:
        raise ValueError("JSON-stat 'time' dimension has no category index")

    fixed_idx: list[int] = []
    for pos, dim_id in enumerate(ids):
        if pos == time_pos:
            fixed_idx.append(0)  # placeholder, overwritten per period below
            continue
        cat_index = (dimension.get(dim_id) or {}).get("category", {}).get("index")
        if cat_index and len(cat_index) != 1:
            # The caller's query filters every non-time dimension down to a single
            # category (see this module's docstring); if the API ever echoes back more
            # than one, picking "whichever is first in dict order" would silently return
            # a value from the WRONG category with full apparent confidence -- refuse
            # instead (caught by _latest and degraded to confidence=0.0).
            raise ValueError(
                f"JSON-stat dimension {dim_id!r} has {len(cat_index)} categories, "
                "expected exactly 1 (the query should have pre-filtered it)"
            )
        fixed_idx.append(next(iter(cat_index.values())) if cat_index else 0)

    values = payload.get("value") or {}

    def value_at(flat_index: int) -> float | None:
        if isinstance(values, dict):
            raw = values.get(str(flat_index))
        else:
            raw = values[flat_index] if flat_index < len(values) else None
        return None if raw is None else float(raw)

    out: list[tuple[str, float | None]] = []
    for period, t_idx in time_index.items():
        combo = list(fixed_idx)
        combo[time_pos] = t_idx
        flat = 0
        for size, idx in zip(sizes, combo, strict=True):
            flat = flat * size + idx
        out.append((period, value_at(flat)))
    out.sort(key=lambda pair: pair[0])
    return out


def _geo_dimension_is_empty(payload: dict[str, Any]) -> bool:
    """True when the response carries a geo dimension with zero categories (no data for that
    geo code). Distinct from 'all observations null', which means not yet published."""
    ids = payload.get("id") or []
    sizes = payload.get("size") or []
    if "geo" in ids and len(sizes) == len(ids):
        return sizes[ids.index("geo")] == 0
    geo = (payload.get("dimension") or {}).get("geo") or {}
    return "geo" in ids and not (geo.get("category") or {}).get("index")


class EurostatProvider:
    source_name = "eurostat"

    def __init__(self, timeout: float = 10.0, ttl_seconds: float = 24 * 3600) -> None:
        self.timeout = timeout
        self._cache = TTLCache(ttl_seconds)

    def _latest(self, dataset: str, geo: str, extra: dict[str, str]) -> dict[str, Any]:
        """Latest non-null observation for one dataset/geo, or a degraded dict if unavailable.

        Never raises: a network failure or a malformed payload degrades `value` to None with
        `confidence=0.0` instead of bubbling up, per the "never invent missing data" rule.
        Only successful reads are cached, so a transient failure is retried next call.
        """
        query = {"format": "JSON", "lang": "EN", "geo": geo, "lastTimePeriod": 13, **extra}
        key = dataset + "|" + "&".join(f"{k}={v}" for k, v in sorted(query.items()))
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            response = httpx.get(
                EUROSTAT_URL.format(dataset=dataset),
                params=query,
                timeout=self.timeout,
                follow_redirects=True,
            )
            response.raise_for_status()
            payload = response.json()
            series = parse_jsonstat(payload)
        except (
            httpx.HTTPError,
            ValueError,
            TypeError,
            AttributeError,
            KeyError,
            IndexError,
        ) as exc:
            return {
                "value": None,
                "as_of": None,
                "source": self.source_name,
                "tier": "A",
                "confidence": 0.0,
                "geo": geo,
                "dataset": dataset,
                "error": str(exc),
            }
        result: dict[str, Any] = {
            "value": None,
            "as_of": None,
            "source": self.source_name,
            "tier": "A",
            "confidence": 0.0,
            "geo": geo,
            "dataset": dataset,
            "note": "series returned but every observation is null (not yet published)",
        }
        if _geo_dimension_is_empty(payload):
            result["note"] = (
                f"no observations for geo '{geo}' in {dataset}: Eurostat returned an empty geo "
                "dimension (wrong or unpublished geo code; e.g. une_rt_m has no EA20 aggregate, "
                "use EU27_2020 or a country code)"
            )
            self._cache.set(key, result)
            return result
        for period, value in reversed(series):
            if value is not None:
                result = {
                    "value": value,
                    "as_of": period,
                    "source": self.source_name,
                    "tier": "A",
                    "confidence": 1.0,
                    "geo": geo,
                    "dataset": dataset,
                }
                break
        self._cache.set(key, result)
        return result

    def hicp_annual_rate(self, geo: str = "EA20") -> dict[str, Any]:
        """Euro-area (or country) HICP annual rate of change, latest published month."""
        return self._latest("prc_hicp_manr", geo, {"coicop": "CP00", "unit": "RCH_A"})

    def unemployment_rate(self, geo: str = "EU27_2020") -> dict[str, Any]:
        """Seasonally adjusted total unemployment rate, latest published month.

        Default geo is EU27_2020: Eurostat's une_rt_m has no euro-area (EA20) aggregate, the
        request returns an empty geo dimension (verified live 2026-08-29)."""
        return self._latest(
            "une_rt_m", geo, {"s_adj": "SA", "age": "TOTAL", "sex": "T", "unit": "PC_ACT"}
        )
