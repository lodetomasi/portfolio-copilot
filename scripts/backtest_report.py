"""Generate docs/BACKTEST.md: replay of the plan rules on past prices for every model
portfolio (free data, yfinance with stooq fallback) plus performance benchmarks of the
deterministic engines. Replay ≠ forecast; the report says so on every table.

Run: `uv run python scripts/backtest_report.py` (network needed for the price history).
"""

from __future__ import annotations

import csv
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from portfolio_copilot.parsers.broker_export import parse_portfolio_export  # noqa: E402
from portfolio_copilot.portfolio.backtest import simulate_cash_flow_plan  # noqa: E402
from portfolio_copilot.portfolio.plan import load_model_portfolios  # noqa: E402
from portfolio_copilot.portfolio.rebalance import FeeModel, allocate_cash_to_targets  # noqa: E402
from portfolio_copilot.providers.stooq import StooqProvider  # noqa: E402
from portfolio_copilot.providers.yfinance_provider import YFinanceProvider  # noqa: E402

OUT = ROOT / "docs" / "BACKTEST.md"
INITIAL = 5000.0
MONTHLY = 300.0
PERIODS = ("5y", "10y")


def fetch_closes(tickers: dict[str, str], period: str) -> tuple[pd.DataFrame, str, list[str]]:
    """yfinance first, stooq for buckets yfinance misses. Returns (closes, sources, missing)."""
    yf_df = YFinanceProvider().get_monthly_closes(tickers, period=period)
    sources = {b: "yfinance" for b in yf_df.columns}
    missing = list(yf_df.attrs.get("missing", []))
    if missing:
        st = StooqProvider().get_monthly_closes({b: tickers[b] for b in missing}, period=period)
        for b in st.columns:
            sources[b] = "stooq"
        missing = [b for b in missing if b not in st.columns]
        if not st.empty:
            yf_df = yf_df.join(st, how="inner") if not yf_df.empty else st
    return yf_df, ", ".join(f"{b}: {s}" for b, s in sources.items()), missing


def replay_all() -> list[dict]:
    models = load_model_portfolios()
    rows = []
    for name, profile in models["profiles"].items():
        tickers = {b: models["instruments"][b]["yf_ticker"] for b in profile.targets}
        for period in PERIODS:
            try:
                closes, sources, missing = fetch_closes(tickers, period)
            except Exception as exc:  # network failure: report, never invent
                rows.append({"profile": name, "period": period, "error": f"{type(exc).__name__}: {exc}"})
                continue
            usable = {b: w for b, w in profile.targets.items() if b in closes.columns}
            if len(closes) < 24 or not usable:
                rows.append({"profile": name, "period": period, "error": f"insufficient data (rows={len(closes)}, missing={missing})"})
                continue
            total = sum(usable.values())
            targets = {b: w / total for b, w in usable.items()}
            res = simulate_cash_flow_plan(
                closes, targets, initial_cash=INITIAL, monthly_contribution=MONTHLY,
                fee_model=FeeModel(), rebalance_band_abs=0.03,
            )
            rows.append({
                "profile": name, "period": period, "from": str(closes.index[0].date()), "to": str(closes.index[-1].date()),
                "months": res["months"], "contributed": res["contributed_eur"], "final": res["final_value_eur"],
                "gain": res["gain_eur"], "fees": res["fees_eur"], "fees_pct": res["fees_pct_of_contributions"],
                "orders": res["orders"], "max_dd": res["max_drawdown"], "oob": res["months_out_of_band_pct"],
                "cash_left": res["cash_left_eur"], "sources": sources, "missing": missing,
            })
    return rows


def benchmarks() -> list[dict]:
    out = []
    # parser: 1000-row synthetic export
    tmp = ROOT / ".pytest_report"
    tmp.mkdir(exist_ok=True)
    path = tmp / "bench_export.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh, delimiter=";", lineterminator="\n")
        w.writerow(["Titolo", "Strumento", "Valuta", "Quantità", "P.zo medio\ndi carico", "P.zo di\nmercato", "Val di mercato €\n(Margine)", "Var €", "Var %"])
        for i in range(1000):
            w.writerow([f"SYNTHETIC ETF {i}", "ETF", "EUR", "10", "100,00", "101,00", "1.010,00", "+10,00", "+1,00%"])
    t0 = time.perf_counter()
    p = parse_portfolio_export(str(path))
    dt = time.perf_counter() - t0
    out.append({"engine": "parser (1000 rows)", "seconds": dt, "detail": f"{len(p.holdings)} holdings"})

    rng = np.random.default_rng(0)
    t0 = time.perf_counter()
    for _ in range(1000):
        cur = {k: float(v) for k, v in zip("ABCD", rng.uniform(0, 5000, 4), strict=True)}
        allocate_cash_to_targets(cur, {"A": 0.5, "B": 0.3, "C": 0.15, "D": 0.05}, float(rng.uniform(0, 2000)), FeeModel())
    dt = time.perf_counter() - t0
    out.append({"engine": "allocator (1000 random scenarios)", "seconds": dt, "detail": f"{dt / 1000 * 1e3:.2f} ms/scenario"})

    rets = rng.normal(0.004, 0.05, size=(240, 3))
    prices = pd.DataFrame(100 * np.exp(np.cumsum(rets, axis=0)), columns=["A", "B", "C"])
    t0 = time.perf_counter()
    simulate_cash_flow_plan(prices, {"A": 0.6, "B": 0.3, "C": 0.1}, initial_cash=5000, monthly_contribution=300)
    dt = time.perf_counter() - t0
    out.append({"engine": "backtest (240 months, 3 buckets)", "seconds": dt, "detail": "synthetic seeded path"})
    return out


def main() -> int:
    as_of = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    rows = replay_all()
    bench = benchmarks()
    lines = [
        "# Backtest & performance report",
        "",
        f"Generated {as_of} by `scripts/backtest_report.py`.",
        "",
        "> **Replay, not forecast.** Each row replays the plan rules (cash-flow-first waterfall + top-up, "
        f"fee {FeeModel().fixed_fee_eur} EUR/order, max fee ratio 1%, band ±3%, {INITIAL:.0f} EUR initial + "
        f"{MONTHLY:.0f} EUR/month, never sells) on past monthly prices from free sources. Past prices say nothing "
        "about future returns; the useful KPIs are fees paid, months out of band and idle cash — those measure the RULES. "
        "`period` is what was requested; `from → to` is the common window actually available for every bucket "
        "(some UCITS ETF share classes have short listings, so a 10y request may replay fewer months).",
        "",
        "## Model portfolios replayed",
        "",
        "| profile | period | from → to | months | contributed € | final € | gain € | fees € (% of contrib.) | orders | max drawdown | months out of band | cash left € | sources |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for r in rows:
        if "error" in r:
            lines.append(f"| {r['profile']} | {r['period']} | — | — | — | — | — | — | — | — | — | — | **not available**: {r['error']} |")
            continue
        lines.append(
            f"| {r['profile']} | {r['period']} | {r['from']} → {r['to']} | {r['months']} | {r['contributed']:,.0f} | {r['final']:,.0f} | "
            f"{r['gain']:,.0f} | {r['fees']:,.2f} ({r['fees_pct']:.2%}) | {r['orders']} | {r['max_dd']:.1%} | {r['oob']:.0%} | {r['cash_left']:,.2f} | {r['sources']}"
            + (f"; missing: {r['missing']}" if r["missing"] else "") + " |"
        )
    lines += [
        "",
        "Reading the table: `fees %` should stay ≤ 1% (the cap the engine enforces per order); `cash left` should be "
        "below one minimum economic order (295 €); `months out of band` shows how often drift exceeded ±3% before "
        "new cash pulled it back — the engine never sells, so long trends keep a bucket out of band until contributions catch up.",
        "",
        "## Performance benchmarks (deterministic engines, this machine)",
        "",
        "| engine | seconds | detail |",
        "|---|---:|---|",
    ]
    for b in bench:
        lines.append(f"| {b['engine']} | {b['seconds']:.3f} | {b['detail']} |")
    med = statistics.median(b["seconds"] for b in bench)
    lines += ["", f"Median engine call: {med:.3f} s. All engines are pure Python/pandas; no network in the benchmark rows."]
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT}: {len(rows)} replay rows ({sum(1 for r in rows if 'error' in r)} unavailable), {len(bench)} benchmarks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
