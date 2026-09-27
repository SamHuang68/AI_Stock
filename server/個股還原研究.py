"""既有行情來源的還原快照及成本敏感度；不覆寫原價、不產生候選。"""
import json
import math
import statistics
from contextlib import closing
from datetime import datetime

import stock_signals as ss

TABLE = 'stock_adjustment_snapshots'
COSTS = (0, 20, 50, 100)


def save_snapshot(symbol, market, pack):
    import datastore
    dates, close, adjusted = pack['timestamps'], pack['quoteClose'], pack['adjclose']
    if len(dates) != len(close) or len(dates) != len(adjusted):
        raise ValueError('還原序列長度不一致')
    rows = []
    for ts, raw, adj in zip(dates, close, adjusted):
        if raw is None or adj is None:
            continue
        if not all(math.isfinite(float(v)) and float(v) > 0 for v in (raw, adj)):
            raise ValueError('還原價格無效')
        rows.append({'date': ss.bar_date(ts, market), 'rawClose': raw, 'adjClose': adj})
    if not rows:
        raise ValueError('來源未提供可用還原價格')
    payload = {'rows': rows, 'events': pack['events'], 'source': pack['source'],
               'fetchedAt': pack['fetchedAt'], 'priceBasis': 'vendor_adjusted_snapshot'}
    # 同一市場、股票保留多次來源快照；新研究只取最新一次，不拼接不同還原基準。
    with datastore._db_write_lock, closing(datastore.get_conn()) as conn, conn:
        conn.execute(f'CREATE TABLE IF NOT EXISTS {TABLE}(market TEXT, symbol TEXT, fetched_at INTEGER, '
                     'payload TEXT NOT NULL, PRIMARY KEY(market,symbol,fetched_at))')
        conn.execute(f'INSERT OR IGNORE INTO {TABLE} VALUES(?,?,?,?)',
                     (market, symbol, pack['fetchedAt'], json.dumps(payload, ensure_ascii=False, allow_nan=False)))
    return len(rows)


def load_snapshot(connection, symbol, market='TW'):
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (TABLE,)).fetchone():
        return None
    row = connection.execute(f'SELECT payload FROM {TABLE} WHERE market=? AND symbol=? '
                             'ORDER BY fetched_at DESC LIMIT 1', (market, symbol)).fetchone()
    return json.loads(row[0]) if row else None


def adjusted_bars(bars, snapshot):
    """完整且相容才接納，不能因缺日壓縮事件天數。"""
    values = {r['date']: r for r in (snapshot or {}).get('rows', [])}
    out = []
    for b in bars:
        r = values.get(b['date'])
        if not r or not math.isclose(r['rawClose'], b['close'], rel_tol=0.0001, abs_tol=0.005):
            return None
        factor = r['adjClose'] / r['rawClose']
        if not math.isfinite(factor) or factor <= 0:
            return None
        out.append({**b, **{key: b[key] * factor for key in ('open', 'high', 'low', 'close')}})
    return out


def net_return(gross, round_trip_bps):
    if not math.isfinite(round_trip_bps) or not 0 <= round_trip_bps <= 1000:
        raise ValueError('往返成本須介於 0 與 1000 基點')
    side = round_trip_bps / 20000
    return (1 + gross) * (1 - side) / (1 + side) - 1


def summary(values):
    return {'n': len(values), 'gate': 'ok' if len(values) >= ss.MIN_SAMPLE else 'insufficient',
            'medianRet': statistics.median(values) if len(values) >= ss.MIN_SAMPLE else None,
            'upRatio': sum(v > 0 for v in values) / len(values) if len(values) >= ss.MIN_SAMPLE else None}


class Sensitivity:
    def __init__(self, connection, sessions, market='TW'):
        self.connection, self.market = connection, market
        self.positions = {d: i for i, d in enumerate(sessions)}
        self.covered, self.missing = [], []
        self.rows = {s['id']: {h: {'raw': [], 'adjusted': [], 'commonRaw': [], 'commonAdjusted': [],
                                  'rawEvents': 0, 'adjustedEvents': 0, 'commonEvents': 0}
                             for h in ss.STAT_HORIZONS} for s in ss.SIGNALS}

    def add(self, symbol, bars, chips):
        snapshot = load_snapshot(self.connection, symbol, self.market)
        adjusted = adjusted_bars(bars, snapshot)
        if not adjusted:
            self.missing.append(symbol)
            return
        self.covered.append({'symbol': symbol, 'from': bars[0]['date'], 'to': bars[-1]['date'],
                             'fetchedAt': snapshot['fetchedAt'],
                             'dividends': len(snapshot['events'].get('dividends') or {}),
                             'splits': len(snapshot['events'].get('splits') or {})})
        raw, adj = ss.build_frame(bars, chips), ss.build_frame(adjusted, chips)
        dates = raw['date']
        for spec in ss.SIGNALS:
            raw_starts, adj_starts = set(ss.event_indices(raw, spec)), set(ss.event_indices(adj, spec))
            for hz in ss.STAT_HORIZONS:
                def mature(starts, frame):
                    return {o['t']: o['ret'] for o in ss.forward_outcomes(frame, sorted(starts), hz, 'bull', 1)
                            if dates[o['t']] in self.positions and
                            all(self.positions.get(dates[k]) == self.positions[dates[o['t']]] + k - o['t']
                                for k in range(o['t'], o['t'] + hz + 2))}
                r, a = mature(raw_starts, raw), mature(adj_starts, adj)
                common = sorted(r.keys() & a.keys())
                row = self.rows[spec['id']][hz]
                row['raw'].extend(r.values()); row['adjusted'].extend(a.values())
                row['commonRaw'].extend(r[t] for t in common)
                row['commonAdjusted'].extend(a[t] for t in common)
                row['rawEvents'] += len(r); row['adjustedEvents'] += len(a); row['commonEvents'] += len(common)

    def finish(self):
        signals = []
        for spec in ss.SIGNALS:
            horizons = []
            for hz, row in self.rows[spec['id']].items():
                horizons.append({'horizon': hz,
                    **{k: row[k] for k in ('rawEvents', 'adjustedEvents', 'commonEvents')},
                    'raw': summary(row['raw']), 'adjusted': summary(row['adjusted']),
                    'commonRaw': summary(row['commonRaw']), 'commonAdjusted': summary(row['commonAdjusted']),
                    'costScenarios': [{'roundTripBps': cost, **summary([net_return(v, cost) for v in row['adjusted']])}
                                      for cost in COSTS]})
            signals.append({'signalId': spec['id'], 'label': spec['label'], 'horizons': horizons})
        return {'version': 'st-price-sensitivity/v1', 'covered': self.covered, 'missingSymbols': self.missing,
                'coveredSymbols': len(self.covered), 'totalSymbols': len(self.covered) + len(self.missing),
                'status': 'available' if self.covered else 'missing', 'signals': signals,
                'method': '原價與供應商還原快照各用同一引擎，次日收盤起算；成本於進出各計往返假設的一半。',
                'limitations': ['目前重編的還原價格不是歷史點時資料；不改寫原始價格與既有候選。',
                                '只分析完整覆蓋的股票；覆蓋不足不可外推全市場。',
                                '供應商原價可能已處理股票分割；此處比較供應商 quote 與 adjclose，不重複套用分割。',
                                '成本是 0／20／50／100 基點的假設；未模擬撮合、稅制、最低手續費與漲跌停成交。']}
