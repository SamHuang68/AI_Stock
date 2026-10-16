"""一般日線來源的不可覆寫收據；不冒充官方日線品質認證。"""
import hashlib
import json
import math
import time
import uuid
from urllib.parse import urlparse, parse_qs


EVIDENCE_TABLES = ('bar_source_receipts', 'bar_first_ingest', 'bar_reinsert_ingest', 'bar_revision_ingest')


def parse_yahoo_daily(raw, source_symbol, market):
    """擷取與收據核對共用同一解析器，保留既有缺值與日線契約。"""
    res = json.loads(raw)['chart']['result'][0]
    meta = res.get('meta') or {}
    actual_symbol = meta.get('symbol')
    if actual_symbol and str(actual_symbol).upper() != source_symbol.upper():
        raise ValueError('來源證券代號與請求不符，拒絕寫入')
    zone = meta.get('exchangeTimezoneName')
    if zone and ((market == 'TW' and zone != 'Asia/Taipei') or (market == 'US' and zone not in ('America/New_York', 'America/Chicago', 'US/Eastern', 'US/Central'))):
        raise ValueError('來源交易所時區與市場不符，拒絕寫入')
    granularity = meta.get('dataGranularity')
    if granularity and granularity != '1d':
        raise ValueError('來源回傳非日線資料，拒絕寫入日線庫')
    q = res['indicators']['quote'][0]
    rows = []
    for i, t in enumerate(res['timestamp']):
        cl = q['close'][i]
        if not isinstance(cl, (int, float)) or not math.isfinite(cl) or cl <= 0:
            continue
        op, hi, lo = [v if isinstance(v, (int, float)) and math.isfinite(v) and v > 0 else None
                      for v in (q['open'][i], q['high'][i], q['low'][i])]
        vol = q['volume'][i]
        vol = vol if isinstance(vol, (int, float)) and math.isfinite(vol) and vol >= 0 else None
        rows.append((t, op, hi, lo, cl, vol))
    return res, rows


def capture_yahoo(raw, url, symbol, market, source_symbol):
    """保留取得當下的原始位元組與解析結果，供同次寫入核對。"""
    return {'receiptId': uuid.uuid4().hex, 'source': 'Yahoo Finance',
            'symbol': symbol, 'market': market, 'url': url,
            'raw': raw, 'sha256': hashlib.sha256(raw).hexdigest(),
            'retrievedAt': time.time(), 'parserVersion': 'yahoo-chart-daily-v1',
            'volumeContract': 'Yahoo chart indicators.quote.volume 原始值，未換算',
            'sourceSymbol': source_symbol}


def store_receipt(conn, receipt, symbol, market, source, rows):
    """沿用官方收據的不可覆寫原則，使用獨立的一般來源契約。"""
    if (not isinstance(receipt, dict) or source != 'Yahoo Finance'
            or receipt.get('source') != source or receipt.get('symbol') != symbol
            or receipt.get('market') != market):
        raise ValueError('日線來源收據與本次標的或來源不符')
    raw = receipt.get('raw')
    retrieved = receipt.get('retrievedAt')
    if (not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != receipt.get('sha256')
            or not isinstance(retrieved, (int, float)) or not math.isfinite(retrieved)
            or receipt.get('parserVersion') != 'yahoo-chart-daily-v1'
            or receipt.get('volumeContract') != 'Yahoo chart indicators.quote.volume 原始值，未換算'):
        raise ValueError('日線來源原始回應或取得時間無效')
    receipt_id = receipt.get('receiptId')
    if not isinstance(receipt_id, str) or len(receipt_id) != 32 or any(c not in '0123456789abcdef' for c in receipt_id):
        raise ValueError('日線來源收據識別無效')
    expected = symbol if symbol.startswith('^') or symbol.endswith(('.TW', '.TWO')) else symbol + '.TW' if market == 'TW' else symbol
    allowed = {expected}
    if market == 'TW' and expected.endswith('.TW'):
        allowed.add(expected.removesuffix('.TW') + '.TWO')
    source_symbol = receipt.get('sourceSymbol')
    url = urlparse(receipt.get('url', ''))
    if (source_symbol not in allowed or url.scheme != 'https'
            or url.netloc not in ('query1.finance.yahoo.com', 'query2.finance.yahoo.com')
            or url.path != '/v8/finance/chart/' + source_symbol
            or parse_qs(url.query).get('interval') != ['1d']):
        raise ValueError('日線來源網址或證券代號與收據不符')
    _, parsed_rows = parse_yahoo_daily(raw, source_symbol, market)
    captured = {tuple(row) for row in parsed_rows}
    if any(tuple(row) not in captured for row in rows):
        raise ValueError('待寫入日線不屬於本次取得的解析結果')
    conn.execute('CREATE TABLE IF NOT EXISTS bar_source_receipts('
                 'receipt_id TEXT PRIMARY KEY,source TEXT NOT NULL,symbol TEXT NOT NULL,market TEXT NOT NULL,'
                 'source_url TEXT NOT NULL,raw_payload BLOB NOT NULL,source_hash TEXT NOT NULL,'
                 'retrieved_at REAL NOT NULL,parser_version TEXT NOT NULL,volume_contract TEXT NOT NULL) WITHOUT ROWID')
    conn.execute('CREATE TABLE IF NOT EXISTS bar_first_ingest('
                 'market TEXT NOT NULL,symbol TEXT NOT NULL,ts INTEGER NOT NULL,run_id TEXT NOT NULL,'
                 'receipt_id TEXT NOT NULL,written_at REAL NOT NULL,payload TEXT NOT NULL,'
                 'PRIMARY KEY(market,symbol,ts)) WITHOUT ROWID')
    conn.execute('CREATE TABLE IF NOT EXISTS bar_reinsert_ingest('
                 'market TEXT NOT NULL,symbol TEXT NOT NULL,ts INTEGER NOT NULL,run_id TEXT NOT NULL,'
                 'receipt_id TEXT NOT NULL,written_at REAL NOT NULL,payload TEXT NOT NULL,'
                 'PRIMARY KEY(market,symbol,ts,run_id)) WITHOUT ROWID')
    conn.execute('CREATE TABLE IF NOT EXISTS bar_revision_ingest('
                 'revision_id TEXT NOT NULL,run_id TEXT NOT NULL,receipt_id TEXT NOT NULL,'
                 'PRIMARY KEY(revision_id,run_id)) WITHOUT ROWID')
    for table in ('bar_source_receipts', 'bar_first_ingest', 'bar_reinsert_ingest', 'bar_revision_ingest'):
        for action in ('UPDATE', 'DELETE'):
            conn.execute(f'CREATE TRIGGER IF NOT EXISTS {table}_no_{action.lower()} '
                         f'BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,\'首次來源證據不可覆寫或刪除\'); END')
    # INSERT OR REPLACE 不會觸發 DELETE 觸發器，另以同主鍵的 BEFORE INSERT 擋下；正常寫入先自行檢查，不會觸發。
    for table, key in (('bar_source_receipts', 'receipt_id=NEW.receipt_id'),
                       ('bar_first_ingest', 'market=NEW.market AND symbol=NEW.symbol AND ts=NEW.ts'),
                       ('bar_reinsert_ingest', 'market=NEW.market AND symbol=NEW.symbol AND ts=NEW.ts AND run_id=NEW.run_id'),
                       ('bar_revision_ingest', 'revision_id=NEW.revision_id AND run_id=NEW.run_id')):
        conn.execute(f'CREATE TRIGGER IF NOT EXISTS {table}_no_replace BEFORE INSERT ON {table} '
                     f'WHEN EXISTS(SELECT 1 FROM {table} WHERE {key}) '
                     f'BEGIN SELECT RAISE(ABORT,\'首次來源證據不可覆寫或刪除\'); END')
    for table in EVIDENCE_TABLES:
        definition = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if definition is None or 'WITHOUT ROWID' not in (definition[0] or '').upper():
            raise ValueError('證據表 %s 的定義不是 WITHOUT ROWID（可能是舊版建立）；不沿用，以免不可覆寫的保證失效' % table)
    values = (receipt_id, source, symbol, market, receipt['url'], raw, receipt['sha256'],
              retrieved, receipt['parserVersion'], receipt['volumeContract'])
    old = conn.execute('SELECT * FROM bar_source_receipts WHERE receipt_id=?', (receipt_id,)).fetchone()
    if old is not None and tuple(old) != values:
        raise ValueError('日線來源收據識別已存在且內容不同')
    if old is None:
        conn.execute('INSERT INTO bar_source_receipts VALUES(?,?,?,?,?,?,?,?,?,?)', values)
    return receipt_id


def link_first_insert(conn, market, symbol, row, run_id, receipt_id):
    """只在本次確實新增 bars 時呼叫；既有資料缺證據不得回填。"""
    # 已有首次證據（bars 曾被別處刪除後重新取得）時保留原證據、不建立第二筆「首次」，
    # 也不讓整個標的的更新因主鍵衝突而永久失敗。
    payload = json.dumps(row, ensure_ascii=False, allow_nan=False)
    old = conn.execute('SELECT payload FROM bar_first_ingest WHERE market=? AND symbol=? AND ts=?',
                       (market, symbol, row[0])).fetchone()
    if old:
        # 值相同視為同一筆；值不同則另存本次重插與其收據，兩次寫入都能追溯。
        if old[0] != payload and not conn.execute(
                'SELECT 1 FROM bar_reinsert_ingest WHERE market=? AND symbol=? AND ts=? AND run_id=?',
                (market, symbol, row[0], run_id)).fetchone():
            conn.execute('INSERT INTO bar_reinsert_ingest VALUES(?,?,?,?,?,?,?)',
                         (market, symbol, row[0], run_id, receipt_id, time.time(), payload))
        return False
    conn.execute('INSERT INTO bar_first_ingest VALUES(?,?,?,?,?,?,?)',
                 (market, symbol, row[0], run_id, receipt_id, time.time(), payload))
    return True


def link_revision(conn, revision_id, run_id, receipt_id):
    """修訂保留原內容雜湊去重；每次取得關聯另存。"""
    if not conn.execute('SELECT 1 FROM bar_revision_ingest WHERE revision_id=? AND run_id=?',
                        (revision_id, run_id)).fetchone():
        conn.execute('INSERT INTO bar_revision_ingest VALUES(?,?,?)', (revision_id, run_id, receipt_id))
