"""Generate docs/TEST_REPORT.md: one row per test (status, duration), coverage per module,
lint/validation gates. Reproducible: `uv run --with pytest-cov python scripts/test_report.py`.
"""

from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "TEST_REPORT.md"
TMP = ROOT / ".pytest_report"


def run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def main() -> int:
    TMP.mkdir(exist_ok=True)
    junit = TMP / "junit.xml"
    cov_json = TMP / "coverage.json"
    code, out = run(
        [
            "uv", "run", "--with", "pytest-cov", "pytest", "-q", "-p", "no:cacheprovider",
            f"--junitxml={junit}", "--durations=0",
            "--cov=portfolio_copilot", f"--cov-report=json:{cov_json}", "--cov-report=term",
        ]
    )
    summary_line = next((ln for ln in out.splitlines()[::-1] if "passed" in ln or "failed" in ln), "")

    root = ET.parse(junit).getroot()
    cases = []
    for tc in root.iter("testcase"):
        status = "passed"
        detail = ""
        for tag in ("failure", "error"):
            node = tc.find(tag)
            if node is not None:
                status = tag
                detail = (node.attrib.get("message") or "")[:120]
        if tc.find("skipped") is not None:
            node = tc.find("skipped")
            status = "xfail" if "xfail" in (node.attrib.get("type", "") + node.attrib.get("message", "")) else "skipped"
            detail = (node.attrib.get("message") or "")[:120]
        file = tc.attrib.get("classname", "").split(".")[-1] or "?"
        cases.append(
            {"file": file, "name": tc.attrib.get("name", ""), "time": float(tc.attrib.get("time", 0)),
             "status": status, "detail": detail}
        )
    cases.sort(key=lambda c: (c["file"], c["name"]))

    cov = json.loads(cov_json.read_text()) if cov_json.exists() else {"files": {}, "totals": {}}
    ruff_code, ruff_out = run(["uv", "run", "ruff", "check", "."])
    validations = {}
    for target in (".", "skills", "agents"):
        vcode, vout = run(["claude", "plugin", "validate", "--strict", target])
        validations[target] = "pass" if vcode == 0 else f"FAIL: {vout.splitlines()[-1] if vout else ''}"

    counts = {s: sum(1 for c in cases if c["status"] == s) for s in ("passed", "failure", "error", "xfail", "skipped")}
    total_time = sum(c["time"] for c in cases)
    as_of = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Test report",
        "",
        f"Generated {as_of} by `scripts/test_report.py`. Every test is offline and deterministic.",
        "",
        "## Gates",
        "",
        "| gate | result |",
        "|---|---|",
        f"| pytest | {summary_line or 'n/a'} |",
        f"| tests total / passed / failed+error / xfail / skipped | {len(cases)} / {counts['passed']} / {counts['failure'] + counts['error']} / {counts['xfail']} / {counts['skipped']} |",
        f"| total test time | {total_time:.2f} s |",
        f"| ruff check . | {'clean' if ruff_code == 0 else 'FAIL'} |",
        f"| claude plugin validate --strict . | {validations['.']} |",
        f"| claude plugin validate --strict skills | {validations['skills']} |",
        f"| claude plugin validate --strict agents | {validations['agents']} |",
        f"| line coverage (src/portfolio_copilot) | {cov.get('totals', {}).get('percent_covered', 0):.1f}% |",
        "",
        "## Coverage per module",
        "",
        "| module | statements | missing | covered |",
        "|---|---:|---:|---:|",
    ]
    for path, data in sorted(cov.get("files", {}).items()):
        s = data["summary"]
        rel = path.replace(str(ROOT) + "/", "").replace("src/portfolio_copilot/", "")
        lines.append(f"| {rel} | {s['num_statements']} | {s['missing_lines']} | {s['percent_covered']:.0f}% |")

    lines += ["", "## Slowest 10 tests", "", "| test | seconds |", "|---|---:|"]
    for c in sorted(cases, key=lambda c: -c["time"])[:10]:
        lines.append(f"| {c['file']}::{c['name']} | {c['time']:.3f} |")

    lines += ["", "## Every test", ""]
    current = None
    for c in cases:
        if c["file"] != current:
            current = c["file"]
            n = sum(1 for x in cases if x["file"] == current)
            t = sum(x["time"] for x in cases if x["file"] == current)
            lines += ["", f"### {current} — {n} tests, {t:.2f} s", "", "| test | status | seconds | note |", "|---|---|---:|---|"]
        mark = {"passed": "✅", "failure": "❌", "error": "❌", "xfail": "⚠️ xfail", "skipped": "⏭️"}[c["status"]]
        lines.append(f"| {c['name']} | {mark} | {c['time']:.3f} | {c['detail']} |")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT} — {len(cases)} tests, {counts['passed']} passed, coverage {cov.get('totals', {}).get('percent_covered', 0):.1f}%")
    return 0 if code == 0 and ruff_code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
