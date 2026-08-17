#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic, evidence-bounded exposure research for Stock Terminal.

Version 3 implements the governance correction established by the five-part
dynamic-leverage research series:

* the monthly core is benchmark-specific and frozen between reviews;
* weekly volatility and margin observations are monitor-only;
* product mechanics are modeled from underlying, reset, cost and liabilities;
* no positive research result can create an order or an add-risk permission.

The module is deliberately pure. It consumes existing canonical contracts and
never fetches market data by itself.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
from typing import Any


CONTRACT_VERSION = 3
MODEL_VERSION = 'st-exposure-lab/v3'
CORE_METHOD_VERSION = 'fundamental_return_proxy_v2'
VOL_METHOD_VERSION = 'benchmark_long_horizon_vol_v1'
PRODUCT_METHOD_VERSION = 'daily_leverage_mechanics_v1'


BENCHMARKS: dict[str, dict[str, Any]] = {
    'FTSE_TAIWAN_50': {
        'label': '臺灣50',
        'tsmcWeightPct': 58.35,
        'weightAsOf': '2026-07-31',
        'weightSource': 'FantasyMaya Part 2 public research snapshot',
        'weightQuality': 'external_research',
        'pointInTimeAudited': False,
    },
    'TAIEX': {
        'label': '加權指數',
        'tsmcWeightPct': 42.0,
        'weightAsOf': '2026-07-31',
        'weightSource': 'FantasyMaya Part 2 public research snapshot',
        'weightQuality': 'external_research',
        'pointInTimeAudited': False,
    },
}


PRODUCTS: dict[str, dict[str, Any]] = {
    '2330': {
        'name': '台積電', 'benchmark': 'TSMC', 'leverageMultiple': 1.0,
        'tsmcWeightPct': 100.0, 'technologyWeightPct': 100.0,
        'role': 'single_name_structural_growth', 'diversificationCredit': False,
        'resetFrequency': 'none', 'liabilityType': 'single_equity',
        'holderMarginCallRisk': False,
    },
    '0050': {
        'name': '元大臺灣50', 'benchmark': 'FTSE_TAIWAN_50', 'leverageMultiple': 1.0,
        'tsmcWeightPct': BENCHMARKS['FTSE_TAIWAN_50']['tsmcWeightPct'],
        'technologyWeightPct': 83.49,
        'role': 'large_cap_technology_heavy_index', 'diversificationCredit': True,
        'resetFrequency': 'none', 'liabilityType': 'fund_units',
        'holderMarginCallRisk': False,
    },
    '00631L': {
        'name': '元大臺灣50正2', 'benchmark': 'FTSE_TAIWAN_50', 'leverageMultiple': 2.0,
        'tsmcWeightPct': BENCHMARKS['FTSE_TAIWAN_50']['tsmcWeightPct'],
        'technologyWeightPct': 83.49,
        'role': 'concentrated_large_cap_daily_2x', 'diversificationCredit': False,
        'resetFrequency': 'daily', 'liabilityType': 'fund_level_derivatives',
        'holderMarginCallRisk': False, 'incrementalCostPct': 2.3,
        'costAsOf': '2026-08-14', 'costQuality': 'external_research_assumption',
    },
    '00685L': {
        'name': '群益臺灣加權正2', 'benchmark': 'TAIEX', 'leverageMultiple': 2.0,
        'tsmcWeightPct': BENCHMARKS['TAIEX']['tsmcWeightPct'],
        'technologyWeightPct': None,
        'role': 'concentrated_broad_market_daily_2x', 'diversificationCredit': False,
        'resetFrequency': 'daily', 'liabilityType': 'fund_level_derivatives',
        'holderMarginCallRisk': False, 'incrementalCostPct': 2.3,
        'costAsOf': '2026-08-14', 'costQuality': 'external_research_assumption',
        'hypothesisId': 'POST_SPLIT_LIQUIDITY_MOMENTUM',
    },
}


TSMC_GUIDANCE_HISTORY = (
    ('2024Q1', 18.0, 18.8, 18.87),
    ('2024Q3', 22.4, 23.2, 23.50),
    ('2024Q4', 26.1, 26.9, 26.88),
    ('2025Q1', 25.0, 25.8, 25.53),
    ('2025Q2', 28.4, 29.2, 30.07),
    ('2025Q3', 31.8, 33.0, 33.10),
    ('2025Q4', 32.2, 33.4, 33.73),
    ('2026Q1', 34.6, 35.8, 35.90),
    ('2026Q2', 39.0, 40.2, 40.20),
)


TSMC_EPS_PATH = (
    {'quarter': '2026Q1', 'eps': 22.08, 'kind': 'official_actual',
     'source': 'TSMC quarterly results'},
    {'quarter': '2026Q2', 'eps': 27.25, 'kind': 'official_actual',
     'source': 'TSMC quarterly results'},
    {'quarter': '2026Q3', 'eps': 29.29, 'kind': 'guidance_derived',
     'source': 'FantasyMaya model from TSMC Q3 guidance'},
    {'quarter': '2026Q4', 'eps': 28.98, 'kind': 'model_estimate',
     'source': 'FantasyMaya Part 2 public research snapshot'},
)


CORE_ASSUMPTIONS: dict[str, Any] = {
    'asOf': '2026-08-13',
    'frozenUntil': '2026-09-01',
    'reviewCadence': 'monthly',
    'assumptionReviewCadence': 'quarterly_or_official_earnings_event',
    'tsmcPrice': 2395.0,
    'tsmcForwardEps': 107.6,
    'payoutRatioPct': 55.0,
    'otherDividendYieldPct': 3.5,
    'convergenceYears': 5.0,
    'riskFreeRatePct': 1.5,
    'incremental2xCostPct': 2.3,
}


SCENARIOS: dict[str, dict[str, float]] = {
    'bear': {'tsmcGrowthPct': 18.0, 'otherGrowthPct': 0.0, 'fairPe': 18.0},
    'base': {'tsmcGrowthPct': 22.0, 'otherGrowthPct': 6.0, 'fairPe': 22.0},
    'bull': {'tsmcGrowthPct': 26.0, 'otherGrowthPct': 10.0, 'fairPe': 26.0},
}


EXTERNAL_VALIDATION = {
    'id': 'weekly_volatility_timing_oos',
    'status': 'EXTERNAL_OOS_FAILED',
    'source': 'https://blog.fantasymaya.org/posts/taiwan-dynamic-leverage-part4/',
    'asOf': '2026-08-14',
    'sample': 'train 2006-2015; out-of-sample 2016-2026',
    'dynamicCagrPct': 30.44,
    'matchedExposureFixedCagrPct': 36.63,
    'differencePctPoint': -6.19,
    'quality': 'external_research',
    'stReproduced': False,
    'authority': 'weekly_volatility_monitor_only',
}


def _number(value: Any) -> float | None:
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _field(
    value: Any, *, source: str, as_of: str | None, reference: str,
    scope: str, horizon: str, kind: str, method: str,
    confidence: str = 'medium', stale: bool = False,
    quality: str = 'model', benchmark_id: str | None = None,
    point_in_time_audited: bool = False, uncertainty: str | None = None,
) -> dict[str, Any]:
    """Create one field using the shared audit vocabulary."""
    return {
        'value': value, 'source': source, 'asOf': as_of, 'session': 'research',
        'reference': reference, 'scope': scope, 'benchmarkId': benchmark_id,
        'horizon': horizon, 'actualOrAssumption': kind, 'methodVersion': method,
        'confidence': confidence, 'quality': quality, 'stale': bool(stale),
        'pointInTimeAudited': bool(point_in_time_audited),
        'uncertainty': uncertainty,
    }


def _fingerprint(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return 'sha256:' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


def tsmc_guidance_reliability() -> dict[str, Any]:
    rows = []
    at_or_above_high = upper_half = 0
    for quarter, low, high, actual in TSMC_GUIDANCE_HISTORY:
        midpoint = (low + high) / 2.0
        at_or_above_high += int(actual >= high - 1e-9)
        upper_half += int(actual >= midpoint)
        rows.append({
            'quarter': quarter, 'guidanceLowUsdBn': low, 'guidanceHighUsdBn': high,
            'actualUsdBn': actual, 'atOrAboveHigh': actual >= high - 1e-9,
            'inUpperHalf': actual >= midpoint,
        })
    total = len(rows)
    return {
        'observations': total,
        'atOrAboveHighCount': at_or_above_high,
        'atOrAboveHighRatePct': round(at_or_above_high / total * 100.0, 1),
        'upperHalfCount': upper_half,
        'upperHalfRatePct': round(upper_half / total * 100.0, 1),
        'rows': rows,
        'interpretation': '歷史執行力提高近季情境可信度，但不把遠期成長、匯率或估值假設視為必然。',
    }


def tsmc_eps_evidence() -> dict[str, Any]:
    actual = [r for r in TSMC_EPS_PATH if r['kind'] == 'official_actual']
    guidance = [r for r in TSMC_EPS_PATH if r['kind'] == 'guidance_derived']
    model = [r for r in TSMC_EPS_PATH if r['kind'] == 'model_estimate']
    eps_base = sum(float(r['eps']) for r in TSMC_EPS_PATH)
    return {
        'rows': [dict(row) for row in TSMC_EPS_PATH],
        'actualQuarters': len(actual),
        'guidanceDerivedQuarters': len(guidance),
        'modelQuarters': len(model),
        'epsLow': None,
        'epsBase': round(eps_base, 2),
        'epsHigh': None,
        'asOf': '2026-08-14',
        'quality': 'mixed_actual_guidance_model',
        'assumptionFingerprint': _fingerprint(TSMC_EPS_PATH),
        'actionAuthority': 'research_only',
        'warning': 'Q3 為財測推導、Q4 為模型值；缺官方上下界轉 EPS 完整參數時不偽造信賴區間。',
    }


def _benchmark_scenarios(benchmark_id: str, assumptions: dict[str, Any]) -> dict[str, Any]:
    cfg = BENCHMARKS[benchmark_id]
    weight = cfg['tsmcWeightPct'] / 100.0
    price = _number(assumptions.get('tsmcPrice'))
    forward_eps = _number(assumptions.get('tsmcForwardEps'))
    payout = (_number(assumptions.get('payoutRatioPct')) or 0.0) / 100.0
    other_yield = (_number(assumptions.get('otherDividendYieldPct')) or 0.0) / 100.0
    years = _number(assumptions.get('convergenceYears'))
    forward_pe = price / forward_eps if price and forward_eps and forward_eps > 0 else None
    out: dict[str, Any] = {}
    for name, scenario in SCENARIOS.items():
        earnings = weight * scenario['tsmcGrowthPct'] + (1.0 - weight) * scenario['otherGrowthPct']
        tsmc_yield = payout / forward_pe if forward_pe and forward_pe > 0 else None
        index_yield = (weight * tsmc_yield + (1.0 - weight) * other_yield) if tsmc_yield is not None else None
        valuation_tsmc = (
            (scenario['fairPe'] / forward_pe) ** (1.0 / years) - 1.0
            if forward_pe and years and years > 0 and scenario['fairPe'] > 0 else None
        )
        valuation_index = weight * valuation_tsmc if valuation_tsmc is not None else None
        additive = (
            earnings / 100.0 + index_yield + valuation_index
            if index_yield is not None and valuation_index is not None else None
        )
        multiplicative = (
            (1.0 + earnings / 100.0) * (1.0 + index_yield) * (1.0 + valuation_index) - 1.0
            if index_yield is not None and valuation_index is not None else None
        )
        out[name] = {
            **scenario,
            'benchmarkEarningsGrowthPct': round(earnings, 3),
            'forwardPe': round(forward_pe, 3) if forward_pe is not None else None,
            'benchmarkDividendYieldPct': round(index_yield * 100.0, 3) if index_yield is not None else None,
            'valuationEffectPct': round(valuation_index * 100.0, 3) if valuation_index is not None else None,
            'expectedGeometricReturnPct': round(additive * 100.0, 3) if additive is not None else None,
            'multiplicativeSensitivityPct': round(multiplicative * 100.0, 3) if multiplicative is not None else None,
            'approximationDeltaPctPoint': (
                round((multiplicative - additive) * 100.0, 3)
                if additive is not None and multiplicative is not None else None
            ),
            'kind': 'model_scenario',
        }
    return out


def _annualized_log_vol(values: list[float], periods: int | None = None) -> float | None:
    sample = values[-periods:] if periods else values
    if len(sample) < 3:
        return None
    returns = [math.log(sample[i] / sample[i - 1]) for i in range(1, len(sample))
               if sample[i] > 0 and sample[i - 1] > 0]
    if len(returns) < 2:
        return None
    return statistics.stdev(returns) * math.sqrt(252.0) * 100.0


def _downside_log_vol(values: list[float], periods: int = 21) -> float | None:
    sample = values[-periods:]
    if len(sample) < 3:
        return None
    returns = [math.log(sample[i] / sample[i - 1]) for i in range(1, len(sample))
               if sample[i] > 0 and sample[i - 1] > 0]
    downside = [min(0.0, value) for value in returns]
    if len(downside) < 2:
        return None
    return math.sqrt(sum(x * x for x in downside) / (len(downside) - 1)) * math.sqrt(252.0) * 100.0


def _rolling_three_year_vol_median(values: list[float], window: int = 756) -> float | None:
    if len(values) < window + 1:
        return None
    vols = []
    for end in range(window + 1, len(values) + 1, 21):
        value = _annualized_log_vol(values[end - window - 1:end])
        if value is not None:
            vols.append(value)
    return statistics.median(vols) if vols else None


def _rows_to_values(rows: list[Any], preferred: tuple[str, ...]) -> tuple[list[float], str | None]:
    rows = rows or []
    if rows and all(isinstance(row, dict) for row in rows):
        for key in preferred:
            values = [_number(row.get(key)) for row in rows]
            valid = [value for value in values if value is not None and value > 0]
            if len(valid) >= 3:
                return valid, key
        return [], None
    values = [
        _number(row[-1]) for row in rows
        if isinstance(row, (list, tuple)) and len(row) >= 2
    ]
    return [value for value in values if value is not None and value > 0], 'close'


def _benchmark_volatility(benchmark_id: str, contract: dict | None) -> dict[str, Any]:
    contract = contract or {}
    rows = contract.get('rows') or []
    values, series_key = _rows_to_values(
        rows, ('totalReturnIndex', 'total_return', 'priceIndex', 'close', 'value'))
    as_of = contract.get('asOf')
    source = contract.get('source') or 'benchmark-series-unavailable'
    quality = contract.get('quality') or ('insufficient' if not values else 'partial_scope')
    state = _downside_log_vol(values, 21)
    rv252 = _annualized_log_vol(values, 253)
    long_run = _rolling_three_year_vol_median(values)
    candidates = [x for x in (rv252, long_run) if x is not None]
    horizon = max(candidates) if candidates else None
    ratio = state / horizon if state is not None and horizon and horizon > 0 else None
    insufficient = len(values) < 253 or horizon is None
    return {
        'benchmarkId': benchmark_id,
        'status': 'insufficient' if insufficient else ('ready' if len(values) >= 757 else 'partial'),
        'seriesKey': series_key,
        'sampleDays': len(values),
        'stateDownside20AnnualPct': _field(
            round(state, 2) if state is not None else None, source=source, as_of=as_of,
            reference='negative log-return semideviation, latest 20 sessions', scope=benchmark_id,
            benchmark_id=benchmark_id, horizon='state_20_sessions', kind='derived',
            method='downside_log_semideviation_v1', confidence='medium', quality=quality,
            point_in_time_audited=bool(contract.get('pointInTimeAudited'))),
        'realized252AnnualPct': _field(
            round(rv252, 2) if rv252 is not None else None, source=source, as_of=as_of,
            reference='latest 252-session annualized log-return volatility', scope=benchmark_id,
            benchmark_id=benchmark_id, horizon='252_sessions', kind='derived',
            method='log_return_rv252_v1', confidence='medium', quality=quality,
            point_in_time_audited=bool(contract.get('pointInTimeAudited'))),
        'longRunMedianAnnualPct': _field(
            round(long_run, 2) if long_run is not None else None, source=source, as_of=as_of,
            reference='median of 756-session rolling annualized volatility, sampled monthly', scope=benchmark_id,
            benchmark_id=benchmark_id, horizon='rolling_3_year', kind='derived',
            method='rolling_756_log_vol_median_v1', confidence='low' if long_run is None else 'medium',
            quality=quality, point_in_time_audited=bool(contract.get('pointInTimeAudited'))),
        'horizonForecastAnnualPct': _field(
            round(horizon, 2) if horizon is not None else None, source=source, as_of=as_of,
            reference='conservative ST proxy=max(RV252, rolling 3-year volatility median); not the author 52-week forecast',
            scope=benchmark_id, benchmark_id=benchmark_id, horizon='12_month_research', kind='derived',
            method=VOL_METHOD_VERSION, confidence='low' if insufficient else 'medium', quality=quality,
            point_in_time_audited=bool(contract.get('pointInTimeAudited')),
            uncertainty='The article 52-week mean-reversion coefficients are unpublished; ST uses a transparent proxy.'),
        'stateToForecastRatio': round(ratio, 3) if ratio is not None else None,
        'roles': {
            'state': 'weekly monitor only; cannot mutate the monthly core',
            'forecast': 'slow benchmark-specific denominator for variance drag and Kelly research',
        },
    }


def _taiex_volatility(key_levels: dict | None) -> dict[str, Any]:
    key_levels = key_levels or {}
    vol = key_levels.get('volatility') or {}
    state = _number(vol.get('stateDownside20AnnualPct'))
    horizon = _number(vol.get('horizonForecastAnnualPct'))
    if horizon is None:
        horizon = _number(vol.get('realized60AnnualPct'))
    if horizon is None:
        horizon = _number(vol.get('realized20AnnualPct'))
    ratio = state / horizon if state is not None and horizon and horizon > 0 else None
    as_of = key_levels.get('referenceDate') or key_levels.get('asOf')
    source = key_levels.get('source') or 'local-daily-series'
    stale = bool((key_levels.get('quality') or {}).get('stale'))
    quality = 'stale' if stale else ('derived' if horizon is not None else 'insufficient')
    return {
        'benchmarkId': 'TAIEX',
        'status': 'insufficient' if horizon is None else ('stale' if stale else 'ready'),
        'seriesKey': 'close',
        'sampleDays': (key_levels.get('sample') or {}).get('rows'),
        'stateDownside20AnnualPct': _field(
            round(state, 2) if state is not None else None, source=source, as_of=as_of,
            reference='negative-return semideviation, latest 20 sessions', scope='TAIEX',
            benchmark_id='TAIEX', horizon='state_20_sessions', kind='derived',
            method='downside_semideviation_v1', confidence='medium', stale=stale, quality=quality),
        'realized252AnnualPct': _field(
            None, source=source, as_of=as_of, reference='not supplied by key-level contract', scope='TAIEX',
            benchmark_id='TAIEX', horizon='252_sessions', kind='derived', method='unavailable',
            confidence='low', stale=stale, quality='insufficient'),
        'longRunMedianAnnualPct': _field(
            None, source=source, as_of=as_of, reference='not supplied by key-level contract', scope='TAIEX',
            benchmark_id='TAIEX', horizon='rolling_3_year', kind='derived', method='unavailable',
            confidence='low', stale=stale, quality='insufficient'),
        'horizonForecastAnnualPct': _field(
            round(horizon, 2) if horizon is not None else None, source=source, as_of=as_of,
            reference='ST key-level long-horizon proxy; benchmark-specific TAIEX only', scope='TAIEX',
            benchmark_id='TAIEX', horizon='12_month_research', kind='derived',
            method='rv60_longrun_blend_v1', confidence='low' if stale else 'medium',
            stale=stale, quality=quality,
            uncertainty='This proxy must not be used for FTSE Taiwan 50 products.'),
        'stateToForecastRatio': round(ratio, 3) if ratio is not None else None,
        'roles': {
            'state': 'weekly monitor only; cannot mutate the monthly core',
            'forecast': 'slow TAIEX-only denominator for variance drag and Kelly research',
        },
    }


def _risk_mode(risk_profile: dict | None) -> str | None:
    if not isinstance(risk_profile, dict):
        return None
    lev = _number(risk_profile.get('maxLeverage'))
    if lev is None:
        return None
    if lev <= 1.0:
        return 'conservative'
    if lev <= 1.5:
        return 'moderate'
    return 'aggressive'


def _mode_ceilings(
    expected_base_pct: float | None, forecast_vol_pct: float | None,
    incremental_cost_pct: float | None, edge_band_crosses_zero: bool,
) -> dict[str, Any]:
    """Monthly core ceilings; weekly observations are intentionally absent."""
    configs = {
        'conservative': {'riskFraction': 0.55, 'hardCapPct': 100.0},
        'moderate': {'riskFraction': 0.80, 'hardCapPct': 150.0},
        'aggressive': {'riskFraction': 1.00, 'hardCapPct': 200.0},
    }
    sigma = forecast_vol_pct / 100.0 if forecast_vol_pct is not None else None
    expected = expected_base_pct / 100.0 if expected_base_pct is not None else None
    cost = incremental_cost_pct / 100.0 if incremental_cost_pct is not None else None
    lambda_star = None
    if sigma is not None and sigma > 0 and expected is not None and cost is not None:
        lambda_star = max(1.0, 0.5 + (expected - cost) / (sigma * sigma))
    rows = {}
    for name, cfg in configs.items():
        raw_pct = lambda_star * cfg['riskFraction'] * 100.0 if lambda_star is not None else None
        caps = [cfg['hardCapPct']]
        if edge_band_crosses_zero:
            caps.append(100.0)
        ceiling = min([raw_pct, *caps]) if raw_pct is not None else None
        rows[name] = {
            **cfg,
            'costAdjustedKellyPct': round(lambda_star * 100.0, 1) if lambda_star is not None else None,
            'researchCeilingPct': round(max(0.0, ceiling), 1) if ceiling is not None else None,
            'authority': 'monthly_core_research_only',
            'weeklyHealthApplied': False,
            'formula': 'lambda*=0.5+(g-c_incremental)/sigma^2; risk fraction and hard policy cap',
        }
    return rows


def portfolio_lookthrough(stocks: dict | None) -> dict[str, Any] | None:
    """Translate surface weights into daily-leverage and TSMC economic exposure."""
    if not isinstance(stocks, dict) or not stocks:
        return None
    effective_gross = tsmc_exposure = tech_exposure = 0.0
    tech_coverage = 0.0
    rows = []
    for raw_symbol, raw in stocks.items():
        symbol = str(raw_symbol).upper().replace('.TW', '').replace('.TWO', '')
        surface = _number((raw or {}).get('weight')) or 0.0
        product = PRODUCTS.get(symbol, {})
        multiple = _number(product.get('leverageMultiple')) or 1.0
        effective = surface * multiple
        tsmc_weight = _number(product.get('tsmcWeightPct'))
        tech_weight = _number(product.get('technologyWeightPct'))
        effective_gross += effective
        if tsmc_weight is not None:
            tsmc_exposure += effective * tsmc_weight / 100.0
        if tech_weight is not None:
            tech_exposure += effective * tech_weight / 100.0
            tech_coverage += effective
        rows.append({
            'symbol': symbol, 'surfaceWeightPct': round(surface, 2),
            'leverageMultiple': multiple, 'effectiveGrossPct': round(effective, 2),
            'tsmcEconomicExposurePct': round(effective * tsmc_weight / 100.0, 2) if tsmc_weight is not None else None,
            'technologyEconomicExposurePct': round(effective * tech_weight / 100.0, 2) if tech_weight is not None else None,
            'benchmark': product.get('benchmark') or 'UNKNOWN', 'role': product.get('role') or 'unmapped',
            'resetFrequency': product.get('resetFrequency'), 'liabilityType': product.get('liabilityType'),
            'diversificationCredit': bool(product.get('diversificationCredit', True)),
            'hypothesisId': product.get('hypothesisId'),
        })
    leveraged = [r for r in rows if r['leverageMultiple'] > 1]
    return {
        'effectiveGrossExposurePct': round(effective_gross, 2),
        'tsmcEconomicExposurePct': round(tsmc_exposure, 2),
        'technologyEconomicExposurePct': round(tech_exposure, 2) if tech_coverage else None,
        'technologyCoverageEffectiveGrossPct': round(tech_coverage, 2),
        'rows': rows,
        'leveragedOverlap': len(leveraged) >= 2,
        'diversificationCredit': False if len(leveraged) >= 2 else None,
        'overlapNote': (
            '00631L 與 00685L 均為台股每日正二，底層高度重疊；並列持有視為集中曝險，不視為分散。'
            if len(leveraged) >= 2 else None
        ),
    }


def _actual_holding_symbols(portfolio: dict | None) -> set[str]:
    if not isinstance(portfolio, dict) or portfolio.get('kind') != 'actual':
        return set()
    if portfolio.get('available') is False:
        return set()
    stocks = portfolio.get('stocks') or {}
    if not isinstance(stocks, dict):
        return set()
    symbols: set[str] = set()
    for raw_symbol, row in stocks.items():
        symbol = str(raw_symbol).upper().replace('.TW', '').replace('.TWO', '')
        if (_number((row or {}).get('weight')) or 0.0) > 0:
            symbols.add(symbol)
    return symbols


def _holding_hypotheses(actual_symbols: set[str]) -> list[dict[str, Any]]:
    hypotheses: list[dict[str, Any]] = []
    if '00685L' in actual_symbols:
        hypotheses.append({
            'id': 'POST_SPLIT_LIQUIDITY_MOMENTUM',
            'symbol': '00685L', 'status': 'UNVERIFIED',
            'scope': 'actual_portfolio_only', 'trigger': 'positive_weight_holding',
            'claim': '拆股後單價降低，可能改善參與度與資金動能。',
            'modelTreatment': '只作交易／流動性觀察，不增加分散、基本面或期望報酬分數。',
            'confirmationMetrics': [
                '拆股前後各20交易日成交值中位數', '拆股前後各20交易日成交量中位數',
                '週轉率', '買賣價差與折溢價',
            ],
            'confirmationRule': '成交值與週轉率同步顯著改善，且價差／折溢價未惡化，才升級為 SUPPORTED。',
            'invalidationRule': '只有名目股價下降，成交值與週轉率未改善或價差惡化。',
            'diversificationCredit': False,
        })
    return hypotheses


def _selected_benchmark(actual_symbols: set[str]) -> tuple[str, str]:
    mapped = {str(PRODUCTS[s]['benchmark']) for s in actual_symbols
              if s in PRODUCTS and PRODUCTS[s].get('benchmark') in BENCHMARKS}
    if len(mapped) == 1:
        return next(iter(mapped)), 'actual_portfolio_underlying'
    if len(mapped) > 1:
        return 'MIXED', 'actual_portfolio_multiple_underlyings'
    return 'FTSE_TAIWAN_50', 'default_research_benchmark_for_0050_00631L'


def _weekly_health(
    volatility: dict[str, Any], margin_state: dict | None,
    research_inputs: dict | None,
) -> dict[str, Any]:
    ratio = _number(volatility.get('stateToForecastRatio'))
    percentile = _number((margin_state or {}).get('percentile52w'))
    direction = str((margin_state or {}).get('direction') or 'unknown')
    anchor = _number(CORE_ASSUMPTIONS.get('tsmcPrice'))
    current = _number((research_inputs or {}).get('currentTsmcPrice'))
    anchor_move = (current / anchor - 1.0) * 100.0 if current and anchor and anchor > 0 else None
    flags = []
    if ratio is not None and ratio > 1.20:
        flags.append('short_vol_elevated')
    if percentile is not None and percentile >= 80:
        flags.append('margin_elevated')
        if direction == 'rising':
            flags.append('margin_elevated_and_rising')
    if anchor_move is not None and abs(anchor_move) >= 15.0:
        flags.append('core_anchor_move')
    review_required = 'core_anchor_move' in flags
    return {
        'status': 'monitor_only',
        'headline': '需要複查' if review_required else ('壓力偏高，維持監控' if flags else '監控正常'),
        'flags': flags,
        'reviewRequired': review_required,
        'pressureElevated': bool(flags),
        'stateToForecastRatio': round(ratio, 3) if ratio is not None else None,
        'marginPercentile52w': round(percentile, 1) if percentile is not None else None,
        'marginDirection': direction,
        'coreAnchorMovePct': round(anchor_move, 2) if anchor_move is not None else None,
        'thresholds': {'stateToForecastRatio': 1.20, 'marginPercentile52w': 80, 'coreAnchorMoveAbsPct': 15},
        'thresholdKind': 'heuristic_health_grade',
        'actionAuthority': 'monitor_only',
        'coreMutationAllowed': False,
        'mayIncreaseExposure': False,
        'mayAddRestrictions': True,
        'externalValidationStatus': EXTERNAL_VALIDATION['status'],
    }


def _level_map(contract: dict | None, preferred: tuple[str, ...]) -> dict[str, float]:
    out: dict[str, float] = {}
    rows = [row for row in ((contract or {}).get('rows') or []) if isinstance(row, dict)]
    selected_key = next((
        key for key in preferred
        if len([row for row in rows if (_number(row.get(key)) or 0) > 0]) >= 3
    ), None)
    if selected_key is None:
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        iso = str(row.get('date') or '')[:10]
        if len(iso) != 10:
            continue
        value = _number(row.get(selected_key))
        if value is not None and value > 0:
            out[iso] = value
    return out


def _return_map(levels: dict[str, float]) -> dict[str, float]:
    out: dict[str, float] = {}
    dates = sorted(levels)
    for previous, current in zip(dates, dates[1:]):
        if levels[previous] > 0 and levels[current] > 0:
            out[current] = levels[current] / levels[previous] - 1.0
    return out


def _sample_covariance(left: list[float], right: list[float]) -> float | None:
    if len(left) != len(right) or len(left) < 2:
        return None
    left_mean = statistics.mean(left)
    right_mean = statistics.mean(right)
    return sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right)) / (len(left) - 1)


def _daily_leverage_metrics(
    product_contract: dict | None,
    underlying_contract: dict | None,
    target_leverage: float,
) -> dict[str, Any]:
    product_levels = _level_map(product_contract, ('close', 'value'))
    underlying_levels = _level_map(
        underlying_contract, ('totalReturnIndex', 'total_return', 'priceIndex', 'close', 'value'))
    product_returns = _return_map(product_levels)
    underlying_returns = _return_map(underlying_levels)
    common = sorted(set(product_returns) & set(underlying_returns))[-252:]
    product_sample = [product_returns[key] for key in common]
    underlying_sample = [underlying_returns[key] for key in common]
    if len(common) < 60:
        return {
            'rollingBeta': None, 'trackingResidualAnnualPct': None,
            'empiricalCostGapAnnualPct': None, 'sampleDays': len(common),
            'quality': 'insufficient_aligned_history',
        }
    # Corporate actions must be adjusted explicitly; never interpret a split
    # discontinuity as leverage or tracking behavior.
    if any(abs(value) > 0.60 for value in product_sample) or any(abs(value) > 0.30 for value in underlying_sample):
        return {
            'rollingBeta': None, 'trackingResidualAnnualPct': None,
            'empiricalCostGapAnnualPct': None, 'sampleDays': len(common),
            'quality': 'corporate_action_or_bad_tick_detected',
        }
    variance = statistics.variance(underlying_sample)
    covariance = _sample_covariance(product_sample, underlying_sample)
    beta = covariance / variance if covariance is not None and variance > 0 else None
    residual = [p - target_leverage * u for p, u in zip(product_sample, underlying_sample)]
    residual_vol = statistics.stdev(residual) * math.sqrt(252.0) * 100.0 if len(residual) > 1 else None
    total_return_product = (product_contract or {}).get('returnBasis') == 'total_return'
    cost_gaps = [
        math.log1p(target_leverage * u) - math.log1p(p)
        for p, u in zip(product_sample, underlying_sample)
        if total_return_product and 1.0 + target_leverage * u > 0 and 1.0 + p > 0
    ]
    cost_gap = statistics.mean(cost_gaps) * 252.0 * 100.0 if cost_gaps else None
    return {
        'rollingBeta': round(beta, 3) if beta is not None else None,
        'trackingResidualAnnualPct': round(residual_vol, 3) if residual_vol is not None else None,
        'empiricalCostGapAnnualPct': round(cost_gap, 3) if cost_gap is not None else None,
        'sampleDays': len(common),
        'sampleStart': common[0] if common else None,
        'sampleEnd': common[-1] if common else None,
        'quality': (
            ('ready' if len(common) >= 120 else 'partial_scope')
            if total_return_product else 'tracking_only_unadjusted_product'
        ),
    }


def _product_mechanics(actual_symbols: set[str], benchmark_data: dict[str, Any] | None) -> dict[str, Any]:
    visible = {'0050', '00631L'} | actual_symbols
    product_contracts = (benchmark_data or {}).get('PRODUCTS') or {}
    rows = []
    for symbol in sorted(visible):
        product = PRODUCTS.get(symbol)
        if not product or product.get('benchmark') not in BENCHMARKS:
            continue
        metrics = _daily_leverage_metrics(
            product_contracts.get(symbol),
            (benchmark_data or {}).get(product.get('benchmark')),
            float(product.get('leverageMultiple') or 1.0),
        )
        rows.append({
            'symbol': symbol,
            'underlyingBenchmarkId': product.get('benchmark'),
            'targetLeverage': product.get('leverageMultiple'),
            'resetFrequency': product.get('resetFrequency'),
            'liabilityType': product.get('liabilityType'),
            'holderMarginCallRisk': product.get('holderMarginCallRisk'),
            'incrementalCostPct': product.get('incrementalCostPct'),
            'costAsOf': product.get('costAsOf'),
            'costQuality': product.get('costQuality'),
            **metrics,
            'methodVersion': PRODUCT_METHOD_VERSION,
            'warning': (
                '產品序列為未還原收盤；可觀察 beta／殘差，但成本缺口必須等 total-return 序列。'
                if metrics.get('quality') == 'tracking_only_unadjusted_product'
                else (None if metrics.get('quality') in ('ready', 'partial_scope')
                      else '未取得可用同基準日報酬序列前，不推定實際 beta、追蹤殘差或成本缺口。')
            ),
        })
    return {
        'rows': rows,
        'formula': {
            'rollingBeta': 'Cov(product returns, underlying returns) / Var(underlying returns)',
            'trackingResidual': 'Std(product return - targetLeverage * underlying return) * sqrt(252)',
            'empiricalCostGap': '252 * mean(log(1+lambda*r_underlying)-log(1+r_product))',
        },
        'actionAuthority': 'research_only',
        'pledgedLeverage': {
            'status': 'not_configured',
            'requiredInputs': ['borrowRate', 'maintenanceRatio', 'creditLimit', 'rebalanceRule'],
            'warning': '借款／質押條件屬使用者與券商契約，不使用全域預設。',
        },
    }


def _temperature_band(score: float | None) -> tuple[str, str]:
    if score is None:
        return 'unknown', '資料不足'
    if score < 35:
        return 'cool', '偏低'
    if score < 60:
        return 'steady', '中性'
    if score < 80:
        return 'watch', '偏高'
    return 'hot', '過熱'


def _temperature_component(key: str, label: str, score: float | None, detail: str) -> dict[str, Any]:
    bounded = max(0.0, min(100.0, score)) if score is not None else None
    tone, state = _temperature_band(bounded)
    return {
        'key': key, 'label': label,
        'score': round(bounded) if bounded is not None else None,
        'tone': tone, 'state': state, 'detail': detail,
    }


def _exposure_temperature(
    weekly_health: dict[str, Any], benchmark_rows: dict[str, Any],
    lookthrough: dict | None, actual_symbols: set[str], selected_benchmark: str,
) -> dict[str, Any]:
    ratio = _number(weekly_health.get('stateToForecastRatio'))
    volatility_score = max(0.0, min(100.0, (ratio - 0.60) / 0.80 * 100.0)) if ratio is not None else None
    components = [_temperature_component(
        'volatility', '波動壓力', volatility_score,
        f'短期／中長期 {ratio:.2f}x' if ratio is not None else '缺少同基準波動比較')]

    margin_pct = _number(weekly_health.get('marginPercentile52w'))
    components.append(_temperature_component(
        'margin', '融資擁擠', margin_pct,
        f'52週 {margin_pct:.0f} 百分位' if margin_pct is not None else '本機融資歷史不足'))

    status_scores = {
        'EDGE_POSITIVE_RESEARCH': 40.0, 'RESEARCH_DATA_INCOMPLETE': 55.0,
        'INDETERMINATE': 70.0, 'NO_2X_EDGE': 85.0,
    }
    status_labels = {
        'EDGE_POSITIVE_RESEARCH': '效率差為正（研究）',
        'RESEARCH_DATA_INCOMPLETE': '研究資料未完整',
        'INDETERMINATE': '情境跨零', 'NO_2X_EDGE': '效率差不為正',
    }
    relevant_rows = (
        list(benchmark_rows.values()) if selected_benchmark == 'MIXED'
        else [benchmark_rows.get(selected_benchmark) or {}]
    )
    statuses = [str((row or {}).get('status') or '') for row in relevant_rows]
    leverage_status = max(statuses, key=lambda s: status_scores.get(s, 50.0)) if statuses else ''
    components.append(_temperature_component(
        'leverage', '槓桿適配', status_scores.get(leverage_status),
        status_labels.get(leverage_status, '缺少正二比較條件')))

    gross = _number((lookthrough or {}).get('effectiveGrossExposurePct')) if actual_symbols else None
    overlap = bool((lookthrough or {}).get('leveragedOverlap')) if gross is not None else False
    portfolio_score = max(0.0, min(100.0, (gross - 75.0) / 125.0 * 100.0)) if gross is not None else None
    if portfolio_score is not None and overlap:
        portfolio_score = max(portfolio_score, 85.0)
    portfolio_detail = '未載入實際持倉'
    if gross is not None:
        portfolio_detail = f'穿透 {gross:.1f}%' + (' · 集中重疊' if overlap else '')
    components.append(_temperature_component('portfolio', '投組曝險', portfolio_score, portfolio_detail))

    weights = {'volatility': 0.30, 'margin': 0.20, 'leverage': 0.20, 'portfolio': 0.30}
    available = [row for row in components if row['score'] is not None]
    weight_sum = sum(weights[row['key']] for row in available)
    weighted = (sum(row['score'] * weights[row['key']] for row in available) / weight_sum
                if weight_sum else None)
    if weighted is not None:
        weighted = max(weighted, max(row['score'] for row in available) * 0.85)
    tone, state = _temperature_band(weighted)
    return {
        'score': round(weighted) if weighted is not None else None,
        'tone': tone, 'state': state, 'components': components,
        'interpretation': '分數越高代表曝險壓力越大、約束應越嚴格；不代表市場漲跌方向。',
        'formula': '可得燈號加權平均；單一最高風險至少保留 85%，避免被平均稀釋。',
    }


def build_exposure_lab(
    *, key_levels: dict | None = None,
    benchmark_data: dict[str, Any] | None = None,
    margin_state: dict | None = None,
    risk_profile: dict | None = None,
    portfolio: dict | None = None,
    research_inputs: dict | None = None,
    as_of: str | None = None,
) -> dict[str, Any]:
    """Build the v3 research contract without mutating any external state."""
    core_overrides = ((research_inputs or {}).get('coreAssumptions')
                      if isinstance((research_inputs or {}).get('coreAssumptions'), dict) else {})
    assumptions = {**CORE_ASSUMPTIONS, **core_overrides}
    assumption_fingerprint = _fingerprint({
        'core': assumptions, 'scenarios': SCENARIOS,
        'benchmarks': BENCHMARKS, 'method': CORE_METHOD_VERSION,
    })
    actual_symbols = _actual_holding_symbols(portfolio)
    selected_benchmark, selection_reason = _selected_benchmark(actual_symbols)

    volatility_by_benchmark = {
        'FTSE_TAIWAN_50': _benchmark_volatility(
            'FTSE_TAIWAN_50', (benchmark_data or {}).get('FTSE_TAIWAN_50')),
        'TAIEX': _taiex_volatility(key_levels),
    }
    benchmark_rows: dict[str, Any] = {}
    cost_pct = _number(assumptions.get('incremental2xCostPct'))
    for benchmark_id, cfg in BENCHMARKS.items():
        scenarios = _benchmark_scenarios(benchmark_id, assumptions)
        vol_contract = volatility_by_benchmark[benchmark_id]
        forecast = _number((vol_contract.get('horizonForecastAnnualPct') or {}).get('value'))
        threshold = ((forecast / 100.0) ** 2 * 100.0 + cost_pct
                     if forecast is not None and cost_pct is not None else None)
        edges = {}
        for scenario_id, row in scenarios.items():
            expected = _number(row.get('expectedGeometricReturnPct'))
            edges[scenario_id] = round(expected - threshold, 3) if expected is not None and threshold is not None else None
            row['leveragedCarryEdge2xPctPoint'] = edges[scenario_id]
        finite_edges = [v for v in edges.values() if v is not None]
        crosses_zero = bool(finite_edges and min(finite_edges) <= 0 <= max(finite_edges))
        base_edge = edges.get('base')
        if forecast is None or base_edge is None or len(finite_edges) != len(SCENARIOS):
            status = 'RESEARCH_DATA_INCOMPLETE'
        elif crosses_zero:
            status = 'INDETERMINATE'
        elif base_edge <= 0:
            status = 'NO_2X_EDGE'
        else:
            status = 'EDGE_POSITIVE_RESEARCH'
        base_expected = _number((scenarios.get('base') or {}).get('expectedGeometricReturnPct'))
        ceilings = _mode_ceilings(
            base_expected, forecast, cost_pct,
            crosses_zero or (base_edge is not None and base_edge <= 0))
        benchmark_rows[benchmark_id] = {
            'benchmarkId': benchmark_id, 'label': cfg['label'],
            'tsmcWeightPct': cfg['tsmcWeightPct'], 'weightAsOf': cfg['weightAsOf'],
            'weightSource': cfg['weightSource'], 'weightQuality': cfg['weightQuality'],
            'pointInTimeAudited': cfg['pointInTimeAudited'],
            'scenarios': scenarios,
            'daily2xOutperformanceThresholdPct': round(threshold, 3) if threshold is not None else None,
            'baseEdgeVs2xThresholdPct': base_edge,
            'leveragedCarryEdge2x': {
                'bearPctPoint': edges.get('bear'), 'basePctPoint': base_edge,
                'bullPctPoint': edges.get('bull'), 'crossesZero': crosses_zero,
                'status': status, 'unit': 'percentage_points_per_year',
                'actionAuthority': 'research_only',
            },
            'status': status, 'ceilings': ceilings,
            'volatility': vol_contract,
            'formula': 'M2=g_proxy-(sigma_horizon^2+c_incremental)',
        }

    selected_rows = (
        [benchmark_rows[k] for k in BENCHMARKS]
        if selected_benchmark == 'MIXED' else [benchmark_rows[selected_benchmark]]
    )
    mode = _risk_mode(risk_profile)
    selected_candidates = [
        row['ceilings'][mode]['researchCeilingPct'] for row in selected_rows
        if mode and row['ceilings'][mode]['researchCeilingPct'] is not None
    ]
    selected_ceiling = min(selected_candidates) if selected_candidates else None
    if selected_benchmark == 'MIXED':
        available_ratios = [
            _number((row or {}).get('stateToForecastRatio'))
            for row in volatility_by_benchmark.values()
        ]
        available_ratios = [value for value in available_ratios if value is not None]
        selected_volatility = {
            'benchmarkId': 'MIXED', 'status': 'mixed_no_aggregate',
            'stateDownside20AnnualPct': _field(
                None, source='multiple benchmark contracts', as_of=as_of,
                reference='mixed portfolio: no synthetic level series is inferred', scope='MIXED',
                benchmark_id='MIXED', horizon='state_20_sessions', kind='derived',
                method='suppressed_mixed_benchmark', confidence='low', quality='insufficient'),
            'horizonForecastAnnualPct': _field(
                None, source='multiple benchmark contracts', as_of=as_of,
                reference='read each underlying benchmark separately', scope='MIXED',
                benchmark_id='MIXED', horizon='12_month_research', kind='derived',
                method='suppressed_mixed_benchmark', confidence='low', quality='insufficient'),
            'stateToForecastRatio': max(available_ratios) if available_ratios else None,
            'roles': {
                'state': 'worst available component ratio for monitor-only flags',
                'forecast': 'suppressed until an explicit portfolio-weighted series exists',
            },
        }
    else:
        selected_volatility = volatility_by_benchmark.get(selected_benchmark) or {}
    weekly_health = _weekly_health(selected_volatility, margin_state, research_inputs)

    lookthrough = None
    if isinstance(portfolio, dict):
        lookthrough = portfolio.get('lookThrough') or portfolio_lookthrough(portfolio.get('stocks'))
    hypotheses = _holding_hypotheses(actual_symbols)
    visible_products = {
        symbol: product for symbol, product in PRODUCTS.items()
        if symbol != '00685L' or symbol in actual_symbols
    }
    warnings = [
        '0050 是大型權值／科技高度集中的指數工具，不標示為純 AI ETF。',
        '每日正二長期結果受路徑、波動耗損、成本、重設與追蹤誤差影響。',
        '研究上限不是配置目標；Risk Profile 不完整時不輸出最終曝險範圍。',
        '週度波動與融資只負責監控／複查，永不直接改寫月度核心研究。',
    ]
    if {'00631L', '00685L'}.issubset(actual_symbols):
        warnings.insert(1, '實際持有的兩檔台股每日正二底層高度重疊；視為集中，不是有效分散。')
    if benchmark_rows['FTSE_TAIWAN_50']['status'] == 'RESEARCH_DATA_INCOMPLETE':
        warnings.append('臺灣50官方序列尚未形成足夠樣本；不以加權指數波動代替。')

    temperature = _exposure_temperature(
        weekly_health, benchmark_rows, lookthrough, actual_symbols, selected_benchmark)
    reliability = tsmc_guidance_reliability()
    return {
        'contractVersion': CONTRACT_VERSION, 'model': MODEL_VERSION, 'asOf': as_of,
        'shadowMode': True, 'decisionUse': 'research_ceiling_only',
        'actionAuthority': 'research_only',
        'coreResearch': {
            'asOf': assumptions.get('asOf'), 'frozenUntil': assumptions.get('frozenUntil'),
            'reviewCadence': assumptions.get('reviewCadence'),
            'assumptionReviewCadence': assumptions.get('assumptionReviewCadence'),
            'selectedBenchmarkId': selected_benchmark,
            'selectionReason': selection_reason,
            'assumptionFingerprint': assumption_fingerprint,
            'actionAuthority': 'monthly_core_research_only',
            'weeklyMutationAllowed': False,
        },
        'weeklyHealth': weekly_health,
        'externalValidation': EXTERNAL_VALIDATION,
        'fundamentalReliability': {
            'tsmcGuidanceHistory': _field(
                reliability, source='TSMC quarterly earnings releases', as_of='2026Q2',
                reference='USD revenue guidance versus reported quarterly revenue', scope='TSMC',
                horizon='2024Q1-2026Q2 sample', kind='observed', method='tsmc_guidance_score_v1',
                confidence='high', quality='official_actual', point_in_time_audited=False),
            'tsmcEpsEvidence': _field(
                tsmc_eps_evidence(), source='TSMC quarterly results + external research model', as_of='2026-08-14',
                reference='Q1/Q2 actual; Q3 guidance-derived; Q4 model estimate', scope='TSMC',
                horizon='2026_full_year', kind='mixed', method='tsmc_eps_evidence_v1',
                confidence='medium', quality='mixed_actual_guidance_model',
                uncertainty='Q3/Q4 are not official actual EPS.'),
        },
        'assumptions': {
            'core': _field(
                assumptions, source='FantasyMaya Part 2 + ST explicit sensitivity registry',
                as_of=assumptions.get('asOf'), reference='not consensus and not guaranteed return',
                scope='Taiwan equities', horizon='long_horizon_research', kind='assumption',
                method=CORE_METHOD_VERSION, confidence='low', quality='model_assumption',
                uncertainty='Growth, fair P/E, payout, other-company yield and product cost are assumptions.'),
            'scenarioSet': _field(
                SCENARIOS, source='ST sensitivity model', as_of=assumptions.get('asOf'),
                reference='bear/base/bull model scenarios; not a confidence interval', scope='Taiwan equities',
                horizon='long_horizon_research', kind='assumption', method=CORE_METHOD_VERSION,
                confidence='low', quality='model_assumption'),
            'productIncrementalCostPct': _field(
                cost_pct, source='FantasyMaya Part 3/4 external research assumption', as_of='2026-08-14',
                reference='composite incremental annual cost for daily 2x; components not independently verified',
                scope='daily 2x ETF', horizon='annualized', kind='assumption',
                method='incremental_cost_composite_v1', confidence='low', quality='external_research_assumption',
                uncertainty='Do not add empirical tracking gap to this composite without de-duplication.'),
        },
        'products': visible_products,
        'productMechanics': _product_mechanics(actual_symbols, benchmark_data),
        'benchmarks': benchmark_rows,
        'benchmarkVolatility': volatility_by_benchmark,
        'volatility': selected_volatility,
        'marginState': margin_state or {'available': False, 'reason': 'local_margin_history_unavailable'},
        'riskMode': mode,
        'selectedBenchmarkId': selected_benchmark,
        'selectedResearchCeilingPct': round(selected_ceiling, 1) if selected_ceiling is not None else None,
        'finalEligibleRange': None,
        'portfolioLookThrough': lookthrough,
        'temperature': temperature,
        'hypotheses': hypotheses,
        'warnings': warnings,
    }
