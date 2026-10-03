"""四類官方公司行動核對；首次證據與後續修訂分開保存。"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

PARSER_VERSION = 'twse-reference-ratio-v1'
ROUTES = (
    ('exRight/TWT49U', '資料日期', '股票代號', '除權息', '除權息前收盤價', '除權息參考價'),
    ('reducation/TWTAUU', '恢復買賣日期', '股票代號', '減資', '停止買賣前收盤價格', '恢復買賣參考價'),
    ('change/TWTB8U', '恢復買賣日期', '股票代號', '面額變更', '停止買賣前收盤價格', '恢復買賣參考價'),
    ('split/TWTCAU', '恢復買賣日期', 'ETF代號', 'ETF分割', '停止買賣前收盤價格', '恢復買賣參考價'),
)
CONFLICT_REASON = '官方公司行動來源修訂尚未核對；首次證據與新收據均保留'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def ensure_action_schema(conn):
    """沿用現有比較表；所有新增表均在呼叫端交易內建立。"""
    statements = (
        '''CREATE TABLE IF NOT EXISTS action_price_evidence(
          market TEXT,symbol TEXT,session_date TEXT,kind TEXT,previous_close REAL,reference_price REAL,
          factor REAL,status TEXT,reason TEXT,source_url TEXT,source_hash TEXT,retrieved_at TEXT,
          parser_version TEXT,payload_json TEXT,PRIMARY KEY(market,symbol,session_date,kind))''',
        '''CREATE TABLE IF NOT EXISTS action_price_coverage(
          market TEXT,symbol TEXT,start_date TEXT,end_date TEXT,parser_version TEXT,sources_json TEXT,
          PRIMARY KEY(market,symbol))''',
        '''CREATE TABLE IF NOT EXISTS action_source_receipts(
          id TEXT PRIMARY KEY,market TEXT,symbol TEXT,route TEXT,start_date TEXT,end_date TEXT,
          source_hash TEXT,source_url TEXT,retrieved_at TEXT,parser_version TEXT,payload_json TEXT)''',
        '''CREATE TABLE IF NOT EXISTS action_price_revisions(
          id TEXT PRIMARY KEY,market TEXT,symbol TEXT,session_date TEXT,kind TEXT,observed_at TEXT,
          original_payload TEXT,revision_payload TEXT,source_receipt_id TEXT,reason TEXT)''',
    )
    for sql in statements:
        conn.execute(sql)


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(',', '').strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _merge(intervals):
    merged = []
    for begin, end in sorted(intervals):
        if merged and begin <= merged[-1][1] + timedelta(days=1):
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((begin, end))
    return merged


def _coverage(sources, begin, end):
    """逐路取涵蓋交集；只回傳包含本次範圍的連續分段。"""
    intervals = []
    for route, *_ in ROUTES:
        values = []
        for item in sources:
            if not isinstance(item, dict) or item.get('route') != route:
                continue
            try:
                first, last = date.fromisoformat(item['start']), date.fromisoformat(item['end'])
                parsed = urlparse(item['url'])
                observed = datetime.fromisoformat(item['retrievedAt'])
                valid = (first <= last and observed.tzinfo is not None and parsed.scheme == 'https'
                         and parsed.hostname in ('www.twse.com.tw', 'wwwc.twse.com.tw', 'openapi.twse.com.tw')
                         and parsed.path.endswith('/' + route.rsplit('/', 1)[-1])
                         and re.fullmatch(r'[0-9a-fA-F]{64}', item.get('sourceHash', ''))
                         and item.get('stat') in ('OK', '很抱歉，沒有符合條件的資料!'))
            except (KeyError, ValueError, TypeError):
                valid = False
            if valid:
                values.append((first, last))
        intervals.append(_merge(values))
    common = intervals[0]
    for values in intervals[1:]:
        common = _merge((max(a, c), min(b, d)) for a, b in common for c, d in values
                        if max(a, c) <= min(b, d))
    for first, last in common:
        if first <= begin <= end <= last:
            return first.isoformat(), last.isoformat()
    raise ValueError('四類官方來源收據未完整涵蓋本次查詢期間，未提交涵蓋')


def _response_period(data, first, last, kind):
    """官方各路回傳期間欄位不同；核對實際欄位，不能用請求值代填。"""
    expected_start, expected_end = first.strftime('%Y%m%d'), last.strftime('%Y%m%d')
    containers = [data]
    if 'params' in data:
        if not isinstance(data['params'], dict):
            raise ValueError(kind + '回應期間參數格式無效')
        containers.append(data['params'])
    starts = [item[key] for item in containers for key in ('strDate', 'startDate') if key in item]
    ends = [item['endDate'] for item in containers if 'endDate' in item]
    if any(value != expected_start for value in starts) or any(value != expected_end for value in ends):
        raise ValueError(kind + '回應查詢期間與請求不符')
    if data.get('stat') == 'OK' and (not starts or not ends):
        raise ValueError(kind + '回應缺少可核對的查詢起訖，未提交涵蓋')


def _meaning(row):
    """不同查詢範圍、回應雜湊或取得時間本身不代表事件數值修訂。"""
    payload = json.loads(row[13])
    return list(row[2:9]) + [row[12], dict(zip(payload['fields'], payload['row']))]


def refresh_actions(db, symbol, begin, end, fetch, check=lambda: None):
    if begin > end or not re.fullmatch(r'\d{4,6}[A-Z]?', symbol):
        raise ValueError('公司行動查詢標的或日期範圍無效')
    evidence, receipts, seen = [], [], set()
    for year in range(begin.year, end.year + 1):
        first, last = max(begin, date(year, 1, 1)), min(end, date(year, 12, 31))
        for route, date_field, code_field, kind, before_field, after_field in ROUTES:
            check()
            url = ('https://wwwc.twse.com.tw/rwd/zh/' + route + '?startDate=' + first.strftime('%Y%m%d')
                   + '&endDate=' + last.strftime('%Y%m%d') + '&response=json')
            response = fetch(url)
            data, source_hash = response
            observed = datetime.now(timezone.utc).isoformat()
            check()
            if not isinstance(data, dict) or not isinstance(source_hash, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', source_hash):
                raise ValueError(kind + '來源格式或雜湊無效')
            _response_period(data, first, last, kind)
            receipt = {'year': year, 'route': route, 'start': first.isoformat(), 'end': last.isoformat(),
                       'stat': data.get('stat'), 'sourceHash': source_hash, 'url': url, 'retrievedAt': observed}
            receipt_id = hashlib.sha256(encoded([symbol, url, source_hash, PARSER_VERSION]).encode()).hexdigest()
            receipts.append((receipt_id, receipt, encoded(data)))
            if data.get('stat') == '很抱歉，沒有符合條件的資料!':
                if data.get('data'):
                    raise ValueError(kind + '空集合狀態與資料矛盾')
                continue
            fields = data.get('fields')
            required = [date_field, code_field, before_field, after_field]
            if kind == '除權息':
                required.append('權/息')
            if kind == 'ETF分割':
                required.append('分割(反分割)')
            if (data.get('stat') != 'OK' or not isinstance(fields, list)
                    or not all(isinstance(field, str) for field in fields) or len(set(fields)) != len(fields)
                    or not all(key in fields for key in required) or not isinstance(data.get('data'), list)):
                raise ValueError(kind + '資料尚未完整核對')
            for values in data['data']:
                check()
                if not isinstance(values, list) or len(values) != len(fields):
                    raise ValueError(kind + '資料列與欄位數量不符')
                raw = dict(zip(fields, values))
                if str(raw[code_field]).strip() != symbol:
                    continue
                parts = re.fullmatch(r'\s*(\d{2,4})[/-](\d{1,2})[/-](\d{1,2})\s*', str(raw[date_field]))
                if not parts:
                    raise ValueError('公司行動日期無法辨識')
                y, m, d = map(int, parts.groups())
                day = date(y + (1911 if y < 1911 else 0), m, d)
                if not first <= day <= last or (day, kind) in seen:
                    raise ValueError('公司行動日期超出範圍或同日同類資料重複')
                seen.add((day, kind))
                before, after = _number(raw[before_field]), _number(raw[after_field])
                supported = ((kind == '除權息' and str(raw['權/息']).strip() == '息')
                             or (kind == 'ETF分割' and str(raw['分割(反分割)']).strip() in ('分割', '反分割')))
                reason = None if supported else '除權、減資、面額變更或未知類型尚未支援價格比較調整'
                if before is None or after is None:
                    supported, reason = False, '官方前收盤或參考價缺漏／無效，不能建立調整因子'
                factor = after / before if supported else None
                if factor is not None and not math.isfinite(factor):
                    supported, factor, reason = False, None, '官方參考價比值無效'
                payload = {'fields': fields, 'row': values, 'request': {'start': first.isoformat(), 'end': last.isoformat()}}
                row = ('TW', symbol, day.isoformat(), kind, before, after, factor,
                       'supported' if supported else 'unsupported', reason, url, source_hash, observed,
                       PARSER_VERSION, encoded(payload))
                evidence.append((row, receipt_id))
    check()
    with closing(sqlite3.connect(db)) as conn, conn:
        conn.execute('BEGIN IMMEDIATE')
        check()
        ensure_action_schema(conn)
        previous = conn.execute('SELECT parser_version,sources_json FROM action_price_coverage WHERE market=? AND symbol=?', ('TW', symbol)).fetchone()
        sources = json.loads(previous[1]) if previous and previous[0] == PARSER_VERSION else []
        if not isinstance(sources, list):
            raise ValueError('既有公司行動涵蓋收據格式無效，未覆寫')
        for identity, receipt, payload in receipts:
            check()
            conn.execute('INSERT OR IGNORE INTO action_source_receipts VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                         (identity, 'TW', symbol, receipt['route'], receipt['start'], receipt['end'],
                          receipt['sourceHash'], receipt['url'], receipt['retrievedAt'], PARSER_VERSION, payload))
            if not any(isinstance(old, dict) and old.get('url') == receipt['url'] and old.get('sourceHash') == receipt['sourceHash'] for old in sources):
                sources.append(receipt)
        prior_rows = conn.execute('SELECT * FROM action_price_evidence WHERE market=? AND symbol=? AND session_date BETWEEN ? AND ?',
                                  ('TW', symbol, begin.isoformat(), end.isoformat())).fetchall()
        prior = {(row[2], row[3]): row for row in prior_rows}
        current = {(row[2], row[3]): (row, receipt_id) for row, receipt_id in evidence}
        for key in sorted(set(prior) | set(current)):
            check()
            old = prior.get(key)
            new, receipt_id = current.get(key, (None, None))
            if new:
                conn.execute('INSERT OR IGNORE INTO corporate_actions VALUES(?,?,?,?,?)', (*new[:4], 'TWSE'))
            if old is None:
                conn.execute('INSERT INTO action_price_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)', new)
                continue
            if new is not None and _meaning(old) == _meaning(new):
                continue
            if receipt_id is None:
                route = next(route for route, _, _, kind, *_ in ROUTES if kind == old[3])
                receipt_id = next(identity for identity, receipt, _ in receipts
                                  if receipt['route'] == route and receipt['start'] <= old[2] <= receipt['end'])
            payload = encoded(new) if new is not None else 'null'
            identity = hashlib.sha256(encoded([symbol, key, _meaning(old), _meaning(new) if new else None, receipt_id]).encode()).hexdigest()
            conn.execute('INSERT OR IGNORE INTO action_price_revisions VALUES(?,?,?,?,?,?,?,?,?,?)',
                         (identity, 'TW', symbol, old[2], old[3], datetime.now(timezone.utc).isoformat(),
                          encoded(old), payload, receipt_id, CONFLICT_REASON))
        first, last = _coverage(sources, begin, end)
        conn.execute('INSERT OR REPLACE INTO action_price_coverage VALUES(?,?,?,?,?,?)',
                     ('TW', symbol, first, last, PARSER_VERSION, encoded(sources)))
        conn.execute('INSERT OR REPLACE INTO action_coverage VALUES(?,?,?,?,?)',
                     ('TW', symbol, first, last, 'TWSE除權息、減資、面額變更、ETF分割'))
        check()
    return len(evidence)
