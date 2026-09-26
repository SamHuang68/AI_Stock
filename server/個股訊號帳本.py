"""個股前瞻紀錄：沿用大盤帳本的追加、去重與凍結規則，使用獨立資料表。"""
from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

try:
    from . import stock_signals as ss
    from . import 個股訊號研究 as research
except ImportError:
    import stock_signals as ss
    import 個股訊號研究 as research


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def init(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.executescript('''
          CREATE TABLE IF NOT EXISTS stock_protocols(
            protocol_id TEXT PRIMARY KEY, registered_at TEXT NOT NULL, payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS stock_trials(
            trial_id TEXT PRIMARY KEY, protocol_id TEXT NOT NULL, symbol TEXT NOT NULL,
            origin_session TEXT NOT NULL, observed_at TEXT NOT NULL, payload TEXT NOT NULL,
            UNIQUE(protocol_id,symbol,origin_session));
          CREATE TABLE IF NOT EXISTS stock_trial_bars(
            trial_id TEXT NOT NULL, session_date TEXT NOT NULL, observed_at TEXT NOT NULL,
            payload TEXT NOT NULL, PRIMARY KEY(trial_id,session_date));
          CREATE TABLE IF NOT EXISTS stock_trial_chips(
            trial_id TEXT NOT NULL, session_date TEXT NOT NULL, observed_at TEXT NOT NULL,
            payload TEXT NOT NULL, PRIMARY KEY(trial_id,session_date));
          CREATE TABLE IF NOT EXISTS stock_outcomes(
            trial_id TEXT NOT NULL, horizon INTEGER NOT NULL, resolved_at TEXT NOT NULL,
            payload TEXT NOT NULL, PRIMARY KEY(trial_id,horizon));
        ''')


def register(path, report, engine_digest, now=None):
    now = now or datetime.now(ss._TZ['TW'])
    if now.tzinfo is None:
        raise ValueError('註冊時間必須包含時區')
    payload = {'researchDigest': research.digest(report), 'engineDigest': engine_digest,
               'policy': report['policy'], 'selection': report['selection'],
               'registeredAt': now.isoformat(), 'researchSummary': report['signals'],
               'historicalLimitations': report['limitations']}
    protocol_id = research.digest(payload)
    init(path)
    with closing(sqlite3.connect(path)) as conn, conn:
        conn.execute('INSERT OR IGNORE INTO stock_protocols VALUES(?,?,?)',
                     (protocol_id, now.isoformat(), _json(payload)))
    return protocol_id


def protocol(path, protocol_id):
    with closing(sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        row = conn.execute('SELECT payload FROM stock_protocols WHERE protocol_id=?', (protocol_id,)).fetchone()
    if not row:
        raise ValueError('找不到已凍結的研究協定')
    return json.loads(row[0])


def track(path, protocol_id, series, benchmark_bars, engine_digest, *, now=None, chips=None):
    """只觀察當日收盤事件；舊日期僅補齊已登錄試驗的結果，絕不新增歷史試驗。"""
    now = now or datetime.now(ss._TZ['TW'])
    if now.tzinfo is None:
        raise ValueError('觀察時間必須包含時區')
    now = now.astimezone(ss._TZ['TW'])
    cfg = protocol(path, protocol_id)
    if cfg['engineDigest'] != engine_digest:
        raise ValueError('計算程式版本已改變，拒絕沿用舊協定')
    counts = {'observationsAdded': 0, 'outcomesAdded': 0, 'historicalBackfill': False}
    if cfg['selection']['status'] != 'forward_only':
        return {**counts, 'status': 'inactive', 'reason': cfg['selection']['reason']}
    spec = ss.SIGNAL_BY_ID[cfg['selection']['signalId']]
    registered = datetime.fromisoformat(cfg['registeredAt']).astimezone(ss._TZ['TW'])
    today = now.date().isoformat()
    # 收盤後 30 分鐘才受理當日 K；盤中資料不得成為結果或新試驗。
    finalized_today = (now.hour, now.minute) >= (14, 0)
    benchmark_bars = [b for b in benchmark_bars if b['date'] < today or (b['date'] == today and finalized_today)]
    market = research.market_regimes(benchmark_bars)
    with closing(sqlite3.connect(path)) as conn, conn:
        for symbol, raw_bars in series:
            bars = [b for b in raw_bars if b['date'] < today or (b['date'] == today and finalized_today)]
            if not bars:
                continue
            chip_rows = [r for r in (chips or {}).get(symbol, []) if r['date'] <= bars[-1]['date']]
            chip_by_date = {r['date']: r for r in chip_rows}
            frame = ss.build_frame(bars, chip_rows)
            t = len(bars) - 1
            # 僅註冊後的下一個日期；註冊當日亦不回填。
            if (bars[-1]['date'] == today and today > registered.date().isoformat() and
                    research.context_matches(market.get(today), research.regime(frame, t), cfg['policy']['context']) and
                    t in ss.event_indices(frame, spec)):
                hit = spec['detect'](frame, t)
                trial_id = research.digest([protocol_id, symbol, today])
                payload = {'event': {'index': t, **hit}, 'signalId': spec['id'],
                           'invalidation': spec['invalidText'], 'inputBars': bars,
                           'chips': chip_rows,
                           'benchmarkBars': benchmark_bars, 'benchmarkDigest': research.digest(benchmark_bars),
                           'marketRegime': market[today],
                           'inputDigest': research.digest(frame), 'context': cfg['policy']['context'],
                           'priceBasis': cfg['policy']['priceBasis'],
                           'researchDigest': cfg['researchDigest']}
                cur = conn.execute('INSERT OR IGNORE INTO stock_trials VALUES(?,?,?,?,?,?)',
                                   (trial_id, protocol_id, symbol, today, now.isoformat(), _json(payload)))
                counts['observationsAdded'] += cur.rowcount
            trials = conn.execute('SELECT trial_id,origin_session,payload FROM stock_trials '
                                  'WHERE protocol_id=? AND symbol=?', (protocol_id, symbol)).fetchall()
            for trial_id, origin, text in trials:
                existing = {r[0] for r in conn.execute('SELECT horizon FROM stock_outcomes WHERE trial_id=?', (trial_id,))}
                if set(cfg['policy']['horizons']) <= existing:
                    continue
                frozen = json.loads(text)
                chip_key = 'trust' if spec['id'] == 'chip_trust_buy3' else 'foreign'
                for b in bars:
                    if b['date'] > origin:
                        conn.execute('INSERT OR IGNORE INTO stock_trial_bars VALUES(?,?,?,?)',
                                     (trial_id, b['date'], now.isoformat(), _json(b)))
                        chip = chip_by_date.get(b['date'])
                        if chip and chip.get(chip_key) is not None:
                            conn.execute('INSERT OR IGNORE INTO stock_trial_chips VALUES(?,?,?,?)',
                                         (trial_id, b['date'], now.isoformat(), _json(chip)))
                future = [json.loads(r[0]) for r in conn.execute(
                    'SELECT payload FROM stock_trial_bars WHERE trial_id=? ORDER BY session_date', (trial_id,))]
                combined = frozen['inputBars'] + future
                future_chips = [json.loads(r[0]) for r in conn.execute(
                    'SELECT payload FROM stock_trial_chips WHERE trial_id=? ORDER BY session_date', (trial_id,))]
                f = ss.build_frame(combined, frozen['chips'] + future_chips)
                t0 = frozen['event']['index']
                sessions = sorted(d for d in market if d > origin)
                for hz in cfg['policy']['horizons']:
                    if hz in existing:
                        continue
                    expected = sessions[:cfg['policy']['entryLag'] + hz]
                    actual = [b['date'] for b in future[:cfg['policy']['entryLag'] + hz]]
                    if len(expected) != cfg['policy']['entryLag'] + hz or actual != expected:
                        # 指數已知有交易但個股缺日，不能用後面的價格代替入場或到期。
                        continue
                    outs = ss.forward_outcomes(f, [t0], hz, 'bull', cfg['policy']['entryLag'])
                    if not outs:
                        continue
                    end = t0 + cfg['policy']['entryLag'] + hz
                    prices = combined[t0:end + 1]
                    lifecycle = ss._lifecycle(f, spec, frozen['event'], end)
                    if (spec['family'] == 'chip' and lifecycle['status'] != 'invalidated' and
                            any(f[chip_key][k] is None for k in range(t0 + 1, end + 1))):
                        lifecycle = {'status': 'unavailable', 'reason': '後續籌碼缺值，不能確認狀態'}
                    result = {**outs[0], 'horizon': hz, 'entryDate': f['date'][t0 + cfg['policy']['entryLag']],
                              'endDate': f['date'][end], 'prices': prices, 'pricesDigest': research.digest(prices),
                              'lifecycle': lifecycle, 'expectedSessions': expected,
                              'note': '各日價格依本機批次首次取得時凍結；依本機指數交易日對齊，已知缺日保持待補；未模擬成交。'}
                    cur = conn.execute('INSERT OR IGNORE INTO stock_outcomes VALUES(?,?,?,?)',
                                       (trial_id, hz, now.isoformat(), _json(result)))
                    counts['outcomesAdded'] += cur.rowcount
    return {**counts, 'status': 'observing', 'asOf': now.isoformat()}
