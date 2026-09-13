"""補齊三合一結果欄位；觀察資料與使用者篩選條件分開處理。"""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

from jsonl_trace import append_jsonl
from 估值趨勢 import (PE_DATASETS, REVENUE_DATASETS, TZ_TPE, load_chip_snapshots,
                     number, parse_revenue, parse_valuation, source_date)

FIELDS = ('revYoy', 'per', 'yield', 'trustStreak', 'foreignStreak')


def trace(path, event, trace_id, **fields):
    try:
        append_jsonl(str(path), {'ts': datetime.now(TZ_TPE).isoformat(), 'event': event,
                                'correlationId': trace_id, **fields},
                     max_bytes=256 * 1024, tail_lines=400)
    except OSError:
        pass


def market_sessions(database, now=None):
    """只讀既有官方交易日曆；沒有最新日曆時不推算籌碼天數。"""
    from 台股日線 import latest_session
    now = (now or datetime.now(TZ_TPE)).astimezone(TZ_TPE)
    try:
        with closing(sqlite3.connect(Path(database).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
            rows = conn.execute('SELECT year,closed,opened,refreshed_at FROM calendar_years WHERE year IN (?,?)',
                                (now.year, now.year - 1)).fetchall()
            current = [row for row in rows if row[0] == now.year]
            if not current or now - datetime.fromisoformat(current[0][3]) > timedelta(days=7):
                return []
            closed = {datetime.fromisoformat(day).date() for row in rows for day in json.loads(row[1])}
            opened = {datetime.fromisoformat(day).date() for row in rows for day in json.loads(row[2])}
            expected = latest_session(now, closed, opened).isoformat()
            days = [row[0] for row in conn.execute(
                'SELECT session_date FROM market_sessions WHERE session_date<=? ORDER BY session_date DESC LIMIT 61',
                (expected,))]
            return list(reversed(days)) if days and days[0] == expected else []
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return []


def chip_fields(code, sessions, snapshots):
    """依來源日去重，缺日不跨接；只有連續觀察下限時另附標記。"""
    out = {'trustStreak': None, 'foreignStreak': None, 'fieldStatus': {}, 'chipAsOf': None}
    dated, conflicts = {}, set()
    undated = False
    for snapshot in snapshots.values():
        rec = snapshot.get(code)
        if not isinstance(rec, dict):
            continue
        dates = {source_date(rec.get(key)) for key in
                 ('sourceDate', 'tradingDate', 'tradeDate', 'sessionDate', 'session_date')}
        dates.discard(None)
        if len(dates) != 1:
            undated = True
            conflicts.update(dates)
            continue
        day = next(iter(dates))
        values = {key: number(rec.get(key)) for key in ('trust', 'foreign')}
        if day in dated and dated[day] != values:
            conflicts.add(day)
        dated[day] = values
    if sessions:
        out['chipAsOf'] = max((day for day in dated if day <= sessions[-1]), default=None)
    for field, key in (('trustStreak', 'trust'), ('foreignStreak', 'foreign')):
        value, count, complete = None, 0, False
        for day in reversed(sessions):
            current = None if day in conflicts else dated.get(day, {}).get(key)
            if current is None:
                break
            if value is None:
                value = 1 if current > 0 else -1 if current < 0 else 0
            if value == 0 or current * value <= 0:
                complete = True
                break
            count += 1
        out[field] = None if value is None else value * count
        out[field + 'Complete'] = complete
        if value is None:
            reason = ('官方交易日曆尚未更新' if not sessions else
                      '舊籌碼紀錄未保存來源交易日，連買天數不可判定' if undated and not dated else
                      '最新交易日缺少可核對的籌碼資料')
            out['fieldStatus'][field] = reason
        elif not complete:
            out['fieldStatus'][field] = f'已核對連續{count}個交易日；更早資料不足，顯示已觀察下限'
        else:
            out['fieldStatus'][field] = '已核對來源交易日；正數為連買、負數為連賣、零為當日買賣超零'
    return out


def enrich(record, *, lookup, monthly_revenue, sessions, snapshots):
    code = record['sym']
    out = {**record, **dict.fromkeys(FIELDS), 'fieldStatus': {}}
    ordinary = bool(re.fullmatch(r'[1-9]\d{3}', code))
    if ordinary:
        raw, dataset = None, None
        for dataset in PE_DATASETS:
            raw = lookup([dataset], code)
            if raw:
                break
        out.update(parse_valuation(raw, dataset if raw else None))
        if out['per'] is not None and out['per'] <= 0:
            out['per'] = None
        revenue = lookup(list(REVENUE_DATASETS), code)
        if parse_revenue(revenue)['revYoy'] is None:
            markets = ('otc', 'sii') if out.get('valuationSource') == 'TPEx peratio' else ('sii', 'otc')
            for market in markets:
                fallback = monthly_revenue(market, code)
                if parse_revenue(fallback)['revYoy'] is not None:
                    revenue = fallback
                    break
        out.update(parse_revenue(revenue))
    for field in ('revYoy', 'per', 'yield'):
        out['fieldStatus'][field] = (
            'ETF 等非普通股不適用公司營收與一般股票估值' if not ordinary else
            '官方資料尚缺或不適用' if out[field] is None else
            '資料期間：' + str((out.get('revenuePeriod') if field == 'revYoy' else out.get('valuationDate')) or '來源未附日期'))
    chip = chip_fields(code, sessions, snapshots)
    out['fieldStatus'].update(chip.pop('fieldStatus'))
    out.update(chip)
    return out


def matches(record, fund, chip):
    for raw, field, operator in ((fund.get('revYoyMin'), 'revYoy', 'min'),
                                 (fund.get('perMax'), 'per', 'max'),
                                 (fund.get('yieldMin'), 'yield', 'min'),
                                 (chip.get('trustBuyDays'), 'trustStreak', 'min'),
                                 (chip.get('foreignBuyDays'), 'foreignStreak', 'min')):
        if raw is None or raw == '':
            continue
        threshold, value = number(raw), number(record.get(field))
        if threshold is None or value is None:
            return False
        if field in ('trustStreak', 'foreignStreak') and value < 0 and record.get(field + 'Complete') is False:
            return False
        if operator == 'min' and value < threshold or operator == 'max' and value > threshold:
            return False
    return True


def enrich_results(records, fund, chip, *, lookup, monthly_revenue, database, chip_history_path,
                   trace_path, trace_id):
    sessions = market_sessions(database)
    if sessions:
        from chip_history_tracker import refresh_latest
        try:
            updated = refresh_latest(sessions[-1], directory=chip_history_path)
            trace(trace_path, '官方籌碼同步', trace_id, expectedSession=sessions[-1], updated=updated)
        except Exception as exc:
            trace(trace_path, '官方籌碼暫缺', trace_id, error=type(exc).__name__)
    snapshots = load_chip_snapshots(chip_history_path)
    trace(trace_path, '補齊欄位開始', trace_id, candidates=len(records), snapshots=len(snapshots),
          expectedSession=sessions[-1] if sessions else None)
    results = []
    available = dict.fromkeys(FIELDS, 0)
    for record in records:
        row = enrich(record, lookup=lookup, monthly_revenue=monthly_revenue,
                     sessions=sessions, snapshots=snapshots)
        for field in FIELDS:
            available[field] += row[field] is not None
        if matches(row, fund, chip):
            results.append({**row, 'revYoy': round(row['revYoy'], 1) if row['revYoy'] is not None else None})
    trace(trace_path, '補齊欄位完成', trace_id, candidates=len(records), matched=len(results), available=available)
    return results
