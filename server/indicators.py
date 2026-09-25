# -*- coding: utf-8 -*-
"""
技術指標精算（鐵律：RSI / SMA 必須精確，禁止概略）

SMA：簡單算術平均
RSI：Wilder smoothing（與 TradingView / 主流券商一致）
EMA：alpha = 2/(n+1)，以前 n 根 SMA 為種子（TradingView ta.ema 慣例）
MACD：EMA12 − EMA26；Signal = MACD 線的 EMA9；Hist = MACD − Signal
Bollinger：SMA20 ± 2 × 母體標準差（除以 n，TradingView ta.stdev 預設）
ATR：Wilder RMA of True Range（首根 TR = high − low；TradingView ta.atr 慣例）

所有推播 daemon、個股訊號引擎與盤後摘要共用本檔；禁止各模組自寫近似版。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence


Number = float


def sma(values: Sequence[Optional[Number]], period: int, idx: Optional[int] = None) -> Optional[float]:
    """SMA at idx (default: last). Needs period finite values ending at idx."""
    if period <= 0:
        return None
    if idx is None:
        idx = len(values) - 1
    if idx < 0 or idx + 1 < period:
        return None
    window = values[idx - period + 1 : idx + 1]
    if any(v is None for v in window):
        return None
    return float(sum(window)) / float(period)


def rsi_wilders(prices: Sequence[Number], period: int = 14) -> Optional[float]:
    """
    Wilder's RSI.
    需要至少 period+1 根收盤價。
    avg_loss==0 → 100；標準公式 100 - 100/(1+RS)。
    """
    if period <= 0:
        return None
    n = len(prices)
    if n <= period:
        return None
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, n):
        diff = float(prices[i]) - float(prices[i - 1])
        if diff > 0:
            gains.append(diff)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(-diff)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def rsi_wilders_series(prices: Sequence[Number], period: int = 14) -> List[Optional[float]]:
    """逐根 RSI（前 period 根為 None）。用於回歸比對。"""
    out: List[Optional[float]] = [None] * len(prices)
    if len(prices) <= period:
        return out
    gains: List[float] = []
    losses: List[float] = []
    for i in range(1, len(prices)):
        diff = float(prices[i]) - float(prices[i - 1])
        gains.append(diff if diff > 0 else 0.0)
        losses.append(-diff if diff < 0 else 0.0)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    # RSI at index == period (after period changes from prices[0..period])
    if avg_loss == 0:
        out[period] = 100.0
    else:
        rs = avg_gain / avg_loss
        out[period] = 100.0 - (100.0 / (1.0 + rs))
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            out[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            out[i + 1] = 100.0 - (100.0 / (1.0 + rs))
    return out


def sma_series(values: Sequence[Optional[Number]], period: int) -> List[Optional[float]]:
    """逐根 SMA；每點與 sma(values, period, i) 完全相同（同一加總順序，無滾動誤差）。"""
    return [sma(values, period, i) for i in range(len(values))]


def ema_series(values: Sequence[Optional[Number]], period: int) -> List[Optional[float]]:
    """逐根 EMA（alpha=2/(n+1)，以首段連續 n 根 SMA 為種子）。

    前置 None（例如 MACD 線尚未成形）會被略過；種子成形後若再遇 None 即停止，
    不以前值外插，避免把缺值偷偷補成連續序列。
    """
    out: List[Optional[float]] = [None] * len(values)
    if period <= 0:
        return out
    start = None
    run = 0
    for i, v in enumerate(values):
        run = run + 1 if v is not None else 0
        if run == period:
            start = i
            break
    if start is None:
        return out
    seed_window = values[start - period + 1 : start + 1]
    prev = float(sum(seed_window)) / float(period)
    out[start] = prev
    alpha = 2.0 / (period + 1.0)
    for i in range(start + 1, len(values)):
        v = values[i]
        if v is None:
            break
        prev = alpha * float(v) + (1.0 - alpha) * prev
        out[i] = prev
    return out


def macd_series(closes: Sequence[Number], fast: int = 12, slow: int = 26,
                signal: int = 9) -> Dict[str, List[Optional[float]]]:
    """MACD 線、Signal 線、柱狀體（皆為逐根序列）。"""
    ema_fast = ema_series(closes, fast)
    ema_slow = ema_series(closes, slow)
    line: List[Optional[float]] = [
        (f - s) if f is not None and s is not None else None
        for f, s in zip(ema_fast, ema_slow)
    ]
    sig = ema_series(line, signal)
    hist: List[Optional[float]] = [
        (m - s) if m is not None and s is not None else None
        for m, s in zip(line, sig)
    ]
    return {'macd': line, 'signal': sig, 'hist': hist}


def stdev_population(values: Sequence[Optional[Number]], period: int,
                     idx: Optional[int] = None) -> Optional[float]:
    """母體標準差（除以 n），與 Bollinger / TradingView ta.stdev 預設一致。"""
    mean = sma(values, period, idx)
    if mean is None:
        return None
    if idx is None:
        idx = len(values) - 1
    window = values[idx - period + 1 : idx + 1]
    var = sum((float(x) - mean) ** 2 for x in window) / float(period)
    return math.sqrt(var)


def bollinger_series(closes: Sequence[Number], period: int = 20,
                     k: float = 2.0) -> Dict[str, List[Optional[float]]]:
    """Bollinger 中軌／上軌／下軌與相對帶寬 (upper-lower)/mid。"""
    mid: List[Optional[float]] = []
    upper: List[Optional[float]] = []
    lower: List[Optional[float]] = []
    width: List[Optional[float]] = []
    for i in range(len(closes)):
        m = sma(closes, period, i)
        sd = stdev_population(closes, period, i) if m is not None else None
        if m is None or sd is None:
            mid.append(None); upper.append(None); lower.append(None); width.append(None)
            continue
        u, lo = m + k * sd, m - k * sd
        mid.append(m); upper.append(u); lower.append(lo)
        width.append((u - lo) / m if m else None)
    return {'mid': mid, 'upper': upper, 'lower': lower, 'width': width}


def true_range_series(highs: Sequence[Number], lows: Sequence[Number],
                      closes: Sequence[Number]) -> List[float]:
    """True Range；首根沒有前收，TR = high − low。"""
    out: List[float] = []
    for i in range(len(closes)):
        h, lo = float(highs[i]), float(lows[i])
        if i == 0:
            out.append(h - lo)
            continue
        pc = float(closes[i - 1])
        out.append(max(h - lo, abs(h - pc), abs(lo - pc)))
    return out


def atr_wilders_series(highs: Sequence[Number], lows: Sequence[Number],
                       closes: Sequence[Number], period: int = 14) -> List[Optional[float]]:
    """ATR（Wilder RMA）：第 period 根以前 period 個 TR 平均為種子。"""
    out: List[Optional[float]] = [None] * len(closes)
    if period <= 0 or len(closes) < period:
        return out
    tr = true_range_series(highs, lows, closes)
    prev = sum(tr[:period]) / float(period)
    out[period - 1] = prev
    for i in range(period, len(tr)):
        prev = (prev * (period - 1) + tr[i]) / float(period)
        out[i] = prev
    return out


def prior_extreme(values: Sequence[Number], period: int, idx: Optional[int] = None,
                  *, highest: bool = True) -> Optional[float]:
    """idx 之前 period 根（不含 idx 當根）的最高／最低；突破判斷用，避免自己比自己。"""
    if idx is None:
        idx = len(values) - 1
    if period <= 0 or idx - period < 0:
        return None
    window = [float(v) for v in values[idx - period : idx]]
    return max(window) if highest else min(window)


def candle_snapshot(candles: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """推播 daemon／選股共用的單點指標快照（由舊到新的日 K）。

    欄位與前端 pro_v2 computeIndicators 對齊：sma5/20/60、Wilder RSI14、
    Bollinger(20, 2σ 母體)、5/20 日均量比、前 20 日高低（不含當根）。
    rsiPrevMin5 = 當根之前 5 根 RSI 的最小值，供「曾跌破 30 後回升」這類跨越判斷。
    資料不足的欄位回 None，由呼叫端決定不觸發，而不是用 0 或 50 補值。
    """
    closes = [float(c['close']) for c in candles]
    highs = [float(c.get('high') if c.get('high') is not None else c['close']) for c in candles]
    lows = [float(c.get('low') if c.get('low') is not None else c['close']) for c in candles]
    vols = [float(c.get('volume') or 0) for c in candles]
    n = len(closes)
    if n == 0:
        return {'close': None, 'sma5': None, 'sma20': None, 'sma60': None, 'rsi14': None,
                'rsiPrevMin5': None, 'bbL': None, 'bbU': None, 'bbMid': None,
                'volRatio': None, 'high20': None, 'low20': None, 'highs': []}
    rsi_s = rsi_wilders_series(closes, 14)
    prev_window = [v for v in rsi_s[max(0, n - 6): n - 1] if v is not None]
    bb_mid = sma(closes, 20)
    sd20 = stdev_population(closes, 20)
    v5 = sma(vols, 5)
    v20 = sma(vols, 20)
    return {
        'close': closes[-1],
        'sma5': sma(closes, 5),
        'sma20': bb_mid,
        'sma60': sma(closes, 60),
        'rsi14': rsi_s[-1],
        'rsiPrevMin5': min(prev_window) if prev_window else None,
        'bbMid': bb_mid,
        'bbU': (bb_mid + 2.0 * sd20) if bb_mid is not None and sd20 is not None else None,
        'bbL': (bb_mid - 2.0 * sd20) if bb_mid is not None and sd20 is not None else None,
        'volRatio': (v5 / v20) if v5 is not None and v20 else None,
        'high20': prior_extreme(highs, 20, highest=True),
        'low20': prior_extreme(lows, 20, highest=False),
        'highs': highs,
    }
