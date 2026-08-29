"""Potential-ranking and informational tagging for the stock picker.

User principle (binding, see CLAUDE.md): the picker ranks by POTENTIAL across the whole
universe -- huge companies and small ones in the same net -- with NO exclusion by size,
index membership or overlap. Overlap with the core ETF, sector concentration and size are
INFORMATION shown next to each idea (tags/notes), never filters. Only the risk caps
(single stock, growth, high-risk, speculative bucket) and the red-team gate limit a BUY;
they never remove an idea from this ranking.

Pure functions over the plain-dict shape produced by ``StockScore.model_dump(mode="json")``:
``{ticker, score, confidence, category, components: [...], snapshot: {market_cap, sector,
industry, ...}, ...}``. Every helper reads with ``.get()`` and degrades to ``None``/empty
rather than raising on a partial or hand-built dict.
"""

from __future__ import annotations

import math
from collections import Counter
from typing import Any

from portfolio_copilot.portfolio.exposure import classify, fit_score

# market_cap (in the snapshot's currency, usually USD/EUR-ish order of magnitude) -> bucket.
# Checked largest-first; the first threshold a cap meets or exceeds wins.
_SIZE_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (200e9, "mega"),
    (10e9, "large"),
    (2e9, "mid"),
    (300e6, "small"),
    (50e6, "micro"),
)

_CORE_OVERLAP_NOTE = "likely a large weight in a global index ETF you already hold"

SHORTLIST_NOTE = (
    "Ranked by potential across all sizes; nothing excluded. Overlap and concentration "
    "are information, caps and the red team decide the size."
)


def _size_bucket(market_cap: float | None) -> str | None:
    """Bucket a market cap into mega/large/mid/small/micro/nano; ``None`` when the
    market cap itself is unknown or non-finite (NaN/inf) -- never guessed (CLAUDE.md
    #6). Below $50mln (true penny-stock territory) is "nano", never folded into
    "micro" -- the label must not understate that risk."""
    if market_cap is None or not math.isfinite(market_cap):
        return None
    for threshold, name in _SIZE_THRESHOLDS:
        if market_cap >= threshold:
            return name
    return "nano"


def _risk_cap_pct(category: str | None, caps: dict) -> float | None:
    """Map a score ``category`` (scoring/engine.py's ``score_snapshot`` labels) to the
    matching per-stock risk-limit cap. A category the caller's caps dict doesn't cover
    (e.g. "UNRATED / NO DATA", or a caps dict missing the key) comes back ``None`` rather
    than an invented number."""
    category = category or ""
    if "Asymmetric" in category or "High Risk" in category:
        return caps.get("max_high_risk_stock_weight")
    if "Growth" in category:
        return caps.get("max_growth_stock_weight")
    if "Quality" in category:
        return caps.get("max_single_stock_weight")
    return None


def rank_by_potential(scored: list[dict], min_confidence: float = 0.0) -> list[dict]:
    """Rank candidates by potential: score desc, then confidence desc, then ticker asc.

    Never drops an item. An item whose confidence is below ``min_confidence`` stays in
    the list at its ranked position, with ``"low_confidence"`` added to its ``tags`` list
    instead of being removed -- confidence is information for the reader, not a filter.
    """
    ranked: list[dict] = []
    for item in scored:
        copy_item = dict(item)
        tags = list(copy_item.get("tags") or [])
        if copy_item.get("confidence", 0.0) < min_confidence and "low_confidence" not in tags:
            tags.append("low_confidence")
        copy_item["tags"] = tags
        ranked.append(copy_item)

    ranked.sort(
        key=lambda it: (
            -(it.get("score") or 0.0),
            -(it.get("confidence") or 0.0),
            it.get("ticker") or "",
        )
    )
    return ranked


def annotate(item: dict, exposure: dict | None, caps: dict) -> dict:
    """Attach informational tags to one ranked candidate. Adds:

    - ``size_bucket``: mega/large/mid/small/micro/nano/``None`` from the snapshot's
      market cap.
    - ``risk_cap_pct``: the per-stock risk-limit cap its category maps to (``None`` if
      the category has none, e.g. no usable data).
    - ``core_overlap_note``: an informational string for a mega-cap candidate -- likely
      already a large weight in a global index ETF the user holds. Note, not a filter.
      Gated on the actual exposure evidence when available: with no portfolio context
      (``exposure is None``) the static mega-cap heuristic is the best available signal,
      but when real exposure evidence is given and shows no overlap (``diversification``
      at/above the same 0.5 threshold used for "core-like"), the note is suppressed
      rather than contradicting that evidence.
    - ``themes``/``drivers``: the candidate's hidden-exposure classification.
    - ``diversification``: 0..1 fit against the portfolio's existing exposure (via
      ``portfolio.exposure.fit_score``) when ``exposure`` is given, else ``None``.
      Informational: it never removes the candidate, only describes overlap.
    - ``lane``: ``"core-like"`` (mega cap AND heavy overlap with existing exposure),
      ``"speculative"`` (Asymmetric/High Risk category), else ``"diversifying"``. Checked
      in that order, so a mega/high-overlap Asymmetric pick reads as core-like: size and
      overlap describe *how* it enters the portfolio even for a spicy score category.
      A ``screen_stocks`` failure placeholder (``item.get("error")`` truthy -- no usable
      snapshot at all) short-circuits to ``lane="error"`` instead of a fabricated-looking
      "diversifying" micro/unknown-size company.

    None of these fields ever remove ``item`` from a list -- they are read-only context
    for the human/red-team decision, per the user's binding no-exclusion principle.
    """
    result = dict(item)
    if item.get("error"):
        # A fetch/scoring failure, not a genuinely scored (if data-poor) candidate --
        # never let it masquerade as one (finding 13).
        result["size_bucket"] = None
        result["risk_cap_pct"] = None
        result["core_overlap_note"] = None
        result["themes"] = []
        result["drivers"] = []
        result["diversification"] = None
        result["lane"] = "error"
        return result

    snapshot = item.get("snapshot") or {}
    category = item.get("category") or ""

    size_bucket = _size_bucket(snapshot.get("market_cap"))
    result["size_bucket"] = size_bucket
    result["risk_cap_pct"] = _risk_cap_pct(category, caps or {})

    themes: list[str] = []
    drivers: list[str] = []
    diversification: float | None = None
    if exposure is not None:
        candidate = classify(
            name=item.get("ticker") or "",
            sector=snapshot.get("sector"),
            industry=snapshot.get("industry"),
        )
        themes = candidate["themes"]
        drivers = candidate["drivers"]
        diversification = fit_score(candidate, exposure)["fit"]

    result["themes"] = themes
    result["drivers"] = drivers
    result["diversification"] = diversification

    if size_bucket == "mega":
        if exposure is None:
            core_overlap_note = _CORE_OVERLAP_NOTE
        elif diversification is not None and diversification < 0.5:
            core_overlap_note = _CORE_OVERLAP_NOTE
        else:
            core_overlap_note = None
    else:
        core_overlap_note = None
    result["core_overlap_note"] = core_overlap_note

    is_high_risk_category = "Asymmetric" in category or "High Risk" in category
    if size_bucket == "mega" and diversification is not None and diversification < 0.5:
        lane = "core-like"
    elif is_high_risk_category:
        lane = "speculative"
    else:
        lane = "diversifying"
    result["lane"] = lane

    return result


def _sector_concentration(annotated: list[dict]) -> dict[str, Any]:
    """Share of ``annotated`` sitting in its single most common known sector, with a
    warning string once that share exceeds 50%. Items with no sector on file are excluded
    from the count (an unknown sector cannot evidence concentration) but still count in
    the denominator via ``len(annotated)``, so a shortlist thin on sector data reports a
    correspondingly lower, honest share rather than an inflated one over known-only items.
    """
    sectors = [(item.get("snapshot") or {}).get("sector") for item in annotated]
    known = [s for s in sectors if s]
    total = len(annotated)

    if not known or total == 0:
        return {"sector": None, "share": 0.0, "warning": None}

    counts = Counter(known)
    max_count = max(counts.values())
    top_sector = sorted(sector for sector, count in counts.items() if count == max_count)[0]
    share = max_count / total

    warning = None
    if share > 0.5:
        warning = f"{top_sector} is {share:.0%} of the shortlist -- concentration risk"
    return {"sector": top_sector, "share": round(share, 4), "warning": warning}


def _size_mix(annotated: list[dict]) -> dict[str, int]:
    """Count of each ``size_bucket`` across ``annotated`` (``"unknown"`` for a missing
    market cap)."""
    counts: dict[str, int] = {}
    for item in annotated:
        key = item.get("size_bucket") or "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _available_components(annotated: list[dict]) -> dict[str, dict[str, int]]:
    """Per score component (growth/quality/valuation/...), how many of ``annotated`` had
    usable data for it vs. how many were scored at all -- a coverage readout, not a rank."""
    stats: dict[str, dict[str, int]] = {}
    for item in annotated:
        for component in item.get("components") or []:
            name = component.get("name")
            if not name:
                continue
            entry = stats.setdefault(name, {"available": 0, "total": 0})
            entry["total"] += 1
            if component.get("available"):
                entry["available"] += 1
    return stats


def shortlist(
    scored: list[dict],
    exposure: dict | None,
    caps: dict,
    top_n: int = 10,
    min_confidence: float = 0.0,
) -> dict:
    """Rank the whole universe by potential and annotate the top ``top_n`` for display.

    ``top_n`` only bounds how many candidates appear in ``"ranked"`` here -- it is a
    display limit, not a screen: ``rank_by_potential`` (called internally) still ranks
    every candidate in ``scored`` and drops none of them, and the summary stats below are
    computed from that FULL ranked-and-annotated universe, not just the display slice.

    ``min_confidence`` is forwarded to ``rank_by_potential`` so a caller can surface the
    ``"low_confidence"`` tag on thin-coverage candidates; it never removes anything.

    A ``screen_stocks`` failure placeholder (``item.get("error")`` truthy) is annotated
    with ``lane="error"`` and excluded from every summary statistic (it is not a
    genuinely scored, if data-poor, candidate) but still appears in ``"ranked"`` so the
    caller can see it happened.

    Returns ``{"ranked": [...annotated top_n...], "summary": {"sector_concentration",
    "size_mix", "available_components", "note"}}``.
    """
    full_ranked = rank_by_potential(scored, min_confidence=min_confidence)
    annotated_full = [annotate(item, exposure, caps) for item in full_ranked]
    scoreable = [item for item in annotated_full if item.get("lane") != "error"]

    return {
        "ranked": annotated_full[:top_n],
        "summary": {
            "sector_concentration": _sector_concentration(scoreable),
            "size_mix": _size_mix(scoreable),
            "available_components": _available_components(scoreable),
            "note": SHORTLIST_NOTE,
        },
    }
