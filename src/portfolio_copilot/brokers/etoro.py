"""eToro Public API v2 client — the user's own account, tier A, read + gated execution.

Built strictly from ``etoro_api_notes.md`` (VERIFIED items used as-is; UNVERIFIED items are
either implemented behind a module-level constant marked with a ``NOTE`` comment, or -- where
the notes give no method/path/body at all -- deliberately **not implemented**, raising
``NotAvailable`` instead of guessing an endpoint. This module only talks to
``https://public-api.etoro.com``; it never logs in, never scrapes a private area, and never
stores credentials anywhere but in memory for the lifetime of one client instance.

Not implemented (raise ``NotAvailable``), and why:

- ``cancel_order``: the notes list only a doc-page *title* for order cancellation
  ("cancels-an-order-before-it-is-executed") with no confirmed method, path, or request body.
- Full portfolio (``/api/v1/trading/info/portfolio``), aggregate-portfolio, modify SL/TP,
  async order submission and cost-preview are VERIFIED to exist but were not requested by
  this client's method list; adding a path constant for one only when a method uses it keeps
  an unused, never-exercised guess out of the module.

Every method returns a dict shaped ``{..normalised fields.., "raw": <payload>,
"source": "etoro_api", "tier": "A", "mode": <demo|real>, "as_of": <ISO 8601 UTC>}``. A field
the API payload does not carry is ``None`` -- this client never invents a value (including
``equity``, which the notes explicitly warn must not be computed here; see ``account()``).
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

# --------------------------------------------------------------------------------------
# Base URL and paths (module-level constants, per the eToro API notes).
# --------------------------------------------------------------------------------------

BASE_URL = "https://public-api.etoro.com"

# VERIFIED (§2.2 of the notes; live-probed 2026-08-29 for both demo and real).
PATH_PNL_REAL = "/api/v1/trading/info/real/pnl"
PATH_PNL_DEMO = "/api/v1/trading/info/demo/pnl"

# VERIFIED (§3.1/§3.2/§3.3). Market-data has no demo/real split.
PATH_SEARCH = "/api/v1/market-data/search"
PATH_INSTRUMENTS = "/api/v1/market-data/instruments"
PATH_RATES = "/api/v1/market-data/instruments/rates"

# VERIFIED (§4.8).
PATH_ELIGIBILITY = "/api/v2/trading/info/eligibility"

# VERIFIED (§4.1).
PATH_ORDER_OPEN_REAL = "/api/v2/trading/execution/orders"
PATH_ORDER_OPEN_DEMO = "/api/v2/trading/execution/demo/orders"

# VERIFIED (§2.4/§4.3).
PATH_ORDER_LOOKUP_REAL = "/api/v2/trading/info/orders:lookup"
PATH_ORDER_LOOKUP_DEMO = "/api/v2/trading/info/demo/orders:lookup"

# Real: VERIFIED (§4.2). Demo: VERIFIED live-probed 2026-08-29 (task context "CLOSE-ORDER
# STATUS"), matching the real path pattern with a /demo/ segment.
PATH_CLOSE_POSITION_REAL = "/api/v1/trading/execution/market-close-orders/positions/{position_id}"
PATH_CLOSE_POSITION_DEMO = (
    "/api/v1/trading/execution/demo/market-close-orders/positions/{position_id}"
)

# Demo vs real path selection lives in this ONE table + helper (``EToroClient._venue_path``).
_VENUE_PATHS: dict[str, dict[str, str]] = {
    "pnl": {"demo": PATH_PNL_DEMO, "real": PATH_PNL_REAL},
    "order_open": {"demo": PATH_ORDER_OPEN_DEMO, "real": PATH_ORDER_OPEN_REAL},
    "order_lookup": {"demo": PATH_ORDER_LOOKUP_DEMO, "real": PATH_ORDER_LOOKUP_REAL},
    "close_position": {"demo": PATH_CLOSE_POSITION_DEMO, "real": PATH_CLOSE_POSITION_REAL},
}

# Order-status-id -> normalised status (VERIFIED, market-orders guide, §2.4).
_ORDER_STATUS_MAP: dict[int, str] = {
    1: "pending",
    2: "pending",
    11: "pending",
    12: "pending",
    3: "filled",
    4: "rejected",
    5: "partially_filled",
    10: "rejected_partially_filled",
}
_TERMINAL_ORDER_STATUSES = {"filled", "rejected", "cancelled", "rejected_partially_filled"}

DEFAULT_ENV_FILE = Path(__file__).resolve().parents[3] / "data" / "private" / "etoro.env"

_READ_RATE_LIMIT = 60  # requests / 60s (VERIFIED, §5, shared read tier)
_WRITE_RATE_LIMIT = 20  # requests / 60s (VERIFIED, §5, shared write/eligibility tier)
_RATE_WINDOW_S = 60.0
_DEFAULT_RETRY_AFTER_S = 1.0


# --------------------------------------------------------------------------------------
# Credentials
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Credentials:
    """eToro API credentials: the application key and the user key.

    ``repr``/``str`` always redact both keys -- neither value is ever safe to log.
    """

    api_key: str
    user_key: str

    def __repr__(self) -> str:  # pragma: no cover - trivial, exercised via str() tests
        return "Credentials(api_key='***', user_key='***')"

    def __str__(self) -> str:
        return self.__repr__()


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


_UNSET: Any = object()


def load_credentials(
    env: Mapping[str, str] | None = None,
    env_file: Path | None = _UNSET,
) -> Credentials | None:
    """Load eToro credentials: env vars first, then a ``KEY=VALUE`` file.

    ``env`` defaults to ``os.environ``. ``env_file`` defaults to
    ``data/private/etoro.env``; pass ``None`` explicitly to skip the file entirely. Returns
    ``None`` when no complete credential pair is found anywhere -- this never raises for
    absence, so the adapter can treat "not configured" as a normal, silent state.
    """
    active_env = os.environ if env is None else env
    api_key = active_env.get("ETORO_API_KEY")
    user_key = active_env.get("ETORO_USER_KEY")
    if api_key and user_key:
        return Credentials(api_key=api_key, user_key=user_key)

    path = DEFAULT_ENV_FILE if env_file is _UNSET else env_file
    if path is None or not path.exists():
        return None
    file_values = _parse_env_file(path)
    api_key = file_values.get("ETORO_API_KEY")
    user_key = file_values.get("ETORO_USER_KEY")
    if api_key and user_key:
        return Credentials(api_key=api_key, user_key=user_key)
    return None


# --------------------------------------------------------------------------------------
# Typed errors
# --------------------------------------------------------------------------------------


class EToroError(Exception):
    """Base error. Never carries headers, keys, or other credential material."""

    def __init__(
        self, status: int, code: str, message: str, request_id: str | None
    ) -> None:
        self.status = status
        self.code = code
        self.message = message
        self.request_id = request_id
        super().__init__(f"eToro API error {status} ({code}): {message} [request_id={request_id}]")


class NotConfigured(EToroError):
    """No credentials, or credentials rejected (401/403) -- possibly bound to the other
    environment (see the demo/real key-binding caveat in the notes)."""


class KycRequired(EToroError):
    pass


class InsufficientFunds(EToroError):
    pass


class MarketClosed(EToroError):
    pass


class RateLimited(EToroError):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        request_id: str | None,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(status, code, message, request_id)
        self.retry_after = retry_after


class Unavailable(EToroError):
    """5xx / transport-level failure."""


class NotAvailable(EToroError):
    """This client deliberately does not implement the requested call: the API notes give
    no verified method/path/body for it. Never a guessed endpoint."""


def _error_for(status: int, message: str, request_id: str | None, mode: str) -> EToroError:
    if status in (401, 403):
        if mode == "demo":
            note = (
                f"credentials appear bound to the other environment (demo call returned {status})"
            )
        else:
            note = message or f"authentication failed ({status})"
        return NotConfigured(status, "auth", note, request_id)
    lowered = (message or "").lower()
    if "kyc" in lowered or "verif" in lowered:
        return KycRequired(status, "kyc_required", message, request_id)
    if "insufficient" in lowered or "funds" in lowered:
        return InsufficientFunds(status, "insufficient_funds", message, request_id)
    if "market" in lowered and "closed" in lowered:
        return MarketClosed(status, "market_closed", message, request_id)
    if status >= 500:
        return Unavailable(status, "unavailable", message, request_id)
    return EToroError(status, "error", message, request_id)


# --------------------------------------------------------------------------------------
# Rate limiter
# --------------------------------------------------------------------------------------


class _SlidingWindowLimiter:
    """Sliding-window limiter with injectable clock/sleep, for deterministic tests."""

    def __init__(
        self,
        max_calls: int,
        window_s: float,
        clock: Callable[[], float],
        sleep: Callable[[float], None],
    ) -> None:
        self.max_calls = max_calls
        self.window_s = window_s
        self._clock = clock
        self._sleep = sleep
        self._calls: list[float] = []

    def acquire(self) -> None:
        now = self._clock()
        self._calls = [t for t in self._calls if t > now - self.window_s]
        if len(self._calls) >= self.max_calls:
            wait = self._calls[0] + self.window_s - now
            if wait > 0:
                self._sleep(wait)
            now = self._clock()
            self._calls = [t for t in self._calls if t > now - self.window_s]
        self._calls.append(now)


# --------------------------------------------------------------------------------------
# Client
# --------------------------------------------------------------------------------------


class EToroClient:
    """eToro Public API v2 client for one account mode (demo or real).

    ``transport`` is an ``httpx.BaseTransport`` (e.g. ``httpx.MockTransport`` in tests);
    when omitted, a real network transport is used. ``clock``/``sleep`` are injectable for
    deterministic rate-limiter and retry tests.
    """

    def __init__(
        self,
        credentials: Credentials | None,
        mode: Literal["demo", "real"] = "demo",
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if mode not in ("demo", "real"):
            raise ValueError("mode must be 'demo' or 'real'")
        self.credentials = credentials
        self.mode = mode
        self.timeout = timeout
        self._clock = clock
        self._sleep = sleep
        self._read_limiter = _SlidingWindowLimiter(_READ_RATE_LIMIT, _RATE_WINDOW_S, clock, sleep)
        self._write_limiter = _SlidingWindowLimiter(
            _WRITE_RATE_LIMIT, _RATE_WINDOW_S, clock, sleep
        )
        self._client = httpx.Client(base_url=BASE_URL, transport=transport, timeout=timeout)
        self._instrument_cache: dict[int, dict[str, Any]] = {}

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> EToroClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- internals -----------------------------------------------------------------

    def _venue_path(self, kind: str, **fmt: Any) -> str:
        template = _VENUE_PATHS[kind][self.mode]
        return template.format(**fmt) if fmt else template

    def _envelope(self, raw: Any, extra: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "source": "etoro_api",
            "tier": "A",
            "mode": self.mode,
            "as_of": datetime.now(UTC).isoformat(),
            "raw": raw,
        }
        result.update(extra)
        return result

    @staticmethod
    def _retry_after_seconds(headers: httpx.Headers) -> float:
        raw = headers.get("Retry-After")
        if raw is None:
            return _DEFAULT_RETRY_AFTER_S
        try:
            return max(0.0, float(raw))
        except ValueError:
            return _DEFAULT_RETRY_AFTER_S

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        write: bool = False,
    ) -> Any:
        if self.credentials is None:
            raise NotConfigured(0, "not_configured", "eToro credentials are not configured", None)

        limiter = self._write_limiter if write else self._read_limiter
        response: httpx.Response | None = None
        # One id per LOGICAL request: a 429 retry re-sends the same request, so it must
        # carry the same idempotency id -- a fresh id on a write retry could double-send.
        request_id = str(uuid.uuid4())
        for attempt in range(2):
            limiter.acquire()
            headers = {
                "x-api-key": self.credentials.api_key,
                "x-user-key": self.credentials.user_key,
                "x-request-id": request_id,
                "User-Agent": "portfolio-copilot",
            }
            if json_body is not None:
                headers["Content-Type"] = "application/json"
            response = self._client.request(
                method, path, params=params, json=json_body, headers=headers
            )
            # Writes are never auto-retried on 429: RateLimited surfaces to the caller,
            # who decides whether re-sending an order is safe.
            if response.status_code == 429 and attempt == 0 and not write:
                self._sleep(self._retry_after_seconds(response.headers))
                continue
            break

        assert response is not None  # loop always runs at least once
        return self._parse_or_raise(response, request_id)

    def _parse_or_raise(self, response: httpx.Response, request_id: str) -> Any:
        if 200 <= response.status_code < 300:
            if not response.content:
                return {}
            return response.json()

        try:
            body: Any = response.json()
        except ValueError:
            body = {}
        detail = body.get("detail") if isinstance(body, dict) else None
        title = body.get("title") if isinstance(body, dict) else None
        message = detail or title or (response.text[:200] if response.text else "")
        message = message or f"HTTP {response.status_code}"

        if response.status_code == 429:
            retry_after = self._retry_after_seconds(response.headers)
            raise RateLimited(429, "rate_limited", message, request_id, retry_after=retry_after)
        raise _error_for(response.status_code, message, request_id, self.mode)

    # -- account / positions ---------------------------------------------------------

    def account(self) -> dict[str, Any]:
        """Cash and unrealized P/L from the pnl endpoint.

        ``equity`` is only ever set from an explicit field in the payload -- this client
        never derives it, per the notes' explicit warning against inventing equity.
        """
        payload = self._request("GET", self._venue_path("pnl"))
        portfolio = payload.get("clientPortfolio", payload) if isinstance(payload, dict) else {}
        return self._envelope(
            payload,
            {
                "cash_available": portfolio.get("credit"),
                "unrealized_pnl_total": portfolio.get("unrealizedPnL"),
                "equity": portfolio.get("equity"),
                "account_currency_id": portfolio.get("accountCurrencyId"),
            },
        )

    def positions(self) -> dict[str, Any]:
        """Open positions, normalised. Symbol/name come only from an already-cached
        ``instrument()`` lookup -- this never triggers a network call per position."""
        payload = self._request("GET", self._venue_path("pnl"))
        portfolio = payload.get("clientPortfolio", payload) if isinstance(payload, dict) else {}
        raw_positions = portfolio.get("positions") or []
        normalized = []
        for pos in raw_positions:
            if not isinstance(pos, dict):
                continue
            pnl_block = pos.get("unrealizedPnL") or {}
            instrument_id = pos.get("instrumentID")
            cached = (
                self._instrument_cache.get(instrument_id) if instrument_id is not None else None
            )
            normalized.append(
                {
                    "position_id": pos.get("positionID"),
                    "instrument_id": instrument_id,
                    "symbol": cached.get("symbol") if cached else None,
                    "name": cached.get("name") if cached else None,
                    "units": pos.get("units"),
                    "open_rate": pos.get("openRate"),
                    "amount": pos.get("amount"),
                    "leverage": pos.get("leverage"),
                    "is_buy": pos.get("isBuy"),
                    "pnl": pnl_block.get("pnL"),
                    "exposure": pnl_block.get("exposureInAccountCurrency"),
                    "opened_at": pos.get("openDateTime"),
                }
            )
        return self._envelope(payload, {"positions": normalized})

    def orders(self) -> dict[str, Any]:
        """Pending order arrays as carried by the pnl payload (VERIFIED live, §2.2/task
        LIVE FACTS): ``orders``, ``stockOrders``, ``entryOrders``, ``exitOrders``,
        ``ordersForOpen``, ``ordersForClose``, ``ordersForCloseMultiple`` -- passed through
        per group, never re-shaped beyond that (their individual field lists are not fully
        documented)."""
        payload = self._request("GET", self._venue_path("pnl"))
        portfolio = payload.get("clientPortfolio", payload) if isinstance(payload, dict) else {}
        groups = {
            key: portfolio.get(key) or []
            for key in (
                "orders",
                "stockOrders",
                "entryOrders",
                "exitOrders",
                "ordersForOpen",
                "ordersForClose",
                "ordersForCloseMultiple",
            )
        }
        return self._envelope(payload, {"orders": groups})

    def cancel_order(self, order_id: int | str) -> dict[str, Any]:
        raise NotAvailable(
            0,
            "not_available",
            "cancel_order is not implemented: the eToro API notes name only a doc-page title "
            "for order cancellation, with no confirmed method, path, or request body",
            None,
        )

    # -- instruments / rates ----------------------------------------------------------

    def search_instruments(self, query: str) -> dict[str, Any]:
        """Ticker/name search. Field names match the live-probed response shape
        (``internalInstrumentId``/``internalSymbolFull``/``internalInstrumentDisplayName``/
        ``internalAssetClassId``), which differs from the (unconfirmed against a live call)
        doc-page field names -- the live probe takes precedence."""
        payload = self._request("GET", PATH_SEARCH, params={"internalSymbolFull": query})
        items = payload.get("items") or [] if isinstance(payload, dict) else []
        normalized = [
            {
                "instrument_id": it.get("internalInstrumentId"),
                "symbol": it.get("internalSymbolFull"),
                "name": it.get("internalInstrumentDisplayName"),
                "asset_class_id": it.get("internalAssetClassId"),
                "current_rate": it.get("currentRate"),
                "tradable": it.get("isCurrentlyTradable"),
            }
            for it in items
            if isinstance(it, dict)
        ]
        return self._envelope(payload, {"items": normalized})

    def instrument(self, instrument_id: int) -> dict[str, Any]:
        """Instrument metadata (doc field names, §3.2 -- not independently live-probed).
        Caches the normalised result so ``positions()`` can resolve symbol/name."""
        payload = self._request(
            "GET", PATH_INSTRUMENTS, params={"instrumentIds": str(instrument_id)}
        )
        rows: list[dict[str, Any]]
        if isinstance(payload, dict) and "instrumentID" in payload:
            rows = [payload]
        elif isinstance(payload, dict):
            # "instrumentDisplayDatas" is the live-probed wrapper key (2026-08-29); the
            # doc-page names ("items"/"instruments") are kept as fallbacks.
            rows = (
                payload.get("instrumentDisplayDatas")
                or payload.get("items")
                or payload.get("instruments")
                or []
            )
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []
        row = next(
            (r for r in rows if isinstance(r, dict) and r.get("instrumentID") == instrument_id),
            (rows[0] if rows else {}),
        )
        normalized = {
            "instrument_id": row.get("instrumentID", instrument_id),
            "symbol": row.get("symbolFull"),
            "name": row.get("instrumentDisplayName"),
            "exchange": row.get("exchangeID"),
            "instrument_type": row.get("instrumentTypeID"),
            "tradable": row.get("isCurrentlyTradable"),
        }
        self._instrument_cache[normalized["instrument_id"]] = normalized
        return self._envelope(payload, normalized)

    def rate(self, instrument_id: int) -> dict[str, Any]:
        payload = self._request("GET", PATH_RATES, params={"instrumentIds": str(instrument_id)})
        rows: list[dict[str, Any]]
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = payload.get("items") or payload.get("rates") or []
        else:
            rows = []
        row = next(
            (r for r in rows if isinstance(r, dict) and r.get("instrumentID") == instrument_id),
            (rows[0] if rows else {}),
        )
        normalized = {
            "instrument_id": row.get("instrumentID", instrument_id),
            "ask": row.get("ask"),
            "bid": row.get("bid"),
            "last_execution": row.get("lastExecution"),
            "date": row.get("date"),
        }
        return self._envelope(payload, normalized)

    def eligibility(self, instrument_id: int) -> dict[str, Any]:
        """Pre-trade validation: fractional-unit support, minimum trade size, market-open
        state (§4.8). Uses the write-tier limiter (dedicated 20/60s per the notes)."""
        payload = self._request(
            "POST",
            PATH_ELIGIBILITY,
            json_body={"instrumentIds": [instrument_id]},
            write=True,
        )
        rows: list[dict[str, Any]]
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            rows = payload.get("items") or payload.get("eligibility") or []
        else:
            rows = []
        row = next(
            (
                r
                for r in rows
                if isinstance(r, dict) and r.get("instrumentId") == instrument_id
            ),
            (rows[0] if rows else {}),
        )
        return self._envelope(
            payload,
            {
                "instrument_id": instrument_id,
                "units_quantity_type": row.get("unitsQuantityType"),
                "min_position_exposure": row.get("minPositionExposure"),
                "tradable": row.get("allowOpenPosition"),
                "allow_entry_orders": row.get("allowEntryOrders"),
                "allow_exit_orders": row.get("allowExitOrders"),
            },
        )

    # -- orders: open / lookup / wait / close -----------------------------------------

    def open_market_order(
        self,
        instrument_id: int,
        amount: float | None,
        side: Literal["buy", "sellShort"] = "buy",
        leverage: int = 1,
        units: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        settlement_type: str = "real",
    ) -> dict[str, Any]:
        """Open a market order. ``amount``/``units`` are mutually exclusive (``units`` wins
        if both given); the caller (execution pipeline) is responsible for choosing
        ``settlement_type='real'``/``leverage=1`` for stock/ETF buys per the plan."""
        if side not in ("buy", "sellShort"):
            raise ValueError(
                "side must be 'buy' or 'sellShort' (this endpoint has no plain 'sell')"
            )
        body: dict[str, Any] = {
            "action": "open",
            "transaction": side,
            "instrumentId": instrument_id,
            "settlementType": settlement_type,
            "orderType": "mkt",
            "leverage": leverage,
            "orderCurrency": "usd",
        }
        if units is not None:
            body["units"] = units
        elif amount is not None:
            body["amount"] = amount
        else:
            raise ValueError("either amount or units must be given")
        if stop_loss is not None:
            body["stopLossRate"] = stop_loss
        if take_profit is not None:
            body["takeProfitRate"] = take_profit

        payload = self._request(
            "POST", self._venue_path("order_open"), json_body=body, write=True
        )
        return self._envelope(
            payload,
            {
                "order_id": payload.get("orderId"),
                "reference_id": payload.get("referenceId"),
                "token": payload.get("token"),
            },
        )

    def order_lookup(self, order_id: int | str) -> dict[str, Any]:
        payload = self._request(
            "GET", self._venue_path("order_lookup"), params={"orderId": order_id}
        )
        status_block = payload.get("status") or {} if isinstance(payload, dict) else {}
        status_id = status_block.get("id")
        return self._envelope(
            payload,
            {
                "order_id": payload.get("orderId"),
                "status": _ORDER_STATUS_MAP.get(status_id, "unknown"),
                "status_id": status_id,
                "error_code": status_block.get("errorCode"),
                "error_message": status_block.get("errorMessage"),
            },
        )

    def _poll_close_status(self, order_id: int | str, position_id: int | None) -> dict[str, Any]:
        """Close orders don't appear in ``orders:lookup`` (404, live-probed); poll the pnl
        arrays instead: still pending while the position remains in ``positions()`` or the
        order id is still listed under ``ordersForClose``/``ordersForCloseMultiple``."""
        positions_payload = self.positions()
        orders_payload = self.orders()
        still_open = any(
            p.get("position_id") == position_id for p in positions_payload.get("positions", [])
        )
        pending_ids: set[Any] = set()
        for group_key in ("ordersForClose", "ordersForCloseMultiple"):
            group = orders_payload.get("orders", {}).get(group_key) or []
            if isinstance(group, dict):
                group = [group]
            for entry in group:
                if isinstance(entry, dict) and entry.get("orderID") is not None:
                    pending_ids.add(entry.get("orderID"))
        status = "pending" if (still_open or order_id in pending_ids) else "filled"
        return {
            "order_id": order_id,
            "position_id": position_id,
            "status": status,
            "source": "etoro_api",
            "tier": "A",
            "mode": self.mode,
            "as_of": datetime.now(UTC).isoformat(),
            "raw": {"positions": positions_payload["raw"], "orders": orders_payload["raw"]},
        }

    def wait_for_fill(
        self,
        order_id: int | str,
        *,
        kind: Literal["open", "close"] = "open",
        position_id: int | None = None,
        polls: int = 10,
        interval_s: float = 1.0,
    ) -> dict[str, Any]:
        """Poll until the order reaches a terminal state, or ``polls`` attempts are used up.

        ``kind='open'`` polls ``order_lookup``; ``kind='close'`` polls the pnl arrays
        instead (see ``_poll_close_status`` and the notes' CLOSE-ORDER STATUS caveat).
        Never raises on exhaustion -- returns the last observed (possibly still-pending)
        result so the caller decides what to record.
        """
        last: dict[str, Any] | None = None
        for attempt in range(max(1, polls)):
            last = (
                self._poll_close_status(order_id, position_id)
                if kind == "close"
                else self.order_lookup(order_id)
            )
            if last.get("status") in _TERMINAL_ORDER_STATUSES or last.get("status") == "filled":
                return last
            if attempt < polls - 1:
                self._sleep(interval_s)
        assert last is not None
        return last

    def close_position(
        self, position_id: int, instrument_id: int, units: float | None = None
    ) -> dict[str, Any]:
        """Close (fully, or partially if ``units`` is given) an open position."""
        payload = self._request(
            "POST",
            self._venue_path("close_position", position_id=position_id),
            json_body={"InstrumentId": instrument_id, "UnitsToDeduct": units},
            write=True,
        )
        order_for_close = payload.get("orderForClose") or {} if isinstance(payload, dict) else {}
        return self._envelope(
            payload,
            {
                "order_id": order_for_close.get("orderID"),
                "position_id": order_for_close.get("positionID", position_id),
                "status_id": order_for_close.get("statusID"),
                "token": payload.get("token") if isinstance(payload, dict) else None,
            },
        )
