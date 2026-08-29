"""Generate docs/PICKER_BACKTEST.md: a disclosed PROXY backtest of the stock picker's
scoring logic over free, point-in-time-honest data (see portfolio/picker_backtest.py for
exactly what each proxy component measures and why it is not the production scorer).

Universe: ~20 liquid US names spanning market caps and sectors (the picker ranks by
potential across the WHOLE universe -- no exclusion by size or index membership) against
a world-equity benchmark. Quarterly rebalances over the last 5 years, 6-month forward
horizon. Every number is a REPLAY, never a forecast; every structural limitation
(survivorship, Yahoo backfill risk, no transaction costs, event-dated-not-consensus
revisions, small-sample warnings) is disclosed verbatim in the report.

Run: `uv run python scripts/picker_backtest_report.py` (network needed). Never run this in
tests -- it is excluded from the test suite on purpose (see tests/test_picker_backtest.py
for the offline, deterministic coverage of the engine this script drives).
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pandas as pd
import yfinance as yf

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from portfolio_copilot.portfolio.picker_backtest import run_proxy_backtest  # noqa: E402
from portfolio_copilot.providers import sec_edgar  # noqa: E402
from portfolio_copilot.providers.sec_edgar import SECEdgarProvider  # noqa: E402
from portfolio_copilot.providers.yfinance_estimates import fetch_rating_events  # noqa: E402
from portfolio_copilot.providers.yfinance_surprises import fetch_surprise_history  # noqa: E402

OUT = ROOT / "docs" / "PICKER_BACKTEST.md"

# ~20 liquid US names deliberately spanning market caps and sectors: mega-cap tech,
# financials, healthcare, energy, staples, industrials and several small/mid caps. The
# picker's binding principle is "no exclusion by size" -- this universe mixes them on
# purpose rather than curating a large-cap-only sample.
DEFAULT_UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",  # mega-cap tech
    "META", "JPM", "JNJ", "XOM", "PG",  # mega-cap, mixed sectors
    "COST", "UNH", "V", "HD", "CAT",  # large-cap, mixed sectors
    "DE", "LULU", "ETSY", "CROX", "PLNT",  # mid/small-cap, mixed sectors
]
BENCHMARK_PRIMARY = "VWCE.MI"
BENCHMARK_FALLBACK = "ACWI"
MIN_PRICE_ROWS = 252  # ~1 trading year; below this, momentum/forward-return can't work

PRICE_PERIOD = "6y"
HORIZON_MONTHS = 6
REBALANCE_YEARS = 5
EPS_TAGS = ["EarningsPerShareDiluted", "EarningsPerShareBasic"]


def fetch_prices(ticker: str) -> pd.Series | None:
    """Daily closes for ``ticker`` over ``PRICE_PERIOD``, tz-naive. ``None`` on any failure."""
    try:
        hist = yf.Ticker(ticker).history(period=PRICE_PERIOD, auto_adjust=True)
    except Exception as exc:  # yfinance can raise almost anything (HTTP, parsing, rate limit)
        print(f"  prices: {ticker} failed ({exc!r})")
        return None
    if not (isinstance(hist, pd.DataFrame) and "Close" in hist.columns and not hist.empty):
        return None
    closes = hist["Close"].dropna()
    index = pd.DatetimeIndex(closes.index)
    if index.tz is not None:
        index = index.tz_localize(None)
    closes.index = index
    return closes


def _fetch_company_facts_json(ticker: str, provider: SECEdgarProvider) -> dict | None:
    """Raw SEC EDGAR companyfacts JSON for ``ticker``, or ``None`` if it has no CIK.

    Deliberately does not call ``SECEdgarProvider``'s private ``_get_json``/cache (the WP
    for this script must not modify sec_edgar.py): reuses its public ``cik_for_ticker``,
    ``FACTS_URL`` and ``user_agent``/``timeout`` instead, with its own one-shot HTTP call.
    """
    cik = provider.cik_for_ticker(ticker)
    if cik is None:
        return None
    response = httpx.get(
        sec_edgar.FACTS_URL.format(cik=cik),
        timeout=provider.timeout,
        headers={"User-Agent": provider.user_agent},
        follow_redirects=True,
    )
    response.raise_for_status()
    return response.json()


def _annual_rows(facts: dict, tags: list[str]) -> list[dict]:
    """One row per fiscal-period end (10-K/10-K/A, fp=='FY', ~1-year duration), picking the
    most-recently-filed report of each period across every tag in ``tags``.

    Two real SEC XBRL quirks make this trickier than it looks, both seen live on AAPL:

    - filers change tags over time (Apple: ``Revenues`` pre-2018, then
      ``RevenueFromContractWithCustomerExcludingAssessedTax``) -- an early tag with only
      old rows must never shadow a later tag that carries the recent years, so every tag
      is scanned (no early break on the first one with any match).
    - a single 10-K repeats 2-3 years of comparative figures, all stamped with that
      filing's own ``fy`` -- e.g. a FY2024 10-K's comparative FY2022 row also carries
      ``fy: 2024``. Grouping by ``fy`` therefore silently drops periods; the real period
      identity is ``end`` (duration end date). Deduping picks the EARLIEST ``filed`` for
      each ``end`` -- the original 10-K, not a later filing's restated comparative column
      -- so a period's ``filed`` date is genuinely "as first disclosed", never delayed by
      years past when investors could actually have known it.
    """
    gaap = facts.get("facts", {}).get("us-gaap", {})
    by_end: dict[str, dict] = {}
    for tag in tags:
        units = gaap.get(tag, {}).get("units", {})
        for unit_rows in units.values():
            for r in unit_rows:
                if r.get("form") not in {"10-K", "10-K/A"} or r.get("fp") != "FY":
                    continue
                end, start, filed = r.get("end"), r.get("start"), r.get("filed")
                if not (end and start and filed):
                    continue
                try:
                    duration_days = (date.fromisoformat(end) - date.fromisoformat(start)).days
                except ValueError:
                    continue
                if not (340 <= duration_days <= 390):  # reject stray non-annual durations
                    continue
                existing = by_end.get(end)
                if existing is None or filed < existing["filed"]:
                    by_end[end] = r
    return [by_end[end] for end in sorted(by_end)]


def extract_asfiled_fundamentals(facts: dict) -> list[dict]:
    """``[{end, filed, revenue, eps}]`` -- one row per fiscal year, as-filed (10-K only).

    Point-in-time by construction: ``filed`` is the SEC filing date of that 10-K, ``end``
    its fiscal-year end. Quarterly (10-Q) figures are deliberately not used: XBRL duration
    facts for a quarter are not reliably non-cumulative across filers, while annual 10-K
    figures are unambiguous. This means ``fundamental_momentum`` in picker_backtest.py
    effectively updates once per fiscal year, not every quarter (disclosed in the report).
    """
    revenue_rows = {r["end"]: r for r in _annual_rows(facts, sec_edgar.CONCEPTS["revenue"])}
    eps_rows = {r["end"]: r for r in _annual_rows(facts, EPS_TAGS)}
    rows = []
    for end in sorted(set(revenue_rows) | set(eps_rows)):
        rev_r, eps_r = revenue_rows.get(end), eps_rows.get(end)
        filed_candidates = [r["filed"] for r in (rev_r, eps_r) if r and r.get("filed")]
        rows.append(
            {
                "end": end,
                "filed": max(filed_candidates) if filed_candidates else None,
                "revenue": float(rev_r["val"]) if rev_r else None,
                "eps": float(eps_r["val"]) if eps_r else None,
            }
        )
    return rows


def fetch_fundamentals(ticker: str, provider: SECEdgarProvider) -> list[dict]:
    """As-filed ``[{end, filed, revenue, eps}]`` rows, ``[]`` on any failure (never raises).

    Foreign filers (20-F/ADRs) and tickers SEC doesn't recognise legitimately have no
    us-gaap facts -- an empty list, not an error, matching this project's "degrade, never
    fabricate" rule.
    """
    try:
        facts = _fetch_company_facts_json(ticker, provider)
    except Exception as exc:  # one ticker's unexpected failure must not abort the whole run
        print(f"  fundamentals: {ticker} failed ({exc!r})")
        return []
    return extract_asfiled_fundamentals(facts) if facts else []


def _fmt_pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def build_universe(
    tickers: list[str], provider: SECEdgarProvider
) -> tuple[dict[str, dict], list[str]]:
    """Fetch prices/surprises/fundamentals/rating events for every ticker.

    A ticker with too little price history to compute momentum or a forward return at all
    is dropped up front and reported as skipped; everything else degrades field by field
    inside ``proxy_score_at``/``run_proxy_backtest`` (never raises, never invents data).
    """
    universe: dict[str, dict] = {}
    skipped: list[str] = []
    today = date.today()
    for ticker in tickers:
        print(f"fetching {ticker} ...")
        prices = fetch_prices(ticker)
        if prices is None or len(prices) < MIN_PRICE_ROWS:
            skipped.append(ticker)
            continue
        universe[ticker] = {
            "prices": prices,
            "surprises": fetch_surprise_history(ticker, today).quarters,
            "fundamentals": fetch_fundamentals(ticker, provider),
            "rating_events": fetch_rating_events(ticker, today),
        }
    return universe, skipped


def fetch_benchmark() -> tuple[pd.Series | None, str]:
    prices = fetch_prices(BENCHMARK_PRIMARY)
    if prices is not None and len(prices) >= MIN_PRICE_ROWS:
        return prices, BENCHMARK_PRIMARY
    print(f"  benchmark {BENCHMARK_PRIMARY} unusable, falling back to {BENCHMARK_FALLBACK}")
    prices = fetch_prices(BENCHMARK_FALLBACK)
    return prices, BENCHMARK_FALLBACK


def render_report(
    *,
    as_of: str,
    universe: dict[str, dict],
    all_tickers: list[str],
    skipped: list[str],
    benchmark_ticker: str,
    rebalance_dates: list[pd.Timestamp],
    result: dict,
) -> str:
    lines = [
        "# Stock-picker PROXY backtest",
        "",
        f"Generated {as_of} by `scripts/picker_backtest_report.py`.",
        "",
        "> **Disclosed PROXY, not the production scorer.** This replays a simplified, "
        "point-in-time-honest proxy of `scoring/engine.py` -- price momentum, an "
        "as-filed fundamental-growth signal, an earnings-surprise track record, and "
        "analyst rating-change momentum -- on free data only. It is a REPLAY, not a "
        "forecast, and it is not the real V1 scorer (no quality/valuation/catalysts "
        "components here). See `portfolio/picker_backtest.py` for exactly what each "
        "proxy component measures.",
        "",
        "## Disclosures (verbatim from the engine)",
        "",
    ]
    lines += [f"- {d}" for d in result["disclosures"]]
    lines += [
        "",
        "## Universe",
        "",
        f"Benchmark: `{benchmark_ticker}`"
        + (
            f" (fallback -- {BENCHMARK_PRIMARY} had insufficient history)."
            if benchmark_ticker != BENCHMARK_PRIMARY
            else "."
        ),
        "",
        f"Scored: {len(universe)}/{len(all_tickers)} tickers -- "
        f"{', '.join(sorted(universe)) if universe else 'none'}.",
    ]
    if skipped:
        lines.append(f"Skipped (insufficient price history): {', '.join(skipped)}.")
    lines += [
        "",
        "## Aggregates",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| rebalance dates attempted | {len(rebalance_dates)} |",
        f"| periods with a computable excess return | {result['n_periods']} |",
        f"| mean excess return (top quantile equal-weight vs benchmark) | "
        f"{_fmt_pct(result['mean_excess'])} |",
        f"| hit rate (share of periods beating the benchmark) | "
        f"{_fmt_pct(result['hit_rate'])} |",
        f"| t-stat of excess return | "
        f"{result['t_stat']:.2f} |" if result["t_stat"] is not None else "| t-stat of excess return | n/a |",
        "",
        "## Per-rebalance detail",
        "",
        "| date | n scored | n top | n skipped | top return | benchmark return | excess | hit |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in result["rows"]:
        hit = "n/a" if row["hit"] is None else ("yes" if row["hit"] else "no")
        lines.append(
            f"| {row['date']} | {row['n_scored']} | {row['n_top']} | {row['n_skipped']} | "
            f"{_fmt_pct(row['top_return'])} | {_fmt_pct(row['benchmark_return'])} | "
            f"{_fmt_pct(row['excess'])} | {hit} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tickers",
        help="Comma-separated ticker override (default: the fixed ~20-name universe below).",
    )
    args = parser.parse_args(argv)
    tickers = [t.strip().upper() for t in args.tickers.split(",")] if args.tickers else list(
        DEFAULT_UNIVERSE
    )

    as_of = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    provider = SECEdgarProvider()

    benchmark, benchmark_ticker = fetch_benchmark()
    if benchmark is None:
        print(f"No usable benchmark data ({BENCHMARK_PRIMARY} or {BENCHMARK_FALLBACK}); aborting.")
        return 1

    universe, skipped = build_universe(tickers, provider)
    if not universe:
        print("No ticker had enough price history to score; aborting.")
        return 1

    end = pd.Timestamp.today().normalize() - pd.DateOffset(months=HORIZON_MONTHS)
    start = end - pd.DateOffset(years=REBALANCE_YEARS)
    rebalance_dates = list(pd.date_range(start=start, end=end, freq="QS"))

    result = run_proxy_backtest(
        universe, benchmark, rebalance_dates=rebalance_dates, horizon_months=HORIZON_MONTHS
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        render_report(
            as_of=as_of,
            universe=universe,
            all_tickers=tickers,
            skipped=skipped,
            benchmark_ticker=benchmark_ticker,
            rebalance_dates=rebalance_dates,
            result=result,
        ),
        encoding="utf-8",
    )
    print(
        f"wrote {OUT} -- {len(universe)}/{len(tickers)} tickers scored, "
        f"{result['n_periods']} periods, mean_excess={result['mean_excess']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
