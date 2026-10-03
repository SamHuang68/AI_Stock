"""真實前瞻帳本的即時唯讀診斷；不補事件、價格、結果或執行收據。"""
import hashlib
import json
import math
import sqlite3
import zlib
from collections import Counter
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

import stock_signals as ss
import 每日個股留存 as daily
from 個股訊號研究 import digest
from 台股交易參考 import eligible_bar, session

VERSION = 'st-forward-diagnostics/v1'
SAMPLE_LIMIT = 12


def validate_outcome(payload, horizon, origin):
    """沿用凍結結果的價格重現契約；未留存結果回傳缺值。"""
    if payload is None:
        return None
    value = json.loads(payload)
    prices, dates = value['prices'], value['expectedSessions']
    if (value['horizon'] != horizon or len(prices) != horizon + 1 or len(dates) != horizon + 1
            or dates != sorted(set(dates)) or dates[0] <= origin
            or [bar['date'] for bar in prices] != dates
            or value['entryDate'] != dates[0] or value['endDate'] != dates[-1]
            or value['pricesDigest'] != digest(prices) or any(not ss.complete_bar(bar) for bar in prices)):
        raise ValueError('成熟結果的價格與日期不一致')
    if daily.maturity_progress(origin, dates, dates, horizon)['status'] != 'ready':
        raise ValueError('成熟結果存在交易日缺口，不得順延湊期')
    entry = float(prices[0]['close'])
    if not math.isfinite(entry) or entry <= 0:
        raise ValueError('進場價格無效')
    ret = float(prices[-1]['close']) / entry - 1
    adverse = min(float(bar['low']) for bar in prices[1:]) / entry - 1
    if not all(math.isfinite(x) for x in (ret, adverse, value['ret'], value['adverse'])):
        raise ValueError('結果不是有限數值')
    if not math.isclose(ret, value['ret'], abs_tol=1e-10) or not math.isclose(adverse, value['adverse'], abs_tol=1e-10):
        raise ValueError('成熟結果不能由凍結價格重現')
    return value


def validate_event(event_id, input_id, signal, symbol, day, version, compressed, event_payload):
    """核對既有識別雜湊與凍結來源；舊規則自成一組，不當作毀損。"""
    try:
        if not version:
            return None, 'invalid_version'
        frozen = json.loads(zlib.decompress(compressed))
        if frozen['engineDigest'] != version:
            return None, 'invalid_version'
        event = json.loads(event_payload)
        if (frozen['bars'][-1]['date'] != day or input_id != digest([version, symbol, day])
                or event_id != digest([input_id, signal]) or event['date'] != day
                or event['signalId'] != signal or event.get('provisional')):
            return None, 'invalid_evidence'
        date.fromisoformat(day)
        return frozen, None
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, zlib.error):
        return None, 'invalid_evidence'


def _clock(now):
    now = now or datetime.now(ss._TZ['TW'])
    if now.tzinfo is None:
        raise ValueError('診斷時間必須含時區')
    return now.astimezone(ss._TZ['TW'])


def _completed(day, now):
    date.fromisoformat(day)
    return (day < now.date().isoformat() or
            (day == now.date().isoformat() and (now.hour, now.minute) >= (14, 0)))


def load_sessions(market_path, now):
    """只讀已存在的大盤日線，不用日曆表定日或舊事件輸入代替實際基準。"""
    if not Path(market_path).is_file():
        return [], {'status': 'unavailable', 'reason': '尚無本機大盤資料庫'}
    import datastore
    with datastore.read_snapshot(market_path) as conn:
        bars = ss.normalize_bars(datastore.get_bars_bulk(['^TWII'], connection=conn).get('^TWII') or [])
    dates = [b['date'] for b in bars if ss.complete_bar(b) and _completed(b['date'], now)
             and session(b['date'])['status'] != 'closed']
    return dates, {'status': 'available' if dates else 'unavailable', 'source': '本機大盤日線唯讀快照'}


def _fingerprint(value):
    if value is None:
        return None
    return hashlib.sha256(value if isinstance(value, bytes) else str(value).encode('utf-8')).hexdigest()


def inspect_ledger(conn, sessions, *, now, rules, sample_limit=SAMPLE_LIMIT, benchmark_source=None):
    """在呼叫者的同一讀取交易內核對，內部狀態索引不對外輸出。"""
    sessions = sorted({day for day in sessions if _completed(day, now) and session(day)['status'] != 'closed'})
    records = conn.execute('SELECT e.id,e.input_id,e.signal_id,e.symbol,e.session_date,i.engine,'
                           'i.payload,e.payload,e.observed_at FROM daily_events e '
                           'LEFT JOIN daily_inputs i ON i.id=e.input_id ORDER BY e.session_date,e.id').fetchall()
    outcomes = {(r[0], r[1]): (r[2], r[3]) for r in conn.execute(
        'SELECT event_id,horizon,payload,resolved_at FROM daily_outcomes')}
    prices = {}
    for symbol in sorted({r[3] for r in records}):
        prices[symbol] = {}
        for day, stamp, payload in conn.execute(
                'SELECT session_date,observed_at,payload FROM daily_prices WHERE symbol=? ORDER BY session_date', (symbol,)):
            try:
                bar = json.loads(payload)
                valid = (bar['date'] == day and _completed(day, now) and eligible_bar(symbol, day) and ss.complete_bar(bar))
            except (ValueError, TypeError, KeyError, AttributeError):
                valid = False
            prices[symbol][day] = {'valid': valid, 'observedAt': stamp}
    counts = {str(h): Counter() for h in (5, 20)}
    due = Counter()
    samples, states = [], {}
    seen_samples = set()
    for event_id, input_id, signal, symbol, origin, version, compressed, event_payload, observed_at in records:
        frozen, invalid = validate_event(event_id, input_id, signal, symbol, origin, version, compressed, event_payload)
        try:
            if not _completed(origin, now):
                invalid = 'invalid_evidence'
        except (ValueError, TypeError):
            invalid = 'invalid_evidence'
        valid_prices = [d for d, value in prices[symbol].items() if value['valid']]
        for horizon in (5, 20):
            try:
                progress = daily.maturity_progress(origin, sessions, valid_prices, horizon)
            except (ValueError, TypeError):
                progress = {'horizon': horizon, 'requiredFollowingSessions': horizon + 1,
                            'observedFollowingSessions': 0, 'expectedSessions': [],
                            'missingPriceDates': [], 'missingBenchmarkDates': []}
                invalid = 'invalid_evidence'
            payload, resolved_at = outcomes.get((event_id, horizon), (None, None))
            state = invalid
            if not state:
                try:
                    result = validate_outcome(payload, horizon, origin)
                    if result is not None and any(not _completed(day, now) for day in result['expectedSessions']):
                        raise ValueError('結果含尚未完成的日期')
                    if result is not None and any(not eligible_bar(symbol, day) for day in result['expectedSessions']):
                        raise ValueError('結果含已知不可交易的日期')
                    state = 'mature' if result is not None else (
                        'ready_unrecorded' if progress['status'] == 'ready' else progress['status'])
                    if result is None and not sessions:
                        state = 'missing_benchmark_sessions'
                except (ValueError, TypeError, KeyError, IndexError, ZeroDivisionError, AttributeError):
                    state = 'invalid_evidence'
            states[(event_id, horizon)] = state
            counts[str(horizon)][state] += 1
            if state != 'mature' and progress['observedFollowingSessions'] >= horizon + 1:
                due[horizon] += 1
            # 每個原因／期間保留第一例，再依固定排序補充；不任意截斷完整帳本。
            sample = {'eventId': event_id, 'inputId': input_id, 'rulesDigest': version,
                      'currentRules': version == rules, 'symbol': symbol, 'signalId': signal, 'eventDate': origin,
                      **progress, 'status': state, 'eventFirstRecordedAt': observed_at,
                      'inputFirstRecordedAt': frozen.get('observedAt') if frozen else None,
                      'inputPayloadDigest': _fingerprint(compressed), 'eventPayloadDigest': _fingerprint(event_payload),
                      'outcomeRecordedAt': resolved_at, 'outcomePayloadDigest': _fingerprint(payload),
                      'observedPriceDates': [d for d in progress['expectedSessions'] if d in valid_prices],
                      'invalidPriceDates': [d for d in progress['expectedSessions']
                                            if d in prices[symbol] and not prices[symbol][d]['valid']],
                      'priceFirstRecordedAt': [{'date': d, 'observedAt': prices[symbol][d]['observedAt']}
                                               for d in progress['expectedSessions'] if d in prices[symbol]]}
            sample_key = (state, horizon)
            if sample_key not in seen_samples:
                samples.insert(len(seen_samples), sample)
                seen_samples.add(sample_key)
            elif len(samples) < sample_limit:
                samples.append(sample)
            samples = samples[:sample_limit]
    horizons = []
    for h in (5, 20):
        reasons = dict(sorted(counts[str(h)].items()))
        mature = reasons.get('mature', 0)
        pending = len(records) - mature
        horizons.append({'horizon': h, 'mature': mature, 'pending': pending, 'due': due[h],
                         'waiting': pending - due[h], 'reasons': reasons,
                         'requiredFollowingSessions': h + 1,
                         'readyUnrecorded': reasons.get('ready_unrecorded', 0),
                         'unverified': reasons.get('invalid_version', 0) + reasons.get('invalid_evidence', 0)})
    ids = {r[0] for r in records}
    last = conn.execute('SELECT payload FROM daily_runs ORDER BY at DESC LIMIT 1').fetchone()
    report = {'version': VERSION, 'enabled': True, 'checkedAt': now.isoformat(), 'events': len(records),
              'benchmarkAsOf': sessions[-1] if sessions else None,
              'benchmarkSource': {**(benchmark_source or {}), 'status': 'available' if sessions else 'unavailable'},
              'horizons': horizons, 'byHorizon': {h: dict(sorted(values.items())) for h, values in counts.items()},
              'samples': samples, 'sampleLimit': sample_limit, 'totalEventHorizons': 2 * len(records),
              'orphans': sum(eid not in ids or h not in (5, 20) for eid, h in outcomes),
              'storedResults': len(outcomes), 'lastRun': json.loads(last[0]) if last else None,
              'currentRulesDigest': rules, 'externalCalls': 0, 'readOnly': True, 'candidatePromotion': False,
              'note': '即時唯讀核對；次一實際交易日收盤進場，5／20日須有事件後6／21個實際基準日與首次留存價格。'
                      '缺日不順延；未成熟不是零報酬，滿20筆僅展示描述統計，不證明策略有效。',
              'traceNote': '雜湊供核對目前帳本內容，並非外部簽章；時間僅顯示原有欄位，未留存即為缺值。'
                           '個股日期以帳本首次留存價格核對，不以後來行情快取替代。'
                           '即時診斷與上次留存收據分開，讀取不產生成熟結果。'}
    return report, states


def read_diagnostics(path, sessions=None, *, now=None, sample_limit=SAMPLE_LIMIT):
    now = _clock(now)
    if not Path(path).is_file():
        return {'version': VERSION, 'enabled': False, 'events': 0, 'horizons': [], 'orphans': 0,
                'samples': [], 'byHorizon': {}, 'readOnly': True, 'externalCalls': 0, 'candidatePromotion': False}
    source = {'status': 'available', 'source': '呼叫端本機大盤唯讀快照'}
    if sessions is None:
        sessions, source = load_sessions(Path(path).parent / 'market.db', now)
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        conn.execute('PRAGMA query_only=ON')
        conn.execute('BEGIN')
        report, _ = inspect_ledger(conn, sessions, now=now, rules=daily.engine_digest(),
                                   sample_limit=sample_limit, benchmark_source=source)
    return report
