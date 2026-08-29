"""Deterministic loader for the user's portfolio configuration (fees, targets, risk
limits, rebalancing rules).

Skills must never open ``config/portfolio.yaml`` with the Read tool and hand-extract
numbers -- that is mental math over financial data, which CLAUDE.md forbids. This module
is the single place that reads the file; ``server.get_portfolio_config`` exposes it as an
MCP tool so every number reaching Claude carries an explicit source.

The user's own file (``config/portfolio.yaml``) is git-ignored and typically absent until
they create one; when it is missing this loader falls back to the tracked
``config/portfolio.example.yaml`` and reports that via ``is_example`` so Claude never
mistakes example numbers for the user's real configuration.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "portfolio.yaml"
EXAMPLE_CONFIG_PATH = REPO_ROOT / "config" / "portfolio.example.yaml"

# Sections a portfolio.yaml may define; missing sections come back as None, never invented.
CONFIG_SECTIONS = ("base_currency", "fees", "rebalancing", "risk_limits", "scoring", "targets")


def load_portfolio_config(
    path: Path | str | None = None,
    *,
    default_path: Path | str = DEFAULT_CONFIG_PATH,
    example_path: Path | str = EXAMPLE_CONFIG_PATH,
) -> dict:
    """Load fees/targets/risk_limits/rebalancing rules from a portfolio config file.

    Resolution order:
    - ``path`` given: read exactly that file, or raise ``FileNotFoundError`` -- no fallback.
    - ``path`` omitted: ``default_path`` if it exists, else ``example_path``.

    Returns the raw sections (``None`` for any section the file does not define) plus
    provenance: ``source`` (the path actually read), ``is_example`` (True when the user has
    not created their own config yet) and ``as_of`` (the file's last-modified time, UTC ISO
    8601). Raises ``FileNotFoundError`` when neither the requested nor the fallback file
    exists.
    """
    if path is not None:
        candidate = Path(path)
        is_example = False
    elif Path(default_path).exists():
        candidate = Path(default_path)
        is_example = False
    else:
        candidate = Path(example_path)
        is_example = True

    if not candidate.exists():
        raise FileNotFoundError(f"Portfolio config not found: {candidate}")

    raw = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
    mtime = datetime.fromtimestamp(candidate.stat().st_mtime, tz=UTC)

    result: dict = {section: raw.get(section) for section in CONFIG_SECTIONS}
    result["source"] = str(candidate)
    result["is_example"] = is_example
    result["as_of"] = mtime.isoformat()
    return result
