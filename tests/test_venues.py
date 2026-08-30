from portfolio_copilot.portfolio.venues import ETORO, EXPORT, VenueProfile, size_order


def test_etoro_profile_is_fractional_usd():
    assert ETORO.name == "etoro"
    assert ETORO.currency == "USD"
    assert ETORO.fractional is True
    assert ETORO.unit_rounding == "none"


def test_export_profile_is_whole_unit_eur():
    assert EXPORT.name == "export"
    assert EXPORT.currency == "EUR"
    assert EXPORT.fractional is False
    assert EXPORT.unit_rounding == "floor"


def test_size_order_etoro_kept_amount_is_informational_units():
    result = size_order(150.0, 200.0, ETORO, min_order=0.0, min_exposure=100.0)
    assert result["dropped_reason"] is None
    assert result["amount"] == 150.0
    assert result["units"] == 0.75


def test_size_order_etoro_below_min_exposure_is_dropped():
    result = size_order(50.0, 200.0, ETORO, min_order=0.0, min_exposure=100.0)
    assert result["dropped_reason"] == "below_min_exposure"
    assert result["units"] is None
    assert result["amount"] == 0.0


def test_size_order_etoro_no_min_exposure_never_drops_on_size():
    result = size_order(1.0, 200.0, ETORO, min_order=0.0, min_exposure=None)
    assert result["dropped_reason"] is None
    assert result["amount"] == 1.0


def test_size_order_export_whole_units_floor_and_kept():
    result = size_order(310.0, 100.0, EXPORT, min_order=295.0)
    assert result["dropped_reason"] is None
    assert result["units"] == 3.0
    assert result["amount"] == 300.0


def test_size_order_export_never_rounds_up():
    # floor(199 / 100) = 1, never 2 -- the amount used is units * price, not the ask.
    result = size_order(199.0, 100.0, EXPORT, min_order=50.0)
    assert result["units"] == 1.0
    assert result["amount"] == 100.0


def test_size_order_export_below_one_unit_is_dropped():
    result = size_order(50.0, 100.0, EXPORT, min_order=1.0)
    assert result["dropped_reason"] == "below_one_unit"
    assert result["units"] is None


def test_size_order_export_below_min_order_is_dropped_even_with_units():
    # 1 unit at 100 = 100 EUR, below the 295 EUR minimum economic order.
    result = size_order(150.0, 100.0, EXPORT, min_order=295.0)
    assert result["dropped_reason"] == "below_min_order"
    assert result["units"] is None
    assert result["amount"] == 0.0


def test_size_order_missing_price_is_dropped_for_both_venues():
    for venue in (ETORO, EXPORT):
        result = size_order(100.0, None, venue, min_order=1.0)
        assert result["dropped_reason"] == "missing_price"
        assert result["units"] is None


def test_size_order_non_positive_price_is_dropped():
    result = size_order(100.0, 0.0, EXPORT, min_order=1.0)
    assert result["dropped_reason"] == "missing_price"


def test_size_order_non_positive_amount_is_dropped_for_both_venues():
    for venue in (ETORO, EXPORT):
        result = size_order(0.0, 100.0, venue, min_order=1.0)
        assert result["dropped_reason"] == "non_positive_amount"
        result_neg = size_order(-5.0, 100.0, venue, min_order=1.0)
        assert result_neg["dropped_reason"] == "non_positive_amount"


def test_size_order_is_deterministic():
    first = size_order(310.0, 99.99, EXPORT, min_order=295.0)
    second = size_order(310.0, 99.99, EXPORT, min_order=295.0)
    assert first == second


def test_venue_profile_is_a_pydantic_model():
    custom = VenueProfile(
        name="custom",
        currency="GBP",
        fractional=True,
        unit_rounding="none",
        fee_model_source="none",
        min_order_source="none",
    )
    assert custom.currency == "GBP"


def test_size_order_export_floor_does_not_lose_a_unit_to_float_error():
    # 4.33 * 1105 = 4784.65 exactly, but float `4784.65 // 4.33` yields 1104.
    result = size_order(4784.65, 4.33, EXPORT, min_order=0.0)
    assert result["dropped_reason"] is None
    assert result["units"] == 1105.0
    import pytest as _pytest

    assert result["amount"] == _pytest.approx(4784.65)
