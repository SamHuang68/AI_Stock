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
    if _durable_default is not None:
        return _durable_default.submit_callable(name, fn, meta=meta, coalesce=coalesce)
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
    if _durable_default is not None:
        return _durable_default.legacy_status()
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
    if _durable_default is not None:
        jobs = _durable_default.status()['jobs']
        return any(j['status'] in ('queued', 'running') and
                   (name is None or j['type'] == 'legacy:' + name) for j in jobs)
    with _lock:
        if name:
            if _running and _running.get('name') == name:
                return True
            return name in _pending
        return bool(_running) or bool(_pending)


# 正式初始化後，舊 H5 入口也共用此持久工作者。Pulse 仍由 PulseUpdates 獨立擁有。
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from daemon_lock import acquire_daemon_lock, release_daemon_lock

_durable_default = None
_JOB_TABLE = 'managed_update_jobs_v1'
_ACTIVE = ('queued', 'running')
_RETRYABLE = ('failed', 'interrupted', 'timed_out')


class QueueFull(RuntimeError):
    pass


class JobExpired(RuntimeError):
    pass


class JobStopped(RuntimeError):
    pass


class JobContext:
    """合作式期限；非合作來源仍占用工作者，直到實際返回。"""
    def __init__(self, owner, job):
        self.owner, self.job = owner, job
        self.started = owner.monotonic()

    def check(self):
        if self.owner._stop.is_set():
            raise JobStopped('服務已停止；拒絕後續提交')
        if self.owner.monotonic() - self.started >= self.job['timeoutSeconds']:
            raise JobExpired('工作超過執行期限；未開始下一項工作')

    def stage(self, text):
        self.check()
        self.owner._stage(self.job['jobId'], str(text)[:160])


class DurableJobQueue:
    """有界、持久、單一工作者；讀取不建表、不恢復、不啟動。"""
    def __init__(self, db_path=None, *, capacity=16, retain=100,
                 clock=time.time, monotonic=time.monotonic):
        self.db_path = os.path.abspath(db_path or os.environ.get('ST_UPDATE_JOBS_DB') or
                                       Path(__file__).resolve().parents[1] / 'data/update_jobs.sqlite3')
        self.capacity, self.retain = max(1, int(capacity)), max(10, int(retain))
        self.clock, self.monotonic = clock, monotonic
        self._handlers = {}
        self._callables = {}
        self._lock = threading.RLock()
        self._wake, self._stop = threading.Event(), threading.Event()
        self._thread = self._lease = self._context = None
        self.worker_error = None

    def register(self, kind, fn, *, priority=50, timeout=300):
        if not isinstance(kind, str) or not kind or len(kind) > 120 or not callable(fn):
            raise ValueError('工作類型或執行函式不正確')
        if not 0 <= priority <= 100 or timeout <= 0:
            raise ValueError('優先順序或期限不正確')
        with self._lock:
            self._handlers[kind] = (fn, int(priority), float(timeout))

    def _connect(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA synchronous=FULL')
        return conn

    @staticmethod
    def _initialize(conn):
        conn.execute(f'''CREATE TABLE IF NOT EXISTS {_JOB_TABLE}(
            job_id TEXT PRIMARY KEY, kind TEXT NOT NULL, coalesce_key TEXT NOT NULL,
            params_json TEXT NOT NULL, reason TEXT NOT NULL, priority INTEGER NOT NULL,
            timeout_seconds REAL NOT NULL, status TEXT NOT NULL, stage TEXT NOT NULL,
            queued_at REAL NOT NULL, started_at REAL, finished_at REAL,
            error TEXT, result_json TEXT, parent_job_id TEXT, root_job_id TEXT NOT NULL,
            attempt INTEGER NOT NULL)''')
        conn.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS idx_{_JOB_TABLE}_active ON '
                     f"{_JOB_TABLE}(coalesce_key) WHERE status IN ('queued','running')")

    def _read(self, sql, args=()):
        if not os.path.isfile(self.db_path):
            return []
        try:
            with closing(sqlite3.connect(Path(self.db_path).as_uri() + '?mode=ro',
                                         uri=True, timeout=10)) as conn:
                conn.row_factory = sqlite3.Row
                return conn.execute(sql, args).fetchall()
        except sqlite3.OperationalError as exc:
            if 'no such table' in str(exc):
                return []
            raise

    def _view(self, row):
        if row is None:
            return None
        def stamp(value):
            return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None
        elapsed = max(0, (row['finished_at'] or self.clock()) - (row['started_at'] or self.clock()))
        if self._context and self._context.job['jobId'] == row['job_id']:
            elapsed = max(0, self.monotonic() - self._context.started)
        return dict(jobId=row['job_id'], type=row['kind'], params=json.loads(row['params_json']),
                    reason=row['reason'], priority=row['priority'], timeoutSeconds=row['timeout_seconds'],
                    status=row['status'], stage=row['stage'], queuedAt=stamp(row['queued_at']),
                    startedAt=stamp(row['started_at']), finishedAt=stamp(row['finished_at']),
                    elapsedMs=round(elapsed * 1000), overdue=row['status'] == 'running' and elapsed >= row['timeout_seconds'],
                    error=row['error'], result=json.loads(row['result_json']) if row['result_json'] else None,
                    parentJobId=row['parent_job_id'], rootJobId=row['root_job_id'], attempt=row['attempt'],
                    canRetry=row['status'] in _RETRYABLE and row['kind'] in self._handlers and not row['kind'].startswith('legacy:'))

    def get(self, job_id):
        rows = self._read(f'SELECT * FROM {_JOB_TABLE} WHERE job_id=?', (str(job_id),))
        return self._view(rows[0]) if rows else None

    def status(self):
        rows = self._read(f"SELECT * FROM {_JOB_TABLE} WHERE status IN ('queued','running') OR rowid IN "
                          f"(SELECT rowid FROM {_JOB_TABLE} WHERE status NOT IN ('queued','running') "
                          'ORDER BY queued_at DESC,rowid DESC LIMIT ?) ORDER BY queued_at DESC,rowid DESC',
                          (self.retain,))
        count = self._read(f'SELECT COUNT(*) AS total FROM {_JOB_TABLE}')
        return {'jobs': [self._view(row) for row in rows], 'capacity': self.capacity,
                'totalJobs': count[0]['total'] if count else 0,
                'worker': bool(self._thread and self._thread.is_alive()), 'workerError': self.worker_error}

    def archive(self):
        return [self._view(row) for row in self._read(f'SELECT * FROM {_JOB_TABLE} ORDER BY queued_at DESC,rowid DESC')]

    def start(self):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            digest = hashlib.sha256(os.path.normcase(os.path.realpath(self.db_path)).encode()).hexdigest()[:20]
            lease = acquire_daemon_lock('managed-updates-' + digest,
                                        lock_dir=Path(self.db_path).parent / 'runtime_locks')
            if lease is None:
                raise RuntimeError('另一個程序已擁有更新工作者')
            try:
                with closing(self._connect()) as conn, conn:
                    self._initialize(conn)
                    conn.execute(f"UPDATE {_JOB_TABLE} SET status='interrupted',stage='服務重啟',"
                                 "finished_at=?,error='前次執行已中斷，請檢查後重試' WHERE status='running'", (self.clock(),))
                    # 沒有可重建函式的舊 H5 工作只保留收據，不猜測重跑。
                    for row in conn.execute(f"SELECT job_id,kind FROM {_JOB_TABLE} WHERE status='queued'").fetchall():
                        if row['kind'] not in self._handlers or row['kind'].startswith('legacy:'):
                            self._callables.pop(row['job_id'], None)
                            conn.execute(f"UPDATE {_JOB_TABLE} SET status='interrupted',stage='無法重建',"
                                         "finished_at=?,error='工作無可恢復的註冊函式' WHERE job_id=?", (self.clock(), row['job_id']))
                self._lease = lease
                self._stop.clear()
                self._thread = threading.Thread(target=self._run, daemon=True, name='st-managed-updates')
                self._thread.start()
            except Exception:
                release_daemon_lock(lease)
                raise

    def stop(self, timeout=2):
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)
        # 非合作工作尚未返回時不可解鎖，避免新程序與舊來源並行。
        return not bool(self._thread and self._thread.is_alive())

    def submit_registered(self, kind, params=None, *, reason='manual', parent=None, unique=False):
        params = {} if params is None else params
        encoded = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if not isinstance(params, dict) or len(encoded) > 2048 or not isinstance(reason, str) or not 1 <= len(reason) <= 80:
            raise ValueError('工作參數或觸發原因不正確')
        with self._lock:
            if kind not in self._handlers:
                raise ValueError('不支援的更新工作')
            _, priority, timeout = self._handlers[kind]
            job_id = uuid.uuid4().hex
            key = kind + ':' + (job_id if unique else hashlib.sha256(encoded.encode()).hexdigest())
            with closing(self._connect()) as conn, conn:
                self._initialize(conn)
                conn.execute('BEGIN IMMEDIATE')
                previous = conn.execute(f"SELECT * FROM {_JOB_TABLE} WHERE coalesce_key=? AND status IN ('queued','running')", (key,)).fetchone()
                if previous:
                    return {'ok': True, 'job': self._view(previous), 'coalesced': True}
                count = conn.execute(f"SELECT COUNT(*) FROM {_JOB_TABLE} WHERE status IN ('queued','running')").fetchone()[0]
                if count >= self.capacity:
                    raise QueueFull('更新佇列已滿；請等待既有工作完成')
                conn.execute(f'INSERT INTO {_JOB_TABLE}(job_id,kind,coalesce_key,params_json,reason,priority,timeout_seconds,status,stage,queued_at,parent_job_id,root_job_id,attempt) '
                             "VALUES(?,?,?,?,?,?,?,'queued','等待執行',?,?,?,?)",
                             (job_id, kind, key, encoded, reason, priority, timeout, self.clock(),
                              parent['jobId'] if parent else None, parent['rootJobId'] if parent else job_id,
                              parent['attempt'] + 1 if parent else 1))
                # 更新工作沿革保留；即時清單有界，完整資料由明確匯出入口取得。
                row = conn.execute(f'SELECT * FROM {_JOB_TABLE} WHERE job_id=?', (job_id,)).fetchone()
        self._wake.set()
        return {'ok': True, 'job': self._view(row), 'coalesced': False}

    def retry(self, job_id):
        job = self.get(job_id)
        if not job or not job['canRetry']:
            raise ValueError('工作不存在、仍在執行或不允許重試')
        return self.submit_registered(job['type'], job['params'], reason='retry', parent=job)

    def submit_callable(self, name, fn, *, meta=None, coalesce=True):
        kind = 'legacy:' + str(name or 'anonymous')
        def invoke(context, params):
            with self._lock:
                callback = self._callables.pop(context.job['jobId'])
            return callback()
        # _run 取得函式時也持同一把鎖，避免工作先啟動才綁定 callback。
        with self._lock:
            self.register(kind, invoke, priority=80, timeout=300)
            result = self.submit_registered(kind, {}, reason='legacy', unique=not coalesce)
            if not result['coalesced']:
                self._callables[result['job']['jobId']] = fn
        return dict(result, ok=not result['coalesced'], queued=not result['coalesced'], skipped=result['coalesced'], name=name,
                    reason='running' if result['coalesced'] else None)

    def legacy_status(self):
        state = self.status()
        def legacy(job):
            def epoch(value):
                return datetime.fromisoformat(value).timestamp() if value else None
            return dict(job, name=job['type'].removeprefix('legacy:'), ok=job['status'] == 'succeeded',
                        queued_at=epoch(job['queuedAt']), started_at=epoch(job['startedAt']),
                        finished_at=epoch(job['finishedAt']), elapsed_ms=job['elapsedMs'], meta={})
        pending = [legacy(j) for j in state['jobs'] if j['status'] == 'queued']
        running = next((legacy(j) for j in state['jobs'] if j['status'] == 'running'), None)
        return dict(state, pending=[j['name'] for j in pending], pendingDetail={j['name']: j for j in pending},
                    running=running, queueSize=len(pending), history=[legacy(j) for j in state['jobs'] if j['status'] not in _ACTIVE])

    def _stage(self, job_id, text):
        with closing(self._connect()) as conn, conn:
            conn.execute(f"UPDATE {_JOB_TABLE} SET stage=? WHERE job_id=? AND status='running'", (text, job_id))

    def _claim(self):
        with closing(self._connect()) as conn, conn:
            conn.execute('BEGIN IMMEDIATE')
            # 等候一分鐘的工作升到最高級，防止低優先工作持續飢餓。
            row = conn.execute(f"SELECT * FROM {_JOB_TABLE} WHERE status='queued' ORDER BY "
                               'CASE WHEN queued_at<? THEN -1 ELSE priority END,queued_at,rowid LIMIT 1', (self.clock() - 60,)).fetchone()
            if row:
                conn.execute(f"UPDATE {_JOB_TABLE} SET status='running',stage='執行中',started_at=? WHERE job_id=?", (self.clock(), row['job_id']))
                return self._view(conn.execute(f'SELECT * FROM {_JOB_TABLE} WHERE job_id=?', (row['job_id'],)).fetchone())

    def _finish(self, job, status, result, error):
        with closing(self._connect()) as conn, conn:
            conn.execute(f'UPDATE {_JOB_TABLE} SET status=?,stage=?,finished_at=?,result_json=?,error=? WHERE job_id=?',
                         (status, {'succeeded': '完成', 'failed': '失敗', 'timed_out': '逾時後已結束', 'interrupted': '已中斷'}[status],
                          self.clock(), json.dumps(result, ensure_ascii=False, allow_nan=False) if result is not None else None,
                          error, job['jobId']))

    def _run(self):
        try:
            while not self._stop.is_set():
                try:
                    job = self._claim()
                    if not job:
                        self._wake.wait(0.5)
                        self._wake.clear()
                        continue
                    context = JobContext(self, job)
                    self._context = context
                    result, error, status = None, None, 'succeeded'
                    try:
                        context.check()
                        with self._lock:
                            fn = self._handlers[job['type']][0]
                        result = fn(context, job['params'])
                        context.check()
                        json.dumps(result, allow_nan=False)
                    except Exception as exc:
                        status = 'timed_out' if isinstance(exc, JobExpired) else 'interrupted' if isinstance(exc, JobStopped) else 'failed'
                        error, result = str(exc)[:400], None
                    # 終態持久失敗只重試同一收據，不重跑來源函式。
                    while True:
                        try:
                            self._finish(job, status, result, error)
                            self.worker_error = None
                            break
                        except sqlite3.Error as exc:
                            self.worker_error = '保存工作結果失敗：' + str(exc)[:160]
                            if self._stop.wait(0.5):
                                return
                    self._context = None
                except Exception as exc:
                    self.worker_error = '更新工作者失敗：' + str(exc)[:200]
                    if self._stop.wait(0.5):
                        break
        finally:
            self._context = None
            release_daemon_lock(self._lease)
            self._lease = None


def use_durable_queue(manager):
    """只由服務啟動接線呼叫，不在讀取端點初始化。"""
    global _durable_default
    with _lock:
        if _worker_started and (_running or _pending):
            raise RuntimeError('舊背景佇列仍有工作；須完成後才能切換持久佇列')
        _durable_default = manager
