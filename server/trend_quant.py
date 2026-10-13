# -*- coding: utf-8 -*-
"""指數／期貨價格序列趨勢量化。

與成交金額量能量化同構：vs前日／vs5日均／動能分／近20日Z／連續漲跌／趨勢標籤。
供 /pulse strip 加權、櫃買、台指期使用。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence
from exchange_source_dates import official_date


def merge_dated_series(values, dates, latest=None, latest_date=None, *, allow_zero=False):
    """依明示交易日更新；沒有日期的舊呼叫不混入即時價。"""
    pairs = []
    for i, raw in enumerate(values):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = None
        day = official_date(dates[i]) if i < len(dates) else None
        valid = value is not None and math.isfinite(value) and (value >= 0 if allow_zero else value > 0)
        pairs.append((day, value if valid else None))
    dated = bool(pairs) and all(day is not None for day, _ in pairs)
    if dated:
        pairs = sorted(dict(pairs).items())
    day = official_date(latest_date)
    try:
        current = float(latest) if latest is not None else None
    except (TypeError, ValueError):
        current = None
    merged = False
    if day and current is not None and math.isfinite(current) and (current >= 0 if allow_zero else current > 0):
        if not pairs or dated and day >= pairs[-1][0]:
            if pairs and day == pairs[-1][0]:
                pairs[-1] = (day, current)
            else:
                pairs.append((day, current))
            merged = True
    # 缺值保留切段意義，不把缺值兩側串成相鄰觀測。
    start = max((i + 1 for i, (_, value) in enumerate(pairs) if value is None), default=0)
    pairs = pairs[start:]
    return [value for _, value in pairs], {
        'asOf': pairs[-1][0].isoformat() if pairs and pairs[-1][0] else None,
        'latestMerged': merged,
        'dateVerified': bool(pairs) and all(day is not None for day, _ in pairs),
    }


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
                       latest: Optional[float] = None,
                       quote_change_pct: Optional[float] = None,
                       dates=None, latest_date=None) -> Dict[str, Any]:
    """由收盤價序列＋可選當日即時價，建趨勢量化指標。

    closes: 由舊到新的日線收盤價。
    latest: 同標的的即時報價，用於更新當前水位／均線偏離。
    quote_change_pct: 若即時報價提供官方昨收漲跌幅，必須傳入；它優先於
        日線快取相鄰兩筆的推算，避免換月、夜盤或日線落後時顯示相反方向。

    回傳：chgPct 是即時報價的官方漲跌幅（若有）；streak／trend 仍為日線趨勢。
    """
    empty = {
        'close': None, 'chgPct': None, 'ma5': None, 'vsMa5Pct': None,
        'z20': None, 'momScore': None, 'streak': None,
        'trend': None, 'level': None, 'n': 0, 'spark': [],
    }
    rows = list(closes or [])
    if rows and isinstance(rows[0], dict):
        dates = [row.get('sourceDate') or row.get('date') for row in rows]
        rows = [row.get('close') for row in rows]
    series, quality = merge_dated_series(rows, list(dates or []), latest, latest_date)
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
    quote_chg = None
    if quote_change_pct is not None:
        try:
            candidate = float(quote_change_pct)
            if math.isfinite(candidate):
                quote_chg = candidate
        except Exception:
            pass
    display_chg = quote_chg if quote_chg is not None else chg
    mom = momentum_score(vs_ma5, z20, display_chg)
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
        # 即時報價的昨收基準優先；日線相鄰值只在沒有報價時計算備援。
        'chgPct': round(display_chg, 2) if display_chg is not None else None,
        'ma5': round(ma5, 4) if ma5 is not None else None,
        'vsMa5Pct': round(vs_ma5, 2) if vs_ma5 is not None else None,
        'z20': round(z20, 2) if z20 is not None else None,
        'momScore': round(mom, 1),
        'streak': streak if streak != 0 else 0,
        'trend': trend,
        'level': level,
        'n': len(series),
        'spark': spark,
        **quality,
    }
