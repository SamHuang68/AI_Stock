"""突破訊號的隔日成交情境與公平對照；只計算已核對資料，不抓行情、不寫入。"""
from __future__ import annotations

import hashlib
import math
from bisect import bisect_right
from collections import Counter
from random import Random
from statistics import mean, median

try:
    from .突破觀察 import HORIZONS, RULES
except ImportError:
    from 突破觀察 import HORIZONS, RULES

VERSION = 'breakout-execution-v1'
SCENARIOS = {'gross': 0., 'baseNet': .0025, 'stressNet': .005}
DRAWS = 1000


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _quantile(ordered: list[float], probability: float) -> float | None:
    if not ordered:
        return None
    position = (len(ordered) - 1) * probability
    lower = int(position)
    return ordered[lower] + (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]) * (position - lower)


def _distribution(values: list[float]) -> dict:
    ordered = sorted(values)
    return {'n': len(values), 'mean': mean(values) if values else None,
            'median': median(values) if values else None,
            'positivePct': sum(value > 0 for value in values) / len(values) * 100 if values else None,
            'p05': _quantile(ordered, .05), 'q25': _quantile(ordered, .25), 'q75': _quantile(ordered, .75),
            'min': ordered[0] if ordered else None, 'max': ordered[-1] if ordered else None,
            'smallSample': len(values) < 30}


def _scenario_stats(trades: list[dict]) -> dict:
    return {'n': len(trades), **{key: _distribution([trade[key] for trade in trades]) for key in SCENARIOS}}


def _reasons(reasons: list[str]) -> list[dict]:
    return [{'reason': reason, 'count': count} for reason, count in sorted(Counter(reasons).items())]


class _Market:
    """預先建立品質索引，避免每個規則／抽樣重讀資料庫或重掃長區間。"""

    def __init__(self, rows: list[dict], calendar_years: set[int], action_days: set[str], action_coverage: object):
        self.rows = rows
        self.dates = [row['date'] for row in rows]
        if any(previous >= current for previous, current in zip(self.dates, self.dates[1:])):
            raise ValueError('成交研究時間軸須依日期遞增且不得重複')
        self.calendar_years = calendar_years
        if isinstance(action_coverage, dict):
            self.coverage = (action_coverage.get('start'), action_coverage.get('end'))
        else:
            self.coverage = tuple(action_coverage) if action_coverage else None
        actions = set(action_days)
        self.issues, self.issue_prefix = [], [0]
        for i, row in enumerate(rows):
            issues = list(row.get('issues', ['資料品質尚未核對']))
            if row.get('source') not in ('TWSE', 'TPEX'):
                issues.append('歷史來源尚未經官方核對')
            if not all(_number(row.get(key)) for key in ('open', 'high', 'low', 'close', 'volume')):
                issues.append('價格或成交量缺值／無成交')
            elif not row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high']:
                issues.append('開高低收邊界無效')
            reason = '；'.join(sorted(set(issues)))
            self.issues.append(reason)
            self.issue_prefix.append(self.issue_prefix[-1] + bool(reason))
            if i and _number(row.get('close')) and _number(rows[i - 1].get('close')):
                if abs(row['close'] / rows[i - 1]['close'] - 1) > .15:
                    actions.add(row['date'])
        self.actions = sorted(actions)

    def trade(self, index: int, horizon: int) -> dict:
        entry, end = index + 1, index + horizon
        trade = {'signalDate': self.dates[index], 'entryDate': self.dates[entry] if entry < len(self.rows) else None,
                 'exitDate': self.dates[end] if end < len(self.rows) else None, 'horizon': horizon,
                 'status': 'immature', 'reason': '截至日尚未走完指定市場交易日，未納入成熟統計',
                 'entryPrice': None, 'exitPrice': None, **dict.fromkeys(SCENARIOS), 'nonOverlapping': False}
        if end >= len(self.rows):
            return trade
        trade.update(status='excluded', reason=None)
        first_day, last_day = self.dates[index], self.dates[end]
        if self.issue_prefix[end + 1] != self.issue_prefix[index]:
            failures = [f'{self.dates[i]}：{self.issues[i]}' for i in range(index, end + 1) if self.issues[i]]
            trade['reason'] = '成交區間含缺值、無成交或未核對資料：' + '；'.join(failures)
        elif any(year not in self.calendar_years for year in range(int(first_day[:4]), int(last_day[:4]) + 1)):
            trade['reason'] = '成交區間的交易日曆尚未完整核對'
        elif not self.coverage or not self.coverage[0] or not self.coverage[1] or not self.coverage[0] <= first_day <= last_day <= self.coverage[1]:
            trade['reason'] = '公司行動涵蓋區間尚未核對'
        elif bisect_right(self.actions, last_day) > bisect_right(self.actions, first_day):
            trade['reason'] = '成交區間跨公司行動或重大價格斷點，已排除'
        elif any(self.rows[i]['open'] == self.rows[i]['high'] == self.rows[i]['low'] == self.rows[i]['close'] for i in {entry, end}):
            trade['reason'] = '進場或出場日為一價日，無法證實可按假設價格成交'
        if trade['reason']:
            return trade
        entry_price, exit_price = self.rows[entry]['open'], self.rows[end]['close']
        trade.update(status='mature', entryPrice=entry_price, exitPrice=exit_price)
        trade.update({key: (exit_price * (1 - cost) / (entry_price * (1 + cost)) - 1) * 100 for key, cost in SCENARIOS.items()})
        return trade


def _random_baseline(*, symbol: str, key: str, horizon: int, mature: list[dict], candidates: list[dict]) -> dict:
    seed = hashlib.sha256(f'{VERSION}|{symbol}|{key}|{horizon}'.encode('utf-8')).hexdigest()
    groups: dict[str, list[dict]] = {}
    for trade in candidates:
        groups.setdefault(trade['signalDate'][:4], []).append(trade)
    targets = Counter(trade['signalDate'][:4] for trade in mature)
    strata = [{'year': year, 'signals': count, 'candidates': len(groups.get(year, []))} for year, count in sorted(targets.items())]
    result = {'status': '無成熟訊號', 'draws': 0, 'seed': seed, 'n': len(mature), 'yearStrata': strata,
              'note': '同股票、同訊號年份成熟候選，依各年份訊號筆數分層。每組無放回，候選包含訊號日，持有區間可重疊；比例不是統計檢定的 p 值。',
              'metrics': {key: dict.fromkeys(('signalMean', 'p025', 'median', 'p975', 'atLeastSignalPct')) for key in SCENARIOS}}
    if not mature:
        return result
    if any(stratum['candidates'] < stratum['signals'] for stratum in strata):
        result.update(status='候選不足', note='同年份成熟候選少於訊號筆數，無法形成相同樣本數的比較。')
        return result
    rng = Random(int(seed, 16))
    distributions = {key: [] for key in SCENARIOS}
    for _ in range(DRAWS):
        selected = [trade for year, count in sorted(targets.items()) for trade in rng.sample(groups[year], count)]
        for scenario in SCENARIOS:
            distributions[scenario].append(math.fsum(trade[scenario] for trade in selected) / len(selected))
    result.update(status='完成', draws=DRAWS)
    for scenario, values in distributions.items():
        signal_mean = math.fsum(trade[scenario] for trade in mature) / len(mature)
        ordered = sorted(values)
        result['metrics'][scenario] = {'signalMean': signal_mean, 'p025': _quantile(ordered, .025),
                                       'median': median(values), 'p975': _quantile(ordered, .975),
                                       'atLeastSignalPct': sum(value >= signal_mean for value in values) / DRAWS * 100}
    return result


def build_execution(rows: list[dict], *, symbol: str, calendar_years: set[int], action_days: set[str],
                    action_coverage: tuple | list | dict | None, sample_start: int = 0,
                    benchmark_rows: list[dict] | None = None, benchmark_action_days: set[str] | None = None,
                    benchmark_action_coverage: tuple | list | dict | None = None) -> dict:
    """以市場交易日索引模擬成交；暖機只供既有 research 判定，不納入本期訊號。"""
    if not 0 <= sample_start <= len(rows):
        raise ValueError('成交研究暖機起點超出資料範圍')
    market = _Market(rows, calendar_years, action_days, action_coverage)
    benchmark_by_day = {row['date']: row for row in benchmark_rows or []}
    # 始終依個股同一市場交易日時間軸配對，缺值不可跳到下一個有價格日期。
    matched_rows = [benchmark_by_day.get(day, {'date': day, 'issues': ['0050 交易日資料缺漏']}) for day in market.dates]
    benchmark_market = _Market(matched_rows, calendar_years, benchmark_action_days or set(), benchmark_action_coverage)
    outcomes = {(i, horizon): market.trade(i, horizon) for i in range(sample_start, len(rows)) for horizon in HORIZONS
                if any(rows[i].get('research', {}).get('eligible', {}).values())}
    benchmark_outcomes: dict[tuple[int, int], dict] = {}
    groups = []
    for rule in RULES:
        key = rule['key']
        eligible = [i for i in range(sample_start, len(rows)) if rows[i].get('research', {}).get('eligible', {}).get(key)]
        eligible_set = set(eligible)
        signal_indices = [i for i in eligible if key in rows[i].get('research', {}).get('signals', [])]
        ineligible = [rows[i].get('research', {}).get('reason', {}).get(key, '研究資格尚未核對')
                      for i in range(sample_start, len(rows)) if i not in eligible_set]
        group = {'key': key, 'label': rule['label'], 'signalCount': len(signal_indices),
                 'eligibleDays': len(eligible), 'ineligibleReasons': _reasons(ineligible), 'horizons': {}}
        for horizon in HORIZONS:
            trades = [dict(outcomes[(i, horizon)]) for i in signal_indices]
            mature, independent, stock_pairs, benchmark_pairs, excess_pairs = [], [], [], [], []
            benchmark_failures = []
            last_exit = -1
            for index, trade in zip(signal_indices, trades):
                if trade['status'] != 'mature':
                    trade['benchmark'] = {'status': 'excluded', 'reason': '個股交易未成熟或已排除，不納入配對比較',
                                          'entryDate': trade['entryDate'], 'exitDate': trade['exitDate'],
                                          'entryPrice': None, 'exitPrice': None, **dict.fromkeys(SCENARIOS)}
                    continue
                mature.append(trade)
                if index + 1 > last_exit:
                    trade['nonOverlapping'] = True
                    independent.append(trade)
                    last_exit = index + horizon
                pair_key = (index, horizon)
                if pair_key not in benchmark_outcomes:
                    benchmark_outcomes[pair_key] = benchmark_market.trade(index, horizon)
                benchmark = benchmark_outcomes[pair_key]
                trade['benchmark'] = {k: v for k, v in benchmark.items() if k not in ('signalDate', 'horizon', 'nonOverlapping')}
                if benchmark['status'] == 'mature':
                    stock_pairs.append(trade)
                    benchmark_pairs.append(benchmark)
                    excess_pairs.append({scenario: trade[scenario] - benchmark[scenario] for scenario in SCENARIOS})
                else:
                    benchmark_failures.append(benchmark['reason'])
            candidates = [outcomes[(i, horizon)] for i in eligible if outcomes[(i, horizon)]['status'] == 'mature']
            group['horizons'][str(horizon)] = {
                'counts': {'signals': len(trades), 'mature': len(mature),
                           'immature': sum(trade['status'] == 'immature' for trade in trades),
                           'excluded': sum(trade['status'] == 'excluded' for trade in trades),
                           'nonOverlapping': len(independent), 'overlapExcluded': len(mature) - len(independent)},
                'excludedReasons': _reasons([trade['reason'] for trade in trades if trade['status'] == 'excluded']),
                'raw': _scenario_stats(mature), 'nonOverlapping': _scenario_stats(independent),
                'random': _random_baseline(symbol=symbol, key=key, horizon=horizon, mature=mature, candidates=candidates),
                'benchmark': {'symbol': '0050', 'label': '元大台灣 50', 'eligibleStockCount': len(mature),
                              'pairedCount': len(stock_pairs), 'excludedCount': len(benchmark_failures),
                              'excludedReasons': _reasons(benchmark_failures), 'stock': _scenario_stats(stock_pairs),
                              'benchmark': _scenario_stats(benchmark_pairs), 'excess': _scenario_stats(excess_pairs),
                              'note': '三組統計只使用完全相同的可配對交易；差額單位為百分點，使用原始價格且未含股息。'},
                'trades': trades}
        groups.append(group)
    return {'version': VERSION, 'horizons': list(HORIZONS), 'rules': groups,
            'assumptions': {'entry': '訊號後下一個市場交易日開盤',
                            'exit': '訊號後第 h 個市場交易日收盤；h=1 為進場當日收盤',
                            'baseCostPerSidePct': .25, 'stressCostPerSidePct': .5,
                            'costNote': '雙邊總成本情境假設，非實際稅率或券商費率；未含股息。',
                            'notes': ['訊號、進場與出場均受所選截至日限制；不把下一個有價格日期當成下一交易日。',
                                      '公司行動、重大價格斷點或進出場一價日保守排除；資料不足的報酬為無值。',
                                      '日線無委託簿與開收盤可成交數量；即使不是一價日，也不保證所需部位可按假設價格成交。',
                                      '使用目前已核對資料，非當時發布版本；不計算複利投資組合、VIDYA 或停損。',
                                      '非重疊交易按最早成熟訊號選取；下一筆進場日須晚於上一筆出場日。',
                                      '隨機與 0050 對照使用全部成熟首次訊號；隨機候選需通過相同規則資格及成交品質。',
                                      '描述統計、小樣本提醒與隨機比例均不代表統計顯著性或未來交易優勢。']}}
