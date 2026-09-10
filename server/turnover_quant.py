# -*- coding: utf-8 -*-
"""成交金額量化指標（單位：億）。

與大盤體質量能分同源：8000 億 = 50 分、1.2 兆偏熱（結構題錨，不是常態分位數）。
另給近 20 日 Z 的相對冷熱標籤。供 /pulse strip、/marketflow.turnoverQuant 使用。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from trend_quant import overlay_latest, session_date_key


def volume_score_yi(yi: float) -> float:
    """成交金額（億）→ 0~100 體制量能分（8000 億 = 50）。"""
    return max(0.0, min(100.0, 50.0 + 50.0 * math.tanh((float(yi) - 8000.0) / 4000.0)))


def volume_relative_label(z20: Optional[float]) -> Optional[str]:
    """近 20 日 Z 的相對冷熱；與 8000 億體制錨分開。"""
    if z20 is None:
        return None
    if z20 >= 1.0:
        return '相對偏熱'
    if z20 <= -1.0:
        return '相對偏冷'
    return '相對中性'


def volume_relative_score(z20: Optional[float]) -> Optional[float]:
    if z20 is None:
        return None
    return round(max(0.0, min(100.0, 50.0 + 50.0 * math.tanh(float(z20) / 1.5))), 1)


def turnover_quant(
    turns: Optional[List[dict]],
    latest_yi: Optional[float] = None,
    latest_date: Optional[Any] = None,
) -> Dict[str, Any]:
    """由日成交序列＋可選當日官方億元，建量能量化指標。

    turns: [{date, amount: 元, ...}, ...]
    latest_date: 當日官方成交所屬交易日。缺日期時只覆寫最後一根，不因盤中累積量 append。
    回傳：yi, chgPct, ma5Yi, vsMa5Pct, z20, volumeScore, volumeRelative, streak, trend, level, n
    """
    empty = {
        'yi': None, 'chgPct': None, 'ma5Yi': None, 'vsMa5Pct': None,
        'z20': None, 'volumeScore': None, 'volumeRelative': None,
        'volumeRelativeScore': None, 'streak': None,
        'trend': None, 'level': None, 'n': 0,
    }
    series: List[float] = []
    dates: List[Optional[str]] = []
    for row in turns or []:
        if not isinstance(row, dict):
            continue
        try:
            if row.get('amount') is None:
                continue
            yi = float(row['amount']) / 1e8
        except (TypeError, ValueError):
            continue
        if not math.isfinite(yi):
            continue
        series.append(yi)
        dates.append(session_date_key(row.get('date') or row.get('asOf')))
    if latest_yi is not None:
        try:
            cur0 = float(latest_yi)
        except (TypeError, ValueError):
            cur0 = None
        if cur0 is not None and math.isfinite(cur0):
            overlay_latest(
                series, dates, cur0, session_date_key(latest_date), same_bar=False)
    if not series:
        return empty
    cur = series[-1]
    prev = series[-2] if len(series) >= 2 else None
    chg = ((cur - prev) / prev * 100.0) if prev not in (None, 0) else None
    win5 = series[-5:]
    ma5 = sum(win5) / len(win5) if win5 else None
    vs_ma5 = ((cur - ma5) / ma5 * 100.0) if ma5 not in (None, 0) else None
    z20 = None
    if len(series) >= 6:
        w = series[-20:] if len(series) >= 20 else series
        mu = sum(w) / len(w)
        var = sum((x - mu) ** 2 for x in w) / len(w)
        sd = math.sqrt(var) if var > 0 else 0.0
        if sd > 1e-9:
            z20 = (cur - mu) / sd
    vol_sc = volume_score_yi(cur)
    rel = volume_relative_label(z20)
    rel_sc = volume_relative_score(z20)
    streak = 0
    for i in range(len(series) - 1, 0, -1):
        d = series[i] - series[i - 1]
        if abs(d) < 1e-9:
            break
        sign = 1 if d > 0 else -1
        if streak == 0:
            streak = sign
        elif (streak > 0 and sign > 0) or (streak < 0 and sign < 0):
            streak += sign
        else:
            break
    if cur >= 12000:
        level = '爆量'
    elif cur >= 10000:
        level = '兆級'
    elif cur >= 8000:
        level = '健康'
    elif cur >= 5000:
        level = '偏弱'
    else:
        level = '清淡'
    if vs_ma5 is not None and vs_ma5 >= 15 and cur >= 8000:
        trend = '放量趨升'
    elif vs_ma5 is not None and vs_ma5 >= 8:
        trend = '溫和放量'
    elif vs_ma5 is not None and vs_ma5 <= -15:
        trend = '明顯縮量'
    elif vs_ma5 is not None and vs_ma5 <= -8:
        trend = '溫和縮量'
    elif chg is not None and chg >= 10:
        trend = '單日放量'
    elif chg is not None and chg <= -10:
        trend = '單日縮量'
    else:
        trend = '量能持穩'
    return {
        'yi': round(cur, 1),
        'chgPct': round(chg, 2) if chg is not None else None,
        'ma5Yi': round(ma5, 1) if ma5 is not None else None,
        'vsMa5Pct': round(vs_ma5, 2) if vs_ma5 is not None else None,
        'z20': round(z20, 2) if z20 is not None else None,
        'volumeScore': round(vol_sc, 1),
        'volumeRelative': rel,
        'volumeRelativeScore': rel_sc,
        'streak': streak if streak != 0 else 0,
        'trend': trend,
        'level': level,
        'n': len(series),
    }
