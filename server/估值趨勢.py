"""估值承接研究：只讀既有官方快取與本機日線，不下載、不回寫決策。"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from typing import Mapping

from datastore import read_snapshot
from exchange_source_dates import TAIPEI
from market_contract import quote_contract, tw_symbol_code
from 台股基本面 import (INCOME_DATASETS, REVENUE_DATASETS, income_record,
                      number, pick, revenue_record, source_date)
from 三合一選股 import chip_fields, load_chip_snapshots, market_sessions, matches

VERSION = 'valuation-research-2'
IP_REVIEW = {'3529': '力旺', '6643': 'M31'}
PE_DATASETS = ('exchangeReport/BWIBBU_ALL', 'tpex:tpex_mainboard_peratio_analysis')
SCOPE_REASONS = {
    'excludedNonStock': '本研究僅適用臺灣四位數普通股，ETF 與其他市場不適用',
    'excludedMarket': '指定交易市場與官方資料來源不一致',
    'excludedIp': '此股票另案估值，預設排除於一般估值研究',
    'excludedPeInvalid': '缺少有效正本益比',
    'excludedPeAbove': '官方本益比超出設定上限',
    'excludedSourceDate': '官方本益比缺少有效來源日期或來源不一致',
    'excludedStale': '本益比未對齊最近已完成交易日，或交易日曆尚缺',
}
EXCLUSION_REASONS = {**SCOPE_REASONS,
                     'missingTechnical': '本機完整日線不足、來源尚未核對，或技術指標計算尚不可用'}


def validate_settings(raw=None):
    raw = {} if raw is None else raw
    if not isinstance(raw, Mapping):
        raise ValueError('研究設定須為物件。')
    pe_max = number(raw.get('peMax', 30))
    exclude_ip = raw.get('excludeIp', True)
    if pe_max is None or not 0 < pe_max <= 200:
        raise ValueError('本益比上限須大於 0 且不超過 200。')
    if not isinstance(exclude_ip, bool):
        raise ValueError('另案估值排除設定須為布林值。')
    return {'peMax': pe_max, 'excludeIp': exclude_ip}


def cached_lookup(cache):
    """將 server._openapi_ds 轉為唯讀查表函式；抓取時間絕不代替來源日。"""
    def lookup(datasets, code):
        for dataset in datasets:
            dataset = dataset.removeprefix('opendata/')
            entry = cache.get('__list__' + dataset)
            rows = entry[1] if isinstance(entry, (list, tuple)) and len(entry) == 2 else []
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                identity = next((str(row[k]).strip() for k in
                                 ('公司代號', '證券代號', 'Code', 'SecuritiesCompanyCode', '股票代號')
                                 if row.get(k) is not None), '')
                if identity == code:
                    return dict(row)
        return None
    return lookup


def parse_valuation(row, dataset, *, cutoff):
    row = row or {}
    dates = {source_date(row[k]) for k in ('Date', '日期', '資料日期', '交易日期', 'TradingDate')
             if row.get(k) not in (None, '')}
    valid = len(dates) == 1 and None not in dates and next(iter(dates)) <= cutoff
    valid = valid and dataset in PE_DATASETS
    day = next(iter(dates)) if valid else None
    pe = pick(row, '本益比', 'PEratio', 'PriceEarningRatio') if valid else None
    return {'per': pe if pe is not None and pe > 0 else None,
            'yield': pick(row, '殖利率', 'DividendYield', 'YieldRatio', 'Yield') if valid else None,
            'valuationDate': day,
            'valuationSource': ('TWSE BWIBBU_ALL' if dataset == PE_DATASETS[0] else
                                'TPEx peratio' if dataset == PE_DATASETS[1] else None),
            'valuationDateValid': bool(valid)}


def load_prices(code, database, now, expected=None, board=None):
    """沿用 bars + bar_quality 的市場、原始價格、官方來源契約，缺列保留。"""
    cutoff = (now.date() if now.hour >= 18 else now.date() - timedelta(days=1)).isoformat()
    rows, reasons = [], []
    try:
        with read_snapshot(database) as conn:
            conn.row_factory = sqlite3.Row
            raw = conn.execute('''SELECT b.*,q.session_date,q.source,q.volume_unit,q.price_basis,
                       q.issues,q.retrieved_at FROM bars b LEFT JOIN bar_quality q
                       ON b.market=q.market AND b.symbol=q.symbol AND b.ts=q.ts
                       WHERE b.market='TW' AND b.symbol=? ORDER BY b.ts DESC LIMIT 160''', (code,)).fetchall()
            for item in reversed(raw):
                stamp = number(item['ts'])
                try:
                    day = datetime.fromtimestamp(stamp, TAIPEI).date().isoformat() if stamp is not None else None
                except (ValueError, OSError, OverflowError):
                    day = None
                if day is None or day > cutoff:
                    continue
                valid = (item['source'] in ('TWSE', 'TPEX') and (board is None or item['source'] == board)
                         and item['session_date'] == day
                         and item['price_basis'] == '原始價格' and item['volume_unit'] == '股')
                try:
                    issues = json.loads(item['issues'] or '[]')
                except (TypeError, ValueError):
                    issues = ['品質紀錄無效']
                if not isinstance(issues, list):
                    issues = ['品質紀錄無效']
                if any('來源' in str(issue) or '修訂' in str(issue) or '無效' in str(issue) for issue in issues):
                    valid = False
                bar = {'date': day, 'source': item['source'], 'qualityValid': valid,
                       **{k: number(item[k]) if valid else None for k in ('open', 'high', 'low', 'close', 'volume')}}
                prices = [bar[k] for k in ('open', 'high', 'low', 'close')]
                if not all(v is not None and v > 0 for v in prices) or not (
                        bar['low'] <= min(bar['open'], bar['close']) <= max(bar['open'], bar['close']) <= bar['high']):
                    for key in ('open', 'high', 'low', 'close'):
                        bar[key] = None
                if bar['volume'] is not None and bar['volume'] < 0:
                    bar['volume'] = None
                rows.append(bar)
            if expected:
                sessions = [r[0] for r in conn.execute('SELECT session_date FROM market_sessions WHERE session_date<=? '
                            'ORDER BY session_date DESC LIMIT 101', (expected,))]
                by_day = {}
                for bar in rows:
                    if bar['date'] in by_day:
                        by_day[bar['date']] = {'date': bar['date'], 'qualityValid': False}
                    else:
                        by_day[bar['date']] = bar
                rows = [by_day.get(day, {'date': day, 'qualityValid': False}) for day in reversed(sessions)]
    except (OSError, sqlite3.Error, ValueError, TypeError):
        return [], ['本機官方日線或品質紀錄尚未保存']
    if not rows:
        reasons.append('本機沒有可核對的已完成交易日日線')
    elif not rows[-1].get('qualityValid') or rows[-1].get('close') is None:
        reasons.append('最近交易日日線缺少官方來源、完整價格或品質核對')
    if not expected:
        reasons.append('官方交易日曆尚未更新，價格新鮮度與連續區間不可確認')
    return rows, reasons


def price_observation(bars, *, expected=None):
    last = bars[-1] if bars else {}
    close = number(last.get('close'))
    fresh = expected is not None and last.get('date') == expected
    prior = bars[-21:-1] if fresh and len(bars) >= 21 else []
    valid_range = bool(prior) and all(number(b.get('high')) is not None and number(b.get('low')) is not None
                                         and 0 < b['low'] <= b['high'] for b in prior)
    top = max(b['high'] for b in prior) if valid_range else None
    bottom = min(b['low'] for b in prior) if valid_range else None
    volumes = [number(b.get('volume')) for b in prior]
    mean = number(sum(v / 20 for v in volumes)) if len(volumes) == 20 and all(v is not None and v >= 0 for v in volumes) else None
    volume = number(last.get('volume'))
    ratio = number(volume / mean) if mean and volume is not None and volume >= 0 else None
    distance = number((top - close) / top * 100) if top and close else None
    state = None
    if top and bottom and close and volume is not None and volume > 0:
        state = ('帶量越過' if ratio is not None and ratio >= 1.5 else '越過但量未確認') if close > top else (
            '跌破下緣' if close < bottom else '接近上緣' if distance is not None and distance <= 2 else '區間內')
    closes = [number(b.get('close')) for b in bars[-100:]] if fresh else []
    peak = max(closes) if len(closes) == 100 and all(v is not None and v > 0 for v in closes) else None
    return {'close': close, 'priceAsOf': last.get('date') if close is not None else None,
            'priceSource': last.get('source') if close is not None else None,
            'priceBasis': '原始價格；已完成交易日日收盤，未還原除權息',
            'priceFresh': bool(fresh and close is not None), 'volumeShares': volume,
            'drawdown100': (close / peak - 1) * 100 if peak and close else None,
            'rangeTop': top, 'rangeBottom': bottom, 'distanceToTopPct': distance,
            'rangePosition': state, 'breakoutVolumeRatio': ratio,
            'breakoutVolumeBasis': '當日成交股數／前二十個完整交易日平均成交股數'}


def _fundamentals(code, lookup, now, board):
    revenue, income = None, None
    for dataset in REVENUE_DATASETS:
        if board and dataset.startswith('tpex:') != (board == 'TPEX'):
            continue
        candidate = revenue_record(lookup([dataset], code), dataset, now.date())
        if candidate and candidate.get('sourceDate'):
            if revenue is None or (candidate.get('periodLabel') or '') > (revenue.get('periodLabel') or ''):
                revenue = candidate
    for dataset, kind, _ in INCOME_DATASETS:
        if board and dataset.startswith('tpex:') != (board == 'TPEX'):
            continue
        candidate = income_record(lookup([dataset], code), kind, dataset, now.date())
        if candidate and candidate.get('sourceDate'):
            income = candidate
            break
    return revenue or {}, income


def get_research(code, *, database, lookup, settings=None, name=None, market='TW', now=None,
                 chip_history_path=None, _sessions=None, _snapshots=None):
    """GET 的純讀取入口。lookup 必須是既有官方快取查表，不能觸發下載。"""
    settings = validate_settings(settings)
    now = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    symbol, code = str(code or '').strip().upper(), tw_symbol_code(code)
    ordinary = market == 'TW' and re.fullmatch(r'[1-9]\d{3}', code) is not None
    sessions = market_sessions(database, now) if _sessions is None else _sessions
    expected = sessions[-1] if sessions else None
    dataset, raw, conflict = None, None, False
    if ordinary:
        candidates = [(ds, lookup([ds], code)) for ds in PE_DATASETS]
        candidates = [(ds, value) for ds, value in candidates if value]
        conflict = len(candidates) > 1
        if candidates:
            dataset, raw = candidates[0]
    valuation = parse_valuation(raw, dataset, cutoff=now.date().isoformat())
    board = 'TPEX' if dataset == PE_DATASETS[1] else 'TWSE' if dataset else None
    mismatch = conflict or (symbol.endswith('.TW') and board == 'TPEX') or (symbol.endswith('.TWO') and board == 'TWSE')
    reason = ('excludedNonStock' if not ordinary else 'excludedMarket' if mismatch else
              'excludedIp' if settings['excludeIp'] and code in IP_REVIEW else
              'excludedSourceDate' if not valuation['valuationDateValid'] else
              'excludedStale' if not expected or valuation['valuationDate'] != expected else
              'excludedPeInvalid' if valuation['per'] is None or valuation['per'] <= 0 else
              'excludedPeAbove' if valuation['per'] > settings['peMax'] else None)
    bars, missing = load_prices(code, database, now, expected, board) if ordinary and not mismatch else ([], [])
    if board:
        for bar in bars:
            if bar.get('source') and bar['source'] != board:
                bar.update({k: None for k in ('open', 'high', 'low', 'close', 'volume')})
                missing.append('日線來源與估值交易市場不一致')
    obs = price_observation(bars, expected=expected)
    revenue, income = _fundamentals(code, lookup, now, board) if ordinary and not mismatch else ({}, None)
    snapshots = (_snapshots if _snapshots is not None else load_chip_snapshots(chip_history_path)
                 if chip_history_path else {})
    chip = chip_fields(code, sessions, snapshots) if ordinary and not mismatch else {
        'trustStreak': None, 'foreignStreak': None, 'chipAsOf': None, 'fieldStatus': {}}
    if reason:
        missing.append(SCOPE_REASONS[reason])
    if revenue.get('yoyPct') is None:
        missing.append('官方營收缺少有效來源日期或年增率')
    if revenue.get('priorPeriod'):
        missing.append('營收為較早期別：' + str(revenue.get('periodLabel')))
    for key, message in (('drawdown100', '未滿一百個連續有效交易日，無法計算回撤'),
                         ('rangePosition', '前二十日區間或當日成交狀態不足'),
                         ('breakoutVolumeRatio', '成交量不足或前二十日均量為零')):
        if obs[key] is None:
            missing.append(message)
    missing.append('尚無當時可得財報版本與假設歷程，不能宣稱歷史策略有效')
    research = {**valuation, **obs, 'contractVersion': VERSION,
                'scopeEligible': reason is None, 'scopeReasonCode': reason,
                'scopeReason': SCOPE_REASONS.get(reason),
                'valuationModel': '另案估值' if code in IP_REVIEW else '一般估值',
                'dataStatus': 'not_applicable' if not ordinary else 'partial' if reason or not obs['priceFresh']
                              or obs['rangePosition'] is None else 'available',
                'asOf': now.date().isoformat(), 'expectedSession': expected,
                'revenuePeriod': revenue.get('periodLabel'), 'revenueSource': revenue.get('source'),
                'revenueDate': revenue.get('sourceDate'), 'revenueMom': revenue.get('momPct'),
                'revenueCumYoy': revenue.get('cumYoyPct'), 'revenuePriorPeriod': revenue.get('priorPeriod'),
                'income': income, 'epsBasis': 'user_assumption_only',
                'pitFinancialsAvailable': False, 'strategyValidated': False,
                'trustAsOf': chip.get('chipAsOf'), 'missing': list(dict.fromkeys(missing))}
    row = {'sym': code, 'name': name or code, 'close': obs['close'], 'changePct': None,
           'rsi14': None, 'volRatio': obs['breakoutVolumeRatio'], 'per': valuation['per'],
           'yield': valuation['yield'], 'revYoy': revenue.get('yoyPct'),
           'trustStreak': chip.get('trustStreak'), 'foreignStreak': chip.get('foreignStreak'),
           'fieldStatus': chip.get('fieldStatus', {}),
           'trustStreakComplete': chip.get('trustStreakComplete'),
           'foreignStreakComplete': chip.get('foreignStreakComplete'), 'research': research,
           'market': quote_contract({'price': obs['close']}, symbol=code, market=market,
                                    source=obs['priceSource'], as_of=obs['priceAsOf'], session='completed')}
    return {'row': row, 'researchMeta': {'enabled': True, **settings, 'contractVersion': VERSION,
            'dataPolicy': '只讀既有官方快取與本機資料', 'strategyValidated': False}}


def run_screen(body, *, symbols, database, lookup, names=None, settings=None,
               universe_source='既有研究股票範圍', now=None, chip_history_path=None,
               calc_ind=None, tech_match=None):
    """與 GET 相同結果契約；所有條件缺值均不通過，不以 close／0 補 OHLCV。"""
    settings = validate_settings(settings if settings is not None else body.get('research'))
    now = (now or datetime.now(TAIPEI)).astimezone(TAIPEI)
    sessions = market_sessions(database, now)
    snapshots = load_chip_snapshots(chip_history_path) if chip_history_path else {}
    # UI 傳完整欄位物件；false／null／空字串不是啟用條件，數字 0 仍是有效門檻。
    raw_tech = body.get('tech') or {}
    tech = {key: value for key, value in raw_tech.items()
            if value is not None and value is not False and value != ''}
    for key in ('rsiMin', 'rsiMax', 'volRatioMin'):
        if key in tech:
            if number(tech[key]) is None:
                raise ValueError('技術篩選門檻須為有限數值。')
            tech[key] = str(number(tech[key]))
    symbols = sorted(set(str(s).strip().upper() for s in symbols))
    results, excluded, tech_pass = [], {}, 0
    for symbol in symbols:
        row = get_research(symbol, database=database, lookup=lookup, settings=settings,
                           name=(names or {}).get(tw_symbol_code(symbol)), now=now,
                           _sessions=sessions, _snapshots=snapshots)['row']
        reason = row['research']['scopeReasonCode']
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        if tech:
            board = 'TPEX' if row['research']['valuationSource'] == 'TPEx peratio' else 'TWSE'
            bars, _ = load_prices(row['sym'], database, now, sessions[-1] if sessions else None, board)
            if (not row['research']['priceFresh'] or calc_ind is None or tech_match is None or len(bars) < 70 or
                    any(b.get(k) is None for b in bars for k in ('open', 'high', 'low', 'close', 'volume'))):
                excluded['missingTechnical'] = excluded.get('missingTechnical', 0) + 1
                continue
            ind = calc_ind(*[[b[k] for b in bars] for k in ('close', 'high', 'low', 'volume')])
            if not tech_match(tech, ind):
                continue
            row.update(rsi14=number(ind.get('rsi14')), changePct=number(ind.get('changePct')))
        tech_pass += 1
        if matches(row, body.get('fund') or {}, body.get('chip') or {}):
            results.append(row)
    order = {'接近上緣': 0, '帶量越過': 1, '越過但量未確認': 2, '區間內': 3, '跌破下緣': 4}
    results.sort(key=lambda row: (order.get(row['research']['rangePosition'], 5),
                 abs(row['research']['distanceToTopPct']) if row['research']['distanceToTopPct'] is not None else float('inf'), row['sym']))
    return {'results': results[:80], 'scanned': len(symbols), 'techPass': tech_pass,
            'matched': len(results), 'calculationVersion': VERSION,
            'researchMeta': {'enabled': True, **settings, 'contractVersion': VERSION,
                'universeSource': universe_source, 'excluded': excluded, 'returned': min(len(results), 80),
                'exclusions': [{'code': code, 'reason': EXCLUSION_REASONS[code], 'count': count}
                               for code, count in sorted(excluded.items())],
                'separateSymbols': [{'sym': code, 'name': (names or {}).get(code) or name,
                    'valuationModel': '另案估值', 'excludedFromGeneral': settings['excludeIp']}
                    for code, name in IP_REVIEW.items()],
                'truncated': len(results) > 80, 'strategyValidated': False,
                'sortBasis': '區間位置、距上緣絕對距離、股票代號；缺值置後，非報酬預測'},
            'scope': '最新公開資料與本機日線觀察；未具備歷史財報時點回測條件。'}
