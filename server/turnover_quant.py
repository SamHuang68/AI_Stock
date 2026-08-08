# -*- coding: utf-8 -*-
"""成交金額量化指標（單位：億）。

與大盤體質量能分同源：8000 億 = 50 分、1.2 兆偏熱。
供 /pulse strip、/marketflow.turnoverQuant 使用。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


def volume_score_yi(yi: float) -> float:
    """成交金額（億）→ 0~100 量能分。"""
    return max(0.0, min(100.0, 50.0 + 50.0 * math.tanh((float(yi) - 8000.0) / 4000.0)))


def turnover_quant(turns: Optional[List[dict]], latest_yi: Optional[float] = None) -> Dict[str, Any]:
    """由日成交序列＋可選當日官方億元，建量能量化指標。

    turns: [{amount: 元, ...}, ...]
    回傳：yi, chgPct, ma5Yi, vsMa5Pct, z20, volumeScore, streak, trend, level, n
    """
    empty = {
        'yi': None, 'chgPct': None, 'ma5Yi': None, 'vsMa5Pct': None,
        'z20': None, 'volumeScore': None, 'streak': None,
        'trend': None, 'level': None, 'n': 0,
    }
    series: List[float] = []
    for t in turns or []:
        try:
            if t.get('amount') is not None:
                series.append(float(t['amount']) / 1e8)
        except Exception:
            continue
    if latest_yi is not None:
        try:
            cur0 = float(latest_yi)
        except Exception:
            cur0 = None
        if cur0 is not None:
            if not series:
                series = [cur0]
            elif abs(series[-1] - cur0) / max(abs(cur0), 1.0) <= 0.03:
                series[-1] = cur0
            else:
                series.append(cur0)
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
        'streak': streak if streak != 0 else 0,
        'trend': trend,
        'level': level,
        'n': len(series),
    }
