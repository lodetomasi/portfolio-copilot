"""Offline tests for the macro engine: Eurostat (HICP, unemployment) + ECB deposit rate."""

import json
from pathlib import Path

import httpx
import pytest

from portfolio_copilot.providers.ecb_rates import ECB_DFR_URL, ECBRatesProvider, parse_ecb_csv
from portfolio_copilot.providers.eurostat import EurostatProvider, parse_jsonstat
from portfolio_copilot.providers.macro import macro_snapshot

FIXTURES = Path(__file__).parent / "fixtures"
HICP_PAYLOAD = json.loads((FIXTURES / "eurostat_hicp_sample.json").read_text())
UNE_PAYLOAD = json.loads((FIXTURES / "eurostat_une_sample.json").read_text())
DFR_CSV = (FIXTURES / "ecb_dfr_sample.csv").read_text()


def _response(url: str, **kwargs) -> httpx.Response:
    return httpx.Response(200, request=httpx.Request("GET", url), **kwargs)


# ---------------------------------------------------------------------------
# parse_jsonstat
# ---------------------------------------------------------------------------


def test_parse_jsonstat_hicp_sorted_with_nulls_for_missing_and_explicit_null():
    series = parse_jsonstat(HICP_PAYLOAD)
    periods = [p for p, _ in series]
    assert periods == sorted(periods)  # ascending
    assert periods[0] == "2025-07" and periods[-1] == "2026-07"
    by_period = dict(series)
    assert by_period["2025-07"] == 2.2
    assert by_period["2026-06"] == 2.3
    assert by_period["2026-01"] is None  # explicit null in the fixture's sparse value map
    assert by_period["2026-07"] is None  # entirely absent from the sparse value map


def test_parse_jsonstat_unemployment_series_fully_populated():
    series = parse_jsonstat(UNE_PAYLOAD)
    assert len(series) == 13
    assert dict(series)["2026-07"] == 6.1
    assert all(value is not None for _, value in series)


def test_parse_jsonstat_rejects_payload_without_time_dimension():
    with pytest.raises(ValueError):
        parse_jsonstat({"dimension": {"geo": {"category": {"index": {"EA20": 0}}}}, "value": {}})


def test_parse_jsonstat_rejects_time_dimension_without_index():
    with pytest.raises(ValueError):
        parse_jsonstat({"dimension": {"time": {"category": {}}}, "id": ["time"], "value": {}})


# ---------------------------------------------------------------------------
# EurostatProvider
# ---------------------------------------------------------------------------


def test_hicp_annual_rate_returns_latest_non_null_and_caches(monkeypatch):
    calls = []

    def fake_get(url, params, timeout, follow_redirects):
        calls.append((url, dict(params), timeout))
        return _response(url, json=HICP_PAYLOAD)

    monkeypatch.setattr(httpx, "get", fake_get)
    provider = EurostatProvider(timeout=4.0)
    first = provider.hicp_annual_rate()
    assert first == {
        "value": 2.3,
        "as_of": "2026-06",
        "source": "eurostat",
        "tier": "A",
        "confidence": 1.0,
        "geo": "EA20",
        "dataset": "prc_hicp_manr",
    }
    second = provider.hicp_annual_rate()
    assert second is first  # cached, no second HTTP call
    assert len(calls) == 1
    url, params, timeout = calls[0]
    assert url == "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/prc_hicp_manr"
    assert params == {
        "format": "JSON",
        "lang": "EN",
        "geo": "EA20",
        "lastTimePeriod": 13,
        "coicop": "CP00",
        "unit": "RCH_A",
    }
    assert timeout == 4.0


def test_unemployment_rate_uses_its_own_dataset_and_cache_key(monkeypatch):
    calls = []

    def fake_get(url, params, timeout, follow_redirects):
        calls.append(url)
        return _response(url, json=UNE_PAYLOAD)

    monkeypatch.setattr(httpx, "get", fake_get)
    provider = EurostatProvider()
    out = provider.unemployment_rate(geo="EA20")
    assert out["value"] == 6.1 and out["as_of"] == "2026-07"
    assert out["source"] == "eurostat" and out["tier"] == "A"
    assert calls == ["https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/une_rt_m"]

    # A different dataset (hicp) does not share the unemployment cache entry.
    def fake_get_hicp(url, params, timeout, follow_redirects):
        calls.append(url)
        return _response(url, json=HICP_PAYLOAD)

    monkeypatch.setattr(httpx, "get", fake_get_hicp)
    provider.hicp_annual_rate(geo="EA20")
    assert len(calls) == 2


def test_eurostat_degrades_on_http_error_without_raising(monkeypatch):
    def fake_get(url, params, timeout, follow_redirects):
        return httpx.Response(500, request=httpx.Request("GET", url), text="server error")

    monkeypatch.setattr(httpx, "get", fake_get)
    out = EurostatProvider().hicp_annual_rate()
    assert out["value"] is None and out["as_of"] is None
    assert out["source"] == "eurostat" and out["tier"] == "A" and out["confidence"] == 0.0
    assert "error" in out


def test_eurostat_degrades_on_malformed_payload_without_raising(monkeypatch):
    def fake_get(url, params, timeout, follow_redirects):
        return _response(url, json={"not": "a jsonstat payload"})

    monkeypatch.setattr(httpx, "get", fake_get)
    out = EurostatProvider().unemployment_rate()
    assert out["value"] is None and out["confidence"] == 0.0
    assert "error" in out


def test_eurostat_degrades_when_every_observation_is_null(monkeypatch):
    all_null_payload = {**HICP_PAYLOAD, "value": {}}

    def fake_get(url, params, timeout, follow_redirects):
        return _response(url, json=all_null_payload)

    monkeypatch.setattr(httpx, "get", fake_get)
    out = EurostatProvider().hicp_annual_rate()
    assert out["value"] is None and out["as_of"] is None and out["confidence"] == 0.0
    assert "not yet published" in out["note"]


# ---------------------------------------------------------------------------
# ECB rates
# ---------------------------------------------------------------------------


def test_parse_ecb_csv_reads_latest_observation():
    as_of, value = parse_ecb_csv(DFR_CSV)
    assert as_of == "2026-08-27"
    assert value == 3.25


def test_parse_ecb_csv_rejects_csv_with_no_observations():
    header_only = "TIME_PERIOD,OBS_VALUE\n"
    with pytest.raises(ValueError):
        parse_ecb_csv(header_only)


def test_parse_ecb_csv_skips_rows_with_empty_obs_value():
    text = "TIME_PERIOD,OBS_VALUE\n2026-07-01,\n2026-08-27,3.25\n"
    assert parse_ecb_csv(text) == ("2026-08-27", 3.25)


def test_deposit_facility_rate_caches_and_uses_timeout(monkeypatch):
    calls = []

    def fake_get(url, timeout, follow_redirects):
        calls.append((url, timeout))
        return _response(url, text=DFR_CSV)

    monkeypatch.setattr(httpx, "get", fake_get)
    provider = ECBRatesProvider(timeout=5.0)
    first = provider.deposit_facility_rate()
    second = provider.deposit_facility_rate()
    assert first == {
        "value": 3.25,
        "as_of": "2026-08-27",
        "source": "ecb_data_portal",
        "tier": "A",
        "confidence": 1.0,
        "note": "ECB deposit facility rate (DFR), floor of the euro-area rate corridor.",
    }
    assert second is first
    assert calls == [(ECB_DFR_URL, 5.0)]


def test_deposit_facility_rate_degrades_on_error_without_raising(monkeypatch):
    def fake_get(url, timeout, follow_redirects):
        return httpx.Response(503, request=httpx.Request("GET", url), text="unavailable")

    monkeypatch.setattr(httpx, "get", fake_get)
    out = ECBRatesProvider().deposit_facility_rate()
    assert out["value"] is None and out["confidence"] == 0.0
    assert out["source"] == "ecb_data_portal" and out["tier"] == "A"
    assert "error" in out


# ---------------------------------------------------------------------------
# macro_snapshot: regime branches and missing-series behaviour
# ---------------------------------------------------------------------------


class _FakeEurostat:
    def __init__(self, hicp_value, unemployment_value=6.0, as_of="2026-06"):
        self._hicp_value = hicp_value
        self._unemployment_value = unemployment_value
        self._as_of = as_of

    def hicp_annual_rate(self, geo="EA20"):
        if self._hicp_value is None:
            return {
                "value": None,
                "as_of": None,
                "source": "eurostat",
                "tier": "A",
                "confidence": 0.0,
            }
        return {
            "value": self._hicp_value,
            "as_of": self._as_of,
            "source": "eurostat",
            "tier": "A",
            "confidence": 1.0,
        }

    def unemployment_rate(self, geo="EA20"):
        return {
            "value": self._unemployment_value,
            "as_of": self._as_of,
            "source": "eurostat",
            "tier": "A",
            "confidence": 1.0,
        }


class _FakeECB:
    def __init__(self, value, as_of="2026-08-27"):
        self._value = value
        self._as_of = as_of

    def deposit_facility_rate(self):
        if self._value is None:
            return {
                "value": None,
                "as_of": None,
                "source": "ecb_data_portal",
                "tier": "A",
                "confidence": 0.0,
            }
        return {
            "value": self._value,
            "as_of": self._as_of,
            "source": "ecb_data_portal",
            "tier": "A",
            "confidence": 1.0,
        }


@pytest.mark.parametrize(
    "dfr_value,hicp_value,expected_regime",
    [
        (4.0, 2.0, "restrictive"),  # spread = 2.0 > 1
        (3.0, 2.0, "neutral"),  # spread = 1.0, boundary is inclusive of neutral
        (2.5, 2.0, "neutral"),  # spread = 0.5, well inside the band
        (2.0, 3.0, "neutral"),  # spread = -1.0, boundary is inclusive of neutral
        (1.0, 3.0, "accommodative"),  # spread = -2.0 < -1
    ],
)
def test_macro_snapshot_regime_branches(dfr_value, hicp_value, expected_regime):
    out = macro_snapshot(_FakeEurostat(hicp_value), _FakeECB(dfr_value))
    assert out["regime"] == expected_regime
    assert f"{dfr_value:.2f}" in out["regime_formula"]
    assert f"{hicp_value:.2f}" in out["regime_formula"]


def test_macro_snapshot_shape_and_slimmed_fields():
    out = macro_snapshot(_FakeEurostat(hicp_value=2.0, unemployment_value=6.5), _FakeECB(3.0))
    assert set(out) == {"hicp", "unemployment", "dfr", "regime", "regime_formula"}
    for key in ("hicp", "unemployment", "dfr"):
        assert set(out[key]) == {"value", "as_of", "source", "tier", "confidence"}
    assert out["unemployment"]["value"] == 6.5
    assert out["unemployment"]["source"] == "eurostat"
    assert out["dfr"]["value"] == 3.0 and out["dfr"]["source"] == "ecb_data_portal"


def test_macro_snapshot_missing_hicp_is_unknown_never_guessed():
    out = macro_snapshot(_FakeEurostat(hicp_value=None), _FakeECB(3.0))
    assert out["regime"] == "unknown"
    assert out["hicp"]["value"] is None
    assert "never guessed" in out["regime_formula"]


def test_macro_snapshot_missing_dfr_is_unknown_never_guessed():
    out = macro_snapshot(_FakeEurostat(hicp_value=2.0), _FakeECB(None))
    assert out["regime"] == "unknown"
    assert out["dfr"]["value"] is None
    assert "never guessed" in out["regime_formula"]


def test_macro_snapshot_end_to_end_with_real_providers(monkeypatch):
    """Wire the real Eurostat + ECB providers through macro_snapshot with all three fixtures."""

    def fake_get(url, timeout, follow_redirects=True, params=None):
        if "eurostat" in url and "prc_hicp_manr" in url:
            return _response(url, json=HICP_PAYLOAD)
        if "eurostat" in url and "une_rt_m" in url:
            return _response(url, json=UNE_PAYLOAD)
        if "data-api.ecb.europa.eu" in url:
            return _response(url, text=DFR_CSV)
        raise AssertionError(f"unexpected URL in test: {url}")

    monkeypatch.setattr(httpx, "get", fake_get)
    out = macro_snapshot(EurostatProvider(), ECBRatesProvider())
    assert out["hicp"] == {
        "value": 2.3, "as_of": "2026-06", "source": "eurostat", "tier": "A", "confidence": 1.0,
    }
    assert out["unemployment"] == {
        "value": 6.1,
        "as_of": "2026-07",
        "source": "eurostat",
        "tier": "A",
        "confidence": 1.0,
    }
    assert out["dfr"] == {
        "value": 3.25,
        "as_of": "2026-08-27",
        "source": "ecb_data_portal",
        "tier": "A",
        "confidence": 1.0,
    }
    assert out["regime"] == "neutral"  # spread = 3.25 - 2.3 = 0.95
    assert "3.25" in out["regime_formula"] and "2.30" in out["regime_formula"]


# ---------------------------------------------------------------------------
# finding 30: NaN/Infinity from either provider must degrade to 'unknown', never
# a confidently-labeled regime
# ---------------------------------------------------------------------------


def test_macro_snapshot_nan_hicp_is_unknown_never_a_confident_regime():
    out = macro_snapshot(_FakeEurostat(hicp_value=float("nan")), _FakeECB(3.25))
    assert out["regime"] == "unknown"
    assert "never guessed" in out["regime_formula"]


def test_macro_snapshot_infinite_dfr_is_unknown_never_a_confident_regime():
    out = macro_snapshot(_FakeEurostat(hicp_value=2.0), _FakeECB(float("inf")))
    assert out["regime"] == "unknown"


# ---------------------------------------------------------------------------
# finding 34: macro_snapshot must surface confidence for every sub-series
# ---------------------------------------------------------------------------


def test_macro_snapshot_shape_includes_confidence_for_every_series():
    out = macro_snapshot(_FakeEurostat(hicp_value=2.0, unemployment_value=6.5), _FakeECB(3.0))
    for key in ("hicp", "unemployment", "dfr"):
        assert "confidence" in out[key]
    assert out["hicp"]["confidence"] == 1.0
    assert out["dfr"]["confidence"] == 1.0


# ---------------------------------------------------------------------------
# finding 31: parse_jsonstat must not silently pick category index 0 when a
# non-time dimension unexpectedly carries more than one category
# ---------------------------------------------------------------------------


def test_parse_jsonstat_rejects_multi_category_non_time_dimension():
    payload = {
        "id": ["unit", "geo", "time"],
        "size": [2, 1, 2],
        "dimension": {
            "unit": {"category": {"index": {"PC_ACT": 0, "RCH_A": 1}}},
            "geo": {"category": {"index": {"EA20": 0}}},
            "time": {"category": {"index": {"2026-05": 0, "2026-06": 1}}},
        },
        "value": {"0": 6.0, "1": 6.1, "2": 2.2, "3": 2.3},
    }
    with pytest.raises(ValueError, match="unit"):
        parse_jsonstat(payload)


# ---------------------------------------------------------------------------
# finding 33: EurostatProvider._latest must never raise on a structurally
# malformed payload -- it always degrades to confidence=0.0
# ---------------------------------------------------------------------------


def test_eurostat_latest_degrades_on_non_dict_payload(monkeypatch):
    def fake_get(url, params=None, timeout=None, follow_redirects=True):
        return _response(url, json=["unexpected", "list", "shape"])

    monkeypatch.setattr(httpx, "get", fake_get)
    out = EurostatProvider().hicp_annual_rate()
    assert out["value"] is None
    assert out["confidence"] == 0.0


def test_eurostat_latest_degrades_on_non_numeric_value_entry(monkeypatch):
    payload = dict(HICP_PAYLOAD)
    payload["value"] = dict(payload["value"])
    payload["value"]["0"] = ["not", "a", "number"]

    def fake_get(url, params=None, timeout=None, follow_redirects=True):
        return _response(url, json=payload)

    monkeypatch.setattr(httpx, "get", fake_get)
    out = EurostatProvider().hicp_annual_rate()
    assert out["value"] is None
    assert out["confidence"] == 0.0


def test_eurostat_reports_empty_geo_dimension_distinctly(monkeypatch):
    """Live finding 2026-08-29: une_rt_m has no euro-area aggregate under EA20/EA19/EA — the
    response comes back with the geo dimension of size 0 and an empty value map. That must be
    reported as 'no observations for this geo' (a wrong geo code), not as 'not yet published'."""
    empty_geo_payload = {
        "id": ["freq", "s_adj", "age", "unit", "sex", "geo", "time"],
        "size": [1, 1, 1, 1, 1, 0, 3],
        "dimension": {
            "freq": {"category": {"index": {"M": 0}}},
            "s_adj": {"category": {"index": {"SA": 0}}},
            "age": {"category": {"index": {"TOTAL": 0}}},
            "unit": {"category": {"index": {"PC_ACT": 0}}},
            "sex": {"category": {"index": {"T": 0}}},
            "geo": {"category": {"index": {}}},
            "time": {"category": {"index": {"2026-05": 0, "2026-06": 1, "2026-07": 2}}},
        },
        "value": {},
    }

    def fake_get(url, params, timeout, follow_redirects):
        return _response(url, json=empty_geo_payload)

    monkeypatch.setattr(httpx, "get", fake_get)
    out = EurostatProvider().unemployment_rate(geo="EA20")
    assert out["value"] is None and out["confidence"] == 0.0
    assert "no observations for geo 'EA20'" in out["note"]
    assert "not yet published" not in out["note"]


def test_unemployment_default_geo_is_eu27_and_macro_uses_separate_geos():
    """Eurostat publishes the euro-area HICP under EA20 but the monthly unemployment aggregate
    only under EU27_2020 (verified live 2026-08-29): the two series need separate geo defaults."""
    calls = {}

    class FakeEurostat:
        def hicp_annual_rate(self, geo="EA20"):
            calls["hicp"] = geo
            return {"value": 2.0, "as_of": "2026-07", "source": "eurostat", "tier": "A",
                    "confidence": 1.0}

        def unemployment_rate(self, geo="EU27_2020"):
            calls["une"] = geo
            return {"value": 6.0, "as_of": "2026-07", "source": "eurostat", "tier": "A",
                    "confidence": 1.0}

    class FakeECB:
        def deposit_facility_rate(self):
            return {"value": 2.25, "as_of": "2026-08-28", "source": "ecb_data_portal",
                    "tier": "A", "confidence": 1.0}

    import inspect

    from portfolio_copilot.providers.macro import macro_snapshot

    assert inspect.signature(EurostatProvider.unemployment_rate).parameters["geo"].default == (
        "EU27_2020"
    )
    out = macro_snapshot(FakeEurostat(), FakeECB())
    assert calls == {"hicp": "EA20", "une": "EU27_2020"}
    assert out["unemployment"]["value"] == 6.0 and out["regime"] == "neutral"
