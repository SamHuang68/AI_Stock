"""突破研究的純資料計算；不抓行情、不寫資料，也不產生交易分數。"""
from __future__ import annotations

import hashlib
import json
import math
from bisect import bisect_right
from decimal import Decimal
from statistics import mean, median

try:
    from .公司行動比較 import Comparison, PRICE_BASIS, json_safe
except ImportError:
    from 公司行動比較 import Comparison, PRICE_BASIS, json_safe

VERSION = 'breakout-observation-v1'
ADJUSTED_VERSION = 'breakout-observation-adjusted-v1'
WARMUP_DAYS = 253
HORIZONS = (1, 3, 5, 10)
RULES = (
    {'key': 'breakout_120_mid', 'label': '中段轉強觀察', 'kind': '研究觀察',
     'formula': '收盤 > 前 120 個交易日最高價，且收盤 ≤ 前 252 個交易日最高價；僅記錄條件由不成立轉為成立。',
     'lookbackDays': 252, 'warmupDays': WARMUP_DAYS},
    {'key': 'breakout_252', 'label': '一年高點突破觀察', 'kind': '研究觀察',
     'formula': '收盤 > 前 252 個交易日最高價；僅記錄條件由不成立轉為成立。',
     'lookbackDays': 252, 'warmupDays': WARMUP_DAYS},
    {'key': 'repair_risk', 'label': '跌深修復風險觀察（工程版）', 'kind': '工程版風險觀察',
     'formula': '收盤 > 前 20 日最高價，前 100 日內最高價高點至後續收盤的最大回撤 ≥ 20%，且收盤距前 252 日最高價 ≤ −15%；僅記錄首次成立。這不是文章的 15 日箱型規則。',
     'lookbackDays': 252, 'warmupDays': WARMUP_DAYS},
)
NOTES = (
    '突破觀察不增加買進分數、不推播、不下單；研究標籤與風險提示不代表進場優勢。',
    '最高價與回撤窗口均排除當日；突破採嚴格大於，等於前高不算突破。前一交易日不可判定時不補成未成立，也不產生首次訊號。',
    '120 日中段轉強需要 252 日高點作上界；三項研究各自檢查資料品質，最多使用開始日前 253 個交易日暖機，暖機日不計入樣本。',
    '跌深修復是明確標示的工程版：先發生的最高價高點至後續日期收盤，計算前 100 日內最大回撤；不等同原文章尚未完整定義的箱型。',
    '報酬為觀察日收盤至後續第 1、3、5、10 個市場交易日收盤，未計股息與稅費，並非文章的隔日開盤、VIDYA 或停損策略回測。',
    '每項基準只使用該規則能判定當日與前日狀態的日期；非重疊樣本及小樣本門檻沿用事件研究，不代表統計顯著性或未來優勢。',
    '截至日僅使用已完成交易日；假日沿用最近資料日。歷史統計使用目前已核對資料，並非當時發布版本；影子紀錄另存實際觀測時間。',
)


def _number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0


def _distribution(values: list[float]) -> dict:
    ordered = sorted(values)

    def quantile(p: float) -> float:
        at = (len(ordered) - 1) * p
        low = int(at)
        return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (at - low)

    return {'n': len(values), 'mean': mean(values) if values else None, 'median': median(values) if values else None,
            'positivePct': sum(v > 0 for v in values) / len(values) * 100 if values else None,
            'q25': quantile(.25) if values else None, 'q75': quantile(.75) if values else None,
            'smallSample': len(values) < 30}


def build_research(rows: list[dict], *, calendar_years: set[int], action_days: set[str],
                   action_coverage: tuple | list | dict | None, sample_start: int = 0,
                   adjustments: dict | None = None) -> dict:
    """計算已正規化的交易日時間軸，輸入及輸出均不產生副作用。

    rows 由既有日線讀取端提供，須按日期遞增且保留缺交易日的空列，
    各列含 date/open/high/low/close/volume/source/issues。issues 已包含
    官方來源、日曆及成交量單位核對。action_coverage 接受資料庫三欄 tuple
    或 {start,end,source}；sample_start 之前的列只供暖機。
    回傳 rows 與輸入逐列對應，供呼叫端放入 candle.research；latest 不退回
    更舊的可用日期，因此缺資料時會明確呈現最近交易日不可判定。
    """
    if not 0 <= sample_start <= len(rows):
        raise ValueError('研究暖機起點超出資料範圍')
    dates = [r['date'] for r in rows]
    if any(a >= b for a, b in zip(dates, dates[1:])):
        raise ValueError('研究時間軸須按交易日遞增且不得重複')
    if isinstance(action_coverage, dict):
        coverage = (action_coverage.get('start'), action_coverage.get('end'), action_coverage.get('source'))
    else:
        coverage = tuple(action_coverage) if action_coverage else None
    actions = set(action_days)
    for previous, current in zip(rows, rows[1:]):
        if _number(previous.get('close')) and _number(current.get('close')) and abs(current['close'] / previous['close'] - 1) > .15:
            actions.add(current['date'])
    comparison = Comparison(rows, adjustments, actions) if adjustments is not None else None
    if comparison:
        actions.update(comparison.action_days)
    version = ADJUSTED_VERSION if comparison else VERSION
    ordered_actions = sorted(actions)
    row_reasons = []
    for row in rows:
        issues = list(row.get('issues', ['資料品質尚未核對']))
        if row.get('source') not in ('TWSE', 'TPEX'):
            issues.append('歷史來源尚未經官方核對')
        if comparison and row.get('priceBasis', row.get('price_basis')) != 'unadjusted':
            issues.append('原始價格基準尚未核對')
        if not all(_number(row.get(k)) for k in ('open', 'high', 'low', 'close', 'volume')):
            issues.append('價格或成交量缺值／無成交')
        elif not row['low'] <= min(row['open'], row['close']) <= max(row['open'], row['close']) <= row['high']:
            issues.append('開高低收邊界無效')
        row_reasons.append('；'.join(sorted(set(issues))))
    issue_prefix = [0]
    for reason in row_reasons:
        issue_prefix.append(issue_prefix[-1] + bool(reason))

    def segment_reason(first: int, last: int, *, compare: bool = False) -> str | None:
        if issue_prefix[last + 1] != issue_prefix[first]:
            return '比較區間含缺值、無成交或未核對資料'
        start, end = dates[first], dates[last]
        if any(year not in calendar_years for year in range(int(start[:4]), int(end[:4]) + 1)):
            return '比較區間的交易日曆尚未完整核對'
        if not coverage or not coverage[0] or not coverage[1] or not coverage[0] <= start <= end <= coverage[1]:
            return '公司行動涵蓋區間尚未核對'
        if comparison and compare:
            return comparison.reason(first, last)
        if bisect_right(ordered_actions, end) > bisect_right(ordered_actions, start):
            return '比較區間跨公司行動或重大價格斷點'
        return None

    condition_reasons: list[dict] = []
    observations = []
    for i, row in enumerate(rows):
        metrics = {key: None for key in ('priorHigh20', 'priorHigh120', 'priorHigh252', 'maxDrawdown100Pct', 'distance252HighPct')}
        conditions: dict[str, bool | None] = {}
        reasons, eligible, current_reasons, hits = {}, {}, {}, []
        # 研究所需的比較區間獨立於既有 20 日 K 線事件，不改動該事件資格。
        quality_by_window = {}
        for rule in RULES:
            key, lookback = rule['key'], rule['lookbackDays']
            if lookback not in quality_by_window:
                quality_by_window[lookback] = (row_reasons[i] or f'前 {lookback} 個交易日暖機資料不足') if i < lookback else (row_reasons[i] or segment_reason(i - lookback, i, compare=True))
            reason = quality_by_window[lookback]
            current_reasons[key] = reason
            conditions[key] = None
        if any(reason is None for reason in current_reasons.values()):
            prior_prices = comparison.prices(i - 252, i) if comparison else rows[i - 252:i]
            for window in (20, 120, 252):
                metrics[f'priorHigh{window}'] = max(r['high'] for r in prior_prices[-window:])
                if comparison:
                    metrics[f'rawPriorHigh{window}'] = max(r['high'] for r in rows[i - window:i])
            close = Decimal(str(row['close']))
            high252 = Decimal(str(metrics['priorHigh252']))
            distance = (close / high252 - 1) * 100
            peak, drawdown = None, Decimal(0)
            for prior in prior_prices[-100:]:
                # 使用較早日期的高點；不假設同日 high 與 close 的先後路徑。
                if peak is not None:
                    drawdown = max(drawdown, (1 - Decimal(str(prior['close'])) / peak) * 100)
                high = Decimal(str(prior['high']))
                peak = max(peak, high) if peak is not None else high
            metrics['distance252HighPct'] = float(distance)
            metrics['maxDrawdown100Pct'] = float(drawdown)
            candidates = {
                'breakout_120_mid': close > Decimal(str(metrics['priorHigh120'])) and close <= high252,
                'breakout_252': close > high252,
                'repair_risk': close > Decimal(str(metrics['priorHigh20'])) and drawdown >= Decimal(20) and distance <= Decimal(-15),
            }
            for key in conditions:
                if current_reasons[key] is None:
                    conditions[key] = candidates[key]
        for rule in RULES:
            key = rule['key']
            previous_condition = observations[i - 1]['conditions'][key] if i else None
            eligible[key] = current_reasons[key] is None and previous_condition is not None
            if current_reasons[key]:
                reasons[key] = current_reasons[key]
            elif previous_condition is None:
                prior_reason = condition_reasons[i - 1][key] if i else '沒有前一交易日'
                reasons[key] = f'前一交易日不可判定，無法確認首次成立：{prior_reason}'
            elif conditions[key] and not previous_condition:
                hits.append(key)
                reasons[key] = '條件首次成立，僅供研究觀察'
            elif conditions[key]:
                reasons[key] = '條件持續成立，本日不重複記錄訊號'
            else:
                reasons[key] = '條件未成立'
        observations.append({'eligible': eligible, 'reason': reasons, 'conditions': conditions, 'signals': hits, 'metrics': metrics})
        if comparison:
            for name, value in metrics.items():
                if isinstance(value, Decimal):
                    metrics[name] = float(value)
            observations[-1].update(priceBasis=PRICE_BASIS, anchorDate=row['date'],
                                    comparisonEvidence=comparison.evidence(max(0, i - 252), i))
        condition_reasons.append(current_reasons)

    def outcome(i: int, horizon: int) -> float | None:
        if i + horizon >= len(rows) or segment_reason(i, i + horizon):
            return None
        return (rows[i + horizon]['close'] / rows[i]['close'] - 1) * 100

    returns = {(i, h): outcome(i, h) for i in range(sample_start, len(rows)) for h in HORIZONS
               if any(observations[i]['eligible'].values())}
    stats = []
    for rule in RULES:
        key = rule['key']
        samples = [(i, observation) for i, observation in enumerate(observations) if i >= sample_start and observation['eligible'][key]]
        group = {'key': key, 'label': rule['label'], 'cases': sum(key in observation['signals'] for _, observation in samples),
                 'eligibleDays': len(samples), 'horizons': {}}
        for horizon in HORIZONS:
            candidates = [(i, returns[(i, horizon)]) for i, observation in samples if key in observation['signals'] and returns[(i, horizon)] is not None]
            baseline = [returns[(i, horizon)] for i, _ in samples if returns[(i, horizon)] is not None]
            independent, last = [], -1
            for i, value in candidates:
                if i > last:
                    independent.append(value)
                    last = i + horizon
            raw_stats, base_stats = _distribution([value for _, value in candidates]), _distribution(baseline)
            group['horizons'][str(horizon)] = {'raw': raw_stats, 'nonOverlapping': _distribution(independent), 'baseline': base_stats,
                                              'difference': raw_stats['mean'] - base_stats['mean'] if candidates and baseline else None}
        stats.append(group)
    latest = None
    if len(rows) > sample_start:
        # 保存完整比較及前日判斷證據的摘要，讓寫入端識別官方資料修訂。
        def digest_value(value: object) -> object:
            # 缺值列也要留下證據；非法浮點數不可讓整份唯讀報告失敗。
            return repr(value) if isinstance(value, float) and not math.isfinite(value) else value

        evidence_start, evidence_end = dates[max(0, len(rows) - WARMUP_DAYS - 1)], dates[-1]
        # 比較窗外的例行涵蓋延長或新曆年不得冒充此筆觀察的資料修訂。
        relevant_coverage = None
        if coverage and coverage[0] and coverage[1]:
            first, last = max(coverage[0], evidence_start), min(coverage[1], evidence_end)
            if first <= last:
                relevant_coverage = (first, last, coverage[2] if len(coverage) > 2 else None)
        relevant_years = [year for year in range(int(evidence_start[:4]), int(evidence_end[:4]) + 1) if year in calendar_years]
        evidence = {'version': version, 'rows': [{key: digest_value(row.get(key)) for key in ('date', 'open', 'high', 'low', 'close', 'volume', 'source', 'issues')}
                    for row in rows[-WARMUP_DAYS - 1:]],
                    'calendarYears': relevant_years, 'actionDays': sorted(d for d in actions if evidence_start < d <= evidence_end),
                    'actionCoverage': relevant_coverage}
        if comparison:
            evidence['comparison'] = comparison.digest_evidence(max(0, len(rows) - WARMUP_DAYS - 1), len(rows) - 1)
            evidence['priceBases'] = [row.get('priceBasis', row.get('price_basis')) for row in rows[-WARMUP_DAYS - 1:]]
        digest = hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()
        latest = {**observations[-1], 'date': rows[-1]['date'], 'close': rows[-1].get('close'), 'source': rows[-1].get('source'), 'inputDigest': digest}
    result = {'version': version, 'rules': [dict(rule) for rule in RULES], 'latest': latest, 'stats': stats,
              'notes': list(NOTES), 'warmupDays': sample_start, 'rows': observations}
    if comparison:
        extra_notes = ['比較價格採官方完整參考價與前收盤價比值，不是官方還原日線、股數比率或總報酬。',
                       '每個觀察日使用自己的價格基準；僅調整比較 OHLC，不調整成交量或原始成交價。',
                       '歷史條件依目前核對資料回算，擷取時間不代表當年的發布時間；原始價格報酬跨公司行動仍排除。']
        result['notes'].extend(extra_notes)
        # 頂層稽核供整段研究及匯出使用；最新觀察摘要仍只使用自身比較窗口。
        evidence = comparison.evidence(0, len(rows) - 1) if rows else {'events': []}
        result.update(priceBasis=PRICE_BASIS, coverage=json_safe(comparison.coverage),
                      adjustmentEvidence={'coverage': json_safe(comparison.coverage), 'events': evidence['events'], 'notes': extra_notes})
    return result
