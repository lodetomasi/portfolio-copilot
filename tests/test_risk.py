from portfolio_copilot.models import AssetType, Holding, Portfolio
from portfolio_copilot.portfolio.risk import summarize_portfolio_risk


def test_summarize_portfolio_risk_empty_portfolio():
    portfolio = Portfolio(holdings=[])
    result = summarize_portfolio_risk(portfolio)
    assert result["total_value"] == 0.0
    assert result["weights"] == []
    assert result["leveraged_nominal_value"] == 0.0
    assert result["leveraged_equivalent_exposure"] == 0.0


def test_summarize_portfolio_risk_unleveraged_only():
    portfolio = Portfolio(
        holdings=[
            Holding(name="Stock A", asset_type=AssetType.EQUITY, market_value=600.0, leverage=1.0),
            Holding(name="Stock B", asset_type=AssetType.EQUITY, market_value=400.0, leverage=1.0),
        ]
    )
    result = summarize_portfolio_risk(portfolio)
    assert result["total_value"] == 1000.0
    assert len(result["weights"]) == 2
    assert round(result["weights"][0]["weight"], 4) == 0.6
    assert round(result["weights"][1]["weight"], 4) == 0.4
    assert result["leveraged_nominal_value"] == 0.0
    assert result["leveraged_nominal_weight"] == 0.0
    assert result["leveraged_equivalent_exposure"] == 0.0
    assert result["leveraged_equivalent_to_portfolio"] == 0.0


def test_summarize_portfolio_risk_with_leveraged_holdings():
    portfolio = Portfolio(
        holdings=[
            Holding(name="Plain ETF", asset_type=AssetType.ETF, market_value=800.0, leverage=1.0),
            Holding(
                name="Leveraged Long ETC",
                asset_type=AssetType.CERTIFICATE,
                market_value=100.0,
                leverage=3.0,
            ),
            Holding(
                name="Leveraged Short ETC",
                asset_type=AssetType.CERTIFICATE,
                market_value=100.0,
                leverage=-2.0,
            ),
        ]
    )
    result = summarize_portfolio_risk(portfolio)
    assert result["total_value"] == 1000.0
    # only the two |leverage| > 1.0 holdings count toward leveraged nominal/equivalent
    assert result["leveraged_nominal_value"] == 200.0
    assert round(result["leveraged_nominal_weight"], 4) == 0.2
    # equivalent exposure = sum(market_value * |leverage|) = 100*3 + 100*2 = 500
    assert result["leveraged_equivalent_exposure"] == 500.0
    assert round(result["leveraged_equivalent_to_portfolio"], 4) == 0.5
