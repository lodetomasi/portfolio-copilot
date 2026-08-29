"""Stooq end-of-day price history (free CSV, no key). Fallback when yfinance has no data."""

from __future__ import annotations

import io
import logging
from datetime import UTC, datetime

import httpx
import pandas as pd

from portfolio_copilot.providers.cache import TTLCache

logger = logging.getLogger(__name__)

STOOQ_URL = "https://stooq.com/q/d/l/?s={symbol}&i={interval}"


def parse_stooq_csv(text: str) -> pd.Series:
    """Close series indexed by date. Raises on Stooq's 'No data' answer or empty payload."""
    if not text.strip() or text.strip().lower().startswith("no data"):
        raise ValueError("Stooq returned no data")
    df = pd.read_csv(io.StringIO(text))
    if "Date" not in df.columns or "Close" not in df.columns:
        raise ValueError(f"Stooq CSV without Date/Close columns: {list(df.columns)}")
    df["Date"] = pd.to_datetime(df["Date"])
    return df.set_index("Date")["Close"].astype(float).dropna()


class StooqProvider:
    source_name = "stooq"

    def __init__(self, timeout: float = 10.0, ttl_seconds: float = 6 * 3600) -> None:
        self.timeout = timeout
        self._cache = TTLCache(ttl_seconds)

    def get_closes(self, symbol: str, interval: str = "m") -> pd.Series:
        key = f"{symbol.lower()}:{interval}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        response = httpx.get(
            STOOQ_URL.format(symbol=symbol.lower(), interval=interval),
            timeout=self.timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
        series = parse_stooq_csv(response.text)
        self._cache.set(key, series)
        return series

    def get_monthly_closes(self, tickers: dict[str, str], period: str = "5y") -> pd.DataFrame:
        """Same contract as YFinanceProvider.get_monthly_closes (period 'Ny' or 'max')."""
        frames: dict[str, pd.Series] = {}
        missing: list[str] = []
        for bucket, symbol in tickers.items():
            try:
                frames[bucket] = self.get_closes(symbol, interval="m")
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning(
                    "Stooq fetch failed for bucket=%s symbol=%s: %s", bucket, symbol, exc
                )
                missing.append(bucket)
        df = pd.DataFrame(frames).dropna()
        normalized_period = period.strip().lower()
        if normalized_period != "max" and not df.empty:
            try:
                years = int(normalized_period.rstrip("y"))
            except ValueError:
                years = None
            if years is not None:
                df = df[df.index >= df.index.max() - pd.DateOffset(years=years)]
        df.attrs.update(
            {"missing": missing, "source": self.source_name, "as_of": datetime.now(UTC).isoformat()}
        )
        return df
