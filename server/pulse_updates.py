"""Pulse 專用持久更新佇列；讀取狀態不建表、不啟動或提交工作。"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from daemon_lock import acquire_daemon_lock, release_daemon_lock
from jsonl_trace import append_jsonl


TABLE = 'pulse_update_jobs_v1'
TERMINAL_RETAIN = 100
_ROOT = Path(__file__).resolve().parents[1]
_CONNECT_LOCK = threading.Lock()


class PulseUpdateExpired(RuntimeError):
    """工作已超過開始新發布的時限；已記錄意圖的發布由既有協定完成。"""


class PulseUpdateStopped(RuntimeError):
    """服務已要求停止，拒絕後續發布。"""


class PulseUpdates:
    def __init__(self, db_path=None, trace_path=None, *, interval_seconds=60,
                 max_run_seconds=300, clock=time.time, monotonic=time.monotonic):
        self.db_path = os.path.abspath(db_path or os.environ.get('ST_UPDATE_JOBS_DB') or
                                       _ROOT / 'data' / 'update_jobs.sqlite3')
        self.trace_path = os.path.abspath(trace_path or _ROOT / 'logs' / 'pulse_updates.jsonl')
        self.interval_seconds = max(0.01, float(interval_seconds))
        self.max_run_seconds = max(0.01, float(max_run_seconds))
        self._clock = clock
        self._monotonic = monotonic
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._lease = None
        self._running_id = None
        self._running_mono = None
        self._worker_error = None
        self._lookup_committed = None

    def _connect(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        # 同程序不同佇列物件首次開啟同一檔案時，WAL 模式切換不可競爭。
        with _CONNECT_LOCK:
            conn = sqlite3.connect(self.db_path, timeout=10)
            try:
                conn.row_factory = sqlite3.Row
                if conn.execute('PRAGMA journal_mode').fetchone()[0].lower() != 'wal':
                    conn.execute('PRAGMA journal_mode=WAL')
                conn.execute('PRAGMA synchronous=FULL')
                return conn
            except Exception:
                conn.close()
                raise

    @staticmethod
    def _initialize(conn):
        conn.execute(f'CREATE TABLE IF NOT EXISTS {TABLE}('
                     'job_id TEXT PRIMARY KEY,reason TEXT NOT NULL,status TEXT NOT NULL,'
                     'queued_at REAL NOT NULL,started_at REAL,finished_at REAL,error TEXT,result_json TEXT,recovery_json TEXT,'
                     "CHECK(status IN ('queued','running','succeeded','failed','interrupted')))")
        columns = {row[1] for row in conn.execute(f'PRAGMA table_info({TABLE})')}
        if 'recovery_json' not in columns:
            conn.execute(f'ALTER TABLE {TABLE} ADD COLUMN recovery_json TEXT')
        conn.execute(f'CREATE UNIQUE INDEX IF NOT EXISTS idx_{TABLE}_active '
                     f"ON {TABLE}((1)) WHERE status IN ('queued','running')")

    @staticmethod
    def _prune(conn):
        conn.execute(f"DELETE FROM {TABLE} WHERE status NOT IN ('queued','running') AND job_id NOT IN "
                     f"(SELECT job_id FROM {TABLE} WHERE status NOT IN ('queued','running') "
                     'ORDER BY finished_at DESC,rowid DESC LIMIT ?)', (TERMINAL_RETAIN,))

    def _read(self, sql, args=()):
        if not os.path.isfile(self.db_path):
            return []
        try:
            with closing(sqlite3.connect(Path(self.db_path).resolve().as_uri() + '?mode=ro',
                                         uri=True, timeout=10)) as conn:
                conn.row_factory = sqlite3.Row
                return conn.execute(sql, args).fetchall()
        except sqlite3.OperationalError as exc:
            if 'no such table' in str(exc):
                return []
            raise

    def _elapsed(self, row):
        if row['started_at'] is None:
            return 0.0
        with self._lock:
            if row['status'] == 'running' and self._running_id == row['job_id'] and self._running_mono is not None:
                return max(0.0, self._monotonic() - self._running_mono)
        return max(0.0, (row['finished_at'] or self._clock()) - row['started_at'])

    def _view(self, row):
        if row is None:
            return None
        elapsed = self._elapsed(row)
        recovery_raw = row['recovery_json'] if 'recovery_json' in row.keys() else None
        def timestamp(value):
            return datetime.fromtimestamp(value, timezone.utc).isoformat() if value is not None else None
        return {'jobId': row['job_id'], 'reason': row['reason'], 'status': row['status'],
                'queuedAt': timestamp(row['queued_at']), 'startedAt': timestamp(row['started_at']),
                'finishedAt': timestamp(row['finished_at']), 'elapsedMs': round(elapsed * 1000),
                'overdue': row['status'] == 'running' and elapsed >= self.max_run_seconds,
                'error': row['error'], 'result': json.loads(row['result_json']) if row['result_json'] else None,
                'recovery': json.loads(recovery_raw) if recovery_raw else None}

    def _trace(self, event, job=None, error=None):
        try:
            append_jsonl(self.trace_path, {
                'ts': datetime.fromtimestamp(self._clock(), timezone.utc).isoformat(),
                'jobId': (job or {}).get('jobId'), 'event': event,
                'status': (job or {}).get('status'), 'elapsedMs': (job or {}).get('elapsedMs', 0),
                **({'error': str(error)[:400]} if error else {}),
            }, max_bytes=256 * 1024, tail_lines=500)
        except OSError:
            pass

    def status(self, job_id=None):
        rows = self._read(f'SELECT * FROM {TABLE} ORDER BY queued_at DESC,rowid DESC LIMIT 101')
        jobs = [self._view(row) for row in rows]
        if job_id is not None:
            selected = self._read(f'SELECT * FROM {TABLE} WHERE job_id=?', (str(job_id),))
            job = self._view(selected[0]) if selected else None
        else:
            job = next((item for item in jobs if item['status'] in ('queued', 'running')), jobs[0] if jobs else None)
        with self._lock:
            worker = bool(self._thread and self._thread.is_alive())
            error = self._worker_error
        return {'ok': True, 'job': job, 'jobs': jobs, 'worker': worker,
                'overdue': bool(job and job['overdue']), 'workerError': error}

    def submit(self, reason='manual'):
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 80:
            raise ValueError('更新原因必須是 1 至 80 字元的非空白字串')
        with self._lock, closing(self._connect()) as conn:
            if self._thread is not None and not self._thread.is_alive() and self._worker_error:
                raise RuntimeError('背景更新工作者已停止；須重新啟動後再提交更新')
            with conn:
                self._initialize(conn)
                conn.execute('BEGIN IMMEDIATE')
                row = conn.execute(f"SELECT * FROM {TABLE} WHERE status IN ('queued','running')").fetchone()
                coalesced = row is not None
                if row is None:
                    job_id = uuid.uuid4().hex
                    conn.execute(f'INSERT INTO {TABLE}(job_id,reason,status,queued_at) VALUES(?,?,?,?)',
                                 (job_id, reason.strip(), 'queued', self._clock()))
                    self._prune(conn)
                    row = conn.execute(f'SELECT * FROM {TABLE} WHERE job_id=?', (job_id,)).fetchone()
        job = self._view(row)
        self._trace('coalesced' if coalesced else 'queued', job)
        self._wake.set()
        return {'job': job, 'coalesced': coalesced}

    @staticmethod
    def _identity(pulse, job_id):
        if not isinstance(pulse, dict) or pulse.get('updateJobId') != job_id:
            raise ValueError('已提交快照不屬於目前更新工作')
        summary = (pulse or {}).get('decisionSummary') or {}
        revision = summary.get('revision')
        if (summary.get('persistence') != 'committed' or not isinstance(summary.get('snapshotId'), str)
                or not summary['snapshotId'] or isinstance(revision, bool)
                or not isinstance(revision, int) or revision < 1):
            raise ValueError('更新結果缺少已提交決策的快照識別與修訂')
        return {key: summary.get(key) for key in ('snapshotId', 'revision', 'inputHash', 'rulesDigest')}

    def _recover(self, latest_pulse):
        rows = self._read(f"SELECT * FROM {TABLE} WHERE status='running'")
        latest = latest_pulse() if rows else None
        recovered = []
        with closing(self._connect()) as conn:
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                for row in rows:
                    state, result, error = 'interrupted', None, '前次程序中斷；使用新工作重新建置'
                    found = self._lookup_committed(row['job_id']) if self._lookup_committed else None
                    candidate = found or latest
                    if candidate and candidate.get('updateJobId') == row['job_id']:
                        try:
                            result = self._identity(candidate, row['job_id'])
                            state, error = 'succeeded', None
                        except (ValueError, TypeError, AttributeError):
                            pass
                    recovery = self._recovery_record(row, 'startup_committed' if result else 'startup_interrupted')
                    conn.execute(f'UPDATE {TABLE} SET status=?,finished_at=?,error=?,result_json=?,recovery_json=? '
                                 "WHERE job_id=? AND status='running'", (
                                     state, self._clock(), error, json.dumps(result) if result else None,
                                     json.dumps(recovery, ensure_ascii=False), row['job_id']))
                    recovered.append(conn.execute(f'SELECT * FROM {TABLE} WHERE job_id=?', (row['job_id'],)).fetchone())
                self._prune(conn)
        for row in recovered:
            self._trace('recovered', self._view(row))

    def _recovery_record(self, row, reason):
        return {'reason': reason, 'at': self._clock(), 'previousStatus': row['status'],
                'previousError': row['error'],
                'previousResult': json.loads(row['result_json']) if row['result_json'] else None,
                'previousRecovery': json.loads(row['recovery_json']) if row['recovery_json'] else None}

    def _reconcile(self):
        if self._lookup_committed is None:
            return
        for row in self._read(f"SELECT * FROM {TABLE} WHERE status IN ('failed','interrupted')"):
            pulse = self._lookup_committed(row['job_id'])
            if pulse is None:
                continue
            result = self._identity(pulse, row['job_id'])
            recovery = self._recovery_record(row, 'committed_after_interruption')
            with closing(self._connect()) as conn:
                with conn:
                    conn.execute(f"UPDATE {TABLE} SET status='succeeded',finished_at=?,error=NULL,"
                                 "result_json=?,recovery_json=? WHERE job_id=? AND status IN ('failed','interrupted')",
                                 (self._clock(), json.dumps(result), json.dumps(recovery, ensure_ascii=False), row['job_id']))
                    current = conn.execute(f'SELECT * FROM {TABLE} WHERE job_id=?', (row['job_id'],)).fetchone()
            self._trace('reconciled', self._view(current))

    def start(self, builder: Callable, latest_pulse: Callable, lookup_committed: Callable | None = None):
        with self._lock:
            if self._thread and self._thread.is_alive():
                return False
            key = hashlib.sha256(os.path.normcase(os.path.realpath(self.db_path)).encode()).hexdigest()[:20]
            lease = acquire_daemon_lock('pulse-updates-' + key,
                                       lock_dir=Path(self.db_path).parent / 'runtime_locks')
            if lease is None:
                return False
            self._lease = lease
            try:
                self._lookup_committed = lookup_committed
                with closing(self._connect()) as conn:
                    with conn:
                        self._initialize(conn)
                self._recover(latest_pulse)
                self._reconcile()
                self._stop.clear()
                self._worker_error = None
                self.submit('boot')
                self._thread = threading.Thread(target=self._loop, args=(builder,),
                                                name='st-pulse-updates', daemon=True)
                self._thread.start()
                return True
            except Exception:
                release_daemon_lock(self._lease)
                self._lease = None
                raise

    def _claim(self):
        with closing(self._connect()) as conn:
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                row = conn.execute(f"SELECT * FROM {TABLE} WHERE status='queued' ORDER BY queued_at LIMIT 1").fetchone()
                if row is None:
                    return None
                conn.execute(f"UPDATE {TABLE} SET status='running',started_at=? WHERE job_id=?",
                             (self._clock(), row['job_id']))
                row = conn.execute(f'SELECT * FROM {TABLE} WHERE job_id=?', (row['job_id'],)).fetchone()
        with self._lock:
            self._running_id, self._running_mono = row['job_id'], self._monotonic()
        return row

    def _retry(self, exc, attempt, job=None):
        with self._lock:
            self._worker_error = f'{type(exc).__name__}: {exc}'[:400]
        self._trace('persistence_retry', job, self._worker_error)
        return not self._stop.wait(min(5.0, 0.1 * 2 ** min(attempt, 6)))

    def _finish(self, job_id, state, result, error):
        with closing(self._connect()) as conn:
            with conn:
                conn.execute(f'UPDATE {TABLE} SET status=?,finished_at=?,error=?,result_json=? '
                             "WHERE job_id=? AND status='running'", (
                                 state, self._clock(), error, json.dumps(result) if result else None, job_id))
                self._prune(conn)
                return conn.execute(f'SELECT * FROM {TABLE} WHERE job_id=?', (job_id,)).fetchone()

    def _run(self, row, builder):
        job_id, started = row['job_id'], self._running_mono
        self._trace('running', self._view(row))
        def guard():
            if self._stop.is_set():
                raise PulseUpdateStopped('更新服務停止中，拒絕發布')
            if self._monotonic() - started >= self.max_run_seconds:
                raise PulseUpdateExpired('更新已超過開始新發布的時限；底層工作仍可能繼續')
            current = self._read(f'SELECT status FROM {TABLE} WHERE job_id=?', (job_id,))
            if not current or current[0]['status'] != 'running':
                raise PulseUpdateStopped('此更新已不再持有發布資格')
        state, result, error = 'succeeded', None, None
        try:
            guard()
            # builder 在記錄新發布意圖前檢查 guard；已提交後不可再因逾時改記失敗。
            result = self._identity(builder(job_id, guard), job_id)
        except Exception as exc:
            state = 'interrupted' if isinstance(exc, PulseUpdateStopped) else 'failed'
            error = f'{type(exc).__name__}: {exc}'[:400]
        attempt = 0
        while True:
            try:
                finished = self._finish(job_id, state, result, error)
                break
            except (sqlite3.Error, OSError) as exc:
                attempt += 1
                # 建置或提交已經完成，只重試工作收據，不能再執行 builder。
                if not self._retry(exc, attempt, self._view(row)):
                    return
        self._trace(state, self._view(finished), error)
        with self._lock:
            self._running_id = self._running_mono = None
            self._worker_error = None

    def _loop(self, builder):
        next_tick = self._monotonic() + self.interval_seconds
        attempt = 0
        try:
            while not self._stop.is_set():
                try:
                    self._reconcile()
                    row = self._claim()
                    if row is not None:
                        self._run(row, builder)
                        if self._stop.is_set():
                            break
                        self._reconcile()
                        next_tick = self._monotonic() + self.interval_seconds
                        continue
                    remaining = next_tick - self._monotonic()
                    if remaining <= 0:
                        self.submit('scheduled')
                        next_tick = self._monotonic() + self.interval_seconds
                        continue
                    attempt = 0
                    with self._lock:
                        self._worker_error = None
                    self._wake.wait(min(remaining, 60))
                    self._wake.clear()
                except (sqlite3.Error, OSError) as exc:
                    attempt += 1
                    if not self._retry(exc, attempt):
                        break
        except Exception as exc:
            with self._lock:
                self._worker_error = f'{type(exc).__name__}: {exc}'[:400]
            self._trace('worker_failed', error=self._worker_error)
        finally:
            with self._lock:
                release_daemon_lock(self._lease)
                self._lease = None

    def stop(self, timeout=2):
        self._stop.set()
        self._wake.set()
        with self._lock:
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=max(0, float(timeout)))
        stopped = not thread or not thread.is_alive()
        return stopped
