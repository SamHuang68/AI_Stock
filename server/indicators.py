# -*- coding: utf-8 -*-
"""
技術指標精算（鐵律：RSI / SMA 必須精確，禁止概略）

SMA：簡單算術平均
RSI：Wilder smoothing（與 TradingView / 主流券商一致）
"""
from __future__ import annotations

from typing import List, Optional, Sequence


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
