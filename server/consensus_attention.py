#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Deterministic attention projection over canonical DecisionContext.

This module does not fetch, poll, predict, or mutate the decision contract.
It compresses already-published evidence into a bounded attention queue for
the floating Consensus Radar.  ``attentionScore`` is a ranking score, never a
probability or trading instruction.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any


CONTRACT_VERSION = 1
MODEL_VERSION = 'st-consensus-attention/v1'
RANKING_VERSION = 'attention-ranking/v1'
MAX_VISIBLE = 3
MAX_ITEMS = 5
ACTIONABLE_STATES = {'WATCH', 'ARMED', 'CONFIRMED', 'ACTIVE', 'CONFLICT'}
STATE_WEIGHT = {
    'OBSERVATION': 0.28, 'RECOVERY': 0.34, 'INVALIDATED': 0.18,
    'WATCH': 0.62, 'CONFLICT': 0.68, 'ARMED': 0.78,
    'CONFIRMED': 0.90, 'ACTIVE': 1.0,
}
SEVERITY_WEIGHT = {
    'observation': 0.45, 'info': 0.58, 'watch': 0.72,
    'warning': 0.88, 'critical': 1.0,
}
CONFLICT_IDS = {
    'FLOW_PRICE_CONFLICT', 'SPOT_FUTURES_CONFLICT', 'TW_US_TECH_DIVERGENCE',
}


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
        return parsed if parsed == parsed and abs(parsed) != float('inf') else default
    except (TypeError, ValueError):
        return default


def _clamp(value: Any, lo: float = 0.0, hi: float = 1.0) -> float:
    parsed = _number(value, lo)
    return max(lo, min(hi, float(parsed)))


def _iso_plus(value: Any, hours: int = 24) -> str | None:
    try:
        parsed = datetime.fromisoformat(str(value or '').replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return (parsed + timedelta(hours=hours)).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _source_domain(evidence_id: Any) -> str:
    evidence_id = str(evidence_id or '').lower()
    if evidence_id.startswith(('twii.', 'anchor.twii')):
        return 'tw_index_price'
    if evidence_id.startswith(('breadth.', 'sector.')):
        return 'tw_breadth_participation'
    if evidence_id.startswith(('flow.', 'risk.margin')):
        return 'tw_cash_flow'
    if evidence_id.startswith(('txf.', 'basis.', 'options.')):
        return 'tw_derivatives'
    if evidence_id.startswith(('global.', 'anchor.adr')):
        return 'global_technology'
    if evidence_id.startswith('anchor.'):
        return 'ai_anchor_chain'
    if evidence_id.startswith(('memory.', 'research.overnight')):
        return 'memory_cycle'
    if evidence_id.startswith(('portfolio.', 'exposure.')):
        return 'owner_portfolio'
    return evidence_id.split('.', 1)[0] or 'unknown'


def _freshness(context: dict[str, Any], expires_at: str | None = None) -> dict[str, Any]:
    quality = context.get('dataQuality') or {}
    score = _clamp(quality.get('freshness'))
    stale_fields = list(quality.get('staleFields') or [])
    status = 'fresh' if score >= 0.65 else ('degraded' if score >= 0.35 else 'stale')
    return {
        'asOf': context.get('asOf'), 'expiresAt': expires_at or _iso_plus(context.get('asOf')),
        'status': status, 'score': round(score, 3), 'staleFields': stale_fields,
    }


def _event_key(item_id: str, session_id: str, state: str, severity: str, direction: str) -> str:
    raw = f'{item_id}|{session_id}|{state}|{severity}|{direction}'
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24]


def _rank(item: dict[str, Any]) -> float:
    state = STATE_WEIGHT.get(str(item.get('lifecycleState') or 'OBSERVATION'), 0.25)
    severity = SEVERITY_WEIGHT.get(str(item.get('severity') or 'observation'), 0.45)
    strength = max(0.18, _clamp((_number(item.get('strength'), 0.0) or 0.0) / 100.0))
    quality = max(0.25, _clamp(item.get('evidenceQuality')))
    domains = max(1, int(_number(item.get('independentDomains'), 0) or 0))
    agreement = min(1.0, 0.35 + 0.22 * domains)
    conflict_penalty = 0.78 if (item.get('conflict') or {}).get('flag') else 1.0
    freshness = 1.0 if (item.get('freshness') or {}).get('status') == 'fresh' else 0.55
    novelty = _clamp(item.get('novelty'), 0.25, 1.0)
    score = state * severity * strength * quality * agreement * conflict_penalty * freshness * novelty
    return round(score * 100.0, 1)


def _finalize(item: dict[str, Any], context: dict[str, Any], session_id: str) -> dict[str, Any]:
    evidence_ids = sorted(set(str(row) for row in item.get('evidenceIds') or [] if row))
    source_domains = sorted(set(_source_domain(row) for row in evidence_ids))
    if item.get('sourceDomains'):
        source_domains = sorted(set(source_domains + list(item['sourceDomains'])))
    freshness = item.get('freshness') or _freshness(context, item.get('expiresAt'))
    item = {
        **item,
        'evidenceIds': evidence_ids,
        'sourceDomains': source_domains,
        'independentDomains': max(int(_number(item.get('independentDomains'), 0) or 0), len(source_domains)),
        'freshness': freshness,
        'authority': 'attention_only',
    }
    item['agreement'] = round(min(1.0, 0.35 + 0.22 * max(1, item['independentDomains'])), 3)
    item['eventKey'] = _event_key(
        str(item.get('id')), session_id, str(item.get('lifecycleState')),
        str(item.get('severity')), str(item.get('direction')),
    )
    item['generation'] = item['eventKey']
    item['attentionScore'] = _rank(item)
    return item


def _structure_item(context: dict[str, Any]) -> dict[str, Any]:
    regime = context.get('regime') or {}
    divergences = list(context.get('divergences') or [])
    ranked = sorted(
        divergences,
        key=lambda row: ({'critical': 3, 'warning': 2, 'info': 1}.get(str(row.get('severity')), 0),
                         _number(row.get('confidence'), 0.0) or 0.0),
        reverse=True,
    )
    lead = ranked[0] if ranked else {}
    severity = str(lead.get('severity') or 'info')
    lifecycle = 'ARMED' if severity == 'critical' else ('WATCH' if severity == 'warning' else 'OBSERVATION')
    regime_id = str(regime.get('id') or 'INSUFFICIENT_DATA')
    direction = ('upside' if regime_id == 'BROAD_RISK_ON' else
                 'downside' if regime_id in ('DEFENSIVE_RISK_OFF', 'CAPITULATION') else 'mixed')
    conflicts = [str(row.get('id')) for row in ranked if str(row.get('id')) in CONFLICT_IDS]
    evidence_ids = [eid for row in ranked[:3] for eid in row.get('evidenceIds') or []]
    env = context.get('actionEnvelope') or {}
    return {
        'id': 'MARKET_STRUCTURE', 'theme': 'market_structure',
        'title': str(regime.get('label') or '市場結構等待確認'), 'market': 'TW',
        'direction': direction, 'severity': severity, 'lifecycleState': lifecycle,
        'strength': round((_number(lead.get('confidence'), regime.get('confidence')) or 0.0) * 100.0, 1),
        'evidenceQuality': _clamp((context.get('dataQuality') or {}).get('completeness')),
        'evidenceIds': evidence_ids,
        'insight': str(lead.get('insight') or '以市場狀態、廣度與資金結構決定注意優先序。'),
        'confirmation': str(lead.get('confirmation') or (env.get('confirmation') or ['等待結構同向'])[0]),
        'invalidation': str(lead.get('invalidation') or (env.get('invalidation') or ['核心結構反轉'])[0]),
        'conflict': {'flag': bool(conflicts), 'reasons': conflicts},
        'novelty': 0.82 if lifecycle != 'OBSERVATION' else 0.55,
        'navigation': {'route': 'decision', 'focusSection': 'divergences', 'highlightId': lead.get('id')},
        'privacyClass': 'shared_market',
    }


def _signal_item(signal: dict[str, Any], theme: str, title: str) -> dict[str, Any]:
    state = str(signal.get('state') or 'OBSERVATION')
    direction = str(signal.get('direction') or 'mixed')
    reasons = list(signal.get('reasons') or [])
    counters = list(signal.get('strongestCounterEvidence') or [])
    tier = str(signal.get('tier') or ('info' if state == 'WATCH' else 'observation'))
    return {
        'id': str(signal.get('signalId') or theme).upper(), 'theme': theme, 'title': title,
        'market': 'TW_CROSS_MARKET', 'direction': direction, 'severity': tier,
        'lifecycleState': state,
        'strength': round(_number(signal.get('strength'), 0.0) or 0.0, 1),
        'evidenceQuality': _clamp(signal.get('evidenceQuality')),
        'independentDomains': int(_number(signal.get('independentDomains'), 0) or 0),
        'evidenceIds': signal.get('evidenceIds') or [],
        'insight': '；'.join(reasons[:2]) if reasons else '來源尚未形成足夠同向共識。',
        'confirmation': str(signal.get('confirmation') or '等待跨市場來源同向'),
        'invalidation': str(signal.get('invalidation') or '核心方向反轉'),
        'conflict': {'flag': direction == 'mixed', 'reasons': counters[:2] or (['核心來源未同向'] if direction == 'mixed' else [])},
        'novelty': 1.0 if state in ACTIONABLE_STATES else 0.48,
        'expiresAt': signal.get('expiresAt'),
        'navigation': {'route': 'decision', 'focusSection': 'precursors',
                       'highlightId': signal.get('signalId')},
        'privacyClass': 'shared_market',
    }


def _precursor_item(signals: list[dict[str, Any]]) -> dict[str, Any] | None:
    headline = [row for row in signals if row.get('signalId') in
                ('TW_DOWNSIDE_PRECURSOR', 'TW_ATTACK_BUILDUP')]
    if not headline:
        return None
    actionable = [row for row in headline if str(row.get('state')) in ACTIONABLE_STATES]
    if len(actionable) >= 2 and len({row.get('direction') for row in actionable}) > 1:
        chosen = max(actionable, key=lambda row: _number(row.get('strength'), 0.0) or 0.0)
        item = _signal_item(chosen, 'headline_precursor', '台股方向前兆衝突')
        item['id'] = 'TW_PRECURSOR_CONFLICT'
        item['direction'] = 'mixed'
        item['lifecycleState'] = 'CONFLICT'
        item['severity'] = 'watch'
        item['conflict'] = {'flag': True, 'reasons': [str(row.get('label')) for row in actionable]}
        item['evidenceIds'] = [eid for row in actionable for eid in row.get('evidenceIds') or []]
        return item
    chosen = max(actionable or headline, key=lambda row: (
        STATE_WEIGHT.get(str(row.get('state')), 0.0), _number(row.get('strength'), 0.0) or 0.0))
    return _signal_item(chosen, 'headline_precursor', str(chosen.get('label') or '台股方向前兆'))


def _owner_exposure_item(context: dict[str, Any]) -> dict[str, Any] | None:
    portfolio = context.get('portfolioOverlay') or {}
    exposure = context.get('exposureLab') or {}
    temperature = exposure.get('temperature') or {}
    if portfolio.get('kind') != 'actual' or not portfolio.get('available') or temperature.get('score') is None:
        return None
    score = _number(temperature.get('score'), 0.0) or 0.0
    tone = str(temperature.get('tone') or 'unknown')
    state = str(temperature.get('state') or '資料不足')
    lifecycle = 'WATCH' if tone in ('watch', 'hot') else 'OBSERVATION'
    severity = 'warning' if tone == 'hot' else ('watch' if tone == 'watch' else 'info')
    look = portfolio.get('lookThrough') or {}
    components = temperature.get('components') or []
    return {
        'id': 'OWNER_EXPOSURE', 'theme': 'owner_exposure', 'title': f'持倉曝險{state}',
        'market': 'OWNER_PORTFOLIO', 'direction': 'risk', 'severity': severity,
        'lifecycleState': lifecycle, 'strength': round(score, 1),
        'evidenceQuality': _clamp((context.get('dataQuality') or {}).get('completeness')),
        'evidenceIds': ['portfolio.look_through', 'exposure.temperature'],
        'sourceDomains': ['owner_portfolio'],
        'insight': ('穿透總曝險 ' + str(look.get('effectiveGrossExposurePct')) + '%')
                   if look.get('effectiveGrossExposurePct') is not None else '持倉風險條件已載入。',
        'confirmation': '曝險壓力燈號下降且限制條件解除',
        'invalidation': '持倉或風險設定變更後必須重新計算',
        'conflict': {'flag': False, 'reasons': []}, 'novelty': 0.72,
        'navigation': {'route': 'decision', 'focusSection': 'exposure', 'highlightId': tone},
        'privacyClass': 'owner_only',
        'components': [{k: row.get(k) for k in ('key', 'label', 'score', 'state')} for row in components],
    }


def build_consensus_attention(context: dict[str, Any] | None) -> dict[str, Any]:
    """Build a replayable, bounded attention queue from one DecisionContext."""
    context = context or {}
    as_of = context.get('asOf')
    session_id = f"{context.get('market') or 'TW'}:{str(as_of or 'unknown')[:10]}"
    warning = context.get('earlyWarnings') or {}
    signals = list(warning.get('signals') or [])
    candidates: list[dict[str, Any]] = [_structure_item(context)]
    precursor = _precursor_item(signals)
    if precursor:
        candidates.append(precursor)
    by_id = {str(row.get('signalId')): row for row in signals}
    for signal_id, theme, title in (
        ('AI_WAFER_DOUBLE_ARROW', 'ai_anchor_chain', 'AI 雙箭頭晶圓連動'),
        ('MEMORY_CYCLE_RESONANCE', 'memory_cycle', '記憶體週期共振'),
    ):
        if signal_id in by_id:
            candidates.append(_signal_item(by_id[signal_id], theme, title))
    owner = _owner_exposure_item(context)
    if owner:
        candidates.append(owner)
    items = [_finalize(row, context, session_id) for row in candidates]
    items.sort(key=lambda row: (row['attentionScore'], row['strength'], row['id']), reverse=True)
    items = items[:MAX_ITEMS]
    actionable = [row for row in items if row.get('lifecycleState') in ACTIONABLE_STATES
                  and (row.get('freshness') or {}).get('status') == 'fresh']
    severity_rank = {'critical': 4, 'warning': 3, 'watch': 2, 'info': 1, 'observation': 0}
    top_severity = max((str(row.get('severity')) for row in actionable),
                       key=lambda value: severity_rank.get(value, 0), default='observation')
    return {
        'contractVersion': CONTRACT_VERSION, 'model': MODEL_VERSION,
        'rankingVersion': RANKING_VERSION, 'generatedAt': as_of, 'sessionId': session_id,
        'baselineAsOf': as_of, 'authority': 'attention_only',
        'maxVisible': MAX_VISIBLE, 'maxItems': MAX_ITEMS,
        'actionableCount': len(actionable), 'monitoringCount': len(items) - len(actionable),
        'topSeverity': top_severity, 'items': items,
        'policy': {
            'strengthIsProbability': False, 'aiMayTrigger': False,
            'staleDataMayAlert': False, 'observationIncrementsBadge': False,
            'newsIsNumericEvidence': False,
        },
    }


def empty(reason: str = 'decision_context_unavailable') -> dict[str, Any]:
    return {
        'contractVersion': CONTRACT_VERSION, 'model': MODEL_VERSION,
        'rankingVersion': RANKING_VERSION, 'generatedAt': None, 'sessionId': None,
        'baselineAsOf': None, 'authority': 'attention_only', 'maxVisible': MAX_VISIBLE,
        'maxItems': MAX_ITEMS, 'actionableCount': 0, 'monitoringCount': 0,
        'topSeverity': 'observation', 'items': [], 'reason': reason,
        'policy': {'strengthIsProbability': False, 'aiMayTrigger': False,
                   'staleDataMayAlert': False, 'observationIncrementsBadge': False,
                   'newsIsNumericEvidence': False},
    }
