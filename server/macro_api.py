# -*- coding: utf-8 -*-
"""
Macro / 特殊圖 Yahoo-shaped 相容層（從 server.py 拆出 · H2）
"""
from __future__ import annotations

from typing import Any, Dict, Optional

import chart_registry as cr


def get_macro_track_chart_json(sym: str, rng: Optional[str] = None) -> Dict[str, Any]:
    """MacroMicro 風格多序列 → Yahoo-compatible（只帶主序列）。完整多序列走 /macro/chart/<id>。"""
    try:
        import macro_track as mt
        years = 25
        if rng in ('1y', '12mo'):
            years = 1
        elif rng in ('2y',):
            years = 2
        elif rng in ('5y',):
            years = 5
        elif rng in ('10y',):
            years = 10
        full = mt.get_chart(sym, years=years)
        primary = cr.pick_primary_series(full.get('series') or [], full.get('id') or sym)
        pts = (primary or {}).get('points') or []
        return mt.points_to_yf_like(pts, full['id'], full['name'])
    except Exception as e:
        print('[macro_api] get_macro_track_chart_json failed:', e)
        return {'chart': {'result': None, 'error': str(e)}}
