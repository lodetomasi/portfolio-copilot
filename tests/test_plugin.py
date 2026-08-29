"""Offline checks for the Claude Code plugin packaging (manifests, skills, hooks)."""

from __future__ import annotations

import inspect
import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

import portfolio_copilot.server as server

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_JSON = ROOT / ".claude-plugin" / "plugin.json"
MARKETPLACE_JSON = ROOT / ".claude-plugin" / "marketplace.json"
HOOKS_JSON = ROOT / "hooks" / "hooks.json"
GUARD = ROOT / "hooks" / "no-broker-access.sh"
SKILLS = sorted(p for p in (ROOT / "skills").glob("*/SKILL.md"))

EXPECTED_SKILLS = {
    "start",
    "investment-plan",
    "portfolio-review",
    "deploy-cash",
    "rebalance",
    "stock-picker",
    "position-review",
}


def _frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"^---\n(.*?)\n---\n", text, flags=re.S)
    assert m, "SKILL.md must start with YAML frontmatter"
    out: dict[str, str] = {}
    key = None
    for line in m.group(1).splitlines():
        if line.startswith(" ") and key:
            out[key] += " " + line.strip()
        elif ":" in line:
            key, _, value = line.partition(":")
            out[key.strip()] = value.strip().lstrip(">").strip()
    return out


def test_plugin_and_marketplace_manifests_agree():
    plugin = json.loads(PLUGIN_JSON.read_text(encoding="utf-8"))
    market = json.loads(MARKETPLACE_JSON.read_text(encoding="utf-8"))
    assert plugin["name"] == "portfolio-copilot"
    entry = next(p for p in market["plugins"] if p["name"] == plugin["name"])
    assert entry["version"] == plugin["version"]
    assert entry["source"] == "./"
    # The boundary must be stated in the manifest itself.
    assert "no order execution" in plugin["description"].lower()


def test_every_expected_skill_exists_with_description():
    names = {p.parent.name for p in SKILLS}
    assert names == EXPECTED_SKILLS
    for path in SKILLS:
        fm = _frontmatter(path.read_text(encoding="utf-8"))
        assert fm.get("name") == path.parent.name
        assert len(fm.get("description", "")) > 40
        assert "argument-hint" in fm


def test_every_skill_states_no_broker_access_and_stays_short():
    for path in SKILLS:
        text = path.read_text(encoding="utf-8")
        body = text.lower()
        assert "no broker access" in body, path
        assert "manual" in body, path
        assert "≤ 6 lines" in text, path  # rookie-out: short answers by contract
        assert len(text.splitlines()) < 120, path


def test_hooks_json_wires_guard_and_banner():
    hooks = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
    pre = hooks["PreToolUse"][0]
    assert "Bash" in pre["matcher"] and "WebFetch" in pre["matcher"]
    assert "no-broker-access.sh" in pre["hooks"][0]["command"]
    assert "${CLAUDE_PLUGIN_ROOT}" in pre["hooks"][0]["command"]
    assert "session-banner.sh" in hooks["SessionStart"][0]["hooks"][0]["command"]


def _run_guard(payload: dict) -> tuple[int, str]:
    proc = subprocess.run(
        ["bash", str(GUARD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
    )
    return proc.returncode, proc.stdout.strip()


@pytest.mark.parametrize(
    "payload",
    [
        {"tool_name": "WebFetch", "tool_input": {"url": "https://broker.example/login"}},
        {"tool_name": "WebFetch", "tool_input": {"url": "https://bank.example/area-privata/home"}},
        {
            "tool_name": "Bash",
            "tool_input": {"command": "curl -u me:secret https://api.broker.example/v1"},
        },
        {
            "tool_name": "Bash",
            "tool_input": {"command": "curl https://x.example -H 'Authorization: Bearer abc'"},
        },
        {"tool_name": "Bash", "tool_input": {"command": "wget https://broker.example/trading/order?id=1"}},
        {"tool_name": "Write", "tool_input": {"file_path": "n.md", "content": "password: hunter2"}},
        {"tool_name": "Bash", "tool_input": {"command": "echo 'OTP=123456' > creds"}},
    ],
)
def test_guard_denies_auth_surfaces_and_credentials(payload):
    code, out = _run_guard(payload)
    assert code == 0
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "no broker access" in decision["permissionDecisionReason"]


@pytest.mark.parametrize(
    "payload",
    [
        {"tool_name": "Read", "tool_input": {"file_path": "~/Downloads/portfolio-export.xlsx"}},
        {"tool_name": "Bash", "tool_input": {"command": "uv run pytest"}},
        {"tool_name": "WebFetch", "tool_input": {"url": "https://finance.yahoo.com/quote/MU"}},
        {"tool_name": "Bash", "tool_input": {"command": "cat portafoglio.csv"}},
        {
            "tool_name": "Bash",
            "tool_input": {"command": "curl -s https://query1.finance.yahoo.com/v8/chart/VWCE.MI"},
        },
        {
            "tool_name": "Write",
            "tool_input": {"file_path": "docs/x.md", "content": "The login flow is out of scope."},
        },
    ],
)
def test_guard_allows_local_exports_and_public_data(payload):
    code, out = _run_guard(payload)
    assert code == 0
    assert out == ""


def test_guard_tolerates_malformed_input():
    proc = subprocess.run(["bash", str(GUARD)], input="not json", capture_output=True, text=True)
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""


@pytest.mark.parametrize(
    "payload",
    [
        # Credential keyword at column 0 of a non-first line: a real newline in the source
        # string renders as the two characters backslash+n in json.dumps output, and that
        # trailing "n" used to fuse with the keyword, defeating the \b boundary.
        {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "config/secrets.yaml",
                "content": "user: foo\npassword: hunter2\n",
            },
        },
        {
            "tool_name": "Bash",
            "tool_input": {
                "command": "set -e\ncurl -H 'Authorization: Bearer sekret' https://example.invalid/api\n"
            },
        },
    ],
)
def test_guard_denies_credentials_starting_a_non_first_line(payload):
    code, out = _run_guard(payload)
    assert code == 0
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"


@pytest.mark.parametrize(
    "url",
    [
        # Split so this file's own content doesn't reproduce the AUTH_URL false positive
        # it exercises (bare "auth"/"token"/"session" substring with no word boundary).
        "https://api.example.com/v2/" + "authors/12345",
        "https://docs.example.org/whitepaper/" + "tokenomics.pdf",
        "https://developer.mozilla.org/en-US/docs/Web/API/Window/" + "sessionStorage",
    ],
)
def test_guard_allows_urls_with_keyword_as_bare_substring(url):
    code, out = _run_guard({"tool_name": "WebFetch", "tool_input": {"url": url}})
    assert code == 0
    assert out == ""


def test_guard_denies_url_with_userinfo_credentials():
    payload = {
        "tool_name": "WebFetch",
        "tool_input": {"url": "https://john.doe:S3cr3tPass@mybroker.example.com/api/positions"},
    }
    code, out = _run_guard(payload)
    assert code == 0
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"


@pytest.mark.parametrize(
    "url",
    [
        "https://mybroker.example.com/accedi",
        "https://mybroker.example.com/signon",
        "https://mybroker.example.com/portal/dashboard",
    ],
)
def test_guard_denies_additional_login_surface_paths(url):
    code, out = _run_guard({"tool_name": "WebFetch", "tool_input": {"url": url}})
    assert code == 0
    decision = json.loads(out)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"


def test_session_start_matcher_covers_fork_source():
    hooks = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
    matcher = hooks["SessionStart"][0]["matcher"]
    assert re.fullmatch(matcher, "fork"), matcher


CONFIG_SOURCING_SKILLS = [
    ROOT / "skills" / "rebalance" / "SKILL.md",
    ROOT / "skills" / "deploy-cash" / "SKILL.md",
    ROOT / "skills" / "portfolio-review" / "SKILL.md",
    ROOT / "skills" / "investment-plan" / "SKILL.md",
]


def test_config_sourcing_skills_use_the_config_tool_not_the_raw_file():
    """targets/fees/risk_limits/rebalancing rules must come from the get_portfolio_config
    MCP tool, never from Claude opening config/portfolio.yaml itself and hand-extracting
    numbers -- these same skills promise "every number comes from an MCP tool, never from
    memory or mental math"."""
    for path in CONFIG_SOURCING_SKILLS:
        text = path.read_text(encoding="utf-8")
        assert "get_portfolio_config" in text, path
        assert "config/portfolio.yaml" not in text, path


def test_category_cap_skills_source_every_cap_from_config():
    """quality/growth/high-risk caps must all be real get_portfolio_config().risk_limits
    keys. Before this fix, quality and high-risk had matching config keys but "growth <= 4%"
    was invented prose with no config or code backing it."""
    for name in ("stock-picker", "position-review"):
        text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert "get_portfolio_config" in text, name
        assert "max_growth_stock_weight" in text, name


BUY_EMITTING_SKILLS = ["stock-picker", "deploy-cash"]


def test_buy_emitting_skills_invoke_red_team_before_buy_small():
    """README.md ("Ogni BUY passa prima dal red team") and docs/ARCHITECTURE.md ("Red team
    ... invoked by skills before any BUY") both promise the read-only red-team agent runs
    before any BUY. stock-picker and deploy-cash are the only skills whose 'Do' steps can
    produce a BUY_SMALL verdict, so both must actually invoke it -- not just score and
    portfolio-risk-check -- before a candidate is allowed to reach BUY_SMALL."""
    for name in BUY_EMITTING_SKILLS:
        text = (ROOT / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        assert "BUY_SMALL" in text, name
        do_section, sep, _answer_section = text.partition("## Answer")
        assert sep, name  # sanity: skill has an Answer section to gate before
        # the gate must live among the 'Do' steps -- run before the answer is presented --
        # not be mentioned only in passing after the answer template.
        assert "red-team" in do_section, name


PROVIDERS_DIR = ROOT / "src" / "portfolio_copilot" / "providers"


def test_architecture_doc_does_not_overclaim_provider_timeouts():
    """docs/ARCHITECTURE.md claims a blanket 'every call with timeout' for providers/, but
    yfinance_provider.py and finviz.py -- unlike ecb_fx.py/sec_edgar.py/stooq.py, which each
    declare an explicit `timeout` constructor parameter -- have no `timeout=` anywhere and
    rely entirely on their underlying libraries' own defaults. CLAUDE.md already documents
    the yfinance half of this gap; both docs must name every exception instead of
    contradicting the code (or each other)."""
    for name in ("ecb_fx.py", "sec_edgar.py", "stooq.py"):
        src = (PROVIDERS_DIR / name).read_text(encoding="utf-8")
        assert "timeout: float" in src, name  # sanity: these really do take an explicit timeout

    for name in ("yfinance_provider.py", "finviz.py"):
        src = (PROVIDERS_DIR / name).read_text(encoding="utf-8")
        assert "timeout" not in src, (
            f"{name} now has an explicit timeout -- update this test and the "
            "ARCHITECTURE.md/CLAUDE.md caveats about the gap"
        )

    arch_text = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")
    providers_lines = [
        line
        for line in arch_text.splitlines()
        if line.strip().startswith("- `providers/`") or line.strip().startswith("providers/*")
    ]
    assert len(providers_lines) == 2, providers_lines  # sanity: both known claim sites found
    for line in providers_lines:
        assert "yfinance" in line.lower(), line
        assert "finviz" in line.lower(), line

    claude_text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    timeout_line = next(
        line for line in claude_text.splitlines() if "ancora senza timeout" in line.lower()
    )
    assert "finviz" in timeout_line.lower(), timeout_line
    providers_bullet = next(
        line for line in claude_text.splitlines() if line.strip().startswith("- `providers/`")
    )
    assert "sempre timeout" not in providers_bullet.lower(), providers_bullet


def test_prd_mvp_tools_list_matches_screen_stocks_signature():
    """docs/PRD.md's MVP tool list documents `screen_stocks(tickers, profile)`, but the
    shipped tool (src/portfolio_copilot/server.py) is `screen_stocks(tickers, min_score=0.0)`.
    There is no `profile` parameter anywhere -- the preset concept lives only on the separate
    `discover_stocks` tool -- so the PRD line must name the real second parameter instead."""
    params = list(inspect.signature(server.screen_stocks).parameters)
    assert params == ["tickers", "min_score"]  # sanity: documents the real signature

    prd_text = (ROOT / "docs" / "PRD.md").read_text(encoding="utf-8")
    screen_stocks_line = next(
        line for line in prd_text.splitlines() if "screen_stocks(" in line
    )
    assert "profile" not in screen_stocks_line, screen_stocks_line
    assert "min_score" in screen_stocks_line, screen_stocks_line


def test_prd_mvp_tools_list_has_no_nonexistent_compare_position_tool():
    """docs/PRD.md's MVP tool list documented `compare_position(ticker, portfolio_path)` as
    MVP tool #8, but no such tool was ever built in server.py. The equivalent job-to-be-done
    (single-position review) is implemented as the `position-review` skill, which composes
    three existing tools -- parse_portfolio_export, portfolio_risk, analyze_stock -- rather
    than a standalone MCP tool. The PRD must say that, not advertise a tool that doesn't exist."""
    assert not hasattr(server, "compare_position")  # sanity: confirms the tool was never built

    prd_text = (ROOT / "docs" / "PRD.md").read_text(encoding="utf-8")
    assert "compare_position" not in prd_text, "PRD still documents the nonexistent tool"

    mvp_section = prd_text.split("## 9. MVP tools", 1)[1].split("## 10.", 1)[0]
    position_review_line = next(
        line for line in mvp_section.splitlines() if "position-review" in line
    )
    for tool_name in ("parse_portfolio_export", "portfolio_risk", "analyze_stock"):
        assert tool_name in position_review_line, position_review_line


def test_claude_md_except_exception_convention_matches_code():
    """CLAUDE.md's coding-conventions bullet claimed the *only* two `except Exception` blocks
    in the whole src tree are the per-ticker one in `screen_stocks` and a multi-encoding
    fallback in `parsers/broker_export.py::_read_table` that "alla fine solleva ValueError".
    Neither part of that claim matches the code: `_read_table` has no except clause of any
    kind (the encoding fallback lives in the separate `_read_rows` function and catches the
    narrower `UnicodeDecodeError`, not `Exception`), and several other `except Exception`
    degrade-to-structured-result blocks were added elsewhere (analyze_stock, review_decisions,
    FinvizProvider.screen, YFinanceProvider.get_monthly_closes) beyond screen_stocks alone. The
    doc must not name a nonexistent site or claim an exhaustive count of two."""
    src_root = ROOT / "src" / "portfolio_copilot"
    actual_sites = [
        f"{path.relative_to(ROOT)}:{i}"
        for path in sorted(src_root.rglob("*.py"))
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if re.search(r"except Exception\b", line)
    ]
    # sanity: several degrade sites exist today, not just screen_stocks
    assert len(actual_sites) >= 5, actual_sites

    broker_export = (src_root / "parsers" / "broker_export.py").read_text(encoding="utf-8")
    assert "except Exception" not in broker_export  # sanity: _read_table never used it
    assert "except UnicodeDecodeError" in broker_export  # sanity: _read_rows really does

    claude_text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    conventions_line = next(
        line for line in claude_text.splitlines() if "except Exception" in line
    )
    sentences = conventions_line.split(". ")
    # must not claim an exhaustive/exact count of "the only" except-Exception sites
    assert not any(
        "i soli" in s.lower() and "except exception" in s.lower() for s in sentences
    ), conventions_line

    # the sentence naming _read_table must not claim it is an except-Exception site
    read_table_sentence = next(s for s in sentences if "_read_table" in s)
    assert "except exception" not in read_table_sentence.lower(), read_table_sentence
    assert "non ha except" in read_table_sentence.lower(), read_table_sentence

    # the real encoding-fallback site and exception type must be named correctly
    assert "_read_rows" in conventions_line, conventions_line
    assert "UnicodeDecodeError" in conventions_line, conventions_line


def test_readme_install_command_is_directory_agnostic():
    """README.md's 3-command install hardcodes `cd portfolio-copilot`, implying the cloned
    repo lives in a directory literally named `portfolio-copilot` (matching pyproject.toml's
    package name). The real checkout can be named anything -- this very repo's own directory
    still carries a pre-scrub, broker-specific name -- so a literal `cd portfolio-copilot`
    run from the parent of the clone fails with 'No such file or directory'. The install
    block must not assume a fixed directory name."""
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    install_section = text.split("## Installazione", 1)[1].split("\n## ", 1)[0]
    assert "cd portfolio-copilot" not in install_section, install_section


def test_makefile_install_target_installs_dev_dependencies():
    """CLAUDE.md's "Comandi" block documents `uv sync --extra dev` as the install step (the
    "dev" extra carries pytest, pytest-asyncio, ruff) and states plainly that `make
    install|test|lint|dev sono alias dei comandi sopra`. But the Makefile's `install` target
    runs a bare `uv sync` -- no --extra/--all-extras -- so it is not actually an alias of the
    documented command. uv only installs `[project.optional-dependencies]` extras when they
    are explicitly requested, and a bare `uv sync` against a venv that already has the "dev"
    extra installed actively uninstalls it. Either way, `make install` followed by `make test`
    / `make lint` (the exact sequence CLAUDE.md's own workflow prescribes) fails to spawn
    pytest/ruff."""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    install_recipe = makefile.split("install:", 1)[1].split("\n\n", 1)[0]
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev_extra = pyproject.get("project", {}).get("optional-dependencies", {}).get("dev")
    assert dev_extra, "expected a 'dev' extra in [project.optional-dependencies]"
    assert "--extra dev" in install_recipe or "--all-extras" in install_recipe, install_recipe
