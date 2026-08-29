"""Chain multiple market-data providers so a rate limit or outage on one does not take down
stock analysis entirely.

``FallbackMarketData`` tries each provider in the given order and keeps the first
snapshot that counts as a "success" (has a price, unless ``min_price_required=False``).
Every provider that was tried and rejected -- because it raised, or because it returned no
price -- is recorded in the winning snapshot's ``provenance.secondary_sources`` so callers
and tests can see what was attempted. If every provider fails, the accumulated attempts are
raised as a single ``ValueError``.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from portfolio_copilot.models import StockSnapshot


def _provider_name(provider: Any) -> str:
    return getattr(provider, "source_name", type(provider).__name__)


class FallbackMarketData:
    def __init__(self, providers: list[Any], min_price_required: bool = True) -> None:
        self.providers = list(providers)
        self.min_price_required = min_price_required

    @property
    def source_name(self) -> str:
        """Chained providers' names, for call sites that expect one provider object to
        carry a single ``source_name`` (e.g. a report that says where a price came from)."""
        return "+".join(_provider_name(p) for p in self.providers)

    def get_stock_snapshot(self, ticker: str) -> StockSnapshot:
        """Return the first provider's snapshot that has a price (or the first snapshot at
        all, when ``min_price_required`` is False); raise ``ValueError`` listing every
        attempt if none qualifies."""
        attempts: list[str] = []
        for provider in self.providers:
            name = _provider_name(provider)
            try:
                snapshot = provider.get_stock_snapshot(ticker)
            except Exception as exc:
                attempts.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            if self.min_price_required and snapshot.price is None:
                attempts.append(f"{name}: no price")
                continue
            snapshot.provenance.secondary_sources = [
                *attempts,
                *snapshot.provenance.secondary_sources,
            ]
            return snapshot

        symbol = ticker.strip().upper()
        detail = "; ".join(attempts) if attempts else "no providers configured"
        raise ValueError(f"All market data providers failed for {symbol}: {detail}")

    def get_monthly_closes(self, tickers: dict[str, str], period: str = "5y") -> pd.DataFrame:
        """Delegate to the first provider that both implements ``get_monthly_closes`` and
        returns a non-empty frame for it; a provider that raises or has nothing is skipped."""
        for provider in self.providers:
            getter = getattr(provider, "get_monthly_closes", None)
            if getter is None:
                continue
            try:
                df = getter(tickers, period=period)
            except Exception:
                continue
            if isinstance(df, pd.DataFrame) and not df.empty:
                return df
        empty = pd.DataFrame()
        empty.attrs["missing"] = list(tickers)
        empty.attrs["source"] = "fallback"
        return empty
