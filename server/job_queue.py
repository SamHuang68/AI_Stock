# -*- coding: utf-8 -*-
"""
統一背景任務佇列（H5）

單 worker：避免 macro／TDCC／margin 同時狂打 TWSE／FRED。
同名任務 coalesce：已在跑或排隊中則跳過重複提交。
"""
from __future__ import annotations

import queue
import threading
import time
import traceback
from typing import Any, Callable, Dict, Optional

try:
    import slog
    log = slog.get_logger('job_queue')
except Exception:
    log = None

_q: queue.Queue = queue.Queue()
_lock = threading.Lock()
_pending: Dict[str, Dict[str, Any]] = {}   # name → meta
_running: Optional[Dict[str, Any]] = None
_history: list = []  # last N finished
_HISTORY_MAX = 20
_worker_started = False


def _ensure_worker() -> None:
    global _worker_started
    with _lock:
        if _worker_started:
            return
        t = threading.Thread(target=_worker_loop, daemon=True, name='st-job-queue')
        t.start()
        _worker_started = True
        if log:
            log.info('job queue worker started')


def _worker_loop() -> None:
    global _running
    while True:
        item = _q.get()
        if item is None:
            break
        name, fn, meta = item
        with _lock:
            _pending.pop(name, None)
            _running = {
                'name': name,
                'started_at': time.time(),
                'meta': dict(meta or {}),
            }
        ok = True
        err = None
        t0 = time.time()
        try:
            if log:
                log.info('job start %s', name)
            fn()
        except Exception as e:
            ok = False
            err = str(e)
            if log:
                log.error('job fail %s: %s\n%s', name, e, traceback.format_exc())
            else:
                print('[job_queue] fail', name, e)
        finally:
            finished = {
                'name': name,
                'ok': ok,
                'error': err,
                'started_at': _running.get('started_at') if _running else t0,
                'finished_at': time.time(),
                'elapsed_ms': int((time.time() - t0) * 1000),
                'meta': dict(meta or {}),
            }
            with _lock:
                _running = None
                _history.append(finished)
                if len(_history) > _HISTORY_MAX:
                    del _history[0:_HISTORY_MAX // 2]
            if log:
                log.info('job done %s ok=%s %sms', name, ok, finished['elapsed_ms'])
            _q.task_done()


def submit(name: str, fn: Callable[[], Any], *, coalesce: bool = True,
           meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    提交背景任務。
    coalesce=True（預設）：同名已在跑或排隊 → 回 skipped。
    """
    _ensure_worker()
    name = str(name or '').strip() or 'anonymous'
    meta = dict(meta or {})
    with _lock:
        if coalesce:
            if _running and _running.get('name') == name:
                return {'ok': False, 'queued': False, 'skipped': True, 'reason': 'running'}
            if name in _pending:
                return {'ok': False, 'queued': False, 'skipped': True, 'reason': 'pending'}
        _pending[name] = {'queued_at': time.time(), 'meta': meta}
    _q.put((name, fn, meta))
    return {'ok': True, 'queued': True, 'skipped': False, 'name': name}


def status() -> Dict[str, Any]:
    with _lock:
        return {
            'pending': sorted(_pending.keys()),
            'pendingDetail': {k: dict(v) for k, v in _pending.items()},
            'running': dict(_running) if _running else None,
            'queueSize': _q.qsize(),
            'history': list(_history[-10:]),
            'worker': _worker_started,
        }


def is_busy(name: Optional[str] = None) -> bool:
    with _lock:
        if name:
            if _running and _running.get('name') == name:
                return True
            return name in _pending
        return bool(_running) or bool(_pending)
