# -*- coding: utf-8 -*-
"""數值的純資料契約：未知值不冒充零，非有限值不通過比較。

來源：codex/wavedeck-paper-p0（0bec06d）的 data_contract.finite_number（WD P0 第 2a 片）。
行情新鮮度（normalize_quote／assess_quote）屬下單閘門政策，另案（2b）。
"""
from __future__ import annotations

import math
from typing import Any


def finite_number(value: Any) -> float | None:
    """接受有限數值及數字字串；布林值、NaN、無限值、非數字與缺值均為未知（None）。

    NaN 的任何比較都是 False（`nan < 門檻` 不成立），所以直接拿來比較的閘門會把它放行；
    `max(0.0, nan)` 也會回 0.0，讓回撤看起來像 0%。先經過這裡再比較。"""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None
