# -*- coding: utf-8 -*-
"""以官方產業分類建立上市個股清單，保留來源交易日與缺值。"""
from __future__ import annotations

import math
import re
from datetime import date
from typing import Any

from sector_flow import build_sector_flow, normalize_sector_name, normalize_session_date


CLASSIFICATION_SOURCE = '臺灣證券交易所月營收公開資料 t187ap05_L 產業別'
QUOTE_SOURCE = '臺灣證券交易所 STOCK_DAY_ALL 日收盤'

# 只沿用現有官方產業分類，不把主題指數或代表股當成完整成分。
_ALIASES = {'金融': '金融保險', '營建': '建材營造', '觀光': '觀光餐旅'}
_ELECTRONICS = {
    '半導體', '電腦及週邊設備', '光電', '通信網路',
    '電子零組件', '電子通路', '資訊服務', '其他電子',
}
_GROUPS = {'電子': _ELECTRONICS}


def source_date(value: Any) -> str | None:
    """轉換西元或民國來源日期；不以讀取日期代替交易日。"""
    normalized = normalize_session_date(value)
    if normalized is None:
        return None
    try:
        return date(int(normalized[:4]), int(normalized[4:6]), int(normalized[6:])).isoformat()
    except ValueError:
        return None


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace(',', '').strip())
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def empty_payload(market: str, sector: str, reason: str, *, ok: bool = True) -> dict[str, Any]:
    return {
        'ok': ok, 'market': market, 'sector': sector,
        'sectorKey': normalize_sector_name(sector),
        'scope': 'UNAVAILABLE', 'scopeLabel': '未提供個股清單',
        'date': None, 'source': None, 'classificationSource': None,
        'count': 0, 'rows': [], 'unavailableReason': reason,
    }


def build_tw_members(snapshot: dict[str, Any], sector: str) -> dict[str, Any]:
    """篩選同產業上市普通股；不限制排行筆數、不排除無成交或漲跌缺值。"""
    key = normalize_sector_name(sector)
    key = _ALIASES.get(key, key)
    if not snapshot.get('twseAvailable'):
        return empty_payload('TW', sector, '上市日行情暫時無法取得，請稍後重新整理。', ok=False)
    if not snapshot.get('classificationCount'):
        return empty_payload('TW', sector, '官方產業分類暫時無法取得，請稍後重新整理。', ok=False)

    source_rows = snapshot.get('rows') or []
    available = {normalize_sector_name(row.get('industry')) for row in source_rows if isinstance(row, dict)}
    wanted = _GROUPS.get(key, {key})
    if not key or not (wanted & available):
        return empty_payload('TW', sector, '此指數未提供可核對的個股成分來源；官方產業分類無法直接對應這個指數。')

    rows = []
    seen = set()
    for raw in source_rows:
        if not isinstance(raw, dict):
            continue
        code = str(raw.get('code') or '').strip()
        if raw.get('ex') != 'TWSE' or not re.fullmatch(r'[1-9]\d{3}', code) or code in seen:
            continue
        if normalize_sector_name(raw.get('industry')) not in wanted:
            continue
        seen.add(code)
        rows.append({
            'code': code, 'name': str(raw.get('name') or code),
            'price': _number(raw.get('price')), 'change': _number(raw.get('change')),
            'changePct': _number(raw.get('changePct')),
            'industry': str(raw.get('industry') or ''), 'ex': 'TWSE',
            'asOf': source_date(raw.get('asOf')),
        })
    rows.sort(key=lambda row: (
        row['changePct'] is None,
        -(row['changePct'] if row['changePct'] is not None else 0), row['code']))
    dates = {row['asOf'] for row in rows}
    day = next(iter(dates)) if len(dates) == 1 and None not in dates else None
    group = key in _GROUPS
    return {
        'ok': True, 'market': 'TW', 'sector': sector, 'sectorKey': key,
        'scope': 'TWSE_INDUSTRY_GROUP' if group else 'TWSE_INDUSTRY',
        'scopeLabel': '上市電子相關產業個股' if group else '同產業上市個股',
        'date': day, 'source': QUOTE_SOURCE, 'classificationSource': CLASSIFICATION_SOURCE,
        'count': len(rows), 'rows': rows, 'unavailableReason': None,
    }


def sector_cache_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """總覽與熱力圖共用完整來源資料，避免最早快取寫入者遺失交易日。"""
    out = dict(payload)
    if not out.get('sectorFlow') and out.get('sectors'):
        out['sectorFlow'] = build_sector_flow(
            out['sectors'], market_scope='TWSE', source=out.get('source') or '未提供',
            as_of=source_date(out.get('date')))
    return out
