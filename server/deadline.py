#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Monotonic deadlines and bounded executors for request-scoped fan-out."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, wait
import threading
import time
from typing import Any, Callable, Mapping


class Deadline:
    def __init__(self, seconds: float):
        self.started = time.monotonic()
        self.ends = self.started + max(0.0, float(seconds))

    def remaining(self, floor: float = 0.0) -> float:
        return max(float(floor), self.ends - time.monotonic())

    def expired(self) -> bool:
        return time.monotonic() >= self.ends


class BoundedExecutor:
    """Thread pool whose running + queued work can never exceed a fixed cap."""

    def __init__(self, max_workers: int, max_in_flight: int, *, prefix: str):
        if max_in_flight < max_workers or max_workers < 1:
            raise ValueError('max_in_flight must be >= max_workers >= 1')
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=prefix)
        self._slots = threading.BoundedSemaphore(max_in_flight)
        self._lock = threading.Lock()
        self._stats = {
            'maxWorkers': max_workers, 'maxInFlight': max_in_flight,
            'submitted': 0, 'completed': 0, 'rejected': 0, 'timeouts': 0, 'inFlight': 0,
        }

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future | None:
        if not self._slots.acquire(blocking=False):
            with self._lock:
                self._stats['rejected'] += 1
            return None

        started = threading.Event()
        released = threading.Event()

        def release_slot(*, completed: bool) -> None:
            if released.is_set():
                return
            with self._lock:
                if released.is_set():
                    return
                released.set()
                if completed:
                    self._stats['completed'] += 1
                self._stats['inFlight'] -= 1
            self._slots.release()

        def run() -> Any:
            started.set()
            try:
                return fn(*args, **kwargs)
            finally:
                release_slot(completed=True)

        with self._lock:
            self._stats['submitted'] += 1
            self._stats['inFlight'] += 1
        try:
            future = self._pool.submit(run)
            # ``Future.cancel`` can remove queued work before ``run`` executes.
            # In that case the wrapper's finally block never releases its slot.
            future.add_done_callback(
                lambda done: release_slot(completed=False)
                if done.cancelled() and not started.is_set() else None)
            return future
        except Exception:
            with self._lock:
                self._stats['inFlight'] -= 1
            self._slots.release()
            raise

    def note_timeouts(self, count: int) -> None:
        with self._lock:
            self._stats['timeouts'] += max(0, int(count))

    def status(self) -> dict[str, int]:
        with self._lock:
            return dict(self._stats)

    def shutdown(self, wait_for_running: bool = True) -> None:
        self._pool.shutdown(wait=wait_for_running, cancel_futures=True)


def collect_named(
    futures: Mapping[str, Future | None],
    *,
    timeout: float,
    executor: BoundedExecutor | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Collect completed results without waiting for work after the deadline."""
    active = {name: future for name, future in futures.items() if future is not None}
    outcomes = {name: 'saturated' for name, future in futures.items() if future is None}
    if not active:
        return {}, outcomes
    done, pending = wait(set(active.values()), timeout=max(0.0, float(timeout)))
    results: dict[str, Any] = {}
    for name, future in active.items():
        if future in done:
            try:
                results[name] = future.result()
                outcomes[name] = 'ok'
            except Exception as exc:
                outcomes[name] = f'error:{type(exc).__name__}'
        else:
            future.cancel()
            outcomes[name] = 'timeout'
    if executor is not None and pending:
        executor.note_timeouts(len(pending))
    return results, outcomes
