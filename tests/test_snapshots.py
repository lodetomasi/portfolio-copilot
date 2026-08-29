import json

import pytest

from portfolio_copilot.portfolio.snapshots import (
    diff_snapshots,
    latest_snapshot,
    list_snapshots,
    load_snapshot,
    save_snapshot,
    snapshot_path,
    snapshots_dir,
)


def _portfolio(holdings: list[dict]) -> dict:
    return {"holdings": holdings, "base_currency": "EUR", "source": "broker_export"}


def test_save_and_load_roundtrip(tmp_path):
    portfolio = _portfolio(
        [
            {
                "name": "Acme Corp",
                "isin": "US0001",
                "symbol": "ACME",
                "asset_type": "equity",
                "quantity": 10.0,
                "market_price": 100.0,
                "market_value": 1000.0,
                "leverage": 1.0,
            },
            {
                "name": "World ETF",
                "isin": "IE0002",
                "symbol": "VWCE",
                "asset_type": "etf",
                "quantity": 5.0,
                "market_price": 100.0,
                "market_value": 500.0,
                "leverage": 1.0,
            },
        ]
    )
    saved = save_snapshot(
        portfolio,
        "2026-01-31",
        home=tmp_path,
        buckets={"Acme Corp": "growth", "World ETF": "core"},
    )
    assert saved.total_value == pytest.approx(1500.0)
    assert saved.holdings[0].bucket == "growth"
    assert saved.holdings[1].bucket == "core"

    loaded = load_snapshot("2026-01-31", home=tmp_path)
    assert loaded == saved
    assert loaded.as_of == "2026-01-31"
    assert loaded.base_currency == "EUR"
    assert loaded.source == "broker_export"


def test_save_refuses_to_overwrite_existing_date(tmp_path):
    portfolio = _portfolio([{"name": "A", "market_value": 100.0}])
    save_snapshot(portfolio, "2026-02-01", home=tmp_path)
    with pytest.raises(FileExistsError):
        save_snapshot(portfolio, "2026-02-01", home=tmp_path)


def test_save_force_overwrites_existing_date(tmp_path):
    v1 = _portfolio([{"name": "A", "market_value": 100.0}])
    v2 = _portfolio([{"name": "A", "market_value": 200.0}])
    save_snapshot(v1, "2026-02-01", home=tmp_path)
    updated = save_snapshot(v2, "2026-02-01", home=tmp_path, force=True)
    assert updated.total_value == pytest.approx(200.0)
    assert load_snapshot("2026-02-01", home=tmp_path).total_value == pytest.approx(200.0)


def test_save_rejects_non_iso_date(tmp_path):
    portfolio = _portfolio([{"name": "A", "market_value": 1.0}])
    with pytest.raises(ValueError):
        save_snapshot(portfolio, "01/05/2026", home=tmp_path)
    assert list_snapshots(tmp_path) == []


def test_list_snapshots_sorted(tmp_path):
    portfolio = _portfolio([{"name": "A", "market_value": 1.0}])
    save_snapshot(portfolio, "2026-03-01", home=tmp_path)
    save_snapshot(portfolio, "2026-01-01", home=tmp_path)
    save_snapshot(portfolio, "2026-02-01", home=tmp_path)
    assert list_snapshots(tmp_path) == ["2026-01-01", "2026-02-01", "2026-03-01"]


def test_latest_snapshot_none_when_no_snapshots_exist(tmp_path):
    assert latest_snapshot(tmp_path) is None


def test_latest_snapshot_returns_most_recent(tmp_path):
    portfolio = _portfolio([{"name": "A", "market_value": 1.0}])
    save_snapshot(portfolio, "2026-01-01", home=tmp_path)
    save_snapshot(portfolio, "2026-02-01", home=tmp_path)
    latest = latest_snapshot(tmp_path)
    assert latest is not None
    assert latest.as_of == "2026-02-01"


def test_load_snapshot_missing_date_raises_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_snapshot("2026-09-01", home=tmp_path)


def test_load_snapshot_corrupted_file_raises_clear_value_error(tmp_path):
    directory = snapshots_dir(tmp_path)
    (directory / "2026-04-01.json").write_text("{not valid json", encoding="utf-8")
    with pytest.raises(ValueError, match="Corrupted snapshot file"):
        load_snapshot("2026-04-01", home=tmp_path)


def test_load_snapshot_schema_mismatch_raises_clear_value_error(tmp_path):
    directory = snapshots_dir(tmp_path)
    (directory / "2026-04-02.json").write_text('{"as_of": "2026-04-02"}', encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid snapshot file"):
        load_snapshot("2026-04-02", home=tmp_path)


def test_save_snapshot_rejects_nan_market_value(tmp_path):
    portfolio = _portfolio([{"name": "Bad", "market_value": float("nan")}])
    with pytest.raises(ValueError):
        save_snapshot(portfolio, "2026-05-01", home=tmp_path)
    assert list_snapshots(tmp_path) == []  # nothing partially written


def test_diff_snapshots_matches_by_isin_then_name_and_aggregates_buckets(tmp_path):
    older = save_snapshot(
        _portfolio(
            [
                {"name": "Acme", "isin": "US0001", "market_value": 1000.0, "quantity": 10.0},
                {"name": "Sold Co", "isin": "US0003", "market_value": 300.0, "quantity": 3.0},
                {"name": "Cash", "market_value": 50.0, "quantity": 50.0},
            ]
        ),
        "2026-01-01",
        home=tmp_path,
        buckets={"Acme": "growth", "Sold Co": "growth", "Cash": "core"},
    )
    newer = save_snapshot(
        _portfolio(
            [
                {"name": "Acme", "isin": "US0001", "market_value": 1100.0, "quantity": 10.0},
                {"name": "New Co", "isin": "US0004", "market_value": 400.0, "quantity": 4.0},
                {"name": "Cash", "market_value": 20.0, "quantity": 20.0},
            ]
        ),
        "2026-02-01",
        home=tmp_path,
        buckets={"Acme": "growth", "New Co": "core", "Cash": "core"},
    )

    diff = diff_snapshots(older, newer)
    assert diff["as_of_before"] == "2026-01-01"
    assert diff["as_of_after"] == "2026-02-01"
    # (1100 + 400 + 20) - (1000 + 300 + 50) = 1520 - 1350
    assert diff["total_change_eur"] == pytest.approx(170.0)

    by_name = {row["name"]: row for row in diff["holdings"]}
    assert by_name["Acme"]["status"] == "kept"
    assert by_name["Acme"]["change_eur"] == pytest.approx(100.0)
    assert by_name["Acme"]["quantity_before"] == pytest.approx(10.0)
    assert by_name["Acme"]["quantity_after"] == pytest.approx(10.0)

    assert by_name["Sold Co"]["status"] == "removed"
    assert by_name["Sold Co"]["value_after"] == pytest.approx(0.0)
    assert by_name["Sold Co"]["change_eur"] == pytest.approx(-300.0)

    assert by_name["New Co"]["status"] == "added"
    assert by_name["New Co"]["value_before"] == pytest.approx(0.0)
    assert by_name["New Co"]["change_eur"] == pytest.approx(400.0)

    assert by_name["Cash"]["status"] == "kept"
    assert by_name["Cash"]["change_eur"] == pytest.approx(-30.0)

    # growth: Acme +100, Sold Co -300 => -200; core: New Co +400, Cash -30 => +370
    assert diff["bucket_change_eur"]["growth"] == pytest.approx(-200.0)
    assert diff["bucket_change_eur"]["core"] == pytest.approx(370.0)
    assert "contributions" in diff["note"]


def test_diff_snapshots_no_buckets_yields_no_bucket_change(tmp_path):
    older = save_snapshot(
        _portfolio([{"name": "A", "market_value": 100.0}]), "2026-06-01", home=tmp_path
    )
    newer = save_snapshot(
        _portfolio([{"name": "A", "market_value": 150.0}]), "2026-06-02", home=tmp_path
    )
    diff = diff_snapshots(older, newer)
    assert diff["bucket_change_eur"] is None


def test_diff_snapshots_aggregates_duplicate_isin_instead_of_dropping_a_lot(tmp_path):
    """Two holdings sharing the same ISIN (e.g. the same security held across two custody
    sub-accounts) must both be reflected in the diff, not have one lot silently vanish
    because a dict comprehension keyed by ISIN kept only the last one iterated."""
    older = save_snapshot(
        _portfolio(
            [
                {"name": "Acme A-share", "isin": "US0001", "market_value": 500.0},
                {"name": "Acme B-share (custody 2)", "isin": "US0001", "market_value": 500.0},
            ]
        ),
        "2026-07-01",
        home=tmp_path,
    )
    newer = save_snapshot(
        _portfolio(
            [
                {"name": "Acme A-share", "isin": "US0001", "market_value": 300.0},
                {"name": "Acme B-share (custody 2)", "isin": "US0001", "market_value": 100.0},
            ]
        ),
        "2026-07-02",
        home=tmp_path,
    )
    diff = diff_snapshots(older, newer)
    assert diff["total_change_eur"] == pytest.approx(-600.0)
    # exactly one row for the shared ISIN, and it must reconcile with total_change_eur --
    # no lot silently dropped.
    rows = [r for r in diff["holdings"] if r["isin"] == "US0001"]
    assert len(rows) == 1
    row = rows[0]
    assert row["value_before"] == pytest.approx(1000.0)
    assert row["value_after"] == pytest.approx(400.0)
    assert row["change_eur"] == pytest.approx(-600.0)


def test_save_snapshot_rejects_nan_quantity(tmp_path):
    portfolio = _portfolio([{"name": "Bad", "market_value": 100.0, "quantity": float("nan")}])
    with pytest.raises(ValueError):
        save_snapshot(portfolio, "2026-08-05", home=tmp_path)
    assert list_snapshots(tmp_path) == []


def test_save_snapshot_rejects_nan_market_price(tmp_path):
    portfolio = _portfolio(
        [{"name": "Bad", "market_value": 100.0, "market_price": float("nan")}]
    )
    with pytest.raises(ValueError):
        save_snapshot(portfolio, "2026-08-06", home=tmp_path)


def test_save_snapshot_rejects_infinite_leverage(tmp_path):
    portfolio = _portfolio([{"name": "Bad", "market_value": 100.0, "leverage": float("inf")}])
    with pytest.raises(ValueError):
        save_snapshot(portfolio, "2026-08-07", home=tmp_path)


def test_load_snapshot_rejects_nan_total_value(tmp_path):
    """A hand-edited/legacy snapshot file with total_value=NaN (a literal Python's json
    module accepts by default) must be rejected at load time with the same clear error as
    a non-finite market_value, never silently loaded and propagated as NaN downstream."""
    directory = snapshots_dir(tmp_path)
    raw = json.dumps(
        {
            "as_of": "2026-08-08",
            "base_currency": "EUR",
            "total_value": float("nan"),
            "holdings": [],
            "source": "broker_export",
        }
    )
    (directory / "2026-08-08.json").write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        load_snapshot("2026-08-08", home=tmp_path)


def test_snapshot_path_rejects_non_iso_as_of_to_prevent_path_traversal(tmp_path):
    """as_of must be validated before being turned into a path component: an unvalidated
    string like '../secret' would resolve outside snapshots/ and let load_snapshot read an
    arbitrary file elsewhere on disk."""
    # a file that legitimately sits outside snapshots/, that traversal must never reach
    (tmp_path / "secret_lookalike.json").write_text(
        json.dumps(
            {
                "as_of": "not-even-the-requested-date",
                "base_currency": "EUR",
                "total_value": 999999.0,
                "holdings": [],
                "source": "broker_export",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        snapshot_path("../secret_lookalike", home=tmp_path)
    with pytest.raises(ValueError):
        load_snapshot("../secret_lookalike", home=tmp_path)


def test_save_snapshot_concurrent_writes_for_the_same_date_are_mutually_exclusive(
    tmp_path, monkeypatch
):
    """force=False must never silently let two concurrent writers both 'win': exactly one
    call succeeds and the other gets FileExistsError, whichever loses. A plain
    check-then-act (path.exists() then write) leaves a window where both callers can pass
    the check before either writes, so widen that window deliberately (mirroring the real
    TOCTOU) by making every Path.exists() call block on a barrier before answering."""
    import pathlib
    import threading

    barrier = threading.Barrier(2, timeout=5)
    original_exists = pathlib.Path.exists

    def slow_exists(self):
        if self.suffix == ".json":
            barrier.wait()
        return original_exists(self)

    monkeypatch.setattr(pathlib.Path, "exists", slow_exists)

    portfolio_a = _portfolio([{"name": "A", "market_value": 111.0}])
    portfolio_b = _portfolio([{"name": "A", "market_value": 222.0}])
    results: dict[str, tuple[str, float | None]] = {}

    def worker(key, portfolio):
        try:
            saved = save_snapshot(portfolio, "2026-08-01", home=tmp_path, force=False)
            results[key] = ("ok", saved.total_value)
        except FileExistsError:
            results[key] = ("exists", None)
        except threading.BrokenBarrierError:
            results[key] = ("broken", None)

    threads = [
        threading.Thread(target=worker, args=("A", portfolio_a)),
        threading.Thread(target=worker, args=("B", portfolio_b)),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    outcomes = [v[0] for v in results.values()]
    assert outcomes.count("ok") == 1, results
    assert outcomes.count("exists") == 1, results
    winner_value = next(v[1] for v in results.values() if v[0] == "ok")
    monkeypatch.setattr(pathlib.Path, "exists", original_exists)
    final = load_snapshot("2026-08-01", home=tmp_path)
    assert final.total_value == pytest.approx(winner_value)
