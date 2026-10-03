"""附加日線品質；首次價格保留，官方差異另存，不暗中切換價格基準。"""
import hashlib
import json
import math
import re
import time
from datetime import date, datetime, timezone, timedelta
from urllib.parse import parse_qs, urlsplit

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
CREATE TABLE IF NOT EXISTS official_source_receipts(
 receipt_id TEXT PRIMARY KEY,source TEXT NOT NULL,source_hash TEXT NOT NULL,
 source_url TEXT NOT NULL,raw_payload TEXT NOT NULL,retrieved_at TEXT NOT NULL,
 written_at TEXT NOT NULL,parser_version TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS official_daily_receipt_links(
 market TEXT NOT NULL,symbol TEXT NOT NULL,session_date TEXT NOT NULL,source TEXT NOT NULL,
 source_hash TEXT NOT NULL,receipt_id TEXT NOT NULL,payload TEXT NOT NULL,written_at TEXT NOT NULL,
 raw_origin INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(market,symbol,session_date,source,source_hash,receipt_id));
CREATE TRIGGER IF NOT EXISTS official_source_receipts_no_update
 BEFORE UPDATE ON official_source_receipts BEGIN SELECT RAISE(ABORT,'來源收據不可覆寫'); END;
CREATE TRIGGER IF NOT EXISTS official_source_receipts_no_delete
 BEFORE DELETE ON official_source_receipts BEGIN SELECT RAISE(ABORT,'來源收據不可刪除'); END;
CREATE TRIGGER IF NOT EXISTS official_daily_receipt_links_no_update
 BEFORE UPDATE ON official_daily_receipt_links BEGIN SELECT RAISE(ABORT,'來源收據連結不可覆寫'); END;
CREATE TRIGGER IF NOT EXISTS official_daily_receipt_links_no_delete
 BEFORE DELETE ON official_daily_receipt_links BEGIN SELECT RAISE(ABORT,'來源收據連結不可刪除'); END;
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

RECEIPT_PARSER_VERSION = 'twse-stock-day-v1'
TAIPEI = timezone(timedelta(hours=8))
MONTH_FIELDS = ['日期', '成交股數', '成交金額', '開盤價', '最高價', '最低價', '收盤價']


def _day(stamp):
    try:
        if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
            return None
        return datetime.fromtimestamp(stamp, TAIPEI).date().isoformat()
    except (OSError, ValueError, OverflowError):
        return None


def _equal(left, right):
    return ((left is None and right is None) or
            (left is not None and right is not None and not isinstance(left, bool) and
             not isinstance(right, bool) and isinstance(left, (int, float)) and
             isinstance(right, (int, float)) and math.isfinite(left) and math.isfinite(right) and
             math.isclose(left, right, rel_tol=1e-6, abs_tol=1e-5)))


def _valid_prices(row):
    prices = row[1:5]
    return (len(prices) == 4 and all(isinstance(v, (int, float)) and not isinstance(v, bool) and
            math.isfinite(v) and v > 0 for v in prices) and
            prices[2] <= min(prices[0], prices[3]) <= max(prices[0], prices[3]) <= prices[1])


def _same_values(left, right):
    """價格沿用既有浮點容差，成交股數必須相等，不因大量成交吞掉一股差異。"""
    return (len(left) == len(right) == 5 and all(_equal(a, b) for a, b in zip(left[:4], right[:4])) and
            _equal(left[4], right[4]) and left[4] == right[4])


def _valid_row(row):
    return (isinstance(row, (list, tuple)) and len(row) == 6 and _day(row[0]) is not None and
            all(v is None or (isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)) for v in row[1:]))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('來源收據 JSON 欄位重複')
        result[key] = value
    return result


def _receipt_number(raw, *, price=False):
    if isinstance(raw, bool):
        return None
    try:
        value = float(str(raw).strip().replace(',', ''))
        return value if math.isfinite(value) and (value > 0 if price else value >= 0) else None
    except (TypeError, ValueError, OverflowError):
        return None


def validate_source_receipt(source_receipt, source, source_hash, symbol, rows, *, now=None):
    """逐列核對原始回應，不能由解析後資料重建或補造取得時間。"""
    now = now or datetime.now(timezone.utc)
    if not isinstance(source_receipt, dict) or source != 'TWSE':
        raise ValueError('來源收據只接受已支援的 TWSE 個股月份格式')
    receipt = {key: source_receipt.get(key) for key in ('url', 'raw_text', 'retrieved_at', 'parser_version')}
    if any(not isinstance(v, str) or not v for v in receipt.values()):
        raise ValueError('來源收據欄位不足')
    if receipt['parser_version'] != RECEIPT_PARSER_VERSION:
        raise ValueError('來源收據解析版本尚未支援')
    raw = receipt['raw_text'].encode('utf-8')
    if len(raw) > 12_000_000 or not isinstance(source_hash, str) or not re.fullmatch('[0-9a-f]{64}', source_hash) or hashlib.sha256(raw).hexdigest() != source_hash:
        raise ValueError('來源收據原始雜湊不符')
    url = urlsplit(receipt['url'])
    query = parse_qs(url.query)
    if (url.scheme != 'https' or url.hostname not in ('www.twse.com.tw', 'wwwc.twse.com.tw') or
            url.username or url.password or url.port not in (None, 443) or url.fragment or
            url.path not in ('/exchangeReport/STOCK_DAY', '/rwd/zh/afterTrading/STOCK_DAY') or
            query.get('stockNo') != [symbol] or query.get('response') != ['json'] or
            len(query.get('date', [])) != 1):
        raise ValueError('來源收據網址或證券身分不符')
    try:
        retrieved = datetime.fromisoformat(receipt['retrieved_at'].replace('Z', '+00:00'))
        month = datetime.strptime(query['date'][0], '%Y%m%d').date()
        data = json.loads(receipt['raw_text'], object_pairs_hook=_unique_object)
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError('來源收據日期或 JSON 無效') from exc
    if retrieved.tzinfo is None or retrieved > now or month.day != 1:
        raise ValueError('來源收據取得時間或月份無效')
    title_pattern = rf'^\s*{month.year - 1911}年0?{month.month}月\s+{re.escape(symbol)}\s'
    if (not isinstance(data, dict) or data.get('stat') != 'OK' or data.get('date') != month.strftime('%Y%m%d') or
            not isinstance(data.get('fields'), list) or data['fields'][:7] != MONTH_FIELDS or not re.search(title_pattern, str(data.get('title', ''))) or
            not isinstance(data.get('data'), list) or not isinstance(data.get('notes'), list) or
            not all(isinstance(note, str) for note in data.get('notes', []))):
        raise ValueError('來源收據月份、欄位、說明或證券身分不符')
    parsed = {}
    for item in data['data']:
        try:
            y, m, d = map(int, item[0].split('/'))
            day = date(y + 1911, m, d)
            values = [*[_receipt_number(item[i], price=True) for i in (3, 4, 5, 6)], _receipt_number(item[1])]
        except (ValueError, TypeError, IndexError, AttributeError) as exc:
            raise ValueError('來源收據日線列無效') from exc
        if (day.year, day.month) != (month.year, month.month) or day.isoformat() in parsed or day > retrieved.astimezone(TAIPEI).date():
            raise ValueError('來源收據交易日重複、超出月份或晚於取得日期')
        parsed[day.isoformat()] = values
    days = set()
    for row in rows:
        day = _day(row[0])
        if day in days or day not in parsed or not _same_values(row[1:], parsed[day]):
            raise ValueError('來源收據與寫入日線不一致')
        days.add(day)
    identity = json.dumps([source, source_hash, receipt['url'], receipt['retrieved_at'], receipt['parser_version']], ensure_ascii=False)
    return hashlib.sha256(identity.encode('utf-8')).hexdigest(), receipt


def issues(row):
    result = []
    if any(v is None or not math.isfinite(v) or v <= 0 for v in row[1:5]):
        result.append('價格缺值或無效')
    elif not row[3] <= min(row[1], row[4]) <= max(row[1], row[4]) <= row[2]:
        result.append('開高低收邊界無效')
    if row[5] is None or not math.isfinite(row[5]) or row[5] <= 0:
        result.append('成交量缺值或無成交')
    return result


def store_official(conn, symbol, market, rows, source, source_hash, *, check=lambda: None, source_receipt=None):
    if market != 'TW' or source not in ('TWSE', 'TPEX'):
        raise ValueError('官方台股品質僅接受 TWSE／TPEX 的 TW 日線')
    if not symbol:
        raise ValueError('官方證券代號不可為空')
    rows = list(rows)
    for row in rows:
        if not _valid_row(row):
            raise ValueError('官方日線欄位無效；缺值須為 null')
    observed = datetime.now(timezone.utc).isoformat()
    receipt_id = None
    if source_receipt is not None:
        receipt_id, receipt = validate_source_receipt(source_receipt, source, source_hash, symbol, rows)
        check()
        conn.execute('INSERT OR IGNORE INTO official_source_receipts VALUES(?,?,?,?,?,?,?,?)',
                     (receipt_id, source, source_hash, receipt['url'], receipt['raw_text'],
                      receipt['retrieved_at'], observed, receipt['parser_version']))
    existing = {}
    for row in conn.execute('SELECT ts,open,high,low,close,volume FROM bars WHERE market=? AND symbol=? ORDER BY ts', (market, symbol)):
        existing.setdefault(_day(row[0]), []).append(row)
    accepted = 0
    for row in rows:
        check()
        day = _day(row[0])
        payload = json.dumps(list(row), ensure_ascii=False, allow_nan=False)
        digest = source_hash or hashlib.sha256(payload.encode()).hexdigest()
        prior_observation = conn.execute('SELECT payload FROM official_daily_observations WHERE market=? AND symbol=? '
                                        'AND session_date=? AND source=? AND source_hash=?',
                                        (market, symbol, day, source, digest)).fetchone()
        if prior_observation:
            previous = json.loads(prior_observation[0])
            if len(previous) != 6 or _day(previous[0]) != day or not _same_values(previous[1:], row[1:]):
                raise ValueError('相同來源雜湊已有不同日線，拒絕覆寫來源觀測')
        conn.execute('INSERT OR IGNORE INTO official_daily_observations VALUES(?,?,?,?,?,?,?)',
                     (market, symbol, day, source, digest, payload, receipt['retrieved_at'] if receipt_id else observed))
        if receipt_id:
            conn.execute('INSERT OR IGNORE INTO official_daily_receipt_links VALUES(?,?,?,?,?,?,?,?,?)',
                         (market, symbol, day, source, digest, receipt_id,
                          prior_observation[0] if prior_observation else payload, observed, int(not existing.get(day))))
        prior = existing.get(day, [])
        same = len(prior) == 1 and _same_values(prior[0][1:], row[1:])
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
        reasons = issues(row)
        # 曾有官方修訂衝突時，即使後來又讀到原值，也不能使量型研究悄悄解除門檻。
        for other_source, other_payload in conn.execute('SELECT source,payload FROM official_daily_observations '
                        'WHERE market=? AND symbol=? AND session_date=?', (market, symbol, day)):
            other = json.loads(other_payload)
            if (other_source != source or len(other) != 6 or _day(other[0]) != day or
                    not _same_values(stored[1:], other[1:])):
                reasons.append('官方來源與原始日線不同；原始值保留')
                break
        conn.execute('INSERT OR REPLACE INTO bar_quality VALUES(?,?,?,?,?,?,?,?,?,?)',
                     (market, symbol, stored[0], day, source, '股', '原始價格',
                      json.dumps(reasons, ensure_ascii=False), receipt['retrieved_at'] if receipt_id else observed, digest))
        accepted += 1
    if accepted:
        conn.execute('INSERT INTO meta VALUES(?,?,?,?) ON CONFLICT(market,symbol) DO UPDATE SET last_update=excluded.last_update',
                     (symbol, market, symbol, int(time.time())))
    check()
    return accepted


def quality_evidence(conn, symbol, market='TW', *, board=None, start=None, end=None):
    """唯讀分欄判定；完整收據核對與歷次觀測衝突共用一個計算入口。"""
    if market != 'TW':
        return {}
    def in_range(day):
        return bool(day and (start is None or day >= start) and (end is None or day <= end))
    raw, observations, linked, receipt_counts = {}, {}, {}, {}
    for row in conn.execute('SELECT ts,open,high,low,close,volume FROM bars WHERE market=? AND symbol=?', (market, symbol)):
        day = _day(row[0])
        if in_range(day):
            raw.setdefault(day, []).append(tuple(row))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'official_daily_observations' in tables:
        for day, source, digest, payload in conn.execute('SELECT session_date,source,source_hash,payload FROM '
                    'official_daily_observations WHERE market=? AND symbol=?', (market, symbol)):
            if in_range(day):
                try:
                    row = json.loads(payload)
                    valid = _valid_row(row) and _day(row[0]) == day
                except (TypeError, ValueError):
                    row, valid = [], False
                observations.setdefault(day, []).append({'row': row, 'valid': valid, 'source': source,
                                                        'hash': digest, 'payload': payload})
    if {'official_source_receipts', 'official_daily_receipt_links'} <= tables:
        groups = {}
        for record in conn.execute('''SELECT l.session_date,l.source,l.source_hash,l.payload,r.receipt_id,
                r.source,r.source_hash,r.source_url,r.raw_payload,r.retrieved_at,r.written_at,r.parser_version,
                l.written_at,l.raw_origin FROM official_daily_receipt_links l LEFT JOIN official_source_receipts r ON l.receipt_id=r.receipt_id
                WHERE l.market=? AND l.symbol=?''', (market, symbol)):
            if in_range(record[0]):
                groups.setdefault(record[4], []).append(tuple(record))
                receipt_counts[record[0]] = receipt_counts.get(record[0], 0) + 1
        for receipt_id, records in groups.items():
            first = records[0]
            receipt = {'url': first[7], 'raw_text': first[8], 'retrieved_at': first[9], 'parser_version': first[11]}
            try:
                parsed_rows = [json.loads(r[3]) for r in records]
                if any(r[1] != r[5] or r[2] != r[6] or not _valid_row(p) or _day(p[0]) != r[0]
                       for r, p in zip(records, parsed_rows)):
                    continue
                verified_id, _ = validate_source_receipt(receipt, first[5], first[6], symbol, parsed_rows)
                if receipt_id != verified_id:
                    continue
                metadata = {'receiptId': receipt_id, 'source': first[5], 'sourceHash': first[6],
                            'url': first[7], 'retrievedAt': first[9], 'writtenAt': first[10],
                            'parserVersion': first[11], 'notes': json.loads(first[8])['notes'],
                            'volumeUnit': '股'}
                for r in records:
                    if any(o['source'] == r[1] and o['hash'] == r[2] and o['payload'] == r[3] for o in observations.get(r[0], [])):
                        linked.setdefault(r[0], []).append({**metadata, 'linkedAt': r[12], 'rawOrigin': bool(r[13])})
            except (ValueError, TypeError, KeyError, IndexError, OverflowError):
                continue
    result = {}
    for day in sorted(set(raw) | set(observations)):
        bars, obs, receipts = raw.get(day, []), observations.get(day, []), linked.get(day, [])
        row = bars[0] if len(bars) == 1 else None
        sources = {o['source'] for o in obs}
        source_conflict = len(sources) > 1 or any(s not in ('TWSE', 'TPEX') or board and s != board for s in sources)
        bad_observation = any(not o['valid'] for o in obs)
        bad_receipt = receipt_counts.get(day, 0) != len(receipts)
        price_conflict = bool(row and any(o['valid'] and not all(_equal(a, b) for a, b in zip(row[1:5], o['row'][1:5])) for o in obs))
        volume_conflict = bool(row and any(o['valid'] and (not _equal(row[5], o['row'][5]) or row[5] != o['row'][5]) for o in obs))
        # 收據本身可供重用，不代表原始行情已接受；量價衝突不要求無限重抓同一收據。
        complete = bool(receipts) and not bad_receipt
        usable = complete and not source_conflict and not bad_observation and len(bars) == 1
        price_verified = bool(usable and _valid_prices(row) and not price_conflict)
        volume_verified = bool(usable and row[5] is not None and isinstance(row[5], (int, float)) and
                               not isinstance(row[5], bool) and math.isfinite(row[5]) and row[5] >= 0 and not volume_conflict)
        result[day] = {'priceVerified': price_verified, 'volumeVerified': volume_verified,
                       'priceConflict': price_conflict, 'volumeConflict': volume_conflict,
                       'sourceConflict': source_conflict, 'receiptComplete': complete,
                       'ambiguousSession': len(bars) > 1, 'invalidObservation': bad_observation, 'invalidReceipt': bad_receipt,
                       'rawPresent': bool(bars), 'observations': len(obs),
                       'revisions': max(0, len(obs) - 1), 'source': next(iter(sources)) if len(sources) == 1 else None,
                       'rawSource': next((r['source'] for r in receipts if r['rawOrigin']), None),
                       'receipts': receipts}
    return result


def quality_summary(conn, symbol, expected, market='TW', *, board=None):
    """同一組預期交易日的可核對涵蓋；observed 絕不等於 accepted。"""
    days = sorted(set(expected))
    evidence = quality_evidence(conn, symbol, market, board=board,
                                start=days[0] if days else None, end=days[-1] if days else None) if days else {}
    groups = {'observed': [], 'accepted': [], 'conflicts': [], 'missing': [], 'invalid': [], 'priceVerified': [],
              'receiptMissing': [], 'receiptInvalid': []}
    for day in days:
        item = evidence.get(day, {})
        observed = item.get('observations', 0) > 0
        if observed:
            groups['observed'].append(day)
        else:
            groups['missing'].append(day)
        if item.get('priceVerified'):
            groups['priceVerified'].append(day)
        if item.get('priceVerified') and item.get('volumeVerified'):
            groups['accepted'].append(day)
        if any(item.get(key) for key in ('priceConflict', 'volumeConflict', 'sourceConflict', 'ambiguousSession')):
            groups['conflicts'].append(day)
        elif observed and not (item.get('priceVerified') and item.get('volumeVerified')):
            groups['invalid'].append(day)
        if observed and not item.get('receiptComplete'):
            groups['receiptMissing'].append(day)
        if item.get('invalidReceipt'):
            groups['receiptInvalid'].append(day)
    return {'expected': len(days), **{key: len(values) for key, values in groups.items()},
            **{key + 'Dates': values for key, values in groups.items()}}
