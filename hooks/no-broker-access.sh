#!/usr/bin/env bash
# PreToolUse guard for portfolio-copilot (broker-agnostic).
# Denies tool calls that touch an authentication / private-area surface or carry credentials.
# The only allowed portfolio input is a LOCAL XLSX/CSV export path. Deterministic, no network.
set -u
INPUT="$(cat)"

# The python script is fixed-size and lives in its own temp file rather than being passed
# via heredoc-into-argv: tool_input itself is fed to python over a pipe (stdin) below, never
# as a CLI argument, so an arbitrarily large payload (e.g. a big local CSV/XLSX-derived
# Write) cannot hit the OS ARG_MAX ceiling and crash the guard with "Argument list too long".
SCRIPT="$(mktemp)"
trap 'rm -f "$SCRIPT"' EXIT
cat > "$SCRIPT" <<'PY'
import json, re, sys

raw = sys.stdin.read()
try:
    payload = json.loads(raw) if raw.strip() else {}
except json.JSONDecodeError:
    sys.exit(0)  # malformed input: do not block, do not guess

tool = payload.get("tool_name", "") or "tool"
tool_input = payload.get("tool_input", {}) or {}
blob = json.dumps(tool_input, ensure_ascii=False).lower()
# json.dumps renders a real newline/carriage-return/tab byte inside a string value as the
# two literal characters "\" + "n"/"r"/"t". The trailing letter is a word character, so it
# fuses with a keyword that starts a non-first line (e.g. "...foo\npassword: ...") and
# defeats the \b word-boundary anchors below. Collapse those escapes back to whitespace
# before matching so a boundary exists wherever the original text had a line break.
blob = re.sub(r"\\[nrt]", " ", blob)

# 1) URLs whose path/query is an authentication or private-area surface. Generic keywords
# are wrapped in \b so they only match whole path/query segments, not a bare substring of
# an unrelated word ("authors", "tokenomics", "sessionStorage", "possession", ...).
AUTH_URL = re.compile(
    r"https?://[^\s\"'<>]*?"
    r"(?:\b(?:login|logon|signin|sign-in|accedi|signon|auth|oauth|otp|token|session|"
    r"area-?(?:privata|clienti|riservata)|private|mybank|home-?banking|trading/order)\b"
    r"|/orders?\b|/portal\b)"
)
# 2) Explicit credential material in the tool input (any tool, any host). The keyword plus
# separator alone is not enough: documentation prose that merely names a credential-shaped
# field to tell a contributor where to source the real value from carries no actual secret.
# Only treat it as a hit when the text right after the separator looks like an opaque secret
# token, not a sentence that opens with an instructional/placeholder word.
CREDENTIAL_KEY = re.compile(
    r"\b(password|passwd|otp|pin|codice\s*(titolare|utente|segreto)|secure\s*code|2fa|mfa)\b"
    r"\s*[:=]\s*"
)
_VALUE_TOKEN = re.compile(r"[^\s\"']+")
_PROSE_STARTERS = {
    "source", "use", "your", "the", "a", "an", "this", "that", "see", "replace",
    "insert", "example", "placeholder", "provide", "enter", "set", "store", "never",
    "generate", "retrieve", "pull", "look", "fill", "add", "put", "<",
}


def _credentials_hit(text):
    for m in CREDENTIAL_KEY.finditer(text):
        value_match = _VALUE_TOKEN.match(text, m.end())
        first_word = value_match.group(0) if value_match else ""
        first_word = first_word.strip("<>.,;:'\"")
        if first_word in _PROSE_STARTERS or first_word.startswith("<"):
            continue
        return m
    return None


# 3) Network clients carrying auth headers/cookies/basic auth.
NET_AUTH = re.compile(
    r"\b(curl|wget|httpx|http)\b[^\n]*?(--?u(ser)?\b|--cookie|-b\s|authorization:|bearer\s)"
)
# 4) Plaintext credentials embedded in a URL's authority component (user:pass@host).
USERINFO_URL = re.compile(r"https?://[^/\s\"'<>@]+:[^/\s\"'<>@]+@")

hit = (
    AUTH_URL.search(blob)
    or _credentials_hit(blob)
    or NET_AUTH.search(blob)
    or USERINFO_URL.search(blob)
)
if hit is None:
    sys.exit(0)

reason = (
    "portfolio-copilot: no broker access. "
    f"The {tool} call touches an authentication/credential surface ('{hit.group(0)[:80]}'). "
    "This plugin never logs into a broker or bank, never reads a private area, never asks for "
    "credentials/OTP/PIN and never sends orders: the only allowed input is a local XLSX/CSV export."
)
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }
}, ensure_ascii=False))
sys.exit(0)
PY
printf '%s' "$INPUT" | python3 "$SCRIPT"
