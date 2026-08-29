"""Venue-specific order-sizing profiles.

The two accounts size orders differently: eToro trades fractional USD *amounts*
with a per-instrument minimum exposure; the export account (the other broker,
manual-only) trades whole units in EUR, sized against the fixed-fee minimum
economic order. ``size_order`` is the single place that turns a target cash
amount and a unit price into a concrete order line for a given venue -- it
never rounds up past what the cash, the price, or the venue's minimum allow.
"""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal

from pydantic import BaseModel


class VenueProfile(BaseModel):
    """Static description of how a venue sizes and prices an order line."""

    name: str
    currency: str
    fractional: bool
    unit_rounding: str  # "none" for fractional venues, "floor" for whole-unit ones
    fee_model_source: str
    min_order_source: str


ETORO = VenueProfile(
    name="etoro",
    currency="USD",
    fractional=True,
    unit_rounding="none",
    fee_model_source="none (settlementType=real, leverage=1, no commission on real stock/ETF)",
    min_order_source="POST /api/v2/trading/info/eligibility -> minPositionExposure",
)

EXPORT = VenueProfile(
    name="export",
    currency="EUR",
    fractional=False,
    unit_rounding="floor",
    fee_model_source="portfolio.rebalance.FeeModel",
    min_order_source="portfolio.rebalance.FeeModel.minimum_economic_order",
)


def size_order(
    amount: float,
    price: float | None,
    venue: VenueProfile,
    min_order: float,
    min_exposure: float | None = None,
) -> dict:
    """Size one order line for ``venue`` given a target cash ``amount`` and unit ``price``.

    eToro (fractional): the amount is kept as given; ``units`` is informational
    (``amount / price``). The line is dropped only when ``amount`` is below
    ``min_exposure`` (eligibility's ``minPositionExposure``) -- ``min_order`` is
    unused for this venue.

    Export (whole units): ``units = floor(amount / price)``, and the line is
    dropped when that is ``0`` or the resulting amount (``units * price``) is
    below ``min_order`` (the minimum economic order). Never rounds up.

    A missing or non-positive ``price``, or a non-positive ``amount``, always
    drops the line -- a price is never invented.

    Returns ``{"units": float | None, "amount": float, "dropped_reason": str | None}``.
    """
    if price is None or price <= 0:
        return {"units": None, "amount": 0.0, "dropped_reason": "missing_price"}
    if amount <= 0:
        return {"units": None, "amount": 0.0, "dropped_reason": "non_positive_amount"}

    if venue.fractional:
        if min_exposure is not None and amount < min_exposure:
            return {"units": None, "amount": 0.0, "dropped_reason": "below_min_exposure"}
        return {"units": amount / price, "amount": float(amount), "dropped_reason": None}

    # Exact decimal floor: float `//` loses a whole unit to representation error
    # (e.g. 4784.65 // 4.33 == 1104.0 while 4.33 * 1105 == 4784.65 exactly).
    units = float(
        (Decimal(str(amount)) / Decimal(str(price))).to_integral_value(rounding=ROUND_FLOOR)
    )
    if units < 1:
        return {"units": None, "amount": 0.0, "dropped_reason": "below_one_unit"}
    resulting_amount = units * price
    if resulting_amount < min_order:
        return {"units": None, "amount": 0.0, "dropped_reason": "below_min_order"}
    return {"units": units, "amount": float(resulting_amount), "dropped_reason": None}
