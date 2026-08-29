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


# Exact finvizfinance "Market Cap." option strings (finvizfinance.constants.filter_dict).
# Used to sample every size bucket -- discovery never excludes by size.
SIZE_BUCKETS: dict[str, str] = {
    "mega": "Mega ($200bln and more)",
    "large": "Large ($10bln to $200bln)",
    "mid": "Mid ($2bln to $10bln)",
    "small": "Small ($300mln to $2bln)",
    "micro": "Micro ($50mln to $300mln)",
    "nano": "Nano (under $50mln)",
}

# Exact finvizfinance order names (finvizfinance.constants.order_dict) used to rank each
# style's screen before truncating to per_screen. One entry per PRESETS key.
STYLE_ORDER: dict[str, str] = {
    "quality_growth": "EPS growth this year",
    "quality_value": "Return on Equity",
    "momentum": "Performance (Quarter)",
}

_UNIVERSE_COLUMNS = ("Ticker", "Company", "Sector", "Industry", "Market Cap")


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
            df = screener.screener_view(
                order=STYLE_ORDER[preset], ascend=False, limit=limit, verbose=0
            )
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
        # A transient scrape failure is not "Finviz has nothing here" -- caching it would
        # block discovery for the full TTL after one blip. Only successful screens are cached.
        if result["ok"]:
            self._cache.set(key, result)
        return result

    def discover_universe(
        self,
        styles: tuple[str, ...] = ("quality_growth", "quality_value", "momentum"),
        sizes: tuple[str, ...] = ("mega", "large", "mid", "small", "micro", "nano"),
        per_screen: int = 15,
        screener_factory=None,
    ) -> dict:
        """Sample the whole market across size buckets and styles. No exclusions.

        Runs one preset screen per (style, size) pair with ``Market Cap.`` overridden to
        the size bucket, then unions candidates by ticker across all of them: a name
        found by more than one screen keeps a single entry with every style that hit it
        listed in ``styles_hit``. Size, style and index overlap are information here,
        never filters -- nothing is dropped for being big, small, or already owned.

        A screen that raises (network error, site change) is recorded in
        ``screens_failed`` and skipped; the rest still run. An empty-but-valid screen
        (no matches) is not a failure. Every candidate must still be re-scored by
        ``analyze_stock`` -- Finviz numbers never enter the score.
        """
        unknown_styles = [s for s in styles if s not in PRESETS or s not in STYLE_ORDER]
        if unknown_styles:
            raise ValueError(f"Unknown style(s) {unknown_styles}. Available: {sorted(STYLE_ORDER)}")
        unknown_sizes = [s for s in sizes if s not in SIZE_BUCKETS]
        if unknown_sizes:
            raise ValueError(f"Unknown size(s) {unknown_sizes}. Available: {sorted(SIZE_BUCKETS)}")
        if per_screen <= 0:
            raise ValueError("per_screen must be > 0")

        key = f"universe:{':'.join(styles)}|{':'.join(sizes)}|{per_screen}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached

        factory = screener_factory or self._screener_factory
        candidates: dict[str, dict] = {}
        screens_failed: list[dict] = []
        screens_run = 0

        for style in styles:
            for size in sizes:
                screens_run += 1
                filters = {**PRESETS[style], "Market Cap.": SIZE_BUCKETS[size]}
                try:
                    screener = factory()
                    screener.set_filter(filters_dict=filters)
                    df = screener.screener_view(
                        order=STYLE_ORDER[style], ascend=False, limit=per_screen, verbose=0
                    )
                except Exception as exc:  # one bad screen must not abort the sampler
                    screens_failed.append(
                        {"style": style, "size": size, "error": f"{type(exc).__name__}: {exc}"}
                    )
                    continue
                if not isinstance(df, pd.DataFrame) or df.empty or "Ticker" not in df.columns:
                    continue
                keep = [c for c in _UNIVERSE_COLUMNS if c in df.columns]
                for row in df[keep].head(per_screen).to_dict(orient="records"):
                    ticker = row.get("Ticker")
                    if pd.isna(ticker) or not ticker:
                        continue
                    clean = {k: (None if pd.isna(v) else v) for k, v in row.items()}
                    existing = candidates.get(ticker)
                    if existing is None:
                        clean["size_bucket"] = size
                        clean["styles_hit"] = [style]
                        candidates[ticker] = clean
                    elif style not in existing["styles_hit"]:
                        existing["styles_hit"].append(style)

        result = {
            "ok": len(screens_failed) < screens_run,
            "candidates": list(candidates.values()),
            "screens_run": screens_run,
            "screens_failed": screens_failed,
            "source": self.source_name,
            "tier": self.tier,
            "as_of": datetime.now(UTC).isoformat(),
            "note": (
                "Universe sample across sizes and styles; nothing excluded; "
                "re-score with analyze_stock"
            ),
        }
        # A fully-failed sample (every screen raised, e.g. a transient scrape blip) is not
        # cached: caching it would block discovery for the full TTL instead of letting the
        # next call retry. A partial or fully-successful sample IS cached as before.
        if result["ok"]:
            self._cache.set(key, result)
        return result
