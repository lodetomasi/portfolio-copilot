"""Offline, deterministic tests for the eToro Public API v2 client.

Every HTTP call goes through ``httpx.MockTransport`` -- no network, no real credentials.
Credential-loading tests use ``tmp_path``/``monkeypatch.setenv`` with FAKE values only and
never touch ``data/private``.
"""

from __future__ import annotations

import httpx
import pytest

from portfolio_copilot.brokers.etoro import (
    PATH_PNL_DEMO,
    PATH_PNL_REAL,
    Credentials,
    EToroClient,
    EToroError,
    InsufficientFunds,
    KycRequired,
    MarketClosed,
    NotAvailable,
    NotConfigured,
    RateLimited,
    Unavailable,
    load_credentials,
)

FAKE_API_KEY = "fake-app-key-zzz111"
FAKE_USER_KEY = '{"fake":"user-key-yyy222"}'


def creds() -> Credentials:
    return Credentials(api_key=FAKE_API_KEY, user_key=FAKE_USER_KEY)


class FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class RecordingSleeper:
    def __init__(self, clock: FakeClock | None = None) -> None:
        self.calls: list[float] = []
        self._clock = clock

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)
        if self._clock is not None:
            self._clock.advance(seconds)


_NO_CREDENTIALS_OVERRIDE = object()


def make_client(
    handler,
    mode: str = "demo",
    credentials=_NO_CREDENTIALS_OVERRIDE,
    clock=None,
    sleep=None,
) -> EToroClient:
    transport = httpx.MockTransport(handler)
    kwargs = {}
    if clock is not None:
        kwargs["clock"] = clock
    if sleep is not None:
        kwargs["sleep"] = sleep
    resolved = creds() if credentials is _NO_CREDENTIALS_OVERRIDE else credentials
    return EToroClient(
        resolved,
        mode=mode,
        transport=transport,
        **kwargs,
    )


def never_called_handler(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"unexpected HTTP call: {request.method} {request.url}")


# ---------------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------------


def test_load_credentials_env_vars_take_precedence(tmp_path):
    env_file = tmp_path / "etoro.env"
    env_file.write_text("ETORO_API_KEY=from-file-key\nETORO_USER_KEY=from-file-user\n")
    env = {"ETORO_API_KEY": "from-env-key", "ETORO_USER_KEY": "from-env-user"}
    result = load_credentials(env=env, env_file=env_file)
    assert result == Credentials(api_key="from-env-key", user_key="from-env-user")


def test_load_credentials_falls_back_to_file(tmp_path):
    env_file = tmp_path / "etoro.env"
    env_file.write_text(
        "# comment\n\nETORO_API_KEY=file-key-123\nETORO_USER_KEY=file-user-456\n"
    )
    result = load_credentials(env={}, env_file=env_file)
    assert result == Credentials(api_key="file-key-123", user_key="file-user-456")


def test_load_credentials_returns_none_when_absent(tmp_path):
    missing_file = tmp_path / "does-not-exist.env"
    assert load_credentials(env={}, env_file=missing_file) is None
    assert load_credentials(env={}, env_file=None) is None


def test_load_credentials_returns_none_on_partial_pair(tmp_path):
    env_file = tmp_path / "etoro.env"
    env_file.write_text("ETORO_API_KEY=only-key\n")
    assert load_credentials(env={"ETORO_API_KEY": "only-env-key"}, env_file=env_file) is None


def test_credentials_repr_and_str_redact_both_keys():
    c = Credentials(api_key=FAKE_API_KEY, user_key=FAKE_USER_KEY)
    assert FAKE_API_KEY not in repr(c)
    assert FAKE_USER_KEY not in repr(c)
    assert FAKE_API_KEY not in str(c)
    assert FAKE_USER_KEY not in str(c)


# ---------------------------------------------------------------------------------
# Headers, request-id uniqueness, demo/real path selection
# ---------------------------------------------------------------------------------


def _pnl_body(**overrides):
    portfolio = {
        "positions": [],
        "unrealizedPnL": 0.0,
        "accountCurrencyId": 1,
        "credit": 1000.0,
        "orders": [],
        "stockOrders": [],
        "entryOrders": [],
        "exitOrders": [],
        "ordersForOpen": [],
        "ordersForClose": [],
        "ordersForCloseMultiple": [],
    }
    portfolio.update(overrides)
    return {"clientPortfolio": portfolio}


def test_headers_present_and_request_id_unique_per_call():
    seen_request_ids: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("x-api-key") == FAKE_API_KEY
        assert request.headers.get("x-user-key") == FAKE_USER_KEY
        assert request.headers.get("User-Agent") == "portfolio-copilot"
        req_id = request.headers.get("x-request-id")
        assert req_id
        seen_request_ids.append(req_id)
        return httpx.Response(200, json=_pnl_body())

    client = make_client(handler)
    client.account()
    client.account()
    assert len(seen_request_ids) == 2
    assert seen_request_ids[0] != seen_request_ids[1]


@pytest.mark.parametrize(
    "mode,expected_path", [("demo", PATH_PNL_DEMO), ("real", PATH_PNL_REAL)]
)
def test_demo_vs_real_path_selection(mode, expected_path):
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        return httpx.Response(200, json=_pnl_body())

    client = make_client(handler, mode=mode)
    client.account()
    assert seen_paths == [expected_path]


def test_not_configured_when_credentials_absent_never_calls_network():
    client = make_client(never_called_handler, credentials=None)
    with pytest.raises(NotConfigured):
        client.account()


# ---------------------------------------------------------------------------------
# Rate limiter (unit-level, deterministic via fake clock/sleep)
# ---------------------------------------------------------------------------------


def test_rate_limiter_spaces_calls_with_fake_clock():
    from portfolio_copilot.brokers.etoro import _SlidingWindowLimiter

    clock = FakeClock(start=0.0)
    sleeper = RecordingSleeper(clock)
    limiter = _SlidingWindowLimiter(max_calls=2, window_s=10.0, clock=clock, sleep=sleeper)

    limiter.acquire()  # t=0
    clock.advance(1.0)
    limiter.acquire()  # t=1, now at capacity (2 calls in window)
    limiter.acquire()  # t=1 -> must wait until first call (t=0) exits the 10s window -> sleep 9s

    assert sleeper.calls == [9.0]


def test_rate_limiter_does_not_sleep_when_under_capacity():
    from portfolio_copilot.brokers.etoro import _SlidingWindowLimiter

    clock = FakeClock(start=0.0)
    sleeper = RecordingSleeper(clock)
    limiter = _SlidingWindowLimiter(max_calls=5, window_s=10.0, clock=clock, sleep=sleeper)
    for _ in range(5):
        limiter.acquire()
    assert sleeper.calls == []


# ---------------------------------------------------------------------------------
# 429 handling
# ---------------------------------------------------------------------------------


def test_429_retries_once_after_retry_after_then_succeeds():
    calls = {"n": 0}
    sleeper = RecordingSleeper()

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "3"}, json={"detail": "slow down"})
        return httpx.Response(200, json=_pnl_body())

    client = make_client(handler, sleep=sleeper)
    result = client.account()
    assert calls["n"] == 2
    assert sleeper.calls == [3.0]
    assert result["cash_available"] == 1000.0


def test_429_twice_raises_rate_limited_with_retry_after():
    sleeper = RecordingSleeper()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "2"}, json={"detail": "too many"})

    client = make_client(handler, sleep=sleeper)
    with pytest.raises(RateLimited) as exc_info:
        client.account()
    assert exc_info.value.retry_after == 2.0
    assert exc_info.value.status == 429
    assert sleeper.calls == [2.0]


# ---------------------------------------------------------------------------------
# Typed error mapping
# ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,detail,mode,expected_exc",
    [
        (401, "invalid key", "demo", NotConfigured),
        (403, "forbidden", "real", NotConfigured),
        (400, "KYC verification required before trading", "demo", KycRequired),
        (400, "insufficient funds for this order", "demo", InsufficientFunds),
        (400, "the market is currently closed", "demo", MarketClosed),
        (500, "internal server error", "demo", Unavailable),
        (400, "some other validation problem", "demo", EToroError),
    ],
)
def test_error_status_maps_to_expected_exception_type(status, detail, mode, expected_exc):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status,
            json={
                "type": "about:blank",
                "title": "Error",
                "status": status,
                "detail": detail,
                "instance": "/x",
            },
        )

    client = make_client(handler, mode=mode)
    with pytest.raises(expected_exc) as exc_info:
        client.account()
    assert exc_info.value.status == status
    assert isinstance(exc_info.value.request_id, str) and exc_info.value.request_id


def test_demo_401_message_mentions_other_environment():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "unauthorized"})

    client = make_client(handler, mode="demo")
    with pytest.raises(NotConfigured) as exc_info:
        client.account()
    assert "other environment" in exc_info.value.message


def test_error_message_never_leaks_credentials():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    client = make_client(handler)
    with pytest.raises(Unavailable) as exc_info:
        client.account()
    text = str(exc_info.value)
    assert FAKE_API_KEY not in text
    assert FAKE_USER_KEY not in text


def test_cancel_order_is_not_available_and_makes_no_request():
    client = make_client(never_called_handler)
    with pytest.raises(NotAvailable):
        client.cancel_order("123")


# ---------------------------------------------------------------------------------
# Normalisation: missing fields -> None, never invented
# ---------------------------------------------------------------------------------


def test_account_normalisation_missing_equity_stays_none():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_pnl_body(credit=207756.0, unrealizedPnL=42.5))

    client = make_client(handler)
    result = client.account()
    assert result["cash_available"] == 207756.0
    assert result["unrealized_pnl_total"] == 42.5
    assert result["equity"] is None  # never computed, only ever an explicit field
    assert result["source"] == "etoro_api"
    assert result["tier"] == "A"
    assert result["mode"] == "demo"


def test_positions_normalisation_with_missing_optional_fields():
    position = {
        "positionID": 555,
        "instrumentID": 1001,
        "units": 2.5,
        "openRate": 150.0,
        "isBuy": True,
        "amount": 375.0,
        "leverage": 1,
        "openDateTime": "2026-08-01T00:00:00Z",
        "unrealizedPnL": {"pnL": 12.3},
        # exposureInAccountCurrency intentionally absent
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_pnl_body(positions=[position]))

    client = make_client(handler)
    result = client.positions()
    assert len(result["positions"]) == 1
    normalized = result["positions"][0]
    assert normalized["position_id"] == 555
    assert normalized["pnl"] == 12.3
    assert normalized["exposure"] is None
    assert normalized["symbol"] is None  # instrument() never called -> no cache hit
    assert normalized["name"] is None


def test_positions_symbol_resolved_from_instrument_cache():
    position = {
        "positionID": 1,
        "instrumentID": 1001,
        "units": 1.0,
        "openRate": 100.0,
        "isBuy": True,
        "amount": 100.0,
        "leverage": 1,
        "openDateTime": "2026-08-01T00:00:00Z",
        "unrealizedPnL": {"pnL": 0.0, "exposureInAccountCurrency": 100.0},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "instruments" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "instrumentID": 1001,
                    "symbolFull": "AAPL",
                    "instrumentDisplayName": "Apple",
                    "exchangeID": 4,
                    "instrumentTypeID": 5,
                    "isCurrentlyTradable": True,
                },
            )
        return httpx.Response(200, json=_pnl_body(positions=[position]))

    client = make_client(handler)
    client.instrument(1001)
    result = client.positions()
    normalized = result["positions"][0]
    assert normalized["symbol"] == "AAPL"
    assert normalized["name"] == "Apple"


def test_search_instruments_uses_live_probed_field_names():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("internalSymbolFull") == "AAPL"
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "internalInstrumentId": 1001,
                        "internalSymbolFull": "AAPL",
                        "internalInstrumentDisplayName": "Apple",
                        "internalAssetClassId": 5,
                    }
                ]
            },
        )

    client = make_client(handler)
    result = client.search_instruments("AAPL")
    assert result["items"] == [
        {
            "instrument_id": 1001,
            "symbol": "AAPL",
            "name": "Apple",
            "asset_class_id": 5,
            "current_rate": None,
            "tradable": None,
        }
    ]


def test_rate_normalisation():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                {
                    "instrumentID": 1001,
                    "ask": 101.5,
                    "bid": 101.4,
                    "date": "2026-08-29T00:00:00Z",
                }
            ],
        )

    client = make_client(handler)
    result = client.rate(1001)
    assert result["ask"] == 101.5
    assert result["bid"] == 101.4
    assert result["last_execution"] is None


def test_eligibility_normalisation():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(
            200,
            json=[
                {
                    "instrumentId": 1001,
                    "unitsQuantityType": "FractionalUnits",
                    "minPositionExposure": 50.0,
                    "allowOpenPosition": True,
                    "allowEntryOrders": True,
                    "allowExitOrders": True,
                }
            ],
        )

    client = make_client(handler)
    result = client.eligibility(1001)
    assert result["units_quantity_type"] == "FractionalUnits"
    assert result["min_position_exposure"] == 50.0
    assert result["tradable"] is True


def test_orders_groups_pass_through_without_invented_fields():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_pnl_body(ordersForClose=[{"orderID": 77, "instrumentID": 1001, "statusID": 11}]),
        )

    client = make_client(handler)
    result = client.orders()
    assert result["orders"]["ordersForClose"] == [
        {"orderID": 77, "instrumentID": 1001, "statusID": 11}
    ]
    assert result["orders"]["orders"] == []


# ---------------------------------------------------------------------------------
# Order open / lookup / wait_for_fill / close
# ---------------------------------------------------------------------------------


def test_open_market_order_body_and_response():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        captured["body"] = _json.loads(request.content)
        captured["path"] = request.url.path
        return httpx.Response(
            200, json={"token": "tok-1", "orderId": 999, "referenceId": "ref-1"}
        )

    client = make_client(handler, mode="demo")
    result = client.open_market_order(1001, amount=116.0)
    assert captured["body"]["action"] == "open"
    assert captured["body"]["transaction"] == "buy"
    assert captured["body"]["settlementType"] == "real"
    assert captured["body"]["leverage"] == 1
    assert captured["body"]["amount"] == 116.0
    assert "units" not in captured["body"]
    assert captured["path"].endswith("/demo/orders")
    assert result["order_id"] == 999
    assert result["reference_id"] == "ref-1"


def test_open_market_order_units_takes_precedence_over_amount():
    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        body = _json.loads(request.content)
        assert "amount" not in body
        assert body["units"] == 2.0
        return httpx.Response(200, json={"orderId": 1, "referenceId": "r", "token": "t"})

    client = make_client(handler)
    client.open_market_order(1001, amount=100.0, units=2.0)


def test_open_market_order_requires_amount_or_units():
    client = make_client(never_called_handler)
    with pytest.raises(ValueError):
        client.open_market_order(1001, amount=None, units=None)


def test_open_market_order_rejects_invalid_side():
    client = make_client(never_called_handler)
    with pytest.raises(ValueError):
        client.open_market_order(1001, amount=10.0, side="sell")


def test_order_lookup_normalises_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"orderId": 999, "status": {"id": 3, "name": "Filled"}},
        )

    client = make_client(handler)
    result = client.order_lookup(999)
    assert result["status"] == "filled"
    assert result["status_id"] == 3


def test_wait_for_fill_open_polls_until_filled():
    statuses = iter([{"id": 1}, {"id": 1}, {"id": 3}])
    sleeper = RecordingSleeper()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"orderId": 1, "status": next(statuses)})

    client = make_client(handler, sleep=sleeper)
    result = client.wait_for_fill(1, kind="open", polls=10, interval_s=0.5)
    assert result["status"] == "filled"
    assert sleeper.calls == [0.5, 0.5]


def test_wait_for_fill_open_returns_last_state_when_exhausted():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"orderId": 1, "status": {"id": 1}})

    client = make_client(handler, sleep=RecordingSleeper())
    result = client.wait_for_fill(1, kind="open", polls=2, interval_s=0.1)
    assert result["status"] == "pending"


def test_wait_for_fill_close_uses_pnl_arrays_not_orders_lookup():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert "orders:lookup" not in request.url.path
        if calls["n"] == 1:
            # still open: position present, order still pending
            return httpx.Response(
                200,
                json=_pnl_body(
                    positions=[{"positionID": 42, "instrumentID": 1001, "unrealizedPnL": {}}],
                    ordersForClose=[{"orderID": 77}],
                ),
            )
        # closed: position gone, order no longer listed
        return httpx.Response(200, json=_pnl_body(positions=[], ordersForClose=[]))

    client = make_client(handler, sleep=RecordingSleeper())
    result = client.wait_for_fill(77, kind="close", position_id=42, polls=5, interval_s=0.1)
    assert result["status"] == "filled"


def test_close_position_normalisation():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path.endswith("/positions/42")
        return httpx.Response(
            200,
            json={
                "orderForClose": {
                    "positionID": 42,
                    "instrumentID": 1001,
                    "orderID": 88,
                    "statusID": 1,
                },
                "token": "tok",
            },
        )

    client = make_client(handler)
    result = client.close_position(42, 1001)
    assert result["order_id"] == 88
    assert result["position_id"] == 42
    assert result["status_id"] == 1


def test_429_read_retry_reuses_the_same_request_id():
    seen_request_ids: list[str] = []
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        seen_request_ids.append(request.headers.get("x-request-id"))
        if calls["n"] == 1:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={"detail": "slow"})
        return httpx.Response(200, json=_pnl_body())

    client = make_client(handler, sleep=RecordingSleeper())
    client.account()
    assert calls["n"] == 2
    # The retry is the SAME logical request: its idempotency id must not change.
    assert seen_request_ids[0] == seen_request_ids[1]


def test_429_on_write_never_retries_and_raises_rate_limited():
    calls = {"n": 0}
    sleeper = RecordingSleeper()

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "2"}, json={"detail": "too many"})

    client = make_client(handler, sleep=sleeper)
    with pytest.raises(RateLimited):
        client.eligibility(1001)  # write-tier call: an auto-retry could double-send
    assert calls["n"] == 1
    assert sleeper.calls == []


def test_instrument_reads_the_live_instrument_display_datas_shape():
    """Live-probed 2026-08-29: the real /market-data/instruments payload wraps rows in
    ``instrumentDisplayDatas`` and carries NO symbol field at all -- only the display
    name. The name must resolve; the symbol must stay None (never invented)."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "instrumentDisplayDatas": [
                    {
                        "instrumentID": 9423,
                        "instrumentDisplayName": "Adobe Systems Inc",
                        "instrumentTypeID": 5,
                        "exchangeID": 33,
                        "images": [],
                    }
                ]
            },
        )

    client = make_client(handler)
    result = client.instrument(9423)
    assert result["instrument_id"] == 9423
    assert result["name"] == "Adobe Systems Inc"
    assert result["symbol"] is None
