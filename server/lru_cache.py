#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Thread-safe LRU cache with TTL for the local Stock Terminal server."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any


class LRUCache:
    """Bounded in-memory cache with per-entry expiry."""

    def __init__(self, maxsize: int, ttl_seconds: float = 60.0):
        self._d: OrderedDict[str, tuple[Any, float]] = OrderedDict()
        self._max = int(maxsize)
        self._ttl = float(ttl_seconds)
        self._lock = threading.Lock()

    @property
    def ttl_seconds(self) -> float:
        return self._ttl

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._d.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if expires_at <= time.time():
                self._d.pop(key, None)
                return None
            self._d.move_to_end(key)
            return value

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        with self._lock:
            expires_at = time.time() + (ttl if ttl is not None else self._ttl)
            if key in self._d:
                self._d.move_to_end(key)
            self._d[key] = (value, expires_at)
            if len(self._d) > self._max:
                self._d.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._d)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                'used': len(self._d),
                'max': self._max,
                'ttlSeconds': self._ttl,
            }
