"""全部個股事件的實際留存；與研究候選協定分開，僅讀本機行情。"""
import hashlib
import json
import sqlite3
import zlib
from contextlib import closing
from datetime import datetime
from pathlib import Path

import stock_signals as ss
from 個股訊號研究 import digest


def engine_digest():
    root = Path(__file__).parent
    return digest({name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                   for name in ('stock_signals.py', 'indicators.py')})


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def enable(path, now=None):
    now = now or datetime.now(ss._TZ['TW'])
    if now.tzinfo is None:
        raise ValueError('啟用時間必須含時區')
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript('''
          CREATE TABLE IF NOT EXISTS daily_config(key TEXT PRIMARY KEY,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS daily_inputs(id TEXT PRIMARY KEY,symbol TEXT,session_date TEXT,engine TEXT,payload BLOB);
          CREATE UNIQUE INDEX IF NOT EXISTS daily_input_day ON daily_inputs(symbol,session_date);
          CREATE TABLE IF NOT EXISTS daily_events(id TEXT PRIMARY KEY,input_id TEXT,symbol TEXT,session_date TEXT,signal_id TEXT,observed_at TEXT,payload TEXT);
          CREATE TABLE IF NOT EXISTS daily_prices(symbol TEXT,session_date TEXT,observed_at TEXT,payload TEXT,PRIMARY KEY(symbol,session_date));
          CREATE TABLE IF NOT EXISTS daily_outcomes(event_id TEXT,horizon INTEGER,resolved_at TEXT,payload TEXT,PRIMARY KEY(event_id,horizon));
          CREATE TABLE IF NOT EXISTS daily_runs(at TEXT PRIMARY KEY,payload TEXT);
        ''')
        conn.execute('INSERT OR IGNORE INTO daily_config VALUES(?,?)', ('activation', encoded({
            'activatedAt': now.isoformat(), 'scope': '本機台股日線庫', 'candidatePromotion': False,
            'note': '僅留存啟用後的當日收盤事件；缺日不回填，不代表通過研究門檻。'})))
    return status(path)


def status(path):
    if not Path(path).is_file():
        return {'enabled': False, 'events': 0, 'outcomes': 0, 'recent': [], 'status': 'disabled'}
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        cfg = json.loads(conn.execute("SELECT payload FROM daily_config WHERE key='activation'").fetchone()[0])
        last = conn.execute('SELECT payload FROM daily_runs ORDER BY at DESC LIMIT 1').fetchone()
        recent = [{'symbol': r[0], 'date': r[1], 'signalId': r[2], 'observedAt': r[3]}
                  for r in conn.execute('SELECT symbol,session_date,signal_id,observed_at FROM daily_events '
                                        'ORDER BY observed_at DESC,id LIMIT 20')]
        return {'enabled': True, **cfg, 'events': conn.execute('SELECT count(*) FROM daily_events').fetchone()[0],
                'outcomes': conn.execute('SELECT count(*) FROM daily_outcomes').fetchone()[0],
                'recent': recent, 'lastRun': json.loads(last[0]) if last else None,
                'status': 'observing', 'priceBasis': '首次留存的未還原價格',
                'limitations': '實際結果需等待 5／20 個交易日成熟；不代表可交易候選，未計費用。'}


def capture(path, series, benchmark, chips=None, now=None):
    now = now or datetime.now(ss._TZ['TW'])
    if now.tzinfo is None:
        raise ValueError('留存時間必須含時區')
    now = now.astimezone(ss._TZ['TW'])
    cfg = status(path)
    if not cfg['enabled']:
        return {'status': 'disabled', 'reason': '每日留存尚未啟用'}
    today, stamp = now.date().isoformat(), now.isoformat()
    finalized = (now.hour, now.minute) >= (14, 0)
    benchmark = [b for b in benchmark if b['date'] < today or (finalized and b['date'] == today)]
    sessions = sorted({b['date'] for b in benchmark})
    counts = {'scanned': 0, 'currentSymbols': 0, 'eventsAdded': 0, 'outcomesAdded': 0,
              'asOf': stamp, 'sessionDate': today, 'historicalBackfill': False,
              'status': 'completed' if finalized and today in sessions else 'waiting',
              'reason': '以當日已收盤資料留存' if finalized and today in sessions else '等待當日收盤與大盤資料'}
    version = engine_digest()
    activated = datetime.fromisoformat(cfg['activatedAt']).astimezone(ss._TZ['TW']).date().isoformat()
    with closing(sqlite3.connect(path, timeout=30)) as conn, conn:
        for symbol, raw in series:
            bars = [b for b in raw if b['date'] < today or (finalized and b['date'] == today)]
            counts['scanned'] += 1
            if len(bars) < ss.MIN_BARS:
                continue
            input_id = digest([version, symbol, today])
            if (bars[-1]['date'] == today and today in sessions and today > activated):
                counts['currentSymbols'] += 1
                if not conn.execute('SELECT 1 FROM daily_inputs WHERE symbol=? AND session_date=?', (symbol, today)).fetchone():
                    stock_chips = [c for c in (chips or {}).get(symbol, []) if c['date'] <= today]
                    result = ss.analyze(bars, symbol=symbol, chips=stock_chips, with_stats=False)
                    fresh = [e for e in result.get('events', []) if e['date'] == today and not e.get('provisional')]
                    # 沒有事件亦保存當日掃描證據，避免重跑後行情修訂製造新事件。
                    payload = {'bars': bars, 'chips': stock_chips, 'benchmark': benchmark,
                               'engineDigest': version, 'evidence': result.get('evidence'),
                               'observedAt': stamp, 'source': 'datastore 唯讀快照'}
                    inserted = conn.execute('INSERT OR IGNORE INTO daily_inputs VALUES(?,?,?,?,?)',
                                 (input_id, symbol, today, version, zlib.compress(encoded(payload).encode('utf-8'))))
                    for ev in fresh if inserted.rowcount else []:
                        event_id = digest([input_id, ev['signalId']])
                        cur = conn.execute('INSERT OR IGNORE INTO daily_events VALUES(?,?,?,?,?,?,?)',
                                           (event_id, input_id, symbol, today, ev['signalId'], stamp, encoded(ev)))
                        counts['eventsAdded'] += cur.rowcount
            pending = conn.execute('SELECT e.id,e.session_date,e.input_id FROM daily_events e WHERE symbol=? '
                'AND (SELECT count(*) FROM daily_outcomes o WHERE o.event_id=e.id)<2', (symbol,)).fetchall()
            if not pending:
                continue
            first = min(e[1] for e in pending)
            for b in bars:
                if b['date'] > first:
                    conn.execute('INSERT OR IGNORE INTO daily_prices VALUES(?,?,?,?)',
                                 (symbol, b['date'], stamp, encoded(b)))
            for event_id, origin, _ in pending:
                expected_all = [d for d in sessions if d > origin]
                prices = {r[0]: json.loads(r[1]) for r in conn.execute(
                    'SELECT session_date,payload FROM daily_prices WHERE symbol=? AND session_date>?', (symbol, origin))}
                for hz in (5, 20):
                    expected = expected_all[:hz + 1]
                    if len(expected) != hz + 1 or any(d not in prices for d in expected):
                        continue
                    if sorted(d for d in prices if origin < d <= expected[-1]) != expected:
                        continue  # 個股有交易但基準缺日，不能跳過該日向後湊足觀察期。
                    observed = [prices[d] for d in expected]
                    entry = observed[0]['close']
                    out = {'horizon': hz, 'entryDate': expected[0], 'endDate': expected[-1],
                           'ret': observed[-1]['close'] / entry - 1,
                           'adverse': min(b['low'] for b in observed[1:]) / entry - 1,
                           'expectedSessions': expected, 'prices': observed, 'pricesDigest': digest(observed),
                           'note': '次日收盤起算；未還原、未計費用，首次取得價格凍結，不覆寫結果。'}
                    cur = conn.execute('INSERT OR IGNORE INTO daily_outcomes VALUES(?,?,?,?)',
                                       (event_id, hz, stamp, encoded(out)))
                    counts['outcomesAdded'] += cur.rowcount
        if finalized and today in sessions and today <= activated:
            counts.update(status='waiting', reason='啟用當日不回填；由下一個交易日開始留存')
        elif finalized and today in sessions and counts['currentSymbols'] == 0:
            counts.update(status='waiting', reason='大盤已更新，個股當日日線尚未到齊')
        conn.execute('INSERT OR IGNORE INTO daily_runs VALUES(?,?)', (stamp, encoded(counts)))
    return counts
