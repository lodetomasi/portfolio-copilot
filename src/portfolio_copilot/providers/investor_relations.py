"""Investor-relations page crawler: public pages only, robots-aware, no JS/login/paywall.

Tier A source: a company's own IR page is the primary source for earnings releases,
presentations, annual/quarterly reports, guidance and press releases. This module never
scrapes anything behind a login or a robots.txt disallow, and it never guesses a document's
date when the page text doesn't state one -- it returns ``None`` instead (CLAUDE.md rule 6).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

from portfolio_copilot.providers.cache import TTLCache

DEFAULT_USER_AGENT = "portfolio-copilot/0.1 (personal research)"
MAX_REQUESTS = 6  # hard cap on HTTP calls (robots.txt + candidate pages) per lookup

IR_PATHS = ("/investors", "/investor-relations", "/investor", "/ir")
IR_SUBDOMAINS = ("ir", "investors")

_KIND_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("annual_report", ("annual report", "form 10-k", "10-k", "annual results")),
    (
        "quarterly_report",
        ("quarterly report", "form 10-q", "10-q", "interim report", "quarterly results"),
    ),
    ("earnings_release", ("earnings release", "earnings call", "earnings", "results announcement")),
    ("guidance", ("guidance", "outlook")),
    ("presentation", ("presentation", "slides", "webcast", "investor day")),
    ("press_release", ("press release", "news release", "media release")),
)
_ALL_KINDS = tuple(kind for kind, _ in _KIND_RULES)
# Public alias so a caller building its own not-found envelope (e.g. server.py, before
# this provider is even reached) can report the same "everything is missing" shape.
ALL_IR_KINDS = _ALL_KINDS

_MONTHS = (
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
)
_MONTH_PATTERN = "|".join(_MONTHS)
_YEAR_PATTERN = r"20(?:2[4-9]|30)"  # 2024-2030, per spec
_DATE_WITH_MONTH_RE = re.compile(
    rf"\b(?:{_MONTH_PATTERN})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+{_YEAR_PATTERN}\b"
    rf"|\b\d{{1,2}}(?:st|nd|rd|th)?\s+(?:{_MONTH_PATTERN})\.?,?\s+{_YEAR_PATTERN}\b",
    re.IGNORECASE,
)
_YEAR_ONLY_RE = re.compile(rf"\b{_YEAR_PATTERN}\b")


def _normalize_host(website: str) -> str:
    """Bare lowercase host for a website string that may omit the scheme."""
    candidate = website.strip()
    if not candidate:
        raise ValueError("website must not be empty")
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    host = urlparse(candidate).netloc
    if not host:
        raise ValueError(f"could not determine a host from {website!r}")
    return host.lower()


def candidate_ir_urls(website: str) -> list[str]:
    """Common investor-relations URL guesses for a company website.

    Tries path-based guesses on the given host first (``/investors``, ``/investor-relations``,
    ``/investor``, ``/ir``), then subdomain guesses (``ir.<domain>``, ``investors.<domain>``).
    ``website`` may omit its scheme; a leading ``www.`` is stripped only for the subdomain
    guesses, since ``ir.www.example.com`` is not a real pattern.
    """
    host = _normalize_host(website)
    domain = host[4:] if host.startswith("www.") else host
    urls = [f"https://{host}{path}" for path in IR_PATHS]
    urls += [f"https://{sub}.{domain}" for sub in IR_SUBDOMAINS]
    return urls


def _parse_robots_groups(robots_txt: str) -> list[tuple[list[str], list[tuple[str, str]]]]:
    """Parse robots.txt into ``(agents, rules)`` groups; rules are ``(directive, path)``
    pairs with ``directive`` one of ``"allow"``/``"disallow"``. Unknown directives (e.g.
    ``Crawl-delay``, ``Sitemap``) are ignored."""
    groups: list[tuple[list[str], list[tuple[str, str]]]] = []
    agents: list[str] = []
    rules: list[tuple[str, str]] = []
    has_rule = False

    def flush() -> None:
        if agents:
            groups.append((list(agents), list(rules)))
        agents.clear()
        rules.clear()

    for raw_line in robots_txt.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field = field.strip().lower()
        value = value.strip()
        if field == "user-agent":
            if has_rule:
                flush()
                has_rule = False
            agents.append(value.lower())
        elif field in ("allow", "disallow"):
            rules.append((field, value))
            has_rule = True
    flush()
    return groups


def robots_allows(robots_txt: str, path: str, agent: str = "*") -> bool:
    """Minimal robots.txt check (longest matching rule wins; ties favor Allow).

    Looks for a group whose ``User-agent`` list names ``agent`` (case-insensitive); falls
    back to the ``*`` group. No robots.txt, no matching group or no matching rule all mean
    "allowed" -- a crawler should not treat the absence of a rule as a disallow.
    """
    groups = _parse_robots_groups(robots_txt)
    agent_lc = agent.lower()
    chosen: list[tuple[str, str]] | None = None
    for agents, rules in groups:
        if agent_lc in agents:
            chosen = rules
            break
    if chosen is None:
        for agents, rules in groups:
            if "*" in agents:
                chosen = rules
                break
    if not chosen:
        return True

    request_path = path if path.startswith("/") else f"/{path}"
    best_len = -1
    best_directive = "allow"
    for directive, rule_path in chosen:
        if not rule_path:
            continue  # an empty value ("Disallow:") restricts nothing
        if request_path.startswith(rule_path):
            more_specific = len(rule_path) > best_len
            tie_prefers_allow = len(rule_path) == best_len and directive == "allow"
            if more_specific or tie_prefers_allow:
                best_len = len(rule_path)
                best_directive = directive
    if best_len == -1:
        return True
    return best_directive == "allow"


def _classify_kind(text: str, href: str) -> str:
    haystack = f"{text} {href}".lower()
    for kind, keywords in _KIND_RULES:
        if any(keyword in haystack for keyword in keywords):
            return kind
    return "other"


def _extract_date(text: str) -> str | None:
    """Best-effort date string from link text -- 'Month Day, Year' / 'Day Month Year' when
    stated, else a bare year (2024-2030), else ``None``. Deliberately not a full date
    parser: good enough to label an IR document without inventing a date it never gave."""
    match = _DATE_WITH_MONTH_RE.search(text)
    if match:
        return " ".join(match.group(0).split())
    match = _YEAR_ONLY_RE.search(text)
    if match:
        return match.group(0)
    return None


class _AnchorParser(HTMLParser):
    """Collects (href, visible text) for every ``<a href=...>`` in an HTML document."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text_parts: list[str] = []
        self._in_anchor = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = next((v for k, v in attrs if k == "href" and v), None)
        if href:
            self._in_anchor = True
            self._href = href
            self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._in_anchor:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_anchor:
            text = " ".join(" ".join(self._text_parts).split())
            if self._href is not None:
                self.anchors.append((self._href, text))
            self._in_anchor = False
            self._href = None
            self._text_parts = []


def extract_ir_links(html: str, base_url: str) -> list[dict]:
    """Extract IR document links from an HTML page.

    Each item is ``{"title", "url", "kind", "date"}``: ``url`` is resolved against
    ``base_url``, ``kind`` is one of the categories in ``_KIND_RULES`` or ``"other"``, and
    ``date`` is parsed from the link text or ``None``. ``javascript:``, ``mailto:`` and
    same-page ``#`` links are skipped; duplicate resolved URLs are kept once.
    """
    parser = _AnchorParser()
    parser.feed(html)
    results: list[dict] = []
    seen: set[str] = set()
    for href, text in parser.anchors:
        if href.startswith(("javascript:", "mailto:", "#")):
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        results.append(
            {
                "title": text or href,
                "url": url,
                "kind": _classify_kind(text, href),
                "date": _extract_date(text),
            }
        )
    return results


class IRProvider:
    """Finds a company's investor-relations page and classifies the documents linked from it.

    Public pages only: no JS execution, no login, no paywall bypass. Respects robots.txt,
    never issues more than ``MAX_REQUESTS`` HTTP calls (robots.txt fetches included) for a
    single lookup, and always identifies itself with ``DEFAULT_USER_AGENT``.
    """

    source_name = "company_ir"
    tier = "A"

    def __init__(self, timeout: float = 10.0, ttl_seconds: float = 6 * 3600) -> None:
        self.timeout = timeout
        self._cache = TTLCache(ttl_seconds)

    def _get(self, url: str) -> httpx.Response:
        return httpx.get(
            url,
            timeout=self.timeout,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            follow_redirects=True,
        )

    def _fetch_robots(self, host: str) -> str | None:
        try:
            response = self._get(f"https://{host}/robots.txt")
        except httpx.HTTPError:
            return None
        return response.text if response.status_code == 200 else None

    def investor_relations(self, website: str) -> dict:
        """Find and summarize a company's investor-relations page.

        Tries the patterns from :func:`candidate_ir_urls` in order, skipping any candidate
        robots.txt disallows, and stops at the first one that returns HTTP 200. Never
        fabricates a result: if every candidate is disallowed, unreachable or non-200, the
        returned dict still has the full shape with ``ok: False`` and a reason.
        """
        cached = self._cache.get(website)
        if cached is not None:
            return cached

        base = {
            "website": website,
            "source": self.source_name,
            "tier": self.tier,
            "as_of": datetime.now(UTC).isoformat(),
        }

        def not_found(error: str, skipped: dict[str, str] | None = None) -> dict:
            result = {
                **base,
                "ok": False,
                "ir_url": None,
                "links": [],
                "confidence": 0.0,
                "missing": list(_ALL_KINDS),
                "error": error,
                **({"skipped": skipped} if skipped is not None else {}),
            }
            self._cache.set(website, result)
            return result

        try:
            candidates = candidate_ir_urls(website)
        except ValueError as exc:
            return not_found(str(exc))

        requests_used = 0
        skipped: dict[str, str] = {}
        robots_by_host: dict[str, str | None] = {}

        for url in candidates:
            parsed = urlparse(url)
            host = parsed.netloc
            if host not in robots_by_host:
                if requests_used >= MAX_REQUESTS:
                    skipped[url] = "request budget exhausted"
                    continue
                requests_used += 1
                robots_by_host[host] = self._fetch_robots(host)
            robots_txt = robots_by_host[host]
            path = parsed.path or "/"
            if robots_txt is not None and not robots_allows(robots_txt, path):
                skipped[url] = "disallowed by robots.txt"
                continue
            if requests_used >= MAX_REQUESTS:
                skipped[url] = "request budget exhausted"
                continue
            requests_used += 1
            try:
                response = self._get(url)
            except httpx.HTTPError as exc:
                skipped[url] = f"{type(exc).__name__}: {exc}"
                continue
            if response.status_code != 200:
                skipped[url] = f"HTTP {response.status_code}"
                continue

            links = extract_ir_links(response.text, url)[:25]
            # Confidence must reflect actual resolved documents, not just how many
            # keyword categories appear in link text/href -- a nav menu with zero dated
            # documents ("Annual Reports" linking to a landing page) is not the same
            # evidence as a page listing real, dated filings, even though both can match
            # the same three keyword categories.
            dated_kinds_found = {
                link["kind"] for link in links if link["kind"] != "other" and link["date"]
            }
            result = {
                **base,
                "ok": True,
                "ir_url": url,
                "links": links,
                "confidence": 0.8 if len(dated_kinds_found) >= 3 else 0.4,
                "missing": [kind for kind in _ALL_KINDS if kind not in dated_kinds_found],
                "skipped": skipped,
            }
            self._cache.set(website, result)
            return result

        return not_found("no investor-relations page found among candidate URLs", skipped)
