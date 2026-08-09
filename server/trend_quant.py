# -*- coding: utf-8 -*-
"""指數／期貨價格序列趨勢量化。

與成交金額量能量化同構：vs前日／vs5日均／動能分／近20日Z／連續漲跌／趨勢標籤。
供 /pulse strip 加權、櫃買、台指期使用。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence


def momentum_score(vs_ma5_pct: Optional[float], z20: Optional[float] = None,
                   chg_pct: Optional[float] = None) -> float:
    """動能分 0~100：以 vs5 為主、Z20／單日漲跌為輔。中性 50。"""
    x = 0.0
    w = 0.0
    if vs_ma5_pct is not None:
        x += float(vs_ma5_pct) / 2.0
        w += 1.0
    if z20 is not None:
        x += float(z20) / 1.2
        w += 0.7
    if chg_pct is not None:
        x += float(chg_pct) / 1.5
        w += 0.4
    if w <= 0:
        return 50.0
    blended = x / w
    return max(0.0, min(100.0, 50.0 + 50.0 * math.tanh(blended)))


def price_series_quant(closes: Optional[Sequence[float]],
                       latest: Optional[float] = None) -> Dict[str, Any]:
    """由收盤價序列＋可選當日即時價，建趨勢量化指標。

    closes: 由舊到新的收盤價
    回傳：close, chgPct, ma5, vsMa5Pct, z20, momScore, streak, trend, level, n, spark
    """
    empty = {
        'close': None, 'chgPct': None, 'ma5': None, 'vsMa5Pct': None,
        'z20': None, 'momScore': None, 'streak': None,
        'trend': None, 'level': None, 'n': 0, 'spark': [],
    }
    series: List[float] = []
    for c in closes or []:
        try:
            v = float(c)
            if v > 0 and math.isfinite(v):
                series.append(v)
        except Exception:
            continue
    if latest is not None:
        try:
            cur0 = float(latest)
        except Exception:
            cur0 = None
        if cur0 is not None and cur0 > 0 and math.isfinite(cur0):
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
    mom = momentum_score(vs_ma5, z20, chg)
    streak = 0
    for i in range(len(series) - 1, 0, -1):
        d = series[i] - series[i - 1]
        if abs(d) < 1e-12:
            break
        sign = 1 if d > 0 else -1
        if streak == 0:
            streak = sign
        elif (streak > 0 and sign > 0) or (streak < 0 and sign < 0):
            streak += sign
        else:
            break
    # 水位：相對 5 日均偏離（指數／期貨共用百分比刻度）
    if vs_ma5 is not None and vs_ma5 >= 3.0:
        level = '強勢'
    elif vs_ma5 is not None and vs_ma5 >= 1.0:
        level = '偏強'
    elif vs_ma5 is not None and vs_ma5 <= -3.0:
        level = '弱勢'
    elif vs_ma5 is not None and vs_ma5 <= -1.0:
        level = '偏弱'
    else:
        level = '中性'
    # 趨勢標籤（與量能版同構語氣）
    if vs_ma5 is not None and vs_ma5 >= 2.0 and streak >= 3:
        trend = '連漲趨升'
    elif vs_ma5 is not None and vs_ma5 >= 1.0:
        trend = '溫和上行'
    elif vs_ma5 is not None and vs_ma5 <= -2.0 and streak <= -3:
        trend = '連跌趨降'
    elif vs_ma5 is not None and vs_ma5 <= -1.0:
        trend = '溫和下行'
    elif chg is not None and chg >= 2.0:
        trend = '單日急漲'
    elif chg is not None and chg <= -2.0:
        trend = '單日急跌'
    else:
        trend = '區間震盪'
    spark = [round(x, 4) for x in series[-20:]]
    return {
        'close': round(cur, 4),
        'chgPct': round(chg, 2) if chg is not None else None,
        'ma5': round(ma5, 4) if ma5 is not None else None,
        'vsMa5Pct': round(vs_ma5, 2) if vs_ma5 is not None else None,
        'z20': round(z20, 2) if z20 is not None else None,
        'momScore': round(mom, 1),
        'streak': streak if streak != 0 else 0,
        'trend': trend,
        'level': level,
        'n': len(series),
        'spark': spark,
    }
