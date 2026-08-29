import pytest

from portfolio_copilot.models import AssetType
from portfolio_copilot.portfolio.sources import (
    account_banner,
    portfolio_from_etoro,
    resolve_source,
    source_unavailable_message,
)


def test_resolve_source_path_given_is_always_export():
    assert resolve_source("export.csv", etoro_configured=False) == "export"
    assert resolve_source("export.csv", etoro_configured=True) == "export"


def test_resolve_source_no_path_uses_etoro_when_configured():
    assert resolve_source(None, etoro_configured=True) == "etoro"


def test_resolve_source_neither_available_is_none():
    assert resolve_source(None, etoro_configured=False) == "none"
    assert resolve_source("", etoro_configured=False) == "none"


def test_source_unavailable_message_only_for_none():
    assert source_unavailable_message("export") == ""
    assert source_unavailable_message("etoro") == ""
    message = source_unavailable_message("none")
    assert "ETORO_API_KEY" in message
    assert "etoro.env" in message


def test_account_banner_etoro_demo_default():
    assert account_banner("etoro") == "Account: eToro DEMO (virtual)"
    assert account_banner("etoro", mode="demo") == "Account: eToro DEMO (virtual)"


def test_account_banner_etoro_real():
    assert account_banner("etoro", mode="real") == "Account: eToro REAL"
    assert account_banner("etoro", mode="REAL") == "Account: eToro REAL"


def test_account_banner_export_names_the_file():
    assert account_banner("export", export_name="export.csv") == (
        "Account: export file export.csv (manual orders only)"
    )


def test_account_banner_export_without_name_is_unnamed():
    assert account_banner("export") == "Account: export file (unnamed) (manual orders only)"


def test_account_banner_none():
    assert account_banner("none") == "Account: none configured"


def _position(**overrides):
    base = {
        "symbol": "AAPL",
        "name": "Apple",
        "units": 2.0,
        "current_rate": 200.0,
        "instrument_type": "stock",
        "leverage": 1.0,
    }
    base.update(overrides)
    return base


def test_portfolio_from_etoro_converts_to_eur_with_fx_rate():
    portfolio, cash_eur, _missing = portfolio_from_etoro(
        positions=[_position()],
        account={"currency": "USD", "cash_available": 1000.0},
        fx_rate_eur_per_ccy=0.92,
    )
    assert portfolio.base_currency == "EUR"
    assert portfolio.source == "etoro_api"
    holding = portfolio.holdings[0]
    assert holding.symbol == "AAPL"
    assert holding.quantity == 2.0
    assert holding.market_price == 200.0
    # native value = 2 * 200 = 400 USD -> 400 * 0.92 EUR
    assert holding.market_value == 368.0
    assert cash_eur == 920.0


def test_portfolio_from_etoro_without_fx_rate_keeps_account_currency():
    portfolio, cash_eur, _missing = portfolio_from_etoro(
        positions=[_position()],
        account={"currency": "USD", "cash_available": 1000.0},
        fx_rate_eur_per_ccy=None,
    )
    assert portfolio.base_currency == "USD"
    assert portfolio.holdings[0].market_value == 400.0
    assert cash_eur is None


def test_portfolio_from_etoro_eur_account_never_needs_fx_rate():
    portfolio, cash_eur, _missing = portfolio_from_etoro(
        positions=[_position()],
        account={"currency": "EUR", "cash_available": 500.0},
        fx_rate_eur_per_ccy=None,
    )
    assert portfolio.base_currency == "EUR"
    assert portfolio.holdings[0].market_value == 400.0
    assert cash_eur == 500.0


def test_portfolio_from_etoro_asset_type_mapping():
    portfolio, _, _missing = portfolio_from_etoro(
        positions=[_position(instrument_type="etf"), _position(instrument_type=None)],
        account={"currency": "EUR"},
        fx_rate_eur_per_ccy=None,
    )
    assert portfolio.holdings[0].asset_type == AssetType.ETF
    assert portfolio.holdings[1].asset_type == AssetType.OTHER


def test_portfolio_from_etoro_leverage_defaults_to_one_when_missing():
    portfolio, _, _missing = portfolio_from_etoro(
        positions=[_position(leverage=None), _position(leverage=5.0)],
        account={"currency": "EUR"},
        fx_rate_eur_per_ccy=None,
    )
    assert portfolio.holdings[0].leverage == 1.0
    assert portfolio.holdings[1].leverage == 5.0


def test_portfolio_from_etoro_missing_fields_become_none_never_invented():
    portfolio, cash_eur, _missing = portfolio_from_etoro(
        positions=[{"symbol": "XYZ"}],
        account={},
        fx_rate_eur_per_ccy=None,
    )
    holding = portfolio.holdings[0]
    assert holding.quantity == 0.0
    assert holding.market_price is None
    assert holding.market_value == 0.0
    assert cash_eur is None


def test_portfolio_from_etoro_uses_explicit_market_value_when_present():
    portfolio, _, _missing = portfolio_from_etoro(
        positions=[_position(market_value=999.0)],
        account={"currency": "EUR"},
        fx_rate_eur_per_ccy=None,
    )
    assert portfolio.holdings[0].market_value == 999.0


def test_portfolio_from_etoro_name_falls_back_to_symbol():
    portfolio, _, _missing = portfolio_from_etoro(
        positions=[{"symbol": "XYZ", "units": 1.0, "current_rate": 10.0}],
        account={"currency": "EUR"},
        fx_rate_eur_per_ccy=None,
    )
    assert portfolio.holdings[0].name == "XYZ"


def test_portfolio_from_etoro_cash_none_when_not_convertible():
    portfolio, cash_eur, _missing = portfolio_from_etoro(
        positions=[],
        account={"currency": "USD", "cash_available": 100.0},
        fx_rate_eur_per_ccy=None,
    )
    assert portfolio.holdings == []
    assert cash_eur is None


# ---------------------------------------------------------------------------
# Real EToroClient.positions() schema (finding #12/#13), missing value flag (#11),
# fx validation (#15)
# ---------------------------------------------------------------------------


def test_portfolio_from_etoro_reads_real_client_position_keys():
    portfolio, cash_eur, missing = portfolio_from_etoro(
        positions=[
            {
                "symbol": "AAPL",
                "units": 2.0,
                "open_rate": 150.0,
                "amount": 300.0,
                "pnl": 20.0,
                "is_buy": True,
                "leverage": 1.0,
            }
        ],
        account={"currency": "USD", "cash_available": 1000.0},
        fx_rate_eur_per_ccy=0.92,
    )
    holding = portfolio.holdings[0]
    assert holding.quantity == 2.0
    # invested amount + unrealized P/L = current value, converted to EUR
    assert holding.market_value == pytest.approx((300.0 + 20.0) * 0.92)
    assert missing == []


def test_portfolio_from_etoro_short_position_gets_negative_quantity():
    portfolio, _, missing = portfolio_from_etoro(
        positions=[
            {
                "symbol": "AAPL",
                "units": 2.0,
                "open_rate": 150.0,
                "amount": 300.0,
                "pnl": 20.0,
                "is_buy": False,
            }
        ],
        account={"currency": "USD", "cash_available": 0.0},
        fx_rate_eur_per_ccy=0.92,
    )
    holding = portfolio.holdings[0]
    assert holding.quantity == -2.0
    assert holding.market_value == pytest.approx(294.4)
    assert missing == []


def test_portfolio_from_etoro_known_quantity_without_any_value_is_flagged_not_zeroed():
    portfolio, _, missing = portfolio_from_etoro(
        positions=[{"symbol": "XYZ", "units": 3.0}],
        account={"currency": "EUR"},
        fx_rate_eur_per_ccy=None,
    )
    assert len(portfolio.holdings) == 1  # coverage is never silently lost
    assert portfolio.holdings[0].market_value == 0.0
    assert missing == ["XYZ"]


def test_portfolio_from_etoro_rejects_non_positive_fx_rate():
    for bad in (0.0, -1.0):
        with pytest.raises(ValueError):
            portfolio_from_etoro(
                positions=[], account={"currency": "USD"}, fx_rate_eur_per_ccy=bad
            )
