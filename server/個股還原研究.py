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
    if not row:
        return None
    payload = json.loads(row[0])
    payload['symbol'] = symbol
    return payload


def _split_events(snapshot):
    """只使用明示的公司行動；不從價差反推分割比率。"""
    events = {}
    for event in ((snapshot or {}).get('events', {}).get('splits') or {}).values():
        try:
            ratio = float(event['numerator']) / float(event['denominator'])
            day = ss.bar_date(event['date'])
            if day and math.isfinite(ratio) and ratio > 0:
                events[day] = {'date': day, 'ratio': ratio, 'source': snapshot.get('source')}
        except (ValueError, TypeError, KeyError, ZeroDivisionError):
            continue
    from 台股交易參考 import split_references
    for event in split_references((snapshot or {}).get('symbol')):
        # 不覆蓋供應商同日事件；若兩者不一致，保留待核對。
        if event['date'] not in events:
            events[event['date']] = event
    through = max((r['date'] for r in (snapshot or {}).get('rows', [])), default='')
    return sorted((e for e in events.values() if e['date'] <= through), key=lambda e: e['date'], reverse=True)


def _basis_match(bar, row, events):
    close = bar.get('close')
    if not isinstance(close, (int, float)) or not math.isfinite(close) or close <= 0:
        return None, []
    if math.isclose(row['rawClose'], bar['close'], rel_tol=.0001, abs_tol=.005):
        return 1.0, []
    ratio, used = 1.0, []
    for event in events:
        if event['date'] <= bar['date']:
            break
        ratio *= event['ratio']
        used.append(event)
        if math.isclose(bar['close'] / ratio, row['rawClose'], rel_tol=.0001, abs_tol=.005):
            return ratio, list(used)
    return None, []


def adjusted_bars(bars, snapshot):
    """完整且相容才接納，不能因缺日壓縮事件天數。"""
    values = {r['date']: r for r in (snapshot or {}).get('rows', [])}
    events = _split_events(snapshot)
    from 台股交易參考 import trading_status
    if any(trading_status((snapshot or {}).get('symbol'), b['date']) for b in bars):
        return None
    out = []
    for b in bars:
        r = values.get(b['date'])
        if not ss.complete_bar(b) or not r or _basis_match(b, r, events)[0] is None:
            return None
        # 本機舊日線可能尚未納入較新的分割；先驗證事件與原價，再直接轉到同一還原基準。
        factor = r['adjClose'] / b['close']
        if not math.isfinite(factor) or factor <= 0:
            return None
        out.append({**b, **{key: b[key] * factor for key in ('open', 'high', 'low', 'close')}})
    return out


def adjusted_segments(bars, snapshot, sessions, market='TW'):
    """回收可驗證區段；共同日期、獨立暖機，不修改完整覆蓋的既有契約。"""
    from 台股交易參考 import continuous_segments, session
    if not snapshot:
        return []
    values = {r['date']: r for r in snapshot.get('rows', [])}
    events = _split_events(snapshot)
    result = []
    # 先按原始索引切開不相容列，避免個股與大盤同日缺漏時掩蓋中斷。
    compatible, groups = [], []
    for bar in bars:
        if market == 'TW' and session(bar['date'])['status'] == 'closed':
            continue
        row = values.get(bar['date'])
        if ss.complete_bar(bar) and row and _basis_match(bar, row, events)[0] is not None:
            compatible.append(bar)
        else:
            if compatible:
                groups.append(compatible)
            compatible = []
    if compatible:
        groups.append(compatible)
    for group in groups:
        parts = continuous_segments(snapshot.get('symbol'), group, sessions) if market == 'TW' else [group]
        for raw in parts:
            if len(raw) < ss.MIN_BARS:
                continue
            adjusted = adjusted_bars(raw, snapshot)
            if adjusted:
                result.append({'raw': raw, 'adjusted': adjusted})
    return result


def alignment_issues(bars, snapshot):
    """保留未接納原因；來源取得成功不等於與既有原價相容。"""
    if not snapshot:
        return {'status': 'missing_snapshot', 'label': '尚無來源快照', 'missingDates': [], 'priceMismatches': []}
    from 台股交易參考 import instrument, references, trading_status
    lifecycle = instrument(snapshot.get('symbol'))
    invalid_dates = [b['date'] for b in bars if trading_status(snapshot.get('symbol'), b['date'])]
    values = {r['date']: r for r in snapshot.get('rows', [])}
    events = _split_events(snapshot)
    missing, mismatches, conversions = [], [], {}
    for bar in bars:
        row = values.get(bar['date'])
        if not row or not ss.complete_bar(bar):
            missing.append(bar['date'])
        else:
            ratio, used = _basis_match(bar, row, events)
            if ratio is None:
                mismatches.append({'date': bar['date'], 'localClose': bar['close'], 'sourceClose': row['rawClose']})
            elif ratio != 1:
                key = tuple(e['date'] for e in used)
                group = conversions.setdefault(key, {'from': bar['date'], 'to': bar['date'], 'bars': 0,
                    'ratio': ratio, 'events': used})
                group['to'] = bar['date']
                group['bars'] += 1
    return {'status': 'incompatible' if missing or mismatches or invalid_dates else 'aligned',
            'label': '停止交易期間仍有價格列，保留原始資料並排除研究' if invalid_dates else
                     ('來源缺日或與本機原價不一致' if missing or mismatches else '完整相容'),
            'invalidTradeDates': invalid_dates, 'instrument': lifecycle,
            'verifiedFindings': references().get('sourceFindings', {}).get(snapshot.get('symbol'), []),
            'missingDates': missing, 'priceMismatches': mismatches,
            'basisConversions': list(conversions.values()),
            'fetchedAt': snapshot.get('fetchedAt'), 'source': snapshot.get('source')}


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
    def __init__(self, connection, sessions, market='TW', *, partial_mode=False):
        self.connection, self.market = connection, market
        self.positions = {d: i for i, d in enumerate(sessions)}
        self.covered, self.missing = [], []
        self.missing_details = []
        self.partial_mode = partial_mode
        self.partial = None if partial_mode else Sensitivity(connection, sessions, market, partial_mode=True)
        self.rows = {s['id']: {h: {'raw': [], 'adjusted': [], 'commonRaw': [], 'commonAdjusted': [],
                                  'rawEvents': 0, 'adjustedEvents': 0, 'commonEvents': 0}
                             for h in ss.STAT_HORIZONS} for s in ss.SIGNALS}

    def add(self, symbol, bars, chips):
        snapshot = load_snapshot(self.connection, symbol, self.market)
        adjusted = adjusted_bars(bars, snapshot)
        if not adjusted:
            self.missing.append(symbol)
            self.missing_details.append({'symbol': symbol, **alignment_issues(bars, snapshot)})
            if self.partial is not None:
                for part in adjusted_segments(bars, snapshot, self.positions, market=self.market):
                    self.partial.add(symbol, part['raw'], chips)
            return
        self.covered.append({'symbol': symbol, 'from': bars[0]['date'], 'to': bars[-1]['date'],
                             'fetchedAt': snapshot['fetchedAt'],
                             'basisConversions': alignment_issues(bars, snapshot)['basisConversions'],
                             'dividends': len(snapshot['events'].get('dividends') or {}),
                             'splits': len(snapshot['events'].get('splits') or {})})
        # 完整覆蓋亦可能有交易日缺口；原價與還原價必須用相同區段重新暖機。
        from 台股交易參考 import continuous_segments
        adjusted_by_date = {b['date']: b for b in adjusted}
        parts = continuous_segments(symbol, bars, self.positions) if self.market == 'TW' else [bars]
        for part in parts:
            if len(part) >= ss.MIN_BARS:
                self._add_continuous(part, [adjusted_by_date[b['date']] for b in part], chips)

    def _add_continuous(self, bars, adjusted, chips):
        raw, adj = ss.build_frame(bars, chips), ss.build_frame(adjusted, chips)
        dates = raw['date']
        for spec in ss.SIGNALS:
            raw_starts, adj_starts = set(ss.event_indices(raw, spec)), set(ss.event_indices(adj, spec))
            for hz in ss.STAT_HORIZONS:
                def mature(starts, frame):
                    return {o['t']: o['ret'] for o in ss.forward_outcomes(frame, sorted(starts), hz, 'bull', 1)
                            if (not self.partial_mode or o['t'] >= ss.MIN_BARS - 1)
                            and dates[o['t']] in self.positions and
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
        out = {'version': 'st-price-sensitivity/v3', 'covered': self.covered, 'missingSymbols': self.missing,
                'missingDetails': self.missing_details,
                'snapshotSymbols': len({r['symbol'] for r in self.covered}) + sum(d['status'] != 'missing_snapshot' for d in self.missing_details),
                'coveredSymbols': len({r['symbol'] for r in self.covered}),
                'totalSymbols': len({r['symbol'] for r in self.covered}) + len(self.missing),
                'reconciledSymbols': len({r['symbol'] for r in self.covered if r['basisConversions']}),
                'status': 'available' if self.covered else 'missing', 'signals': signals,
                'method': '原價與供應商還原快照各用同一引擎，次日收盤起算；成本於進出各計往返假設的一半。',
                'limitations': ['目前重編的還原價格不是歷史點時資料；不改寫原始價格與既有候選。',
                                '公司行動只用於驗證本機與供應商的價格基準；逐日對得上才轉換，原始差異與來源快照仍保留。',
                                '只分析完整覆蓋的股票；覆蓋不足不可外推全市場。',
                                '供應商原價可能已處理股票分割；此處比較供應商 quote 與 adjclose，不重複套用分割。',
                                '成本是 0／20／50／100 基點的假設；未模擬撮合、稅制、最低手續費與漲跌停成交。']}
        if self.partial is not None:
            out['partial'] = self.partial.finish()
        else:
            out.update(windowCount=len(self.covered),
                       coveredBars=sum(self.positions[r['to']] - self.positions[r['from']] + 1 for r in self.covered),
                       method='只含原先整檔未接納股票的連續相容區段；每段至少 70 根暖機，缺口不拼接，候選門檻不變。')
            out['limitations'].append('部分區段另列，不併入完整覆蓋；來源 close 相容不代表全部 OHLCV 已經官方逐筆認證。')
            out['limitations'][2] = '只分析已核對的連續區段，並非完整個股歷史；覆蓋不足不可外推全市場。'
        return out
