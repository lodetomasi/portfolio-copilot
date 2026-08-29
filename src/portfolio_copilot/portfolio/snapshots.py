"""Holdings snapshot store: one dated record per month of the local broker export.

The copilot only ever sees the *current* export handed to it in a given call; nothing
here can see the past unless it was written down at the time. ``save_snapshot`` freezes
one ``Portfolio.model_dump()`` (see ``parsers/broker_export.py``) under its date so later
tools can attribute value changes over time instead of re-deriving history that was never
recorded. Storage: one JSON file per date under ``<home>/snapshots/YYYY-MM-DD.json``,
mirroring the ``ledger_path``/``theses_path`` convention in ``portfolio/ledger.py`` and
``portfolio/thesis.py`` (``PORTFOLIO_COPILOT_HOME``, default ``data/private``, git-ignored).
"""

from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import date
from pathlib import Path

from pydantic import BaseModel, Field, ValidationError, field_validator

DEFAULT_HOME = Path(__file__).resolve().parents[3] / "data" / "private"


def snapshots_dir(home: Path | str | None = None) -> Path:
    """Resolve (and create) the directory holding one JSON file per snapshot date."""
    base = Path(home or os.environ.get("PORTFOLIO_COPILOT_HOME") or DEFAULT_HOME)
    directory = base / "snapshots"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def snapshot_path(as_of: str, home: Path | str | None = None) -> Path:
    """Path of the snapshot file for ``as_of`` (an ISO date string), creating the dir.

    ``as_of`` is validated as an ISO date *before* it is turned into a path component:
    without this, a string like ``'../secret'`` would resolve outside ``snapshots/`` and
    let a caller read or write an arbitrary file elsewhere on disk.
    """
    try:
        date.fromisoformat(as_of)
    except ValueError as exc:
        raise ValueError(f"as_of must be an ISO date (YYYY-MM-DD), got {as_of!r}") from exc
    return snapshots_dir(home) / f"{as_of}.json"


class SnapshotHolding(BaseModel):
    """One holding as it stood on the snapshot's ``as_of`` date."""

    name: str
    isin: str | None = None
    symbol: str | None = None
    asset_type: str = "other"
    quantity: float = 0.0
    market_price: float | None = None
    market_value: float
    leverage: float = 1.0
    bucket: str | None = None

    @field_validator("quantity", "market_price", "market_value", "leverage")
    @classmethod
    def _numeric_fields_must_be_finite(cls, value: float | None, info) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError(f"{info.field_name} must be a finite number, got {value!r}")
        return value


class Snapshot(BaseModel):
    """A full portfolio snapshot for one date."""

    as_of: str
    base_currency: str = "EUR"
    total_value: float
    holdings: list[SnapshotHolding] = Field(default_factory=list)
    source: str = "broker_export"
    plan_targets: dict | None = None

    @field_validator("total_value")
    @classmethod
    def _total_value_must_be_finite(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError(f"total_value must be a finite number, got {value!r}")
        return value


def save_snapshot(
    portfolio: dict,
    as_of: str,
    home: Path | str | None = None,
    buckets: dict[str, str] | None = None,
    plan_targets: dict | None = None,
    force: bool = False,
) -> Snapshot:
    """Validate and persist one dated snapshot of ``portfolio``.

    ``portfolio`` is a ``Portfolio.model_dump()`` dict from ``parsers/broker_export.py``.
    ``buckets`` maps a holding's ``name`` to its plan bucket (typically produced by
    ``portfolio/mapping.py``); a holding absent from ``buckets`` keeps its own ``bucket``
    field, if any. Refuses to overwrite an existing date unless ``force=True``, so an
    accidental re-run of a monthly job can never silently discard whichever version of
    that date was saved first. The write is atomic: a crash mid-write can never leave a
    truncated or partially-updated snapshot file behind.
    """
    try:
        date.fromisoformat(as_of)
    except ValueError as exc:
        raise ValueError(f"as_of must be an ISO date (YYYY-MM-DD), got {as_of!r}") from exc

    path = snapshot_path(as_of, home)

    buckets = buckets or {}
    holdings = [
        SnapshotHolding(
            name=h["name"],
            isin=h.get("isin"),
            symbol=h.get("symbol"),
            asset_type=str(h.get("asset_type", "other")),
            quantity=h.get("quantity", 0.0),
            market_price=h.get("market_price"),
            market_value=h["market_value"],
            leverage=h.get("leverage", 1.0),
            bucket=buckets.get(h["name"], h.get("bucket")),
        )
        for h in portfolio.get("holdings", [])
    ]
    snapshot = Snapshot(
        as_of=as_of,
        base_currency=portfolio.get("base_currency", "EUR"),
        total_value=float(sum(h.market_value for h in holdings)),
        holdings=holdings,
        source="broker_export",
        plan_targets=plan_targets,
    )
    if force:
        _write_snapshot(snapshot, path)
        return snapshot

    # Reserve the path exclusively (atomic at the OS level) before writing, so two
    # concurrent calls for the same as_of can never both pass a check-then-act window:
    # exactly one of them wins this open() and the other gets FileExistsError, whichever
    # order the OS schedules them in.
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise FileExistsError(
            f"A snapshot for {as_of} already exists at {path}. Pass force=True to overwrite."
        ) from exc
    os.close(fd)
    try:
        _write_snapshot(snapshot, path)
    except BaseException:
        # the reservation above left an empty placeholder; if the real write then failed,
        # remove it too so a retry doesn't see a spurious "already exists".
        try:
            if path.exists() and path.stat().st_size == 0:
                path.unlink()
        except OSError:
            pass
        raise
    return snapshot


def _write_snapshot(snapshot: Snapshot, path: Path) -> None:
    """Persist ``snapshot`` atomically: write to a sibling temp file then ``os.replace``
    it over the real path, mirroring ``portfolio/thesis.py``'s write pattern so a
    crash/kill mid-write never leaves the file truncated or otherwise corrupted."""
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".snapshot-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(snapshot.model_dump_json(indent=2))
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def list_snapshots(home: Path | str | None = None) -> list[str]:
    """All stored snapshot dates, sorted ascending (ISO dates sort lexicographically)."""
    return sorted(p.stem for p in snapshots_dir(home).glob("*.json"))


def load_snapshot(as_of: str, home: Path | str | None = None) -> Snapshot:
    """Load one stored snapshot by date.

    Raises ``FileNotFoundError`` if no snapshot was ever saved for ``as_of``, and a clear
    ``ValueError`` if the file exists but is corrupted or does not match the schema --
    never silently skips or drops a bad snapshot.
    """
    path = snapshot_path(as_of, home)
    if not path.exists():
        raise FileNotFoundError(f"No snapshot stored for {as_of} (expected {path})")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Corrupted snapshot file {path}: {exc}") from exc
    try:
        return Snapshot(**raw)
    except ValidationError as exc:
        raise ValueError(f"Invalid snapshot file {path}: {exc}") from exc


def latest_snapshot(home: Path | str | None = None) -> Snapshot | None:
    """The most recent stored snapshot, or ``None`` if none has ever been saved."""
    dates = list_snapshots(home)
    if not dates:
        return None
    return load_snapshot(dates[-1], home)


def _match_key(holding: SnapshotHolding) -> str:
    """Match key for pairing a holding across two snapshots: ISIN when present, else
    name. A holding whose ISIN is present in one snapshot but missing in the other (a
    malformed export) is therefore not matched across the two -- it shows as removed in
    one and added in the other rather than being fuzzily guessed."""
    return f"isin:{holding.isin}" if holding.isin else f"name:{holding.name}"


def _aggregate_by_key(holdings: list[SnapshotHolding]) -> dict[str, SnapshotHolding]:
    """Group ``holdings`` by match key (see ``_match_key``), summing ``market_value`` and
    ``quantity`` for entries sharing a key.

    A snapshot can legitimately contain the same ISIN twice -- the same security held
    across two custody sub-accounts, or a corporate-action tax-lot split in a raw broker
    export. A plain ``{key: holding}`` dict comprehension would silently keep only the
    last one iterated and drop the earlier lot's value with no error; aggregating instead
    keeps every lot's value in the total while still producing one comparable row per key.
    """
    aggregated: dict[str, SnapshotHolding] = {}
    for h in holdings:
        key = _match_key(h)
        existing = aggregated.get(key)
        if existing is None:
            aggregated[key] = h
        else:
            aggregated[key] = existing.model_copy(
                update={
                    "market_value": existing.market_value + h.market_value,
                    "quantity": existing.quantity + h.quantity,
                }
            )
    return aggregated


def diff_snapshots(older: Snapshot, newer: Snapshot) -> dict:
    """Compare two snapshots holding-by-holding (matched by ISIN, then name) and by bucket.

    A duplicate ISIN/name within one snapshot (two custody sub-accounts, a tax-lot split)
    is aggregated -- summed -- before matching, never silently collapsed to the last one
    iterated (see ``_aggregate_by_key``).

    Reports the raw value change only. It does NOT -- and cannot -- separate how much of
    that change is new money contributed versus market movement; that split requires the
    decision ledger / investment plan and must never be inferred from two snapshots alone
    (see the returned ``note``).
    """
    older_by_key = _aggregate_by_key(older.holdings)
    newer_by_key = _aggregate_by_key(newer.holdings)
    all_keys = list(dict.fromkeys([*older_by_key, *newer_by_key]))

    rows: list[dict] = []
    bucket_change: dict[str, float] = {}

    for k in all_keys:
        before = older_by_key.get(k)
        after = newer_by_key.get(k)
        if before is not None and after is not None:
            status, ref = "kept", after
            value_before, value_after = before.market_value, after.market_value
            quantity_before, quantity_after = before.quantity, after.quantity
        elif before is not None:
            status, ref = "removed", before
            value_before, value_after = before.market_value, 0.0
            quantity_before, quantity_after = before.quantity, 0.0
        else:
            assert after is not None  # one of before/after is always set
            status, ref = "added", after
            value_before, value_after = 0.0, after.market_value
            quantity_before, quantity_after = 0.0, after.quantity

        change = value_after - value_before
        rows.append(
            {
                "name": ref.name,
                "isin": ref.isin,
                "status": status,
                "value_before": value_before,
                "value_after": value_after,
                "change_eur": change,
                "quantity_before": quantity_before,
                "quantity_after": quantity_after,
            }
        )
        if ref.bucket is not None:
            bucket_change[ref.bucket] = bucket_change.get(ref.bucket, 0.0) + change

    return {
        "as_of_before": older.as_of,
        "as_of_after": newer.as_of,
        "total_change_eur": newer.total_value - older.total_value,
        "holdings": rows,
        "bucket_change_eur": bucket_change or None,
        "note": (
            "Value change = contributions + market move. This diff cannot separate the "
            "two: contributions must come from the decision ledger or investment plan, "
            "never inferred here from the snapshots alone."
        ),
    }
