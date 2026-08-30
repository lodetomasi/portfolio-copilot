"""Which account a portfolio call reads, and how eToro's data becomes a ``Portfolio``.

The export account (the other broker) and the eToro account are never merged: an
explicit export file path always wins over configured eToro credentials, and every
``Portfolio`` built here carries ``source`` / ``base_currency`` so downstream code
and skill output can always say which account a number came from.
"""

from __future__ import annotations

from typing import Any, Literal

from portfolio_copilot.models import AssetType, Holding, Portfolio

SourceKind = Literal["export", "etoro", "none"]

_ASSET_TYPE_MAP: dict[str, AssetType] = {
    "equity": AssetType.EQUITY,
    "stock": AssetType.EQUITY,
    "etf": AssetType.ETF,
    "certificate": AssetType.CERTIFICATE,
    "bond": AssetType.BOND,
    "cash": AssetType.CASH,
}


def resolve_source(path: str | None, etoro_configured: bool) -> SourceKind:
    """Decide which account a portfolio call should read.

    An explicit ``path`` always means the export account (the other broker,
    manual-only) and wins even when eToro credentials are also configured --
    naming a file is an explicit choice. With no path, eToro is used when
    credentials are configured; with neither, there is no source at all.
    """
    if path:
        return "export"
    if etoro_configured:
        return "etoro"
    return "none"


def source_unavailable_message(source: SourceKind) -> str:
    """Human-readable reason to show when ``resolve_source`` returned ``'none'``."""
    if source != "none":
        return ""
    return (
        "No portfolio source available: no export file path was given and no eToro "
        "credentials are configured (ETORO_API_KEY / ETORO_USER_KEY, or "
        "data/private/etoro.env)."
    )


def account_banner(
    source: SourceKind,
    mode: str | None = None,
    export_name: str | None = None,
) -> str:
    """One line every skill answer starts with, naming the account in view."""
    if source == "etoro":
        if (mode or "demo").strip().lower() == "real":
            return "Account: eToro REAL"
        return "Account: eToro DEMO (virtual)"
    if source == "export":
        return f"Account: export file {export_name or '(unnamed)'} (manual orders only)"
    return "Account: none configured"


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _asset_type_from(instrument_type: str | None) -> AssetType:
    if not instrument_type:
        return AssetType.OTHER
    return _ASSET_TYPE_MAP.get(str(instrument_type).strip().lower(), AssetType.OTHER)


def _native_market_value(
    position: dict[str, Any], quantity: float, market_price: float | None
) -> float | None:
    """Position value in the account's own currency, never invented.

    Precedence: an explicit ``market_value`` field; then ``|quantity| * market_price``
    (``current_rate``, when a live rate is present); then ``amount + pnl`` -- the
    invested amount plus unrealized P/L, i.e. the current liquidation value, using the
    keys ``EToroClient.positions()`` actually emits. ``None`` when no source exists.
    """
    explicit = _as_float(position.get("market_value"))
    if explicit is not None:
        return explicit
    if market_price is not None:
        return abs(quantity) * market_price
    amount = _as_float(position.get("amount"))
    pnl = _as_float(position.get("pnl"))
    if amount is not None and pnl is not None:
        return amount + pnl
    return None


def portfolio_from_etoro(
    positions: list[dict[str, Any]],
    account: dict[str, Any],
    fx_rate_eur_per_ccy: float | None,
) -> tuple[Portfolio, float | None, list[str]]:
    """Build a ``Portfolio`` from normalised eToro positions plus account info.

    Reads the keys ``EToroClient.positions()`` actually emits (all optional, missing ->
    ``None``/default, never invented): ``symbol``, ``name``, ``units`` (-> ``quantity``,
    negated for a short, i.e. ``is_buy`` explicitly ``False``), ``current_rate``
    (-> ``market_price``, when a live rate is present), ``market_value`` /
    ``amount`` + ``pnl`` (native-currency value, see ``_native_market_value``),
    ``instrument_type``, ``leverage``. ``account`` keys: ``currency`` (default
    ``"USD"``), ``cash_available`` (native currency).

    One ``Holding`` per position -- coverage is never silently lost. A position with
    no value source at all keeps ``market_value=0.0`` (the model requires a float) and
    its symbol is listed in the returned ``missing_value_symbols``: the caller MUST
    surface that list, because ``Portfolio.total_value`` understates while it is
    non-empty. ``market_value`` is converted to EUR via ``fx_rate_eur_per_ccy`` (must
    be > 0 when given) when the account currency is not EUR; when that rate is
    ``None`` the value is kept in the account's own currency and
    ``Portfolio.base_currency`` reflects that instead of guessing a rate.
    ``Portfolio.source`` is ``"etoro_api"``.

    Returns ``(portfolio, cash_available_eur, missing_value_symbols)`` -- the cash
    figure is ``None`` when it cannot be expressed in EUR (non-EUR account, no FX
    rate given).
    """
    if fx_rate_eur_per_ccy is not None and fx_rate_eur_per_ccy <= 0:
        raise ValueError(f"fx_rate_eur_per_ccy must be > 0, got {fx_rate_eur_per_ccy!r}")

    account_currency = str(account.get("currency") or "USD").upper()
    to_eur = 1.0 if account_currency == "EUR" else fx_rate_eur_per_ccy
    base_currency = "EUR" if to_eur is not None else account_currency

    holdings: list[Holding] = []
    missing_value_symbols: list[str] = []
    for position in positions:
        symbol = position.get("symbol")
        name = position.get("name") or symbol or "UNKNOWN"
        units = _as_float(position.get("units")) or 0.0
        # A short position (is_buy explicitly False) carries negative quantity; a
        # missing is_buy is treated as long, matching the export-account convention.
        quantity = -units if position.get("is_buy") is False else units
        market_price = _as_float(position.get("current_rate"))
        native_value = _native_market_value(position, quantity, market_price)
        market_value = (
            native_value * to_eur
            if native_value is not None and to_eur is not None
            else native_value
        )
        leverage = _as_float(position.get("leverage"))
        if native_value is None:
            missing_value_symbols.append(str(symbol or name))

        holdings.append(
            Holding(
                symbol=symbol,
                name=name,
                asset_type=_asset_type_from(position.get("instrument_type")),
                currency=account_currency,
                quantity=quantity,
                market_price=market_price,
                market_value=float(market_value) if market_value is not None else 0.0,
                leverage=leverage if leverage is not None else 1.0,
            )
        )

    portfolio = Portfolio(holdings=holdings, base_currency=base_currency, source="etoro_api")

    cash_native = _as_float(account.get("cash_available"))
    cash_available_eur: float | None = None
    if cash_native is not None and to_eur is not None:
        cash_available_eur = cash_native * to_eur

    return portfolio, cash_available_eur, missing_value_symbols
