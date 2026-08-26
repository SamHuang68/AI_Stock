#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stock Terminal deterministic market-decision context.

The engine consumes the already-canonical Pulse payload.  It never performs
network I/O and never asks an LLM to create a regime, level, confidence score
or exposure range.  Pure ``build_decision_context`` calls are replayable;
``publish_context`` owns bounded history and diagnostic trace side effects.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import threading
import time
from collections import deque
from contextlib import closing
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import exposure_lab as _exposure_lab
import consensus_attention as _consensus_attention


CONTRACT_VERSION = 2
ENGINE_VERSION = 'st-decision-context/v2'
REGIME_LABELS = {
    'BROAD_RISK_ON': '廣泛風險偏好',
    'NARROW_RALLY': '指數偏強、結構狹窄',
    'RECOVERY_ATTEMPT': '結構修復嘗試',
    'CONFLICT': '訊號衝突、等待確認',
    'DEFENSIVE_RISK_OFF': '防禦性風險迴避',
    'CAPITULATION': '極端賣壓、等待修復',
    'INSUFFICIENT_DATA': '核心資料不足',
}
REQUIRED_RISK_PROFILE = (
    'baseGrossExposure', 'maxGrossExposure', 'maxLeverage', 'maxSingleNameWeight',
    'maxSectorWeight', 'maxPortfolioBeta', 'maxDailyVaR', 'investmentHorizon',
)

if getattr(__import__('sys'), 'frozen', False):
    _BASE = os.path.dirname(__import__('sys').executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_BASE, 'data', 'decision_history.db')
TRACE_PATH = os.path.join(_BASE, 'logs', 'decision_trace.jsonl')
TW_TZ = timezone(timedelta(hours=8))

_lock = threading.RLock()
_latest_context: dict[str, Any] | None = None
_latest_inputs: dict[str, Any] | None = None
_recent = deque(maxlen=120)
_status = {'lastSuccess': None, 'lastError': None, 'lastElapsedMs': None}


def _number(value: Any) -> float | None:
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _clamp(value: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def _iso_now(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).isoformat()


def _aware_datetime(value: Any) -> datetime | None:
    try:
        parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed.replace(tzinfo=TW_TZ) if parsed.tzinfo is None else parsed
    except (TypeError, ValueError):
        return None


def _quote(pulse: dict, symbol: str, legacy: dict | None = None) -> dict:
    q = (((pulse.get('marketSnapshot') or {}).get('quotes') or {}).get(symbol) or {})
    return q if isinstance(q, dict) and q else (legacy or {})


def _quote_change(q: dict | None) -> float | None:
    q = q or {}
    market = q.get('market') or {}
    return _number(market.get('displayChangePct', q.get('displayChangePct', q.get('changePct'))))


def _make_evidence(
    evidence_id: str,
    metric: str,
    value: Any,
    *,
    source: str,
    as_of: str | None,
    reference: str,
    market_scope: str = 'TW',
    session: str = 'regular',
    quality: str = 'mixed',
    comparison: str | None = None,
) -> dict[str, Any]:
    return {
        'id': evidence_id,
        'metric': metric,
        'value': value,
        'comparison': comparison,
        'source': source or 'unknown',
        'marketScope': market_scope,
        'session': session,
        'asOf': as_of,
        'reference': reference,
        'quality': quality,
    }


def _feature(value: float | None, raw: Any, available: bool = True) -> dict[str, Any]:
    return {
        'value': round(_clamp(value), 4) if value is not None else None,
        'raw': raw,
        'available': bool(available and value is not None),
    }


def _history_improvement(rows: Iterable[dict] | None, current: float | None) -> float | None:
    vals = [_number((x or {}).get('advRatio')) for x in (rows or []) if isinstance(x, dict)]
    vals = [x for x in vals if x is not None]
    if current is None or not vals:
        return None
    # history endpoints return newest first and may already include current.
    prior = vals[1:4] if len(vals) >= 2 and abs(vals[0] - current) < 0.0001 else vals[:3]
    return current - (sum(prior) / len(prior)) if prior else None


def _date_key(value: Any) -> str | None:
    text = str(value or '').strip()[:10].replace('/', '-').replace('.', '-')
    compact = ''.join(ch for ch in text if ch.isdigit())
    if len(compact) == 8:
        return compact
    return None


def _linear_slope(values: Iterable[float] | None, window: int) -> float | None:
    vals = [float(x) for x in list(values or [])[:window] if x is not None]
    if len(vals) < min(3, window):
        return None
    vals.reverse()  # chronological: oldest -> newest
    n = len(vals)
    x_mean = (n - 1) / 2.0
    y_mean = sum(vals) / n
    denominator = sum((i - x_mean) ** 2 for i in range(n))
    if denominator <= 0:
        return None
    return sum((i - x_mean) * (value - y_mean) for i, value in enumerate(vals)) / denominator


def _breadth_trend(
    rows: Iterable[dict] | None,
    current: float | None,
    improvement: float | None,
    *,
    index_history: Iterable[dict] | None = None,
    current_index: float | None = None,
    current_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    index_by_date = {}
    for raw in index_history or []:
        if not isinstance(raw, dict):
            continue
        day = _date_key(raw.get('date') or raw.get('asOf') or raw.get('ts'))
        close = _number(raw.get('close'))
        if day and close is not None:
            index_by_date[day] = {
                'close': close,
                'changePct': _number(raw.get('changePct')),
            }
    points = []
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        ratio = _number(raw.get('advRatio'))
        if ratio is None:
            continue
        as_of = raw.get('asOf') or raw.get('date') or raw.get('ts')
        index_row = index_by_date.get(_date_key(as_of)) or {}
        points.append({
            'asOf': as_of,
            'advRatio': round(_clamp(ratio, 0.0, 1.0), 4),
            'up': raw.get('up'),
            'down': raw.get('down'),
            'flat': raw.get('flat') or raw.get('unchanged'),
            'indexClose': index_row.get('close'),
            'indexChangePct': index_row.get('changePct'),
        })
        if len(points) >= 20:
            break
    if current is not None and (not points or abs(points[0]['advRatio'] - current) > 0.0001):
        stats = current_stats or {}
        points.insert(0, {
            'asOf': stats.get('asOf'), 'advRatio': round(_clamp(current, 0.0, 1.0), 4),
            'up': stats.get('up'), 'down': stats.get('down'), 'flat': stats.get('flat'),
            'indexClose': current_index, 'indexChangePct': stats.get('indexChangePct'),
        })
        points = points[:20]
    elif points and current_index is not None and points[0].get('indexClose') is None:
        points[0]['indexClose'] = current_index
    ratios = [x['advRatio'] for x in points]
    below_neutral_streak = 0
    for ratio in ratios:
        if ratio >= 0.5:
            break
        below_neutral_streak += 1
    chronological = list(reversed(points))
    running_high = None
    for point in chronological:
        close = _number(point.get('indexClose'))
        new_high = close is not None and (running_high is None or close >= running_high)
        point['divergent'] = bool(new_high and point.get('advRatio', 1.0) < 0.5)
        if close is not None:
            running_high = close if running_high is None else max(running_high, close)
    stats = current_stats or {}
    up, down, flat = (_number(stats.get('up')), _number(stats.get('down')), _number(stats.get('flat')))
    total = sum(x or 0.0 for x in (up, down, flat))
    breadth_bar = {
        'upPct': round((up or 0.0) / total * 100.0, 1) if total else None,
        'flatPct': round((flat or 0.0) / total * 100.0, 1) if total else None,
        'downPct': round((down or 0.0) / total * 100.0, 1) if total else None,
        'up': int(up) if up is not None else None,
        'flat': int(flat) if flat is not None else None,
        'down': int(down) if down is not None else None,
    }
    return {
        'rows': points,
        'current': round(current, 4) if current is not None else None,
        'changeVs3': round(improvement, 4) if improvement is not None else None,
        'velocity3': round(_linear_slope(ratios, 3), 4) if _linear_slope(ratios, 3) is not None else None,
        'velocity5': round(_linear_slope(ratios, 5), 4) if _linear_slope(ratios, 5) is not None else None,
        'belowNeutralStreak': below_neutral_streak,
        'breadthBar': breadth_bar,
        'reference': 'TWSE_STOCKS advRatio + ^TWII same-date close; newest first',
    }


def _zscore_latest(values: Iterable[float] | None, window: int) -> tuple[float | None, int]:
    vals = [float(x) for x in list(values or []) if x is not None]
    sample = vals[-window:]
    if len(sample) < window:
        return None, len(sample)
    mean = sum(sample) / len(sample)
    variance = sum((x - mean) ** 2 for x in sample) / len(sample)
    if variance <= 1e-12:
        return 0.0, len(sample)
    return (sample[-1] - mean) / math.sqrt(variance), len(sample)


def _basis_context(
    *,
    spot_price: float | None,
    futures_price: float | None,
    spot_change: float | None,
    futures_change: float | None,
    spot_session: str,
    futures_session: str,
    index_history: Iterable[dict] | None,
    futures_history: Iterable[dict] | None,
    oi_change_pct: float | None,
    fair_basis_estimate_pts: float | None = None,
    expected_dividend_pts: float | None = None,
) -> dict[str, Any]:
    spot_by_date, futures_by_date = {}, {}
    for raw in index_history or []:
        if not isinstance(raw, dict):
            continue
        day, close = _date_key(raw.get('date') or raw.get('asOf') or raw.get('ts')), _number(raw.get('close'))
        if day and close is not None:
            spot_by_date[day] = close
    for raw in futures_history or []:
        if not isinstance(raw, dict):
            continue
        day, close = _date_key(raw.get('date') or raw.get('asOf') or raw.get('ts')), _number(raw.get('close'))
        if day and close is not None:
            futures_by_date[day] = close
    aligned = []
    for day in sorted(set(spot_by_date) & set(futures_by_date)):
        spot = spot_by_date[day]
        points = futures_by_date[day] - spot
        aligned.append({'date': day, 'basisPts': round(points, 2), 'basisPct': round(points / spot * 100.0, 4)})
    basis_values = [x['basisPct'] for x in aligned]
    z20, n20 = _zscore_latest(basis_values, 20)
    z60, n60 = _zscore_latest(basis_values, 60)
    live_points = (futures_price - spot_price) if spot_price is not None and futures_price is not None else None
    live_pct = (live_points / spot_price * 100.0) if live_points is not None and spot_price not in (None, 0) else None
    comparable = str(spot_session or '').lower() in ('regular', 'day') and str(futures_session or '').lower() in ('regular', 'day')
    fair_available = fair_basis_estimate_pts is not None
    adjusted_points = live_points - fair_basis_estimate_pts if live_points is not None and fair_available else None
    lag = spot_change - futures_change if spot_change is not None and futures_change is not None else None
    short_covering = bool(
        spot_change is not None and spot_change > 0 and lag is not None and lag >= 0.02 and
        oi_change_pct is not None and oi_change_pct <= -1.5)
    converging = None
    if len(aligned) >= 2:
        converging = abs(aligned[-1]['basisPct']) < abs(aligned[-2]['basisPct'])
    if not comparable:
        session_tag = '夜盤相對現貨收盤' if str(futures_session or '').lower() == 'night' else '跨盤參考'
    elif lag is not None and lag > 0.10:
        session_tag = '期貨漲幅落後'
    elif lag is not None and lag < -0.10:
        session_tag = '期貨領先'
    else:
        session_tag = '期現同步'
    if converging is True:
        session_tag += ' · 日盤價差收斂'
    return {
        'liveGapPts': round(live_points, 2) if live_points is not None else None,
        'liveGapPct': round(live_pct, 4) if live_pct is not None else None,
        'adjustedBasisPts': round(adjusted_points, 2) if adjusted_points is not None else None,
        'fairBasisEstimatePts': fair_basis_estimate_pts,
        'expectedDividendPts': expected_dividend_pts,
        'adjustmentAvailable': fair_available,
        'mode': ('fair_value_adjusted' if fair_available and comparable else
                 ('cross_session_nominal_gap' if not comparable else 'same_session_nominal_basis')),
        'sessionComparable': comparable,
        'basisZ20': round(z20, 3) if z20 is not None else None,
        'basisZ60': round(z60, 3) if z60 is not None else None,
        'sample20': n20, 'sample60': n60,
        'history': aligned[-60:],
        'futuresLagPctPoint': round(lag, 4) if lag is not None else None,
        'oiChangePct': round(oi_change_pct, 4) if oi_change_pct is not None else None,
        'shortCoveringRisk': short_covering,
        'dayBasisConverging': converging,
        'sessionTag': session_tag,
        'reference': '同日 ^TWII 日盤收盤 vs TXF 日盤近月收盤；夜盤僅作跨盤參考',
    }


def _global_tech_change(pulse: dict) -> float | None:
    vals = []
    for row in pulse.get('global') or []:
        sym = str((row or {}).get('symbol') or '').upper()
        if sym in ('^SOX', '^IXIC'):
            val = _number((row or {}).get('changePct'))
            if val is not None:
                vals.append(val)
    return sum(vals) / len(vals) if vals else None


def _tw_tech_change(pulse: dict) -> float | None:
    vals = []
    for row in pulse.get('sectors') or []:
        name = str((row or {}).get('name') or (row or {}).get('sector') or '')
        if any(k in name for k in ('半導', '電子', '電腦')):
            val = _number((row or {}).get('changePct'))
            if val is not None:
                vals.append(val)
    return sum(vals) / len(vals) if vals else None


def _detect_divergences(
    *,
    index_change: float | None,
    index_streak: float | None,
    adv_ratio: float | None,
    adv_improvement: float | None,
    advancers: float | None,
    decliners: float | None,
    turnover_vs5: float | None,
    txf_change: float | None,
    basis_pct: float | None,
    breadth_trend: dict[str, Any] | None,
    basis_context: dict[str, Any] | None,
    oi_change_pct: float | None,
    inst_yi: float | None,
    tw_tech: float | None,
    global_tech: float | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def add(div_id: str, severity: str, confidence: float, observed: dict, evidence: list[str], confirmation: str, invalidation: str,
            *, insight: str | None = None, visual: dict[str, Any] | None = None):
        row = {
            'id': div_id, 'severity': severity, 'confidence': round(confidence, 2),
            'observed': observed, 'evidenceIds': evidence,
            'confirmation': confirmation, 'invalidation': invalidation,
        }
        if insight:
            row['insight'] = insight
        if visual:
            row['visual'] = visual
        out.append(row)

    if index_change is not None and adv_ratio is not None:
        # 除了明顯的「指數漲、廣度弱」，也捕捉指數連漲但當日下跌家數較多的微幅背離。
        # 後者不能只靠 0.45 的硬切點，否則畫面四捨五入為 45.0% 時會漏報。
        hard_narrow = index_change >= 0.25 and adv_ratio < 0.45
        sustained_narrow = (
            index_change > 0 and (index_streak or 0) >= 3 and adv_ratio < 0.50 and
            advancers is not None and decliners is not None and decliners > advancers
        )
        if hard_narrow or sustained_narrow:
            breadth_gap = max(0.0, 0.50 - adv_ratio)
            divergence_raw = max(0.0, index_change * breadth_gap * 100.0)
            # Raw DI preserves the requested formula.  The bounded score is monotonic only;
            # it is a visual/risk-normalization aid, not a calibrated probability.
            divergence_score = 100.0 * (1.0 - math.exp(-divergence_raw / 10.0))
            trend = breadth_trend or {}
            velocity3 = _number(trend.get('velocity3'))
            velocity5 = _number(trend.get('velocity5'))
            breadth_streak = int(_number(trend.get('belowNeutralStreak')) or 0)
            persistence_boost = min(0.12, breadth_streak * 0.025)
            velocity_boost = min(0.08, max(0.0, -(velocity5 or velocity3 or 0.0)) * 1.5)
            confidence = min(0.95, 0.58 + divergence_score / 100.0 * 0.18 + persistence_boost + velocity_boost)
            severity = ('critical' if divergence_score >= 70 or adv_ratio < 0.30 else
                        ('warning' if divergence_score >= 30 or hard_narrow or adv_ratio < 0.43 else 'watch'))
            ls_ratio = (advancers / decliners) if advancers is not None and decliners not in (None, 0) else None
            add('INDEX_UP_BREADTH_DOWN', severity,
                confidence,
                {'indexChangePct': index_change, 'indexStreak': int(index_streak or 0),
                 'advRatio': adv_ratio, 'advImprovement': adv_improvement,
                 'advancers': int(advancers) if advancers is not None else None,
                 'decliners': int(decliners) if decliners is not None else None,
                 'longShortRatio': round(ls_ratio, 3) if ls_ratio is not None else None,
                 'breadthGapPct': round(breadth_gap * 100.0, 2),
                 'divergenceIntensityRaw': round(divergence_raw, 3),
                 'divergenceIntensityScore': round(divergence_score, 1),
                 'breadthVelocity3': round(velocity3, 4) if velocity3 is not None else None,
                 'breadthVelocity5': round(velocity5, 4) if velocity5 is not None else None,
                 'belowNeutralStreak': breadth_streak,
                 'formula': 'indexChangePct × (0.50 − advRatio) × 100'},
                ['twii.live', 'breadth.stock_scope', 'breadth.velocity'],
                'advRatio 連續兩次觀察 ≥ 0.50 且 5 日斜率不再惡化',
                '指數收破 Pivot 且廣度仍弱',
                insight=('指數由少數權值支撐，廣度未同步；非主流個股追價與新增槓桿風險升高。'),
                visual={
                    'type': 'index_breadth_overlay',
                    'series': list(reversed((trend.get('rows') or [])[:10])),
                    'breadthBar': trend.get('breadthBar') or {},
                    'topWeightContribution': {
                        'available': False,
                        'reason': '尚無同日成分股權重×報酬契約；DI 僅為集中度代理，不冒充前五大貢獻率',
                    },
                })
        elif index_change <= -0.25 and adv_ratio > 0.55:
            add('INDEX_DOWN_BREADTH_UP', 'watch', 0.72,
                {'indexChangePct': index_change, 'advRatio': adv_ratio, 'advImprovement': adv_improvement},
                ['twii.live', 'breadth.stock_scope'], '指數站回 Pivot 且 advRatio ≥ 0.55',
                'advRatio 跌破 0.45')
    if index_change is not None and turnover_vs5 is not None and index_change >= 0.25 and turnover_vs5 <= -5.0:
        add('PRICE_UP_VOLUME_DOWN', 'warning', 0.76,
            {'indexChangePct': index_change, 'turnoverVsMa5Pct': turnover_vs5},
            ['twii.live', 'turnover.score'], '成交額回到 5 日均值以上',
            '量能確認前價格跌破 Pivot')
    if index_change is not None and txf_change is not None:
        basis = basis_context or {}
        sign_conflict = index_change * txf_change < 0 and abs(index_change) >= 0.15 and abs(txf_change) >= 0.15
        basis_z20 = _number(basis.get('basisZ20'))
        adjusted = basis.get('mode') == 'fair_value_adjusted' and bool(basis.get('sessionComparable'))
        basis_extreme = adjusted and basis_z20 is not None and abs(basis_z20) >= 2.0
        short_covering = bool(basis.get('shortCoveringRisk'))
        if sign_conflict or basis_extreme or short_covering:
            confidence = 0.64 + (0.14 if sign_conflict else 0.0) + (0.12 if basis_extreme else 0.0) + (0.10 if short_covering else 0.0)
            evidence_ids = ['twii.live', 'txf.live'] + (['flow.tx_oi'] if oi_change_pct is not None else [])
            add('SPOT_FUTURES_CONFLICT', 'warning', min(0.94, confidence),
                {'spotChangePct': index_change, 'txfChangePct': txf_change,
                 'basisPct': basis_pct, 'basisPts': basis.get('liveGapPts'),
                 'basisMode': basis.get('mode'), 'basisZ20': basis_z20,
                 'basisZ60': basis.get('basisZ60'),
                 'futuresLagPctPoint': basis.get('futuresLagPctPoint'),
                 'txOiChangePct': oi_change_pct,
                 'shortCoveringRisk': short_covering,
                 'sessionComparable': basis.get('sessionComparable')},
                evidence_ids, '期現方向重新一致、OI結構回穩，或調整後基差回到 ±1Z 內',
                '調整後基差突破 ±2Z，或期貨落後伴隨 OI 繼續下降',
                insight=('期貨跟漲意願偏弱且 OI 減少；較符合短空回補／避險退場，不能視為多頭主動加碼證明。'
                         if short_covering else
                         '期現方向或調整後基差出現異常；等待同盤價格與部位結構確認。'),
                visual={'type': 'basis_gauge', 'basis': basis})
    if index_change is not None and inst_yi is not None and abs(index_change) >= 0.25:
        if (index_change > 0 and inst_yi < -30) or (index_change < 0 and inst_yi > 30):
            add('FLOW_PRICE_CONFLICT', 'warning', 0.74,
                {'indexChangePct': index_change, 'institutionalNetYi': inst_yi},
                ['twii.live', 'flow.institutional'], '法人資金方向與價格一致',
                '資金確認前價格失去目前方向')
    if tw_tech is not None and global_tech is not None and tw_tech * global_tech < 0 and abs(tw_tech) >= 0.35 and abs(global_tech) >= 0.35:
        add('TW_US_TECH_DIVERGENCE', 'warning', 0.78,
            {'twTechChangePct': round(tw_tech, 3), 'usTechChangePct': round(global_tech, 3)},
            ['sector.participation', 'global.tech'], '台美科技方向重新一致',
            '下一個重疊觀察期的分歧繼續擴大')
    return out


def _portfolio_summary(raw: dict | None, kind: str = 'actual') -> dict | None:
    if not isinstance(raw, dict):
        return None
    if raw.get('error'):
        return {'kind': kind, 'available': False, 'error': str(raw.get('error'))[:180]}
    stocks = raw.get('stocks') or {}
    beta_sum = beta_weight = 0.0
    max_single = 0.0
    for row in stocks.values():
        w = _number((row or {}).get('weight')) or 0.0
        b = _number((row or {}).get('beta'))
        max_single = max(max_single, w)
        if b is not None:
            beta_sum += w * b
            beta_weight += w
    corr_values = [_number(x) for x in (raw.get('corr') or {}).values()]
    corr_values = [x for x in corr_values if x is not None]
    sectors = raw.get('sector') or {}
    top_sector = max(sectors.items(), key=lambda x: x[1]) if sectors else (None, None)
    port = raw.get('portfolio') or {}
    look_through = _exposure_lab.portfolio_lookthrough(stocks)
    return {
        'kind': kind,
        'available': True,
        'portfolioBeta': round(beta_sum / beta_weight, 3) if beta_weight else None,
        'volAnnualPct': _number(port.get('vol')),
        'var95DailyPct': _number(port.get('var95')),
        'averageCorrelation': round(sum(corr_values) / len(corr_values), 3) if corr_values else None,
        'maxSingleNameWeightPct': round(max_single, 2),
        'topSector': top_sector[0],
        'topSectorWeightPct': _number(top_sector[1]),
        'sampleDays': port.get('days'),
        'skipped': list(raw.get('skipped') or []),
        'stocks': stocks,
        'lookThrough': look_through,
    }


def _position_range(
    regime_id: str,
    confidence: float,
    key_levels: dict,
    risk_profile: dict | None,
    portfolio: dict | None,
    exposure: dict | None = None,
) -> tuple[dict | None, list[str]]:
    if not isinstance(risk_profile, dict):
        return None, ['risk_profile_not_configured']
    missing = [k for k in REQUIRED_RISK_PROFILE if risk_profile.get(k) in (None, '')]
    if missing:
        return None, ['risk_profile_missing:' + ','.join(missing)]
    parsed = {k: _number(risk_profile.get(k)) for k in REQUIRED_RISK_PROFILE if k != 'investmentHorizon'}
    if any(v is None for v in parsed.values()):
        return None, ['risk_profile_invalid_numeric']
    base = parsed['baseGrossExposure']
    max_gross = parsed['maxGrossExposure']
    max_leverage = parsed['maxLeverage']
    horizon = risk_profile.get('investmentHorizon')
    valid_limits = (
        0 <= base <= max_gross and max_gross > 0 and max_leverage > 0 and
        0 < parsed['maxSingleNameWeight'] <= 100 and
        0 < parsed['maxSectorWeight'] <= 100 and
        0 < parsed['maxPortfolioBeta'] <= 10 and
        0 < parsed['maxDailyVaR'] <= 100 and
        isinstance(horizon, str) and 1 <= len(horizon.strip()) <= 32
    )
    if not valid_limits:
        return None, ['risk_profile_invalid_exposure']
    if regime_id == 'INSUFFICIENT_DATA':
        return None, ['insufficient_data_no_position_range']

    is_observation_pool = bool(portfolio and portfolio.get('kind') == 'observation_pool')
    if portfolio and portfolio.get('available') is False and not is_observation_pool:
        return None, ['portfolio_overlay_unavailable']
    regime_multiplier = {
        'BROAD_RISK_ON': 1.0, 'NARROW_RALLY': 0.75, 'RECOVERY_ATTEMPT': 0.60,
        'CONFLICT': 0.50, 'DEFENSIVE_RISK_OFF': 0.25, 'CAPITULATION': 0.15,
        'INSUFFICIENT_DATA': 0.0,
    }[regime_id]
    key_levels_stale = bool(((key_levels or {}).get('quality') or {}).get('stale'))
    volatility = (key_levels or {}).get('volatility') or {}
    state_ratio = None if key_levels_stale else _number(volatility.get('stateToForecastRatio'))
    atr_pct = None if key_levels_stale else _number(((key_levels or {}).get('atr') or {}).get('pct'))
    # Exposure Lab v3 governance: short-horizon volatility and ATR are health
    # observations only.  They may require a review or add an action
    # restriction, but cannot silently resize the published position range.
    volatility_multiplier = 1.0
    confidence_multiplier = 0.65 + 0.35 * _clamp(confidence, 0.0, 1.0)
    target = base * regime_multiplier * volatility_multiplier * confidence_multiplier
    cap = min(max_gross, max_leverage * 100.0)
    constraints: list[str] = ['key_levels_stale'] if key_levels_stale else []
    research_ceiling = _number((exposure or {}).get('selectedResearchCeilingPct'))
    if research_ceiling is not None and research_ceiling < cap:
        cap = research_ceiling
        constraints.append('exposure_lab_research_cap')
    if portfolio and not is_observation_pool:
        beta = _number(portfolio.get('portfolioBeta'))
        var95 = _number(portfolio.get('var95DailyPct'))
        max_beta = _number(risk_profile.get('maxPortfolioBeta'))
        max_var = _number(risk_profile.get('maxDailyVaR'))
        if beta is not None and max_beta not in (None, 0) and beta > max_beta:
            cap *= max_beta / beta
            constraints.append('portfolio_beta_cap')
        if var95 is not None and max_var not in (None, 0) and var95 > max_var:
            cap *= max_var / var95
            constraints.append('portfolio_var_cap')
        max_single = _number(portfolio.get('maxSingleNameWeightPct'))
        max_single_cfg = _number(risk_profile.get('maxSingleNameWeight'))
        if max_single is not None and max_single_cfg is not None and max_single > max_single_cfg:
            constraints.append('single_name_over_limit')
        sec = _number(portfolio.get('topSectorWeightPct'))
        sec_cfg = _number(risk_profile.get('maxSectorWeight'))
        if sec is not None and sec_cfg is not None and sec > sec_cfg:
            constraints.append('sector_over_limit')
        look_through = portfolio.get('lookThrough') or {}
        effective_gross = _number(look_through.get('effectiveGrossExposurePct'))
        if effective_gross is not None and effective_gross > max_gross:
            constraints.append('current_effective_gross_over_limit')
        tsmc_exposure = _number(look_through.get('tsmcEconomicExposurePct'))
        if tsmc_exposure is not None and max_single_cfg is not None and tsmc_exposure > max_single_cfg:
            constraints.append('lookthrough_tsmc_over_limit')
    elif is_observation_pool:
        constraints.append('observation_pool_not_risk_overlay')
    else:
        constraints.append('portfolio_not_provided')
    target = min(target, cap)
    return {
        'lowerPct': round(max(0.0, target * 0.90), 1),
        'targetPct': round(max(0.0, target), 1),
        'upperPct': round(max(0.0, min(target * 1.10, cap)), 1),
        'formula': 'min(base × regime × confidence, Risk Profile caps, Exposure Lab monthly research ceiling)',
        'multipliers': {
            'regime': regime_multiplier,
            'stateVolatility': volatility_multiplier,
            'stateVolatilityApplied': False,
            'observedStateToForecastRatio': round(state_ratio, 4) if state_ratio is not None else None,
            'observedAtrPct': round(atr_pct, 4) if atr_pct is not None else None,
            'dataConfidence': round(confidence_multiplier, 4),
        },
        'capPct': round(cap, 1),
        'researchCeilingPct': round(research_ceiling, 1) if research_ceiling is not None else None,
    }, constraints


def _action_envelope(
    regime_id: str,
    divergences: list[dict],
    key_levels: dict,
    confidence: float,
    risk_profile: dict | None,
    portfolio: dict | None,
    exposure: dict | None = None,
) -> dict[str, Any]:
    catalog = {
        'BROAD_RISK_ON': ('ALLOW_MEASURED_RISK', ['HOLD', 'ADD_RISK_WITHIN_LIMITS'], ['CHASE_GAP_UP'], []),
        'NARROW_RALLY': ('LIMIT_NEW_RISK', ['HOLD', 'ROTATE_TO_LOWER_BETA'], ['ADD_LEVERAGE', 'CHASE_GAP_UP'], []),
        'RECOVERY_ATTEMPT': ('PROBE_WITH_CONFIRMATION', ['HOLD', 'SMALL_PROBE'], ['ADD_LEVERAGE'], ['CHASE_GAP_UP']),
        'CONFLICT': ('WAIT_FOR_CONFIRMATION', ['HOLD', 'REVIEW_HEDGE'], ['ADD_DIRECTIONAL_RISK', 'ADD_LEVERAGE'], []),
        'DEFENSIVE_RISK_OFF': ('DEFENSIVE', ['REDUCE_CONCENTRATION', 'REVIEW_HEDGE'], ['ADD_RISK', 'ADD_LEVERAGE'], ['AVERAGE_DOWN_WITHOUT_CONFIRMATION']),
        'CAPITULATION': ('PRESERVE_LIQUIDITY', ['REVIEW_LIQUIDITY', 'WAIT_FOR_REPAIR'], ['ADD_RISK'], ['TREAT_OVERSOLD_AS_BUY_SIGNAL']),
        'INSUFFICIENT_DATA': ('NO_NEW_DIRECTION', ['REVIEW_DATA_QUALITY'], ['ADD_DIRECTIONAL_RISK'], ['PUBLISH_POSITION_PERCENTAGE']),
    }
    posture, allowed, restricted, prohibited = catalog[regime_id]
    key_levels_stale = bool(((key_levels or {}).get('quality') or {}).get('stale'))
    levels = {} if key_levels_stale else ((key_levels or {}).get('levels') or {})
    confirmation = [d.get('confirmation') for d in divergences if d.get('confirmation')]
    invalidation = [d.get('invalidation') for d in divergences if d.get('invalidation')]
    if levels.get('r1') is not None:
        confirmation.append(f"加權指數守穩 R1 {levels['r1']:.2f}")
    if levels.get('s1') is not None:
        invalidation.append(f"加權指數收破 S1 {levels['s1']:.2f}")
    exposure = exposure or {}
    benchmark_rows = exposure.get('benchmarks') or {}
    selected_benchmark = exposure.get('selectedBenchmarkId')
    selected_rows = (
        list(benchmark_rows.values())
        if selected_benchmark == 'MIXED'
        else [benchmark_rows.get(selected_benchmark) or {}]
    )
    benchmark_states = {(row or {}).get('status') for row in selected_rows}
    if benchmark_states & {'NO_2X_EDGE', 'INDETERMINATE', 'RESEARCH_DATA_INCOMPLETE'} and 'ADD_LEVERAGE' not in restricted:
        restricted = [*restricted, 'ADD_LEVERAGE']
    position_range, constraints = _position_range(
        regime_id, confidence, key_levels or {}, risk_profile, portfolio, exposure)
    mandatory_controls = []
    breadth_guard = next((d for d in divergences
                          if d.get('id') == 'INDEX_UP_BREADTH_DOWN' and (_number(d.get('confidence')) or 0) > 0.70), None)
    if breadth_guard:
        restricted = [x for x in restricted if x != 'CHASE_GAP_UP']
        if 'ADD_LEVERAGE' not in restricted:
            restricted = [*restricted, 'ADD_LEVERAGE']
        if 'CHASE_GAP_UP' not in prohibited:
            prohibited = [*prohibited, 'CHASE_GAP_UP']
        mandatory_controls = [
            {'id': 'LIMIT_NEW_LEVERAGE', 'action': 'ADD_LEVERAGE', 'state': 'RED',
             'enforcement': 'RESTRICTED', 'reason': '指數與廣度背離信心高於 70%'},
            {'id': 'NO_GAP_CHASING', 'action': 'CHASE_GAP_UP', 'state': 'RED',
             'enforcement': 'PROHIBITED', 'reason': '權值集中盤禁止把指數強勢外推至非主流個股'},
        ]
        constraints = [*constraints, 'breadth_divergence_risk_lock']
    weekly_health = (exposure or {}).get('weeklyHealth') or {}
    weekly_flags = set(weekly_health.get('flags') or [])
    if weekly_flags & {'short_vol_elevated', 'margin_elevated_and_rising', 'core_anchor_move'}:
        if 'ADD_LEVERAGE' not in restricted:
            restricted = [*restricted, 'ADD_LEVERAGE']
        constraints = [*constraints, 'exposure_weekly_health_monitor']
        if weekly_health.get('reviewRequired'):
            mandatory_controls = [*mandatory_controls, {
                'id': 'REVIEW_CORE_ASSUMPTIONS', 'action': 'REVIEW_CORE_ASSUMPTIONS',
                'state': 'AMBER', 'enforcement': 'REQUIRED_REVIEW',
                'reason': '週度健康層只要求複查；不得直接改寫月度核心曝險',
            }]
    return {
        'posture': posture,
        'allowed': list(allowed),
        'restricted': list(restricted),
        'prohibited': list(prohibited),
        'rationale': [d['id'].lower() for d in divergences],
        'confirmation': list(dict.fromkeys(confirmation))[:6],
        'invalidation': list(dict.fromkeys(invalidation))[:6],
        'positionRange': position_range,
        'constraints': list(dict.fromkeys(constraints)),
        'mandatoryControls': mandatory_controls,
    }


def empty_context(reason: str = 'pulse_not_ready', now: datetime | None = None) -> dict[str, Any]:
    as_of = _iso_now(now)
    return {
        'ok': True, 'contractVersion': CONTRACT_VERSION, 'market': 'TW', 'asOf': as_of,
        'regime': {'id': 'INSUFFICIENT_DATA', 'label': REGIME_LABELS['INSUFFICIENT_DATA'],
                   'score': 0.0, 'confidence': 0.0, 'ruleId': 'regime.insufficient_data.v1'},
        'actionEnvelope': _action_envelope('INSUFFICIENT_DATA', [], {}, 0.0, None, None, None),
        'keyLevels': {}, 'volatility': {}, 'divergences': [], 'breadthTrend': {'rows': []},
        'basisContext': {}, 'sectorFlow': {},
        'portfolioOverlay': None, 'exposureLab': {},
        'consensusAttention': _consensus_attention.empty(reason),
        'optionsStructure': {'status': 'insufficient', 'shadowMode': True, 'decisionUse': 'research_only'},
        'newsImpact': [], 'scenario': {},
        'confirmation': [], 'invalidation': [], 'evidence': [],
        'dataQuality': {'completeness': 0.0, 'freshness': 0.0, 'scopeConsistency': True,
                        'conflicts': [], 'staleFields': [], 'missingCore': [reason]},
        'model': ENGINE_VERSION,
    }


def build_decision_context(
    pulse: dict[str, Any] | None,
    *,
    key_levels: dict[str, Any] | None = None,
    breadth_history: Iterable[dict] | None = None,
    index_history: Iterable[dict] | None = None,
    futures_history: Iterable[dict] | None = None,
    sector_flow: dict[str, Any] | None = None,
    portfolio_overlay: dict[str, Any] | None = None,
    portfolio_kind: str = 'actual',
    risk_profile: dict[str, Any] | None = None,
    margin_state: dict[str, Any] | None = None,
    benchmark_data: dict[str, Any] | None = None,
    options_structure: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    pulse = dict(pulse or {})
    if not pulse:
        return empty_context('pulse_missing', now)
    now = _aware_datetime(now or datetime.now(timezone.utc)) or datetime.now(timezone.utc)
    as_of = pulse.get('updatedAt') or _iso_now(now)
    snapshot = pulse.get('snapshot') or {}
    indices = pulse.get('indices') or {}
    twii = _quote(pulse, '^TWII', (indices.get('t00') or snapshot.get('t00') or {}))
    txf = _quote(pulse, '__TXF__', (pulse.get('txf') or snapshot.get('txf') or {}))
    twii_change = _quote_change(twii)
    txf_change = _quote_change(txf)
    stocks = pulse.get('stocks') or snapshot.get('stocks') or {}
    adv_ratio = _number(stocks.get('advRatio'))
    advancers = _number(stocks.get('up'))
    decliners = _number(stocks.get('down'))
    unchanged = _number(stocks.get('unchanged', stocks.get('flat')))
    strip = ((pulse.get('overview') or {}).get('strip') or {})
    ttrend = strip.get('t00Trend') or {}
    mom_score = _number(ttrend.get('momScore'))
    index_streak = _number(ttrend.get('streak'))
    current_trend = _clamp(twii_change / 1.5) if twii_change is not None else None
    trend_norm = current_trend
    if current_trend is not None and mom_score is not None:
        trend_norm = 0.65 * current_trend + 0.35 * _clamp((mom_score - 50.0) / 50.0)
    breadth_norm = _clamp((adv_ratio - 0.5) / 0.25) if adv_ratio is not None else None
    adv_improvement = _history_improvement(breadth_history, adv_ratio)
    breadth_trend = _breadth_trend(
        breadth_history, adv_ratio, adv_improvement,
        index_history=index_history, current_index=_number(twii.get('price')),
        current_stats={
            'asOf': pulse.get('date') or as_of, 'up': advancers, 'down': decliners,
            'flat': unchanged, 'indexChangePct': twii_change,
        },
    )

    inst_yi = _number(((snapshot.get('inst') or {}).get('totalYi')))
    if inst_yi is None:
        inst_yi = _number((((pulse.get('overview') or {}).get('institutional') or {}).get('totalYi')))
    volume_score = _number(strip.get('volumeScore', (pulse.get('pillars') or {}).get('volumeScore')))
    extras = pulse.get('extras') or {}
    tx_oi = extras.get('txOi') if isinstance(extras.get('txOi'), dict) else None
    oi_change_pct = _number((tx_oi or {}).get('oiChgPct'))
    oi_price_change_pct = _number((tx_oi or {}).get('priceChgPct'))
    oi_signal = None
    if oi_change_pct is not None and oi_price_change_pct is not None and abs(oi_change_pct) >= 0.25:
        # 同契約 OI 增減只表示部位建立／平倉；方向由同日價格方向決定。
        magnitude = _clamp(abs(oi_change_pct) / 3.0, 0.0, 1.0)
        oi_signal = magnitude if oi_price_change_pct > 0 else (-magnitude if oi_price_change_pct < 0 else 0.0)
    sbl = extras.get('sbl') if isinstance(extras.get('sbl'), dict) else None
    flow_parts = []
    if inst_yi is not None:
        flow_parts.append(_clamp(inst_yi / 300.0))
    if volume_score is not None:
        flow_parts.append(_clamp((volume_score - 50.0) / 50.0))
    if oi_signal is not None:
        flow_parts.append(oi_signal)
    flow_norm = sum(flow_parts) / len(flow_parts) if flow_parts else None

    sector_flow = dict(sector_flow or {})
    participation = _number(sector_flow.get('participationPct'))
    sector_norm = _clamp((participation / 100.0 - 0.5) / 0.30) if participation is not None else None
    global_tech = _global_tech_change(pulse)
    global_norm = _clamp(global_tech / 2.0) if global_tech is not None else None
    risk_score = _number(pulse.get('riskScore'))
    health_score = _number(pulse.get('healthScore'))
    risk_burden = _clamp((risk_score or 0.0) / 100.0, 0.0, 1.0) if risk_score is not None else None

    features = {
        'trend': _feature(trend_norm, {'changePct': twii_change, 'momScore': mom_score}),
        'breadth': _feature(breadth_norm, {
            'advRatio': adv_ratio, 'improvement': adv_improvement,
            'velocity3': breadth_trend.get('velocity3'), 'velocity5': breadth_trend.get('velocity5'),
            'belowNeutralStreak': breadth_trend.get('belowNeutralStreak'),
        }),
        'flow': _feature(flow_norm, {
            'institutionalNetYi': inst_yi, 'volumeScore': volume_score,
            'txOiContract': (tx_oi or {}).get('contract'), 'txOiChangePct': oi_change_pct,
            'txOiPriceChangePct': oi_price_change_pct, 'txOiSignal': round(oi_signal, 4) if oi_signal is not None else None,
            'sblSellYi': _number((sbl or {}).get('sblSellYi')),
        }),
        'sector': _feature(sector_norm, {'participationPct': participation, 'mode': sector_flow.get('mode')}),
        'global': _feature(global_norm, {'usTechChangePct': global_tech}),
        'risk': {'value': round(risk_burden, 4) if risk_burden is not None else None,
                 'raw': {'healthScore': health_score, 'riskScore': risk_score},
                 'available': risk_burden is not None or health_score is not None},
    }
    completeness = _number(pulse.get('dataCompleteness'))
    completeness = _clamp((completeness or 0.0) / 100.0, 0.0, 1.0)
    freshness = 1.0
    try:
        dt = _aware_datetime(as_of)
        if dt is None:
            raise ValueError('invalid asOf')
        age = max(0.0, (now.astimezone(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())
        freshness = 1.0 if age <= 300 else (0.8 if age <= 1800 else (0.5 if age <= 21600 else 0.2))
    except (TypeError, ValueError):
        freshness = 0.8

    scope_consistent = str(pulse.get('breadthScope') or 'TWSE_STOCKS') == 'TWSE_STOCKS'
    missing_core = []
    if twii_change is None:
        missing_core.append('twii_change')
    if adv_ratio is None:
        missing_core.append('breadth_adv_ratio')
    if risk_score is None and health_score is None:
        missing_core.append('health_or_risk')
    if not scope_consistent:
        missing_core.append('breadth_scope')

    basis_pct = _number(strip.get('basisPct'))
    spot_session = str((twii.get('market') or {}).get('session') or twii.get('session') or 'regular')
    futures_session = str((txf.get('market') or {}).get('session') or txf.get('session') or 'night')
    basis_context = _basis_context(
        spot_price=_number(twii.get('price')), futures_price=_number(txf.get('price')),
        spot_change=twii_change, futures_change=txf_change,
        spot_session=spot_session, futures_session=futures_session,
        index_history=index_history, futures_history=futures_history,
        oi_change_pct=oi_change_pct,
        fair_basis_estimate_pts=_number(strip.get('fairBasisEstimatePts')),
        expected_dividend_pts=_number(strip.get('expectedDividendPoints')),
    )
    turnover_vs5 = _number(strip.get('turnoverVsMa5Pct'))
    divergences = _detect_divergences(
        index_change=twii_change, index_streak=index_streak,
        adv_ratio=adv_ratio, adv_improvement=adv_improvement,
        advancers=advancers, decliners=decliners,
        turnover_vs5=turnover_vs5, txf_change=txf_change, basis_pct=basis_pct,
        breadth_trend=breadth_trend, basis_context=basis_context, oi_change_pct=oi_change_pct,
        inst_yi=inst_yi, tw_tech=_tw_tech_change(pulse), global_tech=global_tech,
    )

    index_source = ((twii.get('market') or {}).get('source') or twii.get('source') or 'unknown')
    index_session = ((twii.get('market') or {}).get('session') or 'regular')
    index_ref = ((twii.get('market') or {}).get('referenceType') or twii.get('referenceType') or 'previous_close')
    evidence = []
    if twii_change is not None:
        evidence.append(_make_evidence('twii.live', 'displayChangePct', twii_change, source=index_source,
            as_of=((twii.get('market') or {}).get('asOf') or twii.get('asOf') or as_of),
            reference=index_ref, session=index_session, quality='official'))
    if txf_change is not None:
        evidence.append(_make_evidence('txf.live', 'displayChangePct', txf_change,
            source=((txf.get('market') or {}).get('source') or txf.get('source') or 'unknown'),
            as_of=((txf.get('market') or {}).get('asOf') or txf.get('asOf') or as_of),
            reference=((txf.get('market') or {}).get('referenceType') or 'previous_close'),
            session=((txf.get('market') or {}).get('session') or txf.get('session') or 'night'), quality='official'))
    if adv_ratio is not None:
        evidence.append(_make_evidence('breadth.stock_scope', 'advRatio', adv_ratio,
            source=pulse.get('breadthSource') or 'TWSE MI_INDEX MS', as_of=pulse.get('date') or as_of,
            reference='same-session TWSE stock up/down counts', market_scope='TWSE_STOCKS', quality='official',
            comparison='below_neutral' if adv_ratio < 0.5 else 'above_neutral'))
    if breadth_trend.get('velocity3') is not None or breadth_trend.get('velocity5') is not None:
        evidence.append(_make_evidence(
            'breadth.velocity', 'advRatioRegressionSlope',
            {'slope3': breadth_trend.get('velocity3'), 'slope5': breadth_trend.get('velocity5'),
             'belowNeutralStreak': breadth_trend.get('belowNeutralStreak')},
            source=pulse.get('breadthSource') or 'TWSE MI_INDEX MS', as_of=pulse.get('date') or as_of,
            reference='3/5-session OLS slope; negative means breadth deterioration',
            market_scope='TWSE_STOCKS', quality='derived'))
    if inst_yi is not None:
        evidence.append(_make_evidence('flow.institutional', 'institutionalNetYi', inst_yi,
            source='TWSE BFI82U', as_of=(((pulse.get('overview') or {}).get('institutional') or {}).get('date') or as_of),
            reference='foreign+trust+dealer same-session net', market_scope='TWSE', quality='official'))
    if volume_score is not None:
        evidence.append(_make_evidence('turnover.score', 'volumeScore', volume_score,
            source='TWSE FMTQIK', as_of=as_of, reference='current turnover vs 5/20-session distribution',
            market_scope='TWSE', quality='derived'))
    if tx_oi and oi_change_pct is not None:
        evidence.append(_make_evidence('flow.tx_oi', 'sameContractOiChangePct', round(oi_change_pct, 4),
            source=tx_oi.get('source') or 'FinMind TaiwanFuturesDaily TX', as_of=tx_oi.get('date') or as_of,
            reference=f"contract {tx_oi.get('contract') or 'unknown'} vs {tx_oi.get('prevDate') or 'previous same contract'}",
            market_scope='TAIFEX_TX', session='day', quality='market',
            comparison=('price_up' if (oi_price_change_pct or 0) > 0 else
                        ('price_down' if (oi_price_change_pct or 0) < 0 else 'price_flat'))))
    if basis_context.get('basisZ20') is not None:
        evidence.append(_make_evidence(
            'basis.day_session', 'sameDayCloseBasisZ20', basis_context.get('basisZ20'),
            source='TWSE ^TWII daily + FinMind TAIFEX TX near-month day session', as_of=pulse.get('date') or as_of,
            reference=basis_context.get('reference') or 'same-date close basis',
            market_scope='TWSE_TAIFEX', session='day', quality='derived',
            comparison=('extreme' if abs(float(basis_context['basisZ20'])) >= 2 else 'normal_range')))
    if sbl and _number(sbl.get('sblSellYi')) is not None:
        evidence.append(_make_evidence('flow.sbl', 'sblSellYi', round(_number(sbl.get('sblSellYi')), 3),
            source=sbl.get('source') or 'TWSE TWTASU', as_of=sbl.get('date') or as_of,
            reference='same-session aggregate securities lending sell amount',
            market_scope='TWSE', session='regular', quality='official'))
    if health_score is not None:
        evidence.append(_make_evidence('pulse.health', 'healthScore', health_score,
            source='tw-pulse-intel/v1', as_of=as_of, reference='deterministic market-health pillars', quality='model'))
    if risk_score is not None:
        evidence.append(_make_evidence('pulse.risk', 'riskScore', risk_score,
            source='tw-pulse-intel/v1', as_of=as_of, reference='deterministic risk-factor ledger', quality='model'))
    if participation is not None:
        evidence.append(_make_evidence('sector.participation', 'positiveSectorPct', participation,
            source=sector_flow.get('source') or 'unknown', as_of=sector_flow.get('asOf') or as_of,
            reference=sector_flow.get('label') or 'same-scope sector participation',
            market_scope=sector_flow.get('marketScope') or 'TWSE', quality='official' if sector_flow.get('flowEligible') else 'proxy'))
    if global_tech is not None:
        evidence.append(_make_evidence('global.tech', 'SOX_IXIC_meanChangePct', round(global_tech, 4),
            source='Yahoo Finance', as_of=as_of, reference='latest available US session',
            market_scope='US', session='latest_available', quality='market'))

    options_structure = dict(options_structure or {
        'status': 'insufficient', 'shadowMode': True, 'decisionUse': 'research_only'})
    option_observed = options_structure.get('observed') or {}
    option_derived = options_structure.get('derived') or {}
    option_modeled = options_structure.get('modeled') or {}
    option_quality = options_structure.get('quality') or {}
    option_history = options_structure.get('history') or {}
    option_expiry = option_observed.get('expiry')
    if option_expiry and option_observed.get('rowCount'):
        evidence.append(_make_evidence(
            'options.chain', 'expiryScopedOpenInterest', {
                'expiry': option_expiry,
                'callOi': option_observed.get('callOpenInterest'),
                'putOi': option_observed.get('putOpenInterest'),
                'oiPutCallRatio': option_observed.get('oiPutCallRatio'),
                'callOiMaxStrike': (option_observed.get('callWall') or {}).get('strike'),
                'callOiMax': (option_observed.get('callWall') or {}).get('openInterest'),
                'putOiMaxStrike': (option_observed.get('putWall') or {}).get('strike'),
                'putOiMax': (option_observed.get('putWall') or {}).get('openInterest'),
            }, source='TAIFEX OpenAPI DailyMarketReportOpt',
            as_of=option_observed.get('tradeDate') or option_quality.get('chainAsOf'),
            reference=f'exact expiry {option_expiry}; official day-session EOD chain',
            market_scope='TAIFEX_TXO', session='day_eod', quality='official'))
    if option_derived.get('totalOiGamma1PctNtd') is not None:
        evidence.append(_make_evidence(
            'options.gamma_density', 'oiGamma1PctNtd', {
                'totalYi': option_derived.get('totalOiGammaYi'),
                'ivOiCoveragePct': option_derived.get('ivOiCoveragePct'),
            }, source='ST Black-Scholes from TAIFEX settlement/OI',
            as_of=option_observed.get('tradeDate'),
            reference='direction-neutral OI × gamma × 50 × spot² × 1%; not dealer net exposure',
            market_scope='TAIFEX_TXO', session='research', quality='derived'))
    if option_derived.get('totalOiVega1VolPointNtd') is not None:
        evidence.append(_make_evidence(
            'options.vega_density', 'oiVega1VolPointNtd', {
                'totalWan': option_derived.get('totalOiVegaWan'),
                'vegaOiCoveragePct': option_derived.get('vegaOiCoveragePct'),
            }, source='ST Black-Scholes from TAIFEX settlement/OI',
            as_of=option_observed.get('tradeDate'),
            reference='direction-neutral one-side OI × vega × 50 × 0.01; NTD per IV 1 vol point',
            market_scope='TAIFEX_TXO', session='research', quality='derived'))
    if option_derived.get('atmIvPct') is not None:
        evidence.append(_make_evidence(
            'options.iv_structure', 'expiryIvStructure', {
                'expiry': option_expiry, 'atmIvPct': option_derived.get('atmIvPct'),
                'ivSkew25dPctPoint': option_derived.get('ivSkew25dPctPoint'),
                'coveragePct': option_derived.get('ivOiCoveragePct'),
            }, source='ST Black-Scholes from TAIFEX settlement',
            as_of=option_observed.get('tradeDate'),
            reference='ACT/365 with disclosed r/q assumptions; no missing-IV imputation',
            market_scope='TAIFEX_TXO', session='research', quality='derived'))
    if option_modeled.get('eligible'):
        evidence.append(_make_evidence(
            'options.gex_scenario', 'modeledSignedGexAndFlipBand', {
                'directionConsensus': option_modeled.get('directionConsensus'),
                'flipLow': (option_modeled.get('flipBand') or {}).get('low'),
                'flipHigh': (option_modeled.get('flipBand') or {}).get('high'),
                'flipWidthPct': (option_modeled.get('flipBand') or {}).get('widthPct'),
                'flipStability': (option_modeled.get('flipBand') or {}).get('stability'),
                'balancedGexYi': (((option_modeled.get('scenarios') or [{}])[0]).get('signedGexYi')),
                'balancedVexYi': (((option_modeled.get('scenarios') or [{}])[0]).get('scenarioVexYi')),
                'balancedFlip': (((option_modeled.get('scenarios') or [{}])[0]).get('primaryFlip')),
                'coefficientVersion': option_modeled.get('coefficientVersion'),
            }, source='ST explicit position scenarios',
            as_of=option_observed.get('tradeDate'),
            reference='modeled dealer-side coefficients; public OI cannot reveal dealer inventory',
            market_scope='TAIFEX_TXO', session='shadow_research', quality='model'))
    if option_history.get('status') == 'ready':
        option_changes = option_history.get('changes') or {}
        evidence.append(_make_evidence(
            'options.same_expiry_change', 'sameExpiryStructureChange', {
                'expiry': option_history.get('expiry'),
                'baselineTradeDate': option_history.get('baselineTradeDate'),
                'callOiChangePct': option_changes.get('callOpenInterestPct'),
                'putOiChangePct': option_changes.get('putOpenInterestPct'),
                'atmIvChangePctPoint': option_changes.get('atmIvPctPoint'),
                'gammaDensityChangePct': option_changes.get('totalOiGammaPct'),
                'vegaDensityChangePct': option_changes.get('totalOiVegaPct'),
            }, source='ST local TXO compact history', as_of=option_history.get('currentTradeDate'),
            reference='strict prior tradeDate within the same exact expiry; no cross-expiry comparison',
            market_scope='TAIFEX_TXO', session='day_eod_change', quality='derived'))

    core_bad = bool(missing_core) or freshness < 0.25 or completeness < 0.35
    trend_v = features['trend']['value']
    breadth_v = features['breadth']['value']
    flow_v = features['flow']['value']
    extreme = ((twii_change is not None and twii_change <= -3.0 and adv_ratio is not None and adv_ratio <= 0.20)
               or ((_number(stocks.get('limitDown')) or 0) >= 20 and adv_ratio is not None and adv_ratio < 0.25))
    if core_bad:
        regime_id, rule_id = 'INSUFFICIENT_DATA', 'regime.insufficient_data.v1'
    elif extreme:
        regime_id, rule_id = 'CAPITULATION', 'regime.capitulation.v1'
    elif trend_v is not None and breadth_v is not None and trend_v < -0.45 and breadth_v < -0.35 and (risk_burden or 0) >= 0.55:
        regime_id, rule_id = 'DEFENSIVE_RISK_OFF', 'regime.defensive_risk_off.v1'
    elif trend_v is not None and breadth_v is not None and flow_v is not None and trend_v > 0.35 and breadth_v > 0.25 and flow_v > 0.05:
        regime_id, rule_id = 'BROAD_RISK_ON', 'regime.broad_risk_on.v1'
    elif trend_v is not None and breadth_v is not None and trend_v > 0.30 and breadth_v < -0.10:
        regime_id, rule_id = 'NARROW_RALLY', 'regime.narrow_rally.v1'
    elif trend_v is not None and breadth_v is not None and trend_v > -0.05 and breadth_v > 0.20 and (adv_improvement or 0) >= 0.08 and (flow_v is None or flow_v <= 0.20):
        regime_id, rule_id = 'RECOVERY_ATTEMPT', 'regime.recovery_attempt.v1'
    else:
        regime_id, rule_id = 'CONFLICT', 'regime.conflict.v1'

    weighted = []
    for key, weight in (('trend', 0.35), ('breadth', 0.25), ('flow', 0.15), ('sector', 0.10), ('global', 0.10)):
        val = features[key]['value']
        if val is not None:
            weighted.append((val, weight))
    composite = sum(v * w for v, w in weighted) / sum(w for _, w in weighted) if weighted else 0.0
    if risk_burden is not None:
        composite -= 0.15 * risk_burden
    composite = _clamp(composite)
    separation = min(1.0, abs(composite) + (0.20 if regime_id in ('NARROW_RALLY', 'RECOVERY_ATTEMPT') else 0.0))
    confidence = 0.35 + completeness * 0.35 + freshness * 0.15 + separation * 0.15
    confidence -= min(0.18, len([d for d in divergences if d['severity'] in ('warning', 'critical')]) * 0.04)
    if regime_id == 'INSUFFICIENT_DATA':
        confidence = min(0.20, completeness * 0.20)
    confidence = round(_clamp(confidence, 0.0, 0.95), 2)

    portfolio = _portfolio_summary(portfolio_overlay, portfolio_kind)
    key_levels = dict(key_levels or {})
    tsmc_quote = _quote(pulse, '2330', {})
    current_tsmc_price = _number(tsmc_quote.get('price'))
    exposure = _exposure_lab.build_exposure_lab(
        key_levels=key_levels, benchmark_data=benchmark_data,
        margin_state=margin_state, risk_profile=risk_profile,
        portfolio=portfolio,
        research_inputs={'currentTsmcPrice': current_tsmc_price},
        as_of=as_of)
    envelope = _action_envelope(
        regime_id, divergences, key_levels, confidence, risk_profile, portfolio, exposure)
    exposure['finalEligibleRange'] = envelope.get('positionRange')
    reliability = ((((exposure.get('fundamentalReliability') or {}).get('tsmcGuidanceHistory') or {}).get('value')) or {})
    if reliability:
        evidence.append(_make_evidence(
            'fundamental.tsmc_guidance', 'guidanceAtOrAboveHighRatePct',
            reliability.get('atOrAboveHighRatePct'), source='TSMC quarterly earnings releases',
            as_of='2026Q2', reference=f"{reliability.get('atOrAboveHighCount')}/{reliability.get('observations')} observations",
            market_scope='TSMC', session='research', quality='official'))
    eps_evidence = (((exposure.get('fundamentalReliability') or {}).get('tsmcEpsEvidence') or {}).get('value') or {})
    if eps_evidence:
        evidence.append(_make_evidence(
            'fundamental.tsmc_eps_path', 'actualGuidanceModelQuarterCount', {
                'actualQuarters': eps_evidence.get('actualQuarters'),
                'guidanceDerivedQuarters': eps_evidence.get('guidanceDerivedQuarters'),
                'modelQuarters': eps_evidence.get('modelQuarters'),
                'epsBase': eps_evidence.get('epsBase'),
                'assumptionFingerprint': eps_evidence.get('assumptionFingerprint'),
            }, source='TSMC quarterly results + FantasyMaya external research model',
            as_of=eps_evidence.get('asOf'),
            reference='Q1/Q2 actual; Q3 guidance-derived; Q4 model estimate; no false confidence interval',
            market_scope='TSMC', session='research', quality='mixed_actual_guidance_model'))
    benchmark_rows = exposure.get('benchmarks') or {}
    if benchmark_rows:
        evidence.append(_make_evidence(
            'fundamental.tsmc_weight', 'benchmarkSpecificTsmcWeightPct', {
                key: {'value': row.get('tsmcWeightPct'), 'asOf': row.get('weightAsOf'),
                      'quality': row.get('weightQuality'), 'pointInTimeAudited': row.get('pointInTimeAudited')}
                for key, row in benchmark_rows.items()
            }, source='FantasyMaya Part 2 public research snapshot', as_of='2026-07-31',
            reference='benchmark-specific model input; official point-in-time series still pending',
            market_scope='TW_BENCHMARKS', session='research', quality='external_research'))
    core_research = exposure.get('coreResearch') or {}
    core_assumption_field = (exposure.get('assumptions') or {}).get('core') or {}
    core_assumptions = core_assumption_field.get('value') or {}
    evidence.append(_make_evidence(
        'research.core_assumptions', 'monthlyFrozenCoreAssumptions', {
            'selectedBenchmarkId': core_research.get('selectedBenchmarkId'),
            'frozenUntil': core_research.get('frozenUntil'),
            'tsmcForwardEps': core_assumptions.get('tsmcForwardEps'),
            'payoutRatioPct': core_assumptions.get('payoutRatioPct'),
            'otherDividendYieldPct': core_assumptions.get('otherDividendYieldPct'),
            'incremental2xCostPct': core_assumptions.get('incremental2xCostPct'),
            'assumptionFingerprint': core_research.get('assumptionFingerprint'),
        }, source=core_assumption_field.get('source') or 'ST exposure research registry',
        as_of=core_research.get('asOf'),
        reference='monthly frozen, research-only; weekly health cannot mutate this snapshot',
        market_scope='TW_RESEARCH', session='research', quality='model_assumption'))
    selected_benchmark = exposure.get('selectedBenchmarkId')
    selected_row = benchmark_rows.get(selected_benchmark) or {}
    selected_vol = (exposure.get('volatility') or {})
    horizon_field = selected_vol.get('horizonForecastAnnualPct') or {}
    if selected_benchmark and selected_benchmark != 'MIXED':
        evidence.append(_make_evidence(
            'research.long_horizon_volatility', 'benchmarkHorizonVolatilityAnnualPct',
            horizon_field.get('value'), source=horizon_field.get('source') or 'unknown',
            as_of=horizon_field.get('asOf'),
            reference=horizon_field.get('reference') or 'benchmark-specific long-horizon volatility',
            market_scope=selected_benchmark, session='research',
            quality=horizon_field.get('quality') or 'insufficient'))
    edge = selected_row.get('leveragedCarryEdge2x') or {}
    if selected_row:
        evidence.append(_make_evidence(
            'research.leverage_edge', 'leveragedCarryEdge2xPctPoint', {
                'benchmarkId': selected_benchmark,
                'bear': edge.get('bearPctPoint'), 'base': edge.get('basePctPoint'),
                'bull': edge.get('bullPctPoint'), 'crossesZero': edge.get('crossesZero'),
                'status': edge.get('status'), 'actionAuthority': edge.get('actionAuthority'),
            }, source='ST Exposure Lab v3', as_of=core_research.get('asOf'),
            reference='M2=g_proxy-(sigma_horizon^2+c_incremental); positive is not an add-risk permission',
            market_scope=selected_benchmark or 'TW_RESEARCH', session='research', quality='model'))
    external_validation = exposure.get('externalValidation') or {}
    if external_validation:
        evidence.append(_make_evidence(
            'research.external_oos_validation', 'weeklyVolatilityTimingOosResult', {
                'status': external_validation.get('status'),
                'dynamicCagrPct': external_validation.get('dynamicCagrPct'),
                'matchedExposureFixedCagrPct': external_validation.get('matchedExposureFixedCagrPct'),
                'differencePctPoint': external_validation.get('differencePctPoint'),
                'stReproduced': external_validation.get('stReproduced'),
            }, source=external_validation.get('source') or 'external research',
            as_of=external_validation.get('asOf'),
            reference=external_validation.get('sample') or 'external out-of-sample study',
            market_scope='FTSE_TAIWAN_50', session='research', quality='external_research'))
    mechanics = exposure.get('productMechanics') or {}
    if mechanics.get('rows'):
        evidence.append(_make_evidence(
            'product.daily_leverage_mechanics', 'resetCostAndLiabilityContract', [
                {key: row.get(key) for key in (
                    'symbol', 'underlyingBenchmarkId', 'targetLeverage', 'resetFrequency',
                    'liabilityType', 'holderMarginCallRisk', 'incrementalCostPct', 'quality')}
                for row in mechanics.get('rows') or []
            ], source='TWSE product mechanics + ST explicit assumptions', as_of=core_research.get('asOf'),
            reference='product name never substitutes for underlying, daily reset, cost or liability risk',
            market_scope='TW_PRODUCTS', session='research', quality='mixed'))
    if margin_state and margin_state.get('available'):
        evidence.append(_make_evidence(
            'risk.margin_balance', 'marginBalancePercentile52w', margin_state.get('percentile52w'),
            source=margin_state.get('source') or 'TWSE MI_MARGN MS', as_of=margin_state.get('asOf'),
            reference=margin_state.get('reference') or 'trailing 52-week observations',
            market_scope='TWSE', session='regular', quality='official',
            comparison=margin_state.get('direction')))
    stale_fields = []
    if ((key_levels.get('quality') or {}).get('stale')):
        stale_fields.append('keyLevels')
    if options_structure.get('status') == 'stale' or option_quality.get('isHybridTimestamp'):
        stale_fields.append('optionsStructure')
    news = []
    for item in pulse.get('flash') or []:
        if isinstance(item, dict) and isinstance(item.get('impact'), dict):
            news.append({'time': item.get('time'), 'title': item.get('title'), 'code': item.get('code'),
                         'mkt': item.get('mkt'), 'url': item.get('url'), 'impact': item.get('impact')})
    conflicts = [d['id'] for d in divergences if d['severity'] in ('warning', 'critical')]
    context = {
        'ok': True,
        'contractVersion': CONTRACT_VERSION,
        'market': 'TW',
        'asOf': as_of,
        'regime': {
            'id': regime_id, 'label': REGIME_LABELS[regime_id], 'score': round(composite, 3),
            'confidence': confidence, 'ruleId': rule_id,
        },
        'actionEnvelope': envelope,
        'keyLevels': key_levels,
        'volatility': key_levels.get('volatility') or {},
        'divergences': divergences,
        'breadthTrend': breadth_trend,
        'basisContext': basis_context,
        'sectorFlow': sector_flow,
        'portfolioOverlay': portfolio,
        'exposureLab': exposure,
        'optionsStructure': options_structure,
        'newsImpact': news[:12],
        'scenario': features,
        'confirmation': envelope['confirmation'],
        'invalidation': envelope['invalidation'],
        'evidence': evidence,
        'dataQuality': {
            'completeness': round(completeness, 3), 'freshness': round(freshness, 3),
            'scopeConsistency': scope_consistent, 'conflicts': conflicts,
            'staleFields': stale_fields, 'missingCore': missing_core,
        },
        'model': ENGINE_VERSION,
    }
    context['consensusAttention'] = _consensus_attention.build_consensus_attention(context)
    return context


def compact_context(context: dict | None) -> dict[str, Any]:
    context = context or empty_context()
    regime = context.get('regime') or {}
    env = context.get('actionEnvelope') or {}
    quality = context.get('dataQuality') or {}
    key_levels = context.get('keyLevels') or {}
    levels = (key_levels.get('levels') or {})
    volatility = context.get('volatility') or {}
    flow = (((context.get('scenario') or {}).get('flow') or {}).get('raw') or {})
    exposure = context.get('exposureLab') or {}
    return {
        'contractVersion': context.get('contractVersion', CONTRACT_VERSION),
        'asOf': context.get('asOf'),
        'regime': regime,
        'posture': env.get('posture'),
        'allowed': list(env.get('allowed') or [])[:3],
        'restricted': list(env.get('restricted') or [])[:3],
        'prohibited': list(env.get('prohibited') or [])[:3],
        'mandatoryControls': list(env.get('mandatoryControls') or [])[:3],
        'confirmation': list(context.get('confirmation') or [])[:2],
        'invalidation': list(context.get('invalidation') or [])[:2],
        'levels': {k: levels.get(k) for k in ('r1', 'pivot', 's1')},
        'keyLevelMeta': {
            'referenceDate': key_levels.get('referenceDate'),
            'source': key_levels.get('source'),
            'method': key_levels.get('method'),
            'quality': key_levels.get('quality') or {},
        },
        'volatility': {k: volatility.get(k) for k in (
            'expectedOneDayPct', 'normal68OneDayPct', 'normal68Range',
            'normal95OneDayPct', 'normal95Range', 'proxy', 'modelLimitations',
        )},
        'flow': {k: flow.get(k) for k in (
            'institutionalNetYi', 'volumeScore', 'txOiContract', 'txOiChangePct',
            'txOiPriceChangePct', 'txOiSignal', 'sblSellYi',
        )},
        'exposureLab': {
            'model': exposure.get('model'),
            'shadowMode': exposure.get('shadowMode'),
            'actionAuthority': exposure.get('actionAuthority'),
            'riskMode': exposure.get('riskMode'),
            'selectedBenchmarkId': exposure.get('selectedBenchmarkId'),
            'selectedResearchCeilingPct': exposure.get('selectedResearchCeilingPct'),
            'coreResearch': {k: (exposure.get('coreResearch') or {}).get(k) for k in (
                'asOf', 'frozenUntil', 'reviewCadence', 'assumptionFingerprint',
                'actionAuthority', 'weeklyMutationAllowed')},
            'weeklyHealth': {k: (exposure.get('weeklyHealth') or {}).get(k) for k in (
                'status', 'headline', 'flags', 'reviewRequired', 'actionAuthority',
                'coreMutationAllowed', 'mayIncreaseExposure')},
            'portfolioLookThrough': exposure.get('portfolioLookThrough'),
            'benchmarkStatus': {k: (v or {}).get('status') for k, v in (exposure.get('benchmarks') or {}).items()},
            'hypotheses': exposure.get('hypotheses') or [],
        },
        'divergences': [d.get('id') for d in (context.get('divergences') or [])[:3]],
        'divergenceDetails': [
            {k: d.get(k) for k in ('id', 'severity', 'confidence', 'observed', 'insight', 'confirmation', 'invalidation')}
            for d in (context.get('divergences') or [])[:3]
        ],
        'consensusAttention': context.get('consensusAttention') or _consensus_attention.empty(),
        'basisContext': {k: (context.get('basisContext') or {}).get(k) for k in (
            'liveGapPts', 'liveGapPct', 'adjustedBasisPts', 'mode', 'sessionComparable',
            'basisZ20', 'basisZ60', 'sample20', 'sample60', 'futuresLagPctPoint',
            'oiChangePct', 'shortCoveringRisk', 'sessionTag',
        )},
        'dataQuality': quality,
        'model': context.get('model'),
    }


def _fingerprint(pulse: dict) -> str:
    snap = pulse.get('snapshot') or {}
    selected = {
        'date': pulse.get('date'), 'updatedAt': pulse.get('updatedAt'),
        'snapshot': snap, 'riskScore': pulse.get('riskScore'), 'healthScore': pulse.get('healthScore'),
        'dataCompleteness': pulse.get('dataCompleteness'),
        'basis': (((pulse.get('overview') or {}).get('strip') or {}).get('basisPct')),
        'indexTrend': (((pulse.get('overview') or {}).get('strip') or {}).get('t00Trend')),
    }
    raw = json.dumps(selected, sort_keys=True, ensure_ascii=False, default=str).encode('utf-8')
    return hashlib.sha256(raw).hexdigest()[:24]


def _init_db(path: str = DB_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with closing(sqlite3.connect(path, timeout=10)) as conn:
        with conn:
            conn.execute('CREATE TABLE IF NOT EXISTS decision_history('
                         'id INTEGER PRIMARY KEY AUTOINCREMENT, as_of TEXT, created_at INTEGER, market TEXT, '
                         'input_hash TEXT UNIQUE, regime TEXT, confidence REAL, completeness REAL, context_json TEXT)')


def _save_history(context: dict, input_hash: str, path: str = DB_PATH) -> None:
    _init_db(path)
    with closing(sqlite3.connect(path, timeout=10)) as conn:
        with conn:
            conn.execute('INSERT OR IGNORE INTO decision_history(as_of,created_at,market,input_hash,regime,confidence,completeness,context_json) '
                         'VALUES(?,?,?,?,?,?,?,?)', (
                             context.get('asOf'), int(time.time()), context.get('market'), input_hash,
                             (context.get('regime') or {}).get('id'), (context.get('regime') or {}).get('confidence'),
                             (context.get('dataQuality') or {}).get('completeness'),
                             json.dumps(context, ensure_ascii=False, separators=(',', ':'), default=str)))
            conn.execute('DELETE FROM decision_history WHERE id NOT IN '
                         '(SELECT id FROM decision_history ORDER BY id DESC LIMIT 500)')


def _write_trace(context: dict, input_hash: str, elapsed_ms: int, path: str = TRACE_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    row = {
        'ts': _iso_now(), 'correlationId': input_hash, 'inputVersion': 'pulse/v2',
        'inputHash': input_hash, 'regime': (context.get('regime') or {}).get('id'),
        'confidence': (context.get('regime') or {}).get('confidence'),
        'rulesHit': [(context.get('regime') or {}).get('ruleId')],
        'conflicts': (context.get('dataQuality') or {}).get('conflicts') or [],
        'staleFields': (context.get('dataQuality') or {}).get('staleFields') or [],
        'elapsedMs': elapsed_ms,
    }
    with open(path, 'a', encoding='utf-8') as fh:
        fh.write(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n')
    if os.path.getsize(path) > 256 * 1024:
        with open(path, 'r', encoding='utf-8') as fh:
            tail = fh.readlines()[-500:]
        with open(path, 'w', encoding='utf-8') as fh:
            fh.writelines(tail)


def publish_context(
    context: dict,
    *,
    pulse: dict,
    build_kwargs: dict[str, Any] | None = None,
    db_path: str = DB_PATH,
    trace_path: str = TRACE_PATH,
    elapsed_ms: int = 0,
) -> dict:
    """Publish one canonical context; persistence failures never block Pulse."""
    global _latest_context, _latest_inputs
    fingerprint = _fingerprint(pulse)
    context = dict(context or {})
    try:
        import early_warning as _early_warning
        import overnight_intraday as _overnight_intraday
        signal_db_path = _early_warning.DB_PATH
        if os.path.abspath(db_path) != os.path.abspath(DB_PATH):
            signal_db_path = os.path.join(os.path.dirname(os.path.abspath(db_path)), 'market_signals.db')
        warning = _early_warning.process_context(
            context, pulse, memory_snapshot=_overnight_intraday.latest_cached('all'),
            market_history=(build_kwargs or {}).get('index_history'),
            db_path=signal_db_path)
        context['earlyWarnings'] = warning
        source_map = {
            'globalTech': ('Yahoo Finance', 'latest finalized US session'),
            'anchor': ('Yahoo Finance + ST benchmark research registry', '2330 and 0050-ex-2330 residual where eligible'),
            'memoryCycle': ('ST overnight-intraday fixed baskets', '20-session adjusted daily session structure'),
            'breadthLiquidity': ('TWSE breadth + sector participation', 'same-session stock breadth and sector scope'),
            'flowDerivatives': ('TWSE/TAIFEX canonical Pulse', 'institutional, same-contract OI and futures context'),
        }
        warning_evidence = []
        for family in warning.get('familyScores') or []:
            source, reference = source_map.get(family.get('id'), ('ST deterministic signal engine', 'canonical inputs'))
            warning_evidence.append({
                'id': 'signal.family.' + str(family.get('id') or 'unknown'),
                'metric': 'shadowFamilyScore',
                'value': {
                    'score': family.get('value'), 'quality': family.get('quality'),
                    'available': family.get('available'), 'observed': family.get('observed') or {},
                },
                'comparison': 'negative -1 / neutral 0 / positive +1',
                'source': source, 'marketScope': 'TW_CROSS_MARKET', 'session': 'session_aligned_shadow',
                'asOf': warning.get('asOf'), 'reference': reference,
                'quality': 'derived' if family.get('available') else 'insufficient',
                'authority': 'shadow_observation',
            })
        validation = warning.get('prospectiveValidation') or {}
        validation_status = str(validation.get('status') or 'empty')
        warning_evidence.append({
            'id': 'signal.prospective_validation',
            'metric': 'prospectiveSignalLedger',
            'value': {
                'status': validation_status,
                'totalTrials': validation.get('totalTrials', 0),
                'resolvedOutcomes': validation.get('resolvedOutcomes', 0),
                'coveragePct': validation.get('coveragePct', 0),
                'horizons': validation.get('horizons') or [],
            },
            'comparison': '1 / 3 / 5 finalized sessions; empirical rates withheld below n=20',
            'source': 'ST append-only prospective signal ledger',
            'marketScope': 'TW_CROSS_MARKET', 'session': 'finalized_daily_close',
            'asOf': warning.get('asOf'),
            'reference': 'First observed tracked episode; no retrospective backfill',
            'quality': ('observed' if validation_status == 'ready' else
                        ('building' if validation_status in ('building', 'empty') else 'insufficient')),
            'authority': 'shadow_validation',
        })
        context['evidence'] = list(context.get('evidence') or []) + warning_evidence
    except Exception as exc:
        try:
            import early_warning as _early_warning
            context['earlyWarnings'] = _early_warning.empty(type(exc).__name__)
        except Exception:
            context['earlyWarnings'] = {
                'ok': False, 'shadowOnly': True, 'actionAuthority': 'none',
                'status': 'INSUFFICIENT_DATA', 'signals': [], 'newEvents': [],
            }
    # One canonical projection, recomputed only after the warning lifecycle is
    # attached.  It never polls providers and never mutates DecisionContext.
    context['consensusAttention'] = _consensus_attention.build_consensus_attention(context)
    with _lock:
        _latest_context = context
        _latest_inputs = {'pulse': pulse, **(build_kwargs or {})}
        _recent.append(context)
        _status['lastSuccess'] = _iso_now()
        _status['lastError'] = None
        _status['lastElapsedMs'] = elapsed_ms
    try:
        _save_history(context, fingerprint, db_path)
    except Exception as exc:
        with _lock:
            _status['lastError'] = 'history:' + str(exc)[:160]
    try:
        _write_trace(context, fingerprint, elapsed_ms, trace_path)
    except Exception as exc:
        with _lock:
            _status['lastError'] = 'trace:' + str(exc)[:160]
    try:
        if alert_daemon := __import__('alert_daemon'):
            alert_daemon.deliver_signal_events((context.get('earlyWarnings') or {}).get('newEvents') or [])
    except Exception as exc:
        with _lock:
            _status['lastError'] = 'signal-delivery:' + str(exc)[:160]
    return context


def build_and_publish(pulse: dict, **kwargs: Any) -> dict:
    started = time.perf_counter()
    context = build_decision_context(pulse, **kwargs)
    elapsed = int((time.perf_counter() - started) * 1000)
    base_kwargs = {k: v for k, v in kwargs.items() if k not in ('portfolio_overlay', 'risk_profile', 'portfolio_kind')}
    return publish_context(context, pulse=pulse, build_kwargs=base_kwargs, elapsed_ms=elapsed)


def latest_context() -> dict | None:
    with _lock:
        return json.loads(json.dumps(_latest_context, ensure_ascii=False)) if _latest_context else None


def rebuild_latest(
    *,
    risk_profile: dict | None = None,
    portfolio_overlay: dict | None = None,
    portfolio_kind: str = 'actual',
    options_structure: dict[str, Any] | None = None,
) -> dict:
    with _lock:
        inputs = dict(_latest_inputs or {})
        latest_warning = ((_latest_context or {}).get('earlyWarnings') if _latest_context else None)
        latest_warning_evidence = [
            row for row in (((_latest_context or {}).get('evidence') if _latest_context else None) or [])
            if str((row or {}).get('id') or '').startswith('signal.')
        ]
    if not inputs:
        return empty_context('pulse_not_ready')
    if options_structure is not None:
        inputs['options_structure'] = options_structure
    context = build_decision_context(**inputs, risk_profile=risk_profile, portfolio_overlay=portfolio_overlay, portfolio_kind=portfolio_kind)
    if latest_warning:
        context['earlyWarnings'] = json.loads(json.dumps(latest_warning, ensure_ascii=False))
        context['evidence'] = list(context.get('evidence') or []) + json.loads(
            json.dumps(latest_warning_evidence, ensure_ascii=False))
    context['consensusAttention'] = _consensus_attention.build_consensus_attention(context)
    return context


def latest_market_reference() -> dict[str, Any] | None:
    """Return the exact canonical TWII quote used by the latest Pulse build."""
    with _lock:
        inputs = dict(_latest_inputs or {})
    pulse = inputs.get('pulse') or {}
    if not pulse:
        return None
    snapshot = pulse.get('snapshot') or {}
    indices = pulse.get('indices') or {}
    quote = _quote(pulse, '^TWII', (indices.get('t00') or snapshot.get('t00') or {}))
    price = _number(quote.get('price'))
    if price is None:
        return None
    market = quote.get('market') or {}
    return {
        'price': price,
        'asOf': (market.get('sessionDate') or quote.get('tradeDate') or quote.get('date') or
                 pulse.get('date') or market.get('asOf') or quote.get('asOf') or pulse.get('updatedAt')),
        'source': market.get('source') or quote.get('source') or 'canonical-pulse',
        'session': market.get('session') or quote.get('session') or 'regular',
    }


def update_options_structure(options_structure: dict[str, Any]) -> dict:
    """Rebuild and publish the canonical context after an explicit TXO refresh."""
    with _lock:
        inputs = dict(_latest_inputs or {})
    pulse = inputs.pop('pulse', None)
    if not pulse:
        return empty_context('pulse_not_ready')
    inputs['options_structure'] = dict(options_structure or {})
    started = time.perf_counter()
    context = build_decision_context(pulse, **inputs)
    elapsed = int((time.perf_counter() - started) * 1000)
    return publish_context(context, pulse=pulse, build_kwargs=inputs, elapsed_ms=elapsed)


def history(n: int = 40, path: str = DB_PATH) -> dict[str, Any]:
    n = max(1, min(int(n or 40), 120))
    try:
        _init_db(path)
        with closing(sqlite3.connect(path, timeout=10)) as conn:
            rows = conn.execute('SELECT as_of,regime,confidence,completeness,context_json FROM decision_history '
                                'ORDER BY id DESC LIMIT ?', (n,)).fetchall()
        return {'ok': True, 'model': ENGINE_VERSION, 'rows': [
            {'asOf': r[0], 'regime': r[1], 'confidence': r[2], 'completeness': r[3],
             'context': json.loads(r[4]) if r[4] else None} for r in rows
        ]}
    except Exception as exc:
        return {'ok': False, 'error': str(exc), 'rows': []}


def replay(pulses: Iterable[dict], **kwargs: Any) -> dict[str, Any]:
    contexts = []
    for pulse in pulses or []:
        build_kwargs = dict(kwargs)
        # Historical fixtures must be evaluated at their observation time;
        # otherwise wall-clock freshness makes identical replays non-reproducible.
        if 'now' not in build_kwargs:
            observed_at = _aware_datetime((pulse or {}).get('updatedAt'))
            if observed_at is not None:
                build_kwargs['now'] = observed_at
        contexts.append(build_decision_context(pulse, **build_kwargs))
    transitions = []
    for prev, cur in zip(contexts, contexts[1:]):
        a, b = (prev.get('regime') or {}).get('id'), (cur.get('regime') or {}).get('id')
        if a != b:
            transitions.append({'from': a, 'to': b, 'asOf': cur.get('asOf')})
    return {'ok': True, 'count': len(contexts), 'transitions': transitions, 'contexts': contexts}


def engine_status() -> dict[str, Any]:
    with _lock:
        last = dict(_status)
        ctx = _latest_context
    age = None
    if last.get('lastSuccess'):
        try:
            age = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(last['lastSuccess'])).total_seconds())
        except Exception:
            age = None
    return {
        'version': ENGINE_VERSION,
        'contractVersion': CONTRACT_VERSION,
        'lastSuccess': last.get('lastSuccess'),
        'lastError': last.get('lastError'),
        'lastElapsedMs': last.get('lastElapsedMs'),
        'ageSec': round(age, 1) if age is not None else None,
        'regime': ((ctx or {}).get('regime') or {}).get('id'),
    }
