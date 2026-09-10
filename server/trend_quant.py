# -*- coding: utf-8 -*-
"""指數／期貨價格序列趨勢量化。

與成交金額量能量化同構：vs前日／vs5日均／動能分／近20日Z／連續漲跌／趨勢標籤。
供 /pulse strip 加權、櫃買、台指期使用。
"""
from __future__ import annotations

from datetime import date
import math
from typing import Any, Dict, List, Optional, Sequence, Tuple


def session_date_key(value: Any) -> Optional[str]:
    """Normalize ROC / ISO / compact digits to YYYY-MM-DD. Unknown → None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if 'T' in text:
        text = text.split('T', 1)[0]
    parts = text.replace('-', '/').replace('.', '/').split('/')
    if len(parts) == 3:
        try:
            year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
            if year < 1911:
                year += 1911
            return date(year, month, day).isoformat()
        except (TypeError, ValueError):
            pass
    compact = ''.join(ch for ch in text if ch.isdigit())
    if len(compact) >= 8:
        compact = compact[:8]
        try:
            year, month, day = int(compact[0:4]), int(compact[4:6]), int(compact[6:8])
            return date(year, month, day).isoformat()
        except (TypeError, ValueError):
            return None
    return None


def overlay_latest(
    series: List[float],
    dates: List[Optional[str]],
    latest: float,
    latest_date: Optional[str] = None,
    *,
    same_bar: bool = False,
) -> None:
    """Update the last session in-place. Never invent a new day from a % gap.

    - empty series → append
    - same_bar or missing dates → replace last (live overlay)
    - same date → replace
    - later date → append
    - earlier date → ignore stale print
    """
    if not series:
        series.append(latest)
        dates.append(latest_date)
        return
    last_date = dates[-1] if dates else None
    if same_bar or not latest_date or not last_date:
        series[-1] = latest
        if latest_date:
            dates[-1] = latest_date
        return
    if latest_date == last_date:
        series[-1] = latest
        return
    if latest_date > last_date:
        series.append(latest)
        dates.append(latest_date)


def _parse_close_row(row: Any) -> Optional[Tuple[float, Optional[str]]]:
    if isinstance(row, dict):
        raw = row.get('close')
        if raw is None:
            raw = row.get('price')
        day = session_date_key(row.get('date') or row.get('asOf') or row.get('tradeDate'))
    else:
        raw = row
        day = None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value > 0 and math.isfinite(value):
        return value, day
    return None


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


def price_series_quant(closes: Optional[Sequence[Any]],
                       latest: Optional[float] = None,
                       quote_change_pct: Optional[float] = None,
                       latest_date: Optional[Any] = None,
                       same_bar: bool = False) -> Dict[str, Any]:
    """由收盤價序列＋可選當日即時價，建趨勢量化指標。

    closes: 由舊到新的日線收盤價，或 {'date','close'} 列。
    latest: 同標的的即時報價，用於更新當前水位／均線偏離。
    latest_date: 即時報價所屬交易日；缺日期時只覆寫最後一根，絕不因跳空 append。
    same_bar: 台指期夜盤等「仍屬同一根日 K」時強制覆寫末端。
    quote_change_pct: 若即時報價提供官方昨收漲跌幅，必須傳入；它優先於
        日線快取相鄰兩筆的推算，避免換月、夜盤或日線落後時顯示相反方向。

    回傳：chgPct 是即時報價的官方漲跌幅（若有）；streak／trend 仍為日線趨勢。
    """
    empty = {
        'close': None, 'chgPct': None, 'ma5': None, 'vsMa5Pct': None,
        'z20': None, 'momScore': None, 'streak': None,
        'trend': None, 'level': None, 'n': 0, 'spark': [],
    }
    series: List[float] = []
    dates: List[Optional[str]] = []
    for row in closes or []:
        parsed = _parse_close_row(row)
        if parsed is None:
            continue
        value, day = parsed
        series.append(value)
        dates.append(day)
    if latest is not None:
        try:
            cur0 = float(latest)
        except (TypeError, ValueError):
            cur0 = None
        if cur0 is not None and cur0 > 0 and math.isfinite(cur0):
            overlay_latest(
                series, dates, cur0, session_date_key(latest_date), same_bar=same_bar)
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
        except (TypeError, ValueError):
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
    }
