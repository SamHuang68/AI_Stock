"""ETF 更新逐筆證據與結果；只寫共用歷史目錄下的診斷子目錄。"""
import datetime as dt
import json
import threading
import time
import uuid

import etf_paths
from atomic_store import atomic_write_json


def run_directory():
    return etf_paths.resolve_history_dir() / '_runs'


def report_path(run_id):
    return run_directory() / (uuid.UUID(str(run_id)).hex + '.json')


def read_report(run_id):
    path = report_path(run_id)
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else None


class UpdateTrace:
    def __init__(self, run_id=None):
        self.run_id = uuid.UUID(str(run_id)).hex if run_id else uuid.uuid4().hex
        self.started = time.time()
        self.directory = run_directory()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        atomic_write_json(report_path(self.run_id), {
            'runId': self.run_id, 'accepted': False, 'state': 'unfinished',
            'startedAt': self.started, 'finishedAt': None, 'durationSeconds': None,
            'message': '此作業尚未記錄終止結果；服務若已重啟，請檢查逐筆紀錄。',
        }, backup=False)

    def record(self, event, **fields):
        row = {'timestamp': dt.datetime.now(dt.timezone.utc).isoformat(),
               'component': 'etf_tracker', 'runId': self.run_id, 'event': event, **fields}
        with self.lock, (self.directory / (self.run_id + '.jsonl')).open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')

    def finish(self, *, accepted, **fields):
        report = {'runId': self.run_id, 'accepted': accepted,
                  'startedAt': self.started, 'finishedAt': time.time(),
                  'durationSeconds': round(time.time() - self.started, 2), **fields}
        self.record('terminal_success' if accepted else 'terminal_fail', **fields)
        atomic_write_json(report_path(self.run_id), report, backup=False)
        return report


def latest_report():
    directory = run_directory()
    if not directory.is_dir():
        return None
    paths = sorted(directory.glob('*.json'), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in paths:
        try:
            uuid.UUID(path.stem)
            value = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(value, dict) and 'accepted' in value:
                return value
        except (ValueError, OSError):
            continue
    return None
