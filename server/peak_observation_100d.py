#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Observation-only 100-trading-day peak distance (st-peak-100d-v0, CONDITIONAL only).

Computes ``pctBelowPeak = lastClose / peakClose - 1`` for peakKind ``A`` within the
last ``WINDOW_TRADING_SESSIONS`` trading sessions ending at ``asOf``.

Separate contract from ``st-peak-v0.1`` — see ``docs/ST_PEAK_100D.md``.
This module does **not** write DecisionContext, actionEnvelope, or FACT labels.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Mapping, Sequence

from ohlc_ledger import OhlcBar

import peak_observation as po

CONTRACT_ID = 'st-peak-100d-v0'
PEAK_KIND = po.PEAK_KIND
LABEL = po.LABEL
DISCLAIMER_KEY = 'st-peak-100d-non-recommendation'
EPISTEMIC = po.EPISTEMIC
WINDOW_TRADING_SESSIONS = 100
DEFAULT_PRICE_BASIS = po.DEFAULT_PRICE_BASIS


def disabled_payload(reason: str = 'SHADOW_DISABLED') -> dict[str, Any]:
    return {
        'ok': False,
        'enabled': False,
        'shadowOnly': True,
        'actionAuthority': 'none',
        'decisionUse': 'research_only',
        'predictiveProbability': False,
        'epistemic': EPISTEMIC,
        'label': LABEL,
        'contractId': CONTRACT_ID,
        'disclaimerKey': DISCLAIMER_KEY,
        'hostApprovalHash': None,
        'status': 'DISABLED',
        'reason': reason,
        'observation': None,
    }


def _evidence_hash_inputs(
    *,
    symbol: str,
    as_of: str,
    history_start: str,
    price_basis: str,
    knowledge_cutoff: str,
    peak_kind: str,
    bars: Sequence[Mapping[str, Any]],
    basis_as_of: str | None,
    generation_id: str | None,
    generation_content_hash: str | None,
    source: str,
    window_days: int,
) -> dict[str, Any]:
    return {
        'contractId': CONTRACT_ID,
        'symbol': symbol,
        'asOf': as_of,
        'historyStart': history_start,
        'windowDays': window_days,
        'priceBasis': price_basis,
        'knowledgeCutoff': knowledge_cutoff,
        'peakKind': peak_kind,
        'source': source,
        'basisAsOf': basis_as_of,
        'generationId': generation_id,
        'generationContentHash': generation_content_hash,
        'bars': [
            {
                'sessionDate': str(row.get('sessionDate') or row.get('session_date') or ''),
                'close': row.get('close'),
                'ingestedAt': row.get('ingestedAt') or row.get('ingested_at'),
                'generationId': row.get('generationId') or row.get('generation_id'),
            }
            for row in bars
        ],
    }


def _history_start_for_window(
    bars: Sequence[OhlcBar],
    as_of: str,
    window_sessions: int = WINDOW_TRADING_SESSIONS,
) -> tuple[str, str | None]:
    """Return historyStart for the trailing trading-session window."""
    as_of_date = po._parse_session_date(as_of)
    eligible = sorted(
        [row for row in bars if po._parse_session_date(row.session_date) <= as_of_date],
        key=lambda row: row.session_date,
    )
    if not eligible:
        raise ValueError('no PIT bars through asOf')

    limitation: str | None = None
    if len(eligible) < window_sessions:
        limitation = (
            f'only {len(eligible)} trading sessions available (requested {window_sessions}); '
            'window uses all available sessions — label remains CONDITIONAL'
        )
    window = eligible[-window_sessions:] if len(eligible) >= window_sessions else eligible
    return window[0].session_date, limitation


def _merge_pit_notes(*notes: str | None) -> str | None:
    parts = [str(note).strip() for note in notes if note and str(note).strip()]
    if not parts:
        return None
    return ' '.join(parts)


def build_observation(
    symbol: str,
    *,
    as_of: str | None = None,
    knowledge_cutoff: str | None = None,
    price_basis: str = DEFAULT_PRICE_BASIS,
    peak_kind: str = PEAK_KIND,
    basis_as_of: str | None = None,
    generation_id: str | None = None,
    generation_content_hash: str | None = None,
    bars: Sequence[Sequence[Any]] | None = None,
    base_dir: str | None = None,
    now: datetime | None = None,
    window_days: int = WINDOW_TRADING_SESSIONS,
) -> dict[str, Any]:
    """Build the st-peak-100d-v0 observation object (always label=CONDITIONAL)."""
    now = now or datetime.now(po.TZ_TPE)
    code = str(symbol).strip().upper()
    if peak_kind != PEAK_KIND:
        return _null_observation(
            symbol=code,
            as_of=as_of or po._last_tw_close_day(now).isoformat(),
            knowledge_cutoff=knowledge_cutoff or now.isoformat(),
            price_basis=price_basis,
            null_reason=f'peakKind {peak_kind!r} rejected; only A supported',
            basis_as_of=basis_as_of,
            generation_id=generation_id,
            generation_content_hash=generation_content_hash,
            source='rejected',
            window_days=window_days,
        )

    resolved_as_of = as_of or po._last_tw_close_day(now).isoformat()
    resolved_cutoff = knowledge_cutoff or now.astimezone(po.TZ_TPE).isoformat()

    adj_error = po._validate_adj_requirements(
        price_basis,
        basis_as_of=basis_as_of,
        generation_id=generation_id,
        generation_content_hash=generation_content_hash,
    )
    if adj_error:
        return _null_observation(
            symbol=code,
            as_of=resolved_as_of,
            knowledge_cutoff=resolved_cutoff,
            price_basis=price_basis,
            null_reason=adj_error,
            basis_as_of=basis_as_of,
            generation_id=generation_id,
            generation_content_hash=generation_content_hash,
            source='validation',
            window_days=window_days,
        )

    pit_bars, source, pit_note = po._load_pit_bars(
        code,
        as_of=resolved_as_of,
        knowledge_cutoff=resolved_cutoff,
        price_basis=price_basis,
        generation_id=generation_id,
        bars=bars,
        base_dir=base_dir,
    )

    gen_error = po._generation_mismatch(pit_bars, generation_id)
    if gen_error:
        return _null_observation(
            symbol=code,
            as_of=resolved_as_of,
            knowledge_cutoff=resolved_cutoff,
            price_basis=price_basis,
            null_reason=gen_error,
            basis_as_of=basis_as_of,
            generation_id=generation_id,
            generation_content_hash=generation_content_hash,
            source=source,
            pit_note=pit_note,
            window_days=window_days,
        )

    try:
        resolved_history, window_note = _history_start_for_window(
            pit_bars,
            resolved_as_of,
            window_sessions=window_days,
        )
    except ValueError as exc:
        return _null_observation(
            symbol=code,
            as_of=resolved_as_of,
            knowledge_cutoff=resolved_cutoff,
            price_basis=price_basis,
            null_reason=str(exc),
            basis_as_of=basis_as_of,
            generation_id=generation_id,
            generation_content_hash=generation_content_hash,
            source=source,
            pit_note=pit_note,
            window_days=window_days,
        )

    merged_pit_note = _merge_pit_notes(pit_note, window_note)

    peak_close, peak_date, last_close, null_reason = po._compute_peak_kind_a(
        pit_bars,
        as_of=resolved_as_of,
        history_start=resolved_history,
    )
    if null_reason:
        return _null_observation(
            symbol=code,
            as_of=resolved_as_of,
            knowledge_cutoff=resolved_cutoff,
            history_start=resolved_history,
            price_basis=price_basis,
            null_reason=null_reason,
            basis_as_of=basis_as_of,
            generation_id=generation_id,
            generation_content_hash=generation_content_hash,
            source=source,
            pit_note=merged_pit_note,
            window_days=window_days,
        )

    pct = po._round_pct(last_close / peak_close - 1.0)
    if pct is not None and (pct < -1.0 or pct > 0.0):
        return _null_observation(
            symbol=code,
            as_of=resolved_as_of,
            knowledge_cutoff=resolved_cutoff,
            history_start=resolved_history,
            price_basis=price_basis,
            null_reason=f'pctBelowPeak out of range: {pct}',
            basis_as_of=basis_as_of,
            generation_id=generation_id,
            generation_content_hash=generation_content_hash,
            source=source,
            pit_note=merged_pit_note,
            window_days=window_days,
        )

    bar_dicts = [row.as_dict() for row in pit_bars]
    hash_inputs = _evidence_hash_inputs(
        symbol=code,
        as_of=resolved_as_of,
        history_start=resolved_history,
        price_basis=price_basis,
        knowledge_cutoff=resolved_cutoff,
        peak_kind=PEAK_KIND,
        bars=bar_dicts,
        basis_as_of=basis_as_of,
        generation_id=generation_id,
        generation_content_hash=generation_content_hash,
        source=source,
        window_days=window_days,
    )
    evidence_hash = po.compute_evidence_hash(hash_inputs)

    observation: dict[str, Any] = {
        'contractId': CONTRACT_ID,
        'symbol': code,
        'asOf': resolved_as_of,
        'peakKind': PEAK_KIND,
        'windowDays': window_days,
        'historyStart': resolved_history,
        'priceBasis': price_basis,
        'peakClose': po._round_price(peak_close),
        'peakDate': peak_date,
        'lastClose': po._round_price(last_close),
        'pctBelowPeak': pct,
        'source': source,
        'label': LABEL,
        'knowledgeCutoff': resolved_cutoff,
        'evidenceHash': evidence_hash,
        'hostApprovalHash': None,
        'disclaimerKey': DISCLAIMER_KEY,
    }
    if basis_as_of:
        observation['basisAsOf'] = basis_as_of
    if generation_id:
        observation['generationId'] = generation_id
    if generation_content_hash:
        observation['generationContentHash'] = generation_content_hash
    if merged_pit_note:
        observation['pitLimitation'] = merged_pit_note

    return observation


def _null_observation(
    *,
    symbol: str,
    as_of: str,
    knowledge_cutoff: str,
    history_start: str | None = None,
    price_basis: str,
    null_reason: str,
    basis_as_of: str | None,
    generation_id: str | None,
    generation_content_hash: str | None,
    source: str,
    pit_note: str | None = None,
    window_days: int = WINDOW_TRADING_SESSIONS,
) -> dict[str, Any]:
    resolved_history = history_start
    if resolved_history:
        try:
            resolved_history = po._parse_session_date(resolved_history).isoformat()
        except ValueError:
            pass
    hash_inputs = _evidence_hash_inputs(
        symbol=symbol,
        as_of=as_of,
        history_start=str(resolved_history or ''),
        price_basis=price_basis,
        knowledge_cutoff=knowledge_cutoff,
        peak_kind=PEAK_KIND,
        bars=[],
        basis_as_of=basis_as_of,
        generation_id=generation_id,
        generation_content_hash=generation_content_hash,
        source=source,
        window_days=window_days,
    )
    observation: dict[str, Any] = {
        'contractId': CONTRACT_ID,
        'symbol': symbol,
        'asOf': as_of,
        'peakKind': PEAK_KIND,
        'windowDays': window_days,
        'historyStart': resolved_history,
        'priceBasis': price_basis,
        'peakClose': None,
        'peakDate': None,
        'lastClose': None,
        'pctBelowPeak': None,
        'source': source,
        'label': LABEL,
        'knowledgeCutoff': knowledge_cutoff,
        'evidenceHash': po.compute_evidence_hash(hash_inputs),
        'hostApprovalHash': None,
        'disclaimerKey': DISCLAIMER_KEY,
        'nullReason': null_reason,
    }
    if basis_as_of:
        observation['basisAsOf'] = basis_as_of
    if generation_id:
        observation['generationId'] = generation_id
    if generation_content_hash:
        observation['generationContentHash'] = generation_content_hash
    if pit_note:
        observation['pitLimitation'] = pit_note
    return observation


def build_for_evidence_pack(
    symbol: str,
    *,
    bars: Sequence[Sequence[Any]] | None = None,
    now: datetime | None = None,
    base_dir: str | None = None,
    price_basis: str = DEFAULT_PRICE_BASIS,
) -> dict[str, Any] | None:
    """Attach-friendly wrapper used by ``build_evidence_pack``."""
    now = now or datetime.now(po.TZ_TPE)
    as_of = po._last_tw_close_day(now).isoformat()
    knowledge_cutoff = now.astimezone(po.TZ_TPE).isoformat()
    return build_observation(
        symbol,
        as_of=as_of,
        knowledge_cutoff=knowledge_cutoff,
        price_basis=price_basis,
        bars=bars,
        base_dir=base_dir,
        now=now,
    )
