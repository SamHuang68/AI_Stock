"""以既有資料建立估值承接觀察；不推算未來盈餘或保證價格修復。"""
from __future__ import annotations

import json
import math
import re
from concurrent.futures import as_completed
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

TZ_TPE = timezone(timedelta(hours=8))
IP_REVIEW = {'3529': '力旺', '6643': 'M31'}
PE_DATASETS = ('exchangeReport/BWIBBU_ALL', 'tpex:tpex_mainboard_peratio_analysis')
REVENUE_DATASETS = ('t187ap05_L', 'tpex:mopsfin_t187ap05_O')


def number(value: Any) -> float | None:
    """缺值、布林值與非有限數字皆不冒充可用觀測。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value).replace(',', '').strip())
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def validate_settings(raw: Mapping[str, Any]) -> dict[str, Any]:
    pe_max = number(raw.get('peMax', 30))
    if pe_max is None or not 0 < pe_max <= 200:
        raise ValueError('本益比上限須為大於 0 且不超過 200 的有限數值。')
    exclude_ip = raw.get('excludeIp', True)
    if not isinstance(exclude_ip, bool):
        raise ValueError('另案估值排除設定須為布林值。')
    return {'peMax': pe_max, 'excludeIp': exclude_ip}


def value_from(row: Mapping[str, Any] | None, *names: str) -> float | None:
    for key in names:
        if row and key in row:
            value = number(row[key])
            if value is not None:
                return value
    return None


def contains_number(row: Mapping[str, Any] | None, includes: Sequence[str]) -> float | None:
    for key, value in (row or {}).items():
        if all(part in key for part in includes):
            found = number(value)
            if found is not None:
                return found
    return None


def source_date(value: Any) -> str | None:
    """僅解析來源明載日期，未知時不以抓取日期補值。"""
    raw = str(value or '').strip()
    try:
        if re.fullmatch(r'\d{8}', raw):
            return date(int(raw[:4]), int(raw[4:6]), int(raw[6:])).isoformat()
        if re.fullmatch(r'\d{7}', raw):
            return date(int(raw[:3]) + 1911, int(raw[3:5]), int(raw[5:])).isoformat()
        match = re.fullmatch(r'(\d{3,4})[-/](\d{1,2})[-/](\d{1,2})', raw)
        if match:
            year, month, day = map(int, match.groups())
            return date(year + 1911 if year < 1911 else year, month, day).isoformat()
    except ValueError:
        pass
    return None


def parse_valuation(row: Mapping[str, Any] | None, dataset: str | None) -> dict[str, Any]:
    row = row or {}
    as_of = next((parsed for key in ('Date', '日期', '資料日期', '交易日期', 'TradingDate')
                  if (parsed := source_date(row.get(key)))), None)
    return {
        'per': value_from(row, '本益比', 'PEratio', 'PriceEarningRatio'),
        'yield': value_from(row, '殖利率', 'DividendYield', 'Yield'),
        'valuationDate': as_of,
        'valuationSource': ('TWSE BWIBBU_ALL' if dataset == PE_DATASETS[0]
                            else 'TPEx peratio' if dataset == PE_DATASETS[1] else None),
    }


def scope_reason(code: str, pe: float | None, settings: Mapping[str, Any]) -> str | None:
    if not re.fullmatch(r'[1-9]\d{3}', code):
        return 'excludedNonStock'
    if settings['excludeIp'] and code in IP_REVIEW:
        return 'excludedIp'
    if pe is None or pe <= 0:
        return 'excludedPeInvalid'
    if pe > settings['peMax']:
        return 'excludedPeAbove'
    return None


def parse_revenue(row: Mapping[str, Any] | None) -> dict[str, Any]:
    row = row or {}
    return {
        'revenuePeriod': row.get('資料年月') or row.get('period'),
        'revYoy': contains_number(row, ('去年同月增減',)) if 'yoyPct' not in row else number(row['yoyPct']),
        'revenueMom': contains_number(row, ('上月比較增減',)) if 'momPct' not in row else number(row['momPct']),
        'revenueCumYoy': contains_number(row, ('累計', '前期比較增減')) if 'cumYoyPct' not in row else number(row['cumYoyPct']),
    }


def completed_bars(payload: Mapping[str, Any], now: datetime) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    results = (payload.get('chart') or {}).get('result') or []
    result = results[0] if results else {}
    quotes = ((result.get('indicators') or {}).get('quote') or [{}])[0]
    timestamps = result.get('timestamp') or []
    closes = quotes.get('close') or []
    local = now.astimezone(TZ_TPE)
    by_day: dict[str, dict[str, Any]] = {}
    for index, timestamp in enumerate(timestamps):
        if index >= len(closes):
            continue
        close = number(closes[index])
        if close is None or close <= 0:
            continue
        try:
            bar_day = datetime.fromtimestamp(float(timestamp), TZ_TPE).date()
        except (TypeError, ValueError, OSError, OverflowError):
            continue
        if bar_day > local.date() or (bar_day == local.date() and local.time() < time(13, 30)):
            continue
        bar = {'date': bar_day.isoformat(), 'close': close}
        for field in ('high', 'low', 'volume'):
            values = quotes.get(field) or []
            bar[field] = number(values[index]) if index < len(values) else None
        by_day[bar['date']] = bar
    return [by_day[key] for key in sorted(by_day)], result.get('meta') or {}


def price_observation(bars: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    close = bars[-1]['close'] if bars else None
    prior = bars[-21:-1] if len(bars) >= 21 else []
    valid_range = bool(prior) and all(b.get('high') is not None and b.get('low') is not None
                                      and 0 < b['low'] <= b['high'] for b in prior)
    top = max(b['high'] for b in prior) if valid_range else None
    bottom = min(b['low'] for b in prior) if valid_range else None
    prior_volumes = [number(bar.get('volume')) for bar in prior]
    current_volume = number(bars[-1].get('volume')) if bars else None
    volume_mean = (sum(prior_volumes) / 20 if len(prior_volumes) == 20
                   and all(value is not None and value >= 0 for value in prior_volumes) else None)
    vol_ratio = (current_volume / volume_mean if volume_mean and current_volume is not None
                 and current_volume >= 0 else None)
    distance = (top - close) / top * 100 if top and close else None
    state = None
    if top and bottom and close:
        if close > top:
            state = '帶量越過' if vol_ratio is not None and vol_ratio >= 1.5 else '越過但量未確認'
        elif close < bottom:
            state = '跌破下緣'
        elif distance is not None and distance <= 2:
            state = '接近上緣'
        else:
            state = '區間內'
    peak = max(b['close'] for b in bars[-100:]) if len(bars) >= 100 else None
    return {
        'priceAsOf': bars[-1]['date'] if bars else None,
        'priceBasis': '已完成交易日日收盤',
        'drawdown100': round((close / peak - 1) * 100, 2) if peak else None,
        'rangeTop': round(top, 4) if top else None,
        'rangeBottom': round(bottom, 4) if bottom else None,
        'distanceToTopPct': round(distance, 2) if distance is not None else None,
        'rangePosition': state,
        'volRatio': round(vol_ratio, 2) if vol_ratio is not None else None,
        'breakoutVolumeRatio': round(vol_ratio, 2) if vol_ratio is not None else None,
        'breakoutVolumeBasis': '當日成交量／之前二十個完整交易日平均成交量',
    }


def load_chip_snapshots(directory: str) -> dict[str, Mapping[str, Any]]:
    snapshots: dict[str, Mapping[str, Any]] = {}
    for path in sorted(Path(directory).glob('*.json'), reverse=True)[:60]:
        day = source_date(path.stem)
        if not day:
            continue
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(payload, dict):
                snapshots[day] = payload
        except (OSError, ValueError):
            continue
    return snapshots


def chip_observation(code: str, session_dates: Sequence[str], snapshots: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """只使用每股明載來源交易日；快照檔名不構成交易日證明。"""
    required = list(session_dates[-5:])
    dated: dict[str, Mapping[str, Any]] = {}
    missing_source_date = False
    conflicting_source_date = False
    for snapshot_day in sorted(snapshots):
        record = snapshots[snapshot_day].get(code)
        if not isinstance(record, dict):
            continue
        explicit_dates = {parsed for key in ('sourceDate', 'tradingDate', 'tradeDate', 'sessionDate', 'session_date')
                          if (parsed := source_date(record.get(key)))}
        if not explicit_dates:
            missing_source_date = True
            continue
        if len(explicit_dates) != 1:
            conflicting_source_date = True
            continue
        actual_day = next(iter(explicit_dates))
        if required and actual_day <= required[-1]:
            dated[actual_day] = record
    trust_values: list[float | None] = []
    foreign_values: list[float | None] = []
    for day in required:
        record = dated.get(day, {})
        trust_values.append(number(record.get('trust')))
        foreign_values.append(number(record.get('foreign')))
    def streak(values: Sequence[float | None]) -> int | None:
        if len(values) != 5 or any(value is None for value in values):
            return None
        sign = 1 if values[-1] > 0 else -1 if values[-1] < 0 else 0
        count = 0
        for value in reversed(values):
            if sign and value * sign > 0:
                count += 1
            else:
                break
        return count * sign
    latest_day, latest_value = None, None
    for day in sorted(dated, reverse=True):
        value = number(dated[day].get('trust'))
        if value is not None:
            latest_day, latest_value = day, value
            break
    complete = len(trust_values) == 5 and all(value is not None for value in trust_values)
    date_issue = None
    if not complete:
        if missing_source_date:
            date_issue = '既有籌碼快照未保存來源交易日'
        elif conflicting_source_date:
            date_issue = '籌碼快照來源交易日不一致'
    return {
        'trustLatestShares': latest_value, 'trustAsOf': latest_day,
        'trustNet5d': sum(trust_values) if complete else None,
        'trustObservedDays': sum(value is not None for value in trust_values),
        'trustRequiredDays': 5, 'trustSessionDates': required,
        'trustStreak': streak(trust_values), 'foreignStreak': streak(foreign_values),
        'chipSource': '既有籌碼快照（僅接受明載來源交易日）', 'chipDateIssue': date_issue,
    }


def run_screen(body: Mapping[str, Any], *, settings: Mapping[str, Any], symbols: Sequence[str],
               universe_source: str, lookup: Callable, monthly_revenue: Callable,
               names: Mapping[str, str], fetch_quote: Callable, calc_ind: Callable,
               tech_match: Callable, pool: Any, chip_history_path: str,
               now: datetime | None = None, detail: bool = False) -> dict[str, Any]:
    """來源由既有伺服器注入，先官方估值查表再取得日線。"""
    now = now or datetime.now(TZ_TPE)
    codes = sorted({str(symbol).replace('.TWO', '').replace('.TW', '').strip().upper() for symbol in symbols})
    meta = {key: 0 for key in ('valuationPassed', 'priceCompleted', 'excludedIp', 'excludedPeAbove',
                              'excludedPeInvalid', 'excludedNonStock', 'missingPrice', 'missingRevenue', 'missingChip')}
    meta.update({'enabled': True, 'initialUniverse': len(codes), 'universeSource': universe_source,
                 'peMax': settings['peMax'], 'excludeIp': settings['excludeIp']})
    candidates: dict[str, dict[str, Any]] = {}
    for code in codes:
        early_reason = scope_reason(code, settings['peMax'], settings)
        if early_reason and not detail:
            meta[early_reason] += 1
            continue
        raw, dataset = None, None
        for dataset_name in PE_DATASETS:
            raw = lookup([dataset_name], code)
            if raw:
                dataset = dataset_name
                break
        valuation = parse_valuation(raw, dataset)
        reason = scope_reason(code, valuation['per'], settings)
        if reason:
            meta[reason] += 1
        if not reason or detail:
            valuation['scopeEligible'] = reason is None
            valuation['scopeReason'] = {
                'excludedIp': '使用者指定另案估值，預設不納入一般估值範圍',
                'excludedPeInvalid': '缺少有效正本益比，尚未通過獲利估值前提',
                'excludedPeAbove': '本益比超出目前設定上限',
                'excludedNonStock': '本研究只接受四位數普通股',
            }.get(reason)
            candidates[code] = valuation
    meta['valuationPassed'] = sum(value['scopeEligible'] for value in candidates.values())
    snapshots = load_chip_snapshots(chip_history_path)
    futures = {pool.submit(fetch_quote, code + ('.TWO' if val['valuationSource'] == 'TPEx peratio' else '.TW'),
                           rng='1y', interval='1d'): code for code, val in candidates.items()}
    results = []
    tech_pass = 0
    tech, fund, chip = body.get('tech') or {}, body.get('fund') or {}, body.get('chip') or {}
    for future in as_completed(futures):
        code = futures[future]
        bars, quote_meta = [], {}
        ind = {'close': None}
        price_ok = False
        try:
            _, raw, _ = future.result()
            payload = json.loads(raw) if raw else {}
            bars, quote_meta = completed_bars(payload, now)
            actual_code = str(quote_meta.get('symbol') or code).replace('.TWO', '').replace('.TW', '')
            if actual_code != code or len(bars) < 70:
                raise ValueError('日線資料不足或股票代號不一致')
            closes = [bar['close'] for bar in bars]
            highs = [bar['high'] if bar['high'] is not None else bar['close'] for bar in bars]
            lows = [bar['low'] if bar['low'] is not None else bar['close'] for bar in bars]
            volumes = [bar['volume'] if bar['volume'] is not None else 0 for bar in bars]
            ind = calc_ind(closes, highs, lows, volumes)
            price_ok = True
        except Exception:
            meta['missingPrice'] += 1
            if not detail:
                continue
            bars, ind = [], {'close': None}
        if price_ok:
            meta['priceCompleted'] += 1
        if not detail and not tech_match(tech, ind):
            continue
        if price_ok:
            tech_pass += 1
        rev = lookup(list(REVENUE_DATASETS), code)
        if not rev or contains_number(rev, ('當月營收',)) is None:
            for market in ('otc', 'sii'):
                fallback = monthly_revenue(market, code)
                if fallback and number(fallback.get('monthRev')) is not None:
                    rev = fallback
                    break
        revenue = parse_revenue(rev)
        observations = chip_observation(code, [bar['date'] for bar in bars], snapshots)
        vol_ratio = number(ind.get('volRatio')) if all(bar['volume'] is not None for bar in bars[-20:]) else None
        research = {**candidates[code], **revenue, **price_observation(bars), **observations,
                    'epsBasis': 'official_pe_only',
                    'valuationModel': '另案估值' if code in IP_REVIEW else '一般估值',
                    'missing': []}
        if research['valuationDate'] is None:
            research['missing'].append('官方本益比未附資料日')
        if revenue['revYoy'] is None:
            meta['missingRevenue'] += 1
            research['missing'].append('最新月營收年增資料不足')
        if observations['trustObservedDays'] < 5:
            meta['missingChip'] += 1
            research['missing'].append('同組五個交易日籌碼資料不完整')
        if observations['chipDateIssue']:
            research['missing'].append(observations['chipDateIssue'])
        if research['drawdown100'] is None:
            research['missing'].append('未滿一百個交易日日線')
        if research['rangePosition'] is None:
            research['missing'].append('前二十日高低價資料不足')
        if research['breakoutVolumeRatio'] is None:
            research['missing'].append('當日或之前二十日成交量資料不足')
        checks = ((fund.get('revYoyMin'), revenue['revYoy'], 'min'),
                  (fund.get('yieldMin'), candidates[code]['yield'], 'min'),
                  (chip.get('trustBuyDays'), observations['trustStreak'], 'min'),
                  (chip.get('foreignBuyDays'), observations['foreignStreak'], 'min'))
        if not detail and any(threshold is not None and (number(threshold) is None or value is None or value < number(threshold))
               for threshold, value, _ in checks):
            continue
        results.append({'sym': code, 'name': names.get(code) or code, 'close': ind['close'],
                        'changePct': round(ind['changePct'], 2) if ind.get('changePct') is not None else None,
                        'rsi14': round(ind['rsi14'], 1) if ind.get('rsi14') is not None else None,
                        'volRatio': vol_ratio, 'per': candidates[code]['per'], 'yield': candidates[code]['yield'],
                        'revYoy': revenue['revYoy'], 'trustStreak': observations['trustStreak'],
                        'foreignStreak': observations['foreignStreak'], 'research': research})
    state_order = {'接近上緣': 0, '帶量越過': 1, '越過但量未確認': 2, '區間內': 3, '跌破下緣': 4}
    results.sort(key=lambda row: (state_order.get(row['research']['rangePosition'], 5),
                                 abs(row['research']['distanceToTopPct']) if row['research']['distanceToTopPct'] is not None else math.inf,
                                 row['sym']))
    meta.update({'truncated': len(results) > 80, 'returned': min(len(results), 80),
                 'sortBasis': '區間位置及距上緣距離，非報酬預測'})
    return {'results': results[:80], 'scanned': len(codes), 'techPass': tech_pass,
            'matched': len(results), 'researchMeta': meta}
