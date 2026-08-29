"""Deterministic macro regime snapshot: Eurostat HICP/unemployment + the ECB deposit rate.

Pure combinator -- it fetches nothing itself, only reads what the two providers it is given
return, and never guesses a missing value. A `regime` label is only computed when both the
ECB deposit facility rate (DFR) and HICP are present; either missing makes the regime
'unknown', with the formula string saying so instead of silently defaulting to 'neutral'.
"""

from __future__ import annotations

import math
from typing import Any, Protocol

REGIME_BAND_PP = 1.0  # DFR-minus-HICP spread (percentage points) separating neutral from the rest


class _EurostatLike(Protocol):
    def hicp_annual_rate(self, geo: str = "EA20") -> dict[str, Any]: ...

    def unemployment_rate(self, geo: str = "EU27_2020") -> dict[str, Any]: ...


class _ECBLike(Protocol):
    def deposit_facility_rate(self) -> dict[str, Any]: ...


def _slim(series: dict[str, Any] | None) -> dict[str, Any]:
    """Keep only the fields macro_snapshot promises for each underlying series.

    ``confidence`` is always included -- every provider in this module sets it, and
    CLAUDE.md rule 5 requires every external datum to carry source/as_of/confidence.
    """
    if not series:
        return {"value": None, "as_of": None, "source": None, "tier": None, "confidence": None}
    return {
        "value": series.get("value"),
        "as_of": series.get("as_of"),
        "source": series.get("source"),
        "tier": series.get("tier"),
        "confidence": series.get("confidence"),
    }


def _is_finite_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def macro_snapshot(
    eurostat: _EurostatLike,
    ecb: _ECBLike,
    geo: str = "EA20",
    unemployment_geo: str = "EU27_2020",
) -> dict[str, Any]:
    """Combine HICP, unemployment and the ECB deposit facility rate into one macro read.

    `geo` drives HICP (euro area = EA20); `unemployment_geo` drives une_rt_m, which has no
    EA20 aggregate (EU27_2020 or a country code). `regime` is 'restrictive' when
    DFR - HICP > 1pp, 'accommodative' when < -1pp, 'neutral' within that band (inclusive),
    and 'unknown' whenever DFR or HICP is missing.
    """
    hicp = _slim(eurostat.hicp_annual_rate(geo=geo))
    unemployment = _slim(eurostat.unemployment_rate(geo=unemployment_geo))
    dfr = _slim(ecb.deposit_facility_rate())

    hicp_value, dfr_value = hicp["value"], dfr["value"]
    if not _is_finite_number(hicp_value) or not _is_finite_number(dfr_value):
        regime = "unknown"
        formula = (
            "regime undetermined: dfr and/or hicp missing "
            f"(dfr={dfr_value!r}, hicp={hicp_value!r}) -- never guessed"
        )
    else:
        spread = dfr_value - hicp_value
        formula = f"dfr({dfr_value:.2f}) - hicp({hicp_value:.2f}) = {spread:.2f}pp"
        if spread > REGIME_BAND_PP:
            regime = "restrictive"
        elif spread < -REGIME_BAND_PP:
            regime = "accommodative"
        else:
            regime = "neutral"

    return {
        "hicp": hicp,
        "unemployment": unemployment,
        "dfr": dfr,
        "regime": regime,
        "regime_formula": formula,
    }
