"""現金受限 VIDYA 投組的確定性工程研究；原價不覆寫，讀取端不抓行情。"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import sqlite3
import statistics
from contextlib import closing
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

VERSION = 'breakout-capital-vidya-engineering-v3'
SYMBOLS = ('0050', '2330')
SCENARIOS = {'gross': 0.0, 'baseNet': 0.0025, 'stressNet': 0.005}
DEFAULTS = {'initialCapital': 1000000.0, 'maxPositions': 2, 'allocationFraction': 0.5,
            'lotSize': 1, 'stopLossPct': 8.0, 'vidyaLength': 20, 'cmoLength': 9,
            'warmupBars': 60, 'capitalBasis': 'initial', 'testStart': '2024-01-01',
            'annualRiskFreeRate': 0.0, 'periodsPerYear': 252}
TZ = timezone(timedelta(hours=8))


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _positive(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _day(value):
    if not isinstance(value, str) or date.fromisoformat(value).isoformat() != value:
        raise ValueError('日期須為 YYYY-MM-DD')
    return value


def _risk_settings(annual_risk_free_rate, periods_per_year):
    if (isinstance(annual_risk_free_rate, bool) or not isinstance(annual_risk_free_rate, (int, float))
            or not math.isfinite(annual_risk_free_rate) or not 0 <= annual_risk_free_rate <= 1):
        raise ValueError('無風險年利率須為零至一的小數值')
    if isinstance(periods_per_year, bool) or not isinstance(periods_per_year, int) or not 1 <= periods_per_year <= 366:
        raise ValueError('年化日數須為一至三百六十六的整數')
    return {'annualRiskFreeRate': annual_risk_free_rate, 'periodsPerYear': periods_per_year,
            'dailyRiskFreeRate': (1 + annual_risk_free_rate) ** (1 / periods_per_year) - 1}


def _config(config=None):
    if config is not None and not isinstance(config, dict):
        raise ValueError('研究參數須為物件')
    unknown = set(config or {}) - set(DEFAULTS)
    if unknown:
        raise ValueError('未知研究參數：' + ','.join(sorted(unknown)))
    result = {**DEFAULTS, **(config or {})}
    bounds = {'maxPositions': (1, 20), 'lotSize': (1, 1000), 'vidyaLength': (2, 120),
              'cmoLength': (1, 120), 'warmupBars': (3, 504)}
    for key, (low, high) in bounds.items():
        value = result[key]
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ValueError('研究整數參數超出範圍：' + key)
    if not _positive(result['initialCapital']) or result['initialCapital'] > 1e12:
        raise ValueError('初始資金須大於零且不超過一兆')
    if not _positive(result['allocationFraction']) or result['allocationFraction'] > 1:
        raise ValueError('配置比例須大於零且不超過一')
    if not _positive(result['stopLossPct']) or result['stopLossPct'] >= 100:
        raise ValueError('停損幅度須大於零且小於百分之百')
    if result['cmoLength'] > result['vidyaLength'] or result['warmupBars'] < result['vidyaLength'] + 1:
        raise ValueError('CMO 不得長於 VIDYA，暖機須多於 VIDYA 長度')
    if result['capitalBasis'] not in ('initial', 'previous_close_equity'):
        raise ValueError('配置基準須為初始本金或前一日收盤權益')
    if result['testStart'] is not None:
        _day(result['testStart'])
    _risk_settings(result['annualRiskFreeRate'], result['periodsPerYear'])
    return result


def vidya_value(closes, *, length=20, cmo_length=9):
    """先以 length 棒 SMA 初始化；CMO 用最近 cmo_length 個收盤變化。"""
    if (isinstance(length, bool) or isinstance(cmo_length, bool)
            or not isinstance(length, int) or not isinstance(cmo_length, int)
            or not 0 < cmo_length <= length or len(closes) < length
            or not all(_positive(v) for v in closes)):
        raise ValueError('VIDYA 價格或暖機無效')
    value = math.fsum(closes[:length]) / length
    for index in range(length, len(closes)):
        changes = [closes[j] - closes[j - 1] for j in range(index - cmo_length + 1, index + 1)]
        up = math.fsum(max(change, 0) for change in changes)
        down = math.fsum(max(-change, 0) for change in changes)
        cmo = abs(up - down) / (up + down) if up + down else 0.0
        value += 2 / (length + 1) * cmo * (closes[index] - value)
    return value


def _normalize(datasets, market_dates, as_of=None):
    if not isinstance(datasets, dict) or not 1 <= len(datasets) <= 20:
        raise ValueError('須提供一至二十個明確標的，不自動擴充範圍')
    if len(market_dates) > 6000 or any(_day(day) != day for day in market_dates):
        raise ValueError('交易日資料超出範圍')
    if any(a >= b for a, b in zip(market_dates, market_dates[1:])):
        raise ValueError('市場日期須依序且不得重複')
    if as_of is not None:
        _day(as_of)
    dates = [d for d in market_dates if as_of is None or d <= as_of]
    output = {}
    for symbol, dataset in sorted(datasets.items()):
        if not isinstance(symbol, str) or not symbol or len(symbol) > 20:
            raise ValueError('標的代碼無效')
        selected = [r for r in dataset.get('rows', []) if as_of is None or r['date'] <= as_of]
        by_day = {_day(r['date']): copy.deepcopy(r) for r in selected}
        if len(by_day) != len(selected):
            raise ValueError('同標的輸入日期重複')
        item = {key: copy.deepcopy(value) for key, value in dataset.items() if key != 'rows'}
        item['rows'] = [by_day.get(day, {'date': day, 'issues': ['市場交易日缺資料']}) for day in dates]
        item['action_days'] = sorted(day for day in dataset.get('action_days', []) if dates and dates[0] <= day <= dates[-1])
        item['calendar_years'] = sorted(set(dataset.get('calendar_years', [])) & {int(d[:4]) for d in dates})
        coverage = item.get('action_coverage')
        if dates and coverage and len(coverage) >= 3 and coverage[0] and coverage[1]:
            item['action_coverage'] = [max(coverage[0], dates[0]), min(coverage[1], dates[-1]), coverage[2]]
        output[symbol] = item
    return output, dates


def _quality(symbol, dataset, index, *, opening=False):
    row = dataset['rows'][index]
    if row.get('issues'):
        return '來源品質未核對：' + '、'.join(map(str, row['issues']))
    if row.get('source') not in ('TWSE', 'TPEX'):
        return '官方行情來源尚未核對'
    if row.get('priceBasis') != 'unadjusted':
        return '原始價格基準尚未核對'
    if row.get('sourceDate', row['date']) != row['date']:
        return '來源日期與交易日不一致'
    if int(row['date'][:4]) not in dataset.get('calendar_years', []):
        return '市場交易日曆年度未核對'
    try:
        from .台股交易參考 import trading_status
    except ImportError:
        from 台股交易參考 import trading_status
    if trading_status(symbol, row['date']) or row.get('suspended'):
        return '停止交易期間不得推定可成交'
    coverage = dataset.get('action_coverage')
    if symbol.startswith('00') and (not coverage or dataset.get('action_coverage_kind') != 'etf'):
        return 'ETF 公司行動涵蓋未核對'
    if not coverage or len(coverage) < 3 or not coverage[0] or not coverage[1] or not coverage[0] <= row['date'] <= coverage[1]:
        return '公司行動涵蓋未核對'
    if not str(coverage[2]).startswith(('TWSE', 'TPEX')):
        return '公司行動來源未核對'
    # 開盤只查開盤可得欄位；不以當日收盤、高低價或成交量篩選可成交標的。
    keys = ('open',) if opening else ('open', 'high', 'low', 'close', 'volume')
    if not all(_positive(row.get(key)) for key in keys):
        return '開盤價格缺漏' if opening else '價格或成交量缺值／無成交'
    if not opening and not row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high']:
        return '開高低收邊界無效'
    return None


def _fill_reason(symbol, dataset, index):
    """事後可成交證據須完整；不從一價或零量日線假設開盤撮合成功。"""
    reason = _quality(symbol, dataset, index, opening=True)
    if reason:
        return reason
    row = dataset['rows'][index]
    if not _positive(row.get('volume')):
        return '成交量缺漏或無成交，不能證實開盤成交'
    if not all(_positive(row.get(key)) for key in ('high', 'low', 'close')):
        return '日線成交證據不完整，不能證實開盤成交'
    if row['open'] == row['high'] == row['low'] == row['close']:
        return '一價棒不能證實開盤成交'
    if not row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high']:
        return '開高低收邊界無效，不能證實開盤成交'
    return None


def _observations(symbol, dataset, settings):
    rows, result = dataset['rows'], []
    issues = [_quality(symbol, dataset, i) for i in range(len(rows))]
    actions = set(dataset.get('action_days', []))
    for index, row in enumerate(rows):
        first = index - settings['warmupBars'] + 1
        reason, value = 'VIDYA 固定窗口暖機不足', None
        if first >= 0:
            reason = next((issue for issue in issues[first:index + 1] if issue), None)
            if any(rows[j]['date'] in actions for j in range(first + 1, index + 1)):
                reason = reason or '指標窗口跨公司行動，未重編原價比較'
            if reason is None:
                value = vidya_value([r['close'] for r in rows[first:index + 1]],
                                    length=settings['vidyaLength'], cmo_length=settings['cmoLength'])
        previous = result[-1] if result else {}
        entry = None
        if value is not None and previous.get('vidya') is not None:
            entry = previous['close'] <= previous['vidya'] and row['close'] > value
        result.append({'date': row['date'], 'close': row.get('close'), 'vidya': value,
                       'entrySignal': entry, 'reason': reason or (None if entry is not None else '前一日 VIDYA 尚未完成')})
    return result


def simulate_portfolio(datasets, market_dates, observations, *, sample_start=0, config=None,
                       side_cost=0.0025, benchmark_symbol=None):
    """純撮合與記帳核心；observations 為逐收盤已確定的 VIDYA 與布林訊號。"""
    settings = _config(config)
    if isinstance(side_cost, bool) or not isinstance(side_cost, (int, float)) or not math.isfinite(side_cost) or not 0 <= side_cost <= .05:
        raise ValueError('每邊合計費用與滑價須介於零與百分之五')
    prepared, dates = _normalize(datasets, market_dates)
    if isinstance(sample_start, bool) or not isinstance(sample_start, int) or not 0 <= sample_start <= len(dates):
        raise ValueError('研究起點無效')
    if benchmark_symbol is not None and benchmark_symbol not in prepared:
        raise ValueError('基準標的不在資料集內')
    for symbol in prepared:
        if len(observations.get(symbol, [])) != len(dates):
            raise ValueError('逐日訊號與市場日期長度不一致')
        for day, observation in zip(dates, observations[symbol]):
            signal = observation.get('entrySignal')
            if observation.get('date') != day or (signal is not None and not isinstance(signal, bool)):
                raise ValueError('逐日訊號日期或布林值無效')
            if observation.get('vidya') is not None and not _positive(observation['vidya']):
                raise ValueError('VIDYA 觀察值無效')
    initial = float(settings['initialCapital'])
    cash, positions, pending, trades, rejected, curve, decision_issues = initial, {}, {}, [], [], [], []
    peak, drawdown, incomplete = initial, 0.0, False
    eligible_days = 0
    for index in range(sample_start, len(dates)):
        day = dates[index]
        sizing = initial if settings['capitalBasis'] == 'initial' else (curve[-1]['equity'] if curve else initial)
        # 先賣後買；只按前一收盤已確定的訊號與固定代碼排序，不讀當日漲幅。
        for symbol in sorted(list(positions)):
            position, dataset = positions[symbol], prepared[symbol]
            if day in dataset.get('action_days', []):
                position['accountingUnknown'] = '持有期跨公司行動，股數與現金權利未核對'
            if position.get('exitSignalDate'):
                reason = position.get('accountingUnknown') or _fill_reason(symbol, dataset, index)
                if reason:
                    rejected.append({'symbol': symbol, 'date': day, 'kind': 'exit', 'reason': reason})
                    incomplete = True
                else:
                    raw = dataset['rows'][index]['open']
                    gross = position['shares'] * raw
                    proceeds = gross * (1 - side_cost)
                    cash += proceeds
                    pnl = proceeds - position['entryCash']
                    trades.append({**position, 'exitDate': day, 'exitPrice': raw, 'exitCost': gross * side_cost,
                                   'exitCash': proceeds, 'grossPnl': position['shares'] * (raw - position['entryPrice']),
                                   'netPnl': pnl, 'netReturnPct': pnl / position['entryCash'] * 100})
                    del positions[symbol]
        for symbol, signal_day in sorted(pending.items()):
            dataset = prepared[symbol]
            reason = _fill_reason(symbol, dataset, index)
            if reason:
                incomplete = True
            if any(p.get('accountingUnknown') for p in positions.values()):
                reason = reason or '既有持有權利未知，暫停新增部位'
            if symbol in positions or len(positions) >= (1 if benchmark_symbol else settings['maxPositions']):
                reason = reason or '已持有該標的或持股上限已滿'
            if sizing is None:
                reason = reason or '前一日收盤權益未知，不能決定配置'
            budget = min(cash, (sizing or 0) * (1 if benchmark_symbol else settings['allocationFraction']))
            raw = dataset['rows'][index].get('open')
            shares = 0 if reason else math.floor(budget / (raw * (1 + side_cost)) / settings['lotSize']) * settings['lotSize']
            # 浮點除乘可能在交易單位邊界多出極小金額；不能因容差而借入現金。
            if shares and shares * raw * (1 + side_cost) > budget:
                shares -= settings['lotSize']
            if shares <= 0:
                reason = reason or '可用現金不足最小交易單位'
            if reason:
                rejected.append({'symbol': symbol, 'date': day, 'signalDate': signal_day, 'kind': 'entry', 'reason': reason})
            else:
                gross = shares * raw
                used = gross * (1 + side_cost)
                cash -= used
                positions[symbol] = {'symbol': symbol, 'signalDate': signal_day, 'entryDate': day,
                                     'entryPrice': raw, 'shares': shares, 'entryCash': used,
                                     'entryCost': gross * side_cost, 'sizingEquity': sizing,
                                     'exitSignalDate': None, 'exitReason': None}
        pending = {}
        equity, exposure, valuation = cash, 0.0, []
        for symbol, position in sorted(positions.items()):
            dataset = prepared[symbol]
            row, observation = dataset['rows'][index], observations[symbol][index]
            # 進場當日有公司行動不回推前日持有權利；隔日持有事件則永遠保留未知。
            reason = position.get('accountingUnknown') or _quality(symbol, dataset, index)
            if reason:
                valuation.append({'symbol': symbol, 'reason': reason})
            else:
                value = position['shares'] * row['close']
                equity += value
                exposure += value
                if benchmark_symbol is None and not position.get('exitSignalDate'):
                    loss = row['close'] <= position['entryPrice'] * (1 - settings['stopLossPct'] / 100)
                    below = observation.get('vidya') is not None and row['close'] < observation['vidya']
                    if loss or below:
                        position.update(exitSignalDate=day, exitReason='close_stop' if loss else 'vidya_close')
            position.update(markDate=day, markPrice=None if reason else row['close'])
        if valuation:
            equity, incomplete = None, True
        else:
            peak = max(peak, equity)
            drawdown = max(drawdown, (peak - equity) / peak * 100)
        previous_equity = curve[-1]['equity'] if curve else initial
        daily_return = equity / previous_equity - 1 if equity is not None and _positive(previous_equity) else None
        curve.append({'date': day, 'cash': cash, 'equity': equity, 'dailyReturn': daily_return,
                      'exposurePct': exposure / equity * 100 if _positive(equity) else None,
                      'positions': len(positions), 'valuationReasons': valuation})
        for symbol in sorted(prepared):
            observation = observations[symbol][index]
            if benchmark_symbol is not None:
                candidate = symbol == benchmark_symbol and index == sample_start
            else:
                reason = _quality(symbol, prepared[symbol], index) or observation.get('reason')
                if reason or observation.get('entrySignal') is None or observation.get('vidya') is None:
                    decision_issues.append({'symbol': symbol, 'date': day, 'reason': reason or '收盤訊號未知'})
                    continue
                eligible_days += 1
                candidate = observation['entrySignal']
            if candidate and symbol not in positions:
                pending[symbol] = day
    final = curve[-1]['equity'] if curve else None
    status = 'insufficient' if not curve else 'unknown' if incomplete or decision_issues else 'complete'
    if benchmark_symbol is not None and not positions and not trades and pending:
        status = 'insufficient'
    pending_rows = [{'symbol': s, 'signalDate': d, 'kind': 'entry', 'reason': '缺下一根市場交易日資料，未成交'} for s, d in sorted(pending.items())]
    pending_rows += [{'symbol': s, 'signalDate': p['exitSignalDate'], 'kind': 'exit', 'reason': '缺下一根有效開盤，尚未平倉'}
                     for s, p in sorted(positions.items()) if p.get('exitSignalDate')]
    sharpe = daily_sharpe(curve, annual_risk_free_rate=settings['annualRiskFreeRate'],
                         periods_per_year=settings['periodsPerYear'], had_entry=bool(trades or positions))
    if status != 'complete' and sharpe['reasonCode'] not in ('missing_daily_return', 'insufficient_samples'):
        sharpe.update(value=None, reason='投組成交或決策證據未完整核對', reasonCode='incomplete_portfolio')
    return {'status': status, 'costRatePerSide': side_cost, 'eligibleAssetDays': eligible_days,
            'initialCapital': initial, 'finalEquity': final,
            'dailySharpe': sharpe['value'], 'sharpeEvidence': sharpe,
            'totalReturnPct': (final / initial - 1) * 100 if final is not None and status == 'complete' else None,
            'maxDrawdownPct': drawdown if status == 'complete' else None,
            'observedDrawdownPct': drawdown, 'closedTrades': len(trades),
            'netZeroTrades': sum(math.isclose(t['netPnl'], 0, abs_tol=1e-9) for t in trades),
            'winRatePct': sum(t['netPnl'] > 1e-9 for t in trades) / len(trades) * 100 if trades else None,
            'tradeStatus': 'closed' if trades else 'open_only' if positions else 'no_trades',
            'noTradesReason': None if trades else '期末部位尚未平倉' if positions else
                              '成交或訊號證據不足' if status != 'complete' else
                              '收盤訊號已成立但缺下一根開盤' if pending_rows else
                              '進場因資金或部位限制未成交' if rejected else '期間內沒有可交易的收盤穿越訊號',
            'trades': trades, 'openPositions': list(positions.values()), 'pending': pending_rows,
            'rejected': rejected, 'decisionIssues': decision_issues, 'curve': curve}


def daily_sharpe(curve, *, annual_risk_free_rate=0.0, periods_per_year=252, had_entry=True):
    """與 backtest_v3 一致：日簡單報酬減複利換算日無風險率，採樣本標準差。"""
    settings = _risk_settings(annual_risk_free_rate, periods_per_year)
    evidence = {**settings, 'basis': 'daily_simple_excess_return_sample_standard_deviation',
                'baselineDate': curve[0]['date'] if curve else None,
                'returnWindow': 'close_to_close_after_first_close',
                'value': None, 'n': 0, 'reason': None, 'reasonCode': None}
    # 與 backtest_v3 observed>1 一致：首根收盤只作基準，不另加初始本金的零報酬。
    returns = [row.get('dailyReturn') for row in curve[1:]]
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in returns):
        return {**evidence, 'reason': '每日投組報酬未知，不跨缺日接續', 'reasonCode': 'missing_daily_return'}
    evidence['n'] = len(returns)
    if len(returns) < 2:
        return {**evidence, 'reason': '不足兩個每日報酬樣本', 'reasonCode': 'insufficient_samples'}
    excess = [value - settings['dailyRiskFreeRate'] for value in returns]
    mean, deviation = statistics.mean(excess), statistics.stdev(excess)
    evidence.update(meanDailyExcessReturn=mean, sampleStandardDeviation=deviation)
    if deviation == 0:
        return {**evidence, 'reason': '每日報酬沒有波動' if had_entry else '沒有實際成交，權益沒有波動',
                'reasonCode': 'zero_variance' if had_entry else 'no_trades'}
    return {**evidence, 'value': mean / deviation * math.sqrt(periods_per_year)}


def daily_information_ratio(curve, benchmark_curve, *, periods_per_year=252):
    """同日投組減基準報酬的年化資訊比率，不作無風險 Sharpe 使用。"""
    _risk_settings(0, periods_per_year)
    if len(curve) != len(benchmark_curve) or any(a['date'] != b['date'] for a, b in zip(curve, benchmark_curve)):
        return {'value': None, 'n': 0, 'reason': '投組與基準日期不一致'}
    pairs = [(a.get('dailyReturn'), b.get('dailyReturn')) for a, b in zip(curve[1:], benchmark_curve[1:])]
    if any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value)
           for pair in pairs for value in pair):
        return {'value': None, 'n': 0, 'reason': '每日投組或基準報酬未知，不跨缺日接續'}
    values = [a - b for a, b in pairs]
    if len(values) < 2:
        return {'value': None, 'n': len(values), 'reason': '每日樣本不足'}
    deviation = statistics.stdev(values)
    if deviation == 0:
        return {'value': None, 'n': len(values), 'reason': '超額日報酬變異為零'}
    return {'value': statistics.mean(values) / deviation * math.sqrt(periods_per_year), 'n': len(values), 'reason': None}


def _report(datasets, dates, observations, start, settings):
    scenarios, reference = {}, {}
    for name, cost in SCENARIOS.items():
        result = simulate_portfolio(datasets, dates, observations, sample_start=start, config=settings, side_cost=cost)
        bench = simulate_portfolio(datasets, dates, observations, sample_start=start, config=settings,
                                   side_cost=cost, benchmark_symbol='0050') if '0050' in datasets else None
        if bench is not None:
            reference[name] = bench
        aligned = bench is not None and bench['status'] == result['status'] == 'complete'
        relative = daily_information_ratio(result['curve'], bench['curve'], periods_per_year=settings['periodsPerYear']) if aligned else {'value': None, 'n': 0, 'reason': '投組或 0050 基準資料未完整核對'}
        relative.update(benchmarkSymbol='0050', periodsPerYear=settings['periodsPerYear'],
                        baselineDate=result['curve'][0]['date'] if result['curve'] else None,
                        returnWindow='close_to_close_after_first_close',
                        basis='daily_benchmark_excess_return_sample_standard_deviation')
        result.update(informationRatio=relative['value'], benchmarkEvidence=relative,
                      excessReturnPctPoints=result['totalReturnPct'] - bench['totalReturnPct'] if aligned else None)
        scenarios[name] = result
    return {'rules': [{'key': 'vidya_cross', 'label': '收盤穿越 VIDYA，次日開盤成交', 'scenarios': scenarios}],
            'benchmark': {'label': '0050 同起點持有，逐日原價估值', 'scenarios': reference,
                          'reason': None if reference else '資料集未提供 0050 基準'}}


def build_portfolio(datasets, market_dates, *, sample_start=0, as_of=None, config=None):
    """純研究入口；市場日須明列缺日，參數固定後才切分時間，不尋找最佳組合。"""
    settings = _config(config)
    prepared, dates = _normalize(datasets, market_dates, as_of)
    if isinstance(sample_start, bool) or not isinstance(sample_start, int) or not 0 <= sample_start <= len(dates):
        raise ValueError('研究起點無效')
    observations = {symbol: _observations(symbol, data, settings) for symbol, data in prepared.items()}
    report = _report(prepared, dates, observations, sample_start, settings)
    test_date = settings['testStart']
    split = next((i for i, day in enumerate(dates) if test_date and day >= test_date), len(dates))
    evaluation = {'method': '固定參數、固定日期的時間切分；不最佳化、不用測試集調參',
                  'testStart': test_date, 'optimized': False, 'status': 'insufficient',
                  'reason': '切分日前後的研究資料不足', 'training': None, 'test': None}
    if test_date and sample_start < split < len(dates):
        training_data = {s: {**d, 'rows': d['rows'][:split]} for s, d in prepared.items()}
        training_observations = {s: values[:split] for s, values in observations.items()}
        evaluation.update(status='fixed_parameter_evaluation', reason=None,
                          training=_report(training_data, dates[:split], training_observations, sample_start, settings),
                          test=_report(prepared, dates, observations, split, settings))
    status = 'complete' if report['rules'][0]['scenarios']['baseNet']['status'] == 'complete' else 'limited'
    evidence = {s: {'rows': d['rows'], 'calendar_years': d.get('calendar_years'),
                    'action_days': d.get('action_days'), 'action_coverage': d.get('action_coverage'),
                    'action_coverage_kind': d.get('action_coverage_kind')} for s, d in prepared.items()}
    return {'version': VERSION, 'status': status, **report, 'config': settings,
            'inputDigest': _digest({'datasets': evidence, 'dates': dates, 'start': sample_start, 'config': settings, 'version': VERSION}),
            'range': {'start': dates[sample_start] if sample_start < len(dates) else None,
                      'end': dates[-1] if dates else None, 'warmupDays': sample_start,
                      'marketDays': len(dates) - sample_start},
            'assets': [{'symbol': s, 'rows': values[sample_start:]} for s, values in observations.items()],
            'evaluation': evaluation,
            'summary': {'label': 'VIDYA 現金受限工程研究', 'strategyValidation': False,
                        'sampleSymbols': sorted(prepared), 'optimized': False},
            'sourceNotes': ['僅讀既有快取；缺日、停牌與公司行動涵蓋不足不補價。'],
            'notes': ['預設 20 棒 SMA 初始化、9 期 CMO，alpha=2/21×abs(CMO)；每次使用最後 60 棒工程窗口，並非文章策略驗證。',
                      '收盤由不高於 VIDYA 穿越為高於 VIDYA 才進場；跌破 VIDYA 或相對原始進場價收盤下跌 8% 才退出，最早下一交易日開盤。',
                      '進場的下一市場日缺資料即取消該委託並保留未知；待出場遇缺資料保留至下個可核對開盤，不用同棒高低價猜成交順序。',
                      '同日先賣後買，再按代碼遞增；固定初始本金或前一日已知權益配置，股數向下取最小單位，現金不借貸。',
                      '每邊費用與滑價合計為 0／25／50 基點；現金流依原價乘 (1±成本) 計算，沒有稅制、最低費用或委託簿成交保證。',
                      '每日以原始收盤價估值；期末未平倉不假設賣出，沒有扣尚未發生的出場成本。',
                      '公司行動跨持有期的股數與現金權利未知，後續權益維持未知；ETF 的官方股票除權息涵蓋不等於 ETF 涵蓋。',
                      '每日夏普以日簡單報酬減複利換算的日無風險率，除以樣本標準差後年化；預設無風險年率為零、每年 252 日。',
                      '每日夏普與資訊比率均以第一根收盤作基準，只從第二根收盤起形成日報酬樣本，不加入初始本金至首根收盤的零報酬。',
                      '相對 0050 資訊比率另列 informationRatio，以同日報酬差的平均／樣本標準差年化，與無風險夏普分開。',
                      '固定切分日預設 2024-01-01；訓練區與測試區各從相同本金開始，測試暖機只用過去價格，沒有選參或最佳化。',
                      '快取與品質證據可能事後補齊，並非各歷史時點當下取得的資料快照。']}


def build_saved_portfolio(db_path, as_of=None, *, now=None, config=None):
    """唯讀同一 SQLite 快照，沿用突破觀察的資料正規化，不建立任何資料表。"""
    settings = _config(config)
    clock = (now or datetime.now(TZ)).astimezone(TZ)
    cutoff = date.fromisoformat(as_of) if as_of else clock.date()
    if cutoff > clock.date():
        raise ValueError('截至日期不得晚於今天')
    try:
        try:
            from . import K線事件 as events
            from .突破觀察 import load_dataset
        except ImportError:
            import K線事件 as events
            from 突破觀察 import load_dataset
        with closing(sqlite3.connect(Path(db_path).resolve().as_uri() + '?mode=ro', uri=True, timeout=15)) as conn:
            conn.execute('PRAGMA query_only=ON')
            conn.execute('BEGIN')
            source_status = {symbol: events.freshness(conn, symbol, clock) for symbol in SYMBOLS}
            expected = source_status['2330'].get('expectedSession')
            if not expected:
                raise ValueError('官方最新已完成市場日尚未核對')
            cutoff = min(cutoff, date.fromisoformat(expected))
            datasets = {symbol: load_dataset(conn, symbol, cutoff.isoformat()) for symbol in SYMBOLS}
            calendar_sources = conn.execute('SELECT source FROM market_sessions WHERE session_date<=?',
                                            (cutoff.isoformat(),)).fetchall()
            if any(not str(source).startswith(('TWSE', 'TPEX')) for (source,) in calendar_sources):
                raise ValueError('官方市場日曆來源未核對')
            if any('session_dates' not in dataset for dataset in datasets.values()):
                raise ValueError('共用資料介接未提供完整市場交易日，不能以行情存在日期推定')
            # 共用 loader 以年度休市／補班與已核對月份重建日曆；不可退回只看
            # market_sessions 的已匯入日期，否則兩檔同日缺資料會一起被壓縮掉。
            timeline = sorted({day for dataset in datasets.values() for day in dataset['session_dates']
                               if day <= cutoff.isoformat()})
            start = events.range_start('5y', cutoff, None).isoformat()
            first = next((i for i, day in enumerate(timeline) if day >= start), len(timeline))
            warmup = min(settings['warmupBars'], first)
            timeline = timeline[first - warmup:]
            # 資料庫沒有五年前價格時，起頭完整窗口仍只作暖機，不列入績效。
            sample_start = max(warmup, min(settings['warmupBars'], len(timeline)))
        result = build_portfolio(datasets, timeline, sample_start=sample_start, config=settings)
        result['sourceStatus'] = source_status
        result['sourceNotes'].append('2330／0050 小範圍工程案例，不可外推全市場或宣稱策略已驗證。')
        return result
    except (sqlite3.Error, ValueError, TypeError, KeyError, ImportError) as exc:
        return {'version': VERSION, 'status': 'unavailable', 'reason': str(exc), 'rules': [],
                'assets': [], 'benchmark': None, 'summary': {'strategyValidation': False},
                'notes': ['既有快取或來源證據不足；未下載資料，未把缺資料視為零。'], 'sourceNotes': []}
