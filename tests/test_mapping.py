"""Tests for portfolio_copilot.portfolio.mapping.map_holdings.

All holdings are SYNTHETIC fixtures built as plain dicts, matching the shape of
Portfolio.model_dump()["holdings"][i] (name, isin, symbol, asset_type, market_value,
leverage, ...). No network, no broker data.
"""

from __future__ import annotations

import pytest

from portfolio_copilot.portfolio.mapping import map_holdings
from portfolio_copilot.portfolio.plan import load_model_portfolios

# Real instruments map from the tracked config, loaded read-only via plan.py's own
# loader (never re-implemented here) so ISIN-matching tests use the actual identifiers.
_MODELS = load_model_portfolios()
INSTRUMENTS = _MODELS["instruments"]
BALANCED_TARGETS = _MODELS["profiles"]["balanced"].targets


def _holding(**overrides) -> dict:
    base = {
        "symbol": None,
        "isin": None,
        "name": "Unnamed holding",
        "asset_type": "etf",
        "currency": "EUR",
        "quantity": 1.0,
        "avg_cost": None,
        "market_price": None,
        "market_value": 1000.0,
        "pnl_value": None,
        "pnl_pct": None,
        "leverage": 1.0,
        "sector": None,
        "bucket": None,
    }
    base.update(overrides)
    return base


def test_isin_exact_match_wins_over_name_keywords():
    # Name deliberately looks like a bond fund; the ISIN is the real global_equity
    # instrument. ISIN must win (rule order: ISIN before keywords).
    holding = _holding(
        name="Some Aggregate Bond Fund",
        isin=INSTRUMENTS["global_equity"]["isin"],
        market_value=5_000.0,
    )
    out = map_holdings([holding], BALANCED_TARGETS, INSTRUMENTS)
    assert out["mapped"] == [
        {"name": holding["name"], "bucket": "global_equity", "rule": "isin_exact_match"}
    ]
    assert out["current_values"]["global_equity"] == 5_000.0
    assert out["unmapped"] == []


def test_isin_match_is_case_and_whitespace_insensitive():
    real_isin = INSTRUMENTS["emerging_markets"]["isin"]
    holding = _holding(name="Random name", isin=f" {real_isin.lower()} ", market_value=250.0)
    out = map_holdings([holding], BALANCED_TARGETS, INSTRUMENTS)
    assert out["mapped"][0]["bucket"] == "emerging_markets"
    assert out["current_values"]["emerging_markets"] == 250.0


@pytest.mark.parametrize(
    "name,expected_bucket",
    [
        ("Vanguard FTSE All-World UCITS ETF", "global_equity"),
        ("iShares Core MSCI World UCITS ETF", "global_equity"),
        ("iShares MSCI ACWI ETF", "global_equity"),
        ("SPDR S&P 500 UCITS ETF", "global_equity"),
        ("Xtrackers Developed World UCITS ETF", "global_equity"),
        ("iShares MSCI World Small Cap UCITS ETF", "small_cap"),
        ("SPDR MSCI World Small-Cap UCITS ETF", "small_cap"),
        ("Vanguard FTSE Emerging Markets UCITS ETF", "emerging_markets"),
        ("iShares Core Global Aggregate Bond UCITS ETF EUR Hedged", "global_bonds_hedged"),
        ("Amundi Obbligazionario Governativo Euro", "global_bonds_hedged"),
        ("iShares US Treasury Bond UCITS ETF", "global_bonds_hedged"),
        ("iShares Global Govt Bond UCITS ETF", "global_bonds_hedged"),
    ],
)
def test_each_name_keyword_rule(name, expected_bucket):
    holding = _holding(name=name, market_value=100.0)
    out = map_holdings([holding], BALANCED_TARGETS, INSTRUMENTS)
    assert out["mapped"] == [
        {"name": name, "bucket": expected_bucket, "rule": f"name_keyword_{expected_bucket}"}
    ]
    assert out["unmapped"] == []


def test_small_cap_keyword_wins_over_world_keyword_in_same_name():
    # "MSCI World" (a global_equity keyword) AND "Small Cap" both present:
    # small_cap must win per the mapping spec's explicit precedence rule.
    holding = _holding(name="iShares MSCI World Small Cap UCITS ETF USD (Acc)", market_value=300.0)
    out = map_holdings([holding], BALANCED_TARGETS, INSTRUMENTS)
    assert out["mapped"][0]["bucket"] == "small_cap"
    assert out["current_values"]["small_cap"] == 300.0
    assert out["current_values"]["global_equity"] == 0.0


def test_certificate_is_unmapped():
    holding = _holding(name="Leverage Shares Certificate on NVDA", asset_type="certificate")
    out = map_holdings([holding], BALANCED_TARGETS, INSTRUMENTS)
    assert out["mapped"] == []
    assert out["unmapped"] == [
        {
            "name": holding["name"],
            "asset_type": "certificate",
            "market_value": 1000.0,
            "why": "certificate",
        }
    ]


def test_leveraged_instrument_is_unmapped_even_if_name_matches_a_keyword():
    # Name would otherwise match the "world" keyword rule, but leverage > 1 makes it
    # satellite, not a target bucket -- rule 3 only applies when 1 and 2 didn't match,
    # so pick a name that does NOT also match a keyword to keep the two rules distinct.
    holding = _holding(name="3x Leveraged Nasdaq ETP", asset_type="etf", leverage=3.0)
    out = map_holdings([holding], BALANCED_TARGETS, INSTRUMENTS)
    assert out["mapped"] == []
    assert out["unmapped"][0]["why"] == "leveraged"


def test_single_stock_equity_is_unmapped():
    holding = _holding(name="Apple Inc", asset_type="equity", leverage=1.0, market_value=2_000.0)
    out = map_holdings([holding], BALANCED_TARGETS, INSTRUMENTS)
    assert out["mapped"] == []
    assert out["unmapped"] == [
        {
            "name": "Apple Inc",
            "asset_type": "equity",
            "market_value": 2_000.0,
            "why": "single_stock_equity",
        }
    ]


def test_unrecognized_instrument_falls_back_to_generic_unmapped_reason():
    # Not equity, not a certificate, not leveraged, and the name matches no keyword rule:
    # must not silently disappear from unmapped/coverage accounting.
    holding = _holding(name="Physical Gold ETC", asset_type="etf", leverage=1.0)
    out = map_holdings([holding], BALANCED_TARGETS, INSTRUMENTS)
    assert out["mapped"] == []
    assert out["unmapped"][0]["why"] == "no_bucket_rule_matched"


def test_coverage_is_mapped_value_over_total_value():
    holdings = [
        _holding(name="Vanguard FTSE All-World UCITS ETF", market_value=700.0),
        _holding(name="Apple Inc", asset_type="equity", market_value=300.0),
    ]
    out = map_holdings(holdings, BALANCED_TARGETS, INSTRUMENTS)
    assert out["coverage"] == pytest.approx(700.0 / 1000.0)


def test_empty_holdings_returns_zeroed_targets_and_zero_coverage():
    out = map_holdings([], BALANCED_TARGETS, INSTRUMENTS)
    assert out["current_values"] == dict.fromkeys(BALANCED_TARGETS, 0.0)
    assert out["mapped"] == []
    assert out["unmapped"] == []
    assert out["coverage"] == 0.0


def test_targets_bucket_absent_from_instruments_does_not_crash():
    targets = {"global_equity": 0.5, "commodities": 0.5}
    instruments = {"global_equity": INSTRUMENTS["global_equity"]}
    holding = _holding(name="Vanguard FTSE All-World UCITS ETF", market_value=500.0)
    out = map_holdings([holding], targets, instruments)
    assert out["current_values"] == {"global_equity": 500.0, "commodities": 0.0}


def test_result_can_be_fed_directly_into_allocate_cash_to_targets():
    from portfolio_copilot.portfolio.rebalance import allocate_cash_to_targets

    holdings = [
        _holding(name="Vanguard FTSE All-World UCITS ETF", market_value=6_000.0),
        _holding(
            name="Vanguard FTSE Emerging Markets UCITS ETF",
            market_value=500.0,
        ),
    ]
    out = map_holdings(holdings, BALANCED_TARGETS, INSTRUMENTS)
    result = allocate_cash_to_targets(
        current_values=out["current_values"],
        targets=BALANCED_TARGETS,
        cash_eur=1_000.0,
    )
    assert result["unallocated_cash"] >= 0


# ---------------------------------------------------------------------------
# finding 44: a leveraged/certificate/single-stock holding must stay satellite
# even when its name also happens to match a bucket keyword (rule 3 pre-empts
# rule 2 -- keyword matching is only rule 2, and only applies when nothing more
# specific overrides it)
# ---------------------------------------------------------------------------


def test_leveraged_instrument_matching_a_keyword_still_stays_satellite():
    holding = _holding(
        name="Xtrackers MSCI World 2x Leveraged Daily Swap UCITS ETF",
        asset_type="etf",
        leverage=2.0,
        market_value=3_000.0,
    )
    out = map_holdings([holding], BALANCED_TARGETS, INSTRUMENTS)
    assert out["mapped"] == []
    assert out["unmapped"][0]["why"] == "leveraged"
    assert out["current_values"]["global_equity"] == 0.0


def test_certificate_matching_a_keyword_still_stays_satellite():
    holding = _holding(
        name="Leverage Shares Certificate on MSCI World Small Cap",
        asset_type="certificate",
        market_value=1_000.0,
    )
    out = map_holdings([holding], BALANCED_TARGETS, INSTRUMENTS)
    assert out["mapped"] == []
    assert out["unmapped"][0]["why"] == "certificate"


def test_single_stock_equity_matching_a_keyword_still_stays_satellite():
    holding = _holding(
        name="World Emerging Bond Corp",  # matches world/emerging/bond keywords
        asset_type="equity",
        leverage=1.0,
        market_value=2_000.0,
    )
    out = map_holdings([holding], BALANCED_TARGETS, INSTRUMENTS)
    assert out["mapped"] == []
    assert out["unmapped"][0]["why"] == "single_stock_equity"


# ---------------------------------------------------------------------------
# finding 45: inverse/short leveraged instruments (negative leverage) must be
# classified as leveraged, matching risk.py/exposure.py's own abs() convention
# ---------------------------------------------------------------------------


def test_inverse_leveraged_instrument_is_classified_as_leveraged():
    holding = _holding(name="Inverse 3x Nasdaq ETP", asset_type="etf", leverage=-3.0)
    out = map_holdings([holding], BALANCED_TARGETS, INSTRUMENTS)
    assert out["unmapped"][0]["why"] == "leveraged"


# ---------------------------------------------------------------------------
# finding 46: a duplicate ISIN across two instrument buckets must be a loud
# config error, never a silent, arbitrary pick
# ---------------------------------------------------------------------------


def test_duplicate_isin_across_buckets_raises_instead_of_picking_silently():
    dup_isin = INSTRUMENTS["global_equity"]["isin"]
    instruments = dict(INSTRUMENTS)
    instruments["small_cap_dup"] = {**INSTRUMENTS["small_cap"], "isin": dup_isin}
    holding = _holding(name="Some fund", isin=dup_isin, market_value=1_000.0)
    with pytest.raises(ValueError, match=dup_isin):
        map_holdings([holding], BALANCED_TARGETS, instruments)


# ---------------------------------------------------------------------------
# finding 47: NaN/malformed market_value or leverage must degrade, never crash
# ---------------------------------------------------------------------------


def test_nan_market_value_does_not_poison_current_values():
    holdings = [
        _holding(name="Vanguard FTSE All-World UCITS ETF", market_value=float("nan")),
        _holding(name="Vanguard FTSE All-World UCITS ETF", market_value=9_000.0),
    ]
    out = map_holdings(holdings, BALANCED_TARGETS, INSTRUMENTS)
    assert out["current_values"]["global_equity"] == 9_000.0
    assert out["coverage"] == 1.0


def test_non_numeric_market_value_string_does_not_crash():
    holding = _holding(name="Vanguard FTSE All-World UCITS ETF", market_value="N/A")
    out = map_holdings([holding], BALANCED_TARGETS, INSTRUMENTS)  # must not raise
    assert out["current_values"]["global_equity"] == 0.0
