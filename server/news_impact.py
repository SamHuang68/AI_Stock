#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic news entity/scope/impact tags.

Tags describe likely review priority, never price direction or a trade action.
"""
from __future__ import annotations

from typing import Any, Iterable


_HIGH = (
    '重大訊息', '財務預測', '財測', '財報', '法說', '併購', '收購', '合併', '破產',
    '停產', '召回', '下市', '處分', '訴訟', 'earnings', 'guidance', 'acquisition',
    'merger', 'bankruptcy', 'recall', '8-k',
)
_MEDIUM = (
    '訂單', '供應', '合作', '核准', '股利', '增資', '減資', '投資', '擴產', '董事會',
    'contract', 'approval', 'partnership', 'dividend', 'offering', 'capacity',
)
_AI_CHAIN = {'NVDA', 'AMD', 'AVGO', 'TSM', 'SMCI', 'MU', 'QCOM'}


def tag_item(item: dict[str, Any] | None) -> dict[str, Any]:
    item = dict(item or {})
    title = str(item.get('title') or '')
    clause = str(item.get('clause') or '')
    cat = str(item.get('cat') or '')
    text = f'{title} {clause} {cat}'.lower()
    code = str(item.get('code') or '').upper()
    market = str(item.get('mkt') or 'TW').upper()

    tier, rule_id, reason, confidence = 'LOW', 'news.priority.default.v1', '一般公司／市場事件', 0.58
    if any(k.lower() in text for k in _HIGH):
        tier, rule_id, reason, confidence = 'HIGH', 'news.priority.material.v1', '重大公司事件、財報或法定揭露', 0.88
    elif any(k.lower() in text for k in _MEDIUM):
        tier, rule_id, reason, confidence = 'MEDIUM', 'news.priority.corporate.v1', '可能影響營運、資本或供應關係', 0.74

    scopes = [f'{market}_SINGLE_NAME' if code else f'{market}_MARKET']
    if code in _AI_CHAIN or any(k in text for k in ('ai', '人工智慧', '伺服器', '半導體', '晶片', 'gpu')):
        scopes.append('AI_SUPPLY_CHAIN')
        if market == 'US':
            scopes.append('TW_AI_SPILLOVER')
    if any(k in text for k in ('利率', '通膨', '央行', 'fed', 'tariff', '關稅', '匯率')):
        scopes.append('MACRO')

    return {
        'tier': tier,
        'ruleId': rule_id,
        'reason': reason,
        'confidence': confidence,
        'entity': {'code': item.get('code'), 'name': item.get('name')},
        'scope': list(dict.fromkeys(scopes)),
        'source': item.get('source') or 'unknown',
        'asOf': item.get('time') or None,
        'direction': 'unknown',
    }


def tag_items(items: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    out = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        item = dict(raw)
        item['impact'] = tag_item(item)
        out.append(item)
    return out
