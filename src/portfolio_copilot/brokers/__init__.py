"""Execution-capable broker adapters (tier A, the user's own account).

Everything under ``parsers/`` and ``providers/`` stays read-only and account-agnostic
(local export files, keyless public market data). This package is the one deliberate
exception: ``brokers.etoro`` talks to the eToro Public API v2 using the user's own API
credentials, on the user's own explicit, rule-bound request (see CLAUDE.md and the eToro
execution rule change). It never touches any other broker, never infers ``allow_real``,
and never sends an order that was not shown to and confirmed by the user first.
"""

from __future__ import annotations
