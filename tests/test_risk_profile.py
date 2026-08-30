"""Offline, deterministic tests for the risk-profile questionnaire, drawdown budget, and
persistence. No network: ``observed_drawdowns`` is exercised via a fake in-memory provider
built from the synthetic ``drawdown_history_sample.json`` fixture.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest
import yaml
from pydantic import ValidationError

from portfolio_copilot.portfolio.plan import load_model_portfolios
from portfolio_copilot.portfolio.risk_profile import (
    DEFAULT_STRESS_DD,
    RiskAnswers,
    derive_profile,
    drawdown_budget,
    fits,
    load_risk_profile,
    observed_drawdowns,
    risk_profile_path,
    save_risk_profile,
    suggest_profile,
)

FIXTURES = Path(__file__).parent / "fixtures"
MODEL_PORTFOLIOS = Path(__file__).resolve().parents[1] / "config" / "model_portfolios.yaml"


def _answers(**overrides) -> RiskAnswers:
    base = dict(
        max_drawdown_pct=35,
        speculative_share_pct=10,
        leverage="none",
        emergency_fund=True,
        horizon_years=10.0,
        reaction_to_minus_30="hold",
    )
    base.update(overrides)
    return RiskAnswers(**base)


# ---------------------------------------------------------------------------
# RiskAnswers validation
# ---------------------------------------------------------------------------


def test_risk_answers_rejects_invalid_max_drawdown_pct():
    with pytest.raises(ValidationError):
        _answers(max_drawdown_pct=33)


def test_risk_answers_rejects_invalid_speculative_share_pct():
    with pytest.raises(ValidationError):
        _answers(speculative_share_pct=15)


def test_risk_answers_rejects_invalid_leverage():
    with pytest.raises(ValidationError):
        _answers(leverage="5x")


def test_risk_answers_rejects_invalid_reaction():
    with pytest.raises(ValidationError):
        _answers(reaction_to_minus_30="panic")


# ---------------------------------------------------------------------------
# suggest_profile / derive_profile mapping matrix
# ---------------------------------------------------------------------------


def test_no_emergency_fund_is_always_cautious_even_with_high_speculative_appetite():
    a = _answers(emergency_fund=False, horizon_years=20, speculative_share_pct=60)
    assert suggest_profile(a) == "cautious"


def test_short_horizon_is_cautious():
    a = _answers(horizon_years=2.0)
    assert suggest_profile(a) == "cautious"


def test_horizon_at_3_years_is_not_cautious_on_that_ground_alone():
    a = _answers(horizon_years=3.0, speculative_share_pct=10)
    assert suggest_profile(a) == "balanced"


def test_long_horizon_and_would_hold_or_buy_is_growth():
    a = _answers(horizon_years=8.0, reaction_to_minus_30="buy", speculative_share_pct=10)
    assert suggest_profile(a) == "growth"


def test_long_horizon_but_would_sell_falls_back_to_balanced():
    a = _answers(horizon_years=15.0, reaction_to_minus_30="sell", speculative_share_pct=10)
    assert suggest_profile(a) == "balanced"


def test_medium_horizon_is_balanced():
    a = _answers(horizon_years=5.0, reaction_to_minus_30="hold", speculative_share_pct=10)
    assert suggest_profile(a) == "balanced"


def test_high_speculative_share_overrides_growth_base_to_aggressive_thematic():
    a = _answers(horizon_years=20.0, reaction_to_minus_30="buy", speculative_share_pct=25)
    assert suggest_profile(a) == "aggressive_thematic"


def test_high_speculative_share_overrides_balanced_base_to_aggressive_thematic():
    a = _answers(horizon_years=5.0, reaction_to_minus_30="hold", speculative_share_pct=40)
    assert suggest_profile(a) == "aggressive_thematic"


def test_speculative_share_just_below_threshold_does_not_trigger_aggressive_thematic():
    a = _answers(horizon_years=20.0, reaction_to_minus_30="buy", speculative_share_pct=10)
    assert suggest_profile(a) == "growth"


@pytest.mark.parametrize("speculative", [25, 40, 60])
def test_leverage_none_sets_no_flag(speculative):
    a = _answers(horizon_years=20.0, speculative_share_pct=speculative, leverage="none")
    derived = derive_profile(a)
    assert derived.profile == "aggressive_thematic"
    assert derived.leverage_requested is False
    assert derived.leverage_note is None


@pytest.mark.parametrize("leverage", ["up_to_10", "up_to_25"])
def test_leverage_other_than_none_sets_flag_but_same_profile(leverage):
    a = _answers(horizon_years=20.0, speculative_share_pct=25, leverage=leverage)
    derived = derive_profile(a)
    assert derived.profile == "aggressive_thematic"
    assert derived.leverage_requested is True
    assert derived.leverage_note is not None
    assert "NOT supported" in derived.leverage_note


def test_leverage_flag_independent_of_profile_chosen():
    # Leverage requested even when the base profile ends up 'cautious' (no emergency
    # fund): the flag is orthogonal to which profile the answers land on.
    a = _answers(emergency_fund=False, leverage="up_to_10")
    derived = derive_profile(a)
    assert derived.profile == "cautious"
    assert derived.leverage_requested is True


# ---------------------------------------------------------------------------
# config/model_portfolios.yaml: profiles sum to 1, use known buckets
# ---------------------------------------------------------------------------


def test_model_portfolios_yaml_profiles_sum_to_one():
    models = load_model_portfolios(MODEL_PORTFOLIOS)
    assert set(models["profiles"]) >= {"cautious", "balanced", "growth", "aggressive_thematic"}
    for name, profile in models["profiles"].items():
        assert sum(profile.targets.values()) == pytest.approx(1.0), name


def test_aggressive_thematic_profile_matches_spec_targets():
    models = load_model_portfolios(MODEL_PORTFOLIOS)
    targets = models["profiles"]["aggressive_thematic"].targets
    assert targets == {
        "global_equity": 0.70,
        "small_cap": 0.05,
        "thematic": 0.20,
        "single_stocks": 0.05,
    }


def test_thematic_bucket_has_at_least_four_candidate_etfs_capped_at_5pct_each():
    raw = yaml.safe_load(MODEL_PORTFOLIOS.read_text(encoding="utf-8"))
    thematic = raw["instruments"]["thematic"]
    assert "max 5%" in thematic["rule"]
    assert "4" in thematic["rule"]
    candidates = thematic["candidates"]
    assert len(candidates) >= 4
    for candidate in candidates:
        assert candidate["yf_ticker"]
        assert candidate["name"]


def test_single_stocks_bucket_has_no_fixed_instrument_and_is_routed_to_etoro():
    raw = yaml.safe_load(MODEL_PORTFOLIOS.read_text(encoding="utf-8"))
    single_stocks = raw["instruments"]["single_stocks"]
    assert "yf_ticker" not in single_stocks
    assert single_stocks["routed_to"] == "etoro_satellite"


def test_every_target_bucket_used_by_a_profile_is_a_known_instrument_or_thematic_or_single_stocks():
    raw = yaml.safe_load(MODEL_PORTFOLIOS.read_text(encoding="utf-8"))
    known = set(raw["instruments"])
    for name, spec in raw["profiles"].items():
        for bucket in spec["targets"]:
            assert bucket in known, f"{name} targets unknown bucket {bucket!r}"


# ---------------------------------------------------------------------------
# drawdown_budget arithmetic
# ---------------------------------------------------------------------------


def test_drawdown_budget_weighted_observed_and_stress():
    targets = {"global_equity": 0.7, "global_bonds_hedged": 0.3}
    history = {"global_equity": -0.50, "global_bonds_hedged": -0.05}
    stress = {"global_equity": -0.55, "global_bonds_hedged": -0.10}
    budget = drawdown_budget(targets, history, stress)
    assert budget["observed"] == pytest.approx(0.7 * -0.50 + 0.3 * -0.05)
    assert budget["stress"] == pytest.approx(0.7 * -0.55 + 0.3 * -0.10)
    assert budget["observed_missing_buckets"] == []
    assert budget["stress_missing_buckets"] == []


def test_drawdown_budget_uses_default_stress_when_not_supplied():
    targets = {"global_equity": 1.0}
    budget = drawdown_budget(targets, {"global_equity": -0.40})
    assert budget["stress"] == pytest.approx(DEFAULT_STRESS_DD["global_equity"])


def test_drawdown_budget_partial_stress_override_keeps_other_defaults():
    targets = {"global_equity": 0.5, "thematic": 0.5}
    budget = drawdown_budget(targets, {"global_equity": -0.3, "thematic": -0.6}, {"thematic": -0.9})
    assert budget["stress_dd_used"]["global_equity"] == DEFAULT_STRESS_DD["global_equity"]
    assert budget["stress_dd_used"]["thematic"] == -0.9


def test_drawdown_budget_missing_observed_bucket_degrades_to_none_not_invented():
    targets = {"global_equity": 0.7, "thematic": 0.3}
    budget = drawdown_budget(targets, {"global_equity": -0.4})  # thematic history missing
    assert budget["observed"] is None
    assert budget["observed_missing_buckets"] == ["thematic"]
    # stress still computable: DEFAULT_STRESS_DD covers both buckets.
    assert budget["stress"] is not None


def test_drawdown_budget_missing_bucket_is_never_treated_as_zero():
    # A bucket entirely missing from history_dd must not silently contribute 0 to the sum;
    # observed must be None, not the value of the buckets that *were* covered.
    targets = {"global_equity": 0.5, "small_cap": 0.5}
    budget = drawdown_budget(targets, {"global_equity": -0.4})
    assert budget["observed"] is None
    partial_sum_if_bug = 0.5 * -0.4
    assert budget["observed"] != partial_sum_if_bug


# ---------------------------------------------------------------------------
# fits() + verdict text
# ---------------------------------------------------------------------------


def test_fits_both_true_when_within_budget():
    budget = {"observed": -0.30, "stress": -0.34}
    out = fits(budget, max_drawdown_pct=35)
    assert out["fits_observed"] is True
    assert out["fits_stress"] is True
    assert "holds in both" in out["verdict"]


def test_fits_observed_true_stress_false_matches_worked_example():
    # The exact scenario from the spec: stated -35%, observed -35.6% rounds to -36% but the
    # boundary example uses -35% observed exactly and -55% stress.
    budget = {"observed": -0.35, "stress": -0.55}
    out = fits(budget, max_drawdown_pct=35)
    assert out["fits_observed"] is True
    assert out["fits_stress"] is False
    assert "holds in a 2020-type crash, not in a 2008-type one" in out["verdict"]
    assert "-55%" in out["verdict"]


def test_fits_both_false_when_observed_already_breaches_budget():
    budget = {"observed": -0.45, "stress": -0.65}
    out = fits(budget, max_drawdown_pct=35)
    assert out["fits_observed"] is False
    assert out["fits_stress"] is False
    assert "does not hold even in a 2020-type crash" in out["verdict"]


def test_fits_missing_data_reports_gap_not_a_guessed_boolean():
    budget = {"observed": None, "observed_missing_buckets": ["thematic"], "stress": -0.5,
              "stress_missing_buckets": []}
    out = fits(budget, max_drawdown_pct=35)
    assert out["fits_observed"] is False
    assert out["fits_stress"] is False
    assert "missing" in out["verdict"]
    assert "thematic" in out["verdict"]


# ---------------------------------------------------------------------------
# observed_drawdowns via a fake provider built from the synthetic fixture
# ---------------------------------------------------------------------------


class _FakeProvider:
    """Mimics YFinanceProvider.get_monthly_closes's contract: bucket-named columns,
    ``attrs['missing']`` listing requested buckets absent from the fixture. No network."""

    def __init__(self, buckets: dict[str, list[float]]):
        self._buckets = buckets

    def get_monthly_closes(self, tickers: dict[str, str], period: str = "5y") -> pd.DataFrame:
        frames = {}
        missing = []
        for bucket in tickers:
            series = self._buckets.get(bucket)
            if series is None:
                missing.append(bucket)
                continue
            frames[bucket] = pd.Series(series)
        df = pd.DataFrame(frames)
        df.attrs["missing"] = missing
        return df


@pytest.fixture()
def drawdown_history_fixture() -> dict:
    return json.loads((FIXTURES / "drawdown_history_sample.json").read_text(encoding="utf-8"))


def test_observed_drawdowns_from_fixture(drawdown_history_fixture):
    provider = _FakeProvider(drawdown_history_fixture["buckets"])
    instruments = {
        "global_equity": "VWCE.MI",
        "small_cap": "IUSN.DE",
        "emerging_markets": "VFEA.MI",
        "global_bonds_hedged": "AGGH.MI",
    }
    out = observed_drawdowns(provider, instruments)
    assert out["global_equity"] == pytest.approx(-1 / 3)
    assert out["small_cap"] == pytest.approx(-28 / 58)
    assert out["emerging_markets"] == pytest.approx(-9 / 21)
    assert out["global_bonds_hedged"] == pytest.approx(-3 / 100.5)


def test_observed_drawdowns_missing_bucket_degrades_to_none(drawdown_history_fixture):
    provider = _FakeProvider(drawdown_history_fixture["buckets"])
    instruments = {"global_equity": "VWCE.MI", "thematic": "SMH.MI"}  # thematic not in fixture
    out = observed_drawdowns(provider, instruments)
    assert out["global_equity"] == pytest.approx(-1 / 3)
    assert out["thematic"] is None


def test_observed_drawdowns_empty_instruments_returns_empty_dict():
    provider = _FakeProvider({})
    assert observed_drawdowns(provider, {}) == {}


# ---------------------------------------------------------------------------
# save_risk_profile / load_risk_profile roundtrip, history append
# ---------------------------------------------------------------------------


def test_load_risk_profile_returns_none_when_never_answered(tmp_path):
    assert load_risk_profile(home=tmp_path) is None


def test_save_and_load_roundtrip(tmp_path):
    a = _answers(horizon_years=20.0, speculative_share_pct=25, reaction_to_minus_30="buy")
    derived = derive_profile(a).model_dump()
    saved = save_risk_profile(a, derived, home=tmp_path)
    loaded = load_risk_profile(home=tmp_path)
    assert loaded == saved
    assert loaded["answers"]["horizon_years"] == 20.0
    assert loaded["derived"]["profile"] == "aggressive_thematic"
    assert len(loaded["history"]) == 1
    assert loaded["history"][0]["event"] == "first questionnaire answered"


def test_save_risk_profile_appends_history_on_reask_without_losing_it(tmp_path):
    a1 = _answers(horizon_years=20.0)
    save_risk_profile(a1, derive_profile(a1).model_dump(), home=tmp_path)

    a2 = _answers(horizon_years=2.0, emergency_fund=False)
    saved2 = save_risk_profile(a2, derive_profile(a2).model_dump(), home=tmp_path)

    assert len(saved2["history"]) == 2
    assert saved2["history"][0]["event"] == "first questionnaire answered"
    assert saved2["history"][1]["event"] == "questionnaire re-answered"
    # The re-ask's answers/derived overwrite the top-level fields (latest is authoritative)...
    assert saved2["answers"]["horizon_years"] == 2.0
    assert saved2["derived"]["profile"] == "cautious"
    # ...but nothing before it was silently dropped: history keeps growing, never reset.
    loaded = load_risk_profile(home=tmp_path)
    assert loaded == saved2


def test_save_risk_profile_rejects_invalid_answers_dict(tmp_path):
    with pytest.raises(ValidationError):
        save_risk_profile({"max_drawdown_pct": 999}, {}, home=tmp_path)


def test_risk_profile_path_created_under_home(tmp_path):
    path = risk_profile_path(home=tmp_path)
    assert path == tmp_path / "risk_profile.json"
    assert tmp_path.exists()


def test_load_risk_profile_raises_on_corrupted_file(tmp_path):
    (tmp_path / "risk_profile.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        load_risk_profile(home=tmp_path)


# ---------------------------------------------------------------------------
# The pre-existing data/private/risk_profile.json schema must stay loadable.
# ---------------------------------------------------------------------------


def test_existing_risk_profile_schema_is_loadable(tmp_path):
    existing = {
        "as_of": "2026-08-29",
        "version": 1,
        "answers": {
            "max_drawdown_pct": 35,
            "speculative_share_pct": 25,
            "leverage": "none",
            "emergency_fund": True,
            "horizon_years": 20,
            "reaction_to_minus_30": "buy",
            "preferences": "likes risky/thematic ETFs with drawdowns; no daily-reset "
            "leveraged products (5X certificates being closed)",
        },
        "derived": {
            "profile": "aggressive_thematic",
            "drawdown_budget": {
                "stated_max": -0.35,
                "P1_70_5_20_5": {"observed": -0.356, "stress_2008": -0.555},
                "P2_65_5_10_5_15bond": {"observed": -0.329, "stress_2008": -0.475},
            },
            "note": "stated -35% holds for a 2020-type crash on a 100% equity base, not "
            "for a 2008-type one",
        },
        "reask_policy": "at annual review (2027-08-28) or on explicit request; every skill "
        "must load this file before sizing and stop to ask if missing",
        "history": [
            {"date": "2026-08-29", "event": "first questionnaire (4 questions) answered in chat"}
        ],
    }
    path = risk_profile_path(home=tmp_path)
    path.write_text(json.dumps(existing), encoding="utf-8")
    loaded = load_risk_profile(home=tmp_path)
    assert loaded == existing
    # RiskAnswers itself must also accept the six mapped fields from that file (extra
    # 'preferences' key ignored by the six-field mapping, not by persistence).
    answers = RiskAnswers(**{k: v for k, v in existing["answers"].items() if k != "preferences"})
    assert suggest_profile(answers) == "aggressive_thematic"


def test_observed_drawdowns_not_truncated_by_short_sibling_bucket():
    """Finding #9: the real provider inner-joins buckets on shared dates
    (``pd.DataFrame(frames).dropna()``); a short-history sibling bucket must never
    silently erase another bucket's crash from its own drawdown."""

    long_index = pd.period_range("2020-01", periods=12, freq="M").to_timestamp("M")
    crash = pd.Series(
        [100.0, 80.0, 47.0, 60.0, 70.0, 80.0, 85.0, 90.0, 95.0, 98.0, 99.0, 100.0],
        index=long_index,
    )
    recent = pd.Series([50.0, 51.0, 52.0], index=long_index[-3:])

    class InnerJoinProvider:
        def get_monthly_closes(self, tickers: dict[str, str], period: str = "5y"):
            series = {"crash": crash, "recent": recent}
            frames = {b: series[b] for b in tickers if b in series}
            df = pd.DataFrame(frames).dropna()  # same inner join as the real provider
            df.attrs["missing"] = [b for b in tickers if b not in series]
            return df

    out = observed_drawdowns(InnerJoinProvider(), {"crash": "CRSH", "recent": "RCNT"})
    assert out["crash"] == pytest.approx(-0.53)
    assert out["recent"] == pytest.approx(0.0)


def test_fits_verdict_consistent_when_stress_milder_than_observed():
    budget = {
        "observed": -0.40,
        "observed_missing_buckets": [],
        "stress": -0.30,
        "stress_missing_buckets": [],
    }
    out = fits(budget, max_drawdown_pct=35)
    assert out["fits_observed"] is False
    assert out["fits_stress"] is True
    assert "only in the 2008-type stress estimate" in out["verdict"]
