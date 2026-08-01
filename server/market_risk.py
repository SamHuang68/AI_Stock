# -*- coding: utf-8 -*-
"""市場風險評分（美總經追蹤圖）＋大盤體質說明文字。

設計原則：
  - 分數 0~100，越高越「需要警戒」（市場風險）／或越「健康」（大盤體質，direction=health）
  - 公式可對非金融友人講清楚；前後端共用同一套映射
  - 視圖切換（對齊／原始、可見區間）時可依目前序列重算
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _tanh_map(x: float, center: float, scale: float) -> float:
    """center → 50；x 往上 → 趨近 100；往下 → 趨近 0。"""
    if scale == 0:
        return 50.0
    return _clamp(50.0 + 50.0 * math.tanh((float(x) - center) / scale))


def _last(points: List[Dict[str, Any]]) -> Optional[float]:
    for p in reversed(points or []):
        v = p.get('value')
        if v is not None and isinstance(v, (int, float)) and math.isfinite(float(v)):
            return float(v)
    return None


def _first(points: List[Dict[str, Any]]) -> Optional[float]:
    for p in points or []:
        v = p.get('value')
        if v is not None and isinstance(v, (int, float)) and math.isfinite(float(v)):
            return float(v)
    return None


def _window_return_pct(points: List[Dict[str, Any]]) -> Optional[float]:
    a, b = _first(points), _last(points)
    if a is None or b is None or a == 0:
        return None
    return (b / a - 1.0) * 100.0


def _max_drawdown_pct(points: List[Dict[str, Any]]) -> Optional[float]:
    """區間內相對峰值的最大回撤（正數 %）。"""
    peak = None
    max_dd = 0.0
    n = 0
    for p in points or []:
        v = p.get('value')
        if v is None or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
            continue
        v = float(v)
        n += 1
        if peak is None or v > peak:
            peak = v
        if peak and peak > 0:
            dd = (peak - v) / peak * 100.0
            if dd > max_dd:
                max_dd = dd
    if n < 2:
        return None
    return max_dd


def _series_map(series_list: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    out = {}
    for s in series_list or []:
        k = s.get('key')
        if k:
            out[k] = s.get('points') or []
    return out


def _label_risk(score: Optional[float]) -> str:
    if score is None:
        return '資料不足'
    if score >= 70:
        return '風險偏高'
    if score >= 55:
        return '風險中偏高'
    if score >= 45:
        return '風險中性'
    if score >= 30:
        return '風險偏低'
    return '風險偏低'


def _label_health(score: Optional[float]) -> str:
    if score is None:
        return '資料不足'
    if score >= 70:
        return '體質偏強'
    if score >= 55:
        return '體質中偏強'
    if score >= 45:
        return '體質中性'
    if score >= 30:
        return '體質偏弱'
    return '體質偏冷'


# ── 利率壓力（Fed + 10Y 水準）────────────────────────────────
def score_rate_pressure(fed: Optional[float], us10y: Optional[float]) -> Tuple[Optional[float], Dict[str, Any]]:
    """基準利率中性 2.5%、10Y 中性 3.0%；越高越警戒。"""
    detail: Dict[str, Any] = {}
    parts = []
    if fed is not None:
        sc = _tanh_map(fed, 2.5, 2.0)
        parts.append(sc)
        detail['fedfunds'] = round(float(fed), 3)
        detail['fedScore'] = round(sc, 1)
    if us10y is not None:
        sc = _tanh_map(us10y, 3.0, 1.5)
        parts.append(sc)
        detail['us10y'] = round(float(us10y), 3)
        detail['us10yScore'] = round(sc, 1)
    if not parts:
        return None, detail
    avg = sum(parts) / len(parts)
    detail['score'] = round(avg, 1)
    return round(avg, 1), detail


# ── 信用壓力（HY 相對 IG 落後 + HY 回撤）────────────────────
def score_credit_pressure(ig_pts: List[Dict[str, Any]],
                          hy_pts: List[Dict[str, Any]]) -> Tuple[Optional[float], Dict[str, Any]]:
    """
    IG 報酬 − HY 報酬 越大 → HY 越落後 → 信用壓力越高。
    另看 HY 區間最大回撤。兩項等權。
    """
    detail: Dict[str, Any] = {}
    ig_ret = _window_return_pct(ig_pts)
    hy_ret = _window_return_pct(hy_pts)
    hy_dd = _max_drawdown_pct(hy_pts)
    parts = []
    if ig_ret is not None and hy_ret is not None:
        lag = ig_ret - hy_ret  # pp
        sc = _tanh_map(lag, 0.0, 12.0)  # 落後 12pp → ~76
        parts.append(sc)
        detail['igReturnPct'] = round(ig_ret, 2)
        detail['hyReturnPct'] = round(hy_ret, 2)
        detail['hyLagPp'] = round(lag, 2)
        detail['lagScore'] = round(sc, 1)
    if hy_dd is not None:
        sc = _tanh_map(hy_dd, 8.0, 10.0)  # 回撤 8% 中性偏壓
        parts.append(sc)
        detail['hyDrawdownPct'] = round(hy_dd, 2)
        detail['ddScore'] = round(sc, 1)
    if not parts:
        return None, detail
    avg = sum(parts) / len(parts)
    detail['score'] = round(avg, 1)
    return round(avg, 1), detail


# ── 通膨壓力（CPI YoY）──────────────────────────────────────
def score_inflation_pressure(cpi_yoy: Optional[float]) -> Tuple[Optional[float], Dict[str, Any]]:
    """聯準會隱含目標約 2%；越高越警戒。"""
    detail: Dict[str, Any] = {}
    if cpi_yoy is None:
        return None, detail
    sc = _tanh_map(cpi_yoy, 2.0, 2.0)
    detail['cpiYoy'] = round(float(cpi_yoy), 3)
    detail['score'] = round(sc, 1)
    return round(sc, 1), detail


# ── 金融股壓力（XLF 弱＝警戒）────────────────────────────────
def score_fin_pressure(xlf_pts: List[Dict[str, Any]]) -> Tuple[Optional[float], Dict[str, Any]]:
    """區間報酬越差、回撤越大 → 壓力越高。"""
    detail: Dict[str, Any] = {}
    ret = _window_return_pct(xlf_pts)
    dd = _max_drawdown_pct(xlf_pts)
    parts = []
    if ret is not None:
        # 報酬 −20% → 高壓；+20% → 低壓
        sc = _clamp(50.0 - 50.0 * math.tanh(ret / 20.0))
        parts.append(sc)
        detail['xlfReturnPct'] = round(ret, 2)
        detail['retScore'] = round(sc, 1)
    if dd is not None:
        sc = _tanh_map(dd, 10.0, 12.0)
        parts.append(sc)
        detail['xlfDrawdownPct'] = round(dd, 2)
        detail['ddScore'] = round(sc, 1)
    if not parts:
        return None, detail
    avg = sum(parts) / len(parts)
    detail['score'] = round(avg, 1)
    return round(avg, 1), detail


ALGO_US_RATES_CREDIT = {
    'id': '__US_RATES_CREDIT__',
    'title': '市場風險 · 美國利率 vs 公司債',
    'direction': 'alert',  # 越高越警戒
    'pillars': [
        {
            'key': 'ratePressure',
            'name': '利率壓力',
            'weight': '50%',
            'plain': '基準利率與 10 年期公債殖利率愈高，資金成本愈重，壓力愈大。',
            'formula': (
                'Fed 分 = 50 + 50·tanh((Fed−2.5)/2.0)；'
                '10Y 分 = 50 + 50·tanh((10Y−3.0)/1.5)；'
                '利率壓力 = 兩者平均（缺一則用有的那項）。'
            ),
        },
        {
            'key': 'creditPressure',
            'name': '信用壓力',
            'weight': '50%',
            'plain': '高收益債若明顯落後投資級、或自身回撤變大，代表信用風險升高。',
            'formula': (
                '落後分 = 50 + 50·tanh(((IG區間報酬%−HY區間報酬%)−0)/12)；'
                '回撤分 = 50 + 50·tanh((HY最大回撤%−8)/10)；'
                '信用壓力 = 兩者平均。'
            ),
        },
    ],
    'aggregate': '總分 = 有資料支柱的簡單平均（目前兩支柱等權）。',
    'viewNote': '切換「對齊／原始」或縮放可見區間後，分數依目前視窗內序列重算。利率壓力用最新水準；信用壓力用視窗內報酬與回撤。',
}

ALGO_US_CPI_FIN = {
    'id': '__US_CPI_FIN__',
    'title': '市場風險 · CPI＆利率 vs 金融股',
    'direction': 'alert',
    'pillars': [
        {
            'key': 'inflationPressure',
            'name': '通膨壓力',
            'weight': '⅓',
            'plain': 'CPI 年增率愈高於約 2% 目標，通膨壓力愈大。',
            'formula': '通膨壓力 = 50 + 50·tanh((CPI YoY−2.0)/2.0)',
        },
        {
            'key': 'ratePressure',
            'name': '利率壓力',
            'weight': '⅓',
            'plain': '基準利率愈高，金融環境愈緊。',
            'formula': '利率壓力 = 50 + 50·tanh((Fed−2.5)/2.0)',
        },
        {
            'key': 'finPressure',
            'name': '金融股壓力',
            'weight': '⅓',
            'plain': '金融類股（XLF）區間表現愈差、回撤愈深，壓力愈高。',
            'formula': (
                '報酬分 = 50 − 50·tanh(XLF區間報酬%/20)；'
                '回撤分 = 50 + 50·tanh((XLF最大回撤%−10)/12)；'
                '金融股壓力 = 兩者平均。'
            ),
        },
    ],
    'aggregate': '總分 = 有資料支柱的簡單平均（三支柱等權）。',
    'viewNote': '分數依目前視窗內序列重算；通膨／利率用最新值，金融股用視窗報酬與回撤。',
}

ALGO_TW_MARKET = {
    'id': 'TW_MARKET_FUND',
    'title': '大盤體質',
    'direction': 'health',  # 越高越健康
    'pillars': [
        {
            'key': 'volumeScore',
            'name': '量能',
            'weight': '25%',
            'plain': '全市場成交金額適中偏熱較健康；過冷代表動能不足。',
            'formula': '量能分 = 50 + 50·tanh((成交金額億−8000)/4000)',
        },
        {
            'key': 'instScore',
            'name': '三大法人',
            'weight': '25%',
            'plain': '外資＋投信＋自營合計買超愈多，法人支柱愈強。',
            'formula': '法人分 = 50 + 50·tanh(合計買賣差億 / 300)',
        },
        {
            'key': 'marginScore',
            'name': '融資安全',
            'weight': '25%',
            'plain': '融資維持率愈高愈安全（相對 166% 中性；130% 偏危險）。',
            'formula': '融資分 = 50 + 50·tanh((維持率−166)/30)',
        },
        {
            'key': 'valuationScore',
            'name': '估值',
            'weight': '25%',
            'plain': '全市場本益比中位愈低，估值愈有吸引力。',
            'formula': '估值分 = 50 − 50·tanh((中位本益比−18)/12)',
        },
    ],
    'aggregate': '總分 = 有資料支柱的簡單平均（四支柱等權）。',
    'viewNote': '大盤體質依當日市場流／融資／本益比快照，不隨 K 線縮放重算。',
}


def build_us_rates_credit_risk(series_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    sm = _series_map(series_list)
    fed = _last(sm.get('fedfunds') or [])
    y10 = _last(sm.get('us10y') or [])
    rate_sc, rate_d = score_rate_pressure(fed, y10)
    cred_sc, cred_d = score_credit_pressure(sm.get('baml_ig') or [], sm.get('baml_hy') or [])
    parts = [x for x in (rate_sc, cred_sc) if x is not None]
    score = round(sum(parts) / len(parts), 1) if parts else None
    label = _label_risk(score)
    pillars = []
    if rate_sc is not None:
        pillars.append({
            'key': 'ratePressure', 'k': '利率壓力', 'name': '利率壓力',
            'score': rate_sc,
            'v': _fmt_rate_v(rate_d),
            'detail': rate_d,
        })
    if cred_sc is not None:
        pillars.append({
            'key': 'creditPressure', 'k': '信用壓力', 'name': '信用壓力',
            'score': cred_sc,
            'v': _fmt_credit_v(cred_d),
            'detail': cred_d,
        })
    plain = (
        f'目前市場風險約 {score} 分（{label}）。'
        if score is not None else
        '市場風險資料暫缺。'
    )
    if rate_sc is not None:
        plain += f' 利率壓力 {rate_sc}；'
    if cred_sc is not None:
        plain += f' 信用壓力 {cred_sc}。'
    else:
        plain = plain.rstrip('；') + ('。' if not plain.endswith('。') else '')
    return {
        'kind': 'market_risk',
        'title': '市場風險',
        'direction': 'alert',
        'score': score,
        'label': label,
        'summary': f'市場風險 {score} · {label}' if score is not None else '市場風險 —',
        'plainSummary': plain.strip(),
        'pillars': {p['key']: p['score'] for p in pillars},
        'marketRows': [{'k': p['k'], 'v': p['v'], 'score': p['score']} for p in pillars],
        'pillarDetails': pillars,
        'algo': ALGO_US_RATES_CREDIT,
        '_source': 'FRED Fed/10Y + BAML IG/HY（或缺時 Yahoo LQD/HYG）',
    }


def build_us_cpi_fin_risk(series_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    sm = _series_map(series_list)
    cpi = _last(sm.get('us_cpi_yoy') or [])
    fed = _last(sm.get('fedfunds') or [])
    inf_sc, inf_d = score_inflation_pressure(cpi)
    rate_sc, rate_d = score_rate_pressure(fed, None)
    fin_sc, fin_d = score_fin_pressure(sm.get('xlf') or [])
    parts = [x for x in (inf_sc, rate_sc, fin_sc) if x is not None]
    score = round(sum(parts) / len(parts), 1) if parts else None
    label = _label_risk(score)
    pillars = []
    if inf_sc is not None:
        pillars.append({
            'key': 'inflationPressure', 'k': '通膨壓力', 'name': '通膨壓力',
            'score': inf_sc,
            'v': f"CPI YoY {inf_d.get('cpiYoy')}%" if inf_d.get('cpiYoy') is not None else '—',
            'detail': inf_d,
        })
    if rate_sc is not None:
        pillars.append({
            'key': 'ratePressure', 'k': '利率壓力', 'name': '利率壓力',
            'score': rate_sc,
            'v': f"Fed {rate_d.get('fedfunds')}%" if rate_d.get('fedfunds') is not None else '—',
            'detail': rate_d,
        })
    if fin_sc is not None:
        pillars.append({
            'key': 'finPressure', 'k': '金融股壓力', 'name': '金融股壓力',
            'score': fin_sc,
            'v': _fmt_fin_v(fin_d),
            'detail': fin_d,
        })
    plain = (
        f'目前市場風險約 {score} 分（{label}）。'
        if score is not None else
        '市場風險資料暫缺。'
    )
    bits = []
    if inf_sc is not None:
        bits.append(f'通膨 {inf_sc}')
    if rate_sc is not None:
        bits.append(f'利率 {rate_sc}')
    if fin_sc is not None:
        bits.append(f'金融股 {fin_sc}')
    if bits:
        plain += ' ' + '、'.join(bits) + '。'
    return {
        'kind': 'market_risk',
        'title': '市場風險',
        'direction': 'alert',
        'score': score,
        'label': label,
        'summary': f'市場風險 {score} · {label}' if score is not None else '市場風險 —',
        'plainSummary': plain.strip(),
        'pillars': {p['key']: p['score'] for p in pillars},
        'marketRows': [{'k': p['k'], 'v': p['v'], 'score': p['score']} for p in pillars],
        'pillarDetails': pillars,
        'algo': ALGO_US_CPI_FIN,
        '_source': 'FRED CPI/Fed + Yahoo XLF',
    }


def attach_risk_to_chart(chart_id: str, chart: Dict[str, Any]) -> Dict[str, Any]:
    cid = str(chart_id or '').upper()
    series = chart.get('series') or []
    if cid == '__US_RATES_CREDIT__':
        chart['risk'] = build_us_rates_credit_risk(series)
    elif cid == '__US_CPI_FIN__':
        chart['risk'] = build_us_cpi_fin_risk(series)
    return chart


def enrich_tw_market_fundamental(out: Dict[str, Any]) -> Dict[str, Any]:
    """為大盤體質 payload 補 summary / plainSummary / algo / direction。"""
    score = out.get('score')
    label = _label_health(score)
    out['direction'] = 'health'
    out['label'] = label
    out['summary'] = f'大盤體質 {score} · {label}' if score is not None else '大盤體質 —'
    rows = out.get('marketRows') or []
    bits = [f"{r['k']} {int(round(r['score']))}" for r in rows if r.get('score') is not None]
    plain = (
        f'目前大盤體質約 {score} 分（{label}）。分數愈高代表量能、法人、融資安全與估值綜合愈健康。'
        if score is not None else
        '大盤體質資料暫缺。'
    )
    if bits:
        plain += ' 支柱：' + '、'.join(bits) + '。'
    out['plainSummary'] = plain
    out['algo'] = ALGO_TW_MARKET
    return out


def _fmt_rate_v(d: Dict[str, Any]) -> str:
    bits = []
    if d.get('fedfunds') is not None:
        bits.append(f"Fed {d['fedfunds']}%")
    if d.get('us10y') is not None:
        bits.append(f"10Y {d['us10y']}%")
    return ' · '.join(bits) if bits else '—'


def _fmt_credit_v(d: Dict[str, Any]) -> str:
    bits = []
    if d.get('hyLagPp') is not None:
        lag = d['hyLagPp']
        bits.append(f"HY落後 {lag:+.1f}pp" if isinstance(lag, (int, float)) else f"HY落後 {lag}pp")
    if d.get('hyDrawdownPct') is not None:
        bits.append(f"HY回撤 {d['hyDrawdownPct']:.1f}%")
    return ' · '.join(bits) if bits else '—'


def _fmt_fin_v(d: Dict[str, Any]) -> str:
    bits = []
    if d.get('xlfReturnPct') is not None:
        r = d['xlfReturnPct']
        bits.append(f"報酬 {r:+.1f}%")
    if d.get('xlfDrawdownPct') is not None:
        bits.append(f"回撤 {d['xlfDrawdownPct']:.1f}%")
    return ' · '.join(bits) if bits else '—'
