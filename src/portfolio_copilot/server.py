from __future__ import annotations

import json
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated

import httpx
import pandas as pd
import yfinance as yf
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import Field, ValidationError

from portfolio_copilot.analytics.merge import apply_evidence_report, apply_official_overrides
from portfolio_copilot.models import AssetType, StockSnapshot
from portfolio_copilot.parsers.broker_export import parse_portfolio_export as _parse_export
from portfolio_copilot.portfolio import auction as auction_module
from portfolio_copilot.portfolio import edge as edge_module
from portfolio_copilot.portfolio import exposure as exposure_module
from portfolio_copilot.portfolio import opportunity as opportunity_module
from portfolio_copilot.portfolio import picker as picker_module
from portfolio_copilot.portfolio import picker_backtest as picker_backtest_module
from portfolio_copilot.portfolio import quality as quality_module
from portfolio_copilot.portfolio import replacement as replacement_module
from portfolio_copilot.portfolio import snapshots as snapshots_module
from portfolio_copilot.portfolio import thesis as thesis_module
from portfolio_copilot.portfolio.backtest import simulate_cash_flow_plan
from portfolio_copilot.portfolio.config import load_portfolio_config as _load_portfolio_config
from portfolio_copilot.portfolio.ledger import (
    evaluate_decisions,
    load_decisions,
    record_decision,
)
from portfolio_copilot.portfolio.mapping import map_holdings as _map_holdings
from portfolio_copilot.portfolio.plan import build_investment_plan as _build_plan
from portfolio_copilot.portfolio.plan import load_model_portfolios as _load_model_portfolios
from portfolio_copilot.portfolio.rebalance import FeeModel, allocate_cash_to_targets
from portfolio_copilot.portfolio.risk import summarize_portfolio_risk
from portfolio_copilot.providers import macro as macro_module
from portfolio_copilot.providers import sec_edgar as sec_edgar_module
from portfolio_copilot.providers import sec_filings as sec_filings_module
from portfolio_copilot.providers import yfinance_estimates as estimates_module
from portfolio_copilot.providers import yfinance_surprises as surprises_module
from portfolio_copilot.providers.ecb_fx import ECBFXProvider, convert_to_eur
from portfolio_copilot.providers.ecb_rates import ECBRatesProvider
from portfolio_copilot.providers.eurostat import EurostatProvider
from portfolio_copilot.providers.fallback import FallbackMarketData
from portfolio_copilot.providers.finviz import PRESETS, FinvizProvider
from portfolio_copilot.providers.investor_relations import ALL_IR_KINDS, IRProvider
from portfolio_copilot.providers.openfigi import EXCHANGE_TO_YF_SUFFIX, OpenFIGIProvider
from portfolio_copilot.providers.sec_edgar import SECEdgarProvider
from portfolio_copilot.providers.stooq import StooqProvider
from portfolio_copilot.providers.yahooquery_provider import YahooQueryProvider
from portfolio_copilot.providers.yfinance_provider import YFinanceProvider
from portfolio_copilot.scoring.engine import score_snapshot

mcp = MCPServer("portfolio-copilot")
# Fallback chain: try yfinance first, fall back to yahooquery on a rate limit/outage.
# Kept as separate module-level names (not just list items) so tests can monkeypatch each
# provider's internals directly -- see tests/test_provider_resilience.py.
_yfinance_provider = YFinanceProvider()
_yahooquery_provider = YahooQueryProvider()
provider = FallbackMarketData([_yfinance_provider, _yahooquery_provider])
fx_provider = ECBFXProvider()
sec_provider = SECEdgarProvider()
stooq_provider = StooqProvider()
finviz_provider = FinvizProvider()
eurostat_provider = EurostatProvider()
ecb_rates_provider = ECBRatesProvider()
ir_provider = IRProvider()
openfigi_provider = OpenFIGIProvider()

# STABLE/STRENGTHENING theses are healthy; WEAKENING/BROKEN discount utility; a thesis that
# was never checked, or came back UNVERIFIABLE, is treated as mildly-but-not-fully healthy
# rather than a hard penalty -- CLAUDE.md rule 6 says degrade, not invent a worse verdict.
_THESIS_HEALTH: dict[str, float] = {
    "STRENGTHENING": 1.0,
    "STABLE": 1.0,
    "UNVERIFIABLE": 0.8,
    "WEAKENING": 0.6,
    "BROKEN": 0.2,
}


def _thesis_health(status: str | None) -> float:
    """Map a stored thesis's last check status to a 0..1 utility multiplier. No thesis on
    file is treated as neutral (1.0): absence of a thesis is not evidence of one broken."""
    if status is None:
        return 1.0
    return _THESIS_HEALTH.get(status, 1.0)


# Used only when a real user config exists but genuinely omits risk_limits (or
# max_single_stock_weight within it) -- CLAUDE.md rule 6 forbids inventing "no limit"
# (1.0) for missing data, so a conservative default is used instead, matching the tracked
# config/portfolio.example.yaml.
_DEFAULT_STOCK_CAP_WEIGHT = 0.05


def _clamp_weight(value: float) -> float:
    """Clamp a computed current_weight ratio into Candidate's valid [0, 1] range.

    A holding's market_value is not guaranteed non-negative (margin debt, a short
    position, an atypical export row), so the raw ``current_value / total_value`` ratio
    can fall outside [0, 1] even when ``total_value`` itself is positive -- clamp rather
    than let a downstream Candidate(...) raise an unhandled pydantic.ValidationError."""
    return max(0.0, min(1.0, value))


def _stock_cap_weight(cfg: dict) -> float:
    """Per-stock weight cap from ``cfg['risk_limits']['max_single_stock_weight']``,
    degrading to a conservative default rather than "no limit" when the section (or the
    key) is missing."""
    risk_limits = cfg.get("risk_limits") or {}
    return risk_limits.get("max_single_stock_weight", _DEFAULT_STOCK_CAP_WEIGHT)


def _fee_model_from_config(cfg: dict) -> FeeModel:
    """Build a FeeModel from get_portfolio_config()'s ``fees`` section, falling back to
    FeeModel's own defaults for whatever the user's config does not define."""
    fees = cfg.get("fees") or {}
    defaults = FeeModel()
    return FeeModel(
        fixed_fee_eur=fees.get("default_fixed_fee_eur", defaults.fixed_fee_eur),
        variable_fee_pct=fees.get("variable_fee_pct", defaults.variable_fee_pct),
        max_fee_ratio=fees.get("max_fee_ratio", defaults.max_fee_ratio),
    )

# Shared parameter annotations: current_values and targets look identical
# (dict[str, float]) but hold different units. Documented at the schema level so a
# model driving these tools cold sees the constraint, not just via a runtime error.
CurrentValues = Annotated[
    dict[str, float], Field(description="bucket/symbol -> current absolute value in EUR")
]
Targets = Annotated[
    dict[str, float],
    Field(
        description="bucket/symbol -> target weight as a fraction of 1.0; values must sum to 1.0"
    ),
]


@mcp.tool()
def parse_portfolio_export(
    path: Annotated[str, Field(description="Path to a local broker portfolio export (CSV/XLSX)")],
    base_currency: str = "EUR",
) -> dict:
    """Parse and normalize a local broker portfolio export. Never accesses any broker online."""
    try:
        portfolio = _parse_export(path, base_currency=base_currency)
    except (FileNotFoundError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    return portfolio.model_dump(mode="json")


@mcp.tool()
def get_portfolio_config(path: str | None = None) -> dict:
    """Load targets, fees, risk_limits and rebalancing rules from config/portfolio.yaml.
    Falls back to the tracked config/portfolio.example.yaml when the user has not created
    their own file yet (flagged via `is_example`: say so before using those numbers as if
    they were the user's). Never invents or guesses these numbers."""
    try:
        return _load_portfolio_config(path)
    except FileNotFoundError as exc:
        raise ToolError(str(exc)) from exc


def _snapshot_with_official_data(
    ticker: str, cross_check_sec: bool
) -> tuple[StockSnapshot, dict | None]:
    """Yahoo snapshot (tier B) with audited SEC facts (tier A) applied on top when available.

    Returns the snapshot plus the raw SEC facts dict used for the overrides (``None`` when
    ``cross_check_sec`` is False), so a caller needing evidence reconciliation
    (``apply_evidence_report``) does not have to re-fetch SEC data.
    """
    snapshot = provider.get_stock_snapshot(ticker)
    if not cross_check_sec:
        return apply_official_overrides(snapshot, None), None
    try:
        facts = sec_provider.get_company_facts(ticker)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        facts = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return apply_official_overrides(snapshot, facts), facts


# StockSnapshot fields fillable from providers.yfinance_estimates.AnalystEstimates -- the
# subset the two models share by name (see that module's WORK PACKAGE NOTES: two fields,
# next_earnings_date/revision_events_90d, have no snapshot counterpart and are dropped here).
_ESTIMATE_SNAPSHOT_FIELDS = (
    "est_eps_growth_1y",
    "est_revenue_growth_1y",
    "eps_revisions_up_30d",
    "eps_revisions_down_30d",
    "revision_balance",
    "analyst_count",
    "consensus_score",
    "target_upside",
    "revision_net_90d",
    "revision_pt_change_90d",
    "days_to_next_earnings",
)


def _enrich_snapshot_with_free_data(
    snapshot: StockSnapshot, as_of: date | None = None
) -> tuple[StockSnapshot, dict | None]:
    """Fill the revisions/catalysts StockSnapshot fields from free tier-B/tier-A sources so
    scoring/engine.py's revisions and catalysts components stop being permanently
    unavailable: yfinance analyst estimates + event-dated rating changes
    (``providers.yfinance_estimates``), Yahoo earnings-surprise history
    (``providers.yfinance_surprises``) and, for tickers where SEC EDGAR has a CIK on file
    (US filers), Form 4/4-A insider-filing and 8-K filing counts (``providers.sec_filings``).

    Every one of these four sub-fetches is independently wrapped: a failure (rate limit,
    no coverage, network error, a European local line yfinance doesn't track rating events
    for) leaves the corresponding field(s) untouched -- ``None``, never fabricated -- and is
    recorded as a plain-text note in ``provenance.secondary_sources`` rather than raised or
    silently dropped (CLAUDE.md rule 6). Returns the (possibly updated) snapshot plus the
    raw ``AnalystEstimates`` dict (``None`` on failure) for callers that also want to show
    it directly, e.g. ``analyze_stock``'s ``estimates`` key.
    """
    reference = as_of or date.today()
    updates: dict[str, object] = {}
    notes: list[str] = []
    estimates_dict: dict | None = None
    confidence_cap: float | None = None

    try:
        estimates = estimates_module.fetch_estimates(
            snapshot.ticker, reference, ticker_factory=yf.Ticker
        )
    except Exception as exc:
        notes.append(f"yfinance_estimates: unavailable ({type(exc).__name__}: {exc})")
    else:
        estimates_dict = estimates.model_dump(mode="json")
        for field in _ESTIMATE_SNAPSHOT_FIELDS:
            value = getattr(estimates, field, None)
            if value is not None:
                updates[field] = value
        estimates_confidence = estimates.provenance.get("confidence")
        notes.append(f"yfinance_estimates: confidence {estimates_confidence}")
        if isinstance(estimates_confidence, int | float):
            confidence_cap = float(estimates_confidence)

    try:
        surprises = surprises_module.fetch_surprise_history(
            snapshot.ticker, reference, ticker_factory=yf.Ticker
        )
    except Exception as exc:
        notes.append(f"yfinance_surprises: unavailable ({type(exc).__name__}: {exc})")
    else:
        if surprises.surprise_mean_8q is not None:
            updates["surprise_mean_8q"] = surprises.surprise_mean_8q
            updates["surprise_positive_share_8q"] = surprises.surprise_positive_share_8q
            updates["surprise_streak"] = surprises.surprise_streak
        notes.append(
            f"yfinance_surprises: {surprises.quarters_available or 0} usable quarters"
        )

    try:
        cik = sec_provider.cik_for_ticker(snapshot.ticker)
    except Exception as exc:
        cik = None
        notes.append(f"sec_edgar: CIK lookup failed ({type(exc).__name__}: {exc})")
    if cik is None:
        notes.append(
            "sec_edgar: no CIK on file -- insider/8-K activity counts unavailable "
            "(foreign filer, ADR or unlisted)"
        )
    else:
        try:
            insider = sec_filings_module.insider_activity(
                snapshot.ticker, days=90, provider=sec_provider
            )
        except Exception as exc:
            notes.append(f"sec_insider_activity: unavailable ({type(exc).__name__}: {exc})")
        else:
            if insider.get("ok"):
                updates["insider_form4_90d"] = insider.get("filing_count")
        try:
            filings_8k = sec_filings_module.list_filings(
                snapshot.ticker, forms=("8-K",), limit=20, provider=sec_provider
            )
        except Exception as exc:
            notes.append(f"sec_8k_filings: unavailable ({type(exc).__name__}: {exc})")
        else:
            window_start = (reference - timedelta(days=90)).isoformat()
            updates["filings_8k_90d"] = sum(
                1
                for f in filings_8k
                if window_start <= f.get("filing_date", "") <= reference.isoformat()
            )

    if not updates and not notes:
        return snapshot, estimates_dict

    prov = snapshot.provenance.model_copy(deep=True)
    prov.secondary_sources.extend(notes)
    # yfinance_estimates' own confidence (tracked-field completeness) is a genuine
    # reliability signal for thin analyst-consensus coverage -- fold it into the numeric
    # confidence scoring/engine.py actually reads, not just a text note (finding 25).
    if confidence_cap is not None:
        prov.confidence = min(prov.confidence, confidence_cap)
    enriched = snapshot.model_copy(update={**updates, "provenance": prov})
    return enriched, estimates_dict


@mcp.tool()
def analyze_stock(ticker: str, cross_check_sec: bool = True) -> dict:
    """Deterministic stock score (0-100) + confidence from free public data. Yahoo (tier B)
    provides the snapshot; audited SEC 10-K facts (tier A) override revenue growth and free
    cash flow when the company files with the SEC. Every override is listed in provenance.
    A metric where sources disagree without an official (tier A) tiebreaker is excluded
    from the score entirely; the full reconciliation is returned under "evidence"."""
    try:
        # Fetch the raw (pre-override) snapshot ourselves, rather than through
        # _snapshot_with_official_data, so the evidence cross-check below can compare
        # against the REAL yfinance reading -- not the SEC value that may have already
        # replaced it (apply_official_overrides mutates the field in place while leaving
        # provenance.source unchanged, so reading it back off the overridden snapshot
        # would silently compare the SEC number against itself).
        raw_snapshot = provider.get_stock_snapshot(ticker)
        facts: dict | None = None
        if cross_check_sec:
            try:
                facts = sec_provider.get_company_facts(ticker)
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                facts = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        overridden = apply_official_overrides(raw_snapshot, facts)
        snapshot, evidence = apply_evidence_report(overridden, facts, raw_snapshot=raw_snapshot)
        snapshot, estimates_dict = _enrich_snapshot_with_free_data(snapshot)
        score = score_snapshot(snapshot)
    except Exception as exc:
        return {
            "ticker": ticker,
            "error": f"{type(exc).__name__}: {exc}",
            "score": None,
            "confidence": 0.0,
        }
    result = score.model_dump(mode="json")
    result["evidence"] = evidence
    result["estimates"] = estimates_dict
    return result


@mcp.tool()
def screen_stocks(tickers: list[str], min_score: float = 0.0) -> list[dict]:
    """
    Analyze an explicit ticker universe and rank it. Every ticker is scored, including
    revisions/catalysts when free data (yfinance analyst estimates/rating events, Yahoo
    earnings-surprise history, SEC Form 4/8-K counts) covers it -- see
    ``_enrich_snapshot_with_free_data``. V1 intentionally requires a ticker list instead
    of scraping the whole market (see ``discover_stocks`` for that).
    """
    results = []
    for ticker in tickers:
        try:
            snapshot, _facts = _snapshot_with_official_data(ticker, cross_check_sec=False)
            snapshot, _estimates = _enrich_snapshot_with_free_data(snapshot)
            score = score_snapshot(snapshot)
            if score.score >= min_score:
                results.append(score.model_dump(mode="json"))
        except Exception as exc:
            results.append(
                {
                    "ticker": ticker,
                    "error": str(exc),
                    "score": None,
                    "confidence": 0.0,
                }
            )
    return sorted(
        results,
        key=lambda x: (x.get("score") is not None, x.get("score") or -1),
        reverse=True,
    )


@mcp.tool()
def portfolio_risk(path: str, base_currency: str = "EUR") -> dict:
    """Summarize weights, concentration and leveraged exposure from a local export."""
    try:
        portfolio = _parse_export(path, base_currency=base_currency)
    except (FileNotFoundError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    return summarize_portfolio_risk(portfolio)


@mcp.tool()
def allocate_cash(
    current_values: CurrentValues,
    targets: Targets,
    cash_eur: float,
    fixed_fee_eur: float = 2.95,
    variable_fee_pct: float = 0.0,
    max_fee_ratio: float = 0.01,
    rebalance_band_abs: float = 0.03,
) -> dict:
    """Allocate new cash toward target weights without selling, while considering fees."""
    fee_model = FeeModel(
        fixed_fee_eur=fixed_fee_eur,
        variable_fee_pct=variable_fee_pct,
        max_fee_ratio=max_fee_ratio,
    )
    try:
        return allocate_cash_to_targets(
            current_values=current_values,
            targets=targets,
            cash_eur=cash_eur,
            fee_model=fee_model,
            rebalance_band_abs=rebalance_band_abs,
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def rebalance_portfolio(
    current_values: CurrentValues,
    targets: Targets,
    cash_eur: float = 0.0,
    fixed_fee_eur: float = 2.95,
    variable_fee_pct: float = 0.0,
    max_fee_ratio: float = 0.01,
    rebalance_band_abs: float = 0.03,
    allow_sells: Annotated[
        bool,
        Field(
            description="Last resort per CLAUDE.md's rebalancing order: only when True are "
            "SELL orders for buckets past target+band also proposed, under 'sell_proposals'. "
            "BUY orders (from cash) are produced either way and are never affected by this."
        ),
    ] = False,
) -> dict:
    """
    Cash-flow-first rebalancer. New cash buys the most underweight buckets first (BUY
    orders only, via allocate_cash) -- CLAUDE.md's preferred order: use new cash, suspend
    buys on overweights, buy underweights, and sell only as a last resort. Set
    allow_sells=True to also see SELL orders for buckets still beyond the rebalance band
    after cash is deployed, listed separately under "sell_proposals"; the BUY-only orders
    key is unchanged either way. Nothing here executes a trade.
    """
    result = allocate_cash(
        current_values=current_values,
        targets=targets,
        cash_eur=cash_eur,
        fixed_fee_eur=fixed_fee_eur,
        variable_fee_pct=variable_fee_pct,
        max_fee_ratio=max_fee_ratio,
        rebalance_band_abs=rebalance_band_abs,
    )
    fee_model = FeeModel(
        fixed_fee_eur=fixed_fee_eur,
        variable_fee_pct=variable_fee_pct,
        max_fee_ratio=max_fee_ratio,
    )
    try:
        summary = replacement_module.sell_summary(
            current_values=current_values,
            targets=targets,
            fee_model=fee_model,
            rebalance_band_abs=rebalance_band_abs,
            allow_sells=allow_sells,
            cash_eur=cash_eur,
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    result["sell_proposals"] = summary["orders"]
    if summary["suppressed_count"]:
        result.setdefault("warnings", []).append(
            f"{summary['suppressed_count']} drift sell(s) suppressed because sells are "
            "disabled (pass allow_sells=True to include them)."
        )
    return result


@mcp.tool()
def generate_order_plan(
    current_values: CurrentValues,
    targets: Targets,
    cash_eur: float,
    fixed_fee_eur: float = 2.95,
    variable_fee_pct: float = 0.0,
    max_fee_ratio: float = 0.01,
) -> dict:
    """Return suggested manual orders. This tool cannot send orders to any broker."""
    plan = allocate_cash(
        current_values=current_values,
        targets=targets,
        cash_eur=cash_eur,
        fixed_fee_eur=fixed_fee_eur,
        variable_fee_pct=variable_fee_pct,
        max_fee_ratio=max_fee_ratio,
    )
    plan["execution"] = "MANUAL_ONLY"
    plan["broker_access"] = False
    return plan


@mcp.tool()
def build_investment_plan(
    cash_now: float,
    monthly_contribution: float,
    horizon_years: float,
    risk_tolerance: Annotated[
        str, Field(description="low = would sell after -30%, medium = would hold, high = would buy")
    ],
    start_date: str | None = None,
    fixed_fee_eur: float = 2.95,
    variable_fee_pct: float = 0.0,
    max_fee_ratio: float = 0.01,
    rebalance_band_abs: float = 0.03,
    review_every_months: int = 3,
) -> dict:
    """Turn four rookie answers into a deterministic plan: profile, targets, example
    instruments to verify, initial manual orders, fee-aware contribution cadence, 12-month
    calendar and review rules. No return forecast. Nothing is executed."""
    fee_model = FeeModel(
        fixed_fee_eur=fixed_fee_eur,
        variable_fee_pct=variable_fee_pct,
        max_fee_ratio=max_fee_ratio,
    )
    try:
        start = date.fromisoformat(start_date) if start_date else date.today()
        return _build_plan(
            cash_now=cash_now,
            monthly_contribution=monthly_contribution,
            horizon_years=horizon_years,
            risk_tolerance=risk_tolerance,
            start_date=start,
            fee_model=fee_model,
            rebalance_band_abs=rebalance_band_abs,
            review_every_months=review_every_months,
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def backtest_plan(
    tickers_by_bucket: Annotated[dict[str, str], Field(description="bucket -> yfinance ticker")],
    targets: Targets,
    initial_cash: float,
    monthly_contribution: float,
    period: str = "5y",
    contribution_every_months: int = 1,
    fixed_fee_eur: float = 2.95,
    variable_fee_pct: float = 0.0,
    max_fee_ratio: float = 0.01,
    rebalance_band_abs: float = 0.03,
    price_source: Annotated[str, Field(description="yfinance (default) or stooq")] = "yfinance",
) -> dict:
    """Replay the plan rules on past monthly prices (free provider): fees paid, drift,
    drawdown, final weights. Buckets without price data are reported, never invented.
    This is a replay of the past, not a forecast."""
    source_provider = stooq_provider if price_source == "stooq" else provider
    closes = source_provider.get_monthly_closes(tickers_by_bucket, period=period)
    missing = list(closes.attrs.get("missing", []))
    usable = {b: w for b, w in targets.items() if b in closes.columns}
    total = sum(usable.values())
    if not usable or len(closes) < 2 or total <= 0:
        return {
            "ok": False,
            "error": "No usable price history for the requested buckets",
            "missing_buckets": missing,
            "source": closes.attrs.get("source"),
            "as_of": closes.attrs.get("as_of"),
        }
    renormalized = {b: w / total for b, w in usable.items()}
    result = simulate_cash_flow_plan(
        closes,
        renormalized,
        initial_cash=initial_cash,
        monthly_contribution=monthly_contribution,
        fee_model=FeeModel(
            fixed_fee_eur=fixed_fee_eur,
            variable_fee_pct=variable_fee_pct,
            max_fee_ratio=max_fee_ratio,
        ),
        rebalance_band_abs=rebalance_band_abs,
        contribution_every_months=contribution_every_months,
    )
    result.update(
        {
            "ok": True,
            "missing_buckets": missing,
            "targets_used": renormalized,
            "source": closes.attrs.get("source"),
            "as_of": closes.attrs.get("as_of"),
            "from": str(closes.index[0].date()),
            "to": str(closes.index[-1].date()),
        }
    )
    return result


@mcp.tool()
def discover_stocks(
    preset: Annotated[str, Field(description=f"one of {sorted(PRESETS)}")] = "quality_growth",
    limit: int = 50,
    mode: Annotated[
        str,
        Field(
            description="'universe' (default): sample every market-cap size bucket x style "
            "with NO exclusion by size, index membership or overlap -- big and small "
            "companies in the same net (portfolio.picker's binding potential-ranking "
            "principle; see FinvizProvider.discover_universe). 'preset': the original "
            "single narrower Finviz preset screen, unchanged."
        ),
    ] = "universe",
    per_screen: Annotated[
        int, Field(description="mode='universe' only: max candidates per (style, size) pair")
    ] = 15,
    styles: Annotated[
        list[str] | None,
        Field(description="mode='universe' only: styles to sample; default all 3 presets"),
    ] = None,
    sizes: Annotated[
        list[str] | None,
        Field(
            description="mode='universe' only: size buckets to sample; "
            "default mega/large/mid/small/micro/nano (no floor -- includes penny-stock "
            "territory)"
        ),
    ] = None,
) -> dict:
    """Discovery step for "I have no idea what to buy" (public pages, tier C, no account).

    Nothing is excluded here: mode='universe' (default) samples the WHOLE market across
    every size bucket and style -- huge and small companies in the same net, no filter by
    index membership or overlap; mode='preset' runs one narrower Finviz preset screen
    instead (original behaviour, ``limit`` bounds it). Either way this is discovery only:
    every candidate must be re-scored with rank_candidates/screen_stocks/analyze_stock --
    Finviz numbers never enter the score. Size, sector and overlap tags attached later by
    ``rank_candidates`` are information, never a reason to drop a candidate from this list.
    """
    if preset not in PRESETS:
        raise ToolError(f"Unknown preset '{preset}'. Available: {sorted(PRESETS)}")
    try:
        if mode == "preset":
            return finviz_provider.screen(preset=preset, limit=limit)
        if mode != "universe":
            raise ValueError(f"Unknown mode {mode!r}. Use 'universe' or 'preset'.")
        kwargs: dict = {"per_screen": per_screen}
        if styles is not None:
            kwargs["styles"] = tuple(styles)
        if sizes is not None:
            kwargs["sizes"] = tuple(sizes)
        return finviz_provider.discover_universe(**kwargs)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool()
def log_decision(
    symbol: str,
    action: Annotated[str, Field(description="BUY|BUY_SMALL|HOLD|WATCH|REDUCE|SELL|NO_BUY")],
    reason: str,
    score: float | None = None,
    confidence: float | None = None,
    price: float | None = None,
    amount_eur: float | None = None,
    alternative: Annotated[str | None, Field(description="what you would buy instead")] = None,
    alternative_price: float | None = None,
    red_team: str | None = None,
    sources: list[str] | None = None,
    category: Annotated[
        str | None,
        Field(description="Free-form grouping used by personal_edge, e.g. a sector or strategy"),
    ] = None,
    theme: Annotated[
        str | None,
        Field(description="personal_edge grouping fallback used only when category is not set"),
    ] = None,
    thesis_status: Annotated[
        str | None,
        Field(
            description="STABLE|STRENGTHENING|WEAKENING|BROKEN|UNVERIFIABLE if check_thesis "
            "was run at decision time; feeds decision_quality's thesis_status criterion"
        ),
    ] = None,
    cap_eur: Annotated[
        float | None,
        Field(description="Per-position EUR cap this amount was checked against, for "
                           "decision_quality's amount_within_cap criterion"),
    ] = None,
    decision_kind: Annotated[
        str | None,
        Field(
            description="'bucket' for a bucket/index fill (no red team, no alternative, no "
            "per-stock cap by design -- decision_quality scores it on the criteria that "
            "actually apply); omit for an ordinary single-stock decision"
        ),
    ] = None,
    candidates: Annotated[
        list[dict] | None,
        Field(
            description="The full ranking shown at decision time (e.g. capital_auction's "
            "'candidates_for_ledger'): [{'symbol','kind','utility','price','price_symbol'}, "
            "...]. Stored so portfolio.opportunity can later measure regret against every "
            "option that was on the table, not just the single recorded 'alternative'."
        ),
    ] = None,
) -> dict:
    """Append a suggested decision to the local decision ledger (data/private, git-ignored).
    Records what was decided and the shadow alternative so it can be measured later."""
    try:
        rec = record_decision(
            {
                "symbol": symbol,
                "action": action,
                "reason": reason,
                "score": score,
                "confidence": confidence,
                "price": price,
                "amount_eur": amount_eur,
                "alternative": alternative,
                "alternative_price": alternative_price,
                "red_team": red_team,
                "sources": sources or [],
                "category": category,
                "theme": theme,
                "thesis_status": thesis_status,
                "cap_eur": cap_eur,
                "decision_kind": decision_kind,
                "candidates": candidates or [],
            }
        )
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return rec.model_dump(mode="json")


def _opportunity_prices(decisions: list) -> tuple[dict[str, float | None], dict[str, str]]:
    """Prices needed for portfolio.opportunity's regret measurement: every decision's own
    symbol/alternative plus every candidate (and its price_symbol) shown at decision time.
    Cash candidates need no price (opportunity_cost never looks one up for them), so they
    are skipped rather than logged as a spurious price error."""
    symbols = {d.symbol for d in decisions} | {d.alternative for d in decisions if d.alternative}
    for d in decisions:
        for c in d.candidates:
            if c.kind == "cash":
                continue
            symbols.add(c.symbol)
            if c.price_symbol:
                symbols.add(c.price_symbol)
    prices: dict[str, float | None] = {}
    price_errors: dict[str, str] = {}
    for symbol in sorted(symbols):
        try:
            prices[symbol] = provider.get_stock_snapshot(symbol).price
        except Exception as exc:
            prices[symbol] = None
            price_errors[symbol] = f"{type(exc).__name__}: {exc}"
    return prices, price_errors


def _load_decisions_or_tool_error() -> list:
    """load_decisions(), turning a corrupted/legacy decisions.jsonl line into a clear
    ToolError instead of letting the raw json.JSONDecodeError/pydantic.ValidationError
    reach the caller as an opaque 'Error executing tool <name>' (CLAUDE.md rule 6: degrade
    and say so, never go silent/opaque)."""
    try:
        return load_decisions()
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ToolError(f"decisions.jsonl is corrupted: {exc}") from exc


@mcp.tool()
def review_decisions(min_days: int = 90) -> dict:
    """Shadow portfolio: for every logged decision older than min_days, compare what was
    chosen with the recorded alternative at today's prices (free provider). Reports mean
    decision alpha and hit rate, and refuses to draw conclusions on fewer than 10 decisions.
    Also includes an 'opportunity' section (portfolio.opportunity): regret against the full
    ranking shown at decision time, when decisions were logged with 'candidates'."""
    decisions = _load_decisions_or_tool_error()
    prices, price_errors = _opportunity_prices(decisions)
    report = evaluate_decisions(decisions, prices, min_days=min_days)
    report["price_errors"] = price_errors
    report["source"] = provider.source_name
    report["opportunity"] = opportunity_module.opportunity_report(
        decisions, prices, as_of=date.today(), min_days=min_days
    )
    return report


def _fx_rates_or_none() -> tuple[dict | None, str | None]:
    """Fetch ECB rates, turning any HTTP/parse failure into (None, error_message)."""
    try:
        return fx_provider.get_rates(), None
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


@mcp.tool()
def fx_rates() -> dict:
    """Official ECB euro reference rates (free): units of currency per 1 EUR, with as_of."""
    rates, error = _fx_rates_or_none()
    if rates is None:
        return {"ok": False, "source": fx_provider.source_name, "error": error}
    return rates


@mcp.tool()
def convert_amount_to_eur(amount: float, currency: str) -> dict:
    """Convert an amount to EUR with the ECB reference rate. Unknown currency => value null."""
    rates, error = _fx_rates_or_none()
    if rates is None:
        return {
            "ok": False,
            "amount": amount,
            "currency": currency.upper(),
            "eur": None,
            "rate_per_eur": None,
            "source": fx_provider.source_name,
            "error": error,
        }
    return {
        "amount": amount,
        "currency": currency.upper(),
        "eur": convert_to_eur(amount, currency, rates["rates"]),
        "rate_per_eur": rates["rates"].get(currency.upper()),
        "source": rates["source"],
        "as_of": rates["as_of"],
    }


@mcp.tool()
def company_facts(ticker: str) -> dict:
    """Audited annual fundamentals from SEC EDGAR 10-K XBRL facts (US filers only, free):
    revenue and growth, net income/margin, free cash flow, equity, debt, with fiscal year and
    filing date. Foreign ADRs usually have no us-gaap facts: the result says so."""
    try:
        return sec_provider.get_company_facts(ticker)
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        return {
            "ticker": ticker,
            "source": "sec_edgar",
            "ok": False,
            "confidence": 0.0,
            "error": f"{type(exc).__name__}: {exc}",
        }


@mcp.tool()
def save_thesis(
    thesis: Annotated[
        dict,
        Field(
            description="{'symbol','claims':[...],'falsifiers':[{'metric','op','threshold',"
            "'label'}, ...],'created' (ISO date)}. 'history' is usually omitted on creation."
        ),
    ],
) -> dict:
    """Persist (create or update) a symbol's investment thesis: the claims made at BUY time
    plus concrete, checkable falsifiers (see check_thesis). Upserts by uppercased symbol;
    call this right after log_decision on a BUY so the thesis can later be checked against
    fresh data instead of re-litigated from memory."""
    try:
        saved = thesis_module.save_thesis(thesis)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    return saved.model_dump(mode="json")


@mcp.tool()
def check_thesis(
    symbol: str,
    as_of: str | None = None,
    cross_check_sec: bool = True,
) -> dict:
    """Evaluate a stored thesis's falsifiers against a fresh market snapshot (Yahoo, plus
    audited SEC facts when available -- see analyze_stock). Never invents a thesis: raises
    if none was saved for this symbol via save_thesis. Returns the new check plus the
    previous status and a qualitative delta (new/unchanged/improved/worsened)."""
    check_date = as_of or date.today().isoformat()
    try:
        snapshot, _facts = _snapshot_with_official_data(symbol, cross_check_sec)
    except Exception as exc:
        raise ToolError(
            f"Could not fetch metrics for {symbol}: {type(exc).__name__}: {exc}"
        ) from exc
    metrics = snapshot.model_dump(mode="json")
    try:
        return thesis_module.check_thesis(symbol, metrics, check_date)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def _score_symbol_for_replacement(
    ticker: str, exposure: dict | None
) -> tuple[float, float, float, str | None]:
    """Shared by propose_replacement's current holding and its candidates: score, its
    confidence, fit against `exposure` (1.0 when no portfolio context was given) and the
    symbol's last stored thesis status, if any."""
    symbol = ticker.strip().upper()
    snapshot, _facts = _snapshot_with_official_data(symbol, cross_check_sec=False)
    score = score_snapshot(snapshot)
    theses = thesis_module.load_theses()
    thesis = theses.get(symbol)
    status = thesis.history[-1].status if thesis and thesis.history else None
    fit = 1.0
    if exposure is not None:
        candidate_exposure = exposure_module.classify(
            name=snapshot.ticker, sector=snapshot.sector, industry=snapshot.industry
        )
        theme_caps = (_load_portfolio_config().get("risk_limits") or {}).get("theme_caps")
        fit = exposure_module.fit_score(candidate_exposure, exposure, caps=theme_caps)["fit"]
    return score.score, score.confidence, fit, status


@mcp.tool()
def propose_replacement(
    current_symbol: str,
    current_value_eur: float,
    candidate_tickers: list[str],
    holdings: Annotated[
        list[dict] | None,
        Field(
            description="Parsed portfolio holdings (parse_portfolio_export's 'holdings' "
            "list) used to score each candidate's fit against existing hidden exposure. "
            "Omit to treat every candidate as fully diversifying (fit=1.0)."
        ),
    ] = None,
    fixed_fee_eur: float = 2.95,
    variable_fee_pct: float = 0.0,
    max_fee_ratio: float = 0.01,
    cash_utility: float = 55.0,
    min_improvement: float = 15.0,
    max_roundtrip_fee_ratio: float = 0.02,
) -> dict:
    """Is `current_symbol` still worth its slot, versus one of `candidate_tickers` or plain
    cash? Utility blends each symbol's analyze_stock score/confidence with its fit against
    `holdings`' hidden exposure (portfolio.exposure) and, when a thesis was saved for it,
    its last check_thesis status. Returns HOLD/REPLACE/SELL_TO_CASH with fee-aware order(s)
    -- a good company is not automatically a good addition (CLAUDE.md), and the round-trip
    fee must be worth paying before rotating."""
    fee_model = FeeModel(
        fixed_fee_eur=fixed_fee_eur, variable_fee_pct=variable_fee_pct, max_fee_ratio=max_fee_ratio
    )
    current_symbol_norm = current_symbol.strip().upper()
    exposure = exposure_module.portfolio_exposure(holdings) if holdings else None
    # The current holding's own fit must be measured against the REST of the portfolio,
    # never against an exposure snapshot that already includes 100% of itself -- otherwise
    # a large, genuinely diversifying core holding gets fit=0 purely because it dominates
    # the exposure it is being compared to (a self-comparison artifact, not a real
    # diversification signal). Candidates keep the full portfolio exposure: they are not
    # already part of it (or, if they happen to be, that overlap is exactly what should
    # discount their fit).
    exposure_excl_current = (
        exposure_module.portfolio_exposure(
            [h for h in holdings if (h.get("symbol") or "").strip().upper() != current_symbol_norm]
        )
        if holdings
        else None
    )

    try:
        cur_score, cur_confidence, cur_fit, cur_status = _score_symbol_for_replacement(
            current_symbol, exposure_excl_current
        )
        current_utility = replacement_module.utility(
            cur_score, cur_confidence, fit=cur_fit, thesis_health=_thesis_health(cur_status)
        )
    except Exception as exc:
        raise ToolError(
            f"Could not score {current_symbol}: {type(exc).__name__}: {exc}"
        ) from exc

    # Per-stock weight cap (CLAUDE.md: "limite per singolo titolo"), enforced only when the
    # caller supplied enough portfolio context (holdings) to know a candidate's existing
    # weight and the portfolio's total value -- without that, degrade by not enforcing a
    # cap we cannot compute, exactly like `fit` degrades to 1.0 without `holdings`.
    stock_cap_weight = _stock_cap_weight(_load_portfolio_config()) if holdings else None
    holdings_total_value = sum(float(h.get("market_value") or 0.0) for h in holdings or [])
    held_value_by_symbol: dict[str, float] = {}
    for h in holdings or []:
        sym = (h.get("symbol") or "").strip().upper()
        if sym:
            held_value_by_symbol[sym] = held_value_by_symbol.get(sym, 0.0) + float(
                h.get("market_value") or 0.0
            )

    candidate_errors: dict[str, str] = {}
    candidate_utilities: list[dict] = []
    max_buy_value_by_symbol: dict[str, float] = {}
    for ticker in candidate_tickers:
        symbol = ticker.strip().upper()
        try:
            score, confidence, fit, status = _score_symbol_for_replacement(ticker, exposure)
            candidate_utility = replacement_module.utility(
                score, confidence, fit=fit, thesis_health=_thesis_health(status)
            )
        except Exception as exc:
            candidate_errors[symbol] = f"{type(exc).__name__}: {exc}"
            continue
        candidate_utilities.append(
            {"symbol": symbol, "utility": candidate_utility, "confidence": confidence}
        )
        if stock_cap_weight is not None and holdings_total_value > 0:
            held = held_value_by_symbol.get(symbol, 0.0)
            max_buy_value_by_symbol[symbol] = max(
                0.0, stock_cap_weight * holdings_total_value - held
            )

    result = replacement_module.propose_replacement(
        current={
            "symbol": current_symbol_norm,
            "value_eur": current_value_eur,
            "utility": current_utility,
        },
        candidates=[
            {"symbol": c["symbol"], "utility": c["utility"]} for c in candidate_utilities
        ],
        fee_model=fee_model,
        cash_utility=cash_utility,
        min_improvement=min_improvement,
        max_roundtrip_fee_ratio=max_roundtrip_fee_ratio,
        max_buy_value_by_symbol=max_buy_value_by_symbol or None,
    )
    result["current_utility"] = round(current_utility, 4)
    result["current_confidence"] = cur_confidence
    result["candidate_utilities"] = candidate_utilities
    if candidate_errors:
        result["candidate_errors"] = candidate_errors
    return result


@mcp.tool()
def portfolio_exposure(path: str, base_currency: str = "EUR") -> dict:
    """Hidden-exposure theme/driver rollup for a local export (config/exposure_graph.yaml):
    a small-cap ETF and an "AI software" fund can lean on the same driver despite unrelated
    sector labels. For each single-stock equity holding, fetches sector/industry from the
    market-data provider (a failed lookup is recorded under 'provider_errors', never
    guessed) so it can be classified; ETFs/certificates/bonds use only the fields already in
    the export. Includes a separate leverage-adjusted 'equivalent' view -- an intuitive
    metric only, never a VaR substitute (CLAUDE.md)."""
    try:
        portfolio = _parse_export(path, base_currency=base_currency)
    except (FileNotFoundError, ValueError) as exc:
        raise ToolError(str(exc)) from exc

    holdings: list[dict] = []
    provider_errors: dict[str, str] = {}
    sector_provenance: dict[str, dict] = {}
    for holding in portfolio.holdings:
        data = holding.model_dump()
        industry = None
        sector = holding.sector
        if holding.asset_type == AssetType.EQUITY and holding.symbol:
            try:
                snapshot = provider.get_stock_snapshot(holding.symbol)
                sector = sector or snapshot.sector
                industry = snapshot.industry
                sector_provenance[holding.symbol] = snapshot.provenance.model_dump(mode="json")
            except Exception as exc:
                provider_errors[holding.symbol] = f"{type(exc).__name__}: {exc}"
        data["sector"] = sector
        data["industry"] = industry
        holdings.append(data)

    result = exposure_module.portfolio_exposure(holdings)
    if provider_errors:
        result["provider_errors"] = provider_errors
    result["sector_provenance"] = sector_provenance
    return result


def _targets_and_instruments() -> tuple[dict, dict]:
    """get_portfolio_config()'s targets plus config/model_portfolios.yaml's example
    instruments, both needed to map holdings to buckets. Raises ToolError (never a raw
    FileNotFoundError/ValueError) when either config is missing or unusable."""
    try:
        cfg = _load_portfolio_config()
        instruments = _load_model_portfolios()["instruments"]
    except (FileNotFoundError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    targets = cfg.get("targets")
    if not targets:
        raise ToolError("No targets configured (config/portfolio.yaml or the example fallback)")
    return targets, instruments


def _price_ranking_for_ledger(
    ranking: list[dict], instruments: dict, stock_prices: dict[str, float | None]
) -> list[dict]:
    """capital_auction's 'ranking' ({symbol, utility, kind}), enriched with each candidate's
    current price and price_symbol so it can be passed straight into log_decision's
    'candidates' -- the raw material for portfolio.opportunity's later regret measurement.

    A 'stock' candidate is priced from the snapshot already fetched to score it (no second
    network call). A 'bucket' candidate is priced through its model-portfolio proxy ETF
    (config/model_portfolios.yaml's yf_ticker); a bucket with no configured instrument, or a
    price lookup that fails, gets price=None -- never invented. 'cash' needs no price."""
    bucket_price_cache: dict[str, float | None] = {}

    def _bucket_price(yf_ticker: str) -> float | None:
        if yf_ticker not in bucket_price_cache:
            try:
                bucket_price_cache[yf_ticker] = provider.get_stock_snapshot(yf_ticker).price
            except Exception:
                bucket_price_cache[yf_ticker] = None
        return bucket_price_cache[yf_ticker]

    enriched: list[dict] = []
    for row in ranking:
        entry = dict(row)
        if row["kind"] == "stock":
            entry["price"] = stock_prices.get(row["symbol"])
            entry["price_symbol"] = None
        elif row["kind"] == "bucket":
            yf_ticker = (instruments.get(row["symbol"]) or {}).get("yf_ticker")
            entry["price_symbol"] = yf_ticker
            entry["price"] = _bucket_price(yf_ticker) if yf_ticker else None
        else:  # cash
            entry["price"] = None
            entry["price_symbol"] = None
        enriched.append(entry)
    return enriched


@mcp.tool()
def capital_auction(
    path: str,
    cash_eur: float,
    candidate_tickers: list[str] | None = None,
    base_currency: str = "EUR",
) -> dict:
    """Rank every use of new cash -- underweight target buckets, screened candidate stocks
    and holding cash itself -- by marginal utility (portfolio.auction) and allocate cash_eur
    to the winners, one economic order at a time. Bucket current values come from the local
    export mapped via portfolio.mapping against config/model_portfolios.yaml's example
    instruments; targets come from get_portfolio_config(). Candidate stocks are scored via
    analyze_stock; a stock below 0.5 confidence can never win. Each candidate's fit is its
    hidden-exposure overlap against the portfolio's own exposure (portfolio.exposure) -- a
    candidate that piles onto an already-large driver scores lower fit than one that
    diversifies. A stored thesis (check_thesis) discounts a candidate's utility if it is
    WEAKENING or BROKEN. Suggestions only -- never sends an order."""
    try:
        portfolio = _parse_export(path, base_currency=base_currency)
    except (FileNotFoundError, ValueError) as exc:
        raise ToolError(str(exc)) from exc

    targets, instruments = _targets_and_instruments()
    cfg = _load_portfolio_config()
    fee_model = _fee_model_from_config(cfg)
    stock_cap_weight = _stock_cap_weight(cfg)

    holdings_dump = [h.model_dump() for h in portfolio.holdings]
    try:
        mapping_result = _map_holdings(holdings_dump, targets, instruments)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    current_values = mapping_result["current_values"]
    total_value = portfolio.total_value

    candidates: list[auction_module.Candidate] = []
    for bucket, weight in targets.items():
        current_value = current_values.get(bucket, 0.0)
        deficit = max(0.0, weight * total_value - current_value)
        candidates.append(
            auction_module.Candidate(
                symbol=bucket,
                kind="bucket",
                edge=0.5,
                confidence=1.0,
                current_weight=(
                    _clamp_weight(current_value / total_value) if total_value > 0 else 0.0
                ),
                deficit_eur=deficit,
            )
        )

    held_value = {h.symbol.upper(): h.market_value for h in portfolio.holdings if h.symbol}
    try:
        theses = thesis_module.load_theses()
    except ValueError as exc:
        raise ToolError(f"Could not load stored theses: {exc}") from exc
    exposure = exposure_module.portfolio_exposure(holdings_dump)
    stock_errors: dict[str, str] = {}
    stock_prices: dict[str, float | None] = {}
    for ticker in candidate_tickers or []:
        symbol = ticker.strip().upper()
        try:
            snapshot, _facts = _snapshot_with_official_data(symbol, cross_check_sec=False)
            score = score_snapshot(snapshot)
        except Exception as exc:
            stock_errors[symbol] = f"{type(exc).__name__}: {exc}"
            continue
        stock_prices[symbol] = snapshot.price
        thesis = theses.get(symbol)
        status = thesis.history[-1].status if thesis and thesis.history else None
        candidate_exposure = exposure_module.classify(
            name=snapshot.ticker, sector=snapshot.sector, industry=snapshot.industry
        )
        theme_caps = (cfg.get("risk_limits") or {}).get("theme_caps")
        fit = exposure_module.fit_score(candidate_exposure, exposure, caps=theme_caps)["fit"]
        current_value = held_value.get(symbol, 0.0)
        candidates.append(
            auction_module.Candidate(
                symbol=symbol,
                kind="stock",
                edge=score.score / 100.0,
                confidence=score.confidence,
                thesis_health=_thesis_health(status),
                fit=fit,
                current_weight=(
                    _clamp_weight(current_value / total_value) if total_value > 0 else 0.0
                ),
                cap_weight=stock_cap_weight,
            )
        )

    candidates.append(
        auction_module.Candidate(
            symbol="CASH", kind="cash", edge=1.0, confidence=1.0, current_weight=0.0
        )
    )

    result = auction_module.capital_auction(cash_eur, candidates, fee_model, total_value)
    result["bucket_mapping"] = {
        "unmapped": mapping_result["unmapped"],
        "coverage": mapping_result["coverage"],
    }
    if stock_errors:
        result["stock_errors"] = stock_errors
    result["candidates_for_ledger"] = _price_ranking_for_ledger(
        result["ranking"], instruments, stock_prices
    )
    return result


@mcp.tool()
def personal_edge(
    min_days: int = 90,
    min_sample: Annotated[
        int, Field(ge=1, description="Minimum measured decisions before a raise/lower verdict")
    ] = 10,
) -> dict:
    """This user's own track record, not a market study: mean decision alpha and hit rate
    by category/theme (see log_decision's category/theme fields), from the decision
    ledger's measured rows. Refuses to call a group's evidence threshold raise/lower until
    it has at least min_sample measured decisions in it (default 10, CLAUDE.md-aligned)."""
    decisions = _load_decisions_or_tool_error()
    symbols = {d.symbol for d in decisions} | {d.alternative for d in decisions if d.alternative}
    prices: dict[str, float | None] = {}
    price_errors: dict[str, str] = {}
    price_provenance: dict[str, dict] = {}
    for symbol in sorted(symbols):
        try:
            snapshot = provider.get_stock_snapshot(symbol)
            prices[symbol] = snapshot.price
            price_provenance[symbol] = snapshot.provenance.model_dump(mode="json")
        except Exception as exc:
            prices[symbol] = None
            price_errors[symbol] = f"{type(exc).__name__}: {exc}"

    evaluation = evaluate_decisions(decisions, prices, min_days=min_days)
    by_id = {d.id: d for d in decisions}
    rows: list[dict] = []
    for row in evaluation["rows"]:
        if row["status"] != "measured":
            continue
        record = by_id.get(row["id"])
        enriched = dict(row)
        if record is not None:
            if record.category:
                enriched["category"] = record.category
            elif record.theme:
                enriched["theme"] = record.theme
        rows.append(enriched)

    report = edge_module.personal_edge(rows, min_sample=min_sample)
    report["decisions_measured"] = evaluation["decisions_measured"]
    report["decisions_unmeasurable"] = evaluation["decisions_unmeasurable"]
    report["price_errors"] = price_errors
    report["price_provenance"] = price_provenance
    return report


@mcp.tool()
def decision_quality(decision_id: str) -> dict:
    """Process-quality rubric (0-100) for one logged decision (see log_decision): did it
    have sources, adequate confidence, a red-team pass, a documented reason, a recorded
    alternative, a recorded price/amount and a non-deteriorating thesis? Never looks at the
    outcome. Paired here with the decision/outcome matrix using today's measured alpha, when
    the decision is already priceable."""
    decisions = _load_decisions_or_tool_error()
    record = next((d for d in decisions if d.id == decision_id), None)
    if record is None:
        raise ToolError(f"No decision found with id {decision_id!r}")

    symbols = {record.symbol}
    if record.alternative:
        symbols.add(record.alternative)
    prices: dict[str, float | None] = {}
    price_errors: dict[str, str] = {}
    price_provenance: dict[str, dict] = {}
    for symbol in symbols:
        try:
            snapshot = provider.get_stock_snapshot(symbol)
            prices[symbol] = snapshot.price
            price_provenance[symbol] = snapshot.provenance.model_dump(mode="json")
        except Exception as exc:
            prices[symbol] = None
            price_errors[symbol] = f"{type(exc).__name__}: {exc}"

    evaluation = evaluate_decisions([record], prices, min_days=0)
    measurement = evaluation["rows"][0]
    quality = quality_module.decision_quality(record.model_dump(mode="json"))
    return {
        "decision": record.model_dump(mode="json"),
        "quality": quality,
        "measurement": measurement,
        "outcome_matrix": quality_module.decision_outcome_matrix(
            quality["score"], measurement.get("decision_alpha")
        ),
        "price_errors": price_errors,
        "price_provenance": price_provenance,
    }


@mcp.tool()
def macro_snapshot(
    geo: Annotated[str, Field(description="Eurostat geo for HICP (EA20 = euro area)")] = "EA20",
    unemployment_geo: Annotated[
        str, Field(description="Eurostat geo for unemployment; une_rt_m has no EA20 aggregate")
    ] = "EU27_2020",
) -> dict:
    """Deterministic macro regime read: HICP (Eurostat, tier A), unemployment (Eurostat,
    tier A; EU27_2020 by default because the euro-area aggregate is not published for
    une_rt_m) plus the ECB deposit facility rate (tier A). regime is
    restrictive/neutral/accommodative only when both HICP and the deposit rate are
    available; either missing makes it 'unknown' -- never guessed."""
    return macro_module.macro_snapshot(
        eurostat_provider, ecb_rates_provider, geo=geo, unemployment_geo=unemployment_geo
    )


@mcp.tool()
def filing_sections(
    ticker: str,
    form: str = "10-K",
    items: Annotated[
        list[str] | None,
        Field(
            description="Item numbers/letters to extract, e.g. ['1A','7'] for Risk Factors "
            "and MD&A. Defaults to ['1A','7'] when omitted."
        ),
    ] = None,
) -> dict:
    """Item-section text from the most recent SEC filing of `form` for `ticker` (tier A,
    free, data.sec.gov). A ticker with no CIK, or no filing of that form (e.g. a foreign
    private issuer filing 20-F instead of 10-K), comes back ok=False with a readable
    reason -- text is extracted by a best-effort heading scan, never invented."""
    try:
        return sec_filings_module.filing_sections(
            ticker, form=form, items=tuple(items or ("1A", "7"))
        )
    except (httpx.HTTPError, ValueError) as exc:
        return {
            "ticker": ticker.strip().upper(),
            "form": form,
            "source": "sec_edgar_filings",
            "tier": "A",
            "ok": False,
            "confidence": 0.0,
            "error": f"{type(exc).__name__}: {exc}",
        }


@mcp.tool()
def insider_activity(ticker: str, days: int = 90) -> dict:
    """Form 4 / 4-A filing counts in the trailing `days` window for `ticker` (SEC EDGAR,
    tier A, free) -- an insider-paperwork activity signal, not a buy/sell tally: the
    transaction XML (shares, price, direction) is not parsed, and that limitation is always
    stated in the result."""
    try:
        return sec_filings_module.insider_activity(ticker, days=days)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    except httpx.HTTPError as exc:
        return {
            "ticker": ticker.strip().upper(),
            "source": "sec_edgar_filings",
            "tier": "A",
            "ok": False,
            "confidence": 0.0,
            "filing_count": None,
            "filing_dates": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


@mcp.tool()
def investor_relations_links(ticker: str) -> dict:
    """Find and classify a company's investor-relations page (annual/quarterly reports,
    earnings releases, guidance, presentations, press releases) from its public website
    (yfinance's `info.website`), respecting robots.txt. Tier A: the company's own site.
    Never logs in, executes JavaScript, or bypasses a paywall."""
    symbol = ticker.strip().upper()
    # Matches IRProvider.investor_relations()'s own not-found envelope shape (CLAUDE.md
    # rule 5: every external datum needs source/as_of/confidence, even -- especially --
    # a degraded/missing one) for the two failure paths that happen before that provider
    # is ever reached.
    envelope_base = {
        "source": ir_provider.source_name,
        "tier": ir_provider.tier,
        "as_of": datetime.now(UTC).isoformat(),
        "confidence": 0.0,
        "ir_url": None,
        "links": [],
        "missing": list(ALL_IR_KINDS),
    }
    try:
        website = yf.Ticker(symbol).info.get("website")
    except Exception as exc:
        return {
            **envelope_base,
            "ticker": symbol,
            "ok": False,
            "website": None,
            "error": f"{type(exc).__name__}: {exc}",
        }
    if not website:
        return {
            **envelope_base,
            "ticker": symbol,
            "ok": False,
            "website": None,
            "error": "yfinance has no 'website' field for this ticker",
        }
    result = ir_provider.investor_relations(website)
    result["ticker"] = symbol
    return result


@mcp.tool()
def map_holdings_to_targets(path: str, base_currency: str = "EUR") -> dict:
    """Map every holding in a local export to a target allocation bucket (portfolio.mapping)
    by ISIN then by name keywords, using get_portfolio_config()'s targets and
    config/model_portfolios.yaml's example instruments. Certificates, leveraged instruments
    and single stocks are reported as satellite positions outside the bucket system -- never
    silently dropped from coverage. The result's 'current_values' plugs directly into
    rebalance_portfolio/allocate_cash's current_values parameter."""
    try:
        portfolio = _parse_export(path, base_currency=base_currency)
    except (FileNotFoundError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    targets, instruments = _targets_and_instruments()
    try:
        return _map_holdings([h.model_dump() for h in portfolio.holdings], targets, instruments)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc


def _plan_targets_for_snapshot() -> dict | None:
    """Targets to record on a snapshot: the saved investment plan's own targets
    (data/private/investment_plan.json) take precedence over get_portfolio_config()'s --
    the plan is what the user is actually committed to, the config is only a fallback for
    before a plan exists. Never invents a value: None when neither source has one."""
    home = Path(os.environ.get("PORTFOLIO_COPILOT_HOME") or snapshots_module.DEFAULT_HOME)
    plan_path = home / "investment_plan.json"
    if plan_path.exists():
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            plan = None
        if plan and plan.get("targets"):
            return plan["targets"]
    try:
        return _load_portfolio_config().get("targets") or None
    except FileNotFoundError:
        return None


@mcp.tool()
def save_portfolio_snapshot(
    path: Annotated[str, Field(description="Path to a local broker portfolio export (CSV/XLSX)")],
    as_of: Annotated[
        str | None,
        Field(description="ISO date (YYYY-MM-DD) to file this snapshot under; defaults to today"),
    ] = None,
    force: Annotated[
        bool, Field(description="Overwrite an existing stored snapshot for the same date")
    ] = False,
) -> dict:
    """Freeze the local export as one dated monthly snapshot (portfolio.snapshots,
    data/private/snapshots, git-ignored) so a later check-in can measure what actually
    changed instead of re-deriving history that was never recorded. Holdings are mapped to
    target buckets the same way map_holdings_to_targets does; the stored plan_targets
    prefer data/private/investment_plan.json's own targets over get_portfolio_config()'s.
    Refuses to overwrite an existing date unless force=True."""
    try:
        portfolio = _parse_export(path)
    except (FileNotFoundError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    targets, instruments = _targets_and_instruments()
    holdings_dump = [h.model_dump() for h in portfolio.holdings]
    try:
        mapping_result = _map_holdings(holdings_dump, targets, instruments)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    buckets = {m["name"]: m["bucket"] for m in mapping_result["mapped"]}
    resolved_as_of = as_of or date.today().isoformat()
    try:
        snapshot = snapshots_module.save_snapshot(
            portfolio.model_dump(mode="json"),
            resolved_as_of,
            buckets=buckets,
            plan_targets=_plan_targets_for_snapshot(),
            force=force,
        )
    except (FileExistsError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    result = snapshot.model_dump(mode="json")
    result["unmapped"] = mapping_result["unmapped"]
    result["coverage"] = mapping_result["coverage"]
    return result


@mcp.tool()
def list_portfolio_snapshots() -> dict:
    """Every stored monthly snapshot date (portfolio.snapshots, data/private/snapshots,
    git-ignored, local-only), oldest first."""
    return {"dates": snapshots_module.list_snapshots()}


@mcp.tool()
def compare_snapshots(
    older: Annotated[str, Field(description="ISO date of the earlier stored snapshot")],
    newer: Annotated[
        str | None,
        Field(
            description="ISO date of the later stored snapshot; defaults to the most "
            "recently stored one (typically the one just saved by save_portfolio_snapshot)"
        ),
    ] = None,
) -> dict:
    """Diff two stored monthly snapshots (portfolio.snapshots.diff_snapshots): total and
    per-holding/per-bucket value change since 'older'. Cannot separate contributions from
    market move on its own -- always read the returned 'note' before calling a number
    'gain' or 'loss'."""
    try:
        older_snapshot = snapshots_module.load_snapshot(older)
    except (FileNotFoundError, ValueError) as exc:
        raise ToolError(str(exc)) from exc
    if newer is None:
        try:
            newer_snapshot = snapshots_module.latest_snapshot()
        except (FileNotFoundError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        if newer_snapshot is None:
            raise ToolError("No snapshots stored yet.")
    else:
        try:
            newer_snapshot = snapshots_module.load_snapshot(newer)
        except (FileNotFoundError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
    return snapshots_module.diff_snapshots(older_snapshot, newer_snapshot)


@mcp.tool()
def resolve_isins(
    isins: list[str],
    exch_code: Annotated[
        str | None,
        Field(
            description="Restrict the OpenFIGI search to one exchange (e.g. 'MI' for Borsa "
            "Italiana, 'US' for US-listed) and, when known, also compose a yfinance-style "
            "ticker for it (providers.openfigi.EXCHANGE_TO_YF_SUFFIX). Omit to search all "
            "exchanges for the ISIN (no yf_ticker is composed without a specific exchange)."
        ),
    ] = None,
) -> dict:
    """Map ISINs to tickers via the free, keyless OpenFIGI mapping API (tier A, no signup):
    useful when a broker export identifies a holding only by ISIN and another tool
    (analyze_stock, map_holdings_to_targets) needs a yfinance-style ticker instead. A miss
    or an exchange OpenFIGI doesn't map to a known Yahoo suffix comes back as `None` for
    that ISIN -- never an invented ticker. OpenFIGI's anonymous rate limit (25 req/min) is
    respected internally; a persistent HTTP failure (e.g. 429) is raised as a ToolError
    rather than silently returning nothing."""
    try:
        mapped = openfigi_provider.map_isins(isins, exch_code=exch_code)
    except httpx.HTTPError as exc:
        raise ToolError(f"OpenFIGI request failed: {type(exc).__name__}: {exc}") from exc

    suffix = EXCHANGE_TO_YF_SUFFIX.get(exch_code.upper()) if exch_code else None
    results: dict[str, dict | None] = {}
    for isin, row in mapped.items():
        if row is None:
            results[isin] = None
            continue
        entry = dict(row)
        entry["yf_ticker"] = (
            f"{entry['ticker']}{suffix}" if suffix is not None and entry.get("ticker") else None
        )
        results[isin] = entry

    # openfigi_provider.errors is a module-level singleton's dict: only prune it on a
    # later successful lookup of the SAME isin, so scope what we report here to the
    # isins this call actually resolved -- never leak an unrelated prior call's stale
    # error (finding 26).
    scoped_errors = {isin: msg for isin, msg in openfigi_provider.errors.items() if isin in mapped}

    return {
        "results": results,
        "errors": scoped_errors,
        "source": openfigi_provider.source_name,
        "tier": "A",
        "as_of": datetime.now(UTC).isoformat(),
    }


@mcp.tool()
def rank_candidates(
    tickers: list[str],
    path: Annotated[
        str | None,
        Field(
            description="Local broker export used only to compute each candidate's hidden-"
            "exposure overlap/diversification tag (portfolio.exposure) -- never to filter "
            "the ranking. Omit to rank without portfolio context (themes/diversification "
            "come back empty/None for every candidate)."
        ),
    ] = None,
    top_n: int = 10,
    min_confidence: Annotated[
        float,
        Field(
            description="Below this confidence, a candidate stays in the ranking but gets "
            "a 'low_confidence' tag in its `tags` list -- information, never a filter."
        ),
    ] = 0.0,
) -> dict:
    """Score every ticker in `tickers` (screen_stocks) and rank the WHOLE set by potential --
    huge and small caps in the same net. Nothing is excluded for being big, small, already
    inside an index/ETF, or concentrated in one sector: size, sector and index-overlap are
    informational tags attached to each ranked idea (portfolio.picker.annotate), never a
    filter. Only the caller's own risk caps (get_portfolio_config's risk_limits, when `path`
    is given) and a later red-team pass should ever limit how big a resulting BUY is sized --
    never this ranking itself. `top_n` only bounds how many of the ranked ideas are returned
    in `ranked`; every scored ticker (minus screening-error placeholders, reported separately
    in `screening_errors`) still counts toward the summary stats."""
    scored = screen_stocks(tickers)
    screening_errors = {s["ticker"]: s["error"] for s in scored if s.get("error")}

    exposure = None
    if path:
        try:
            portfolio = _parse_export(path)
        except (FileNotFoundError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        exposure = exposure_module.portfolio_exposure(
            [h.model_dump() for h in portfolio.holdings]
        )

    cfg = _load_portfolio_config()
    caps = cfg.get("risk_limits") or {}
    result = picker_module.shortlist(
        scored, exposure, caps, top_n=top_n, min_confidence=min_confidence
    )
    if screening_errors:
        result["screening_errors"] = screening_errors
    return result


# us-gaap tags for diluted/basic EPS -- CONCEPTS in providers/sec_edgar.py tracks revenue
# but has no EPS concept, so backtest_picker's fundamental_momentum needs its own lookup.
_EPS_TAGS = ("EarningsPerShareDiluted", "EarningsPerShareBasic")


def _annual_fundamental_rows(facts: dict, tags: tuple[str, ...]) -> list[dict]:
    """Every distinct fiscal-year (10-K/10-K/A) row for any tag in `tags`, deduped by the
    period's 'end' date and keeping the EARLIEST 'filed' occurrence for it (the original
    10-K, not a later restated comparative). Scans every tag without an early break: a
    company can switch XBRL tags for the same concept over time (e.g. ``Revenues`` ->
    ``RevenueFromContractWithCustomerExcludingAssessedTax``), and breaking out of the loop
    on the first tag with any match would silently hide the newer tag's rows behind a
    handful of stale ones from the old tag. Pure function, no I/O -- offline-testable
    against a hand-built ``facts`` dict."""
    gaap = (facts or {}).get("facts", {}).get("us-gaap", {})
    by_end: dict[str, dict] = {}
    for tag in tags:
        units = gaap.get(tag, {}).get("units", {})
        # Revenue tags report in "USD"; per-share tags (EPS) report in "USD/shares" --
        # fall back to whatever unit key is present, same pattern as sec_edgar.py's
        # _annual_series, rather than hardcoding "USD" and silently finding no EPS rows.
        rows = units.get("USD") or next(iter(units.values()), [])
        for row in rows:
            if row.get("form") not in {"10-K", "10-K/A"} or row.get("fp") != "FY":
                continue
            end, filed, value = row.get("end"), row.get("filed"), row.get("val")
            if not end or not filed or value is None:
                continue
            existing = by_end.get(end)
            if existing is None or filed < existing["filed"]:
                by_end[end] = {"end": end, "filed": filed, "value": float(value)}
    return sorted(by_end.values(), key=lambda r: r["end"])


def _fetch_asfiled_fundamentals(symbol: str) -> list[dict]:
    """As-filed ``{end, filed, revenue, eps}`` rows for `symbol` from raw SEC EDGAR XBRL
    company facts (US filers only), for ``portfolio.picker_backtest``'s point-in-time
    fundamental_momentum component. Every failure -- no CIK on file, a malformed payload,
    a network error -- degrades to ``[]``: ``proxy_score_at`` then simply reports
    fundamental_momentum as unavailable for this ticker rather than a fabricated value."""
    try:
        cik = sec_provider.cik_for_ticker(symbol)
        if cik is None:
            return []
        facts = sec_provider._get_json(sec_edgar_module.FACTS_URL.format(cik=cik))
    except Exception:
        return []
    revenue_rows = {
        r["end"]: r
        for r in _annual_fundamental_rows(facts, tuple(sec_edgar_module.CONCEPTS["revenue"]))
    }
    eps_rows = {r["end"]: r for r in _annual_fundamental_rows(facts, _EPS_TAGS)}
    rows: list[dict] = []
    for end in sorted(set(revenue_rows) | set(eps_rows)):
        rev, eps = revenue_rows.get(end), eps_rows.get(end)
        filed = min(r["filed"] for r in (rev, eps) if r is not None)
        rows.append(
            {
                "end": end,
                "filed": filed,
                "revenue": rev["value"] if rev else None,
                "eps": eps["value"] if eps else None,
            }
        )
    return rows


@mcp.tool()
def backtest_picker(
    tickers: list[str],
    years: int = 5,
    horizon_months: int = 6,
    benchmark: str = "VWCE.MI",
) -> dict:
    """Disclosed PROXY backtest of the picker's ranking logic (portfolio.picker_backtest) on
    live free data: for each ticker, fetches price history (yfinance, tier B), earnings-
    surprise history (yfinance, tier B, see providers.yfinance_surprises), analyst rating-
    change events (yfinance, tier B, US-listed/ADR only) and as-filed annual fundamentals
    (SEC EDGAR XBRL, tier A, US filers only), then replays a quarterly-rebalance top-quintile
    strategy against `benchmark`. This is NOT the production scorer (scoring/engine.py) --
    it is a narrower, point-in-time-honest proxy answering "would this ranking logic have
    beaten the benchmark on past data". Every mandatory disclosure (survivorship bias --
    today's tickers only --, Yahoo backfill risk, no transaction costs, event-dated not
    true point-in-time consensus revisions) is always returned under `disclosures`; a
    ticker/benchmark with no usable price history is skipped and reported, never invented."""
    reference = date.today()
    try:
        benchmark_closes = provider.get_monthly_closes({"benchmark": benchmark}, period="max")
    except Exception as exc:
        return {
            "ok": False,
            "error": f"Could not fetch benchmark {benchmark}: {type(exc).__name__}: {exc}",
        }
    if "benchmark" not in benchmark_closes.columns or benchmark_closes["benchmark"].dropna().empty:
        return {"ok": False, "error": f"No usable price history for benchmark {benchmark}"}
    benchmark_prices = benchmark_closes["benchmark"].dropna()

    universe: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    for ticker in tickers:
        symbol = ticker.strip().upper()
        try:
            closes = provider.get_monthly_closes({symbol: symbol}, period="max")
        except Exception as exc:
            skipped[symbol] = f"{type(exc).__name__}: {exc}"
            continue
        if symbol not in closes.columns or closes[symbol].dropna().empty:
            skipped[symbol] = "no usable price history"
            continue
        prices = closes[symbol].dropna()

        try:
            surprise_history = surprises_module.fetch_surprise_history(
                symbol, reference, ticker_factory=yf.Ticker
            )
            surprises = [q.model_dump(mode="json") for q in surprise_history.quarters]
        except Exception:
            surprises = []

        try:
            rating_events = estimates_module.fetch_rating_events(
                symbol, reference, ticker_factory=yf.Ticker
            )
        except Exception:
            rating_events = []

        universe[symbol] = {
            "prices": prices,
            "surprises": surprises,
            "fundamentals": _fetch_asfiled_fundamentals(symbol),
            "rating_events": rating_events,
        }

    if not universe:
        return {"ok": False, "error": "No ticker had usable price history", "skipped": skipped}

    last_date = benchmark_prices.index.max()
    cutoff = last_date - pd.DateOffset(months=horizon_months)
    start = last_date - pd.DateOffset(years=years)
    rebalance_dates = [ts.date() for ts in pd.date_range(start=start, end=cutoff, freq="QE")]
    if not rebalance_dates:
        return {
            "ok": False,
            "error": "No rebalance date fits the requested years/horizon_months window",
        }

    result = picker_backtest_module.run_proxy_backtest(
        universe=universe,
        benchmark_prices=benchmark_prices,
        rebalance_dates=rebalance_dates,
        horizon_months=horizon_months,
    )
    result["ok"] = True
    result["tickers_used"] = sorted(universe)
    result["skipped"] = skipped
    result["benchmark"] = benchmark
    return result


@mcp.prompt()
def portfolio_review(path: str) -> str:
    """Orchestrate a complete portfolio review."""
    return f"""
Review the portfolio export at: {path}

Use MCP tools, not mental arithmetic.
1. Parse the portfolio.
2. Compute portfolio risk and concentration.
3. Identify duplicate/redundant exposures where data permits.
4. Separate core, satellite and leveraged exposure.
5. Do not recommend trades merely to create activity.
6. Return BUY/HOLD/WATCH/REDUCE/SELL only when supported by evidence.
7. State missing data and uncertainty.
8. Never execute trades.
"""


@mcp.prompt()
def stock_picker(tickers: str) -> str:
    """Rank a comma-separated candidate universe."""
    return f"""
Run a stock-picking review on this candidate universe:
{tickers}

Use screen_stocks on the parsed ticker list.
Then:
- show top ideas;
- separate Quality, Growth/Momentum and Asymmetric/High Risk;
- include score and confidence;
- do not call a stock BUY solely because of the score;
- consider portfolio constraints if portfolio context is available;
- NO BUY is a valid outcome.
"""


@mcp.prompt()
def rebalance(path: str, cash_eur: float) -> str:
    """Guide a fee-aware portfolio rebalance."""
    return f"""
Rebalance the portfolio export at {path} with {cash_eur:.2f} EUR of new cash.
Prefer cash-flow rebalancing, minimize sells and transaction costs, respect configured
risk limits, and produce a manual order plan only.
"""


@mcp.prompt()
def deploy_cash(path: str, cash_eur: float) -> str:
    """Decide how to deploy new cash across existing targets and new ideas."""
    return f"""
I have {cash_eur:.2f} EUR of new capital and portfolio file {path}.
First analyze current portfolio concentration and drift.
Then decide whether the best action is:
- add to existing core;
- add to an existing stock;
- introduce a new candidate;
- hold cash.
Do not force an investment.
All order suggestions must account for fees and remain manual-only.
"""


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
