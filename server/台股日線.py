"""官方台股日線更新：日期契約、逐日原子寫入、來源與品質紀錄。"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sqlite3
from contextlib import closing
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen

try:
    from . import datastore
    from .daemon_lock import acquire_daemon_lock, release_daemon_lock
    from .jsonl_trace import append_jsonl
except ImportError:
    import datastore
    from daemon_lock import acquire_daemon_lock, release_daemon_lock
    from jsonl_trace import append_jsonl

TZ = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]
CODE = re.compile(r'^(?:[1-9]\d{3}[A-Z]?|00\d{2,4}[A-Z]?|9\d{5})$')
_last_request = 0.0


def numeric(value: object, *, positive: bool = False) -> float | None:
    try:
        result = float(str(value).replace(',', '').strip())
        return result if math.isfinite(result) and (result > 0 if positive else result >= 0) else None
    except (TypeError, ValueError):
        return None


def stamp(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time(), TZ).replace(hour=9).timestamp())


def get_json(url: str, trace=None) -> tuple[object, str]:
    global _last_request
    for attempt in range(3):
        time.sleep(max(0, 1.2 - (time.monotonic() - _last_request)))
        _last_request = time.monotonic()
        started = time.monotonic()
        try:
            with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}), timeout=25) as response:
                raw = response.read()
            value = json.loads(raw)
            digest = hashlib.sha256(raw).hexdigest()
            if trace:
                trace('來源完成', url=url, bytes=len(raw), elapsedMs=round((time.monotonic() - started) * 1000), sourceHash=digest)
            return value, digest
        except Exception as exc:
            if trace:
                trace('來源失敗', url=url, attempt=attempt + 1, error=type(exc).__name__)
            if attempt == 2:
                raise
            time.sleep(10 * (attempt + 1))
    raise RuntimeError('來源未回傳資料')


def calendar(year: int, fetch=get_json) -> tuple[set[date], set[date]]:
    try:
        data, _ = fetch('https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?response=json&date=' + str(year) + '0101')
    except Exception:
        data = None
    if isinstance(data, dict) and data.get('data'):
        records = data['data']
        closed, opened = set(), set()
        for row in records:
            # 日期欄位以實際欄位名稱解讀，不依賴展示順序。
            fields = data.get('fields', [])
            item = dict(zip(fields, row))
            raw_day = str(item.get('日期', ''))
            if re.fullmatch(r'\d{4}-\d{2}-\d{2}', raw_day):
                day = date.fromisoformat(raw_day)
                if day.year != year:
                    raise ValueError('官方休市資料年度不符')
                text = ' '.join(map(str, row))
                (opened if '開始交易' in text or '最後交易' in text or '補行交易' in text else closed).add(day)
                continue
            match = re.search(r'(\d{1,2})月(\d{1,2})日', raw_day)
            if not match:
                raise ValueError('官方開休市日期格式無法辨識')
            day = date(year, int(match[1]), int(match[2]))
            text = ' '.join(map(str, row))
            (opened if '開始交易' in text or '最後交易' in text or '補行交易' in text else closed).add(day)
        return closed, opened
    # OpenAPI 明確包含年度；只接受要求年度，禁止用今年假日推估別年。
    data, _ = fetch('https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule')
    if not isinstance(data, list):
        raise ValueError('官方開休市資料無效')
    closed, opened = set(), set()
    for row in data:
        raw = str(row.get('Date', ''))
        if not re.fullmatch(r'\d{7}', raw) or int(raw[:3]) + 1911 != year:
            continue
        day = date(year, int(raw[3:5]), int(raw[5:7]))
        text = str(row.get('Name', '')) + str(row.get('Description', ''))
        (opened if '開始交易' in text or '最後交易' in text or '補行交易' in text else closed).add(day)
    if not closed:
        raise ValueError('官方休市資料年度不足')
    return closed, opened


def stored_calendar(db: Path, year: int, fetch=get_json) -> tuple[set[date], set[date]]:
    """當年度每七日重核；過去年度沿用已核對版本，不刷新快取時間。"""
    now = datetime.now(TZ)
    with closing(sqlite3.connect(db)) as conn:
        row = conn.execute('SELECT closed,opened,refreshed_at FROM calendar_years WHERE year=?', (year,)).fetchone()
    if row and (year < now.year or now - datetime.fromisoformat(row[2]) <= timedelta(days=7)):
        return {date.fromisoformat(d) for d in json.loads(row[0])}, {date.fromisoformat(d) for d in json.loads(row[1])}
    closed, opened = calendar(year, fetch)
    save_calendar(db, year, closed, opened)
    return closed, opened


def latest_session(now: datetime, closed: set[date], opened: set[date]) -> date:
    local = now.astimezone(TZ)
    # 完整日成交資料採保守 18:00 截點；早晨一律以前一個完整交易日為目標。
    day = local.date() if local.hour >= 18 else local.date() - timedelta(days=1)
    for _ in range(30):
        if day not in closed and (day.weekday() < 5 or day in opened):
            return day
        day -= timedelta(days=1)
    raise ValueError('無法確認最近完整交易日')


def save_calendar(db: Path, year: int, closed: set[date], opened: set[date]) -> None:
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute('INSERT OR REPLACE INTO calendar_years VALUES(?,?,?,?)',
                     (year, json.dumps(sorted(d.isoformat() for d in closed)), json.dumps(sorted(d.isoformat() for d in opened)), datetime.now(timezone.utc).isoformat()))
        day = date(year, 1, 1)
        sessions = []
        while day.year == year:
            if day not in closed and (day.weekday() < 5 or day in opened):
                sessions.append((day.isoformat(), 'TWSE開休市'))
            day += timedelta(days=1)
        conn.execute('DELETE FROM market_sessions WHERE session_date BETWEEN ? AND ?', (f'{year}-01-01', f'{year}-12-31'))
        conn.executemany('INSERT OR REPLACE INTO market_sessions VALUES(?,?)', sessions)
        for month, through, actual in conn.execute('SELECT month,observed_through,dates FROM session_months WHERE month LIKE ?', (str(year) + '%',)).fetchall():
            conn.execute('DELETE FROM market_sessions WHERE session_date BETWEEN ? AND ?', (month + '-01', through))
            conn.executemany('INSERT OR REPLACE INTO market_sessions VALUES(?,?)', [(d, 'TWSE實際成交日') for d in json.loads(actual)])


def reconcile_sessions(db: Path, begin: date, end: date, fetch=get_json) -> set[date]:
    """使用官方大盤成交日期修正已發生的臨時休市；尚無後續證據的日期保持待核對。"""
    actual = set()
    month = begin.replace(day=1)
    while month <= end:
        next_month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
        with closing(sqlite3.connect(db)) as conn:
            cached = conn.execute('SELECT observed_through,dates FROM session_months WHERE month=?', (month.strftime('%Y-%m'),)).fetchone()
            expected_end = conn.execute('SELECT MAX(session_date) FROM market_sessions WHERE session_date>=? AND session_date<? AND session_date<=?', (month.isoformat(), next_month.isoformat(), end.isoformat())).fetchone()[0]
        if cached and expected_end and cached[0] >= expected_end:
            actual.update(date.fromisoformat(d) for d in json.loads(cached[1]) if d <= end.isoformat())
            month = next_month
            continue
        data, digest = fetch('https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?response=json&date=' + month.strftime('%Y%m%d'))
        if data.get('stat') != 'OK' or data.get('date') != month.strftime('%Y%m%d') or data.get('fields', [])[:1] != ['日期']:
            raise ValueError('實際交易日期尚未核對')
        dates = []
        for row in data.get('data', []):
            y, m, d = map(int, str(row[0]).split('/'))
            day = date(y + 1911, m, d)
            if day.replace(day=1) != month:
                raise ValueError('實際交易日期月份不符')
            if day <= end:
                dates.append(day)
        if not dates or len(set(dates)) != len(dates):
            raise ValueError('實際交易日期不足或重複')
        with closing(sqlite3.connect(db)) as conn, conn:
            conn.execute('DELETE FROM market_sessions WHERE session_date BETWEEN ? AND ?', (month.isoformat(), max(dates).isoformat()))
            conn.executemany('INSERT OR REPLACE INTO market_sessions VALUES(?,?)', [(d.isoformat(), 'TWSE實際成交日') for d in dates])
            conn.execute('INSERT OR REPLACE INTO session_months VALUES(?,?,?,?)', (month.strftime('%Y-%m'), max(dates).isoformat(), json.dumps([d.isoformat() for d in dates]), digest))
        actual.update(dates)
        month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
    return actual


def refresh_actions(db: Path, symbol: str, begin: date, end: date, fetch=get_json) -> int:
    """三種官方事件全數核對成功才延長涵蓋區間。"""
    actions = []
    endpoints = [('exRight/TWT49U', '資料日期', '除權息'),
                 ('reducation/TWTAUU', '恢復買賣日期', '減資'),
                 ('change/TWTB8U', '恢復買賣日期', '面額變更')]
    for year in range(begin.year, end.year + 1):
        first, last = max(begin, date(year, 1, 1)), min(end, date(year, 12, 31))
        for route, date_field, kind in endpoints:
            # 證交所公告頁亦由官方 wwwc 站提供；此站歷史範圍查詢已核對可用。
            url = 'https://wwwc.twse.com.tw/rwd/zh/' + route + '?startDate=' + first.strftime('%Y%m%d') + '&endDate=' + last.strftime('%Y%m%d') + '&response=json'
            data, _ = fetch(url)
            if data.get('stat') == '很抱歉，沒有符合條件的資料!':
                continue
            if data.get('stat') != 'OK' or not all(k in data.get('fields', []) for k in (date_field, '股票代號')):
                raise ValueError(kind + '資料尚未完整核對')
            for values in data.get('data', []):
                row = dict(zip(data['fields'], values))
                if str(row['股票代號']).strip() != symbol:
                    continue
                parts = list(map(int, re.findall(r'\d+', str(row[date_field]))))
                if len(parts) != 3:
                    raise ValueError('公司行動日期無法辨識')
                day = date(parts[0] + (1911 if parts[0] < 1911 else 0), parts[1], parts[2])
                if not first <= day <= last:
                    raise ValueError('公司行動回傳超出查詢日期')
                actions.append(('TW', symbol, day.isoformat(), kind, 'TWSE'))
    with closing(sqlite3.connect(db)) as conn, conn:
        prior = conn.execute('SELECT start_date,end_date FROM action_coverage WHERE market=? AND symbol=?', ('TW', symbol)).fetchone()
        coverage_begin = begin.isoformat()
        if prior and date.fromisoformat(prior[1]) + timedelta(days=1) >= begin and prior[0] <= coverage_begin:
            coverage_begin = prior[0]
        conn.execute('DELETE FROM corporate_actions WHERE market=? AND symbol=? AND session_date BETWEEN ? AND ?', ('TW', symbol, begin.isoformat(), end.isoformat()))
        conn.executemany('INSERT OR REPLACE INTO corporate_actions VALUES(?,?,?,?,?)', actions)
        conn.execute('INSERT OR REPLACE INTO action_coverage VALUES(?,?,?,?,?)', ('TW', symbol, coverage_begin, end.isoformat(), 'TWSE除權息、減資、面額變更'))
    return len(actions)


def parse_daily(data: dict, exchange: str, day: date) -> list[dict]:
    if str(data.get('date', '')) != day.strftime('%Y%m%d') or str(data.get('stat', '')).lower() != 'ok':
        raise ValueError('官方資料日期或狀態不符，禁止寫入')
    names = {'TWSE': ('證券代號', '證券名稱', '開盤價', '最高價', '最低價', '收盤價'),
             'TPEX': ('代號', '名稱', '開盤', '最高', '最低', '收盤')}[exchange]
    tables = [t for t in data.get('tables', []) if t.get('data') and all(n in t.get('fields', []) for n in (*names, '成交股數'))]
    if not tables:
        raise ValueError('官方日線欄位不足')
    records, seen = [], set()
    for table in tables:
        for values in table['data']:
            row = dict(zip(table['fields'], values))
            code = str(row[names[0]]).strip()
            if not CODE.fullmatch(code):
                continue
            if code in seen:
                raise ValueError('官方同日代號重複')
            seen.add(code)
            prices = [numeric(row[n], positive=True) for n in names[2:]]
            volume = numeric(row['成交股數'])
            issues = []
            if any(v is None for v in prices):
                issues.append('價格缺值或無成交')
            elif not prices[2] <= min(prices[0], prices[3]) <= max(prices[0], prices[3]) <= prices[1]:
                issues.append('開高低收邊界無效')
            if volume is None or volume <= 0:
                issues.append('成交量缺值或無成交')
            records.append({'symbol': code, 'name': str(row[names[1]]), 'prices': prices, 'volume': volume, 'issues': issues})
    return records


def import_day(db: Path, exchange: str, day: date, records: list[dict], digest: str, *, min_rows: int = 500) -> None:
    if len(records) < min_rows:
        raise ValueError('官方全市場資料筆數不足，保留原資料')
    retrieved = datetime.now(timezone.utc).isoformat()
    ts = stamp(day)
    with closing(sqlite3.connect(db, timeout=30)) as conn, conn:
        previous = conn.execute('SELECT row_count FROM daily_imports WHERE exchange=? ORDER BY session_date DESC LIMIT 1', (exchange,)).fetchone()
        if previous and len(records) < previous[0] * 0.9:
            raise ValueError('全市場筆數異常下降，保留原資料')
        for record in records:
            # 清除同交易日不同來源時間戳的重複列，範圍只限這筆證券。
            start = stamp(day) - 9 * 3600
            conn.execute('DELETE FROM bars WHERE market=? AND symbol=? AND ts>=? AND ts<? AND ts<>?', ('TW', record['symbol'], start, start + 86400, ts))
            conn.execute('DELETE FROM bar_quality WHERE market=? AND symbol=? AND session_date=? AND ts<>?', ('TW', record['symbol'], day.isoformat(), ts))
        conn.executemany('INSERT OR REPLACE INTO bars VALUES(?,?,?,?,?,?,?,?)',
                         [(r['symbol'], 'TW', ts, *r['prices'], r['volume']) for r in records])
        conn.executemany('INSERT OR REPLACE INTO bar_quality VALUES(?,?,?,?,?,?,?,?,?,?)',
                         [('TW', r['symbol'], ts, day.isoformat(), exchange, '股', '原始價格', json.dumps(r['issues'], ensure_ascii=False), retrieved, digest) for r in records])
        conn.executemany('INSERT INTO meta VALUES(?,?,?,?) ON CONFLICT(market,symbol) DO UPDATE SET name=excluded.name,last_update=excluded.last_update',
                         [(r['symbol'], 'TW', r['name'], int(time.time())) for r in records])
        conn.execute('INSERT OR REPLACE INTO daily_imports VALUES(?,?,?,?,?)', (exchange, day.isoformat(), len(records), digest, retrieved))


def run_update(db: Path, *, start: date | None = None, now: datetime | None = None, fetch=get_json, refresh_existing: bool = False) -> dict:
    db = db.resolve()
    lock = acquire_daemon_lock('official-daily-bars', lock_dir=db.parent / 'runtime_locks')
    if lock is None:
        return {'ok': False, 'status': '更新進行中', 'database': str(db)}
    run_id = uuid.uuid4().hex
    trace_path = db.parent / 'daily_bars_update.jsonl'
    def trace(event, **fields):
        append_jsonl(str(trace_path), {'at': datetime.now(timezone.utc).isoformat(), 'runId': run_id, 'event': event, **fields}, max_bytes=4_000_000, tail_lines=2000)
    state = {'ok': False, 'runId': run_id, 'startedAt': datetime.now(timezone.utc).isoformat(), 'status': '更新中', 'database': str(db), 'completedDays': [], 'failures': []}
    def save():
        with closing(sqlite3.connect(db, timeout=30)) as conn, conn:
            conn.execute('INSERT OR REPLACE INTO daily_update_state VALUES(1,?)', (json.dumps(state, ensure_ascii=False),))
    try:
        old_path = datastore.DB_PATH
        try:
            datastore.DB_PATH = str(db)
            datastore.init_db()
        finally:
            datastore.DB_PATH = old_path
        save()
        trace('工作開始', database=str(db))
        now = now or datetime.now(TZ)
        closed, opened = stored_calendar(db, now.astimezone(TZ).year, fetch)
        previous_closed, previous_opened = stored_calendar(db, now.astimezone(TZ).year - 1, fetch)
        closed |= previous_closed
        opened |= previous_opened
        target = latest_session(now, closed, opened)
        state['expectedSession'] = target.isoformat()
        with closing(sqlite3.connect(db)) as conn, conn:
            imported = {(r[0], r[1]) for r in conn.execute('SELECT exchange,session_date FROM daily_imports')}
        # 初次補近四個月，之後保留已開始區間，確保失敗日期會再次嘗試。
        first = start or (date.fromisoformat(min(day for _, day in imported)) if imported else target - timedelta(days=120))
        first = min(first, target)
        for year in range(first.year, target.year):
            old_closed, old_opened = stored_calendar(db, year, fetch)
            closed |= old_closed
            opened |= old_opened
        actual = reconcile_sessions(db, first, target, fetch)
        # 只有已公布後續交易日的缺日才可視為休市；最新應有日未公布仍須失敗提示。
        confirmed_through = max(actual)
        for offset in range((target - first).days + 1):
            if len(state['failures']) >= 3:
                break
            day = first + timedelta(days=offset)
            if day in closed or (day.weekday() >= 5 and day not in opened):
                continue
            if day < confirmed_through and day not in actual:
                continue
            with closing(sqlite3.connect(db)) as conn, conn:
                conn.execute('INSERT OR REPLACE INTO market_sessions VALUES(?,?)', (day.isoformat(), 'TWSE開休市'))
            for exchange in ('TWSE', 'TPEX'):
                if not refresh_existing and (exchange, day.isoformat()) in imported:
                    continue
                url = ('https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&type=ALLBUT0999&date=' + day.strftime('%Y%m%d') if exchange == 'TWSE'
                       else 'https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?response=json&date=' + day.strftime('%Y%%2F%m%%2F%d'))
                try:
                    data, digest = fetch(url, trace) if fetch is get_json else fetch(url)
                    records = parse_daily(data, exchange, day)
                    import_day(db, exchange, day, records, digest)
                    state['completedDays'].append({'exchange': exchange, 'date': day.isoformat(), 'rows': len(records)})
                    trace('資料已提交', exchange=exchange, sessionDate=day.isoformat(), rows=len(records), sourceHash=digest)
                except Exception as exc:
                    state['failures'].append({'exchange': exchange, 'date': day.isoformat(), 'reason': str(exc)[:180]})
                    trace('日期更新失敗', exchange=exchange, sessionDate=day.isoformat(), error=type(exc).__name__)
                save()
                if fetch is get_json:
                    time.sleep(0.4)
        with closing(sqlite3.connect(db)) as conn, conn:
            latest = dict(conn.execute('SELECT exchange,MAX(session_date) FROM daily_imports GROUP BY exchange').fetchall())
        state['latestSessions'] = latest
        # 已建立的研究股票每日延長公司行動核對區間，無完整核對則保持舊涵蓋日期。
        with closing(sqlite3.connect(db)) as conn, conn:
            research = conn.execute("SELECT symbol,end_date FROM action_coverage WHERE market='TW'").fetchall()
        for symbol, end in research:
            if end < target.isoformat():
                try:
                    refresh_actions(db, symbol, date.fromisoformat(end) + timedelta(days=1), target, fetch)
                except Exception as exc:
                    state['failures'].append({'symbol': symbol, 'reason': str(exc)[:180]})
        state['ok'] = not state['failures'] and all(latest.get(ex) == target.isoformat() for ex in ('TWSE', 'TPEX'))
        state['status'] = '已更新' if state['ok'] else '資料不完整'
    except Exception as exc:
        state['status'] = '更新失敗'
        state['failures'].append({'reason': str(exc)[:180]})
    finally:
        state['finishedAt'] = datetime.now(timezone.utc).isoformat()
        try:
            save()
            trace('工作結束', ok=state['ok'], status=state['status'], failureCount=len(state['failures']))
        finally:
            release_daemon_lock(lock)
    return state


def seed_research(db: Path, symbol: str = '2330', years: int = 3, *, fetch=get_json) -> dict:
    """以官方月份資料補齊研究股票，另核對公司行動與完整交易日曆。"""
    if not re.fullmatch(r'\d{4}', symbol) or years not in range(1, 6):
        raise ValueError('研究回補只接受上市四碼股票與一至五年')
    now = datetime.now(TZ)
    old_path = datastore.DB_PATH
    lock = acquire_daemon_lock('official-daily-bars', lock_dir=db.parent / 'runtime_locks')
    if lock is None:
        raise RuntimeError('日線更新進行中，請稍後回補')
    try:
        datastore.DB_PATH = str(db)
        datastore.init_db()
        target = latest_session(now, *stored_calendar(db, now.year, fetch))
        start = date(target.year - years, target.month, 1)
        for year in range(start.year, target.year + 1):
            stored_calendar(db, year, fetch)
        reconcile_sessions(db, start, target, fetch)
        count = 0
        month = start
        while month <= target:
            next_month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
            with closing(sqlite3.connect(db)) as conn:
                expected = {r[0] for r in conn.execute('SELECT session_date FROM market_sessions WHERE session_date>=? AND session_date<? AND session_date<=?', (month.isoformat(), next_month.isoformat(), target.isoformat()))}
                verified = {r[0] for r in conn.execute("SELECT session_date FROM bar_quality WHERE market='TW' AND symbol=? AND source='TWSE' AND session_date>=? AND session_date<?", (symbol, month.isoformat(), next_month.isoformat()))}
            if expected and expected <= verified:
                count += len(expected)
                month = next_month
                continue
            url = 'https://www.twse.com.tw/exchangeReport/STOCK_DAY?response=json&date=' + month.strftime('%Y%m%d') + '&stockNo=' + symbol
            data, digest = fetch(url)
            if data.get('stat') != 'OK' or data.get('fields', [])[:7] != ['日期', '成交股數', '成交金額', '開盤價', '最高價', '最低價', '收盤價']:
                raise ValueError('官方個股月份資料缺失或欄位不符')
            for row in data['data']:
                y, m, d = map(int, row[0].split('/'))
                day = date(y + 1911, m, d)
                if not start <= day <= target or (day.year, day.month) != (month.year, month.month):
                    continue
                prices = [numeric(row[i], positive=True) for i in (3, 4, 5, 6)]
                datastore.upsert_bars(symbol, 'TW', [(stamp(day), *prices, numeric(row[1]))], source='TWSE', source_hash=digest)
                count += 1
            print('研究日線已回補：' + month.isoformat(), flush=True)
            month = date(month.year + (month.month == 12), month.month % 12 + 1, 1)
            if fetch is get_json:
                time.sleep(0.4)
        actions = refresh_actions(db, symbol, start, target, fetch)
        return {'ok': True, 'symbol': symbol, 'rows': count, 'start': start.isoformat(), 'end': target.isoformat(), 'actions': actions}
    finally:
        datastore.DB_PATH = old_path
        release_daemon_lock(lock)


def main() -> int:
    parser = argparse.ArgumentParser(description='更新最近完整交易日的上市、上櫃股票與 ETF 日線')
    parser.add_argument('--database', type=Path, default=Path(datastore.DB_PATH))
    parser.add_argument('--start', type=date.fromisoformat)
    parser.add_argument('--include-private', action='store_true')
    parser.add_argument('--seed-research', action='store_true')
    parser.add_argument('--refresh-existing', action='store_true', help='重新核對指定區間已匯入日期')
    args = parser.parse_args()
    paths = [args.database]
    if args.include_private:
        import os
        private = Path(os.environ.get('LOCALAPPDATA', '')) / 'StockTerminalPrivateWeb/current/data/market.db'
        if not private.is_file():
            raise SystemExit('Private Web 資料庫不存在，未執行更新')
        paths.append(private)
    results = [seed_research(path) if args.seed_research else run_update(path, start=args.start, refresh_existing=args.refresh_existing) for path in paths]
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if all(result['ok'] for result in results) else 1


if __name__ == '__main__':
    sys.exit(main())
