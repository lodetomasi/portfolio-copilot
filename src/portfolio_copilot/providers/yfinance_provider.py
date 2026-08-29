from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import yfinance as yf

from portfolio_copilot.analytics.metrics import annualized_volatility, max_drawdown, pct_return
from portfolio_copilot.models import Provenance, StockSnapshot
from portfolio_copilot.providers.cache import TTLCache


def _f(value):
    if value is None:
        return None
    try:
        value = float(value)
        return value if np.isfinite(value) else None
    except (TypeError, ValueError):
        return None


class YFinanceProvider:
    source_name = "yfinance"

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self._cache = TTLCache(ttl_seconds)

    def get_monthly_closes(self, tickers: dict[str, str], period: str = "5y") -> pd.DataFrame:
        """Monthly adjusted closes, one column per bucket, aligned to calendar month so
        tickers on different exchanges/timezones (e.g. a EUR-base mix of US stocks and
        European UCITS ETFs, which rarely share a trading day or timestamp) still combine
        into usable rows. Buckets whose ticker returns no data, or whose fetch raises
        (rate limit, delisting, network error), are dropped and listed in
        ``df.attrs["missing"]`` so callers can degrade. Per-ticker results are cached
        (TTL cache, same pattern as the other providers) so repeated calls for the same
        ticker/period within one session don't re-hit Yahoo."""
        frames: dict[str, pd.Series] = {}
        missing: list[str] = []
        for bucket, ticker in tickers.items():
            cache_key = f"monthly:{ticker.strip().upper()}:{period}"
            cached = self._cache.get(cache_key)
            if cached is not None:
                frames[bucket] = cached
                continue
            try:
                hist = yf.Ticker(ticker).history(period=period, interval="1mo", auto_adjust=True)
            except Exception:
                missing.append(bucket)
                continue
            if not (isinstance(hist, pd.DataFrame) and "Close" in hist.columns and not hist.empty):
                missing.append(bucket)
                continue
            closes = hist["Close"].dropna()
            index = pd.DatetimeIndex(closes.index)
            if index.tz is not None:
                index = index.tz_localize(None)
            closes.index = index.to_period("M").to_timestamp("M")
            frames[bucket] = closes
            self._cache.set(cache_key, closes)
        df = pd.DataFrame(frames).dropna()
        df.attrs["missing"] = missing
        df.attrs["source"] = self.source_name
        df.attrs["as_of"] = datetime.now(UTC).isoformat()
        return df

    def get_stock_snapshot(self, ticker: str) -> StockSnapshot:
        symbol = ticker.strip().upper()
        if not symbol:
            raise ValueError("Ticker is required")

        cache_key = f"snapshot:{symbol}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            info, hist = cached
        else:
            t = yf.Ticker(symbol)
            info = t.info or {}
            hist = t.history(period="1y", auto_adjust=True)
            self._cache.set(cache_key, (info, hist))

        has_close = isinstance(hist, pd.DataFrame) and "Close" in hist.columns
        price_series = hist["Close"] if has_close else pd.Series(dtype=float)
        missing: list[str] = []

        def val(key: str):
            out = info.get(key)
            if out is None:
                missing.append(key)
            return out

        current_price = (
            _f(info.get("currentPrice"))
            or _f(info.get("regularMarketPrice"))
            or (_f(price_series.iloc[-1]) if not price_series.empty else None)
        )
        if current_price is None:
            missing.append("price")

        sma50 = _f(info.get("fiftyDayAverage"))
        sma200 = _f(info.get("twoHundredDayAverage"))
        high52 = _f(info.get("fiftyTwoWeekHigh"))

        snapshot = StockSnapshot(
            ticker=symbol,
            currency=info.get("currency"),
            price=current_price,
            market_cap=_f(val("marketCap")),
            revenue_growth=_f(val("revenueGrowth")),
            earnings_growth=_f(val("earningsGrowth")),
            gross_margin=_f(val("grossMargins")),
            operating_margin=_f(val("operatingMargins")),
            free_cashflow=_f(val("freeCashflow")),
            debt_to_equity=_f(val("debtToEquity")),
            current_ratio=_f(val("currentRatio")),
            roe=_f(val("returnOnEquity")),
            trailing_pe=_f(val("trailingPE")),
            forward_pe=_f(val("forwardPE")),
            price_to_sales=_f(val("priceToSalesTrailing12Months")),
            enterprise_to_ebitda=_f(val("enterpriseToEbitda")),
            ret_1m=pct_return(price_series, 21),
            ret_3m=pct_return(price_series, 63),
            ret_6m=pct_return(price_series, 126),
            ret_12m=pct_return(price_series, 250),
            vol_1y=annualized_volatility(price_series),
            max_drawdown_1y=max_drawdown(price_series),
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
            sector=info.get("sector"),
            industry=info.get("industry"),
            provenance=Provenance(
                source=self.source_name,
                as_of=datetime.now(UTC),
                confidence=0.75 if current_price is not None else 0.35,
                missing_fields=sorted(set(missing)),
            ),
        )
        return snapshot
