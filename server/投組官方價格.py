"""完整官方原價與既有公司行動比較；不覆寫原價或拼接還原快照。"""
import math
from decimal import Decimal

from 公司行動比較 import Comparison, PRICE_BASIS, load_adjustments
from daily_quality import _equal
from 台股交易參考 import split_references, trading_status, verified_sessions
from 官方價格交叉核對 import load_receipts, reconcile


def full_history(connection, symbol, bars, evidence):
    if not bars:
        return {}, {}, '缺少歷史'
    first, last = bars[0]['date'], bars[-1]['date']
    sessions = verified_sessions(first, last, connection=connection)
    if not sessions or sessions[0] != first or sessions[-1] != last:
        return {}, {}, '完整歷史交易日曆尚未核對'
    expected = {day for day in sessions if trading_status(symbol, day) is None}
    raw = {b['date']: b for b in bars}
    if not expected <= raw.keys():
        return {}, {}, '完整歷史缺少應有交易日原價'
    splits = split_references(symbol)
    rows, conversions, exclusions, reconciled = [], [], [], []
    try:
        crosschecks = load_receipts(connection, symbol)
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        return {}, {}, '第二官方收據無法核對：' + str(exc)
    for bar in bars:
        day = bar['date']
        if day not in expected:
            exclusions.append({'date': day, 'reason': '已核對休市或個股停止交易',
                               'reference': trading_status(symbol, day)})
            continue
        item = evidence.get(day, {})
        official = item.get('officialPrices') or {}
        if (any(item.get(k) for k in ('sourceConflict', 'ambiguousSession', 'invalidObservation', 'invalidReceipt'))
                or official.get('status') != 'verified' or not official.get('receiptIds')):
            return {}, {}, '完整歷史缺少一致的官方原價收據：' + day
        prices = official['values']
        original = [bar.get(k) for k in ('open', 'high', 'low', 'close')]
        if not all(_equal(a, b) for a, b in zip(original, prices)):
            # 僅明示的精確股數分割比可解釋儲存基準；官方比較因子仍由 Comparison 核對。
            ratio, used, matched = 1.0, [], False
            for event in sorted(splits, key=lambda e: e['date'], reverse=True):
                if not day < event['date'] <= last:
                    continue
                ratio *= event['ratio']
                used.append(event)
                if all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                       and _equal(v * ratio, price) for v, price in zip(original, prices)):
                    matched = True
                    break
            if not matched:
                resolution = reconcile(day, original, prices, crosschecks)
                if resolution is None:
                    return {}, {}, '原價差異缺少一致的第二官方報表：' + day
                reconciled.append({**resolution, 'primaryReceiptIds': official['receiptIds']})
            else:
                conversions.append({'date': day, 'rawPrices': original, 'officialPrices': prices,
                                    'ratio': ratio, 'events': list(used), 'receiptIds': official['receiptIds']})
        rows.append({**bar, **dict(zip(('open', 'high', 'low', 'close'), prices)),
                     'source': 'TWSE', 'priceBasis': 'unadjusted', 'issues': []})
    if not rows or rows[0]['date'] != first or rows[-1]['date'] != last:
        return {}, {}, '完整歷史起訖價格無效'
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    actions = {r[0] for r in connection.execute('SELECT session_date FROM corporate_actions WHERE market=? AND symbol=? AND session_date>? AND session_date<=?',
        ('TW', symbol, first, last))} if 'corporate_actions' in tables else set()
    actions.update(e['date'] for e in splits if first < e['date'] <= last)
    comparison = Comparison(rows, load_adjustments(connection, symbol, last), actions)
    reason = comparison.reason(0, len(rows) - 1)
    if reason:
        return {}, {}, reason
    values = {}
    for row in rows:
        value = Decimal(str(row['close']))
        for day, factor in comparison.factors.items():
            if row['date'] < day <= last:
                value *= factor
        number = float(value)
        if not math.isfinite(number) or number <= 0:
            return {}, {}, '官方比較價格無效'
        values[row['date']] = number
    if len(values) != len(rows):
        return {}, {}, '官方比較價格日期不唯一'
    detail = {'priceBasis': PRICE_BASIS, 'anchorDate': last, 'historyStart': first, 'historyEnd': last,
              'excludedDates': [], 'excludedObservations': exclusions, 'basisConversions': conversions,
              'reconciledPrices': reconciled,
              'adjustmentEvidence': comparison.evidence(0, len(rows) - 1),
              'excludedReturnDates': [day for before, day in zip(sessions, sessions[1:]) if before not in values or day not in values],
              'limitations': ['官方參考價比值含價格捨入，不等同股利再投資總報酬或供應商還原價。', '使用目前已核對歷史，非歷史點時資訊。']}
    return values, detail, None
