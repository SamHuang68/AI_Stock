"""以官方日線與明確交易日曆計算事件；讀取端不補值、不抓取遠端資料。"""
from __future__ import annotations

import json
import math
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from statistics import mean, median

try:
    from .台股日線 import TZ, latest_session
except ImportError:
    from 台股日線 import TZ, latest_session

HORIZONS = (1, 3, 5, 10)
RULES = {
    'long_red': ('長紅 K', '（收盤−開盤）／開盤 ≥ 1.5%'),
    'long_black': ('長黑 K', '（收盤−開盤）／開盤 ≤ −1.5%'),
    'doji': ('十字線', '｜收盤−開盤｜／開盤 ≤ 0.2%'),
    'volume': ('成交量異常', '成交股數 > 前 20 個交易日均量 × 1.5'),
    'break_high': ('突破 20 日高點', '收盤 > 前 20 個交易日最高價'),
    'break_low': ('跌破 20 日低點', '收盤 < 前 20 個交易日最低價'),
}


def freshness(conn: sqlite3.Connection, symbol: str, now: datetime | None = None) -> dict:
    now = (now or datetime.now(TZ)).astimezone(TZ)
    result = {'expectedSession': None, 'latestSession': None, 'status': '無法確認', 'fresh': False}
    row = conn.execute("SELECT MAX(ts) FROM bars WHERE symbol=? AND market='TW'", (symbol,)).fetchone()
    if row and row[0]:
        result['latestSession'] = datetime.fromtimestamp(row[0], TZ).date().isoformat()
    try:
        rows = conn.execute('SELECT year,closed,opened,refreshed_at FROM calendar_years WHERE year IN (?,?)', (now.year, now.year - 1)).fetchall()
        if not any(r[0] == now.year for r in rows):
            return result
        closed = {date.fromisoformat(d) for r in rows for d in json.loads(r[1])}
        opened = {date.fromisoformat(d) for r in rows for d in json.loads(r[2])}
        expected = latest_session(now, closed, opened).isoformat()
        result['expectedSession'] = expected
        result['calendarAsOf'] = max(r[3] for r in rows if r[0] == now.year)
        result['calendarRecent'] = now - datetime.fromisoformat(result['calendarAsOf']) <= timedelta(days=7)
        result['exchanges'] = dict(conn.execute('SELECT exchange,MAX(session_date) FROM daily_imports GROUP BY exchange'))
        official = conn.execute("SELECT 1 FROM bar_quality WHERE market='TW' AND symbol=? AND session_date=? AND source IN ('TWSE','TPEX')", (symbol, expected)).fetchone()
        complete = all(result['exchanges'].get(ex) == expected for ex in ('TWSE', 'TPEX'))
        result['fresh'] = bool(official and result['latestSession'] == expected and complete and result['calendarRecent'])
        result['status'] = '已核對最新交易日' if result['fresh'] else '尚未完整更新'
        state = conn.execute('SELECT payload FROM daily_update_state WHERE id=1').fetchone()
        if state:
            payload = json.loads(state[0])
            result['update'] = {k: payload.get(k) for k in ('status', 'startedAt', 'finishedAt', 'expectedSession')}
            if payload.get('expectedSession') == expected and not payload.get('ok'):
                result['fresh'] = False
                result['status'] = '更新中或區間資料尚未完整'
    except (sqlite3.OperationalError, ValueError, TypeError, json.JSONDecodeError):
        result['status'] = '尚未建立官方更新紀錄'
    return result


def valid_number(value: object, positive: bool = True) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and (value > 0 if positive else value >= 0)


def signals(current: dict, previous: list[dict]) -> tuple[list[str], dict]:
    """僅使用當日及前二十日，Decimal 保留門檻等號語意。"""
    o, c = Decimal(str(current['open'])), Decimal(str(current['close']))
    body = (c - o) / o
    avg = sum(Decimal(str(r['volume'])) for r in previous) / Decimal(20)
    high, low = max(r['high'] for r in previous), min(r['low'] for r in previous)
    flags = [body >= Decimal('.015'), body <= Decimal('-.015'), abs(body) <= Decimal('.002'),
             Decimal(str(current['volume'])) > avg * Decimal('1.5'), current['close'] > high, current['close'] < low]
    return [key for key, hit in zip(RULES, flags) if hit], {'bodyPct': float(body * 100), 'volumeRatio': float(Decimal(str(current['volume'])) / avg), 'priorHigh': high, 'priorLow': low}


def distribution(values: list[float]) -> dict:
    ordered = sorted(values)
    def quantile(p):
        at = (len(ordered) - 1) * p
        low = int(at)
        return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (at - low)
    return {'n': len(values), 'mean': mean(values) if values else None, 'median': median(values) if values else None,
            'positivePct': sum(v > 0 for v in values) / len(values) * 100 if values else None,
            'q25': quantile(.25) if values else None, 'q75': quantile(.75) if values else None,
            'smallSample': len(values) < 30}


def report(db: str | Path, symbol: str = '2330', as_of: str | None = None, now: datetime | None = None) -> dict:
    now = (now or datetime.now(TZ)).astimezone(TZ)
    cutoff = date.fromisoformat(as_of) if as_of else now.date()
    if cutoff > now.date():
        raise ValueError('截至日期不得晚於今天')
    with closing(sqlite3.connect(db, timeout=15)) as conn, conn:
        status = freshness(conn, symbol, now)
        expected = status['expectedSession']
        cutoff = min(cutoff, date.fromisoformat(expected)) if expected else cutoff
        start = cutoff - timedelta(days=365 * 3)
        raw = conn.execute('''SELECT b.ts,b.open,b.high,b.low,b.close,b.volume,q.session_date,q.source,q.issues,q.volume_unit
            FROM bars b LEFT JOIN bar_quality q ON b.market=q.market AND b.symbol=q.symbol AND b.ts=q.ts
            WHERE b.market='TW' AND b.symbol=? AND b.ts>=? AND b.ts<? ORDER BY b.ts''',
            (symbol, int(datetime.combine(start, datetime.min.time(), TZ).timestamp()), int(datetime.combine(cutoff + timedelta(days=1), datetime.min.time(), TZ).timestamp()))).fetchall()
        sessions = [r[0] for r in conn.execute('SELECT session_date FROM market_sessions WHERE session_date BETWEEN ? AND ? ORDER BY session_date', (start.isoformat(), cutoff.isoformat()))]
        action_days = {r[0] for r in conn.execute("SELECT session_date FROM corporate_actions WHERE market='TW' AND symbol=? AND session_date BETWEEN ? AND ?", (symbol, start.isoformat(), cutoff.isoformat()))}
        coverage = conn.execute("SELECT start_date,end_date,source FROM action_coverage WHERE market='TW' AND symbol=?", (symbol,)).fetchone()
        name = conn.execute("SELECT name FROM meta WHERE market='TW' AND symbol=?", (symbol,)).fetchone()
    by_day, unverified = {}, 0
    for row in raw:
        day = row[6] or datetime.fromtimestamp(row[0], TZ).date().isoformat()
        issues = json.loads(row[8]) if row[8] else []
        if row[7] not in ('TWSE', 'TPEX'):
            issues = [*issues, '歷史來源尚未經官方核對']
            unverified += 1
        if row[9] != '股':
            issues = [*issues, '成交量單位未核對']
        record = dict(zip(('time', 'open', 'high', 'low', 'close', 'volume'), row[:6]))
        prices = row[1:5]
        if not all(valid_number(v) for v in row[1:6]):
            issues = [*issues, '價格或成交量缺值／無成交']
        elif not prices[2] <= min(prices[0], prices[3]) <= max(prices[0], prices[3]) <= prices[1]:
            issues = [*issues, '開高低收邊界無效']
        if day in by_day:
            issues = [*issues, '同一交易日資料重複']
        by_day[day] = {**record, 'date': day, 'issues': sorted(set(issues)), 'source': row[7], 'signals': []}
    # 日曆中缺少一日就保留缺口，後續第 N 日不會變成第 N 筆可用資料。
    rows = [by_day.get(day, {'date': day, 'issues': ['交易日資料缺漏'], 'signals': [], **{k: None for k in ('time', 'open', 'high', 'low', 'close', 'volume')}}) for day in sessions]
    def covered(first: str, last: str) -> bool:
        return bool(coverage and coverage[0] <= first <= last <= coverage[1])
    for i, row in enumerate(rows):
        if i and valid_number(row['close']) and valid_number(rows[i - 1]['close']) and abs(row['close'] / rows[i - 1]['close'] - 1) > .15:
            action_days.add(row['date'])
        row['eligible'] = False
        if row['issues']:
            row['reason'] = '；'.join(row['issues'])
        elif i < 20:
            row['reason'] = '前 20 個交易日暖機資料不足'
        elif any(r['issues'] for r in rows[i - 20:i]):
            row['reason'] = '前 20 個交易日含缺值或未核對資料'
        elif not covered(rows[i - 20]['date'], row['date']):
            row['reason'] = '公司行動涵蓋區間尚未核對'
        elif any(rows[i - 20]['date'] < d <= row['date'] for d in action_days):
            row['reason'] = '20 日比較區間跨公司行動或重大價格斷點'
        else:
            row['eligible'] = True
            row['signals'], row['metrics'] = signals(row, rows[i - 20:i])
            row['reason'] = '符合事件條件' if row['signals'] else '未出現特殊事件'
    def outcome(i: int, horizon: int) -> dict:
        if i + horizon >= len(rows):
            return {'value': None, 'reason': '資料不足：尚未走完後續交易日'}
        segment = rows[i:i + horizon + 1]
        if any(r['issues'] for r in segment):
            return {'value': None, 'reason': '區間含缺值、無成交或未核對資料'}
        if not covered(segment[0]['date'], segment[-1]['date']):
            return {'value': None, 'reason': '公司行動區間尚未核對'}
        if any(segment[0]['date'] < d <= segment[-1]['date'] for d in action_days):
            return {'value': None, 'reason': '跨公司行動或重大價格斷點，已排除'}
        return {'value': (segment[-1]['close'] / segment[0]['close'] - 1) * 100, 'reason': None}
    for i, row in enumerate(rows):
        row['returns'] = {str(h): outcome(i, h) for h in HORIZONS} if row['eligible'] else {str(h): {'value': None, 'reason': row['reason']} for h in HORIZONS}
    stats = []
    for key, (label, _) in RULES.items():
        group = {'key': key, 'label': label, 'cases': sum(key in r['signals'] for r in rows), 'horizons': {}}
        for h in HORIZONS:
            candidates = [(i, r['returns'][str(h)]['value']) for i, r in enumerate(rows) if key in r['signals'] and r['returns'][str(h)]['value'] is not None]
            baseline = [r['returns'][str(h)]['value'] for r in rows if r['eligible'] and r['returns'][str(h)]['value'] is not None]
            independent, last = [], -1
            for i, value in candidates:
                if i > last:
                    independent.append(value)
                    last = i + h
            raw_stats, base_stats = distribution([v for _, v in candidates]), distribution(baseline)
            group['horizons'][str(h)] = {'raw': raw_stats, 'nonOverlapping': distribution(independent), 'baseline': base_stats,
                                      'difference': raw_stats['mean'] - base_stats['mean'] if candidates and baseline else None}
        stats.append(group)
    shown = rows[-30:]
    return {'sym': symbol, 'name': name[0] if name else symbol, 'asOf': cutoff.isoformat(), 'freshness': status,
            'historyStart': sessions[0] if sessions else None, 'historyEnd': sessions[-1] if sessions else None,
            'historyRows': len(raw), 'eligibleDays': sum(r['eligible'] for r in rows), 'unverifiedRows': unverified,
            'companyActionCoverage': {'start': coverage[0], 'end': coverage[1], 'source': coverage[2]} if coverage else None,
            'candles': shown, 'events': [r for r in reversed(shown) if r['signals']], 'stats': stats,
            'rules': [{'key': k, 'label': v[0], 'formula': v[1]} for k, v in RULES.items()],
            'notes': ['黃色點只代表事件日；同日可有多個標籤，不代表買賣建議。',
                      '報酬以事件日收盤至後續第 1、3、5、10 個市場交易日收盤計算，採原始價格，未含股息、稅費。',
                      '事件與基準共用資料品質、20 日暖機及公司行動排除條件。基準為同一期間所有可判定日期。',
                      '非重疊樣本由最早成熟事件起選取，下一事件須晚於前一事件的報酬終點。',
                      '小樣本標記門檻為 30 筆，僅為閱讀提醒；平均差異並非統計顯著性或未來優勢。',
                      '截至日期只限制可用交易期；使用目前已核對資料，並非重建當時發布版本。未成熟報酬不納入統計。']}
