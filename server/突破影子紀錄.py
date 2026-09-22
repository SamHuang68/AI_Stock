"""日線更新完成後附加研究觀察；讀取研究頁不建立或覆寫紀錄。"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

try:
    from .台股日線 import TZ
except ImportError:
    from 台股日線 import TZ

SCHEMA = '''CREATE TABLE IF NOT EXISTS breakout_observations(
    symbol TEXT NOT NULL, session_date TEXT NOT NULL, rules_version TEXT NOT NULL,
    observed_at TEXT NOT NULL, input_digest TEXT NOT NULL, evidence TEXT NOT NULL,
    PRIMARY KEY(symbol, session_date, rules_version)
)'''


def append_observation(db: str | Path, result: dict, observed_at: datetime) -> bool:
    """僅接受最新完成交易日；相同代號、日期與版本保留第一次觀察。"""
    research = result.get('research') or {}
    latest = research.get('latest') or {}
    freshness = result.get('freshness') or {}
    day = latest.get('date')
    version = research.get('version')
    digest = latest.get('inputDigest')
    if observed_at.tzinfo is None:
        raise ValueError('影子紀錄須提供含時區的觀察時間')
    if not (freshness.get('fresh') and day == freshness.get('expectedSession')
            and day == result.get('asOf') and day <= observed_at.astimezone(TZ).date().isoformat()
            and version and digest and result.get('sym')):
        return False
    payload = json.dumps(latest, ensure_ascii=False, sort_keys=True, allow_nan=False)
    with closing(sqlite3.connect(db, timeout=30)) as conn, conn:
        conn.execute(SCHEMA)
        cursor = conn.execute('''INSERT OR IGNORE INTO breakout_observations
            VALUES(?,?,?,?,?,?)''', (result['sym'], day, version, observed_at.isoformat(), digest, payload))
        return cursor.rowcount == 1


def record_daily(db: str | Path, *, now: datetime | None = None, observed_at: datetime | None = None) -> dict:
    """沿用已建立公司行動涵蓋的研究股票，無遠端請求、無歷史補造。"""
    try:
        from .K線事件 import report
    except ImportError:
        from K線事件 import report
    now = now or datetime.now(TZ)
    with closing(sqlite3.connect(db, timeout=30)) as conn:
        symbols = [r[0] for r in conn.execute("SELECT symbol FROM action_coverage WHERE market='TW' ORDER BY symbol")]
    added, failures = 0, []
    recorded_at = observed_at or datetime.now(TZ)
    for symbol in symbols:
        try:
            result = report(db, symbol, now=now, period='30d', include_execution=False)
            recorded_at = observed_at or datetime.now(TZ)
            added += int(append_observation(db, result, recorded_at))
            adjusted = result.get('research', {}).get('adjusted') or {}
            if adjusted.get('adjustmentEvidence', {}).get('coverage'):
                # 規則版本分開留存，原始模式的首次證據不因新增基準而覆寫。
                added += int(append_observation(db, {**result, 'research': adjusted}, recorded_at))
        except Exception as exc:
            failures.append({'symbol': symbol, 'reason': type(exc).__name__})
    return {'status': '紀錄不完整' if failures else '已檢查', 'checked': len(symbols),
            'added': added, 'failures': failures, 'observedAt': recorded_at.isoformat()}


def summary(db: str | Path, symbol: str, research: dict, as_of: str) -> dict:
    """使用唯讀 SQLite 連線；可查既有歷史紀錄，但不將重算當成前瞻。"""
    version = research.get('version')
    latest = research.get('latest') or {}
    base = {'status': '尚未建立影子紀錄', 'count': 0, 'asOf': None, 'observedAt': None,
            'rulesVersion': version, 'revised': False,
            'note': '日線更新完成後才記錄已建立公司行動涵蓋的研究股票；首次觀察不覆寫，不回填歷史前瞻績效。'}
    with closing(sqlite3.connect(Path(db).resolve().as_uri() + '?mode=ro', uri=True, timeout=15)) as conn:
        state_exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_update_state'").fetchone()
        if state_exists:
            state = conn.execute('SELECT payload FROM daily_update_state WHERE id=1').fetchone()
            if state:
                writer = json.loads(state[0]).get('researchShadow')
                if writer:
                    base['writer'] = writer
                    if writer.get('status') in ('紀錄失敗', '紀錄不完整'):
                        base['note'] += '最近寫入工作未完整完成，請檢查日線更新紀錄。'
        exists = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='breakout_observations'").fetchone()
        if not exists:
            return base
        count = conn.execute('SELECT COUNT(*) FROM breakout_observations WHERE symbol=? AND rules_version=? AND session_date<=?',
                             (symbol, version, as_of)).fetchone()[0]
        row = conn.execute('''SELECT session_date,observed_at,input_digest,evidence FROM breakout_observations
            WHERE symbol=? AND rules_version=? AND session_date<=? ORDER BY session_date DESC LIMIT 1''',
                           (symbol, version, as_of)).fetchone()
    if not row:
        return base
    revised = row[0] == latest.get('date') and row[2] != latest.get('inputDigest')
    return {**base, 'status': ('資料已修訂，保留原觀察' if revised else
                              '已記錄本交易日' if row[0] == latest.get('date') else '尚未記錄本交易日'),
            'count': count, 'asOf': row[0], 'observedAt': row[1], 'inputDigest': row[2],
            'revised': revised, 'evidence': json.loads(row[3])}
