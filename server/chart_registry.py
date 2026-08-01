# -*- coding: utf-8 -*-
"""
圖表註冊表 — 單一真理來源（H0 housekeeping）

前後端必須對齊：
  - id：特殊圖代號（__TW_MARGIN_MIX__ 等）
  - primaryKey：格上報價／/yf 相容路徑的主序列（绝不可用右軸指數）
  - scale of primary：一律 left（或明確指定）

前端對應：src/core/chart_registry_v3.js
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# 主序列 key：格上數值、Yahoo-shaped 相容路徑都吃這個
CHART_PRIMARY_KEYS: Dict[str, str] = {
    '__TW_RATES__': 'discount',
    '__TW_MARGIN_MIX__': 'yoy',
    '__TW_MARGIN_CYCLE__': 'margin_ratio',
    '__US_RATES_CREDIT__': 'fedfunds',
    '__US_CPI_FIN__': 'us_cpi_yoy',
    '__MARGIN_RATIO__': 'margin_ratio',
    # holders 圖 id 動態 __HOLDERS_2330__ — 用 prefix 規則
}

HOLDERS_PRIMARY_KEY = 'major_pct'  # 集中度格上以大股東%為主（人數為左軸直方）

MACRO_TRACK_IDS = (
    '__TW_RATES__',
    '__TW_MARGIN_MIX__',
    '__TW_MARGIN_CYCLE__',
    '__US_RATES_CREDIT__',
    '__US_CPI_FIN__',
)


def normalize_chart_id(sym: Optional[str]) -> str:
    return str(sym or '').strip().upper()


def is_holders_chart(cid: str) -> bool:
    c = normalize_chart_id(cid)
    return c.startswith('__HOLDERS_') and c.endswith('__')


def primary_key_for(chart_id: str) -> Optional[str]:
    cid = normalize_chart_id(chart_id)
    if cid in CHART_PRIMARY_KEYS:
        return CHART_PRIMARY_KEYS[cid]
    if is_holders_chart(cid):
        return HOLDERS_PRIMARY_KEY
    return None


def pick_primary_series(series: List[Dict[str, Any]], chart_id: str) -> Optional[Dict[str, Any]]:
    """
    選主序列：先依註冊表 key；再退左軸有點的序列。
    绝不退回 scale=='right'（避免加權／XLF 被當成 YoY%）。
    """
    series = series or []
    want = primary_key_for(chart_id)
    if want:
        for s in series:
            if s.get('key') == want and s.get('points'):
                return s
    for s in series:
        if s.get('scale') == 'left' and s.get('points'):
            return s
    return None
