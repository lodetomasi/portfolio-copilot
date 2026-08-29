"""Thesis engine: falsifiable investment claims and their deterministic status over time.

A `Thesis` is a set of claims ("why I bought this") paired with `Falsifier`s -- concrete,
checkable conditions under which the claims would be wrong. Checking a thesis against a
fresh metrics snapshot never asks an LLM to judge whether the story still holds (see
CLAUDE.md rule 10: no LLM math/judgement where deterministic Python suffices); it only
compares numbers to thresholds and counts how many of the checkable falsifiers tripped.

A falsifier whose metric is missing from the snapshot is never treated as "did not trip":
it is reported as `unavailable` and excluded from the checkable count, so a thin data
snapshot degrades the verdict (or yields UNVERIFIABLE) instead of manufacturing confidence.

Storage: one JSON object (a dict keyed by uppercase symbol) in ``theses.json`` under
``PORTFOLIO_COPILOT_HOME`` (default ``data/private``, git-ignored), mirroring the
``ledger_path`` convention in ``portfolio/ledger.py``.
"""

from __future__ import annotations

import json
import math
import operator
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

DEFAULT_HOME = Path(__file__).resolve().parents[3] / "data" / "private"

ThesisStatus = Literal["STABLE", "STRENGTHENING", "WEAKENING", "BROKEN", "UNVERIFIABLE"]

_OPS: dict[str, Callable[[float, float], bool]] = {
    "<": operator.lt,
    ">": operator.gt,
    "<=": operator.le,
    ">=": operator.ge,
}

# Best (0) to worst (4); used only to classify a status change as improved/worsened/unchanged.
_SEVERITY: dict[str, int] = {
    "STRENGTHENING": 0,
    "STABLE": 1,
    "UNVERIFIABLE": 2,
    "WEAKENING": 3,
    "BROKEN": 4,
}


def theses_path(home: Path | str | None = None) -> Path:
    """Resolve (and create) the directory holding ``theses.json``."""
    base = Path(home or os.environ.get("PORTFOLIO_COPILOT_HOME") or DEFAULT_HOME)
    base.mkdir(parents=True, exist_ok=True)
    return base / "theses.json"


class Falsifier(BaseModel):
    """One concrete, checkable condition that would falsify the thesis if it holds."""

    metric: str
    op: Literal["<", ">", "<=", ">="]
    threshold: float
    label: str

    @field_validator("threshold")
    @classmethod
    def _threshold_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError(f"threshold must be a finite number, got {value!r}")
        return value


class ThesisCheck(BaseModel):
    """Result of evaluating a thesis's falsifiers against one metrics snapshot."""

    date: str
    status: ThesisStatus
    tripped: list[str] = Field(default_factory=list)
    checked: int = 0
    unavailable: list[str] = Field(default_factory=list)


class Thesis(BaseModel):
    """A symbol's investment thesis: the claims, their falsifiers, and check history."""

    symbol: str
    claims: list[str]
    falsifiers: list[Falsifier] = Field(default_factory=list)
    created: str
    history: list[ThesisCheck] = Field(default_factory=list)


def _is_missing(value: object) -> bool:
    """True for ``None`` and for a non-finite float (NaN/Infinity) -- both must degrade a
    falsifier to "unavailable", never fall through to "checked, did not trip"."""
    if value is None:
        return True
    if isinstance(value, float) and not math.isfinite(value):
        return True
    return False


def evaluate_thesis(thesis: Thesis, metrics: dict, as_of: str) -> ThesisCheck:
    """Evaluate every falsifier of ``thesis`` against ``metrics``. Pure: no I/O, no mutation.

    ``metrics`` is a flat dict (e.g. a ``StockSnapshot.model_dump()``); a falsifier whose
    metric key is missing, ``None`` or a non-finite float (NaN/Infinity) is excluded from
    ``checked`` and listed in ``unavailable`` instead of being silently counted as "not
    tripped" -- a NaN compares False against every operator, so without this guard it would
    otherwise look identical to a metric that genuinely stayed inside its safe range.

    Status rule (deterministic, no LLM judgement):
    - fewer than 1 falsifier could be evaluated -> ``UNVERIFIABLE``;
    - none tripped -> ``STABLE``, or ``STRENGTHENING`` if the thesis's previous check
      (``thesis.history[-1]``) had at least one tripped falsifier *and* every one of those
      previously-tripped falsifiers was re-evaluated this run (its metric present, not
      ``unavailable``) and did not trip -- a previously-tripped falsifier whose metric
      simply went missing this run is not evidence of improvement, so that case reports
      ``UNVERIFIABLE`` instead of manufacturing the single best status;
    - tripped < half of checkable -> ``WEAKENING``;
    - tripped >= half of checkable -> ``BROKEN``.
    """
    tripped: list[str] = []
    unavailable: list[str] = []
    checked = 0
    for f in thesis.falsifiers:
        value = metrics.get(f.metric)
        if _is_missing(value):
            unavailable.append(f.metric)
            continue
        checked += 1
        if _OPS[f.op](float(value), f.threshold):
            tripped.append(f.label)

    if checked < 1:
        return ThesisCheck(
            date=as_of, status="UNVERIFIABLE", tripped=[], checked=0, unavailable=unavailable
        )

    if not tripped:
        previous = thesis.history[-1] if thesis.history else None
        status: ThesisStatus = "STABLE"
        if previous is not None and previous.tripped:
            label_to_metric = {falsifier.label: falsifier.metric for falsifier in thesis.falsifiers}
            reverified = all(
                (metric := label_to_metric.get(label)) is not None and metric not in unavailable
                for label in previous.tripped
            )
            status = "STRENGTHENING" if reverified else "UNVERIFIABLE"
    elif len(tripped) / checked >= 0.5:
        status = "BROKEN"
    else:
        status = "WEAKENING"

    return ThesisCheck(
        date=as_of, status=status, tripped=tripped, checked=checked, unavailable=unavailable
    )


def load_theses(home: Path | str | None = None) -> dict[str, Thesis]:
    """Load all stored theses, keyed by uppercase symbol. Empty dict if none stored yet.

    Raises ``ValueError`` (``json.JSONDecodeError``/``pydantic.ValidationError``, both
    ``ValueError`` subclasses) if the file is corrupted or holds an invalid schema -- never
    silently drops or invents entries.
    """
    path = theses_path(home)
    if not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {symbol: Thesis(**data) for symbol, data in raw.items()}


def _write_theses(theses: dict[str, Thesis], home: Path | str | None = None) -> None:
    """Persist ``theses`` atomically: write to a sibling temp file then ``os.replace`` it
    over the real path, so a crash/kill mid-write can never leave ``theses.json``
    truncated or otherwise corrupted -- the rename either fully happens or not at all."""
    payload = {symbol: json.loads(t.model_dump_json()) for symbol, t in theses.items()}
    path = theses_path(home)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".theses-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, indent=2, ensure_ascii=False))
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def save_thesis(thesis: dict | Thesis, home: Path | str | None = None) -> Thesis:
    """Validate ``thesis`` and persist it, upserting by symbol (stripped and uppercased)."""
    model = thesis if isinstance(thesis, Thesis) else Thesis(**dict(thesis))
    normalized_symbol = model.symbol.strip().upper()
    if model.symbol != normalized_symbol:
        model = model.model_copy(update={"symbol": normalized_symbol})
    theses = load_theses(home)
    theses[model.symbol] = model
    _write_theses(theses, home)
    return model


def _status_delta(previous: str | None, current: str) -> str:
    if previous is None:
        return "new"
    if previous == current:
        return "unchanged"
    if current == "UNVERIFIABLE" and _SEVERITY[previous] > _SEVERITY[current]:
        # A data blackout right after a worse concrete status (WEAKENING/BROKEN) is not a
        # verified improvement -- nothing was re-checked, the feed simply went dark.
        return "unchanged"
    return "improved" if _SEVERITY[current] < _SEVERITY[previous] else "worsened"


def check_thesis(symbol: str, metrics: dict, as_of: str, home: Path | str | None = None) -> dict:
    """Load the stored thesis for ``symbol``, evaluate it, append and persist the check.

    Raises ``ValueError`` if no thesis is stored for ``symbol`` -- never fabricates one.
    Returns the new check plus the previous status and a qualitative delta so a caller
    can report "thesis holding" or "thesis breaking down" without re-deriving severity.
    """
    key = symbol.strip().upper()
    theses = load_theses(home)
    thesis = theses.get(key)
    if thesis is None:
        raise ValueError(f"no thesis found for {key}")

    previous_status = thesis.history[-1].status if thesis.history else None
    check = evaluate_thesis(thesis, metrics, as_of)
    thesis.history.append(check)
    theses[key] = thesis
    _write_theses(theses, home)

    return {
        "symbol": key,
        "check": check,
        "previous_status": previous_status,
        "status": check.status,
        "delta": _status_delta(previous_status, check.status),
    }
