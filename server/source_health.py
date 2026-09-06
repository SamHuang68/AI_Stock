#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TrustedDataLayer source health, throttling, circuit breaker and fetch helper."""
from __future__ import annotations

import json
import threading
import time
import urllib.request


_LOCK = threading.Lock()
HEALTH: dict[str, dict] = {}
LAST_CALL: dict[str, float] = {}
MIN_GAP = {
    'taifex-mis': 1.0,
    'twse-mis': 0.3,
    'twse-chip': 0.35,
    'yahoo-keystats': 0.2,
}
CB_THRESHOLD = 4
CB_COOLDOWN = 30.0


class SourceBreakerOpen(Exception):
    """Raised while a source circuit breaker is open."""


def record(name: str, ok: bool, ms: int, err: Exception | str | None = None) -> None:
    with _LOCK:
        row = HEALTH.get(name)
        if row is None:
            row = {
                'ok_ct': 0, 'err_ct': 0, 'last_ok': 0, 'last_err': 0,
                'last_ms': None, 'fail_streak': 0, 'last_error': None, 'open_until': 0,
            }
            HEALTH[name] = row
        row['last_ms'] = ms
        if ok:
            row['ok_ct'] += 1
            row['last_ok'] = time.time()
            row['fail_streak'] = 0
            row['open_until'] = 0
        else:
            row['err_ct'] += 1
            row['last_err'] = time.time()
            row['fail_streak'] += 1
            row['last_error'] = (str(err)[:160] if err else 'error')
            if row['fail_streak'] >= CB_THRESHOLD:
                row['open_until'] = time.time() + CB_COOLDOWN


def breaker_open(name: str) -> bool:
    with _LOCK:
        row = HEALTH.get(name)
        return bool(row and time.time() < row['open_until'])


def throttle(name: str) -> None:
    gap = MIN_GAP.get(name)
    if not gap:
        return
    with _LOCK:
        last = LAST_CALL.get(name, 0)
        wait = gap - (time.time() - last)
        LAST_CALL[name] = max(time.time(), last + gap)
    if wait > 0:
        time.sleep(min(wait, 3.0))


def fetch_json(name: str, url: str, headers: dict | None = None,
               timeout: int = 10, retries: int = 1, data: bytes | None = None):
    if breaker_open(name):
        raise SourceBreakerOpen(name)
    last_exc: Exception | None = None
    try:
        import http_client as _hc
    except Exception:
        _hc = None
    for attempt in range(retries + 1):
        throttle(name)
        t0 = time.time()
        try:
            if _hc is not None:
                resp = _hc.request(
                    'POST' if data is not None else 'GET',
                    url,
                    headers=headers or {},
                    data=data,
                    timeout=timeout,
                    retries=0,
                )
                raw = resp.body
            else:
                req = urllib.request.Request(url, headers=headers or {}, data=data)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
            parsed = json.loads(raw)
            record(name, True, int((time.time() - t0) * 1000))
            return parsed
        except Exception as exc:
            last_exc = exc
            record(name, False, int((time.time() - t0) * 1000), exc)
            if attempt < retries:
                time.sleep(min(0.5 * (2 ** attempt), 4.0))
    raise last_exc if last_exc else RuntimeError(name + ' fetch failed')


def snapshot() -> dict[str, dict]:
    out: dict[str, dict] = {}
    now = time.time()
    with _LOCK:
        for key, row in HEALTH.items():
            total = row['ok_ct'] + row['err_ct']
            out[key] = {
                'healthy': row['fail_streak'] < CB_THRESHOLD and not (now < row['open_until']),
                'okRate': round(row['ok_ct'] / total * 100, 1) if total else None,
                'calls': total,
                'lastOkAgo': round(now - row['last_ok'], 1) if row['last_ok'] else None,
                'lastErrAgo': round(now - row['last_err'], 1) if row['last_err'] else None,
                'lastMs': row['last_ms'],
                'failStreak': row['fail_streak'],
                'lastError': row['last_error'],
                'breakerOpen': now < row['open_until'],
            }
    return out
