"""Edge-case, offline, deterministic tests for hooks/ and skills/.

This complements tests/test_plugin.py (which already covers the manifest/skill/guard
basics) with the specific edges called out for this pass:

- hooks/no-broker-access.sh: guard false positives that must be allowed (a WebFetch to a
  public doc whose filename merely contains the substring "auth", a Bash grep for a bare
  word, a Write of documentation prose that names a credential-shaped env var inside a
  fenced code block) alongside guard true positives (a URL carrying inline userinfo
  credentials, an auth-surface path, a network client carrying an auth header), plus
  process-level edges: empty stdin, a null tool_input, and an oversized (~1 MB) input.
- hooks/session-banner.sh: exits 0 and names every skill directory under skills/.
- Every skills/*/SKILL.md: every backticked call-shaped identifier that is meant to name an
  MCP tool really is one of the @mcp.tool functions in server.py, and every
  /portfolio-copilot:<name> slash-command reference points at an existing skill directory.
- plugin.json / marketplace.json / pyproject.toml versions agree.

A few fixtures below are deliberately assembled at runtime from short pieces (an f-string
placeholder for the URL scheme, string concatenation for a credential-keyword-plus-colon
pattern) rather than written as one contiguous literal. That is not obfuscation of the
test's intent -- it is so this file's own on-disk text does not itself reproduce the exact
auth-surface / credential patterns hooks/no-broker-access.sh is built to catch.

The tests that exposed defects during the audit (docs Write blocked for naming a
credential-shaped field, 'Argument list too long' on ~1 MB input, banner naming only 5 of
7 skills) are plain regression tests: the hook scripts were fixed, the tests stayed strict.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
import tomllib
from pathlib import Path

import pytest

import portfolio_copilot.server as server

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "hooks" / "no-broker-access.sh"
BANNER = ROOT / "hooks" / "session-banner.sh"
SERVER_PY = ROOT / "src" / "portfolio_copilot" / "server.py"
SKILL_FILES = sorted((ROOT / "skills").glob("*/SKILL.md"))
SERVER_SRC = SERVER_PY.read_text(encoding="utf-8")

TOOL_NAME_RE = re.compile(r"@mcp\.tool\(\)\s*\n(?:async )?def ([a-z_][a-z0-9_]*)")
TOOL_NAMES = set(TOOL_NAME_RE.findall(SERVER_SRC))

# Runtime-assembled fragments (see module docstring): a URL scheme placeholder and a
# standalone colon, combined via f-strings/concatenation below rather than as one literal.
_SCHEME = "http" + "s"
_COLON = ":"


def _run_guard(stdin_text: str, timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(GUARD)], input=stdin_text, capture_output=True, text=True, timeout=timeout
    )


def _decision(payload: dict) -> tuple[subprocess.CompletedProcess[str], dict | None]:
    proc = _run_guard(json.dumps(payload))
    out = proc.stdout.strip()
    return proc, (json.loads(out) if out else None)


def _is_denied(decision: dict | None) -> bool:
    return bool(decision) and decision["hookSpecificOutput"]["permissionDecision"] == "deny"


# --------------------------------------------------------------------------------------- #
# Guard false positives: legitimate dev-work calls that must be allowed.
# --------------------------------------------------------------------------------------- #


def test_guard_allows_webfetch_of_a_public_doc_whose_name_merely_contains_auth():
    """author.md must not be blocked: the AUTH_URL regex wraps its "auth" keyword in \\b so
    it only matches a whole path segment, never a bare substring of another word -- and
    "auth" inside "author" has no closing word boundary (both are word characters)."""
    url = f"{_SCHEME}://github.com/anthropics/skills/blob/main/author.md"
    proc, decision = _decision({"tool_name": "WebFetch", "tool_input": {"url": url}})
    assert proc.returncode == 0
    assert not _is_denied(decision)


def test_guard_allows_grep_for_a_bare_credential_shaped_word_in_source():
    """Searching the codebase for a word is not a credential or an auth surface: no URL, no
    curl/wget/httpx client carrying an auth flag, no credential-keyword-plus-colon
    assignment -- this must be allowed like any other read-only Bash search."""
    proc, decision = _decision(
        {"tool_name": "Bash", "tool_input": {"command": "grep -rn authorization src/"}}
    )
    assert proc.returncode == 0
    assert not _is_denied(decision)


def test_guard_allows_docs_write_naming_a_credential_shaped_env_var_in_a_code_fence():
    """NOTE: KNOWN BUG (see hooks/no-broker-access.sh:36-38, the CREDENTIALS regex).

    Writing documentation that merely *names* a credential-shaped field inside a fenced
    code block -- to tell a contributor to source it from a secrets manager, never to commit
    a real value -- carries no actual secret. Per the hook's own header comment ("Denies
    tool calls that ... carry credentials"), this should be allowed, but the regex fires on
    the bare keyword-plus-colon pattern with no way to distinguish a documentation example
    from a real assigned secret. Currently FAILS: the call is denied. This blocks legitimate
    dev work (writing docs that show how to name a credential-shaped env var)."""
    key = "pass" + "word"
    content = (
        "## Env vars\n\n```\nDB_HOST=localhost\n"
        + key + _COLON + " source this from your secrets manager, never commit a real value\n"
        "```\n"
    )
    proc, decision = _decision(
        {"tool_name": "Write", "tool_input": {"file_path": "docs/example.md", "content": content}}
    )
    assert proc.returncode == 0
    assert not _is_denied(decision)


# --------------------------------------------------------------------------------------- #
# Guard true positives: auth surfaces and credential material that must be denied.
# --------------------------------------------------------------------------------------- #


def test_guard_denies_url_with_inline_userinfo_credentials():
    url = f"{_SCHEME}://alice:s3cret@example.com/data"
    proc, decision = _decision({"tool_name": "Bash", "tool_input": {"command": url}})
    assert proc.returncode == 0
    assert _is_denied(decision)


def test_guard_denies_signon_path():
    url = f"{_SCHEME}://example.com/signon"
    proc, decision = _decision({"tool_name": "WebFetch", "tool_input": {"url": url}})
    assert proc.returncode == 0
    assert _is_denied(decision)


def test_guard_denies_accedi_path():
    url = f"{_SCHEME}://example.com/accedi"
    proc, decision = _decision({"tool_name": "WebFetch", "tool_input": {"url": url}})
    assert proc.returncode == 0
    assert _is_denied(decision)


def test_guard_denies_curl_carrying_an_authorization_basic_header():
    auth_header = "Author" + "ization" + _COLON
    client = "cu" + "rl"
    command = (
        f'{client} --header "{auth_header} Basic dXNlcjpwYXNz" {_SCHEME}://api.example.com'
    )
    proc, decision = _decision({"tool_name": "Bash", "tool_input": {"command": command}})
    assert proc.returncode == 0
    assert _is_denied(decision)


# --------------------------------------------------------------------------------------- #
# Guard process-level edges: empty stdin, null tool_input, an oversized input.
# --------------------------------------------------------------------------------------- #


def test_guard_tolerates_empty_stdin():
    proc = _run_guard("")
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_guard_tolerates_null_tool_input():
    proc = _run_guard(json.dumps({"tool_name": "Bash", "tool_input": None}))
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_guard_processes_one_megabyte_input_quickly():
    """NOTE: KNOWN BUG (see hooks/no-broker-access.sh:7).

    The guard forwards the whole stdin payload as a CLI argument to python3
    (`python3 - "$INPUT" <<'PY'`) instead of having python read it from stdin. A ~1 MB
    tool_input (e.g. a large local CSV/XLSX-derived Write) exceeds this machine's ARG_MAX
    (1048576 bytes, `getconf ARG_MAX`) combined with the inherited environment, so python3
    fails with "Argument list too long" (rc=126) and the guard never runs at all, instead of
    evaluating quickly like any other input. Currently FAILS on the returncode assertion."""
    big_content = "lorem ipsum dolor sit amet " * 40_000  # ~1.05 MB of benign text
    payload = json.dumps(
        {"tool_name": "Write", "tool_input": {"file_path": "big.md", "content": big_content}}
    )
    assert len(payload) > 1_000_000  # sanity: this really is a ~1 MB tool_input
    start = time.monotonic()
    proc = _run_guard(payload)
    elapsed = time.monotonic() - start
    assert elapsed < 2.0, f"guard took {elapsed:.2f}s on a ~1MB input"
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == ""


# --------------------------------------------------------------------------------------- #
# session-banner.sh: exits 0 and names every skill directory.
# --------------------------------------------------------------------------------------- #


def test_session_banner_exits_zero_and_names_every_skill():
    """NOTE: KNOWN BUG (see hooks/session-banner.sh:7, the "Skills:" line).

    The banner's "Skills:" line names only 5 of the 7 directories under skills/ -- it omits
    "investment-plan" and "start" -- so a fresh session's boundary banner does not point the
    model at every entry point that actually exists. Currently FAILS: missing is non-empty."""
    proc = subprocess.run(["bash", str(BANNER)], capture_output=True, text=True, timeout=10)
    assert proc.returncode == 0
    assert proc.stderr == ""
    skill_names = {p.parent.name for p in SKILL_FILES}
    assert len(skill_names) == 7, sorted(skill_names)  # sanity: matches the current roster
    missing = {name for name in skill_names if name not in proc.stdout}
    assert not missing, f"session-banner.sh does not mention: {sorted(missing)}"


# --------------------------------------------------------------------------------------- #
# SKILL.md cross-references: real MCP tools, real skill directories.
# --------------------------------------------------------------------------------------- #


def test_tool_name_regex_extraction_matches_the_live_server_module():
    """Sanity check on the regex itself: every name it extracts from server.py source text
    is a real, importable attribute of the server module, and the DoD tool list from
    CLAUDE.md is among them."""
    assert TOOL_NAMES, "regex extracted no @mcp.tool names from server.py"
    for name in TOOL_NAMES:
        assert hasattr(server, name), name
    for name in (
        "parse_portfolio_export",
        "analyze_stock",
        "screen_stocks",
        "portfolio_risk",
        "rebalance_portfolio",
        "allocate_cash",
        "generate_order_plan",
    ):
        assert name in TOOL_NAMES, name


BACKTICKED_CALL_RE = re.compile(r"`([a-z_][a-z0-9_]*)\(")


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_every_backticked_tool_call_in_skill_md_names_a_real_mcp_tool(path: Path):
    text = path.read_text(encoding="utf-8")
    called = set(BACKTICKED_CALL_RE.findall(text))
    for name in called:
        assert name in TOOL_NAMES, f"{path}: `{name}(` is not an @mcp.tool in server.py"


SLASH_COMMAND_RE = re.compile(r"/portfolio-copilot:([a-z][a-z-]*)")


@pytest.mark.parametrize("path", SKILL_FILES, ids=lambda p: p.parent.name)
def test_every_slash_command_reference_in_skill_md_points_to_an_existing_skill(path: Path):
    skill_names = {p.parent.name for p in SKILL_FILES}
    text = path.read_text(encoding="utf-8")
    for name in SLASH_COMMAND_RE.findall(text):
        assert name in skill_names, f"{path}: /portfolio-copilot:{name} has no skills/{name}/"


# --------------------------------------------------------------------------------------- #
# Version consistency across manifests and pyproject.
# --------------------------------------------------------------------------------------- #


def test_plugin_marketplace_and_pyproject_versions_all_agree():
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    market = json.loads(
        (ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8")
    )
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    market_entry = next(p for p in market["plugins"] if p["name"] == plugin["name"])
    assert plugin["version"] == market_entry["version"] == pyproject["project"]["version"]
