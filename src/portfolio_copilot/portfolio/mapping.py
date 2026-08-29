"""Deterministic holding -> target-bucket mapping.

Decides, for every line of a parsed portfolio, whether it belongs to one of the
allocation buckets in a model portfolio's ``targets`` (e.g. ``global_equity``,
``small_cap``, ``emerging_markets``, ``global_bonds_hedged``) or is a satellite
position (certificate, leveraged instrument, single stock) that intentionally sits
outside the target-bucket system. No network calls, no scoring, no invented data --
pure arithmetic and string matching over the caller's own holdings.

Rule order:
1. Exact ISIN match against ``instruments[bucket]["isin"]`` -- always wins, satellite or not.
2. Certificates, leveraged instruments (``abs(leverage) > 1``, either direction) and
   single stocks (``asset_type == "equity"``) are always satellite -> unmapped, even when
   their name also happens to match a bucket keyword (e.g. a leveraged World ETF).
3. Case-insensitive name keywords, for anything not already satellite (small-cap checked
   before "world" so a fund whose name matches both, e.g. "MSCI World Small Cap", is
   filed under ``small_cap``).
4. Anything else that matched nothing above is still reported, under a generic
   "no rule matched" reason, so it is never silently dropped from coverage.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from portfolio_copilot.models import AssetType
from portfolio_copilot.portfolio.exposure import _coerce_float

_SMALL_CAP_KEYWORDS = ("small cap", "small-cap")
_WORLD_KEYWORDS = ("all-world", "all world", "msci world", "acwi", "s&p 500", "developed world")
_EMERGING_KEYWORDS = ("emerging",)
_BOND_KEYWORDS = ("aggregate bond", "bond", "obbligaz", "treasury", "govt")

WHY_CERTIFICATE = "certificate"
WHY_LEVERAGED = "leveraged"
WHY_SINGLE_STOCK_EQUITY = "single_stock_equity"
WHY_NO_RULE_MATCHED = "no_bucket_rule_matched"


def _isin_to_bucket(instruments: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """Reverse-index ``instruments`` by ISIN. Buckets with no (or blank) ISIN are skipped.

    Raises ``ValueError`` if the same ISIN is registered under two different buckets --
    a config-authoring mistake (e.g. copy-paste when adding a bucket) that must never be
    silently resolved by whichever bucket happens to be last in iteration order.
    """
    reverse: dict[str, str] = {}
    for bucket, info in instruments.items():
        isin = (info or {}).get("isin")
        if not isin:
            continue
        key = str(isin).strip().upper()
        if key in reverse and reverse[key] != bucket:
            raise ValueError(
                f"instruments config is ambiguous: ISIN {key} is registered under both "
                f"{reverse[key]!r} and {bucket!r}"
            )
        reverse[key] = bucket
    return reverse


def _keyword_bucket(name: str) -> tuple[str, str] | None:
    """First keyword rule matched by ``name``, as ``(bucket, rule_label)``, or ``None``."""
    lowered = name.lower()
    if any(keyword in lowered for keyword in _SMALL_CAP_KEYWORDS):
        return "small_cap", "name_keyword_small_cap"
    if any(keyword in lowered for keyword in _WORLD_KEYWORDS):
        return "global_equity", "name_keyword_global_equity"
    if any(keyword in lowered for keyword in _EMERGING_KEYWORDS):
        return "emerging_markets", "name_keyword_emerging_markets"
    if any(keyword in lowered for keyword in _BOND_KEYWORDS):
        return "global_bonds_hedged", "name_keyword_global_bonds_hedged"
    return None


def _is_satellite(asset_type: Any, leverage: float) -> bool:
    """True for a certificate, leveraged instrument (either direction -- an inverse/short
    ETP has negative leverage) or single stock: always satellite, never bucketed by a
    name-keyword match even when the name happens to contain one (rule 3 pre-empts rule 2:
    a leveraged/certificate/single-stock holding is satellite regardless of its name)."""
    return (
        asset_type == AssetType.CERTIFICATE
        or abs(leverage) > 1.0
        or asset_type == AssetType.EQUITY
    )


def _unmapped_reason(asset_type: Any, leverage: float) -> str:
    """Why a holding that matched no ISIN/keyword rule stays out of the target buckets."""
    if asset_type == AssetType.CERTIFICATE:
        return WHY_CERTIFICATE
    if abs(leverage) > 1.0:
        return WHY_LEVERAGED
    if asset_type == AssetType.EQUITY:
        return WHY_SINGLE_STOCK_EQUITY
    return WHY_NO_RULE_MATCHED


def map_holdings(
    holdings: Sequence[Mapping[str, Any]],
    targets: Mapping[str, float],
    instruments: Mapping[str, Mapping[str, Any]],
    isin_resolver: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    """Assign each holding to a target allocation bucket, or explain why it can't be.

    Args:
        holdings: parsed holdings as plain dicts (``Portfolio.model_dump()["holdings"]``
            shape: ``name``, ``isin``, ``asset_type``, ``market_value``, ``leverage``, ...).
        targets: the model portfolio's bucket -> target weight map.
        instruments: bucket -> {"name", "isin", "yf_ticker"} for the same profile
            (``portfolio.plan.load_model_portfolios(...)["instruments"]``).
        isin_resolver: optional ``isin -> ticker | None`` lookup (e.g.
            ``providers.openfigi.OpenFIGIProvider.yf_ticker_for``), tried on a satellite
            holding (single stock, certificate, leveraged instrument) that carries an ISIN
            but no ``symbol`` of its own, so a caller can still price it even though it
            stays outside the target-bucket system. Never required: omitted (the default),
            or a failed/empty lookup, leaves that holding's ``unmapped`` entry exactly as
            before -- no ``resolved_ticker`` key at all -- so this never invents a ticker
            and never changes bucket assignment, only adds a purely additive field when a
            resolution actually succeeds. Any exception it raises is swallowed the same way
            (degrade, never let one bad lookup crash the whole mapping pass).

    Returns:
        ``current_values``: EUR value currently held per bucket in ``targets`` (0.0 for a
            bucket with no matching holding, so this dict can be passed straight to
            :func:`portfolio_copilot.portfolio.rebalance.allocate_cash_to_targets` as
            ``current_values``); a holding that maps to a bucket outside ``targets`` still
            adds its own key, valued at its summed market value.
        ``mapped``: one ``{"name", "bucket", "rule"}`` entry per matched holding.
        ``unmapped``: one ``{"name", "asset_type", "market_value", "why"}`` entry per
            satellite / unrecognized holding, plus ``"resolved_ticker"`` when
            ``isin_resolver`` was given and successfully resolved that holding's ISIN.
        ``coverage``: mapped value / total portfolio value (``0.0`` when the portfolio
            is empty or worth nothing, never a division by zero).
    """
    isin_to_bucket = _isin_to_bucket(instruments)
    current_values: dict[str, float] = {bucket: 0.0 for bucket in targets}
    mapped: list[dict[str, Any]] = []
    unmapped: list[dict[str, Any]] = []
    total_value = 0.0
    mapped_value = 0.0

    for holding in holdings:
        name = holding.get("name", "")
        market_value = _coerce_float(holding.get("market_value"), default=0.0)
        total_value += market_value
        asset_type = holding.get("asset_type")
        leverage = _coerce_float(holding.get("leverage"), default=1.0)
        satellite = _is_satellite(asset_type, leverage)

        bucket: str | None = None
        rule: str | None = None

        isin = holding.get("isin")
        if isin:
            bucket = isin_to_bucket.get(str(isin).strip().upper())
            if bucket is not None:
                rule = "isin_exact_match"

        # Rule 3 (certificate/leveraged/single-stock -> always satellite) pre-empts rule 2
        # (name keywords): a leveraged/certificate/equity holding never gets bucketed by a
        # name-keyword match even when its product name happens to contain one.
        if bucket is None and not satellite:
            keyword_match = _keyword_bucket(str(name))
            if keyword_match is not None:
                bucket, rule = keyword_match

        if bucket is not None:
            current_values[bucket] = current_values.get(bucket, 0.0) + market_value
            mapped.append({"name": name, "bucket": bucket, "rule": rule})
            mapped_value += market_value
            continue

        entry = {
            "name": name,
            "asset_type": asset_type,
            "market_value": market_value,
            "why": _unmapped_reason(asset_type, leverage),
        }
        if isin_resolver is not None and isin and not holding.get("symbol"):
            try:
                resolved = isin_resolver(str(isin).strip().upper())
            except Exception:
                resolved = None
            if resolved:
                entry["resolved_ticker"] = resolved
        unmapped.append(entry)

    coverage = mapped_value / total_value if total_value > 0 else 0.0

    return {
        "current_values": current_values,
        "mapped": mapped,
        "unmapped": unmapped,
        "coverage": coverage,
    }
