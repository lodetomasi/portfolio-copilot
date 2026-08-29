"""SEC EDGAR filings listing, 10-K item-section extraction and Form 4 insider-activity counts.

Zero-signup, same rate-limited `data.sec.gov` / `www.sec.gov` endpoints as ``sec_edgar.py``.
CIK resolution and the SEC-mandated User-Agent are reused from ``SECEdgarProvider`` (not
duplicated); this module adds its own throttle because listing + fetching filing documents
issues more requests per lookup than the company-facts snapshot does.

Tier A source. Everything returned carries ``source``/``as_of``/``confidence`` like the rest
of ``providers/``; a filing or section that cannot be found comes back as a readable, honest
result (``ok: False`` plus an explanation) rather than an exception or an invented value.
"""

from __future__ import annotations

import html as html_lib
import re
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta

import httpx

from portfolio_copilot.providers.cache import TTLCache
from portfolio_copilot.providers.sec_edgar import SECEdgarProvider

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
MAX_REQUESTS_PER_SECOND = 8.0
MAX_SECTION_CHARS = 20_000
INSIDER_FORMS = {"4", "4/A"}

_ITEM_HEADING_RE = re.compile(r"\bitem\s+(\d+[a-z]?)\b\.?", re.IGNORECASE)


class RateLimiter:
    """Leaky-bucket throttle: sleeps just enough to keep calls to <= ``max_per_second``.

    ``clock``/``sleeper`` are injectable so tests can drive it with a fake clock and record
    sleeps instead of actually waiting.
    """

    def __init__(
        self,
        max_per_second: float = MAX_REQUESTS_PER_SECOND,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_per_second <= 0:
            raise ValueError("max_per_second must be > 0")
        self._min_interval = 1.0 / max_per_second
        self._clock = clock
        self._sleep = sleeper
        self._last_call: float | None = None

    def wait(self) -> None:
        """Block (via ``sleeper``) if calling now would exceed the configured rate."""
        now = self._clock()
        if self._last_call is None:
            self._last_call = now
            return
        next_allowed = self._last_call + self._min_interval
        if now < next_allowed:
            self._sleep(next_allowed - now)
            self._last_call = next_allowed
        else:
            self._last_call = now


_rate_limiter = RateLimiter()
_submissions_cache = TTLCache(ttl_seconds=6 * 3600)
_document_cache = TTLCache(ttl_seconds=24 * 3600)


def _get(url: str, provider: SECEdgarProvider) -> httpx.Response:
    """Rate-limited GET with the SEC-mandated User-Agent and a timeout."""
    _rate_limiter.wait()
    response = httpx.get(
        url,
        timeout=provider.timeout,
        headers={"User-Agent": provider.user_agent},
        follow_redirects=True,
    )
    response.raise_for_status()
    return response


def _get_submissions(cik: int, provider: SECEdgarProvider) -> dict:
    key = str(int(cik))
    cached = _submissions_cache.get(key)
    if cached is not None:
        return cached
    data = _get(SUBMISSIONS_URL.format(cik=int(cik)), provider).json()
    if not isinstance(data, dict):
        # Mirrors sec_edgar.py's isinstance(table, dict) guard on the analogous
        # company_tickers.json payload: a 200 response is not a promise of the expected
        # shape, and a raw AttributeError/TypeError three call sites downstream is a far
        # worse failure than a clear, immediately-raised ValueError here.
        raise ValueError(
            f"Malformed SEC submissions payload for CIK {int(cik)}: expected a JSON "
            f"object, got {type(data).__name__}"
        )
    _submissions_cache.set(key, data)
    return data


def _get_text(url: str, provider: SECEdgarProvider) -> str:
    cached = _document_cache.get(url)
    if cached is not None:
        return cached
    text = _get(url, provider).text
    _document_cache.set(url, text)
    return text


def filing_url(cik: int, accession: str, primary_doc: str) -> str:
    """Public filing-document URL from a submissions-JSON row."""
    accession_nodashes = accession.replace("-", "")
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_nodashes}/{primary_doc}"


def list_filings(
    ticker: str,
    forms: tuple[str, ...] = ("10-K", "10-Q", "8-K"),
    limit: int = 10,
    provider: SECEdgarProvider | None = None,
) -> list[dict]:
    """Most recent filings for ``ticker`` matching any of ``forms``, newest first.

    Only the ``recent`` window of SEC's submissions JSON is read (older filings, which SEC
    moves into separate paginated ``files`` entries, are out of scope for this best-effort
    lookup). Returns ``[]`` -- not an error -- when the ticker has no SEC CIK or no filing
    matches ``forms`` (e.g. a foreign private issuer that files 20-F instead of 10-K).
    """
    if limit <= 0:
        raise ValueError("limit must be > 0")
    provider = provider or SECEdgarProvider()
    cik = provider.cik_for_ticker(ticker)
    if cik is None:
        return []
    wanted = {f.strip().upper() for f in forms}
    recent = _get_submissions(cik, provider).get("filings", {}).get("recent", {})
    rows = zip(
        recent.get("form", []),
        recent.get("filingDate", []),
        recent.get("accessionNumber", []),
        recent.get("primaryDocument", []),
        strict=False,
    )
    matches = [
        {
            "form": form,
            "filing_date": filing_date,
            "accession_number": accession,
            "primary_document": primary_doc,
        }
        for form, filing_date, accession, primary_doc in rows
        if form.strip().upper() in wanted
    ]
    matches.sort(key=lambda row: row["filing_date"], reverse=True)
    return matches[:limit]


def _strip_html(raw_html: str) -> str:
    """Tags/scripts/styles removed, entities unescaped, whitespace collapsed to single spaces."""
    text = re.sub(
        r"<(script|style)\b[^>]*>.*?</\1>", " ", raw_html, flags=re.IGNORECASE | re.DOTALL
    )
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def extract_items(html: str, items: tuple[str, ...] = ("1A", "7")) -> dict[str, str]:
    """Section text for each requested Item number/letter (e.g. '1A', '7', '7A', '8').

    Locates 'Item <N>' headings case-insensitively and takes everything up to the next
    'Item <M>' heading (or end of document). This is a naive, best-effort scan: a filing
    whose table of contents itself repeats the heading text ahead of the real section could
    return that (near-empty) span instead of the substantive one -- acceptable for a free-data
    provider that must never invent content, but not a substitute for a real filing parser.

    Each found section is capped at 20,000 characters. An item that is not found comes back
    as ``''``; if any are missing, a human-readable ``'_notes'`` entry explains which.
    """
    text = _strip_html(html)
    matches = list(_ITEM_HEADING_RE.finditer(text))
    out: dict[str, str] = {}
    missing_notes: list[str] = []
    for wanted in items:
        key = wanted.strip().upper()
        starts = [m for m in matches if m.group(1).upper() == key]
        if not starts:
            out[key] = ""
            missing_notes.append(f"Item {key} heading not found in filing text")
            continue
        start = starts[0]
        later = [m.start() for m in matches if m.start() > start.start()]
        end = min(later) if later else len(text)
        out[key] = text[start.end() : end].strip()[:MAX_SECTION_CHARS]
    if missing_notes:
        out["_notes"] = "; ".join(missing_notes)
    return out


def filing_sections(
    ticker: str,
    form: str = "10-K",
    items: tuple[str, ...] = ("1A", "7"),
    provider: SECEdgarProvider | None = None,
) -> dict:
    """Item sections of the most recent ``form`` filing for ``ticker``, with provenance.

    A ticker with no SEC CIK, or no filing of the requested ``form`` (foreign private
    issuers file 20-F instead of 10-K, for example), comes back as a readable ``ok: False``
    result explaining why -- never as an exception or invented text.
    """
    provider = provider or SECEdgarProvider()
    ticker_norm = ticker.strip().upper()
    base = {
        "ticker": ticker_norm,
        "form": form,
        "source": "sec_edgar_filings",
        "tier": "A",
        "fetched_at": datetime.now(UTC).isoformat(),
    }
    cik = provider.cik_for_ticker(ticker_norm)
    if cik is None:
        return {
            **base,
            "ok": False,
            "confidence": 0.0,
            "error": f"Ticker not found in SEC list: {ticker_norm}",
        }
    filings = list_filings(ticker_norm, forms=(form,), limit=1, provider=provider)
    if not filings:
        return {
            **base,
            "ok": False,
            "cik": cik,
            "confidence": 0.0,
            "error": (
                f"No {form} filing found for {ticker_norm} in SEC EDGAR's recent filings "
                "(e.g. a foreign private issuer filing 20-F instead of 10-K)"
            ),
        }
    latest = filings[0]
    url = filing_url(cik, latest["accession_number"], latest["primary_document"])
    sections = extract_items(_get_text(url, provider), items=items)
    keys = [wanted.strip().upper() for wanted in items]
    missing = [key for key in keys if not sections.get(key)]
    available = len(items) - len(missing)
    return {
        **base,
        "ok": available > 0,
        "cik": cik,
        "accession_number": latest["accession_number"],
        "as_of": latest["filing_date"],
        "url": url,
        "sections": sections,
        "missing_fields": missing,
        "confidence": round(0.9 * available / len(items), 2) if items else 0.0,
    }


def _coerce_date(value: str | date | datetime) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


def insider_activity(
    ticker: str,
    days: int = 90,
    as_of: str | date | datetime | None = None,
    provider: SECEdgarProvider | None = None,
) -> dict:
    """Form 4 / 4-A filing counts in the trailing ``days`` window, from the submissions JSON.

    Counts filing *events* only -- Form 4's XML body (which insider, how many shares, buy vs.
    sell) is not parsed, so this is an activity signal ("how much insider paperwork lately"),
    never a net buy/sell tally. That limitation is always stated in the result.
    """
    if days <= 0:
        raise ValueError("days must be > 0")
    provider = provider or SECEdgarProvider()
    ticker_norm = ticker.strip().upper()
    reference = _coerce_date(as_of) if as_of is not None else datetime.now(UTC).date()
    window_start = reference - timedelta(days=days)
    base = {
        "ticker": ticker_norm,
        "source": "sec_edgar_filings",
        "tier": "A",
        "as_of": reference.isoformat(),
        "window_days": days,
        "limitations": [
            "Counts Form 4 / 4-A filing events only; does not parse the transaction XML "
            "(insider, shares, price, buy vs. sell), so this is an activity signal, not a "
            "net trade tally."
        ],
    }
    cik = provider.cik_for_ticker(ticker_norm)
    if cik is None:
        return {
            **base,
            "ok": False,
            "confidence": 0.0,
            "filing_count": None,
            "filing_dates": [],
            "error": f"Ticker not found in SEC list: {ticker_norm}",
        }
    recent = _get_submissions(cik, provider).get("filings", {}).get("recent", {})
    filing_dates_all = recent.get("filingDate", [])
    rows = zip(recent.get("form", []), filing_dates_all, strict=False)
    dates = sorted(
        (
            filing_date
            for form, filing_date in rows
            if form.strip().upper() in INSIDER_FORMS
            and window_start.isoformat() <= filing_date <= reference.isoformat()
        ),
        reverse=True,
    )
    # SEC's paginated 'recent' window can be crowded out by other filing types for a
    # high-frequency filer, so it may not actually reach back `days` -- if its earliest
    # entry is more recent than window_start, the count could understate real activity.
    # Report that honestly with a lower confidence and an explicit limitation instead of
    # asserting the same 0.9 for a fully- and a partially-examined window alike.
    earliest_seen = min(filing_dates_all) if filing_dates_all else None
    window_fully_covered = earliest_seen is not None and earliest_seen <= window_start.isoformat()
    confidence = 0.9 if window_fully_covered else 0.5
    limitations = list(base["limitations"])
    if not window_fully_covered:
        limitations.append(
            "SEC's 'recent' filings window does not reach back to the full requested "
            f"{days}-day period; the count could understate actual insider activity."
        )
    return {
        **base,
        "limitations": limitations,
        "ok": True,
        "cik": cik,
        "confidence": confidence,
        "filing_count": len(dates),
        "filing_dates": dates,
    }
