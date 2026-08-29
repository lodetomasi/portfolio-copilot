from __future__ import annotations

import json

import typer
from rich import print

from portfolio_copilot.parsers.broker_export import parse_portfolio_export
from portfolio_copilot.portfolio.risk import summarize_portfolio_risk
from portfolio_copilot.providers.yfinance_provider import YFinanceProvider
from portfolio_copilot.scoring.engine import score_snapshot

app = typer.Typer(no_args_is_help=True)


@app.command()
def parse(path: str):
    """Parse a local broker portfolio export."""
    p = parse_portfolio_export(path)
    print(json.dumps(p.model_dump(mode="json"), indent=2, ensure_ascii=False))


@app.command()
def risk(path: str):
    """Portfolio risk summary."""
    p = parse_portfolio_export(path)
    print(json.dumps(summarize_portfolio_risk(p), indent=2, ensure_ascii=False))


@app.command()
def stock(ticker: str):
    """Analyze one ticker using the free provider."""
    snap = YFinanceProvider().get_stock_snapshot(ticker)
    score = score_snapshot(snap)
    print(json.dumps(score.model_dump(mode="json"), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    app()
