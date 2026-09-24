"""CMO-VIDYA 與資金受限組合的工程研究；唯讀既有官方資料，不抓行情。"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import sqlite3
from contextlib import closing
from datetime import date, datetime
from pathlib import Path

try:
    from . import K線事件 as events
    from .公司行動比較 import Comparison
    from .突破觀察 import RULES, WARMUP_DAYS, build_research
    from .突破成交研究 import _Market, SCENARIOS
except ImportError:
    import K線事件 as events
    from 公司行動比較 import Comparison
    from 突破觀察 import RULES, WARMUP_DAYS, build_research
    from 突破成交研究 import _Market, SCENARIOS

VERSION = 'breakout-capital-vidya-engineering-v1'
SYMBOLS = ('0050', '2330')
DEFAULTS = {'initialCapital': 1000000., 'maxPositions': 2, 'allocationFraction': .5,
            'lotSize': 1, 'stopLossPct': 8., 'vidyaLength': 20, 'cmoLength': 9, 'warmupBars': 60,
            'capitalBasis': 'initial'}


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _positive(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _config(config: dict | None) -> dict:
    unknown = set(config or {}) - set(DEFAULTS)
    if unknown:
        raise ValueError('未知研究參數：' + ','.join(sorted(unknown)))
    result = {**DEFAULTS, **(config or {})}
    if result['capitalBasis'] not in ('initial', 'previous_close_equity'):
        raise ValueError('配置資金基準須為初始本金或前日已知收盤權益')
    if not _positive(result['initialCapital']) or not _positive(result['allocationFraction']) or result['allocationFraction'] > 1:
        raise ValueError('初始資金須為正，配置比例須大於零且不超過一')
    for key in ('maxPositions', 'lotSize', 'vidyaLength', 'cmoLength', 'warmupBars'):
        if not isinstance(result[key], int) or isinstance(result[key], bool) or result[key] <= 0:
            raise ValueError('研究整數參數無效：' + key)
    if result['maxPositions'] > len(SYMBOLS) or result['cmoLength'] > result['vidyaLength'] or result['warmupBars'] < max(result['vidyaLength'], result['cmoLength']) + 1:
        raise ValueError('持股上限或指標暖機不足')
    if not _positive(result['stopLossPct']) or result['stopLossPct'] >= 100:
        raise ValueError('成本停損幅度須大於零且小於百分之百')
    return result


def vidya_value(closes: list[float], *, length: int, cmo_length: int) -> float:
    """明確工程公式：初始 length 棒均線，其後 alpha=2/(length+1)*abs(CMO)。"""
    if not isinstance(length, int) or not isinstance(cmo_length, int) or not 0 < cmo_length <= length or len(closes) < length + 1 or not all(_positive(value) for value in closes):
        raise ValueError('VIDYA 價格或暖機無效')
    value = math.fsum(closes[:length]) / length
    for index in range(length, len(closes)):
        changes = [closes[j] - closes[j - 1] for j in range(index - cmo_length + 1, index + 1)]
        up = math.fsum(max(change, 0) for change in changes)
        down = math.fsum(max(-change, 0) for change in changes)
        momentum = abs(up - down) / (up + down) if up + down else 0.
        alpha = 2 / (length + 1) * momentum
        value += alpha * (closes[index] - value)
    return value


def _quality(market: _Market, index: int) -> str | None:
    row = market.rows[index]
    if market.issues[index]:
        return market.issues[index]
    if row.get('priceBasis') != 'unadjusted':
        return '原始價格基準尚未核對'
    if int(row['date'][:4]) not in market.calendar_years:
        return '市場交易日曆年度未核對'
    if not market.coverage or not market.coverage[0] or not market.coverage[1] or not market.coverage[0] <= row['date'] <= market.coverage[1]:
        return '公司行動涵蓋未核對'
    return None


def _fill_reason(market: _Market, index: int) -> str | None:
    reason = _quality(market, index)
    row = market.rows[index]
    if reason:
        return reason
    if row['open'] == row['high'] == row['low'] == row['close']:
        return '一價棒不能證實開盤成交'
    return None


def _prepare(symbol: str, dataset: dict, dates: list[str], config: dict, sample_start: int) -> dict:
    supplied_rows = [row for row in dataset['rows'] if not dates or row['date'] <= dates[-1]]
    source = {row['date']: row for row in supplied_rows}
    if len(source) != len(supplied_rows):
        raise ValueError('同標的輸入日期重複')
    rows = [copy.deepcopy(source.get(day, {'date': day, 'issues': ['市場交易日缺資料']})) for day in dates]
    actions = set(dataset.get('action_days') or [])
    adjustments = copy.deepcopy(dataset.get('adjustments') or {'symbol': symbol, 'coverage': None, 'events': []})
    if adjustments.get('symbol') != symbol:
        raise ValueError('公司行動比較證據與資料集標的不一致')
    adjustments['events'] = [event for event in adjustments.get('events', []) if event.get('date', '') <= (dates[-1] if dates else '')]
    years = set(dataset.get('calendar_years') or [])
    coverage = dataset.get('action_coverage')
    research = build_research(rows, calendar_years=years, action_days=actions, action_coverage=coverage,
                              sample_start=sample_start, adjustments=adjustments)
    market = _Market(rows, years, actions | {event['date'] for event in adjustments.get('events', [])}, coverage)
    comparison = Comparison(rows, adjustments, set(market.actions))
    observations = []
    for index, (row, signal) in enumerate(zip(rows, research['rows'])):
        first = index - config['warmupBars'] + 1
        reason, value = 'VIDYA 固定窗口暖機不足', None
        if first >= 0:
            reason = next((_quality(market, j) for j in range(first, index + 1) if _quality(market, j)), None)
            reason = reason or comparison.reason(first, index)
            if reason is None:
                closes = [float(item['close']) for item in comparison.prices(first, index)] + [row['close']]
                value = vidya_value(closes, length=config['vidyaLength'], cmo_length=config['cmoLength'])
        observations.append({'date': row['date'], 'close': row.get('close'), 'vidya': value, 'reason': reason,
                             'anchorDate': row['date'], 'eligible': signal['eligible'], 'signals': signal['signals']})
    evidence = comparison.digest_evidence(0, len(rows) - 1) if rows else {}
    coverage_evidence = None
    if dates and market.coverage:
        coverage_evidence = {'start': max(market.coverage[0] or '', dates[0]),
                             'end': min(market.coverage[1] or '', dates[-1])}
    quality_evidence = {'calendarYears': {str(year): year in years for year in sorted({int(day[:4]) for day in dates})},
                        'actionCoverage': coverage_evidence,
                        'actionDays': sorted(day for day in actions if dates and dates[0] < day <= dates[-1])}
    return {'symbol': symbol, 'market': market, 'officialActions': actions | {event['date'] for event in adjustments.get('events', [])}, 'observations': observations,
            'digest': _digest({'rows': rows, 'comparison': evidence, 'quality': quality_evidence}),
            'adjustmentEvidence': research.get('adjustmentEvidence')}


def _simulate(prepared: dict, dates: list[str], sample_start: int, config: dict, key: str,
              cost: float, *, benchmark: bool = False) -> dict:
    initial = config['initialCapital']
    cash, positions, pending, trades, rejected, curve = initial, {}, {}, [], [], []
    peak, max_drawdown, incomplete = initial, 0., False
    benchmark_entry_failed = False
    decision_issues = []
    eligible_days = 0
    for index in range(sample_start, len(dates)):
        day = dates[index]
        sizing_equity = initial if config['capitalBasis'] == 'initial' else (curve[-1]['equity'] if curve else initial)
        for symbol, position in list(positions.items()):
            market = prepared[symbol]['market']
            row = market.rows[index]
            if day in prepared[symbol]['officialActions'] and day > position['entryDate']:
                position['accountingUnknown'] = '持有期跨公司行動或重大價格斷點，未建立股數與現金權利'
            if index and _positive(row.get('open')) and _positive(market.rows[index - 1].get('close')) and abs(row['open'] / market.rows[index - 1]['close'] - 1) > .15:
                position['accountingUnknown'] = '開盤重大斷點未建立持有權利'
            if position.get('exitSignalDate'):
                reason = position.get('accountingUnknown') or _fill_reason(market, index)
                if reason:
                    rejected.append({'symbol': symbol, 'date': day, 'kind': 'exit', 'reason': reason})
                else:
                    proceeds = position['shares'] * row['open'] * (1 - cost)
                    cash += proceeds
                    trades.append({**position, 'exitDate': day, 'exitPrice': row['open'], 'exitCost': position['shares'] * row['open'] * cost,
                                   'netPnl': proceeds - position['entryCash'], 'netReturnPct': (proceeds / position['entryCash'] - 1) * 100})
                    del positions[symbol]
        # 同日先完成既有出場，再依代碼遞增處理前一日已確定的進場。
        for symbol, signal_day in sorted(pending.items()):
            market = prepared[symbol]['market']
            row = market.rows[index]
            reason = _fill_reason(market, index)
            if any(position.get('accountingUnknown') for position in positions.values()):
                reason = reason or '既有持有權利未知，暫停新增部位'
            if symbol in positions or len(positions) >= (1 if benchmark else config['maxPositions']):
                reason = reason or '已持有該標的或持股上限已滿'
            if index and _positive(row.get('open')) and _positive(market.rows[index - 1].get('close')) and abs(row['open'] / market.rows[index - 1]['close'] - 1) > .15:
                reason = reason or '進場開盤重大斷點，成交假設未核對'
            if sizing_equity is None:
                reason = reason or '前一日收盤權益未知，不能決定複利配置'
            budget = min(cash, (sizing_equity or 0) * (1 if benchmark else config['allocationFraction']))
            shares = 0 if reason else math.floor(budget / (row['open'] * (1 + cost)) / config['lotSize']) * config['lotSize']
            if shares <= 0:
                reason = reason or '可用現金不足最小交易單位'
            if reason:
                rejected.append({'symbol': symbol, 'date': day, 'signalDate': signal_day, 'kind': 'entry', 'reason': reason})
                benchmark_entry_failed = benchmark_entry_failed or benchmark
            else:
                used = shares * row['open'] * (1 + cost)
                cash -= used
                positions[symbol] = {'symbol': symbol, 'signalDate': signal_day, 'entryDate': day, 'entryPrice': row['open'],
                                     'shares': shares, 'entryCash': used, 'entryCost': shares * row['open'] * cost,
                                     'sizingEquity': sizing_equity, 'capitalBasis': config['capitalBasis'],
                                     'exitSignalDate': None, 'exitReason': None}
        pending = {}
        equity, exposure, valuation_reasons = cash, 0., []
        for symbol, position in positions.items():
            market = prepared[symbol]['market']
            row, observation = market.rows[index], prepared[symbol]['observations'][index]
            if index and _positive(row.get('close')) and _positive(market.rows[index - 1].get('close')) and abs(row['close'] / market.rows[index - 1]['close'] - 1) > .15:
                position['accountingUnknown'] = '持有期收盤重大價格斷點未核對'
            reason = position.get('accountingUnknown') or _quality(market, index)
            if reason:
                valuation_reasons.append({'symbol': symbol, 'reason': reason})
            else:
                value = position['shares'] * row['close']
                equity += value
                exposure += value
                if not benchmark and not position['exitSignalDate']:
                    loss = row['close'] <= position['entryPrice'] * (1 - config['stopLossPct'] / 100)
                    below = observation['vidya'] is not None and row['close'] < observation['vidya']
                    if loss or below:
                        position.update(exitSignalDate=day, exitReason='cost_stop' if loss else 'vidya_close')
            position['markDate'] = day
            position['markPrice'] = None if reason else row['close']
        if valuation_reasons:
            equity = None
            incomplete = True
        else:
            peak = max(peak, equity)
            max_drawdown = max(max_drawdown, (peak - equity) / peak * 100)
        curve.append({'date': day, 'cash': cash, 'equity': equity,
                      'exposurePct': exposure / equity * 100 if equity is not None and equity > 0 else None,
                      'positions': len(positions), 'valuationReasons': valuation_reasons})
        for symbol in SYMBOLS:
            observation = prepared[symbol]['observations'][index]
            if not benchmark and (not observation['eligible'].get(key) or observation['vidya'] is None):
                # 未判定的訊號或退出條件不能視為已知未觸發；仍保留可核對逐筆，總績效不升格。
                decision_issues.append({'symbol': symbol, 'date': day, 'reason': observation['reason'] or '突破訊號資料尚未核對'})
            if observation['eligible'].get(key) and observation['vidya'] is not None:
                eligible_days += 1
            candidate = symbol == '0050' and index == sample_start if benchmark else key in observation['signals'] and observation['vidya'] is not None
            if candidate and symbol not in positions:
                pending[symbol] = day
    final_equity = curve[-1]['equity'] if curve else None
    insufficient = not curve or (not benchmark and eligible_days == 0) or (benchmark and not positions and not benchmark_entry_failed)
    unknown = incomplete or bool(decision_issues) or benchmark_entry_failed
    return {'status': 'insufficient' if insufficient else 'unknown' if unknown else 'complete', 'costRatePerSide': cost,
            'eligibleAssetDays': eligible_days, 'initialCapital': initial, 'finalEquity': final_equity,
            'totalReturnPct': (final_equity / initial - 1) * 100 if final_equity is not None and not insufficient and not unknown else None,
            'maxDrawdownPct': None if unknown or insufficient else max_drawdown,
            'maxDrawdownLowerBoundPct': max_drawdown, 'closedTrades': len(trades),
            'trades': trades, 'openPositions': list(positions.values()), 'pending': pending, 'rejected': rejected,
            'decisionIssues': decision_issues, 'curve': curve}


def build_portfolio(datasets: dict, market_dates: list[str], *, sample_start: int = 0,
                    as_of: str | None = None, config: dict | None = None) -> dict:
    """只接受既有 2330/0050 官方日線；market_dates 必須保留所有預期交易日。"""
    settings = _config(config)
    if as_of is not None:
        date.fromisoformat(as_of)
    if set(datasets) != set(SYMBOLS):
        raise ValueError('研究範圍固定為 2330 與 0050')
    if any(date.fromisoformat(day).isoformat() != day for day in market_dates) or any(a >= b for a, b in zip(market_dates, market_dates[1:])):
        raise ValueError('市場日期須依序且不得重複')
    dates = [day for day in market_dates if not as_of or day <= as_of]
    if not isinstance(sample_start, int) or sample_start < 0:
        raise ValueError('研究起點無效')
    sample_start = min(sample_start, len(dates))
    prepared = {symbol: _prepare(symbol, datasets[symbol], dates, settings, sample_start) for symbol in SYMBOLS}
    return _report(prepared, dates, sample_start, settings)


def _report(prepared: dict, dates: list[str], sample_start: int, settings: dict) -> dict:
    rules = [{'key': rule['key'], 'label': rule['label'], 'scenarios': {
        scenario: _simulate(prepared, dates, sample_start, settings, rule['key'], cost)
        for scenario, cost in SCENARIOS.items()}} for rule in RULES]
    benchmark = {scenario: _simulate(prepared, dates, sample_start, settings, RULES[0]['key'], cost, benchmark=True)
                 for scenario, cost in SCENARIOS.items()}
    for rule in rules:
        for scenario, result in rule['scenarios'].items():
            reference = benchmark[scenario]
            result['excessReturnPctPoints'] = result['totalReturnPct'] - reference['totalReturnPct'] if (
                result['status'] == reference['status'] == 'complete' and result['totalReturnPct'] is not None and reference['totalReturnPct'] is not None) else None
    return {'version': VERSION, 'status': 'complete' if all(rule['scenarios']['baseNet']['status'] == 'complete' for rule in rules) else 'limited',
            'config': settings, 'inputDigest': _digest({'assets': {symbol: item['digest'] for symbol, item in prepared.items()}, 'start': sample_start, 'version': VERSION, 'config': settings}),
            'range': {'start': dates[sample_start] if sample_start < len(dates) else None, 'end': dates[-1] if dates else None,
                      'warmupDays': sample_start, 'marketDays': len(dates) - sample_start},
            'assets': [{'symbol': symbol, 'rows': item['observations'][sample_start:], 'inputDigest': item['digest'],
                        'adjustmentEvidence': item['adjustmentEvidence']} for symbol, item in prepared.items()],
            'rules': rules, 'benchmark': {'label': '0050 同起點持有、期末市價', 'scenarios': benchmark},
            'notes': ['工程版 CMO-VIDYA 與停損，未還原文章未揭露的公式，不加入評分或通知。',
                      '每觀察日以前 60 棒（可設定）為固定窗口，先以 length 棒均線初始化，再使用 2/(length+1)×abs(CMO) 遞迴；CMO 使用收盤漲跌和的差／和，零變化時為零。',
                      '指標只用已生效官方參考價比值調整比較，原始成交價不變；收盤低於 VIDYA 或成本停損，次市場交易日開盤退出。',
                      '同日先退出再依代碼排序配置；capitalBasis 明確選擇初始本金或前一日已知收盤權益，配置比例與最小單位固定，不借貸、不加碼。',
                      '跨公司行動持有權利未知，不能預先知道事件而避開交易；不把參考價格比值當股數轉換或含息報酬。',
                      '基準使用相同起始可進場日、成本與市價口徑，曝險及持有期不同；未核對基準不得補零或顯示超額。',
                      '期末持有不強制平倉；保留待成交、缺資料與未知估值。沒有量價容量、委託簿或日內執行保證。',
                      '三個規則各自使用獨立現金帳戶，屬同樣本多次探索；不是樣本外、統計顯著或前瞻驗證。']}


def build_saved_portfolio(db_path: str | Path, as_of: str | None = None, *, now: datetime | None = None) -> dict:
    """固定近五年加暖機，兩檔及所有品質證據共用同一唯讀 SQLite 快照。"""
    clock = (now or datetime.now(events.TZ)).astimezone(events.TZ)
    cutoff = date.fromisoformat(as_of) if as_of else clock.date()
    if cutoff > clock.date():
        raise ValueError('截至日期不得晚於今天')
    try:
        with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True, timeout=15)) as conn:
            conn.execute('BEGIN')
            fresh = events.freshness(conn, '2330', clock)
            if not fresh.get('expectedSession'):
                raise ValueError('官方最新已完成市場日尚未核對')
            cutoff = min(cutoff, date.fromisoformat(fresh['expectedSession']))
            start = events.range_start('5y', cutoff, None).isoformat()
            calendar_rows = conn.execute('SELECT session_date,source FROM market_sessions WHERE session_date<=? ORDER BY session_date', (cutoff.isoformat(),)).fetchall()
            if any(not str(source).startswith(('TWSE', 'TPEX')) for day, source in calendar_rows):
                raise ValueError('官方市場日曆來源未核對')
            timeline = [row[0] for row in calendar_rows]
            first = next((i for i, day in enumerate(timeline) if day >= start), len(timeline))
            warmup = min(WARMUP_DAYS, first)
            timeline = timeline[first - warmup:]
            years = {row[0] for row in conn.execute('SELECT year FROM calendar_years')}
            datasets = {}
            for symbol in SYMBOLS:
                raw = events._read_bars(conn, symbol, cutoff)
                normalized = events._normalize_bars(raw, set(timeline))
                coverage = conn.execute("SELECT start_date,end_date,source FROM action_coverage WHERE market='TW' AND symbol=?", (symbol,)).fetchone()
                actions = {row[0] for row in conn.execute("SELECT session_date FROM corporate_actions WHERE market='TW' AND symbol=? AND session_date<=?", (symbol, cutoff.isoformat()))}
                datasets[symbol] = {'rows': list(normalized.values()), 'calendar_years': years, 'action_days': actions,
                                    'action_coverage': coverage, 'adjustments': events._read_adjustments(conn, symbol, cutoff)}
        settings = _config(None)
        prepared = {symbol: _prepare(symbol, datasets[symbol], timeline, settings, warmup) for symbol in SYMBOLS}
        result = _report(prepared, timeline, warmup, settings)
        result['equitySizing'] = _report(prepared, timeline, warmup, {**settings, 'capitalBasis': 'previous_close_equity'})
        result['sourceStatus'] = fresh
        return result
    except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        return {'version': VERSION, 'status': 'unavailable', 'reason': str(exc), 'rules': [], 'assets': [], 'benchmark': None}
