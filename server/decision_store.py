"""決策發布的 SQLite 邊界；讀取不建表，發布意圖可跨程序恢復。"""
from __future__ import annotations

import copy
import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from log_once import log_once

TAIPEI = timezone(timedelta(hours=8))   # 台灣沒有日光節約時間


def freeze(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=str, allow_nan=False))


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def connect(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=FULL')
    return conn


def initialize(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS decision_history('
                 'id INTEGER PRIMARY KEY AUTOINCREMENT,as_of TEXT,created_at INTEGER,market TEXT,'
                 'input_hash TEXT UNIQUE,regime TEXT,confidence REAL,completeness REAL,context_json TEXT)')
    # decision_history 只是「最近 500 筆」的滾動緩衝（約 8.6 小時），不是歷史檔案；
    # 研究要查的逐日情境標籤另存在這張表，每個台北日期一列，不受 500 筆上限清除。
    conn.execute('CREATE TABLE IF NOT EXISTS decision_regime_daily('
                 'day TEXT PRIMARY KEY,as_of TEXT NOT NULL,regime TEXT,confidence REAL,completeness REAL)')
    conn.execute('CREATE TABLE IF NOT EXISTS decision_commits('
                 'revision INTEGER PRIMARY KEY AUTOINCREMENT,snapshot_id TEXT UNIQUE NOT NULL,'
                 'context_json TEXT NOT NULL,inputs_json TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS decision_publish_intents('
                 'sequence INTEGER PRIMARY KEY AUTOINCREMENT,snapshot_id TEXT UNIQUE NOT NULL,'
                 'payload_json TEXT NOT NULL)')
    conn.execute('CREATE TABLE IF NOT EXISTS decision_delivery_attempts('
                 'snapshot_id TEXT PRIMARY KEY,events_json TEXT NOT NULL,status TEXT NOT NULL,'
                 'result_json TEXT)')


def read_rows(path, sql, args=()):
    if not os.path.isfile(path):
        return []
    try:
        with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True, timeout=10)) as conn:
            return conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError as exc:
        if 'no such table' in str(exc):
            return []
        raise


def load(path, snapshot_id=None):
    sql = 'SELECT context_json,inputs_json,snapshot_id,revision FROM decision_commits'
    args = ()
    if snapshot_id:
        sql += ' WHERE snapshot_id=?'
        args = (snapshot_id,)
    rows = read_rows(path, sql + ' ORDER BY revision DESC LIMIT 1', args)
    if not rows:
        return None
    context, inputs = json.loads(rows[0][0]), json.loads(rows[0][1])
    if (not isinstance(context, dict) or not isinstance(inputs, dict) or
            context.get('snapshotId') != rows[0][2] or context.get('revision') != rows[0][3] or
            context.get('persistence') != 'committed' or not isinstance(inputs.get('pulse'), dict)):
        raise ValueError('已提交快照的識別或輸入不完整，停止恢復')
    return {'context': context, 'inputs': inputs}


def prepare(path, payload):
    with closing(connect(path)) as conn:
        with conn:
            initialize(conn)
            conn.execute('INSERT OR IGNORE INTO decision_publish_intents(snapshot_id,payload_json) VALUES(?,?)',
                         (payload['snapshotId'], encode(payload)))


def pending(path):
    return [json.loads(row[0]) for row in read_rows(path,
        'SELECT payload_json FROM decision_publish_intents ORDER BY sequence')]


def taipei_day(as_of):
    """as_of（UTC 的 Z 結尾、帶時區或無時區）→ (台北日期, UTC 標準字串)；無法解析回 None。無時區視為 UTC。"""
    try:
        moment = datetime.fromisoformat(str(as_of).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (moment.astimezone(TAIPEI).date().isoformat(),
            moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))


def save_regime_daily(conn, as_of, regime, confidence, completeness):
    """每個台北日期留最後一筆（as_of 最大者）；亂序到達的較舊紀錄不覆蓋較新的。"""
    parsed = taipei_day(as_of)
    if not parsed:
        log_once('決策每日情境', f'asOf 無法解析，略過每日情境紀錄：{as_of!r}')
        return
    day, utc = parsed
    conn.execute('INSERT INTO decision_regime_daily(day,as_of,regime,confidence,completeness) VALUES(?,?,?,?,?) '
                 'ON CONFLICT(day) DO UPDATE SET as_of=excluded.as_of,regime=excluded.regime,'
                 'confidence=excluded.confidence,completeness=excluded.completeness '
                 'WHERE excluded.as_of>=decision_regime_daily.as_of', (day, utc, regime, confidence, completeness))


def backfill_regime_daily(conn):
    """每日表還是空的時，用現有的 decision_history 補一次；之後由 save_history 維護。"""
    if conn.execute('SELECT 1 FROM decision_regime_daily LIMIT 1').fetchone():
        return
    for row in conn.execute('SELECT as_of,regime,confidence,completeness FROM decision_history ORDER BY id').fetchall():
        save_regime_daily(conn, *row)


def save_history(conn, context):
    regime = context.get('regime') or {}
    completeness = (context.get('dataQuality') or {}).get('completeness')
    inserted = conn.execute('INSERT OR IGNORE INTO decision_history('
                 'as_of,created_at,market,input_hash,regime,confidence,completeness,context_json) '
                 'VALUES(?,?,?,?,?,?,?,?)', (
                     context.get('asOf'), int(time.time()), context.get('market'), context['inputHash'],
                     regime.get('id'), regime.get('confidence'), completeness, encode(context))).rowcount
    if inserted:
        save_regime_daily(conn, context.get('asOf'), regime.get('id'), regime.get('confidence'), completeness)


def commit(path, context, inputs, published_at):
    """歷史、完整快照、輸入、水位與通知工作在同一交易完成。"""
    context = copy.deepcopy(context)
    with closing(connect(path)) as conn:
        with conn:
            initialize(conn)
            conn.execute('BEGIN IMMEDIATE')
            backfill_regime_daily(conn)
            row = conn.execute('SELECT context_json,inputs_json FROM decision_commits WHERE snapshot_id=?',
                               (context['snapshotId'],)).fetchone()
            if row:
                return {'context': json.loads(row[0]), 'inputs': json.loads(row[1])}
            cursor = conn.execute('INSERT INTO decision_commits(snapshot_id,context_json,inputs_json) VALUES(?,?,?)',
                                  (context['snapshotId'], '{}', encode(inputs)))
            context.update(revision=cursor.lastrowid, persistence='committed',
                           publicationStatus='accepted', publishedAt=published_at, viewScope='canonical')
            conn.execute('UPDATE decision_commits SET context_json=? WHERE revision=?',
                         (encode(context), context['revision']))
            save_history(conn, context)
            conn.execute('INSERT INTO decision_delivery_attempts(snapshot_id,events_json,status) VALUES(?,?,?)',
                         (context['snapshotId'], encode((context.get('earlyWarnings') or {}).get('newEvents') or []),
                          'disabled' if (context.get('earlyWarnings') or {}).get('enabled') is False else 'pending'))
            conn.execute('DELETE FROM decision_publish_intents WHERE snapshot_id=?', (context['snapshotId'],))
            conn.execute('DELETE FROM decision_history WHERE id NOT IN '
                         '(SELECT id FROM decision_history ORDER BY id DESC LIMIT 500)')
            conn.execute('DELETE FROM decision_commits WHERE revision NOT IN '
                         '(SELECT revision FROM decision_commits ORDER BY revision DESC LIMIT 500)')
            conn.execute("DELETE FROM decision_delivery_attempts WHERE status IN ('completed','disabled') AND snapshot_id NOT IN "
                         '(SELECT snapshot_id FROM decision_commits)')
    return {'context': context, 'inputs': copy.deepcopy(inputs)}


def claim_delivery(path):
    """每筆至多自動嘗試一次；中斷或失敗保留結果，避免重啟重複通知。"""
    with closing(connect(path)) as conn:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            row = conn.execute('SELECT snapshot_id,events_json FROM decision_delivery_attempts '
                               "WHERE status='pending' ORDER BY rowid LIMIT 1").fetchone()
            if not row:
                return None
            conn.execute("UPDATE decision_delivery_attempts SET status='attempted' WHERE snapshot_id=?", (row[0],))
            return row[0], json.loads(row[1])


def finish_delivery(path, snapshot_id, result, failed=False):
    with closing(connect(path)) as conn:
        with conn:
            conn.execute('UPDATE decision_delivery_attempts SET status=?,result_json=? WHERE snapshot_id=?',
                         ('failed' if failed else 'completed', encode(freeze(result)), snapshot_id))


def status(path):
    pending_count = read_rows(path, 'SELECT COUNT(*) FROM decision_publish_intents')
    delivery = dict(read_rows(path, 'SELECT status,COUNT(*) FROM decision_delivery_attempts GROUP BY status'))
    return {'pendingPublications': pending_count[0][0] if pending_count else 0, 'deliveryAttempts': delivery}
