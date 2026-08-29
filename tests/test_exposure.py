"""Tests for the hidden-exposure graph (portfolio/exposure.py).

All data is synthetic; the graph itself (config/exposure_graph.yaml) is curated repo
config, not fetched, so these tests are offline and deterministic by construction.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from portfolio_copilot.portfolio.exposure import (
    classify,
    fit_score,
    load_graph,
    portfolio_exposure,
)

FIXTURES = Path(__file__).parent / "fixtures"

EXPECTED_THEMES = {
    "global_equity_core",
    "small_cap",
    "emerging_markets",
    "global_bonds",
    "semiconductors",
    "ai_software",
    "defense_aerospace",
    "biotech_pharma",
    "robotics_automation",
    "gold_miners",
    "energy",
    "banks_financials",
    "real_estate",
    "leveraged_certificates",
    "cash",
}


def _load_sample_holdings() -> list[dict]:
    return json.loads((FIXTURES / "exposure_holdings_sample.json").read_text(encoding="utf-8"))


# --- config validation -------------------------------------------------------------


def test_default_graph_has_exactly_the_curated_themes():
    graph = load_graph()
    assert set(graph["themes"]) == EXPECTED_THEMES


def test_default_graph_every_theme_has_keywords_and_drivers():
    graph = load_graph()
    for theme_name, theme_def in graph["themes"].items():
        assert theme_def["keywords"], f"{theme_name} has no keywords"
        assert theme_def["drivers"], f"{theme_name} has no drivers"


def test_load_graph_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        load_graph(path=tmp_path / "does_not_exist.yaml")


def test_load_graph_rejects_theme_missing_drivers(tmp_path: Path):
    bad = tmp_path / "bad_graph.yaml"
    bad.write_text('themes:\n  broken:\n    keywords: ["x"]\n', encoding="utf-8")
    with pytest.raises(ValidationError):
        load_graph(path=bad)


def test_load_graph_rejects_empty_themes(tmp_path: Path):
    bad = tmp_path / "empty_graph.yaml"
    bad.write_text("themes: {}\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_graph(path=bad)


# --- classify: one instrument per known category ----------------------------------


def test_classify_world_equity_etf():
    result = classify(name="Vanguard FTSE All-World UCITS ETF (USD) Acc")
    assert result["themes"] == ["global_equity_core"]
    assert "equity_beta_global" in result["drivers"]
    assert "usd" in result["drivers"]


def test_classify_small_cap_etf_also_carries_world_equity():
    # Realistic hidden exposure: a "MSCI World Small Cap" ETF is both a small-cap bet
    # and ordinary global equity beta -- that overlap is exactly what this graph exists
    # to surface, so both themes must come back (in curated file order).
    result = classify(name="iShares MSCI World Small Cap UCITS ETF USD (Acc)")
    assert result["themes"] == ["global_equity_core", "small_cap"]
    assert "small_cap_liquidity" in result["drivers"]


def test_classify_emerging_markets_etf():
    result = classify(name="Vanguard FTSE Emerging Markets UCITS ETF (USD) Acc")
    assert result["themes"] == ["emerging_markets"]
    assert "china_demand" in result["drivers"]


def test_classify_global_bond_etf():
    result = classify(name="iShares Core Global Aggregate Bond UCITS ETF EUR Hedged (Acc)")
    assert result["themes"] == ["global_bonds"]
    assert "rates_eur" in result["drivers"]


def test_classify_chip_stock():
    result = classify(name="NVIDIA Corporation", sector="Technology", industry="Semiconductors")
    assert result["themes"] == ["semiconductors"]
    assert set(result["drivers"]) == {"semiconductor_cycle", "ai_capex", "china_demand"}


def test_classify_defense_stock():
    result = classify(name="Leonardo SpA", sector="Industrials", industry="Aerospace & Defense")
    assert result["themes"] == ["defense_aerospace"]
    assert "us_defense_budget" in result["drivers"]


def test_classify_5x_certificate_on_a_bank():
    result = classify(
        name="LEVA FISSA EXAMPLE LONG 5X BANK CERTIFICATE",
        sector="Financials",
        industry="Banks",
        asset_type="certificate",
        leverage=5.0,
    )
    assert result["themes"] == ["banks_financials", "leveraged_certificates"]
    assert "bank_credit_cycle" in result["drivers"]
    assert "leverage_decay" in result["drivers"]


def test_classify_leverage_forces_leveraged_theme_even_without_underlying_match():
    result = classify(name="XYZ123 Structured Note", asset_type="certificate", leverage=2.0)
    assert result["themes"] == ["leveraged_certificates"]
    assert result["drivers"] == ["leverage_decay"]


def test_classify_high_leverage_without_certificate_asset_type_still_flags_leverage():
    result = classify(name="Random Fund", leverage=3.0)
    assert "leveraged_certificates" in result["themes"]


def test_classify_unclassified_when_nothing_matches():
    result = classify(name="Mystery Widget Corp 999")
    assert result["themes"] == ["unclassified"]
    assert result["drivers"] == []


# --- portfolio_exposure: sums, weights, leveraged equivalent map -----------------


def test_portfolio_exposure_empty_portfolio():
    result = portfolio_exposure([])
    assert result["total_value"] == 0.0
    assert result["themes"] == {}
    assert result["drivers"] == {}
    assert result["equivalent"] == {"themes": {}, "drivers": {}}
    assert result["unclassified_weight"] == 0.0


def test_portfolio_exposure_zero_value_holdings_treated_like_empty():
    result = portfolio_exposure([{"name": "Worthless Position", "market_value": 0.0}])
    assert result["total_value"] == 0.0
    assert result["themes"] == {}


def test_portfolio_exposure_sample_theme_weights():
    result = portfolio_exposure(_load_sample_holdings())
    assert result["total_value"] == pytest.approx(8000.0)
    # global_equity_core = world ETF (4000) + small-cap-world ETF (1000)
    assert result["themes"]["global_equity_core"] == pytest.approx(5000.0 / 8000.0)
    assert result["themes"]["small_cap"] == pytest.approx(1000.0 / 8000.0)
    assert result["themes"]["emerging_markets"] == pytest.approx(500.0 / 8000.0)
    assert result["themes"]["global_bonds"] == pytest.approx(500.0 / 8000.0)
    assert result["themes"]["semiconductors"] == pytest.approx(800.0 / 8000.0)
    assert result["themes"]["defense_aerospace"] == pytest.approx(400.0 / 8000.0)
    assert result["themes"]["banks_financials"] == pytest.approx(200.0 / 8000.0)
    assert result["themes"]["leveraged_certificates"] == pytest.approx(200.0 / 8000.0)
    assert result["themes"]["cash"] == pytest.approx(600.0 / 8000.0)
    assert "ai_software" not in result["themes"]
    assert result["unclassified_weight"] == pytest.approx(0.0)


def test_portfolio_exposure_leveraged_equivalent_map_scales_by_leverage():
    result = portfolio_exposure(_load_sample_holdings())
    # nominal weight of the bank certificate is 200/8000; at 5x leverage its
    # equivalent thematic pull is 200*5 = 1000 out of the same 8000 nominal base.
    assert result["themes"]["banks_financials"] == pytest.approx(200.0 / 8000.0)
    assert result["equivalent"]["themes"]["banks_financials"] == pytest.approx(1000.0 / 8000.0)
    assert result["equivalent"]["themes"]["leveraged_certificates"] == pytest.approx(
        1000.0 / 8000.0
    )
    assert result["drivers"]["leverage_decay"] == pytest.approx(200.0 / 8000.0)
    assert result["equivalent"]["drivers"]["leverage_decay"] == pytest.approx(1000.0 / 8000.0)
    # unleveraged themes are unchanged between nominal and equivalent
    assert result["equivalent"]["themes"]["global_equity_core"] == pytest.approx(5000.0 / 8000.0)


def test_portfolio_exposure_unclassified_holding():
    holdings = [
        {
            "name": "Mystery Structured Note ZZZ 999",
            "market_value": 100.0,
            "sector": None,
            "industry": None,
            "asset_type": "other",
            "leverage": 1.0,
        }
    ]
    result = portfolio_exposure(holdings)
    assert result["themes"] == {}
    assert result["drivers"] == {}
    assert result["unclassified_weight"] == pytest.approx(1.0)


def test_portfolio_exposure_missing_optional_fields_default_safely():
    # A minimal holding dict (only name + market_value) must not raise.
    holding = {"name": "Vanguard FTSE All-World UCITS ETF", "market_value": 100.0}
    result = portfolio_exposure([holding])
    assert result["themes"]["global_equity_core"] == pytest.approx(1.0)


# --- fit_score -----------------------------------------------------------------


def test_fit_score_reduced_by_shared_driver_weight_when_semis_already_20pct():
    candidate = classify(name="Advanced Micro Devices, Inc.", industry="Semiconductors")
    exposure = {
        "themes": {"semiconductors": 0.20},
        "drivers": {"semiconductor_cycle": 0.20, "ai_capex": 0.20, "china_demand": 0.20},
    }
    result = fit_score(candidate, exposure)
    assert result["fit"] == pytest.approx(0.4)
    assert set(result["overlap_drivers"]) == {"semiconductor_cycle", "ai_capex", "china_demand"}
    assert result["reasons"]


def test_fit_score_zero_when_theme_cap_would_be_breached():
    candidate = classify(name="Advanced Micro Devices, Inc.", industry="Semiconductors")
    exposure = {"themes": {"semiconductors": 0.20}, "drivers": {}}
    result = fit_score(candidate, exposure, caps={"semiconductors": 0.20})
    assert result["fit"] == 0.0
    assert result["reasons"]


def test_fit_score_full_when_no_overlap_and_no_cap():
    candidate = {"themes": ["gold_miners"], "drivers": ["gold_price", "usd"]}
    exposure = {"themes": {}, "drivers": {}}
    result = fit_score(candidate, exposure)
    assert result["fit"] == 1.0
    assert result["overlap_drivers"] == []


def test_fit_score_cap_not_breached_when_below_threshold():
    candidate = {"themes": ["semiconductors"], "drivers": []}
    exposure = {"themes": {"semiconductors": 0.10}, "drivers": {}}
    result = fit_score(candidate, exposure, caps={"semiconductors": 0.20})
    assert result["fit"] == 1.0


# --- finding 14: NaN market_value/leverage must never poison the aggregate ------------


def test_portfolio_exposure_nan_market_value_is_treated_as_missing_not_poisoning():
    holdings = [
        {"name": "Advanced Micro Devices, Inc.", "industry": "Semiconductors",
         "market_value": float("nan")},
        {"name": "Advanced Micro Devices, Inc.", "industry": "Semiconductors",
         "market_value": 9000.0},
    ]
    result = portfolio_exposure(holdings)
    assert result["total_value"] == pytest.approx(9000.0)
    assert result["themes"]["semiconductors"] == pytest.approx(1.0)


def test_portfolio_exposure_infinite_market_value_is_treated_as_missing():
    holdings = [
        {"name": "Advanced Micro Devices, Inc.", "market_value": float("inf")},
        {"name": "Advanced Micro Devices, Inc.", "market_value": 5000.0},
    ]
    result = portfolio_exposure(holdings)
    assert result["total_value"] == pytest.approx(5000.0)


def test_portfolio_exposure_nan_leverage_defaults_to_unleveraged():
    holdings = [
        {
            "name": "Vanguard FTSE All-World UCITS ETF",
            "market_value": 1000.0,
            "leverage": float("nan"),
        },
    ]
    result = portfolio_exposure(holdings)
    assert result["equivalent"]["themes"] == result["themes"]  # leverage treated as 1.0


def test_portfolio_exposure_all_nan_market_values_returns_all_empty_not_nan():
    holdings = [{"name": "X", "market_value": float("nan")}]
    result = portfolio_exposure(holdings)
    assert result["total_value"] == 0.0
    assert result["themes"] == {}


# --- finding 17: malformed market_value/leverage strings must degrade, never raise ----


def test_portfolio_exposure_italian_formatted_market_value_string():
    holdings = [{"name": "Some ETF", "market_value": "1.234,56"}]
    result = portfolio_exposure(holdings)  # must not raise
    assert result["total_value"] == pytest.approx(1234.56)


def test_portfolio_exposure_unparsable_market_value_string_degrades_to_zero():
    holdings = [
        {"name": "Some ETF", "market_value": "N/A"},
        {"name": "Other ETF", "market_value": 500.0},
    ]
    result = portfolio_exposure(holdings)  # must not raise
    assert result["total_value"] == pytest.approx(500.0)


def test_portfolio_exposure_unparsable_leverage_string_defaults_to_one():
    holdings = [
        {
            "name": "Vanguard FTSE All-World UCITS ETF",
            "market_value": 1000.0,
            "leverage": "n/a",
        }
    ]
    result = portfolio_exposure(holdings)  # must not raise
    assert result["equivalent"]["themes"] == result["themes"]


# --- finding 16: classify must degrade, not crash, on a graph without the
# 'leveraged_certificates' theme ------------------------------------------------------


def test_classify_degrades_gracefully_on_custom_graph_missing_leveraged_theme():
    custom_graph = {
        "themes": {
            "global_equity_core": {
                "keywords": ["msci world"], "drivers": ["equity_beta_global"],
            }
        }
    }
    result = classify(
        name="Some Leveraged Note", asset_type="certificate", leverage=3.0, graph=custom_graph
    )
    assert "leveraged_certificates" in result["themes"]
    assert result["drivers"] == []  # no drivers section to pull from -- degrades, not crashes


# --- finding 19: load_graph must pick up an on-disk edit without a process restart ----


def test_load_graph_reflects_on_disk_edit_without_restart(tmp_path: Path):
    path = tmp_path / "graph.yaml"
    path.write_text(
        "themes:\n  t1:\n    keywords: ['alpha']\n    drivers: ['d1']\n", encoding="utf-8"
    )
    first = load_graph(path)
    assert set(first["themes"]) == {"t1"}

    path.write_text(
        "themes:\n  t1:\n    keywords: ['alpha']\n    drivers: ['d1']\n"
        "  t2:\n    keywords: ['beta']\n    drivers: ['d2']\n",
        encoding="utf-8",
    )
    second = load_graph(path)
    assert set(second["themes"]) == {"t1", "t2"}
