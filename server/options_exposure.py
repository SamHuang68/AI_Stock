#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Expiry-scoped TXO structure research.

The public TAIFEX chain observes contracts, prices, volume and open interest.
It does *not* reveal which side is held by a dealer.  This module therefore
keeps three layers separate:

``observed``
    Official end-of-day chain facts.
``derived``
    Black-Scholes IV/Greeks and direction-neutral OI density.
``modeled``
    Explicit signed-position scenarios and their possible gamma flips.

All calculations are stdlib-only and deterministic.  Network access is kept
at the adapter boundary so fixtures can exercise the complete model offline.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from copy import deepcopy
from datetime import date, datetime, time as dt_time, timezone
from statistics import median
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

from http_client import fetch_json


CONTRACT_VERSION = 2
MODEL_VERSION = 'st-options-structure/v2'
SCENARIO_COEFFICIENT_VERSION = 'txo-public-oi-scenarios/v1'
TXO_MULTIPLIER_NTD = 50.0
REPORT_URL = 'https://openapi.taifex.com.tw/v1/DailyMarketReportOpt'
DELTA_URL = 'https://openapi.taifex.com.tw/v1/DailyOptionsDelta'
TW_TZ = ZoneInfo('Asia/Taipei')
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(BASE_DIR, 'data', 'options_structure_cache.json')
HISTORY_PATH = os.path.join(BASE_DIR, 'data', 'options_structure_history.json')
CACHE_TTL_SEC = 15 * 60
HISTORY_LIMIT = 180

_lock = threading.RLock()
_memory_cache: dict[str, Any] = {'loaded': False, 'value': None, 'savedAt': 0.0}


def _number(value: Any) -> float | None:
    if value in (None, '', '-', '--', '—'):
        return None
    try:
        number = float(str(value).replace(',', '').replace('%', '').strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _integer(value: Any) -> int | None:
    number = _number(value)
    if number is None or number < 0:
        return None
    return int(round(number))


def _date_key(value: Any) -> str | None:
    text = str(value or '').strip()
    try:
        if len(text) >= 10 and text[4] == '-' and text[7] == '-':
            return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None
    raw = ''.join(ch for ch in text if ch.isdigit())
    if len(raw) < 8:
        return None
    raw = raw[:8]
    try:
        return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8])).isoformat()
    except ValueError:
        return None


def _call_put(value: Any) -> str | None:
    raw = str(value or '').strip().lower()
    if raw in ('c', 'call', '買權', '買進選擇權') or raw.startswith('call'):
        return 'C'
    if raw in ('p', 'put', '賣權', '賣出選擇權') or raw.startswith('put'):
        return 'P'
    return None


def normal_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def normal_cdf(x: float) -> float:
    # erfc remains stable in the tails where 1 + erf(x) loses precision.
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def _validate_bs_inputs(spot: float, strike: float, years: float, sigma: float) -> None:
    values = (spot, strike, years, sigma)
    if not all(math.isfinite(float(x)) for x in values):
        raise ValueError('Black-Scholes inputs must be finite')
    if spot <= 0 or strike <= 0 or years <= 0 or sigma <= 0:
        raise ValueError('spot, strike, years and sigma must be positive')


def black_scholes(
    spot: float,
    strike: float,
    years: float,
    risk_free_rate: float,
    dividend_yield: float,
    sigma: float,
    call_put: str,
) -> dict[str, float]:
    """Return price, delta, gamma and vega in index-point units."""
    _validate_bs_inputs(spot, strike, years, sigma)
    if not math.isfinite(risk_free_rate) or not math.isfinite(dividend_yield):
        raise ValueError('rates must be finite')
    cp = _call_put(call_put)
    if cp is None:
        raise ValueError('call_put must be C/Call or P/Put')
    root_t = math.sqrt(years)
    d1 = (math.log(spot / strike) +
          (risk_free_rate - dividend_yield + 0.5 * sigma * sigma) * years) / (sigma * root_t)
    d2 = d1 - sigma * root_t
    discount_q = math.exp(-dividend_yield * years)
    discount_r = math.exp(-risk_free_rate * years)
    if cp == 'C':
        price = spot * discount_q * normal_cdf(d1) - strike * discount_r * normal_cdf(d2)
        delta = discount_q * normal_cdf(d1)
    else:
        price = strike * discount_r * normal_cdf(-d2) - spot * discount_q * normal_cdf(-d1)
        delta = discount_q * (normal_cdf(d1) - 1.0)
    gamma = discount_q * normal_pdf(d1) / (spot * sigma * root_t)
    vega = spot * discount_q * normal_pdf(d1) * root_t
    return {
        'price': price, 'delta': delta, 'gamma': gamma, 'vega': vega,
        'd1': d1, 'd2': d2,
    }


def _arbitrage_bounds(
    spot: float,
    strike: float,
    years: float,
    risk_free_rate: float,
    dividend_yield: float,
    call_put: str,
) -> tuple[float, float]:
    discount_spot = spot * math.exp(-dividend_yield * years)
    discount_strike = strike * math.exp(-risk_free_rate * years)
    if _call_put(call_put) == 'C':
        return max(0.0, discount_spot - discount_strike), discount_spot
    return max(0.0, discount_strike - discount_spot), discount_strike


def solve_implied_volatility(
    option_price: float,
    spot: float,
    strike: float,
    years: float,
    risk_free_rate: float,
    dividend_yield: float,
    call_put: str,
    *,
    lower_sigma: float = 1e-6,
    upper_sigma: float = 5.0,
    tolerance: float = 1e-7,
) -> tuple[float | None, str | None]:
    """Robust bisection IV solver with explicit failure codes."""
    try:
        price = float(option_price)
        _validate_bs_inputs(float(spot), float(strike), float(years), lower_sigma)
    except (TypeError, ValueError):
        return None, 'INVALID_INPUT'
    if not math.isfinite(price) or price < 0:
        return None, 'INVALID_PRICE'
    cp = _call_put(call_put)
    if cp is None:
        return None, 'INVALID_CALL_PUT'
    floor, ceiling = _arbitrage_bounds(
        float(spot), float(strike), float(years), float(risk_free_rate), float(dividend_yield), cp)
    tick_tolerance = 0.05  # half of TXO's common 0.1-point minimum tick near ATM.
    if price < floor - tick_tolerance or price > ceiling + tick_tolerance:
        return None, 'OUTSIDE_ARBITRAGE_BOUNDS'
    price = min(ceiling, max(floor, price))
    if price <= floor + tolerance:
        return lower_sigma, 'AT_INTRINSIC'
    lo, hi = lower_sigma, upper_sigma
    hi_price = black_scholes(spot, strike, years, risk_free_rate, dividend_yield, hi, cp)['price']
    if hi_price + tolerance < price:
        return None, 'IV_ABOVE_CAP'
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        value = black_scholes(spot, strike, years, risk_free_rate, dividend_yield, mid, cp)['price']
        if abs(value - price) <= tolerance:
            return mid, None
        if value < price:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi), None


def implied_volatility(*args: Any, **kwargs: Any) -> float | None:
    """Convenience wrapper returning only the solved volatility."""
    return solve_implied_volatility(*args, **kwargs)[0]


def oi_gamma_1pct_ntd(
    gamma: float,
    open_interest: int | float,
    spot: float,
    multiplier: float = TXO_MULTIPLIER_NTD,
) -> float:
    values = (gamma, open_interest, spot, multiplier)
    if not all(math.isfinite(float(x)) for x in values):
        raise ValueError('gamma exposure inputs must be finite')
    if gamma < 0 or open_interest < 0 or spot <= 0 or multiplier <= 0:
        raise ValueError('invalid gamma exposure input')
    return gamma * open_interest * multiplier * spot * spot * 0.01


def oi_vega_1vol_point_ntd(
    vega: float,
    open_interest: int | float,
    multiplier: float = TXO_MULTIPLIER_NTD,
) -> float:
    values = (vega, open_interest, multiplier)
    if not all(math.isfinite(float(x)) for x in values):
        raise ValueError('vega exposure inputs must be finite')
    if vega < 0 or open_interest < 0 or multiplier <= 0:
        raise ValueError('invalid vega exposure input')
    return vega * 0.01 * open_interest * multiplier


def oi_vega_1vol_ntd(
    vega: float,
    open_interest: int | float,
    multiplier: float = TXO_MULTIPLIER_NTD,
) -> float:
    """Backward-compatible alias; one vol point means IV changes by 0.01."""
    return oi_vega_1vol_point_ntd(vega, open_interest, multiplier)


def _time_to_expiry(trade_date: str, expiry: str) -> float:
    start_day = date.fromisoformat(trade_date)
    end_day = date.fromisoformat(expiry)
    start = datetime.combine(start_day, dt_time(13, 45), tzinfo=TW_TZ)
    end = datetime.combine(end_day, dt_time(13, 30), tzinfo=TW_TZ)
    return max(0.0, (end - start).total_seconds() / (365.0 * 24.0 * 3600.0))


def _select_price(row: dict[str, Any]) -> tuple[float | None, str | None]:
    # DailyMarketReportOpt is an end-of-day dataset.  Settlement is therefore
    # time-aligned and preferred over a possibly stale closing BBO.
    settlement = _number(row.get('SettlementPrice'))
    if settlement is not None and settlement > 0:
        return settlement, 'settlement'
    close = _number(row.get('Close'))
    if close is not None and close > 0:
        return close, 'close_fallback'
    bid, ask = _number(row.get('BestBid')), _number(row.get('BestAsk'))
    if bid is not None and ask is not None and 0 <= bid <= ask:
        return 0.5 * (bid + ask), 'mid_fallback'
    return None, None


def _parity_dividend_yield(
    contracts: list[dict[str, Any]],
    spot: float,
    years: float,
    risk_free_rate: float,
) -> tuple[float | None, int]:
    """Robust same-expiry q estimate from near-ATM put-call parity pairs."""
    if years <= 0:
        return None, 0
    pairs: dict[float, dict[str, float]] = {}
    for item in contracts:
        price = item.get('price')
        strike = item.get('strike')
        if price is None or strike is None or abs(strike / spot - 1.0) > 0.05:
            continue
        pairs.setdefault(strike, {})[item['callPut']] = price
    estimates = []
    for strike, pair in pairs.items():
        if 'C' not in pair or 'P' not in pair:
            continue
        discounted_spot = pair['C'] - pair['P'] + strike * math.exp(-risk_free_rate * years)
        if discounted_spot <= 0:
            continue
        estimate = -math.log(discounted_spot / spot) / years
        if math.isfinite(estimate) and -2.0 <= estimate <= 2.0:
            estimates.append(estimate)
    return (median(estimates), len(estimates)) if estimates else (None, 0)


def _round(value: float | None, digits: int = 4) -> float | None:
    return round(value, digits) if value is not None and math.isfinite(value) else None


def _root_bisect(fn: Callable[[float], float], left: float, right: float) -> float | None:
    fl, fr = fn(left), fn(right)
    if not math.isfinite(fl) or not math.isfinite(fr):
        return None
    if fl == 0:
        return left
    if fr == 0:
        return right
    if fl * fr > 0:
        return None
    lo, hi = left, right
    for _ in range(90):
        mid = 0.5 * (lo + hi)
        fm = fn(mid)
        if not math.isfinite(fm):
            return None
        if abs(fm) <= 1e-8 or hi - lo <= 1e-7:
            return mid
        if fl * fm <= 0:
            hi, fr = mid, fm
        else:
            lo, fl = mid, fm
    return 0.5 * (lo + hi)


def find_roots(
    fn: Callable[[float], float],
    low: float,
    high: float,
    step: float,
) -> list[float]:
    """Find all bracketed roots on a bounded covered range."""
    if not all(math.isfinite(x) for x in (low, high, step)) or low <= 0 or high <= low or step <= 0:
        return []
    roots: list[float] = []
    x0, f0 = low, fn(low)
    x = low
    while x < high:
        x1 = min(high, x + step)
        f1 = fn(x1)
        if math.isfinite(f0) and math.isfinite(f1):
            if f0 == 0:
                roots.append(x0)
            elif f0 * f1 < 0:
                root = _root_bisect(fn, x0, x1)
                if root is not None:
                    roots.append(root)
        x0, f0, x = x1, f1, x1
    if math.isfinite(f0) and f0 == 0:
        roots.append(high)
    deduped: list[float] = []
    for root in sorted(roots):
        if not deduped or abs(root - deduped[-1]) > max(1e-5, step * 1e-4):
            deduped.append(root)
    return deduped


SCENARIOS: tuple[dict[str, Any], ...] = (
    {'id': 'balanced_proxy', 'label': '平衡代理', 'call': -1.0, 'put': 1.0,
     'assumption': '假設造市商 Call 淨空、Put 淨多；非可觀測持倉。', 'flipEligible': True},
    {'id': 'call_heavy', 'label': 'Call 壓力偏高', 'call': -1.0, 'put': 0.5,
     'assumption': '假設 Call 空方影響較強、Put 影響折半。', 'flipEligible': True},
    {'id': 'put_heavy', 'label': 'Put 緩衝偏高', 'call': -0.5, 'put': 1.0,
     'assumption': '假設 Put 多方影響較強、Call 影響折半。', 'flipEligible': True},
    {'id': 'all_short_stress', 'label': '全淨空壓力測試', 'call': -1.0, 'put': -1.0,
     'assumption': '假設造市商對 Call 與 Put 皆淨空；僅壓力測試。', 'flipEligible': False},
)


def _scenario_profile(
    contracts: list[dict[str, Any]],
    scenario: dict[str, Any],
    spot: float,
    years: float,
    risk_free_rate: float,
    dividend_yield: float,
    low: float,
    high: float,
    step: float,
) -> dict[str, Any]:
    def signed_at(test_spot: float) -> float:
        total = 0.0
        for item in contracts:
            coefficient = scenario['call'] if item['callPut'] == 'C' else scenario['put']
            greek = black_scholes(
                test_spot, item['strike'], years, risk_free_rate, dividend_yield,
                item['iv'], item['callPut'])
            total += coefficient * oi_gamma_1pct_ntd(
                greek['gamma'], item['openInterest'], test_spot)
        return total

    def signed_vex_at(test_spot: float) -> float:
        total = 0.0
        for item in contracts:
            coefficient = scenario['call'] if item['callPut'] == 'C' else scenario['put']
            greek = black_scholes(
                test_spot, item['strike'], years, risk_free_rate, dividend_yield,
                item['iv'], item['callPut'])
            total += coefficient * oi_vega_1vol_point_ntd(
                greek['vega'], item['openInterest'])
        return total

    current = signed_at(spot) if contracts else None
    current_vex = signed_vex_at(spot) if contracts else None
    roots = find_roots(signed_at, low, high, step) if scenario.get('flipEligible') and contracts else []
    primary = min(roots, key=lambda x: abs(x - spot)) if roots else None
    return {
        'id': scenario['id'], 'label': scenario['label'], 'assumption': scenario['assumption'],
        'signedGex1PctNtd': _round(current, 2),
        'signedGexYi': _round(current / 1e8, 3) if current is not None else None,
        'scenarioVex1VolPointNtd': _round(current_vex, 2),
        'scenarioVexYi': _round(current_vex / 1e8, 4) if current_vex is not None else None,
        'coefficientVersion': SCENARIO_COEFFICIENT_VERSION,
        'direction': ('positive' if current is not None and current > 0 else
                      ('negative' if current is not None and current < 0 else 'neutral')),
        'roots': [round(root) for root in roots],
        'primaryFlip': round(primary) if primary is not None else None,
        'flipStatus': 'ready' if roots else 'NO_FLIP_IN_COVERED_RANGE',
        'flipEligible': bool(scenario.get('flipEligible')),
    }


def build_options_structure(
    report_rows: Iterable[dict[str, Any]] | None,
    delta_rows: Iterable[dict[str, Any]] | None,
    *,
    spot: float,
    spot_as_of: str | None = None,
    expiry: str | None = None,
    fetched_at: str | None = None,
    now: datetime | None = None,
    risk_free_rate: float = 0.015,
    dividend_yield: float = 0.020,
) -> dict[str, Any]:
    """Build a compact, provenance-rich single-expiry TXO structure."""
    now = now or datetime.now(timezone.utc)
    fetched_at = fetched_at or now.isoformat()
    spot = float(spot)
    if not math.isfinite(spot) or spot <= 0:
        raise ValueError('spot must be a positive finite number')
    if not math.isfinite(risk_free_rate) or not math.isfinite(dividend_yield):
        raise ValueError('risk-free rate and dividend yield must be finite')

    report = [r for r in (report_rows or []) if isinstance(r, dict)
              and str(r.get('Contract') or '').strip().upper() == 'TXO']
    report_dates = [_date_key(r.get('Date')) for r in report]
    trade_date = max((d for d in report_dates if d), default=None)
    if trade_date:
        report = [r for r in report if _date_key(r.get('Date')) == trade_date]
    general = [r for r in report if str(r.get('TradingSession') or '').strip().lower()
               in ('', '一般', '日盤', 'regular', 'day')]
    if general:
        report = general

    settlement_by_key: dict[tuple[str, float, str], str] = {}
    delta_by_key: dict[tuple[str, float, str], float] = {}
    for row in delta_rows or []:
        if not isinstance(row, dict) or str(row.get('Contract') or '').strip().upper() != 'TXO':
            continue
        cp, strike = _call_put(row.get('CallPut')), _number(row.get('StrikePrice'))
        settlement = _date_key(row.get('ContractSettlementDay'))
        month_week = str(row.get('ContractMonth(Week)') or '').strip()
        if cp and strike is not None and settlement and month_week:
            key = (month_week, strike, cp)
            settlement_by_key[key] = settlement
            official_delta = _number(row.get('Delta'))
            if official_delta is not None:
                delta_by_key[key] = official_delta

    normalized_expiry = _date_key(expiry) if expiry else None
    if expiry and not normalized_expiry:
        raise ValueError('expiry must be YYYYMMDD or YYYY-MM-DD')
    available_expiries = sorted(set(settlement_by_key.values()))
    if normalized_expiry:
        selected_expiry = normalized_expiry
    else:
        selected_expiry = next((d for d in available_expiries if not trade_date or d > trade_date), None)

    raw_contracts: list[dict[str, Any]] = []
    seen: set[tuple[float, str]] = set()
    for row in report:
        cp, strike = _call_put(row.get('CallPut')), _number(row.get('StrikePrice'))
        month_week = str(row.get('ContractMonth(Week)') or '').strip()
        if cp is None or strike is None or strike <= 0 or not month_week:
            continue
        key = (month_week, strike, cp)
        row_expiry = settlement_by_key.get(key)
        if not selected_expiry or row_expiry != selected_expiry or (strike, cp) in seen:
            continue
        seen.add((strike, cp))
        oi = _integer(row.get('OpenInterest'))
        volume = _integer(row.get('Volume'))
        price, price_source = _select_price(row)
        raw_contracts.append({
            'strike': strike, 'callPut': cp, 'openInterest': oi or 0, 'volume': volume or 0,
            'price': price, 'priceSource': price_source, 'officialDelta': delta_by_key.get(key),
            'contractMonthWeek': month_week,
        })

    spot_date = _date_key(spot_as_of)
    hybrid = bool(spot_date and trade_date and spot_date != trade_date)
    years = _time_to_expiry(trade_date, selected_expiry) if trade_date and selected_expiry else 0.0
    dte = ((date.fromisoformat(selected_expiry) - date.fromisoformat(trade_date)).days
           if trade_date and selected_expiry else None)
    warnings: list[str] = []
    if hybrid:
        warnings.append('SPOT_CHAIN_TIMESTAMP_MISMATCH')
    if years <= 0:
        warnings.append('EXPIRED_OR_EXPIRY_DAY')
    if years > 0 and years < 1.0 / 365.0:
        warnings.append('NEAR_EXPIRY_UNSTABLE')
    parity_q, parity_pairs = _parity_dividend_yield(raw_contracts, spot, years, risk_free_rate)
    model_dividend_yield = parity_q if parity_q is not None else dividend_yield
    dividend_yield_source = 'put_call_parity_median' if parity_q is not None else 'configured_fallback'
    if parity_q is not None and not -0.10 <= parity_q <= 0.20:
        warnings.append('PARITY_CARRY_ANNUALIZATION_EXTREME')

    contracts: list[dict[str, Any]] = []
    iv_error_counts: dict[str, int] = {}
    total_oi = valid_iv_oi = 0
    for item in raw_contracts:
        oi = item['openInterest']
        total_oi += oi
        iv = error = None
        if item['price'] is not None and years > 0:
            iv, error = solve_implied_volatility(
                item['price'], spot, item['strike'], years, risk_free_rate,
                model_dividend_yield, item['callPut'])
        else:
            error = 'MISSING_PRICE' if item['price'] is None else 'EXPIRED_OR_EXPIRY_DAY'
        if error:
            iv_error_counts[error] = iv_error_counts.get(error, 0) + 1
        row = dict(item)
        row.update({'iv': iv, 'ivError': error, 'gamma': None, 'vega': None,
                    'oiGamma1PctNtd': None, 'oiVega1VolPointNtd': None})
        if iv is not None and years > 0:
            greeks = black_scholes(
                spot, item['strike'], years, risk_free_rate, model_dividend_yield, iv, item['callPut'])
            row.update({
                'gamma': greeks['gamma'], 'vega': greeks['vega'],
                'modelDelta': greeks['delta'],
                'oiGamma1PctNtd': oi_gamma_1pct_ntd(greeks['gamma'], oi, spot),
                'oiVega1VolPointNtd': oi_vega_1vol_point_ntd(greeks['vega'], oi),
            })
            valid_iv_oi += oi
        contracts.append(row)

    coverage = (valid_iv_oi / total_oi) if total_oi else 0.0
    if coverage < 0.80:
        warnings.append('IV_OI_COVERAGE_BELOW_80PCT')

    grouped: dict[float, dict[str, Any]] = {}
    for item in contracts:
        row = grouped.setdefault(item['strike'], {
            'strike': item['strike'], 'callOi': 0, 'putOi': 0, 'callVolume': 0, 'putVolume': 0,
            'callIvPct': None, 'putIvPct': None, 'absoluteGamma1PctNtd': 0.0,
            'oiVega1VolPointNtd': 0.0,
        })
        prefix = 'call' if item['callPut'] == 'C' else 'put'
        row[prefix + 'Oi'] = item['openInterest']
        row[prefix + 'Volume'] = item['volume']
        row[prefix + 'IvPct'] = _round(item['iv'] * 100.0, 2) if item['iv'] is not None else None
        row['absoluteGamma1PctNtd'] += item['oiGamma1PctNtd'] or 0.0
        row['oiVega1VolPointNtd'] += item['oiVega1VolPointNtd'] or 0.0

    profile_all = [grouped[k] for k in sorted(grouped)]
    for row in profile_all:
        row['absoluteGamma1PctNtd'] = round(row['absoluteGamma1PctNtd'], 2)
        row['absoluteGammaYi'] = round(row['absoluteGamma1PctNtd'] / 1e8, 3)
        row['oiVega1VolPointNtd'] = round(row['oiVega1VolPointNtd'], 2)
        row['oiVegaWan'] = round(row['oiVega1VolPointNtd'] / 1e4, 2)
    nearest_idx = min(range(len(profile_all)), key=lambda i: abs(profile_all[i]['strike'] - spot)) if profile_all else 0
    profile = profile_all[max(0, nearest_idx - 8):nearest_idx + 9]

    calls = [x for x in contracts if x['callPut'] == 'C']
    puts = [x for x in contracts if x['callPut'] == 'P']
    # A practical "wall" must remain near the reference market.  Very remote
    # legacy strikes can carry large dormant OI and would otherwise dominate
    # the label while contributing little current structure information.
    wall_low, wall_high = spot * 0.90, spot * 1.10
    nearby_calls = [x for x in calls if wall_low <= x['strike'] <= wall_high]
    nearby_puts = [x for x in puts if wall_low <= x['strike'] <= wall_high]
    call_wall = max(nearby_calls, key=lambda x: x['openInterest'], default=None)
    put_wall = max(nearby_puts, key=lambda x: x['openInterest'], default=None)
    call_oi, put_oi = sum(x['openInterest'] for x in calls), sum(x['openInterest'] for x in puts)
    atm = min(profile_all, key=lambda x: abs(x['strike'] - spot), default=None)
    atm_ivs = ([v for v in ((atm or {}).get('callIvPct'), (atm or {}).get('putIvPct')) if v is not None])

    call25 = min((x for x in calls if x.get('iv') is not None and x.get('officialDelta') is not None),
                 key=lambda x: abs(x['officialDelta'] - 0.25), default=None)
    put25 = min((x for x in puts if x.get('iv') is not None and x.get('officialDelta') is not None),
                key=lambda x: abs(x['officialDelta'] + 0.25), default=None)
    call25_iv = call25['iv'] * 100.0 if call25 else None
    put25_iv = put25['iv'] * 100.0 if put25 else None
    skew25 = put25_iv - call25_iv if put25_iv is not None and call25_iv is not None else None

    modeled_contracts = [x for x in contracts if x.get('iv') is not None and x['openInterest'] > 0]
    strikes = sorted(set(x['strike'] for x in modeled_contracts))
    min_gap = min((b - a for a, b in zip(strikes, strikes[1:]) if b > a), default=100.0)
    search_low = max(min(strikes, default=spot * 0.8), spot * 0.8)
    search_high = min(max(strikes, default=spot * 1.2), spot * 1.2)
    root_step = max(1.0, min_gap / 2.0)
    model_eligible = bool(
        selected_expiry and trade_date and years > 0 and coverage >= 0.80 and
        not hybrid and modeled_contracts and search_high > search_low)
    scenario_rows: list[dict[str, Any]] = []
    if model_eligible:
        for scenario in SCENARIOS:
            scenario_rows.append(_scenario_profile(
                modeled_contracts, scenario, spot, years, risk_free_rate, model_dividend_yield,
                search_low, search_high, root_step))
    else:
        for scenario in SCENARIOS:
            scenario_rows.append({
                'id': scenario['id'], 'label': scenario['label'], 'assumption': scenario['assumption'],
                'signedGex1PctNtd': None, 'signedGexYi': None,
                'scenarioVex1VolPointNtd': None, 'scenarioVexYi': None,
                'coefficientVersion': SCENARIO_COEFFICIENT_VERSION,
                'direction': 'unavailable',
                'roots': [], 'primaryFlip': None, 'flipStatus': 'MODEL_NOT_ELIGIBLE',
                'flipEligible': bool(scenario.get('flipEligible')),
            })

    primary_flips = [x['primaryFlip'] for x in scenario_rows[:3] if x.get('primaryFlip') is not None]
    directions = {x['direction'] for x in scenario_rows[:3] if x.get('direction') not in ('neutral', 'unavailable')}
    flip_ready = len(primary_flips) >= 2
    band_low, band_high = (min(primary_flips), max(primary_flips)) if flip_ready else (None, None)
    band_width_pct = ((band_high - band_low) / spot * 100.0
                      if band_low is not None and band_high is not None else None)

    age_days = None
    if trade_date:
        age_days = max(0, (now.astimezone(TW_TZ).date() - date.fromisoformat(trade_date)).days)
    stale = bool((age_days is not None and age_days > 4) or hybrid)
    if stale:
        warnings.append('STALE_OR_HYBRID_REFERENCE')
    status = ('insufficient' if not raw_contracts or not selected_expiry else
              ('stale' if stale else 'ready'))
    total_abs_gamma = sum(x.get('oiGamma1PctNtd') or 0.0 for x in contracts)
    total_vega = sum(x.get('oiVega1VolPointNtd') or 0.0 for x in contracts)
    top_gamma = sorted(profile_all, key=lambda x: x['absoluteGamma1PctNtd'], reverse=True)[:5]
    top_vega = sorted(profile_all, key=lambda x: x['oiVega1VolPointNtd'], reverse=True)[:5]

    return {
        'ok': status != 'insufficient',
        'contractVersion': CONTRACT_VERSION,
        'model': MODEL_VERSION,
        'status': status,
        'shadowMode': True,
        'decisionUse': 'research_only',
        'observed': {
            'contract': 'TXO', 'expiry': selected_expiry, 'tradeDate': trade_date,
            'session': 'day_eod', 'spot': round(spot, 2), 'spotAsOf': spot_date or spot_as_of,
            'dte': dte, 'rowCount': len(raw_contracts), 'profile': profile,
            'callWall': ({'strike': call_wall['strike'], 'openInterest': call_wall['openInterest']}
                         if call_wall else None),
            'putWall': ({'strike': put_wall['strike'], 'openInterest': put_wall['openInterest']}
                        if put_wall else None),
            'wallScope': {'method': 'max_open_interest_within_10pct_spot',
                          'low': round(wall_low), 'high': round(wall_high)},
            'callOpenInterest': call_oi, 'putOpenInterest': put_oi,
            'oiPutCallRatio': _round(put_oi / call_oi, 3) if call_oi else None,
        },
        'derived': {
            'method': 'Black-Scholes ACT/365; official settlement price; no IV imputation',
            'atmStrike': (atm or {}).get('strike'),
            'atmIvPct': _round(median(atm_ivs), 2) if atm_ivs else None,
            'call25IvPct': _round(call25_iv, 2), 'put25IvPct': _round(put25_iv, 2),
            'ivSkew25dPctPoint': _round(skew25, 2),
            'ivOiCoveragePct': round(coverage * 100.0, 1),
            'totalOiGamma1PctNtd': round(total_abs_gamma, 2),
            'totalOiGammaYi': round(total_abs_gamma / 1e8, 3),
            'totalOiVega1VolPointNtd': round(total_vega, 2),
            'totalOiVegaWan': round(total_vega / 1e4, 2),
            'totalOiVega1VolNtd': round(total_vega, 2),
            'vegaOiCoveragePct': round(coverage * 100.0, 1),
            'topGammaStrikes': [{k: row.get(k) for k in ('strike', 'absoluteGamma1PctNtd', 'absoluteGammaYi')}
                                for row in top_gamma],
            'topVegaStrikes': [{k: row.get(k) for k in ('strike', 'oiVega1VolPointNtd', 'oiVegaWan')}
                               for row in top_vega],
        },
        'modeled': {
            'eligible': model_eligible and not stale,
            'label': 'Modeled Signed GEX / 情境式淨 Gamma',
            'coefficientVersion': SCENARIO_COEFFICIENT_VERSION,
            'scenarios': scenario_rows,
            'directionConsensus': (next(iter(directions)) if len(directions) == 1 else 'DIRECTION_AMBIGUOUS'),
            'flipBand': {
                'status': ('ready' if flip_ready else 'INSUFFICIENT_SCENARIO_ROOTS'),
                'low': band_low, 'high': band_high,
                'widthPct': _round(band_width_pct, 2),
                'stability': ('low' if band_width_pct is not None and band_width_pct > 2.0 else
                              ('normal' if band_width_pct is not None else 'unavailable')),
                'coveredRange': [round(search_low), round(search_high)] if search_high > search_low else None,
            },
            'warning': '情境係數不是造市商真實持倉，不用於直接買賣。',
        },
        'quality': {
            'source': {'chain': REPORT_URL, 'delta': DELTA_URL},
            'fetchedAt': fetched_at, 'chainAsOf': trade_date, 'spotAsOf': spot_date or spot_as_of,
            'isHybridTimestamp': hybrid, 'ageCalendarDays': age_days,
            'ivOiCoveragePct': round(coverage * 100.0, 1), 'deltaCoveragePct': round(
                (sum(1 for x in raw_contracts if x.get('officialDelta') is not None) / len(raw_contracts) * 100.0)
                if raw_contracts else 0.0, 1),
            'ivErrors': iv_error_counts, 'warnings': list(dict.fromkeys(warnings)),
            'availableExpiries': available_expiries[:24],
        },
        'assumptions': {
            'multiplierNtdPerPoint': TXO_MULTIPLIER_NTD,
            'riskFreeRate': risk_free_rate, 'carryYield': model_dividend_yield,
            'carryYieldSource': dividend_yield_source,
            'dividendYield': model_dividend_yield,
            'dividendYieldSource': dividend_yield_source, 'putCallParityPairs': parity_pairs,
            'timeBasis': 'ACT/365; observation 13:45 Asia/Taipei; expiry 13:30 Asia/Taipei',
            'ivPricePriority': ['settlement', 'close_fallback', 'mid_fallback'],
            'flipSmileRule': 'sticky_strike',
            'publicOiLimit': '公開 OI 僅是多空未沖銷配對，無法證明造市商方向。',
        },
    }


def _read_disk_cache() -> dict[str, Any] | None:
    try:
        with open(CACHE_PATH, 'r', encoding='utf-8') as fh:
            value = json.load(fh)
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_disk_cache(value: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    temp_path = CACHE_PATH + '.tmp'
    with open(temp_path, 'w', encoding='utf-8') as fh:
        json.dump(value, fh, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
    os.replace(temp_path, CACHE_PATH)


class OptionsHistoryCorruptError(RuntimeError):
    pass


def _read_history_rows(*, strict: bool = False) -> list[dict[str, Any]]:
    try:
        with open(HISTORY_PATH, 'r', encoding='utf-8') as fh:
            payload = json.load(fh)
        rows = payload.get('rows') if isinstance(payload, dict) else payload
        return [row for row in (rows or []) if isinstance(row, dict)]
    except json.JSONDecodeError as exc:
        if strict:
            raise OptionsHistoryCorruptError('options history JSON is corrupt') from exc
        return []
    except OSError:
        return []


def _write_history_rows(rows: list[dict[str, Any]]) -> None:
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    temp_path = HISTORY_PATH + f'.{os.getpid()}.{threading.get_ident()}.tmp'
    payload = {
        'schemaVersion': 1, 'model': 'st-options-history/v1',
        'updatedAt': datetime.now(timezone.utc).isoformat(), 'rows': rows[-HISTORY_LIMIT:],
    }
    try:
        with open(temp_path, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(temp_path, HISTORY_PATH)
    finally:
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass


def _compact_history_snapshot(value: dict[str, Any]) -> dict[str, Any] | None:
    observed = value.get('observed') or {}
    derived = value.get('derived') or {}
    modeled = value.get('modeled') or {}
    quality = value.get('quality') or {}
    trade_date = _date_key(observed.get('tradeDate'))
    expiry = _date_key(observed.get('expiry'))
    persistable = bool(
        value.get('ok') and value.get('status') == 'ready' and
        observed.get('session') == 'day_eod' and trade_date and expiry and trade_date < expiry and
        not quality.get('isHybridTimestamp'))
    if not persistable:
        return None
    call_wall, put_wall = observed.get('callWall') or {}, observed.get('putWall') or {}
    band = modeled.get('flipBand') or {}
    return {
        'tradeDate': trade_date, 'expiry': expiry, 'recordedAt': quality.get('fetchedAt'),
        'contractVersion': value.get('contractVersion'), 'model': value.get('model'),
        'spot': _number(observed.get('spot')), 'dte': _integer(observed.get('dte')),
        'callOpenInterest': _integer(observed.get('callOpenInterest')),
        'putOpenInterest': _integer(observed.get('putOpenInterest')),
        'oiPutCallRatio': _number(observed.get('oiPutCallRatio')),
        'callWallStrike': _number(call_wall.get('strike')),
        'putWallStrike': _number(put_wall.get('strike')),
        'wallScopeLow': _number((observed.get('wallScope') or {}).get('low')),
        'wallScopeHigh': _number((observed.get('wallScope') or {}).get('high')),
        'atmIvPct': _number(derived.get('atmIvPct')),
        'ivSkew25dPctPoint': _number(derived.get('ivSkew25dPctPoint')),
        'totalOiGammaYi': _number(derived.get('totalOiGammaYi')),
        'totalOiVegaWan': _number(derived.get('totalOiVegaWan')),
        'ivOiCoveragePct': _number(derived.get('ivOiCoveragePct')),
        'deltaCoveragePct': _number(quality.get('deltaCoveragePct')),
        'directionConsensus': modeled.get('directionConsensus') if modeled.get('eligible') else None,
        'coefficientVersion': modeled.get('coefficientVersion'),
        'flipLow': _number(band.get('low')) if modeled.get('eligible') else None,
        'flipHigh': _number(band.get('high')) if modeled.get('eligible') else None,
    }


def _history_quality(snapshot: dict[str, Any]) -> float:
    values = [x for x in (_number(snapshot.get('ivOiCoveragePct')),
                          _number(snapshot.get('deltaCoveragePct'))) if x is not None]
    return min(values) if values else 0.0


def _pct_change(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return _round((current - previous) / abs(previous) * 100.0, 2)


def _point_change(current: float | None, previous: float | None, digits: int = 2) -> float | None:
    if current is None or previous is None:
        return None
    return _round(current - previous, digits)


def _history_context(snapshot: dict[str, Any], rows: list[dict[str, Any]]) -> dict[str, Any]:
    trade_date, expiry = snapshot['tradeDate'], snapshot['expiry']
    same_expiry = sorted(
        (row for row in rows if row.get('expiry') == expiry and
         str(row.get('tradeDate') or '') < trade_date),
        key=lambda row: str(row.get('tradeDate') or ''))
    if same_expiry:
        previous = same_expiry[-1]
        model_comparable = bool(
            snapshot.get('model') == previous.get('model') and
            snapshot.get('coefficientVersion') == previous.get('coefficientVersion'))
        changes = {
            'spotPoints': _point_change(snapshot.get('spot'), previous.get('spot'), 2),
            'spotPct': _pct_change(snapshot.get('spot'), previous.get('spot')),
            'callOpenInterestPct': _pct_change(snapshot.get('callOpenInterest'), previous.get('callOpenInterest')),
            'putOpenInterestPct': _pct_change(snapshot.get('putOpenInterest'), previous.get('putOpenInterest')),
            'oiPutCallRatio': _point_change(snapshot.get('oiPutCallRatio'), previous.get('oiPutCallRatio'), 3),
            'callWallStrike': _point_change(snapshot.get('callWallStrike'), previous.get('callWallStrike'), 0),
            'putWallStrike': _point_change(snapshot.get('putWallStrike'), previous.get('putWallStrike'), 0),
            'atmIvPctPoint': _point_change(snapshot.get('atmIvPct'), previous.get('atmIvPct'), 2),
            'ivSkewPctPoint': _point_change(snapshot.get('ivSkew25dPctPoint'), previous.get('ivSkew25dPctPoint'), 2),
            'totalOiGammaPct': _pct_change(snapshot.get('totalOiGammaYi'), previous.get('totalOiGammaYi')),
            'totalOiVegaPct': _pct_change(snapshot.get('totalOiVegaWan'), previous.get('totalOiVegaWan')),
            'flipLowPoints': (_point_change(snapshot.get('flipLow'), previous.get('flipLow'), 0)
                              if model_comparable else None),
            'flipHighPoints': (_point_change(snapshot.get('flipHigh'), previous.get('flipHigh'), 0)
                               if model_comparable else None),
        }
        return {
            'status': 'ready', 'sameExpiry': True, 'expiry': expiry,
            'currentTradeDate': trade_date, 'baselineTradeDate': previous.get('tradeDate'),
            'sampleCount': len(same_expiry) + 1, 'requiredSamples': 2, 'changes': changes,
            'modelComparable': model_comparable,
            'modelComparisonReason': None if model_comparable else 'MODEL_OR_COEFFICIENT_VERSION_CHANGED',
        }
    older = sorted(
        (row for row in rows if str(row.get('tradeDate') or '') < trade_date),
        key=lambda row: str(row.get('tradeDate') or ''))
    if older:
        previous = older[-1]
        return {
            'status': 'new_expiry', 'sameExpiry': False, 'expiry': expiry,
            'currentTradeDate': trade_date, 'previousExpiry': previous.get('expiry'),
            'baselineTradeDate': None, 'sampleCount': 1, 'requiredSamples': 2, 'changes': {},
        }
    return {
        'status': 'building', 'sameExpiry': True, 'expiry': expiry,
        'currentTradeDate': trade_date, 'baselineTradeDate': None,
        'sampleCount': 1, 'requiredSamples': 2, 'changes': {},
    }


def _record_history(value: dict[str, Any]) -> dict[str, Any]:
    snapshot = _compact_history_snapshot(value)
    if not snapshot:
        return {'status': 'unavailable', 'sameExpiry': False, 'sampleCount': 0,
                'requiredSamples': 2, 'changes': {}}
    with _lock:
        try:
            rows = _read_history_rows(strict=True)
        except OptionsHistoryCorruptError:
            context = _history_context(snapshot, [])
            context.update({'persistence': 'corrupt_source', 'historyPersisted': False})
            return context
        context = _history_context(snapshot, rows)
        key = (snapshot['tradeDate'], snapshot['expiry'])
        existing = next((row for row in rows if (row.get('tradeDate'), row.get('expiry')) == key), None)
        if existing is None:
            rows.append(snapshot)
        elif _history_quality(snapshot) >= _history_quality(existing):
            rows = [snapshot if (row.get('tradeDate'), row.get('expiry')) == key else row for row in rows]
        rows.sort(key=lambda row: (str(row.get('tradeDate') or ''), str(row.get('expiry') or '')))
        try:
            _write_history_rows(rows)
        except OSError:
            context['persistence'] = 'write_failed'
            context['historyPersisted'] = False
        else:
            context['persistence'] = 'recorded'
            context['historyPersisted'] = True
        return context


def history(*, limit: int = 30, expiry: str | None = None) -> dict[str, Any]:
    limit = max(1, min(int(limit), 180))
    normalized_expiry = _date_key(expiry) if expiry else None
    if expiry and not normalized_expiry:
        raise ValueError('expiry must be YYYYMMDD or YYYY-MM-DD')
    with _lock:
        rows = _read_history_rows(strict=True)
    if normalized_expiry:
        rows = [row for row in rows if row.get('expiry') == normalized_expiry]
    rows.sort(key=lambda row: (str(row.get('tradeDate') or ''), str(row.get('expiry') or '')), reverse=True)
    return {
        'schemaVersion': 1, 'model': 'st-options-history/v1',
        'expiry': normalized_expiry, 'count': min(len(rows), limit),
        'total': len(rows), 'rows': deepcopy(rows[:limit]),
    }


def latest_cached() -> dict[str, Any] | None:
    with _lock:
        if not _memory_cache['loaded']:
            _memory_cache['value'] = _read_disk_cache()
            _memory_cache['loaded'] = True
        return deepcopy(_memory_cache['value']) if _memory_cache['value'] else None


def refresh(
    *,
    spot: float,
    spot_as_of: str | None,
    expiry: str | None = None,
    force: bool = False,
    now: datetime | None = None,
    fetcher: Callable[..., Any] = fetch_json,
) -> dict[str, Any]:
    """Fetch official sources, build one exact expiry and cache atomically."""
    now = now or datetime.now(timezone.utc)
    with _lock:
        cached = latest_cached()
        same_expiry = not expiry or _date_key(expiry) == ((cached or {}).get('observed') or {}).get('expiry')
        if (not force and cached and same_expiry and
                time.time() - float(_memory_cache.get('savedAt') or 0.0) < CACHE_TTL_SEC):
            return cached
    fetched_at = now.isoformat()
    try:
        report = fetcher(REPORT_URL, timeout=25, retries=2)
        delta = fetcher(DELTA_URL, timeout=25, retries=2)
        if not isinstance(report, list) or not isinstance(delta, list):
            raise ValueError('TAIFEX options endpoints must return arrays')
        value = build_options_structure(
            report, delta, spot=spot, spot_as_of=spot_as_of, expiry=expiry,
            fetched_at=fetched_at, now=now)
        value['history'] = _record_history(value)
        with _lock:
            _memory_cache.update({'loaded': True, 'value': value, 'savedAt': time.time()})
            try:
                _write_disk_cache(value)
            except OSError:
                pass
        return deepcopy(value)
    except Exception as exc:
        cached = latest_cached()
        if cached:
            cached['status'] = 'stale'
            cached.setdefault('quality', {})['fallbackError'] = str(exc)[:240]
            warnings = cached['quality'].setdefault('warnings', [])
            if 'SOURCE_REFRESH_FAILED' not in warnings:
                warnings.append('SOURCE_REFRESH_FAILED')
            cached.setdefault('modeled', {})['eligible'] = False
            return cached
        return {
            'ok': False, 'contractVersion': CONTRACT_VERSION, 'model': MODEL_VERSION,
            'status': 'insufficient', 'shadowMode': True, 'decisionUse': 'research_only',
            'observed': {}, 'derived': {},
            'modeled': {'eligible': False, 'scenarios': [], 'warning': '無可用官方資料，不產生情境數字。'},
            'quality': {'source': {'chain': REPORT_URL, 'delta': DELTA_URL},
                        'fetchedAt': fetched_at, 'warnings': ['SOURCE_REFRESH_FAILED'],
                        'error': str(exc)[:240]},
            'assumptions': {'publicOiLimit': '公開 OI 無法證明造市商方向。'},
        }


def clear_memory_cache() -> None:
    """Test helper; does not delete the recoverable disk cache."""
    with _lock:
        _memory_cache.update({'loaded': False, 'value': None, 'savedAt': 0.0})
