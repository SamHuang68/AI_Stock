"""已核對的公開交易參考；純本機讀取，不推論未收錄股票仍在交易。"""
import json
import sqlite3
import time as _time
from datetime import date, time, timedelta
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def references():
    return json.loads(Path(__file__).with_suffix('.json').read_text(encoding='utf-8'))


# JSON 只收錄人工核對的年度；之後的年度改讀市場資料庫內由 台股日線.stored_calendar 自動抓取的
# TWSE 官方開休市日曆（calendar_years），避免跨年後一律變成「未知」（審查 CAL-02）。
# 只用於 JSON 年度之後；更早的年度維持原行為，不改變既有歷史計算。
DB_CALENDAR_SOURCE = 'TWSE 開休市日曆（市場資料庫 calendar_years，自動更新）'
_DB_CALENDAR_TTL_SECONDS = 3600
_db_calendar_cache = {}


def _db_calendar(year):
    """回傳 (休市日集合, 補班日集合)；資料庫未收錄或內容矛盾時回 None。結果快取一小時。"""
    now = _time.monotonic()
    hit = _db_calendar_cache.get(year)
    if hit and hit[0] > now:
        return hit[1]
    value = None
    try:
        import datastore
        with datastore.read_snapshot() as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='calendar_years'").fetchone():
                row = conn.execute('SELECT closed,opened FROM calendar_years WHERE year=?', (year,)).fetchone()
                if row:
                    closed, opened = json.loads(row[0]), json.loads(row[1])
                    if not isinstance(closed, list) or not isinstance(opened, list):
                        raise ValueError('年度日曆內容不是日期清單')
                    closed = {date.fromisoformat(day) for day in closed}
                    opened = {date.fromisoformat(day) for day in opened}
                    if any(day.year != year for day in closed | opened) or closed & opened:
                        raise ValueError('年度日曆日期或開休市內容矛盾')
                    value = (frozenset(closed), frozenset(opened))
    except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
        from log_once import log_once
        log_once('tw-calendar-db', '資料庫交易日曆無法讀取：' + str(exc))
        value = None
    _db_calendar_cache[year] = (now + _DB_CALENDAR_TTL_SECONDS, value)
    return value


def _official_later_year(year):
    calendar_year = int(references()['calendar']['year'])
    return _db_calendar(year) if year > calendar_year else None


def calendar_covers(year):
    """該年度是否有官方日曆（JSON 已核對年度，或之後年度的資料庫官方日曆）。"""
    return str(year) == references()['calendar']['year'] or _official_later_year(int(year)) is not None


def session(day):
    day = date.fromisoformat(day) if isinstance(day, str) else day
    calendar = references()['calendar']
    official = _official_later_year(day.year) if str(day.year) != calendar['year'] else None
    if official is not None:
        closed, opened = official
        if day in closed:
            return {'status': 'closed', 'reason': '官方公告休市（TWSE 開休市日曆）', 'source': DB_CALENDAR_SOURCE}
        if day.weekday() >= 5 and day not in opened:
            return {'status': 'closed', 'reason': '週末休市', 'source': DB_CALENDAR_SOURCE}
        return {'status': 'scheduled', 'reason': '表定交易日；仍以當日日線確認是否實際交易', 'source': DB_CALENDAR_SOURCE}
    holiday = calendar['closed'].get(day.isoformat())
    if holiday:
        source = calendar.get('closedSources', {}).get(day.isoformat(), calendar['source'])
        return {'status': 'closed', 'reason': '官方公告休市：' + holiday, 'source': source}
    if day.weekday() >= 5:
        return {'status': 'closed', 'reason': '週末休市', 'source': calendar['source']}
    if str(day.year) == calendar['year']:
        return {'status': 'scheduled', 'reason': '表定交易日；仍以當日日線確認是否實際交易', 'source': calendar['source']}
    return {'status': 'unknown', 'reason': '尚無該年度官方日曆，不以平日推定已交易', 'source': None}


def is_closed_day(day):
    """週末或官方日曆收錄的休市日。未涵蓋年度只能依週末判斷（不以平日推定休市）。"""
    return session(day)['status'] == 'closed'


def last_close_day(local_now, close=time(13, 30)):
    """台北時間 local_now 當下「最近一個已收盤」的交易日；收盤前取前一日，並跳過週末與官方休市日。"""
    day = local_now.date()
    if local_now.time() < close:
        day -= timedelta(days=1)
    while is_closed_day(day):
        day -= timedelta(days=1)
    return day


def next_session_day(day):
    """day 之後的下一個交易日（跳過週末與官方休市日）。"""
    day = (date.fromisoformat(day) if isinstance(day, str) else day) + timedelta(days=1)
    while is_closed_day(day):
        day += timedelta(days=1)
    return day


def previous_session(day, *, session_lookup=None):
    """前一個已涵蓋的表定交易日；當日或回溯年度未知時停止。"""
    cursor = date.fromisoformat(day) if isinstance(day, str) else day
    lookup = session_lookup or session
    # 只看日曆狀態：跨年時改由下一年度的官方日曆接續（審查 CAL-02），未知年度仍停止。
    if lookup(cursor)['status'] == 'unknown':
        return None
    while True:
        cursor -= timedelta(days=1)
        state = lookup(cursor)['status']
        if state == 'unknown':
            return None
        if state == 'scheduled':
            return cursor.isoformat()


def instrument(symbol, as_of=None):
    item = references()['instruments'].get(symbol)
    if not item or (as_of and as_of < item['stopDate']):
        return None
    return {'symbol': symbol, **item}


def split_references(symbol):
    return references()['splits'].get(symbol, [])


def trading_status(symbol, day):
    """已知個股停止交易區間；未知主檔不冒稱官方確認可交易。"""
    ended = instrument(symbol, day)
    if ended:
        return ended
    for item in references().get('suspensions', {}).get(symbol, []):
        if item['from'] <= day < item['resumeDate']:
            return {'symbol': symbol, 'status': 'suspended', **item}
    return None


def eligible_bar(symbol, day):
    return session(day)['status'] != 'closed' and trading_status(symbol, day) is None


def continuous_segments(symbol, bars, sessions):
    """以基準交易日切段；缺日、停牌、終止後價格都不能壓縮成相鄰 K 棒。"""
    from stock_signals import complete_bar
    positions = {day: i for i, day in enumerate(sessions)}
    part, result = [], []
    for bar in bars:
        day = bar['date']
        # 來源可能在全市場休市日留存平價零量列；略過該列，不中斷真實交易日。
        if session(day)['status'] == 'closed':
            continue
        valid = day in positions and eligible_bar(symbol, day) and complete_bar(bar)
        adjacent = not part or positions.get(day) == positions[part[-1]['date']] + 1
        if part and adjacent:
            between = date.fromisoformat(part[-1]['date']) + timedelta(days=1)
            end = date.fromisoformat(day)
            while between < end:
                if session(between)['status'] == 'scheduled':
                    adjacent = False
                    break
                between += timedelta(days=1)
        if not valid or not adjacent:
            if part:
                result.append(part)
            part = []
        if valid:
            part.append(bar)
    if part:
        result.append(part)
    return result


def continuous_frames(symbol, frame, sessions):
    """研究共用的有效連續指標；切段後重新暖機，不沿用缺口前的指標。"""
    import stock_signals as ss
    bars = [{k: frame[k][i] for k in ('date', 'open', 'high', 'low', 'close', 'volume')}
            for i in range(len(frame['date']))]
    parts = continuous_segments(symbol, bars, sessions)
    if len(parts) == 1 and len(parts[0]) == len(bars):
        return [frame]
    chips = [{k: frame[k][i] for k in ('date', 'trust', 'foreign')}
             for i in range(len(frame['date']))]
    return [ss.build_frame(part, chips) for part in parts if len(part) >= ss.MIN_BARS]


def verified_sessions(start, end, *, connection=None, allow_partial=False):
    """唯讀日曆；預設要求完整涵蓋，明示部分模式只回最後已核對尾段。"""
    import sqlite3
    import datastore
    begin, stop = date.fromisoformat(str(start)[:10]), date.fromisoformat(str(end)[:10])
    if begin > stop:
        return []
    if connection is None:
        try:
            with datastore.read_snapshot() as conn:
                return verified_sessions(start, end, connection=conn, allow_partial=allow_partial)
        except (OSError, sqlite3.Error, ValueError, TypeError) as exc:
            from log_once import log_once
            log_once('research-session-calendar', '研究交易日曆無法核對：' + str(exc))
            return None
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    calendars, months = {}, {}
    if 'calendar_years' in tables:
        for year, closed, opened in connection.execute('SELECT year,closed,opened FROM calendar_years WHERE year BETWEEN ? AND ?', (begin.year, stop.year)):
            closed, opened = json.loads(closed), json.loads(opened)
            if not isinstance(closed, list) or not isinstance(opened, list):
                raise ValueError('年度日曆內容不是日期清單')
            if any(date.fromisoformat(day).year != year for day in closed + opened) or set(closed) & set(opened):
                raise ValueError('年度日曆日期或開休市內容矛盾')
            calendars[year] = (set(closed), set(opened))
    if 'session_months' in tables:
        for month, through, days in connection.execute('SELECT month,observed_through,dates FROM session_months WHERE month BETWEEN ? AND ?', (begin.isoformat()[:7], stop.isoformat()[:7])):
            days = json.loads(days)
            if not isinstance(days, list) or not str(through).startswith(month) or any(date.fromisoformat(day).isoformat()[:7] != month or day > through for day in days):
                raise ValueError('實際交易月份收據的日期無效')
            months[month] = (through, set(days))
    result, cursor = [], begin
    while cursor <= stop:
        day = cursor.isoformat()
        month = months.get(day[:7])
        if month and day <= month[0]:
            opened = day in month[1]
        elif cursor.year in calendars:
            closed, extra = calendars[cursor.year]
            opened = day not in closed and (cursor.weekday() < 5 or day in extra)
        elif str(cursor.year) == references()['calendar']['year']:
            opened = session(cursor)['status'] == 'scheduled'
        else:
            if not allow_partial:
                return None
            result = []
            cursor += timedelta(days=1)
            continue
        if opened:
            result.append(day)
        cursor += timedelta(days=1)
    return result
