"""凍結前向觀測分母與事件協定；計算不取用外部來源或改寫輸入。"""
from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from copy import deepcopy
from decimal import Decimal
from contextlib import closing
from datetime import datetime, time, timezone, timedelta
from pathlib import Path

TZ = timezone(timedelta(hours=8))
VERSION = 'warning-observation-study/2026-09-v1'
PROTOCOL = {'version': VERSION, 'horizons': [1, 3, 5], 'materialMovePct': 2.0, 'minimumSample': 20,
            'minimumAvailableDomains': 3, 'closeAvailableHourTW': 18,
            'resolution': '首次到期發布即凍結成果；該次缺資料保留未知，後補或修訂不改寫',
            'denominator': '每個規則版本、訊號與市場日期的首次前向觀測，包含未觸發及未知',
            'event': '起點觀測價至未來指定交易日收盤路徑的同向最大變動至少百分之二',
            'benchmark': '同一觀測時點的加權指數漲跌方向與訊號方向一致',
            'overlap': '原始每日樣本與最早日期起選、下一起點晚於上一終點的非重疊樣本分列',
            'scope': '前瞻影子研究；不回填歷史分母，不是可交易報酬或預測機率'}


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def aware(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo is not None else None
    except (ValueError, TypeError):
        return None


def finite(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def finalized_close(row: dict | None, clock: datetime) -> bool:
    if row is None or not finite(row.get('close')) or row['close'] <= 0 or not row.get('source') or row.get('issues'):
        return False
    day = str(row.get('date') or '')
    as_of = aware(row.get('asOf'))
    observed = aware(row.get('observedAt'))
    if observed is not None and observed > clock:
        return False
    if as_of is not None:
        close_time = datetime.combine(datetime.fromisoformat(day).date(), time(13, 30), TZ)
        return close_time <= as_of <= clock
    # 舊 canonical 日歷史只有日期時，當天列仍可能是盤中暫存值。
    return str(row.get('asOf') or '') == day and day < clock.astimezone(TZ).date().isoformat()


def load_calendar(db_path: str | Path) -> dict:
    """只讀既有 TW 官方交易日曆；不建表、不呼叫可能連外的日曆更新器。"""
    try:
        with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True, timeout=10)) as conn:
            conn.execute('BEGIN')
            years = conn.execute('SELECT year,refreshed_at FROM calendar_years ORDER BY year').fetchall()
            rows = conn.execute('SELECT session_date,source FROM market_sessions ORDER BY session_date').fetchall()
        covered = {int(year) for year, _ in years}
        if any(not str(source).startswith(('TWSE', 'TPEX')) for day, source in rows if int(day[:4]) in covered):
            raise ValueError('日曆含未核對來源')
        dates = [day for day, source in rows if int(day[:4]) in covered]
        if not dates or not covered:
            raise ValueError('未建立官方市場日曆')
        return {'status': 'ready', 'market': 'TW', 'dates': dates, 'years': sorted(covered),
                'source': '官方市場交易日與年度日曆收據', 'sourceAsOf': max(str(at) for _, at in years),
                'version': digest({'dates': dates, 'years': sorted(covered)})}
    except (sqlite3.Error, ValueError, TypeError, OSError) as exc:
        return {'status': 'unknown', 'market': 'TW', 'dates': [], 'years': [], 'source': None,
                'sourceAsOf': None, 'version': None, 'reason': '官方市場日曆不可用：' + type(exc).__name__}


def freeze(context: dict, pulse: dict, memory: dict | None, evaluated: dict, signals: list[dict],
           market_ref: dict, calendar: dict | None, observed_at: str) -> list[dict]:
    """完整凍結首次觀測，包括無訊號與不可判斷資料；不替過去日期重造前瞻訊號。"""
    observed = aware(observed_at)
    if observed is None:
        raise ValueError('觀測時間必須含時區')
    calendar = calendar or {}
    origin = str(market_ref.get('sessionDate') or '')
    price = market_ref.get('price')
    dates = sorted(set(calendar.get('dates') or []))
    targets = [day for day in dates if day > origin][:5]
    calendar_at = aware(calendar.get('sourceAsOf'))
    market_at = aware(market_ref.get('asOf'))
    base_reason = None
    if calendar.get('status') != 'ready' or calendar.get('market') != 'TW' or not calendar.get('version') or origin not in dates or len(targets) != 5:
        base_reason = '缺少完整官方起點及未來五個交易日曆，漏報無法判定'
    elif calendar_at is None or calendar_at > observed:
        base_reason = '日曆來源時間未知或晚於觀測'
    elif not finite(price) or price <= 0 or market_at is None or market_at > observed or not market_ref.get('source'):
        base_reason = '起點市場價格或可取得時間不可確認'
    elif origin > observed.astimezone(TZ).date().isoformat():
        base_reason = '市場起點日期晚於實際觀測，不得使用未來資料'
    elif datetime.combine(datetime.fromisoformat(targets[0]).date(), time(9), TZ) <= observed:
        base_reason = '第一個目標交易日已開始，不能回填為前瞻觀測'
    quality = context.get('dataQuality') or {}
    if not base_reason and ((evaluated.get('dataQuality') or {}).get('availableDomains', 0) < PROTOCOL['minimumAvailableDomains'] or
                            not finite(quality.get('freshness')) or quality['freshness'] <= 0 or
                            not finite(quality.get('completeness')) or quality['completeness'] <= 0):
        base_reason = '可用證據不足或新鮮度未知，未觸發不能視為可靠陰性觀測'
    if not origin:
        origin = observed.astimezone(TZ).date().isoformat()
    quote = (pulse.get('marketSnapshot') or {}).get('quotes', {}).get('^TWII') or {}
    change = (quote.get('market') or {}).get('displayChangePct', quote.get('changePct'))
    results = []
    for signal in signals:
        engine = signal.get('engineVersion') or evaluated.get('model')
        policy = signal.get('policyVersion') or evaluated.get('policyVersion')
        protocol = {**deepcopy(PROTOCOL), 'engineVersion': engine, 'policyVersion': policy}
        protocol_id = digest(protocol)
        direction = signal.get('direction')
        reason = base_reason or (None if direction in ('upside', 'downside') else '方向混合或未知')
        if not evaluated.get('ok'):
            reason = reason or '輸入尚未完成可靠評估'
        sign = 1 if direction == 'upside' else -1
        benchmark = (change * sign > 0) if finite(change) else None
        replay = deepcopy({'context': context, 'pulse': pulse, 'memory': memory, 'evaluated': evaluated,
                  'signal': signal, 'marketReference': market_ref,
                  'calendar': {'version': calendar.get('version'), 'source': calendar.get('source'),
                               'sourceAsOf': calendar.get('sourceAsOf'), 'origin': origin, 'targets': targets}})
        results.append({'observationId': digest([protocol_id, signal.get('signalId'), origin]),
                        'protocolId': protocol_id, 'protocol': protocol, 'signalId': signal.get('signalId'),
                        'originSession': origin, 'observedAt': observed_at, 'direction': direction,
                        'originPrice': price if finite(price) else None, 'targetSessions': targets,
                        'eligible': reason is None, 'unknownReason': reason,
                        'alert': signal.get('state') in ('WATCH', 'ARMED', 'CONFIRMED', 'ACTIVE') if reason is None else None,
                        'benchmarkAlert': benchmark, 'episodeId': signal.get('firstSeenAt'),
                        'inputDigest': digest(replay), 'replay': replay, 'retrospectiveBackfill': False})
    return results


def resolve(record: dict, market_sessions: list[dict], now: str) -> list[dict]:
    clock = aware(now)
    if clock is None:
        raise ValueError('解析時間必須含時區')
    by_day = {row['date']: row for row in market_sessions}
    results = []
    for horizon in record['protocol']['horizons']:
        result = {'horizonSessions': horizon, 'status': 'immature', 'reason': '目標交易日尚未完成',
                  'targetSession': None, 'path': [], 'materialMoveHit': None, 'relativeLeadSessions': None,
                  'leadReason': '門檻到達時間不是相對基準領先時間'}
        targets = record.get('targetSessions') or []
        if not record.get('eligible'):
            result.update(status='unknown', reason=record.get('unknownReason'))
        elif len(targets) < horizon:
            result.update(status='unknown', reason='凍結日曆缺少目標交易日')
        else:
            target = targets[horizon - 1]
            result['targetSession'] = target
            if datetime.combine(datetime.fromisoformat(target).date(), time(record['protocol']['closeAvailableHourTW']), TZ) <= clock:
                path = [by_day.get(day) for day in targets[:horizon]]
                if any(not finalized_close(row, clock) for row in path):
                    result.update(status='unknown', reason='指定市場交易日收盤缺漏或未核對，不跳至下一筆')
                else:
                    sign = 1 if record['direction'] == 'upside' else -1
                    returns = [float((Decimal(str(row['close'])) / Decimal(str(record['originPrice'])) - 1) * 100 * sign) for row in path]
                    threshold = record['protocol']['materialMovePct']
                    result.update(status='mature', reason=None, path=path, directionalReturnPct=returns[-1],
                                  materialMoveHit=max(returns) >= threshold,
                                  eventArrivalSessions=next((i + 1 for i, value in enumerate(returns) if value >= threshold), None),
                                  closePathMaxFavorablePct=max([0] + returns), closePathMaxAdversePct=max([0] + [-value for value in returns]))
        results.append(result)
    return results


def summarize(records: list[dict], outcomes: dict[str, list[dict]], now: str) -> dict:
    strata = {}
    for record in records:
        key = (record['protocolId'], record['signalId'], record['direction'])
        strata.setdefault(key, []).append(record)
    groups = []
    for (protocol_id, signal_id, direction), samples in sorted(strata.items()):
        samples.sort(key=lambda item: item['originSession'])
        group = {'protocolId': protocol_id, 'protocol': samples[0]['protocol'], 'signalId': signal_id,
                 'direction': direction, 'observations': len(samples), 'startedAt': samples[0]['observedAt'], 'horizons': []}
        observed_dates = {item['originSession'] for item in samples}
        known_dates = {day for item in samples for day in item.get('targetSessions', [])
                       if samples[0]['originSession'] <= day <= samples[-1]['originSession']}
        missing_dates = sorted(known_dates - observed_dates)
        group.update(unobservedSessions=len(missing_dates), unobservedDates=missing_dates,
                     unobservedScope='只計首次到末次觀測間已凍結日曆可證明的缺日；更早、尾端及未涵蓋區間未知')
        for horizon in group['protocol']['horizons']:
            mature, unknown, immature, awaiting, independent = [], 0, 0, 0, []
            last_target = ''
            for record in samples:
                outcome = next((item for item in outcomes.get(record['observationId'], []) if item['horizonSessions'] == horizon), None)
                if outcome is None:
                    targets = record.get('targetSessions') or []
                    target = targets[horizon - 1] if len(targets) >= horizon else None
                    due = datetime.combine(datetime.fromisoformat(target).date(), time(record['protocol']['closeAvailableHourTW']), TZ) if target else None
                    if due is not None and aware(now) is not None and due <= aware(now):
                        awaiting += 1
                    else:
                        immature += 1
                    continue
                if outcome['status'] != 'mature':
                    unknown += 1
                    continue
                mature.append((record, outcome))
                if record['originSession'] > last_target:
                    independent.append((record, outcome))
                    last_target = outcome['targetSession']
            events = [(record, outcome) for record, outcome in mature if outcome['materialMoveHit']]
            alarms = [(record, outcome) for record, outcome in mature if record['alert']]
            missed = sum(not record['alert'] for record, _ in events)
            false_alerts = sum(not outcome['materialMoveHit'] for _, outcome in alarms)
            paired = [(record, outcome) for record, outcome in mature if record['benchmarkAlert'] is not None]
            paired_events = [(record, outcome) for record, outcome in paired if outcome['materialMoveHit']]
            minimum = group['protocol']['minimumSample']
            group['horizons'].append({'sessions': horizon, 'mature': len(mature), 'immature': immature,
                'unknown': unknown, 'awaitingResolution': awaiting,
                'nonOverlapping': len(independent), 'overlapExcluded': len(mature) - len(independent),
                'materialEvents': len(events), 'alerts': len(alarms), 'missedEvents': missed, 'falseAlerts': false_alerts,
                'observedMissRatePct': missed / len(events) * 100 if len(events) >= minimum else None,
                'falseAlertRatePct': false_alerts / len(alarms) * 100 if len(alarms) >= minimum else None,
                'benchmarkPairedEvents': len(paired_events),
                'signalCapturePct': sum(record['alert'] for record, _ in paired_events) / len(paired_events) * 100 if len(paired_events) >= minimum else None,
                'benchmarkCapturePct': sum(record['benchmarkAlert'] for record, _ in paired_events) / len(paired_events) * 100 if len(paired_events) >= minimum else None,
                'populationMissRatePct': None, 'populationMissReason': '未觀測日期與研究開始以前的分母未知，不能外推完整市場漏報率'})
        groups.append(group)
    return {'version': VERSION, 'status': 'collecting' if records else 'not_started', 'observations': len(records),
            'strata': groups, 'retrospectiveBackfill': False,
            'notes': ['每個版本每日首次觀測凍結；舊訊號帳本不回填無警報分母。',
                      '本研究衡量每日首次快照，盤中後續轉移另存於既有事件帳本，兩者不是同一分母。',
                      '未知、未成熟與未觀測分開；漏報只對已完整觀測的事件計算。',
                      '門檻到達交易日數不是領先其他方法的時間；風險數字只代表收盤路徑。',
                      '每日事件區間可重疊；非重疊樣本另列，樣本門檻不是顯著性證明。']}
