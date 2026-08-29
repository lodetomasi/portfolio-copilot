"""Second free market-data source, backed by the ``yahooquery`` package.

Mirrors the normalisation approach of ``providers/yfinance_provider.py`` (the same ``_f``
coercion helper, the same ``missing_fields``/``Provenance`` shape) but sources fields from
yahooquery's ``price``, ``summary_detail``, ``financial_data`` and ``key_stats``
(``defaultKeyStatistics``) quoteSummary modules. Used as a fallback when yfinance is
rate-limited or returns no price -- see ``providers/fallback.py``.

No momentum/history fields are populated (they would require a separate historical-prices
call); ``above_sma50``/``above_sma200``/``distance_52w_high`` are derived cheaply from the
50/200-day averages and 52-week high already present in the ``summary_detail`` payload.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import numpy as np
from yahooquery import Ticker

from portfolio_copilot.models import Provenance, StockSnapshot
from portfolio_copilot.providers.cache import TTLCache


def _f(value: Any) -> float | None:
    if value is None:
        return None
    try:
        value = float(value)
        return value if np.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _module_dict(modules: Any, symbol: str) -> dict[str, Any]:
    """yahooquery returns ``{symbol: {...fields...}}`` on success, or ``{symbol: "<error
    string>"}`` when the symbol/module lookup fails (e.g. "Quote not found for symbol: X").
    Normalise the failure case to an empty dict so field extraction stays uniform."""
    value = modules.get(symbol) if isinstance(modules, dict) else None
    return value if isinstance(value, dict) else {}


class YahooQueryProvider:
    source_name = "yahooquery"

    def __init__(
        self,
        ttl_seconds: float = 300.0,
        timeout: float = 8.0,
        ticker_factory: Callable[..., Any] = Ticker,
    ) -> None:
        self._cache = TTLCache(ttl_seconds)
        self._timeout = timeout
        self._ticker_factory = ticker_factory

    def get_stock_snapshot(self, ticker: str) -> StockSnapshot:
        symbol = ticker.strip().upper()
        if not symbol:
            raise ValueError("Ticker is required")

        cache_key = f"snapshot:{symbol}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            price_mod, summary_mod, financial_mod, keystats_mod = cached
        else:
            try:
                t = self._ticker_factory(symbol, timeout=self._timeout)
                price_mod = _module_dict(t.price, symbol)
                summary_mod = _module_dict(t.summary_detail, symbol)
                financial_mod = _module_dict(t.financial_data, symbol)
                keystats_mod = _module_dict(t.key_stats, symbol)
            except Exception as exc:
                raise ValueError(f"yahooquery lookup failed for {symbol}: {exc}") from exc
            self._cache.set(cache_key, (price_mod, summary_mod, financial_mod, keystats_mod))

        missing: list[str] = []

        def val(source: dict[str, Any], key: str) -> Any:
            out = source.get(key)
            if out is None:
                missing.append(key)
            return out

        current_price = _f(financial_mod.get("currentPrice")) or _f(
            price_mod.get("regularMarketPrice")
        )
        if current_price is None:
            missing.append("price")

        sma50 = _f(summary_mod.get("fiftyDayAverage"))
        sma200 = _f(summary_mod.get("twoHundredDayAverage"))
        high52 = _f(summary_mod.get("fiftyTwoWeekHigh"))

        snapshot = StockSnapshot(
            ticker=symbol,
            currency=price_mod.get("currency"),
            price=current_price,
            market_cap=_f(val(price_mod, "marketCap")),
            revenue_growth=_f(val(financial_mod, "revenueGrowth")),
            earnings_growth=_f(val(financial_mod, "earningsGrowth")),
            gross_margin=_f(val(financial_mod, "grossMargins")),
            operating_margin=_f(val(financial_mod, "operatingMargins")),
            free_cashflow=_f(val(financial_mod, "freeCashflow")),
            debt_to_equity=_f(val(financial_mod, "debtToEquity")),
            current_ratio=_f(val(financial_mod, "currentRatio")),
            roe=_f(val(financial_mod, "returnOnEquity")),
            trailing_pe=_f(val(summary_mod, "trailingPE")),
            forward_pe=_f(val(summary_mod, "forwardPE")),
            price_to_sales=_f(val(summary_mod, "priceToSalesTrailing12Months")),
            enterprise_to_ebitda=_f(val(keystats_mod, "enterpriseToEbitda")),
            distance_52w_high=(
                (current_price / high52 - 1.0)
                if current_price is not None and high52 not in (None, 0)
                else None
            ),
            above_sma50=(
                current_price > sma50
                if current_price is not None and sma50 is not None
                else None
            ),
            above_sma200=(
                current_price > sma200
                if current_price is not None and sma200 is not None
                else None
            ),
            provenance=Provenance(
                source=self.source_name,
                as_of=datetime.now(UTC),
                confidence=0.7 if current_price is not None else 0.3,
                missing_fields=sorted(set(missing)),
                tier="B",
            ),
        )
        return snapshot
