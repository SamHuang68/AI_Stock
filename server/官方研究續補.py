"""在既有官方研究範圍內續補最近月份；不建立新的全歷史資料管線。"""
from datetime import date, datetime, timedelta
from pathlib import Path
import re
import threading
import time

import datastore
from daily_cache_jobs import Budget
from daily_quality import quality_evidence
from daemon_lock import acquire_daemon_lock, release_daemon_lock
from 公司行動更新 import PARSER_VERSION
from 台股交易參考 import trading_status, verified_sessions
from 台股日線 import TZ, seed_research


def _previous_month(day):
    return (day.replace(day=1) - timedelta(days=1)).replace(day=1)


def _candidates(db):
    """只有既有官方公司行動涵蓋已包含原始行情起點的研究股票。"""
    with datastore.read_snapshot(db) as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'bars', 'action_price_coverage'} <= tables:
            return []
        rows = conn.execute('''SELECT c.symbol,c.start_date,c.end_date,MIN(b.ts)
            FROM action_price_coverage c JOIN bars b ON b.symbol=c.symbol AND b.market=c.market
            WHERE c.market='TW' AND c.parser_version=? GROUP BY c.symbol''', (PARSER_VERSION,)).fetchall()
    result = []
    for symbol, first, last, stamp in rows:
        if not re.fullmatch(r'\d{4}', symbol):
            continue
        try:
            start, end = date.fromisoformat(first), date.fromisoformat(last)
            raw_first = datetime.fromtimestamp(stamp, TZ).date()
        except (ValueError, TypeError, OverflowError, OSError) as exc:
            raise ValueError('既有官方研究日期無效，未啟動自動續補：' + symbol) from exc
        if start <= raw_first <= end:
            result.append({'symbol': symbol, 'rawFirst': raw_first, 'actionEnd': end})
    return result


def _inspect(db, item, target):
    """原始月收據與公司行動分別核對，既有量價衝突標記保持原狀。"""
    first = max(_previous_month(target), item['rawFirst'])
    with datastore.read_snapshot(db) as conn:
        coverage = conn.execute('SELECT start_date,end_date,parser_version FROM action_price_coverage '
            'WHERE market=? AND symbol=?', ('TW', item['symbol'])).fetchone()
        valid = bool(coverage and coverage[2] == PARSER_VERSION
                     and coverage[0] <= item['rawFirst'].isoformat() <= coverage[1])
        if not valid:
            return {'complete': False, 'reason': '既有完整公司行動涵蓋已改變', 'blocked': True}
        end = date.fromisoformat(coverage[1])
        sessions = verified_sessions(first.isoformat(), target.isoformat(), connection=conn)
        expected = [day for day in (sessions or []) if trading_status(item['symbol'], day) is None]
        evidence = quality_evidence(conn, item['symbol'], board='TWSE',
                                    start=first.isoformat(), end=target.isoformat())
    missing = []
    for day in expected:
        item_quality = evidence.get(day, {})
        official = item_quality.get('officialPrices') or {}
        if (official.get('status') != 'verified' or not official.get('receiptIds')
                or not item_quality.get('rawPresent') or not item_quality.get('receiptComplete')
                or any(item_quality.get(key) for key in
                       ('sourceConflict', 'ambiguousSession', 'invalidObservation', 'invalidReceipt'))):
            missing.append(day)
    calendar_complete = bool(sessions and sessions[-1] == target.isoformat())
    current_start = target.replace(day=1)
    begin = min(current_start, end + timedelta(days=1)) if end < target else current_start
    if not calendar_complete:
        # 未核對日曆可能位於前月；只在原有兩個月界線內補足，不猜交易日。
        begin = min(begin, first)
    if missing:
        begin = min(begin, date.fromisoformat(missing[0]))
    begin = begin.replace(day=1)
    blocked = begin < _previous_month(target)
    complete = calendar_complete and not missing and end >= target
    return {'complete': complete, 'blocked': blocked, 'begin': begin.isoformat(),
            'actionThrough': end.isoformat(), 'receiptMissingDates': missing,
            'calendarComplete': calendar_complete,
            'reason': '舊缺口超過前月與當月，需明示區間續補' if blocked else
                      None if complete else '官方原始月收據或公司行動尚未涵蓋目標日'}


def refresh(db, day, *, now=None, previous_attempts=None, previous_pending=None,
            budget_seconds=60, request_limit=20):
    """共用最多六十秒／二十請求；同一資料庫不重入、不另起下載程序。"""
    if (not 0 < budget_seconds <= 60 or type(request_limit) is not int
            or not 1 <= request_limit <= 20):
        raise ValueError('官方研究續補上限為六十秒及二十個來源請求')
    target = date.fromisoformat(day)
    now = now or datetime.now(TZ)
    if target != now.astimezone(TZ).date() or now.astimezone(TZ).hour < 18:
        return {'status': 'partial', 'results': {}, 'pendingSymbols': [], 'attemptedAt': {},
                'reason': '官方研究續補只在當日十八時後處理完整交易日', 'sourceRequests': 0}
    db = Path(db).resolve()
    if not db.is_file():
        return {'status': 'completed', 'results': {}, 'pendingSymbols': [], 'attemptedAt': {},
                'reason': '沒有既有官方研究資料庫，不建立資料庫或歷史', 'sourceRequests': 0}
    attempts = dict(previous_attempts or {})
    result = {'status': 'partial', 'results': {}, 'pendingSymbols': [],
              'attemptedAt': attempts, 'sourceRequests': 0,
              'scope': '已建立完整官方涵蓋的研究股票；最多前月與當月'}
    lock = acquire_daemon_lock('official-research-extension', lock_dir=db.parent / 'runtime_locks')
    if lock is None:
        result['reason'] = '既有官方研究續補仍在執行，不重啟或建立第二份工作'
        return result
    budget = Budget(threading.Event(), seconds=budget_seconds, requests=request_limit)
    try:
        budget.check()
        candidates = _candidates(db)
        pending = set(previous_pending or [])
        def order(item):
            value = attempts.get(item['symbol'])
            return (item['symbol'] not in pending, value if isinstance(value, (int, float)) else 0,
                    item['symbol'])
        candidates.sort(key=order)
        for index, item in enumerate(candidates):
            symbol = item['symbol']
            try:
                budget.check()
                before = _inspect(db, item, target)
                budget.check()
                if before['complete']:
                    result['results'][symbol] = {'status': 'completed', 'reused': True, **before}
                    continue
                if before.get('blocked'):
                    result['results'][symbol] = {'status': 'partial', **before}
                    result['pendingSymbols'].append(symbol)
                    continue
                if budget.used >= request_limit:
                    raise TimeoutError('本次官方研究續補已達來源請求上限')
                attempts[symbol] = time.time()
                seeded = seed_research(db, symbol, now=now, begin=date.fromisoformat(before['begin']),
                                       fetch=budget.get_json, check=budget.check)
                budget.check()
                after = _inspect(db, item, target)
                budget.check()
                result['results'][symbol] = {'status': 'completed' if after['complete'] else 'partial',
                    'reused': False, **after, 'seedQuality': seeded.get('quality'),
                    'seedQualityComplete': seeded.get('qualityComplete'),
                    'fetchedMonths': seeded.get('fetchedMonths'), 'reusedMonths': seeded.get('reusedMonths')}
                if not after['complete']:
                    result['pendingSymbols'].append(symbol)
            except TimeoutError as exc:
                result['results'][symbol] = {'status': 'pending', 'reason': str(exc), 'error': type(exc).__name__}
                result['pendingSymbols'].extend(row['symbol'] for row in candidates[index:])
                break
            except Exception as exc:
                result['results'][symbol] = {'status': 'partial', 'reason': str(exc)[:240], 'error': type(exc).__name__}
                result['pendingSymbols'].append(symbol)
        result['pendingSymbols'] = sorted(set(result['pendingSymbols']))
        result['status'] = 'partial' if result['pendingSymbols'] else 'completed'
        return result
    finally:
        result['sourceRequests'] = budget.used
        release_daemon_lock(lock)
