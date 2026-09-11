"""共用同範圍的焦點掃描，並從完成時起算快取有效期。"""
from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import Future
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Hashable


@dataclass(frozen=True)
class _Entry:
    payload: dict[str, Any]
    completed: float
    completed_at: str
    duration_ms: int
    scan_id: str


class FocusScanCache:
    def __init__(
        self, ttl_sec: float = 180, *, max_entries: int = 64,
        wait_timeout_sec: float = 120,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ):
        if ttl_sec <= 0 or max_entries < 1 or wait_timeout_sec < 0:
            raise ValueError('焦點掃描快取設定無效')
        self._ttl = ttl_sec
        self._max_entries = max_entries
        self._wait_timeout = wait_timeout_sec
        self._clock = clock
        self._wall_clock = wall_clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[Hashable, _Entry] = OrderedDict()
        self._inflight: dict[Hashable, Future] = {}

    def _response(self, entry: _Entry, *, cache_hit: bool, shared: bool) -> dict[str, Any]:
        # 每位呼叫者取得獨立副本，避免格式化或排序污染其他頁面的結果。
        response = deepcopy(entry.payload)
        response['scan'] = {
            'id': entry.scan_id,
            'completedAt': entry.completed_at,
            'durationMs': entry.duration_ms,
            'ageSeconds': round(max(0.0, self._clock() - entry.completed), 3),
            'cacheHit': cache_hit,
            'shared': shared,
        }
        return response

    def get_or_scan(
        self, key: Hashable, scan: Callable[[], dict[str, Any]], *, force: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            entry = self._entries.get(key)
            if not force and entry is not None and self._clock() - entry.completed < self._ttl:
                self._entries.move_to_end(key)
                return self._response(entry, cache_hit=True, shared=False)
            future = self._inflight.get(key)
            owner = future is None
            if owner:
                future = Future()
                self._inflight[key] = future

        if not owner:
            # 等待者逾時只結束自己的等待，不取消其他頁面共用的工作。
            return self._response(future.result(timeout=self._wait_timeout), cache_hit=False, shared=True)

        started = self._clock()
        try:
            payload = scan()
            if not isinstance(payload, dict) or payload.get('ok') is not True:
                raise ValueError('焦點掃描未回傳成功結果')
            completed = self._clock()
            entry = _Entry(
                payload=deepcopy(payload), completed=completed,
                completed_at=datetime.fromtimestamp(self._wall_clock(), timezone.utc).isoformat(),
                duration_ms=round(max(0.0, completed - started) * 1000), scan_id=uuid.uuid4().hex,
            )
            with self._lock:
                self._entries[key] = entry
                self._entries.move_to_end(key)
                while len(self._entries) > self._max_entries:
                    self._entries.popitem(last=False)
            future.set_result(entry)
        except BaseException as exc:
            future.set_exception(exc)
            raise
        finally:
            with self._lock:
                self._inflight.pop(key, None)
        return self._response(entry, cache_hit=False, shared=False)
