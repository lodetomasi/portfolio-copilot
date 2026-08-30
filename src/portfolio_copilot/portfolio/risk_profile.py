"""Risk-profile questionnaire, deterministic profile mapping, and drawdown budgeting.

Six fixed questions map to a model-portfolio profile name (``config/model_portfolios.yaml``)
via a deterministic decision table -- never an LLM judgement (CLAUDE.md rule 8). The answers
and the derived profile are persisted so the questionnaire is asked once and then remembered
across sessions ("le domande le deve fare sempre e tenerle in memoria" -- read on every use,
re-asked only on explicit request or at the stored re-ask policy date; a re-ask appends to
``history`` and never silently overwrites the previous answer set).

``drawdown_budget``/``fits`` turn a set of bucket targets plus per-bucket observed and
stress drawdowns into a weighted worst case and a plain-language verdict. Never invents a
missing bucket's drawdown (CLAUDE.md rule 4): a bucket absent from the input degrades the
corresponding weighted figure to ``None`` and is listed under ``*_missing_buckets`` instead
of being silently skipped from the weighted sum.

Storage: ``risk_profile.json`` under ``PORTFOLIO_COPILOT_HOME`` (default ``data/private``,
git-ignored), mirroring the ``ledger_path``/``theses_path`` convention.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import pandas as pd
from pydantic import BaseModel

from portfolio_copilot.analytics.metrics import max_drawdown

DEFAULT_HOME = Path(__file__).resolve().parents[3] / "data" / "private"

MaxDrawdownPct = Literal[20, 35, 50, 70]
SpeculativeSharePct = Literal[0, 10, 25, 40, 60]
Leverage = Literal["none", "up_to_10", "up_to_25"]
Reaction = Literal["sell", "hold", "buy"]

# Weighted-worst-case stress assumptions per bucket, used when the caller does not supply
# (or only partially supplies) its own ``stress_dd``. These are explicit, declared
# assumptions -- not invented data -- documented here and in CLAUDE.md-adjacent docs.
DEFAULT_STRESS_DD: dict[str, float] = {
    "global_equity": -0.50,
    "small_cap": -0.60,
    "emerging_markets": -0.60,
    "thematic": -0.70,
    "single_stocks": -0.70,
    "global_bonds_hedged": -0.10,
}


def risk_profile_path(home: Path | str | None = None) -> Path:
    """Resolve (and create) the directory holding ``risk_profile.json``."""
    base = Path(home or os.environ.get("PORTFOLIO_COPILOT_HOME") or DEFAULT_HOME)
    base.mkdir(parents=True, exist_ok=True)
    return base / "risk_profile.json"


class RiskAnswers(BaseModel):
    """The six fixed questionnaire answers. Extra free-text notes (e.g. ``preferences``)
    are accepted and passed through by callers but are not part of the deterministic
    mapping -- only these six fields drive ``suggest_profile``/``derive_profile``."""

    max_drawdown_pct: MaxDrawdownPct
    speculative_share_pct: SpeculativeSharePct
    leverage: Leverage
    emergency_fund: bool
    horizon_years: float
    reaction_to_minus_30: Reaction


class DerivedProfile(BaseModel):
    """Result of mapping ``RiskAnswers`` to a model-portfolio profile name."""

    profile: str
    leverage_requested: bool = False
    leverage_note: str | None = None


def derive_profile(answers: RiskAnswers) -> DerivedProfile:
    """Deterministic mapping from answers to a model-portfolio profile name.

    Order (each check is a hard override of the ones after it):
    1. No emergency fund, or horizon < 3 years -> 'cautious' (capital preservation first,
       regardless of stated speculative appetite or leverage -- safety-net gap wins).
    2. Otherwise the base profile is 'growth' if horizon >= 8 years AND the stated
       reaction to a -30% year is not 'sell', else 'balanced'.
    3. If speculative_share_pct >= 25, the profile becomes 'aggressive_thematic'
       regardless of the base computed in step 2.
    A leverage answer other than 'none' never changes the profile name: it only sets
    ``leverage_requested`` so the caller can surface that leveraged daily-reset products
    are excluded from plans by design (never silently honoured, never silently dropped).
    """
    if not answers.emergency_fund or answers.horizon_years < 3:
        profile = "cautious"
    else:
        if answers.horizon_years >= 8 and answers.reaction_to_minus_30 != "sell":
            profile = "growth"
        else:
            profile = "balanced"
        if answers.speculative_share_pct >= 25:
            profile = "aggressive_thematic"

    leverage_requested = answers.leverage != "none"
    leverage_note = (
        "Leveraged/daily-reset products are excluded from plans by design; "
        f"'{answers.leverage}' leverage was requested but is NOT supported."
        if leverage_requested
        else None
    )
    return DerivedProfile(
        profile=profile, leverage_requested=leverage_requested, leverage_note=leverage_note
    )


def suggest_profile(answers: RiskAnswers) -> str:
    """Deterministic model-portfolio profile name for these answers. See ``derive_profile``
    for the leverage flag this discards; use ``derive_profile`` when that flag matters."""
    return derive_profile(answers).profile


def _weighted_worst_case(
    targets: dict[str, float], dd_map: dict[str, float]
) -> tuple[float | None, list[str]]:
    """Weighted sum of ``targets[bucket] * dd_map[bucket]``. A bucket in ``targets`` that
    has no entry in ``dd_map`` is never treated as 0% drawdown (that would understate the
    risk) -- it is listed as missing and the weighted figure degrades to ``None`` rather
    than reporting a partial sum that looks like a complete answer."""
    missing = [bucket for bucket in targets if bucket not in dd_map or dd_map[bucket] is None]
    if missing:
        return None, missing
    total = sum(weight * dd_map[bucket] for bucket, weight in targets.items())
    return total, []


def drawdown_budget(
    targets: dict[str, float],
    history_dd: dict[str, float],
    stress_dd: dict[str, float] | None = None,
) -> dict:
    """Weighted worst-case portfolio drawdown under 'observed' (``history_dd``, the actual
    max drawdown seen in each bucket's own history) and 'stress' (``stress_dd``, falling
    back to ``DEFAULT_STRESS_DD`` per bucket when not supplied)."""
    stress_map = dict(DEFAULT_STRESS_DD)
    if stress_dd:
        stress_map.update(stress_dd)

    observed, observed_missing = _weighted_worst_case(targets, history_dd)
    stress, stress_missing = _weighted_worst_case(targets, stress_map)
    return {
        "observed": observed,
        "observed_missing_buckets": observed_missing,
        "stress": stress,
        "stress_missing_buckets": stress_missing,
        "stress_dd_used": {bucket: stress_map.get(bucket) for bucket in targets},
    }


def fits(budget: dict, max_drawdown_pct: float) -> dict:
    """Booleans + plain-language verdict comparing a ``drawdown_budget`` result against the
    user's stated maximum drawdown tolerance (a positive percent, e.g. 35 for "-35%")."""
    stated = -abs(max_drawdown_pct) / 100.0
    observed = budget.get("observed")
    stress = budget.get("stress")
    fits_observed = observed is not None and observed >= stated
    fits_stress = stress is not None and stress >= stated

    stated_pct = f"{stated * 100:.0f}%"
    if observed is None or stress is None:
        gap = sorted(
            set(budget.get("observed_missing_buckets", []))
            | set(budget.get("stress_missing_buckets", []))
        )
        verdict = (
            f"your {stated_pct} target cannot be fully checked: drawdown data is missing "
            f"for {gap}."
        )
    elif fits_observed and fits_stress:
        verdict = (
            f"your {stated_pct} holds in both a 2020-type crash (observed ≈ {observed * 100:.0f}%) "
            f"and a 2008-type one (stress ≈ {stress * 100:.0f}%)."
        )
    elif fits_observed and not fits_stress:
        verdict = (
            f"your {stated_pct} holds in a 2020-type crash, not in a 2008-type one: "
            f"expect ≈ {stress * 100:.0f}%."
        )
    elif fits_stress and not fits_observed:
        verdict = (
            f"your {stated_pct} does not hold in a 2020-type crash (observed ≈ "
            f"{observed * 100:.0f}%), only in the 2008-type stress estimate "
            f"(≈ {stress * 100:.0f}%)."
        )
    else:
        verdict = (
            f"your {stated_pct} does not hold even in a 2020-type crash: expect ≈ "
            f"{observed * 100:.0f}% observed and ≈ {stress * 100:.0f}% in a 2008-type one."
        )
    return {"fits_observed": fits_observed, "fits_stress": fits_stress, "verdict": verdict}


def observed_drawdowns(provider, instruments: dict[str, str], period: str = "5y") -> dict:
    """Max drawdown per bucket from monthly closes, via any provider exposing
    ``get_monthly_closes(tickers: dict[bucket, ticker], period) -> pd.DataFrame`` with
    bucket-named columns and ``df.attrs['missing']`` listing buckets with no data (the same
    contract as ``providers.yfinance_provider.YFinanceProvider.get_monthly_closes``).

    Network happens inside ``provider`` at runtime; tests inject a fake/fixture-backed
    provider. A bucket with no data (missing from the frame, or listed in
    ``attrs['missing']``) degrades to ``None`` -- never invented.

    Each bucket is fetched with its OWN provider call: the provider inner-joins the
    requested buckets on shared dates (``pd.DataFrame(frames).dropna()``), so a single
    multi-bucket call would let a short-history bucket truncate every other bucket's
    history and silently erase a crash from its drawdown. Per-ticker caching in the
    real provider makes the per-bucket calls cost the same as one combined call.
    """
    out: dict[str, float | None] = {}
    for bucket, ticker in instruments.items():
        df = provider.get_monthly_closes({bucket: ticker}, period=period)
        missing = set(getattr(df, "attrs", {}).get("missing", []))
        if bucket in missing or not isinstance(df, pd.DataFrame) or bucket not in df.columns:
            out[bucket] = None
            continue
        series = df[bucket].dropna()
        out[bucket] = max_drawdown(series) if not series.empty else None
    return out


def save_risk_profile(
    answers: RiskAnswers | dict, derived: dict, home: Path | str | None = None
) -> dict:
    """Persist the questionnaire answers and derived result, appending to ``history``
    instead of silently overwriting a previous answer set (user requirement: the
    questionnaire is asked once, remembered, and every re-ask is recorded, never lost).

    ``derived`` is caller-assembled (typically ``derive_profile`` plus ``drawdown_budget``
    and ``fits`` output) so this module does not dictate its exact shape beyond persisting
    it as given.
    """
    answers_model = answers if isinstance(answers, RiskAnswers) else RiskAnswers(**dict(answers))
    answers_payload = (
        answers.copy() if isinstance(answers, dict) else json.loads(answers_model.model_dump_json())
    )
    today = datetime.now(UTC).date().isoformat()

    previous = load_risk_profile(home)
    history = list(previous.get("history", [])) if previous else []
    history.append(
        {
            "date": today,
            "event": "questionnaire re-answered" if previous else "first questionnaire answered",
        }
    )

    payload = {
        "as_of": today,
        "version": 1,
        "answers": answers_payload,
        "derived": derived,
        "reask_policy": (previous or {}).get(
            "reask_policy", "at annual review or on explicit request"
        ),
        "history": history,
    }

    path = risk_profile_path(home)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".risk_profile-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, indent=2, ensure_ascii=False))
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise
    return payload


def load_risk_profile(home: Path | str | None = None) -> dict | None:
    """Load the stored risk profile, or ``None`` if the questionnaire was never answered.

    Raises ``ValueError`` (``json.JSONDecodeError`` is a subclass) if the file is present
    but corrupted -- never silently drops or invents a profile.
    """
    path = risk_profile_path(home)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
