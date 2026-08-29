"""Tiny in-process TTL cache for market data. Deterministic, no I/O."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any


class TTLCache:
    def __init__(self, ttl_seconds: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.ttl = float(ttl_seconds)
        self._clock = clock
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if item is None:
            return None
        expires, value = item
        if self._clock() >= expires:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (self._clock() + self.ttl, value)
