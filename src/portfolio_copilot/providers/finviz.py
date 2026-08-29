"""Finviz screener via the open-source ``finvizfinance`` crawler (public pages, no account).

Tier C source: used only for DISCOVERY (turn "no idea what to buy" into a shortlist).
Every candidate is then re-scored from Yahoo/SEC data; Finviz numbers never enter the score.
Presets are validated offline against finvizfinance's filter catalogue.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
from finvizfinance.screener.overview import Overview

from portfolio_copilot.providers.cache import TTLCache

# Finviz filter labels/options are the library's own strings (finvizfinance.constants).
PRESETS: dict[str, dict[str, str]] = {
    "quality_growth": {
        "Market Cap.": "+Mid (over $2bln)",
        "Sales growthpast 5 years": "Over 10%",
        "EPS growththis year": "Positive (>0%)",
        "Debt/Equity": "Under 1",
        "Return on Equity": "Positive (>0%)",
        "Average Volume": "Over 500K",
        "200-Day Simple Moving Average": "Price above SMA200",
    },
    "quality_value": {
        "Market Cap.": "+Mid (over $2bln)",
        "Forward P/E": "Under 20",
        "Debt/Equity": "Under 1",
        "Operating Margin": "Positive (>0%)",
        "Return on Equity": "Positive (>0%)",
        "Average Volume": "Over 500K",
    },
    "momentum": {
        "Market Cap.": "+Small (over $300mln)",
        "Average Volume": "Over 500K",
        "200-Day Simple Moving Average": "Price 10% above SMA200",
        "EPS growththis year": "Over 10%",
        "Sales growthqtr over qtr": "Over 10%",
    },
}


def validate_preset(filters: dict[str, str]) -> None:
    """Raise ValueError if a label/option is unknown to finvizfinance (offline check)."""
    Overview().set_filter(filters_dict=filters)


class FinvizProvider:
    source_name = "finviz"
    tier = "C"

    def __init__(self, ttl_seconds: float = 6 * 3600, screener_factory=Overview) -> None:
        self._cache = TTLCache(ttl_seconds)
        self._screener_factory = screener_factory

    def screen(self, preset: str = "quality_growth", limit: int = 50) -> dict:
        """Run a preset screen. Returns tickers plus the columns Finviz shows in its overview."""
        if preset not in PRESETS:
            raise ValueError(f"Unknown preset '{preset}'. Available: {sorted(PRESETS)}")
        if limit <= 0:
            raise ValueError("limit must be > 0")
        key = f"{preset}:{limit}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        try:
            screener = self._screener_factory()
            screener.set_filter(filters_dict=PRESETS[preset])
            df = screener.screener_view(order="Market Cap.", ascend=False, limit=limit, verbose=0)
        except Exception as exc:  # tier-C HTML scraper: network error or site layout change
            df = None
            scrape_error = f"{type(exc).__name__}: {exc}"
        else:
            scrape_error = None
        if scrape_error is not None:
            result = {
                "ok": False,
                "preset": preset,
                "filters": PRESETS[preset],
                "candidates": [],
                "error": f"Finviz scraper call failed: {scrape_error}",
            }
        elif not isinstance(df, pd.DataFrame) or df.empty or "Ticker" not in df.columns:
            result = {
                "ok": False,
                "preset": preset,
                "filters": PRESETS[preset],
                "candidates": [],
                "error": "Finviz returned no rows (site change, rate limit or empty screen)",
            }
        else:
            wanted = ("Ticker", "Company", "Sector", "Industry", "Country", "Market Cap", "P/E",
                      "Price", "Change", "Volume")
            keep = [c for c in wanted if c in df.columns]
            rows = df[keep].head(limit).to_dict(orient="records")
            result = {
                "ok": True,
                "preset": preset,
                "filters": PRESETS[preset],
                "candidates": [
                    {k: (None if pd.isna(v) else v) for k, v in r.items()} for r in rows
                ],
            }
        result.update(
            {
                "source": self.source_name,
                "tier": self.tier,
                "as_of": datetime.now(UTC).isoformat(),
                "note": "Discovery only. Re-score candidates with analyze_stock before deciding.",
            }
        )
        self._cache.set(key, result)
        return result
