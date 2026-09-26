"""沿用個股訊號引擎的離線研究；情境對照、時間區塊與固定分段。"""
from __future__ import annotations

import bisect
import hashlib
import json
import random
import statistics
from collections import Counter, defaultdict
from datetime import date

try:
    from . import stock_signals as ss
except ImportError:
    import stock_signals as ss

VERSION = 'st-stock-research/v1'
CONTEXT = 'market_up_stock_up'
POLICY = {
    'version': VERSION, 'cutoff': '2024-01-01', 'horizons': [5, 20],
    'entryLag': 1, 'referenceBars': 252, 'minControls': 20,
    'minEvents': 100, 'minSymbols': 5, 'minBlocks': 8,
    'bootstrapReplicates': 1200, 'seed': 20260927,
    'context': CONTEXT, 'selectionHorizon': 5,
    'priceBasis': 'unadjusted_snapshot',
}

# 在看過第一輪歷史結果後提出，不能宣稱是未接觸資料的事前假說。
RSI_POLICY = {**POLICY, 'version': 'st-rsi-rebound-research/v1',
              'context': 'market_not_down_stock_down', 'signalId': 'mom_rsi_rebound',
              'hypothesisOrigin': '第一輪歷史探索後提出；只驗證固定 RSI 假說，不搜尋參數'}


def context_matches(market_state, stock_state, context=CONTEXT):
    if context == CONTEXT:
        return market_state == 'up' and stock_state == 'up'
    if context == RSI_POLICY['context']:
        return market_state in ('up', 'other') and stock_state == 'down'
    raise ValueError('未知研究情境')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def regime(frame, t):
    """只用當日及以前既有均線；未知資料不當成盤整。"""
    if t < 64 or frame['sma60'][t] is None or frame['sma60'][t - 5] is None:
        return 'unknown'
    close, ma, before = frame['close'][t], frame['sma60'][t], frame['sma60'][t - 5]
    if close > ma and ma > before:
        return 'up'
    if close < ma and ma < before:
        return 'down'
    return 'other'


def market_regimes(bars):
    frame = ss.build_frame(bars)
    return {d: regime(frame, t) for t, d in enumerate(frame['date'])}


def quarter(day):
    d = date.fromisoformat(day)
    return f'{d.year}-Q{(d.month - 1) // 3 + 1}'


def block_values(rows, key='deltaRet'):
    groups = defaultdict(list)
    for row in rows:
        groups[quarter(row['date'])].append(row[key])
    return {q: statistics.fmean(v) for q, v in sorted(groups.items())}


def block_interval(values, policy=POLICY):
    """各季度等權重抽，保留同季股票的共同行情；不是多重比較後的檢定。"""
    vals = list(values)
    if len(vals) < policy['minBlocks']:
        return None
    rng = random.Random(policy['seed'])
    means = sorted(statistics.fmean(rng.choices(vals, k=len(vals)))
                   for _ in range(policy['bootstrapReplicates']))
    return [means[int((len(means) - 1) * .025)], means[int((len(means) - 1) * .975)]]


def summarize(rows, policy=POLICY):
    n = len(rows)
    symbols = len({r['symbol'] for r in rows})
    blocks = block_values(rows)
    eligible = n >= policy['minEvents'] and symbols >= policy['minSymbols'] and len(blocks) >= policy['minBlocks']
    result = {'n': n, 'symbols': symbols, 'quarters': len(blocks),
              'gate': 'exploratory' if eligible else 'insufficient',
              'window': [min((r['date'] for r in rows), default=None),
                         max((r['date'] for r in rows), default=None)]}
    if n < ss.MIN_SAMPLE:
        return {**result, 'upRatio': None, 'medianRet': None, 'medianAdverse': None,
                'adverseP10': None, 'meanControlRet': None, 'meanControlUp': None,
                'meanDeltaRet': None, 'blockMeanDeltaRet': None, 'deltaRetCI95': None}
    adverse = sorted(r['adverse'] for r in rows)
    return {**result, 'upRatio': statistics.fmean(r['ret'] > 0 for r in rows),
            'medianRet': statistics.median(r['ret'] for r in rows),
            'medianAdverse': statistics.median(adverse), 'adverseP10': adverse[int((n - 1) * .1)],
            'meanControlRet': statistics.fmean(r['controlRet'] for r in rows),
            'meanControlUp': statistics.fmean(r['controlUp'] for r in rows),
            'meanDeltaRet': statistics.fmean(r['deltaRet'] for r in rows),
            'blockMeanDeltaRet': statistics.fmean(blocks.values()),
            'deltaRetCI95': block_interval(blocks.values(), policy) if eligible else None,
            'yearDeltaRet': {y: statistics.fmean(r['deltaRet'] for r in rows if r['date'][:4] == y)
                             for y in sorted({r['date'][:4] for r in rows})},
            'maxSymbolShare': max(Counter(r['symbol'] for r in rows).values()) / n}


def context_increment(rows, policy=POLICY):
    """同季度配對：情境子集合相對同一訊號未篩選集合的增量。"""
    all_blocks = block_values(rows)
    selected = [r for r in rows if r['context']]
    chosen_blocks = block_values(selected)
    differences = [v - all_blocks[q] for q, v in chosen_blocks.items()]
    eligible = (len(selected) >= policy['minEvents'] and
                len({r['symbol'] for r in selected}) >= policy['minSymbols'] and
                len(differences) >= policy['minBlocks'])
    return {'quarters': len(differences),
            'mean': statistics.fmean(differences) if differences else None,
            'ci95': block_interval(differences, policy) if eligible else None}


class Reference:
    """同股票、同大盤情境的已成熟對照；前綴和避免逐事件重掃完整歷史。"""
    def __init__(self, frame, outcomes, market):
        grouped = defaultdict(list)
        for o in outcomes:
            r = market.get(frame['date'][o['t']], 'unknown')
            if r != 'unknown':
                grouped[r].append(o)
        self.groups = {}
        for r, values in grouped.items():
            indices, returns, ups = [], [0.0], [0]
            for o in values:
                indices.append(o['t'])
                returns.append(returns[-1] + o['ret'])
                ups.append(ups[-1] + (o['ret'] > 0))
            self.groups[r] = indices, returns, ups

    def at(self, t, hz, market_regime, policy=POLICY):
        if market_regime not in self.groups:
            return None
        indices, returns, ups = self.groups[market_regime]
        lo = bisect.bisect_left(indices, max(64, t - policy['referenceBars']))
        # 對照的結果必須在事件日之前可知，不使用事件當日或未來結果。
        hi = bisect.bisect_left(indices, t - policy['entryLag'] - hz)
        n = hi - lo
        if n < policy['minControls']:
            return None
        return {'n': n, 'ret': (returns[hi] - returns[lo]) / n,
                'up': (ups[hi] - ups[lo]) / n,
                'lastOutcomeIndex': indices[hi - 1] + policy['entryLag'] + hz}


class Study:
    def __init__(self, benchmark_bars, policy=None):
        self.policy = dict(POLICY if policy is None else policy)
        self.market = market_regimes(benchmark_bars)
        self.market_positions = {d: i for i, d in enumerate(self.market)}
        self.benchmark_digest = digest(benchmark_bars)
        self.rows = {s['id']: {h: [] for h in self.policy['horizons']} for s in ss.SIGNALS}
        self.coverage = []
        self.skipped = defaultdict(int)

    def add(self, symbol, frame):
        dates = frame['date']
        self.coverage.append({'symbol': symbol, 'bars': len(dates), 'from': dates[0], 'to': dates[-1],
                              'digest': digest(frame),
                              'chipDays': sum(x is not None for x in frame['trust'])})
        starts_by_signal = {s['id']: ss.event_indices(frame, s) for s in ss.SIGNALS}
        gaps = [0]
        for i in range(1, len(dates)):
            previous, current = self.market_positions.get(dates[i - 1]), self.market_positions.get(dates[i])
            gaps.append(gaps[-1] + int(previous is None or current is None or current != previous + 1))
        for hz in self.policy['horizons']:
            # 新研究統一下一交易日收盤；既有體檢歷史描述的計價契約維持原樣。
            outcomes = ss.forward_outcomes(frame, range(64, len(dates)), hz, 'bull', self.policy['entryLag'])
            aligned = [o for o in outcomes if gaps[o['t'] + self.policy['entryLag'] + hz] == gaps[o['t']]]
            self.skipped['missing_sessions'] += len(outcomes) - len(aligned)
            outcomes = aligned
            by_index = {o['t']: o for o in outcomes}
            references = Reference(frame, outcomes, self.market)
            for spec in ss.SIGNALS:
                for t in starts_by_signal[spec['id']]:
                    if t not in by_index:
                        self.skipped['immature_or_warmup'] += 1
                        continue
                    mr = self.market.get(dates[t], 'unknown')
                    control = references.at(t, hz, mr, self.policy)
                    if control is None:
                        self.skipped['missing_market_or_controls'] += 1
                        continue
                    o = by_index[t]
                    end = dates[t + self.policy['entryLag'] + hz]
                    self.rows[spec['id']][hz].append({
                        'symbol': symbol, 'date': dates[t], 'endDate': end,
                        'ret': o['ret'], 'adverse': o['adverse'],
                        'controlRet': control['ret'], 'controlUp': control['up'],
                        'controlN': control['n'], 'controlEndDate': dates[control['lastOutcomeIndex']],
                        'deltaRet': o['ret'] - control['ret'], 'marketRegime': mr,
                        'stockRegime': regime(frame, t),
                        'context': context_matches(mr, regime(frame, t), self.policy['context']),
                    })

    def finish(self):
        signals = []
        candidates = []
        cutoff = self.policy['cutoff']
        for spec in ss.SIGNALS:
            horizons = []
            for hz, rows in self.rows[spec['id']].items():
                train = [r for r in rows if r['endDate'] < cutoff]
                check = [r for r in rows if r['date'] >= cutoff]
                item = {'horizon': hz, 'all': summarize(rows, self.policy)}
                for key, part in [('training', train), ('temporalCheck', check)]:
                    item[key] = {'unfiltered': summarize(part, self.policy),
                                 'context': summarize([r for r in part if r['context']], self.policy),
                                 'increment': context_increment(part, self.policy)}
                horizons.append(item)
                if hz == self.policy['selectionHorizon'] and spec['direction'] == 'bull':
                    tr = item['training']
                    ci, inc = tr['context']['deltaRetCI95'], tr['increment']['ci95']
                    if ci and inc and ci[0] > 0 and inc[0] > 0:
                        candidates.append((min(ci[0], inc[0]), spec['id'], item))
            signals.append({'signalId': spec['id'], 'label': spec['label'],
                            'direction': spec['direction'], 'horizons': horizons})
        selection = {'status': 'no_candidate', 'signalId': None,
                     'reason': '沒有偏多訊號同時通過訓練段的情境差距與增量門檻；不改門檻、不改挑法。'}
        if candidates:
            _, sid, item = sorted(candidates, key=lambda x: (-x[0], x[1]))[0]
            check = item['temporalCheck']
            ci, inc = check['context']['deltaRetCI95'], check['increment']['ci95']
            passed = bool(ci and inc and ci[0] > 0 and inc[0] > 0)
            selection = {'signalId': sid, 'context': CONTEXT,
                         'status': 'forward_only' if passed else 'temporal_check_failed',
                         'reason': ('僅列為前瞻觀察候選，探索篩選與歷史分段不構成有效性證明。' if passed else
                                    '訓練段候選未通過時間分段檢查；不改挑其他訊號，也不啟用前瞻候選。')}
        return {'version': VERSION, 'policy': self.policy, 'policyDigest': digest(self.policy),
                'benchmarkDigest': self.benchmark_digest, 'coverage': self.coverage,
                'benchmarkCoverage': {'bars': len(self.market),
                                      'from': min(self.market, default=None), 'to': max(self.market, default=None),
                                      'knownRegimeDays': sum(v != 'unknown' for v in self.market.values())},
                'skipped': dict(self.skipped), 'signals': signals, 'selection': selection,
                'rsiRebound': self.rsi_rebound(),
                'limitations': [
                    '使用目前本機歷史快照重建，並非當年實際留存的點時紀錄。',
                    '價格未還原除權息，未納入費用、成交限制與下市股票的完整歷史。',
                    '95% 區間採季度等權重抽；季度邊界仍可能相依，並未校正多重比較。',
                    '同情境對照衡量相對平常的關聯，不代表因果；時間分段並非未曾接觸的盲測。',
                    '逆向幅度統一由持有現股的下跌風險解讀；偏空及風險訊號不納入做多候選排名。',
                ]}

    def rsi_rebound(self):
        """固定 RSI 假說，重用相同事件與成熟對照，不重算或搜尋指標。"""
        policy = dict(RSI_POLICY)
        horizons = []
        for hz, source in self.rows['mom_rsi_rebound'].items():
            rows = [{**r, 'context': context_matches(r['marketRegime'], r['stockRegime'], policy['context'])}
                    for r in source]
            parts = {'training': [r for r in rows if r['endDate'] < policy['cutoff']],
                     'temporalCheck': [r for r in rows if r['date'] >= policy['cutoff']]}
            item = {'horizon': hz, 'all': summarize(rows, policy)}
            for key, part in parts.items():
                item[key] = {'unfiltered': summarize(part, policy),
                             'context': summarize([r for r in part if r['context']], policy),
                             'increment': context_increment(part, policy)}
            horizons.append(item)
        chosen = next(h for h in horizons if h['horizon'] == policy['selectionHorizon'])
        def passed(part):
            a, b = part['context']['deltaRetCI95'], part['increment']['ci95']
            return bool(a and b and a[0] > 0 and b[0] > 0)
        train_ok = passed(chosen['training'])
        check_ok = train_ok and passed(chosen['temporalCheck'])
        status = 'forward_only' if check_ok else ('temporal_check_failed' if train_ok else 'no_candidate')
        return {'version': policy['version'], 'policy': policy, 'policyDigest': digest(policy),
                'benchmarkDigest': self.benchmark_digest,
                'selection': {'signalId': policy['signalId'], 'context': policy['context'], 'status': status,
                              'reason': ('固定假說通過歷史探索門檻，僅可累積註冊後前瞻觀察。' if check_ok else
                                         '固定 RSI 假說未通過完整門檻；維持研究，不降低門檻。')},
                'signals': [{'signalId': policy['signalId'], 'label': 'RSI 超賣回升', 'horizons': horizons}],
                'limitations': ['假說在看過第一輪結果後提出；歷史分段不構成獨立盲測。',
                                '情境為大盤非下降、個股仍在下降趨勢；未知大盤排除。',
                                '次日收盤起算、價格未還原、未計費用；季度區間未校正多重比較。']}
