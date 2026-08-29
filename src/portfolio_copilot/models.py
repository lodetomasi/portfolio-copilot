from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AssetType(StrEnum):
    EQUITY = "equity"
    ETF = "etf"
    CERTIFICATE = "certificate"
    BOND = "bond"
    CASH = "cash"
    OTHER = "other"


class Decision(StrEnum):
    BUY = "BUY"
    BUY_SMALL = "BUY_SMALL"
    HOLD = "HOLD"
    WATCH = "WATCH"
    REDUCE = "REDUCE"
    SELL = "SELL"
    NO_BUY = "NO_BUY"


class Holding(BaseModel):
    symbol: str | None = None
    isin: str | None = None
    name: str
    asset_type: AssetType = AssetType.OTHER
    currency: str = "EUR"
    quantity: float = 0.0
    avg_cost: float | None = None
    market_price: float | None = None
    market_value: float
    pnl_value: float | None = None
    pnl_pct: float | None = None
    leverage: float = 1.0
    sector: str | None = None
    bucket: str | None = None


class Portfolio(BaseModel):
    holdings: list[Holding]
    base_currency: str = "EUR"
    source: str = "broker_export"

    @property
    def total_value(self) -> float:
        return float(sum(h.market_value for h in self.holdings))


class Provenance(BaseModel):
    source: str
    as_of: datetime
    confidence: float = Field(ge=0.0, le=1.0)
    missing_fields: list[str] = Field(default_factory=list)
    tier: str | None = None  # A official (SEC, ECB) / B aggregator (Yahoo) / C crawler (Finviz)
    overrides: list[str] = Field(default_factory=list)  # "field: tierA source replaces tierB"
    secondary_sources: list[str] = Field(default_factory=list)


class StockSnapshot(BaseModel):
    ticker: str
    currency: str | None = None
    price: float | None = None
    market_cap: float | None = None

    revenue_growth: float | None = None
    earnings_growth: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    free_cashflow: float | None = None
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    roe: float | None = None

    trailing_pe: float | None = None
    forward_pe: float | None = None
    price_to_sales: float | None = None
    enterprise_to_ebitda: float | None = None

    ret_1m: float | None = None
    ret_3m: float | None = None
    ret_6m: float | None = None
    ret_12m: float | None = None
    vol_1y: float | None = None
    max_drawdown_1y: float | None = None
    distance_52w_high: float | None = None
    above_sma50: bool | None = None
    above_sma200: bool | None = None

    sector: str | None = None
    industry: str | None = None

    # Analyst estimates / revisions (free-data proxies -- see ARCHITECTURE.md).
    est_eps_growth_1y: float | None = None
    est_revenue_growth_1y: float | None = None
    eps_revisions_up_30d: int | None = None
    eps_revisions_down_30d: int | None = None
    revision_balance: float | None = None
    analyst_count: int | None = None
    consensus_score: float | None = None
    target_upside: float | None = None
    revision_net_90d: int | None = None  # net analyst upgrades minus downgrades, event-dated
    revision_pt_change_90d: float | None = None

    # Catalysts / event density.
    days_to_next_earnings: int | None = None
    insider_form4_90d: int | None = None
    filings_8k_90d: int | None = None
    surprise_mean_8q: float | None = None
    surprise_positive_share_8q: float | None = None
    surprise_streak: int | None = None

    provenance: Provenance


class ScoreComponent(BaseModel):
    name: str
    score: float = Field(ge=0.0, le=100.0)
    weight: float = Field(gt=0)
    available: bool = True
    reasons: list[str] = Field(default_factory=list)


class StockScore(BaseModel):
    ticker: str
    score: float = Field(ge=0.0, le=100.0)
    confidence: float = Field(ge=0.0, le=1.0)
    category: str
    components: list[ScoreComponent]
    reasons: list[str] = Field(default_factory=list)
    snapshot: StockSnapshot | None = None


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class SuggestedOrder(BaseModel):
    symbol: str
    side: OrderSide
    value_eur: float
    estimated_fee_eur: float
    fee_ratio: float
    reason: str


class ToolEnvelope(BaseModel):
    ok: bool = True
    data: Any = None
    warnings: list[str] = Field(default_factory=list)
