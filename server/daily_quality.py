"""附加日線品質；首次價格保留，官方差異另存，不暗中切換價格基準。"""
import hashlib
import json
import math
import time
from datetime import datetime, timezone

SCHEMA = '''
CREATE TABLE IF NOT EXISTS bar_fetch_coverage(
 market TEXT NOT NULL,symbol TEXT NOT NULL,source TEXT NOT NULL,
 start_date TEXT NOT NULL,end_date TEXT NOT NULL,fetched_at REAL NOT NULL,
 PRIMARY KEY(market,symbol,source,start_date,end_date));
CREATE TABLE IF NOT EXISTS bar_quality(
 market TEXT NOT NULL,symbol TEXT NOT NULL,ts INTEGER NOT NULL,
 session_date TEXT NOT NULL,source TEXT NOT NULL,volume_unit TEXT NOT NULL,
 price_basis TEXT NOT NULL,issues TEXT NOT NULL,retrieved_at TEXT NOT NULL,
 source_hash TEXT NOT NULL,PRIMARY KEY(market,symbol,ts));
CREATE TABLE IF NOT EXISTS official_daily_observations(
 market TEXT NOT NULL,symbol TEXT NOT NULL,session_date TEXT NOT NULL,source TEXT NOT NULL,
 source_hash TEXT NOT NULL,payload TEXT NOT NULL,retrieved_at TEXT NOT NULL,
 PRIMARY KEY(market,symbol,session_date,source,source_hash));
CREATE TABLE IF NOT EXISTS daily_imports(
 exchange TEXT NOT NULL,session_date TEXT NOT NULL,row_count INTEGER NOT NULL,
 source_hash TEXT NOT NULL,imported_at TEXT NOT NULL,PRIMARY KEY(exchange,session_date));
CREATE TABLE IF NOT EXISTS daily_update_state(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS corporate_actions(
 market TEXT NOT NULL,symbol TEXT NOT NULL,session_date TEXT NOT NULL,kind TEXT NOT NULL,
 source TEXT NOT NULL,PRIMARY KEY(market,symbol,session_date,kind));
CREATE TABLE IF NOT EXISTS action_coverage(
 market TEXT NOT NULL,symbol TEXT NOT NULL,start_date TEXT NOT NULL,end_date TEXT NOT NULL,
 source TEXT NOT NULL,PRIMARY KEY(market,symbol));
CREATE TABLE IF NOT EXISTS market_sessions(session_date TEXT PRIMARY KEY,source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS calendar_years(
 year INTEGER PRIMARY KEY,closed TEXT NOT NULL,opened TEXT NOT NULL,refreshed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS session_months(
 month TEXT PRIMARY KEY,observed_through TEXT NOT NULL,dates TEXT NOT NULL,source_hash TEXT NOT NULL);
'''


def issues(row):
    result = []
    if any(v is None or not math.isfinite(v) or v <= 0 for v in row[1:5]):
        result.append('價格缺值或無效')
    elif not row[3] <= min(row[1], row[4]) <= max(row[1], row[4]) <= row[2]:
        result.append('開高低收邊界無效')
    if row[5] is None or not math.isfinite(row[5]) or row[5] <= 0:
        result.append('成交量缺值或無成交')
    return result


def store_official(conn, symbol, market, rows, source, source_hash, *, check=lambda: None):
    try:
        from .stock_signals import bar_date
    except ImportError:
        from stock_signals import bar_date
    if market != 'TW' or source not in ('TWSE', 'TPEX'):
        raise ValueError('官方台股品質僅接受 TWSE／TPEX 的 TW 日線')
    if not symbol:
        raise ValueError('官方證券代號不可為空')
    observed = datetime.now(timezone.utc).isoformat()
    existing = {}
    for row in conn.execute('SELECT ts,open,high,low,close,volume FROM bars WHERE market=? AND symbol=? ORDER BY ts', (market, symbol)):
        existing.setdefault(bar_date(row[0], market), []).append(row)
    accepted = 0
    for row in rows:
        check()
        if len(row) != 6 or not isinstance(row[0], (int, float)) or not math.isfinite(row[0]) or any(v is not None and (not isinstance(v, (int, float)) or not math.isfinite(v)) for v in row[1:]):
            raise ValueError('官方日線欄位無效；缺值須為 null')
        day = bar_date(row[0], market)
        if not day:
            raise ValueError('官方日線日期無效')
        payload = json.dumps(list(row), ensure_ascii=False, allow_nan=False)
        digest = source_hash or hashlib.sha256(payload.encode()).hexdigest()
        conn.execute('INSERT OR IGNORE INTO official_daily_observations VALUES(?,?,?,?,?,?,?)',
                     (market, symbol, day, source, digest, payload, observed))
        prior = existing.get(day, [])
        same = len(prior) == 1 and all((a is None and b is None) or (a is not None and b is not None and math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-5)) for a, b in zip(prior[0][1:], row[1:]))
        if prior and not same:
            # 官方資料與現有價格基準不同時不覆寫；兩份原始值都保留供後續核對。
            for old in prior:
                quality = conn.execute('SELECT issues FROM bar_quality WHERE market=? AND symbol=? AND ts=?', (market, symbol, old[0])).fetchone()
                reasons = sorted(set((json.loads(quality[0]) if quality else []) + ['官方來源與原始日線不同；原始值保留']))
                if quality:
                    # 舊價格與其來源雜湊一起保留；新觀測的來源、雜湊已獨立存於 observations。
                    conn.execute('UPDATE bar_quality SET issues=? WHERE market=? AND symbol=? AND ts=?',
                                 (json.dumps(reasons, ensure_ascii=False), market, symbol, old[0]))
                else:
                    conn.execute('INSERT INTO bar_quality VALUES(?,?,?,?,?,?,?,?,?,?)',
                                 (market, symbol, old[0], day, '來源修訂待核對', '未知', '原有價格基準',
                                  json.dumps(reasons, ensure_ascii=False), observed, ''))
            continue
        stored = prior[0] if same else row
        if not prior:
            conn.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)', (symbol, market, *row))
            existing[day] = [row]
        conn.execute('INSERT OR REPLACE INTO bar_quality VALUES(?,?,?,?,?,?,?,?,?,?)',
                     (market, symbol, stored[0], day, source, '股', '原始價格',
                      json.dumps(issues(row), ensure_ascii=False), observed, digest))
        accepted += 1
    if accepted:
        conn.execute('INSERT INTO meta VALUES(?,?,?,?) ON CONFLICT(market,symbol) DO UPDATE SET last_update=excluded.last_update',
                     (symbol, market, symbol, int(time.time())))
    check()
    return accepted
