"""Server-level tests for the portfolio_exposure MCP tool's wiring: the only
provider-touching tool in server.py that discarded the fetched snapshot's provenance
(source/as_of/confidence) instead of surfacing it -- CLAUDE.md rule 5.
"""

from __future__ import annotations

from datetime import UTC, datetime

import portfolio_copilot.server as server
from portfolio_copilot.models import Holding, Portfolio, Provenance, StockSnapshot


def _snapshot(ticker: str, **overrides) -> StockSnapshot:
    data = dict(
        ticker=ticker,
        sector="Technology",
        industry="Semiconductors",
        provenance=Provenance(
            source="yahooquery-fallback", as_of=datetime.now(UTC), confidence=0.35,
        ),
    )
    data.update(overrides)
    return StockSnapshot(**data)


def test_portfolio_exposure_surfaces_sector_provenance(monkeypatch):
    portfolio = Portfolio(
        holdings=[
            Holding(symbol="AMD", name="Advanced Micro Devices", asset_type="equity",
                    market_value=1_000.0),
        ]
    )
    monkeypatch.setattr(server, "_parse_export", lambda path, base_currency="EUR": portfolio)
    monkeypatch.setattr(
        server.provider, "get_stock_snapshot", lambda symbol: _snapshot(symbol)
    )
    result = server.portfolio_exposure(path="dummy.csv")
    assert "sector_provenance" in result
    assert result["sector_provenance"]["AMD"]["source"] == "yahooquery-fallback"
    assert result["sector_provenance"]["AMD"]["confidence"] == 0.35
