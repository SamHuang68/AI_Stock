"""保存第二官方報表原件；只對逐欄一致的原價差異提供可追溯核對。"""
import hashlib
import json
import re
from datetime import date, datetime, timezone
from urllib.parse import parse_qs, urlsplit

from daily_quality import TAIPEI, _equal, _receipt_number, _unique_object

TABLE = 'official_price_crosschecks'
VERSION = 'twse-price-crosscheck-v1'


def parse_receipt(symbol, digest, receipt):
    if not isinstance(receipt, dict) or receipt.get('parser_version') != VERSION:
        raise ValueError('交叉核對來源版本無效')
    raw = receipt.get('raw_text')
    if not isinstance(raw, str) or len(raw.encode('utf-8')) > 12_000_000 or hashlib.sha256(raw.encode('utf-8')).hexdigest() != digest:
        raise ValueError('交叉核對原始回應雜湊不符')
    url = urlsplit(receipt['url'])
    query = parse_qs(url.query)
    observed = datetime.fromisoformat(receipt['retrieved_at'].replace('Z', '+00:00'))
    if (url.scheme != 'https' or url.hostname not in ('www.twse.com.tw', 'wwwc.twse.com.tw')
            or url.username or url.password or url.port not in (None, 443) or url.fragment
            or observed.tzinfo is None or observed > datetime.now(timezone.utc)
            or query.get('response') != ['json'] or len(query.get('date', [])) != 1):
        raise ValueError('交叉核對網址、時間或參數無效')
    requested = datetime.strptime(query['date'][0], '%Y%m%d').date()
    data = json.loads(raw, object_pairs_hook=_unique_object)
    observed_day = observed.astimezone(TAIPEI).date()
    if data.get('stat') != 'OK' or data.get('date') != requested.strftime('%Y%m%d') or requested > observed_day:
        raise ValueError('交叉核對回應日期或狀態不符')
    result = {}
    if url.path == '/exchangeReport/STOCK_DAY_AVG':
        title = rf'^\s*{requested.year - 1911}年0?{requested.month}月\s+{re.escape(symbol)}\s'
        if (requested.day != 1 or query.get('stockNo') != [symbol] or data.get('fields') != ['日期', '收盤價']
                or not re.search(title, str(data.get('title', '')))):
            raise ValueError('交叉核對月收盤標的或欄位不符')
        for row in data['data']:
            if len(row) != 2:
                raise ValueError('交叉核對月收盤欄數不符')
            if row[0] == '月平均收盤價':
                continue
            y, m, d = map(int, row[0].split('/'))
            day = date(y + 1911, m, d)
            if day.strftime('%Y%m') != requested.strftime('%Y%m') or day.isoformat() in result or day > observed_day:
                raise ValueError('交叉核對月份、日期重複或晚於取得日')
            result[day.isoformat()] = {'close': _receipt_number(row[1], price=True)}
    elif url.path == '/exchangeReport/MI_INDEX' and query.get('type') == ['ALLBUT0999']:
        names = ['證券代號', '開盤價', '最高價', '最低價', '收盤價']
        tables = [t for t in data.get('tables', []) if set(names) <= set(t.get('fields', []))]
        if len(tables) != 1:
            raise ValueError('交叉核對全市場價格表不足或重複')
        table = tables[0]
        fields = table['fields']
        if len(set(fields)) != len(fields):
            raise ValueError('交叉核對全市場欄名重複')
        rows = [r for r in table['data'] if len(r) == len(fields) and str(r[fields.index(names[0])]).strip() == symbol]
        if len(rows) != 1:
            raise ValueError('交叉核對全市場標的缺失或重複')
        result[requested.isoformat()] = {k: _receipt_number(rows[0][fields.index(n)], price=True)
            for k, n in zip(('open', 'high', 'low', 'close'), names[1:])}
    else:
        raise ValueError('交叉核對來源路由未支援')
    if not result or any(v is None for row in result.values() for v in row.values()):
        raise ValueError('交叉核對缺少有效價格')
    return result


def save_receipt(conn, symbol, digest, receipt):
    parsed = parse_receipt(symbol, digest, receipt)
    identity = hashlib.sha256(json.dumps([symbol, digest, receipt['url'], receipt['retrieved_at']], ensure_ascii=False).encode()).hexdigest()
    conn.execute(f'CREATE TABLE IF NOT EXISTS {TABLE}(id TEXT PRIMARY KEY,symbol TEXT NOT NULL,source_hash TEXT NOT NULL,receipt TEXT NOT NULL)')
    for action in ('UPDATE', 'DELETE'):
        conn.execute(f"CREATE TRIGGER IF NOT EXISTS {TABLE}_no_{action.lower()} BEFORE {action} ON {TABLE} BEGIN SELECT RAISE(ABORT,'交叉來源收據不可覆寫或刪除'); END")
    conn.execute(f'INSERT OR IGNORE INTO {TABLE} VALUES(?,?,?,?)', (identity, symbol, digest, json.dumps(receipt, ensure_ascii=False)))
    return {'id': identity, 'dates': len(parsed)}


def load_receipts(conn, symbol):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone():
        return {}
    result = {}
    for identity, digest, payload in conn.execute(f'SELECT id,source_hash,receipt FROM {TABLE} WHERE symbol=?', (symbol,)):
        receipt = json.loads(payload)
        expected = hashlib.sha256(json.dumps([symbol, digest, receipt['url'], receipt['retrieved_at']], ensure_ascii=False).encode()).hexdigest()
        if identity != expected:
            raise ValueError('交叉核對收據身分不符')
        for day, prices in parse_receipt(symbol, digest, receipt).items():
            result.setdefault(day, []).append({'id': identity, 'sourceHash': digest, 'url': receipt['url'], 'prices': prices})
    return result


def reconcile(day, original, official, crosschecks):
    fields = ('open', 'high', 'low', 'close')
    if len(original) != len(fields) or len(official) != len(fields):
        return None
    differences = {k: [a, b] for k, a, b in zip(fields, original, official) if not _equal(a, b)}
    proofs = crosschecks.get(day, [])
    expected = dict(zip(fields, official))
    # 次來源提供的任何價格欄位都必須一致；不能只看原始行情有差異的欄位。
    if any(not isinstance(p.get('prices'), dict) or not p['prices']
           or any(field not in expected or not _equal(value, expected[field]) for field, value in p['prices'].items())
           for p in proofs):
        return None
    for field, (_, value) in differences.items():
        observations = [p['prices'][field] for p in proofs if field in p['prices']]
        if not observations or any(not _equal(v, value) for v in observations):
            return None
    if not differences:
        return None
    return {'date': day, 'classification': 'two-official-reports-agree', 'differences': differences,
            'crosscheckReceipts': [{k: p[k] for k in ('id', 'sourceHash', 'url')} for p in proofs]}
