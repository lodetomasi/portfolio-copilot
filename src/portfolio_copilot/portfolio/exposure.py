"""Hidden-exposure graph: theme/driver classification and portfolio-level rollup.

A "good sector label" hides a lot: a small-cap ETF can still be mostly global equity
beta, a chip stock and an "AI software" fund can both lean on the same ai_capex driver,
and a 5x certificate multiplies whatever underlying theme it tracks. This module reads
the curated ``config/exposure_graph.yaml`` (themes -> keywords + shared macro/factor
drivers) and turns it into:

- ``classify``: one instrument -> its themes and drivers (deterministic keyword match,
  never a guess -- an instrument matching nothing is ``"unclassified"``);
- ``portfolio_exposure``: a whole portfolio -> weight per theme and per driver, plus a
  separate leverage-adjusted ``equivalent`` map (CLAUDE.md: leverage is shown, never
  folded into the nominal weight, and is not a VaR substitute);
- ``fit_score``: how much a new candidate would pile onto exposure the portfolio
  already carries, for portfolio-aware BUY screening.

Pure functions; no I/O beyond loading the YAML graph itself.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GRAPH_PATH = REPO_ROOT / "config" / "exposure_graph.yaml"


def _coerce_float(value: object, default: float = 0.0) -> float:
    """Best-effort float coercion for a holding field (market_value/leverage) supplied by
    an arbitrary caller (not necessarily the vetted broker-export parser): ``None``, a
    blank/unparsable string, or a non-finite float (NaN/Infinity) all degrade to
    ``default`` instead of raising or poisoning downstream aggregates. Handles the same
    Italian-locale number formats (``"1.234,56"``) as ``parsers/broker_export.py``."""
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value) if math.isfinite(value) else default

    text = str(value).strip().replace("\xa0", "").replace("€", "").replace("$", "")
    text = text.replace("%", "")
    if not text:
        return default
    if "," in text and "." in text and text.rfind(",") > text.rfind("."):
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    text = re.sub(r"[^0-9.\-+]", "", text)
    if not text:
        return default
    try:
        parsed = float(text)
    except ValueError:
        return default
    return parsed if math.isfinite(parsed) else default


class ThemeDefinition(BaseModel):
    """One theme node: the keywords that identify it and the drivers it exposes."""

    keywords: list[str] = Field(min_length=1)
    drivers: list[str] = Field(min_length=1)

    @field_validator("keywords", "drivers")
    @classmethod
    def _no_blank_entries(cls, value: list[str]) -> list[str]:
        if any(not str(item).strip() for item in value):
            raise ValueError("keywords/drivers entries must be non-empty strings")
        return value


class ExposureGraph(BaseModel):
    """Validated curated theme graph loaded from YAML."""

    themes: dict[str, ThemeDefinition] = Field(min_length=1)


@lru_cache(maxsize=8)
def _load_validated(path_str: str, mtime: float) -> dict:
    raw = yaml.safe_load(Path(path_str).read_text(encoding="utf-8")) or {}
    graph = ExposureGraph.model_validate(raw)
    return graph.model_dump()


def load_graph(path: Path | str | None = None) -> dict:
    """Load and validate the curated hidden-exposure theme graph.

    ``path`` defaults to ``config/exposure_graph.yaml``. Every theme must declare at
    least one keyword and one driver; a malformed or empty file raises
    ``pydantic.ValidationError`` rather than degrading silently -- CLAUDE.md forbids
    inventing missing data, and a broken theme definition is exactly that. A missing
    file raises ``FileNotFoundError`` with no fallback.

    Cached by (path, mtime): a hand-edit to the YAML (this file's own header invites
    editing it by hand) is picked up on the next call in the same process, instead of
    silently serving a stale, pre-edit result until restart.
    """
    candidate = Path(path) if path is not None else DEFAULT_GRAPH_PATH
    if not candidate.exists():
        raise FileNotFoundError(f"Exposure graph config not found: {candidate}")
    return _load_validated(str(candidate), candidate.stat().st_mtime)


def classify(
    name: str,
    sector: str | None = None,
    industry: str | None = None,
    asset_type: str | None = None,
    leverage: float = 1.0,
    *,
    graph: dict | None = None,
) -> dict:
    """Classify one instrument into hidden-exposure themes and macro/factor drivers.

    Matching is a deterministic, case-insensitive substring search of each theme's
    curated keywords against ``name``/``sector``/``industry`` joined together -- no
    inference beyond that. An instrument can legitimately carry more than one theme
    (e.g. a "MSCI World Small Cap" ETF is both ``global_equity_core`` and
    ``small_cap``); that overlap is the point of the graph.

    A leveraged instrument (``asset_type == "certificate"`` or ``abs(leverage) > 1.0``)
    always additionally carries ``leveraged_certificates`` (driver ``leverage_decay``)
    on top of whatever underlying theme its name/sector/industry matched, if any.

    An instrument matching no theme comes back as ``{"themes": ["unclassified"],
    "drivers": []}`` rather than a guess.

    Returns ``{"themes": list[str], "drivers": list[str]}`` (drivers de-duplicated and
    sorted for deterministic output).
    """
    graph = graph if graph is not None else load_graph()
    themes_graph = graph["themes"]

    text = " ".join(
        value for value in (name, sector, industry) if isinstance(value, str) and value.strip()
    ).lower()

    themes: list[str] = []
    drivers: set[str] = set()
    for theme_name, theme_def in themes_graph.items():
        if any(keyword.lower() in text for keyword in theme_def["keywords"]):
            themes.append(theme_name)
            drivers.update(theme_def["drivers"])

    is_leveraged = (isinstance(asset_type, str) and asset_type.lower() == "certificate") or abs(
        leverage
    ) > 1.0
    if is_leveraged and "leveraged_certificates" not in themes:
        themes.append("leveraged_certificates")
        # Degrade rather than crash if a caller-supplied/reduced graph omits this theme
        # (the default, checked-in graph always defines it): the leveraged tag is still
        # recorded, just without drivers to pull from.
        drivers.update((themes_graph.get("leveraged_certificates") or {}).get("drivers") or [])

    if not themes:
        return {"themes": ["unclassified"], "drivers": []}
    return {"themes": themes, "drivers": sorted(drivers)}


def portfolio_exposure(holdings: list[dict], *, graph: dict | None = None) -> dict:
    """Aggregate a portfolio's holdings into hidden-exposure theme/driver weights.

    Each holding is classified independently via ``classify``; because one instrument
    can carry several themes, theme and driver weights are NOT constrained to sum to
    1.0 -- that overlap is exactly what a hidden-exposure view is for.

    Nominal weights are ``market_value / total_value``. A separate ``equivalent`` map
    (``{"themes": {...}, "drivers": {...}}``) uses ``market_value * abs(leverage)``
    instead, so a leveraged certificate's true thematic pull is visible without
    conflating it with the nominal weight (see CLAUDE.md: the leveraged equivalent is
    an intuitive metric, never a VaR substitute).

    An empty portfolio, or one whose holdings all carry zero/missing ``market_value``,
    returns all-empty maps rather than dividing by zero.
    """
    graph = graph if graph is not None else load_graph()

    theme_nominal: dict[str, float] = {}
    theme_equivalent: dict[str, float] = {}
    driver_nominal: dict[str, float] = {}
    driver_equivalent: dict[str, float] = {}
    unclassified_value = 0.0
    total_value = 0.0

    for holding in holdings:
        market_value = _coerce_float(holding.get("market_value"), default=0.0)
        total_value += market_value

        leverage = _coerce_float(holding.get("leverage"), default=1.0)
        equivalent_value = market_value * abs(leverage)

        result = classify(
            name=holding.get("name") or "",
            sector=holding.get("sector"),
            industry=holding.get("industry"),
            asset_type=holding.get("asset_type"),
            leverage=leverage,
            graph=graph,
        )

        if result["themes"] == ["unclassified"]:
            unclassified_value += market_value
            continue

        for theme in result["themes"]:
            theme_nominal[theme] = theme_nominal.get(theme, 0.0) + market_value
            theme_equivalent[theme] = theme_equivalent.get(theme, 0.0) + equivalent_value
        for driver in result["drivers"]:
            driver_nominal[driver] = driver_nominal.get(driver, 0.0) + market_value
            driver_equivalent[driver] = driver_equivalent.get(driver, 0.0) + equivalent_value

    if not math.isfinite(total_value) or total_value <= 0:
        return {
            "total_value": 0.0,
            "themes": {},
            "drivers": {},
            "equivalent": {"themes": {}, "drivers": {}},
            "unclassified_weight": 0.0,
        }

    return {
        "total_value": total_value,
        "themes": {theme: value / total_value for theme, value in theme_nominal.items()},
        "drivers": {driver: value / total_value for driver, value in driver_nominal.items()},
        "equivalent": {
            "themes": {theme: value / total_value for theme, value in theme_equivalent.items()},
            "drivers": {driver: value / total_value for driver, value in driver_equivalent.items()},
        },
        "unclassified_weight": unclassified_value / total_value,
    }


def fit_score(candidate: dict, exposure: dict, caps: dict | None = None) -> dict:
    """Score how much a candidate instrument overlaps the portfolio's existing exposure.

    ``candidate`` is a ``classify()``-shaped dict (``{"themes": [...], "drivers":
    [...]}``); ``exposure`` is a ``portfolio_exposure()``-shaped dict. ``fit`` starts at
    1.0 (fully additive / diversifying) and is reduced by the nominal weight the
    portfolio already holds in any driver the candidate shares with it:
    ``fit = 1 - min(1, shared_driver_weight)``.

    ``fit`` is forced to 0.0, regardless of driver overlap, if any of the candidate's
    themes has already reached its cap in ``caps`` (``theme -> max_weight``) -- a
    capped theme is a hard stop, not a diversification trade-off.

    Returns ``{"fit": float, "overlap_drivers": list[str], "reasons": list[str]}``.
    """
    driver_weights = exposure.get("drivers") or {}
    candidate_drivers = candidate.get("drivers") or []
    overlap_drivers = sorted(
        driver for driver in candidate_drivers if driver_weights.get(driver, 0.0) > 0.0
    )
    shared_driver_weight = sum(driver_weights.get(driver, 0.0) for driver in overlap_drivers)

    reasons: list[str] = []
    if overlap_drivers:
        reasons.append(
            f"shares driver(s) {', '.join(overlap_drivers)}, already "
            f"{shared_driver_weight:.1%} of the portfolio"
        )

    theme_weights = exposure.get("themes") or {}
    candidate_themes = candidate.get("themes") or []
    breached_themes = sorted(
        theme
        for theme in candidate_themes
        if caps and caps.get(theme) is not None and theme_weights.get(theme, 0.0) >= caps[theme]
    )

    if breached_themes:
        fit = 0.0
        reasons.append(f"theme cap already reached for {', '.join(breached_themes)}")
    else:
        fit = 1.0 - min(1.0, shared_driver_weight)

    return {"fit": round(fit, 4), "overlap_drivers": overlap_drivers, "reasons": reasons}
