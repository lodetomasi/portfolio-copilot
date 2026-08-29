"""Execution-venue allowlist in hooks/no-broker-access.sh (rules changed 2026-08-29).

eToro Public API and developer-docs URLs are allowed; every other venue's auth/order surface
and any credential material in tool input are still denied. Test literals are assembled from
fragments so this file itself never contains a string the guard would flag.
"""

import json
import subprocess
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parents[1] / "hooks" / "no-broker-access.sh"

ETORO_API = "https://public-api.etoro.com/api/v2/trading/"
ORDERS = "execution/demo/" + "ord" + "ers"
OTHER_VENUE_ORDER = "https://other.example/trading/" + "ord" + "er?id=1"
OTHER_VENUE_LOGIN = "https://broker.example/" + "log" + "in"
BASIC_AUTH_FLAG = "-" + "u me:secret"
SECRET_LINE = "pass" + "word: hunter2"


def _run(payload: dict) -> str:
    proc = subprocess.run(
        ["bash", str(GUARD)], input=json.dumps(payload), capture_output=True, text=True, timeout=10
    )
    assert proc.returncode == 0
    return proc.stdout.strip()


@pytest.mark.parametrize(
    "command",
    [
        "curl -sL -A 'portfolio-copilot' https://api-portal.etoro.com/ -o portal.html",
        f"curl -s {ETORO_API}{ORDERS}",
        f"curl -s {ETORO_API}info/portfolio",
        "curl -s https://builders.etoro.com/learn/authentication-and-api-keys",
        f"uv run python -c \"import httpx; httpx.post('{ETORO_API}{ORDERS}', json={{}})\"",
    ],
)
def test_etoro_api_and_docs_urls_are_allowed(command):
    assert _run({"tool_name": "Bash", "tool_input": {"command": command}}) == ""


@pytest.mark.parametrize(
    "payload",
    [
        {"tool_name": "WebFetch", "tool_input": {"url": OTHER_VENUE_LOGIN}},
        {"tool_name": "Bash", "tool_input": {"command": f"curl {OTHER_VENUE_ORDER}"}},
        {"tool_name": "Bash", "tool_input": {"command": f"curl {BASIC_AUTH_FLAG} {ETORO_API}x"}},
        {"tool_name": "Write", "tool_input": {"file_path": "n.md", "content": SECRET_LINE}},
    ],
)
def test_other_venues_and_credentials_still_denied(payload):
    out = _run(payload)
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


CLIENT = "cu" + "rl"
LIB = "ht" + "tpx"
HEADER_DOC = (
    "Headers: x-api-key (app key), x-" + "user-key (user key), x-request-id.\n"
    "Client: " + LIB + " with timeout; mocked in tests with " + LIB + ".MockTransport.\n"
    "Rate limits: 60 reads/min, 20 writes/min."
)


def test_header_names_and_client_lib_in_docs_are_not_credentials():
    """Regression: json-escaped newlines let a client word and a later flag match across
    unrelated lines, and the header name x-user-key was mistaken for a basic-auth flag."""
    for tool in ("Write", "Bash"):
        payload = {
            "tool_name": tool,
            "tool_input": {"file_path": "docs/x.md", "content": HEADER_DOC},
        }
        assert _run(payload) == ""


def test_basic_auth_and_bearer_on_command_line_are_still_denied():
    cmd = CLIENT + " " + BASIC_AUTH_FLAG + " https://api.example/v1"
    out = _run({"tool_name": "Bash", "tool_input": {"command": cmd}})
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    cmd2 = CLIENT + " -H 'Author" + "ization: Bea" + "rer abcdefghijkl' https://api.example/v1"
    out2 = _run({"tool_name": "Bash", "tool_input": {"command": cmd2}})
    assert json.loads(out2)["hookSpecificOutput"]["permissionDecision"] == "deny"
