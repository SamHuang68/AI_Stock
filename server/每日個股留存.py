"""全部個股事件的實際留存；與研究候選協定分開，僅讀本機行情。"""
import hashlib
import json
import sqlite3
import zlib
from contextlib import closing
from datetime import datetime
from pathlib import Path

import stock_signals as ss
from 台股交易參考 import session, instrument, trading_status, eligible_bar, continuous_segments
from 個股訊號研究 import digest


def engine_digest():
    root = Path(__file__).parent
    return digest({name: hashlib.sha256((root / name).read_bytes()).hexdigest()
                   for name in ('stock_signals.py', 'indicators.py', '每日個股留存.py',
                                '台股交易參考.py', '台股交易參考.json')})


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def maturity_progress(origin, sessions, price_dates, horizon):
    """只以實際基準日與首次價格核對；不猜測未來開市或壓縮缺日。"""
    following = sorted({day for day in sessions if day > origin})
    expected = following[:horizon + 1]
    prices = {day for day in price_dates if day > origin}
    missing = [day for day in expected if day not in prices]
    # 尚未滿期時，基準最後一日之後的個股價格也能證明基準漏日。
    extra = sorted(day for day in prices if day not in expected and
                   (len(expected) < horizon + 1 or day <= expected[-1]))
    reason = ('missing_benchmark_sessions' if extra else 'missing_stock_sessions' if missing else
              'awaiting_observed_sessions' if len(expected) < horizon + 1 else 'ready')
    return {'status': reason, 'horizon': horizon, 'requiredFollowingSessions': horizon + 1,
            'observedFollowingSessions': len(expected), 'benchmarkAsOf': following[-1] if following else None,
            'expectedSessions': expected, 'missingPriceDates': missing, 'missingBenchmarkDates': extra}


def _chip_schema(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS daily_chip_inputs('
                 'id TEXT PRIMARY KEY,input_id TEXT,signal_id TEXT,observed_at TEXT,payload BLOB)')


def _capture_chips(conn, input_row, symbol, today, stamp, chips, version):
    """較晚到達的籌碼有獨立證據；不改寫先前價量輸入、不隔日補造事件。"""
    input_id, original_version, compressed = input_row
    price = json.loads(zlib.decompress(compressed))
    bars = price['bars']
    expected = [b['date'] for b in bars[-4:]]
    values = {r['date']: r for r in chips if r['date'] <= today}
    missing, added, complete = [], 0, 0
    for sid, field in (('chip_trust_buy3', 'trust'), ('chip_foreign_sell3', 'foreign')):
        event_id = digest([input_id, sid])
        if conn.execute('SELECT 1 FROM daily_chip_inputs WHERE id=?', (event_id,)).fetchone():
            complete += 1
            continue
        absent = [day for day in expected if ss._finite(values.get(day, {}).get(field)) is None]
        if original_version != version or len(expected) != 4 or absent:
            missing.append({'symbol': symbol, 'signalId': sid, 'missingDates': absent,
                            'reason': '引擎版本已變更，原觀察保留' if original_version != version else '等待完整四日籌碼'})
            continue
        stock_chips = [values[day] for day in sorted(values)]
        result = ss.analyze(bars, symbol=symbol, chips=stock_chips, with_stats=False)
        payload = {'priceInputId': input_id, 'barsDigest': digest(bars), 'chips': stock_chips,
                   'engineDigest': version, 'observedAt': stamp, 'requiredDates': expected,
                   'source': '同日稍後到齊的本機籌碼；使用首次價量輸入'}
        conn.execute('INSERT INTO daily_chip_inputs VALUES(?,?,?,?,?)',
                     (event_id, input_id, sid, stamp, zlib.compress(encoded(payload).encode('utf-8'))))
        for ev in result.get('events', []):
            if ev['signalId'] == sid and ev['date'] == today and not ev.get('provisional'):
                saved = {**ev, 'chipInputId': event_id}
                cur = conn.execute('INSERT OR IGNORE INTO daily_events VALUES(?,?,?,?,?,?,?)',
                    (event_id, input_id, symbol, today, sid, stamp, encoded(saved)))
                added += cur.rowcount
        complete += 1
    return added, complete, missing


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
        _chip_schema(conn)
        conn.execute('INSERT OR IGNORE INTO daily_config VALUES(?,?)', ('activation', encoded({
            'activatedAt': now.isoformat(), 'scope': '本機台股日線庫', 'candidatePromotion': False,
            'note': '僅留存啟用後的當日收盤事件；缺日不回填，不代表通過研究門檻。'})))
    return status(path)


def status(path):
    if not Path(path).is_file():
        return {'enabled': False, 'events': 0, 'outcomes': 0, 'recent': [], 'status': 'disabled'}
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.execute('BEGIN')  # 啟用設定、事件與成熟結果必須出自同一讀取快照。
        cfg = json.loads(conn.execute("SELECT payload FROM daily_config WHERE key='activation'").fetchone()[0])
        last = conn.execute('SELECT payload FROM daily_runs ORDER BY at DESC LIMIT 1').fetchone()
        total = conn.execute('SELECT count(*) FROM daily_events').fetchone()[0]
        horizons = [{'horizon': horizon, 'resolved': conn.execute(
            'SELECT count(*) FROM daily_events e WHERE EXISTS '
            '(SELECT 1 FROM daily_outcomes o WHERE o.event_id=e.id AND o.horizon=?)', (horizon,)).fetchone()[0],
            'requiredFollowingSessions': horizon + 1} for horizon in (5, 20)]
        for item in horizons:
            item['pending'] = total - item['resolved']
        recent = [{'symbol': r[0], 'date': r[1], 'signalId': r[2], 'observedAt': r[3]}
                  for r in conn.execute('SELECT symbol,session_date,signal_id,observed_at FROM daily_events '
                                        'ORDER BY observed_at DESC,id LIMIT 20')]
        return {'enabled': True, **cfg, 'events': total,
                'outcomes': conn.execute('SELECT count(*) FROM daily_outcomes').fetchone()[0],
                'recent': recent, 'lastRun': json.loads(last[0]) if last else None,
                'forward': {'horizons': horizons, 'entry': 'next_session_close',
                            'eventRange': dict(zip(('first', 'last'), conn.execute(
                                'SELECT min(session_date),max(session_date) FROM daily_events').fetchone())),
                            'note': '由事件次一實際交易日收盤起算；5／20 日觀察須有事件後 6／21 個完整基準日及個股價格。'},
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
    calendar = session(today)
    tradable_dates = {}
    def tradable(day):
        if day not in tradable_dates:
            tradable_dates[day] = session(day)['status'] != 'closed'
        return tradable_dates[day]
    finalized = (now.hour, now.minute) >= (14, 0)
    benchmark = [b for b in benchmark if tradable(b['date']) and
                 (b['date'] < today or (finalized and b['date'] == today))]
    sessions = sorted({b['date'] for b in benchmark})
    counts = {'scanned': 0, 'currentSymbols': 0, 'eventsAdded': 0, 'outcomesAdded': 0,
              'asOf': stamp, 'sessionDate': today, 'historicalBackfill': False,
              'status': 'completed' if finalized and today in sessions else 'waiting',
              'reason': '以當日已收盤資料留存' if finalized and today in sessions else '等待當日收盤與大盤資料'}
    counts['calendar'] = calendar
    counts['excludedInstruments'] = []
    counts.update(chipChannelsComplete=0, chipChannelsExpected=0, missingChipInputs=[], priceInputs=0,
                  missingPriceSymbols=[], priceExclusions=[], outcomeProgress={
                      'byHorizon': {str(h): {} for h in (5, 20)}, 'samples': [], 'sampleLimit': 10})

    def excluded_price(symbol, bars, segments=None):
        last_day = bars[-1]['date'] if bars else None
        consecutive = len(segments[-1]) if segments else 0
        reason = ('missing_current_bar' if last_day != today else
                  'insufficient_history' if len(bars) < ss.MIN_BARS else 'incomplete_or_discontinuous_history')
        counts['missingPriceSymbols'].append(symbol)  # 保留舊客戶端欄位，詳情另列。
        counts['priceExclusions'].append({'symbol': symbol, 'reason': reason, 'lastBarDate': last_day,
                                         'availableBars': len(bars), 'continuousBars': consecutive,
                                         'requiredBars': ss.MIN_BARS})
    can_capture = finalized and today in sessions and calendar['status'] != 'closed'
    if calendar['status'] == 'closed':
        counts.update(status='closed', reason=calendar['reason'] + '；不要求當日日線')
    elif not finalized:
        counts.update(status='waiting', reason='尚未到收盤留存時間；14:00 後檢查當日日線')
    version = engine_digest()
    activated = datetime.fromisoformat(cfg['activatedAt']).astimezone(ss._TZ['TW']).date().isoformat()
    with closing(sqlite3.connect(path, timeout=30)) as conn, conn:
        _chip_schema(conn)
        for symbol, raw in series:
            bars = [b for b in raw if eligible_bar(symbol, b['date']) and
                    (b['date'] < today or (finalized and b['date'] == today))]
            lifecycle = instrument(symbol, today)
            inactive = trading_status(symbol, today)
            if inactive:
                counts['excludedInstruments'].append(inactive)
            counts['scanned'] += 1
            if len(bars) < ss.MIN_BARS:
                if can_capture and not inactive:
                    excluded_price(symbol, bars)
            input_id = digest([version, symbol, today])
            parts = continuous_segments(symbol, bars, sessions)
            current_bars = parts[-1] if parts else []
            if (can_capture and current_bars and current_bars[-1]['date'] == today
                    and len(current_bars) >= ss.MIN_BARS and today > activated):
                counts['currentSymbols'] += 1
                if not conn.execute('SELECT 1 FROM daily_inputs WHERE symbol=? AND session_date=?', (symbol, today)).fetchone():
                    stock_chips = []
                    result = ss.analyze(current_bars, symbol=symbol, chips=stock_chips, with_stats=False)
                    fresh = [e for e in result.get('events', []) if e['date'] == today and not e.get('provisional')
                             and ss.SIGNAL_BY_ID.get(e['signalId'], {}).get('family') != 'chip']
                    # 沒有事件亦保存當日掃描證據，避免重跑後行情修訂製造新事件。
                    payload = {'bars': current_bars, 'chips': stock_chips, 'benchmark': benchmark,
                               'engineDigest': version, 'evidence': result.get('evidence'),
                               'observedAt': stamp, 'source': 'datastore 唯讀快照'}
                    inserted = conn.execute('INSERT OR IGNORE INTO daily_inputs VALUES(?,?,?,?,?)',
                                 (input_id, symbol, today, version, zlib.compress(encoded(payload).encode('utf-8'))))
                    for ev in fresh if inserted.rowcount else []:
                        event_id = digest([input_id, ev['signalId']])
                        cur = conn.execute('INSERT OR IGNORE INTO daily_events VALUES(?,?,?,?,?,?,?)',
                                           (event_id, input_id, symbol, today, ev['signalId'], stamp, encoded(ev)))
                        counts['eventsAdded'] += cur.rowcount
                frozen = conn.execute('SELECT id,engine,payload FROM daily_inputs WHERE symbol=? AND session_date=?',
                                      (symbol, today)).fetchone()
                counts['priceInputs'] += 1
                added, complete, missing = _capture_chips(conn, frozen, symbol, today, stamp,
                                                          (chips or {}).get(symbol, []), version)
                counts['eventsAdded'] += added
                counts['chipChannelsExpected'] += 2
                counts['chipChannelsComplete'] += complete
                counts['missingChipInputs'].extend(missing)
            elif can_capture and not inactive:
                if len(bars) >= ss.MIN_BARS:
                    excluded_price(symbol, bars, parts)
            pending = conn.execute('SELECT e.id,e.session_date,e.input_id FROM daily_events e WHERE symbol=? '
                'AND (SELECT count(*) FROM daily_outcomes o WHERE o.event_id=e.id)<2', (symbol,)).fetchall()
            if not pending:
                continue
            first = min(e[1] for e in pending)
            invalid_dates = {b['date'] for b in bars if b['date'] > first and not ss.complete_bar(b)}
            for b in bars:
                if b['date'] > first and ss.complete_bar(b):
                    conn.execute('INSERT OR IGNORE INTO daily_prices VALUES(?,?,?,?)',
                                 (symbol, b['date'], stamp, encoded(b)))
            for event_id, origin, _ in pending:
                if not eligible_bar(symbol, origin):
                    continue
                saved_prices = {r[0]: json.loads(r[1]) for r in conn.execute(
                    'SELECT session_date,payload FROM daily_prices WHERE symbol=? AND session_date>?', (symbol, origin))
                    if eligible_bar(symbol, r[0])}
                prices = {day: bar for day, bar in saved_prices.items() if ss.complete_bar(bar)}
                invalid = (invalid_dates | (set(saved_prices) - set(prices))) - set(prices)
                for hz in (5, 20):
                    if conn.execute('SELECT 1 FROM daily_outcomes WHERE event_id=? AND horizon=?',
                                    (event_id, hz)).fetchone():
                        continue
                    progress = maturity_progress(origin, sessions, prices, hz)
                    progress['invalidPriceDates'] = [day for day in progress['expectedSessions'] if day in invalid]
                    if progress['status'] != 'ready':
                        groups = counts['outcomeProgress']['byHorizon'][str(hz)]
                        groups[progress['status']] = groups.get(progress['status'], 0) + 1
                        if len(counts['outcomeProgress']['samples']) < counts['outcomeProgress']['sampleLimit']:
                            counts['outcomeProgress']['samples'].append(
                                {'eventId': event_id, 'symbol': symbol, 'eventDate': origin, **progress})
                        continue
                    expected = progress['expectedSessions']
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
        if can_capture and today <= activated:
            counts.update(status='waiting', reason='啟用當日不回填；由下一個交易日開始留存')
        elif can_capture and counts['currentSymbols'] == 0:
            counts.update(status='waiting', reason='尚無符合完整歷史條件的當日個股輸入；請核對缺漏與排除原因')
        elif can_capture and (counts['missingPriceSymbols'] or counts['missingChipInputs']):
            counts.update(status='partial', reason='價量與籌碼分開留存；缺來源與歷史不足分列，僅當日新增事件可重試')
        for hz in (5, 20):
            unresolved = conn.execute('SELECT count(*) FROM daily_events e WHERE NOT EXISTS '
                '(SELECT 1 FROM daily_outcomes o WHERE o.event_id=e.id AND o.horizon=?)', (hz,)).fetchone()[0]
            groups = counts['outcomeProgress']['byHorizon'][str(hz)]
            unexamined = unresolved - sum(groups.values())
            if unexamined > 0:
                groups['not_evaluated_current_input'] = unexamined
        conn.execute('INSERT OR IGNORE INTO daily_runs VALUES(?,?)', (stamp, encoded(counts)))
    return counts
