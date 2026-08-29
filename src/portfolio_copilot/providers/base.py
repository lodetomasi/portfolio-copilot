from __future__ import annotations

from typing import Protocol

import pandas as pd

from portfolio_copilot.models import StockSnapshot


class MarketDataProvider(Protocol):
    def get_stock_snapshot(self, ticker: str) -> StockSnapshot: ...

    def get_monthly_closes(self, tickers: dict[str, str], period: str = "5y") -> pd.DataFrame:
        """Monthly close prices, one column per key of ``tickers`` (bucket -> ticker)."""
        ...
