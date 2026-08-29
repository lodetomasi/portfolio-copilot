"""SEC EDGAR XBRL company facts (free, no key) for US-listed filers.

Audited annual figures from 10-K filings: revenue, net income, operating cash flow, capex,
equity. Used to cross-check the free market-data provider. Foreign filers (20-F, ADRs)
often have no us-gaap facts: the result then says so instead of inventing numbers.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime

import httpx

from portfolio_copilot.providers.cache import TTLCache

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
# SEC EDGAR returns HTTP 403 for any User-Agent that has no identifiable app name + contact
# (per https://www.sec.gov/os/webmaster-faq#developers). A description-only string (no email)
# is rejected, so the shipped default carries a placeholder contact to work out of the box.
# Override with PORTFOLIO_COPILOT_SEC_USER_AGENT to a real contact if SEC ever flags usage.
DEFAULT_USER_AGENT = (
    "portfolio-copilot/0.1 (contact@example.com; override via PORTFOLIO_COPILOT_SEC_USER_AGENT)"
)

# concept -> list of us-gaap tags to try, in order
CONCEPTS: dict[str, list[str]] = {
    "revenue": [
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "SalesRevenueNet",
    ],
    "net_income": ["NetIncomeLoss"],
    "operating_cash_flow": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment"],
    "equity": ["StockholdersEquity"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
}


def _annual_series(facts: dict, tags: list[str]) -> list[dict]:
    """Latest value per fiscal year from 10-K filings, newest first."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    for tag in tags:
        units = gaap.get(tag, {}).get("units", {})
        usd = units.get("USD") or next(iter(units.values()), [])
        annual = [
            r
            for r in usd
            if r.get("form") in {"10-K", "10-K/A"} and r.get("fp") == "FY" and "fy" in r
        ]
        if not annual:
            continue
        by_year: dict[int, dict] = {}
        for r in sorted(annual, key=lambda r: (r["fy"], r.get("filed", ""))):
            # keep the value whose period actually ends in that fiscal year (skip restated priors)
            if str(r.get("end", "")).startswith(str(r["fy"])) or r["fy"] not in by_year:
                by_year[r["fy"]] = r
        return [by_year[y] for y in sorted(by_year, reverse=True)]
    return []


def summarize_company_facts(facts: dict) -> dict:
    """Deterministic summary of the latest two fiscal years. Missing concepts stay None."""
    out: dict = {"cik": facts.get("cik"), "entity": facts.get("entityName"), "missing_fields": []}
    latest: dict[str, float | None] = {}
    previous: dict[str, float | None] = {}
    fy = None
    filed = None
    for concept, tags in CONCEPTS.items():
        series = _annual_series(facts, tags)
        latest[concept] = float(series[0]["val"]) if series else None
        previous[concept] = float(series[1]["val"]) if len(series) > 1 else None
        if series:
            fy = max(fy or 0, int(series[0]["fy"]))
            filed = max(filed or "", str(series[0].get("filed", "")))
        else:
            out["missing_fields"].append(concept)

    rev, rev_prev = latest["revenue"], previous["revenue"]
    cfo, capex = latest["operating_cash_flow"], latest["capex"]
    out.update(
        {
            "fiscal_year": fy,
            "filed": filed or None,
            "revenue": rev,
            "revenue_growth": (rev / rev_prev - 1.0) if rev and rev_prev else None,
            "net_income": latest["net_income"],
            "net_margin": (
                latest["net_income"] / rev if rev and latest["net_income"] is not None else None
            ),
            "free_cashflow": (cfo - abs(capex)) if cfo is not None and capex is not None else cfo,
            "equity": latest["equity"],
            "long_term_debt": latest["long_term_debt"],
        }
    )
    if out["free_cashflow"] is not None and capex is None:
        out["missing_fields"].append("capex (free_cashflow = operating cash flow only)")
    return out


class SECEdgarProvider:
    source_name = "sec_edgar"

    def __init__(self, timeout: float = 15.0, ttl_seconds: float = 24 * 3600) -> None:
        self.timeout = timeout
        self._cache = TTLCache(ttl_seconds)
        self.user_agent = os.environ.get("PORTFOLIO_COPILOT_SEC_USER_AGENT", DEFAULT_USER_AGENT)

    def _get_json(self, url: str) -> dict:
        cached = self._cache.get(url)
        if cached is not None:
            return cached
        response = httpx.get(
            url,
            timeout=self.timeout,
            headers={"User-Agent": self.user_agent},
            follow_redirects=True,
        )
        if response.status_code == 403:
            # Surface a clear, actionable one-liner instead of httpx's generic multi-line
            # message, which buries the actual cause (a rejected User-Agent) in a URL.
            raise httpx.HTTPStatusError(
                f"SEC EDGAR rejected the request with HTTP 403 -- the User-Agent "
                f"({self.user_agent!r}) likely doesn't meet SEC's fair-access policy; "
                f"set PORTFOLIO_COPILOT_SEC_USER_AGENT to an app name plus a real contact email.",
                request=response.request,
                response=response,
            )
        response.raise_for_status()
        data = response.json()
        self._cache.set(url, data)
        return data

    def cik_for_ticker(self, ticker: str) -> int | None:
        table = self._get_json(TICKERS_URL)
        if not isinstance(table, dict):
            raise ValueError(
                "SEC EDGAR company_tickers.json has an unexpected shape: "
                f"expected a dict of dicts, got {type(table).__name__}."
            )
        wanted = ticker.strip().upper()
        for row in table.values():
            if not isinstance(row, dict):
                raise ValueError(
                    "SEC EDGAR company_tickers.json has an unexpected shape: "
                    f"expected each entry to be a dict, got {type(row).__name__}."
                )
            if str(row.get("ticker", "")).upper() == wanted:
                return int(row["cik_str"])
        return None

    def get_company_facts(self, ticker: str) -> dict:
        cik = self.cik_for_ticker(ticker)
        base = {
            "ticker": ticker.strip().upper(),
            "source": self.source_name,
            "fetched_at": datetime.now(UTC).isoformat(),
        }
        if cik is None:
            return {**base, "ok": False, "confidence": 0.0, "error": "Ticker not found in SEC list"}
        summary = summarize_company_facts(self._get_json(FACTS_URL.format(cik=cik)))
        available = len(CONCEPTS) - len([m for m in summary["missing_fields"] if m in CONCEPTS])
        return {
            **base,
            **summary,
            "ok": available > 0,
            "confidence": round(0.95 * available / len(CONCEPTS), 2),
            "as_of": summary["filed"],
        }
