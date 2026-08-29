"""Offline tests for the OpenFIGI ISIN -> ticker mapping provider."""

from __future__ import annotations

import httpx
import pytest

from portfolio_copilot.providers.openfigi import EXCHANGE_TO_YF_SUFFIX, OpenFIGIProvider

ENEL_ISIN = "IT0003128367"
ASML_ISIN = "NL0010273215"


def _response(url: str, status_code: int, body) -> httpx.Response:
    return httpx.Response(status_code, request=httpx.Request("POST", url), json=body)


def _hit_row(ticker="ENEL", exch_code="MI", name="ENEL SPA", figi="BBG000BWJKD8") -> dict:
    return {
        "figi": figi,
        "name": name,
        "ticker": ticker,
        "exchCode": exch_code,
        "securityType": "Common Stock",
        "marketSector": "Equity",
    }


def _make_fake_post(handler):
    """A drop-in for httpx.post recording every call and delegating to ``handler``."""
    calls: list[list[dict]] = []

    def fake_post(url, json, timeout, headers):
        assert headers["Content-Type"] == "application/json"
        calls.append(json)
        return handler(url, json)

    fake_post.calls = calls
    return fake_post


# --- happy path -----------------------------------------------------------------------


def test_map_isins_happy_path(monkeypatch):
    provider = OpenFIGIProvider()

    def handler(url, jobs):
        assert jobs == [{"idType": "ID_ISIN", "idValue": ENEL_ISIN, "exchCode": "MI"}]
        return _response(url, 200, [{"data": [_hit_row()]}])

    monkeypatch.setattr(httpx, "post", _make_fake_post(handler))

    result = provider.map_isins([ENEL_ISIN], exch_code="MI")

    assert result == {
        ENEL_ISIN: {
            "ticker": "ENEL",
            "exch_code": "MI",
            "name": "ENEL SPA",
            "security_type": "Common Stock",
            "market_sector": "Equity",
            "figi": "BBG000BWJKD8",
        }
    }
    assert ENEL_ISIN not in provider.errors


def test_map_isins_prefers_exchcode_match_over_first_row(monkeypatch):
    provider = OpenFIGIProvider()
    rows = [_hit_row(ticker="ENEL_US", exch_code="US"), _hit_row(ticker="ENEL", exch_code="MI")]

    def handler(url, jobs):
        return _response(url, 200, [{"data": rows}])

    monkeypatch.setattr(httpx, "post", _make_fake_post(handler))

    result = provider.map_isins([ENEL_ISIN], exch_code="MI")

    assert result[ENEL_ISIN]["ticker"] == "ENEL"
    assert result[ENEL_ISIN]["exch_code"] == "MI"


def test_map_isins_no_matching_exchange_is_a_miss_not_a_fabricated_ticker(monkeypatch):
    """findings 17/19: OpenFIGI has a hit for the ISIN, but on a DIFFERENT exchange than
    the one requested -- must be a miss, never a silently wrong-exchange ticker at full
    confidence."""
    provider = OpenFIGIProvider()
    rows = [_hit_row(ticker="ASML_US_ADR", exch_code="US")]

    def handler(url, jobs):
        return _response(url, 200, [{"data": rows}])

    monkeypatch.setattr(httpx, "post", _make_fake_post(handler))

    result = provider.map_isins([ASML_ISIN], exch_code="MI")

    assert result[ASML_ISIN] is None
    assert "MI" in provider.errors[ASML_ISIN]


def test_yf_ticker_for_no_matching_exchange_returns_none_not_fabricated(monkeypatch):
    provider = OpenFIGIProvider()

    def handler(url, jobs):
        return _response(url, 200, [{"data": [_hit_row(ticker="ASML_US_ADR", exch_code="US")]}])

    monkeypatch.setattr(httpx, "post", _make_fake_post(handler))

    assert provider.yf_ticker_for(ASML_ISIN, exch_code="MI") is None
    assert provider.provenance_for(ASML_ISIN, exch_code="MI")["confidence"] == 0.0


# --- chunking ---------------------------------------------------------------------------


def test_map_isins_chunks_at_max_jobs_per_request(monkeypatch):
    provider = OpenFIGIProvider(max_jobs_per_request=10, min_interval_s=0.0)
    isins = [f"IT000000000{i:02d}" for i in range(23)]

    def handler(url, jobs):
        return _response(url, 200, [{"data": [_hit_row(ticker=j["idValue"])]} for j in jobs])

    fake_post = _make_fake_post(handler)
    monkeypatch.setattr(httpx, "post", fake_post)

    result = provider.map_isins(isins)

    assert len(fake_post.calls) == 3
    assert [len(c) for c in fake_post.calls] == [10, 10, 3]
    assert all(result[isin] is not None for isin in isins)


def test_map_isins_deduplicates_repeated_isins_in_one_call(monkeypatch):
    provider = OpenFIGIProvider(min_interval_s=0.0)

    def handler(url, jobs):
        assert len(jobs) == 1  # the duplicate must not turn into a second job
        return _response(url, 200, [{"data": [_hit_row()]}])

    fake_post = _make_fake_post(handler)
    monkeypatch.setattr(httpx, "post", fake_post)

    result = provider.map_isins([ENEL_ISIN, ENEL_ISIN])

    assert len(fake_post.calls) == 1
    assert result[ENEL_ISIN]["ticker"] == "ENEL"


# --- rate limiting ------------------------------------------------------------------------


def test_map_isins_spaces_requests_by_min_interval(monkeypatch):
    now = [0.0]
    sleeps: list[float] = []
    provider = OpenFIGIProvider(
        max_jobs_per_request=1,
        min_interval_s=2.5,
        clock=lambda: now[0],
        sleeper=sleeps.append,
    )
    isins = [ENEL_ISIN, ASML_ISIN]

    def handler(url, jobs):
        return _response(url, 200, [{"data": [_hit_row(ticker=jobs[0]["idValue"])]}])

    monkeypatch.setattr(httpx, "post", _make_fake_post(handler))

    provider.map_isins(isins)

    # first request never waits; the second must be spaced by the full min_interval_s
    assert sleeps == [pytest.approx(2.5)]


def test_map_isins_does_not_sleep_when_enough_time_has_passed(monkeypatch):
    now = [0.0]
    sleeps: list[float] = []
    provider = OpenFIGIProvider(
        max_jobs_per_request=1,
        min_interval_s=2.5,
        clock=lambda: now[0],
        sleeper=sleeps.append,
    )

    def handler(url, jobs):
        return _response(url, 200, [{"data": [_hit_row(ticker=jobs[0]["idValue"])]}])

    monkeypatch.setattr(httpx, "post", _make_fake_post(handler))

    provider.map_isins([ENEL_ISIN])
    now[0] = 100.0  # plenty of real time passes between the two calls
    provider.map_isins([ASML_ISIN])

    assert sleeps == []


# --- misses -------------------------------------------------------------------------------


def test_map_isins_miss_returns_none_with_reason_recorded(monkeypatch):
    provider = OpenFIGIProvider()

    def handler(url, jobs):
        return _response(url, 200, [{"warning": "No identifier found."}])

    monkeypatch.setattr(httpx, "post", _make_fake_post(handler))

    result = provider.map_isins(["XX0000000000"])

    assert result == {"XX0000000000": None}
    assert provider.errors["XX0000000000"] == "No identifier found."


def test_map_isins_error_item_returns_none_with_reason_recorded(monkeypatch):
    provider = OpenFIGIProvider()

    def handler(url, jobs):
        return _response(url, 200, [{"error": "Invalid idValue format."}])

    monkeypatch.setattr(httpx, "post", _make_fake_post(handler))

    result = provider.map_isins(["BAD-ISIN"])

    assert result == {"BAD-ISIN": None}
    assert provider.errors["BAD-ISIN"] == "Invalid idValue format."


# --- HTTP errors --------------------------------------------------------------------------


def test_map_isins_raises_on_http_429(monkeypatch):
    provider = OpenFIGIProvider()

    def handler(url, jobs):
        return _response(url, 429, {"error": "Too Many Requests"})

    monkeypatch.setattr(httpx, "post", _make_fake_post(handler))

    with pytest.raises(httpx.HTTPStatusError):
        provider.map_isins([ENEL_ISIN])


# --- caching --------------------------------------------------------------------------------


def test_map_isins_cache_hit_skips_second_request(monkeypatch):
    provider = OpenFIGIProvider()

    def handler(url, jobs):
        return _response(url, 200, [{"data": [_hit_row()]}])

    fake_post = _make_fake_post(handler)
    monkeypatch.setattr(httpx, "post", fake_post)

    first = provider.map_isins([ENEL_ISIN], exch_code="MI")
    second = provider.map_isins([ENEL_ISIN], exch_code="MI")

    assert len(fake_post.calls) == 1
    assert first == second


def test_map_isins_cache_is_scoped_by_exch_code(monkeypatch):
    provider = OpenFIGIProvider(min_interval_s=0.0)

    def handler(url, jobs):
        return _response(url, 200, [{"data": [_hit_row(exch_code=jobs[0].get("exchCode"))]}])

    fake_post = _make_fake_post(handler)
    monkeypatch.setattr(httpx, "post", fake_post)

    provider.map_isins([ENEL_ISIN], exch_code="MI")
    provider.map_isins([ENEL_ISIN], exch_code="US")

    assert len(fake_post.calls) == 2  # different exchCode -> not served from cache


def test_map_isins_expired_cache_entry_refetches(monkeypatch):
    now = [0.0]
    provider = OpenFIGIProvider(ttl_seconds=10.0, min_interval_s=0.0, clock=lambda: now[0])

    def handler(url, jobs):
        return _response(url, 200, [{"data": [_hit_row()]}])

    fake_post = _make_fake_post(handler)
    monkeypatch.setattr(httpx, "post", fake_post)

    provider.map_isins([ENEL_ISIN])
    now[0] = 11.0
    provider.map_isins([ENEL_ISIN])

    assert len(fake_post.calls) == 2


# --- provenance -----------------------------------------------------------------------------


def test_provenance_for_hit(monkeypatch):
    provider = OpenFIGIProvider()

    def handler(url, jobs):
        return _response(url, 200, [{"data": [_hit_row()]}])

    monkeypatch.setattr(httpx, "post", _make_fake_post(handler))
    provider.map_isins([ENEL_ISIN], exch_code="MI")

    prov = provider.provenance_for(ENEL_ISIN, exch_code="MI")

    assert prov["source"] == "openfigi"
    assert prov["tier"] == "A"
    assert prov["confidence"] == 1.0
    assert prov["as_of"]


def test_provenance_for_miss_without_lookup():
    provider = OpenFIGIProvider()

    prov = provider.provenance_for("NEVER0000000")

    assert prov["confidence"] == 0.0
    assert prov["source"] == "openfigi"
    assert prov["tier"] == "A"


def test_provenance_for_after_a_miss_response(monkeypatch):
    provider = OpenFIGIProvider()

    def handler(url, jobs):
        return _response(url, 200, [{"warning": "No identifier found."}])

    monkeypatch.setattr(httpx, "post", _make_fake_post(handler))
    provider.map_isins(["XX0000000000"])

    assert provider.provenance_for("XX0000000000")["confidence"] == 0.0


def test_provenance_for_without_exch_code_resolves_the_last_successful_lookup(monkeypatch):
    """finding 18: a caller that mapped with an exch_code but later asks provenance_for
    without one must not under-report a genuine cached hit as confidence 0.0."""
    provider = OpenFIGIProvider()

    def handler(url, jobs):
        return _response(url, 200, [{"data": [_hit_row()]}])

    monkeypatch.setattr(httpx, "post", _make_fake_post(handler))
    provider.map_isins([ENEL_ISIN], exch_code="MI")

    prov = provider.provenance_for(ENEL_ISIN)  # no exch_code this time

    assert prov["confidence"] == 1.0


# --- yf_ticker_for --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exch_code", "suffix"),
    [
        ("MI", ".MI"),
        ("US", ""),
        ("UN", ""),
        ("UW", ""),
        ("UA", ""),
        ("GY", ".DE"),
        ("GR", ".DE"),
        ("LN", ".L"),
        ("NA", ".AS"),
        ("FP", ".PA"),
    ],
)
def test_yf_ticker_for_suffix_table(monkeypatch, exch_code, suffix):
    provider = OpenFIGIProvider()

    def handler(url, jobs):
        return _response(url, 200, [{"data": [_hit_row(ticker="ABC", exch_code=exch_code)]}])

    monkeypatch.setattr(httpx, "post", _make_fake_post(handler))

    assert provider.yf_ticker_for(ENEL_ISIN, exch_code=exch_code) == f"ABC{suffix}"


def test_yf_ticker_for_unknown_exchange_returns_none_without_a_request(monkeypatch):
    provider = OpenFIGIProvider()
    fake_post = _make_fake_post(lambda url, jobs: pytest.fail("should not call the API"))
    monkeypatch.setattr(httpx, "post", fake_post)

    assert provider.yf_ticker_for(ENEL_ISIN, exch_code="ZZ") is None
    assert fake_post.calls == []


def test_yf_ticker_for_miss_returns_none(monkeypatch):
    provider = OpenFIGIProvider()

    def handler(url, jobs):
        return _response(url, 200, [{"warning": "No identifier found."}])

    monkeypatch.setattr(httpx, "post", _make_fake_post(handler))

    assert provider.yf_ticker_for("XX0000000000", exch_code="MI") is None


def test_exchange_suffix_table_is_a_plain_dict_covering_the_documented_exchanges():
    for code in ("US", "UN", "UW", "UA", "MI", "GY", "GR", "LN", "NA", "FP"):
        assert code in EXCHANGE_TO_YF_SUFFIX


# --- malformed responses must degrade, never crash ------------------------------------------


def test_map_isins_response_length_mismatch_degrades_instead_of_crashing(monkeypatch):
    """finding 20: a response body shorter than the request (upstream truncation, a proxy
    collapsing errors) must not raise -- it must degrade every ISIN in that chunk to a
    recorded miss."""
    provider = OpenFIGIProvider(min_interval_s=0.0)

    def handler(url, jobs):
        return _response(url, 200, [{"data": [_hit_row()]}])  # only 1 item for 2 jobs

    monkeypatch.setattr(httpx, "post", _make_fake_post(handler))

    result = provider.map_isins(["ISIN_A", "ISIN_B"])

    assert result == {"ISIN_A": None, "ISIN_B": None}
    assert "ISIN_A" in provider.errors
    assert "ISIN_B" in provider.errors


# --- ISIN normalization -----------------------------------------------------------------------


def test_map_isins_normalizes_whitespace_and_case_before_dedup_and_cache(monkeypatch):
    """finding 21: a broker-export ISIN cell with incidental whitespace/case must not
    bypass dedup/cache and waste a request against the anonymous rate limit."""
    provider = OpenFIGIProvider(min_interval_s=0.0)

    def handler(url, jobs):
        return _response(url, 200, [{"data": [_hit_row()]}])

    fake_post = _make_fake_post(handler)
    monkeypatch.setattr(httpx, "post", fake_post)

    provider.map_isins([ENEL_ISIN], exch_code="MI")
    result = provider.map_isins([f" {ENEL_ISIN.lower()} "], exch_code="MI")

    assert len(fake_post.calls) == 1  # second call served entirely from cache
    assert result[ENEL_ISIN]["ticker"] == "ENEL"


# --- constructor validation -----------------------------------------------------------------


def test_rejects_non_positive_max_jobs_per_request():
    with pytest.raises(ValueError):
        OpenFIGIProvider(max_jobs_per_request=0)


def test_rejects_negative_min_interval():
    with pytest.raises(ValueError):
        OpenFIGIProvider(min_interval_s=-1.0)
