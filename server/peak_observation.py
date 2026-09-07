#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Observation-only peak distance feature (st-peak-v0.1, CONDITIONAL only).

Computes ``pctBelowPeak = lastClose / peakClose - 1`` for peakKind ``A``
(max close from ``historyStart`` through ``asOf`` on a declared ``priceBasis``).

This module does **not** write DecisionContext, actionEnvelope, or FACT labels.
See ``docs/ST_PEAK_V01.md``.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, time as dtime, timedelta
from typing import Any, Mapping, Sequence

try:
    from zoneinfo import ZoneInfo
    TZ_TPE = ZoneInfo('Asia/Taipei')
except Exception:  # pragma: no cover
    from datetime import timezone
    TZ_TPE = timezone(timedelta(hours=8))

from ohlc_ledger import OhlcBar, filter_bars_pit, query_bars_pit

CONTRACT_ID = 'st-peak-v0.1'
PEAK_KIND = 'A'
LABEL = 'CONDITIONAL'
DISCLAIMER_KEY = 'st-peak-v0.1-non-recommendation'
EPISTEMIC = 'CONDITIONAL'
DEFAULT_PRICE_BASIS = 'unadj_close'
DEFAULT_SOURCE_LEDGER = 'ohlc_ledger/pit'
DEFAULT_SOURCE_LIVE = 'datastore/live-bars-partial-pit'

if getattr(__import__('sys'), 'frozen', False):
    _BASE = os.path.dirname(__import__('sys').executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _parse_session_date(value: Any) -> date:
    raw = str(value or '').strip()
    if not raw:
        raise ValueError('session date is required')
    if len(raw) == 8 and raw.isdigit():
        raw = f'{raw[:4]}-{raw[4:6]}-{raw[6:8]}'
    return date.fromisoformat(raw[:10])


def _session_date_from_ts(ts: float | int) -> str:
    return datetime.fromtimestamp(float(ts), TZ_TPE).date().isoformat()


def _tw_close_iso(ts: float | int) -> str:
    day = datetime.fromtimestamp(float(ts), TZ_TPE).date()
    close_dt = datetime.combine(day, dtime(13, 30), TZ_TPE)
    return close_dt.isoformat()


def _last_tw_close_day(now: datetime) -> date:
    local = now.astimezone(TZ_TPE)
    day = local.date()
    if local.time() < dtime(13, 30):
        day = day.fromordinal(day.toordinal() - 1)
    while day.weekday() >= 5:
        day = day.fromordinal(day.toordinal() - 1)
    return day


def _round_price(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _round_pct(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 8)


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
) -> dict[str, Any]:
    return {
        'contractId': CONTRACT_ID,
        'symbol': symbol,
        'asOf': as_of,
        'historyStart': history_start,
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


def compute_evidence_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def _validate_adj_requirements(
    price_basis: str,
    *,
    basis_as_of: str | None,
    generation_id: str | None,
    generation_content_hash: str | None,
) -> str | None:
    if price_basis != 'adj_close':
        return None
    missing = []
    if not basis_as_of:
        missing.append('basisAsOf')
    if not generation_id:
        missing.append('generationId')
    if not generation_content_hash:
        missing.append('generationContentHash')
    if missing:
        return 'adj_close requires ' + ', '.join(missing)
    return None


def _datastore_bars_to_ledger_rows(
    symbol: str,
    bars: Sequence[Sequence[Any]],
    *,
    price_basis: str,
    knowledge_cutoff: str,
) -> list[dict[str, Any]]:
    """Convert datastore ``(ts,o,h,l,c,v)`` rows into ledger-shaped dicts.

    Live bars lack real ``ingested_at``; we stamp ``knowledge_cutoff`` so PIT
    filtering still runs, but callers must treat ``source`` as partial PIT.
    """
    out: list[dict[str, Any]] = []
    for row in bars or []:
        if not row or row[4] is None:
            continue
        session = _session_date_from_ts(row[0])
        out.append({
            'symbol': symbol,
            'session_date': session,
            'price_basis': price_basis,
            'open': float(row[1] if row[1] is not None else row[4]),
            'high': float(row[2] if row[2] is not None else row[4]),
            'low': float(row[3] if row[3] is not None else row[4]),
            'close': float(row[4]),
            'source': DEFAULT_SOURCE_LIVE,
            'ingested_at': knowledge_cutoff,
            'generation_id': 'live-chart',
        })
    return out


def _load_pit_bars(
    symbol: str,
    *,
    as_of: str,
    knowledge_cutoff: str,
    price_basis: str,
    generation_id: str | None,
    bars: Sequence[Sequence[Any]] | None,
    base_dir: str | os.PathLike[str] | None,
) -> tuple[list[OhlcBar], str, str | None]:
    """Return PIT-visible bars, source id, and optional limitation note."""
    ledger_rows = query_bars_pit(
        symbol,
        as_of=as_of,
        knowledge_cutoff=knowledge_cutoff,
        price_basis=price_basis,
        generation_id=generation_id,
        base_dir=base_dir,
    )
    if ledger_rows:
        return ledger_rows, DEFAULT_SOURCE_LEDGER, None

    if not bars:
        return [], DEFAULT_SOURCE_LEDGER, None

    converted = _datastore_bars_to_ledger_rows(
        symbol,
        bars,
        price_basis=price_basis,
        knowledge_cutoff=knowledge_cutoff,
    )
    pit = filter_bars_pit(converted, as_of=as_of, knowledge_cutoff=knowledge_cutoff)
    note = (
        'Ledger empty; computed from live chart bars with synthetic ingested_at=knowledgeCutoff. '
        'PIT is partial — label remains CONDITIONAL.'
    )
    return pit, DEFAULT_SOURCE_LIVE, note


def _history_start_from_bars(bars: Sequence[OhlcBar], requested: str | None) -> str:
    if requested:
        return _parse_session_date(requested).isoformat()
    if not bars:
        raise ValueError('historyStart unavailable — no PIT bars')
    return bars[0].session_date


def _generation_mismatch(bars: Sequence[OhlcBar], generation_id: str | None) -> str | None:
    if not bars:
        return None
    gens = {row.generation_id for row in bars}
    if generation_id and len(gens) > 1:
        return f'mixed generation_id in window: {sorted(gens)!r}'
    if len(gens) > 1:
        return f'mixed generation_id in window: {sorted(gens)!r}'
    return None


def _compute_peak_kind_a(
    bars: Sequence[OhlcBar],
    *,
    as_of: str,
    history_start: str,
) -> tuple[float | None, str | None, float | None, str | None]:
    """Return peakClose, peakDate, lastClose, nullReason."""
    as_of_date = _parse_session_date(as_of)
    hist_start = _parse_session_date(history_start)
    window = [
        row for row in bars
        if _parse_session_date(row.session_date) >= hist_start
        and _parse_session_date(row.session_date) <= as_of_date
    ]
    if not window:
        return None, None, None, 'no PIT bars in [historyStart, asOf]'

    peak_row = max(window, key=lambda row: (float(row.close), row.session_date))
    last_candidates = [row for row in window if _parse_session_date(row.session_date) == as_of_date]
    if last_candidates:
        last_row = last_candidates[-1]
    else:
        last_row = window[-1]

    peak_close = float(peak_row.close)
    last_close = float(last_row.close)
    if peak_close <= 0 or last_close <= 0:
        return None, None, None, 'non-positive close in window'

    return peak_close, peak_row.session_date, last_close, None


def build_observation(
    symbol: str,
    *,
    as_of: str | None = None,
    knowledge_cutoff: str | None = None,
    history_start: str | None = None,
    price_basis: str = DEFAULT_PRICE_BASIS,
    peak_kind: str = PEAK_KIND,
    basis_as_of: str | None = None,
    generation_id: str | None = None,
    generation_content_hash: str | None = None,
    bars: Sequence[Sequence[Any]] | None = None,
    base_dir: str | os.PathLike[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the st-peak-v0.1 observation object (always label=CONDITIONAL)."""
    now = now or datetime.now(TZ_TPE)
    code = str(symbol).strip().upper()
    if peak_kind != PEAK_KIND:
        return _null_observation(
            symbol=code,
            as_of=as_of or _last_tw_close_day(now).isoformat(),
            knowledge_cutoff=knowledge_cutoff or now.isoformat(),
            history_start=history_start,
            price_basis=price_basis,
            null_reason=f'peakKind {peak_kind!r} rejected; only A supported',
            basis_as_of=basis_as_of,
            generation_id=generation_id,
            generation_content_hash=generation_content_hash,
            source='rejected',
        )

    resolved_as_of = as_of or _last_tw_close_day(now).isoformat()
    resolved_cutoff = knowledge_cutoff or now.astimezone(TZ_TPE).isoformat()

    adj_error = _validate_adj_requirements(
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
            history_start=history_start,
            price_basis=price_basis,
            null_reason=adj_error,
            basis_as_of=basis_as_of,
            generation_id=generation_id,
            generation_content_hash=generation_content_hash,
            source='validation',
        )

    pit_bars, source, pit_note = _load_pit_bars(
        code,
        as_of=resolved_as_of,
        knowledge_cutoff=resolved_cutoff,
        price_basis=price_basis,
        generation_id=generation_id,
        bars=bars,
        base_dir=base_dir,
    )

    gen_error = _generation_mismatch(pit_bars, generation_id)
    if gen_error:
        return _null_observation(
            symbol=code,
            as_of=resolved_as_of,
            knowledge_cutoff=resolved_cutoff,
            history_start=history_start,
            price_basis=price_basis,
            null_reason=gen_error,
            basis_as_of=basis_as_of,
            generation_id=generation_id,
            generation_content_hash=generation_content_hash,
            source=source,
            pit_note=pit_note,
        )

    try:
        resolved_history = _history_start_from_bars(pit_bars, history_start)
    except ValueError as exc:
        return _null_observation(
            symbol=code,
            as_of=resolved_as_of,
            knowledge_cutoff=resolved_cutoff,
            history_start=history_start,
            price_basis=price_basis,
            null_reason=str(exc),
            basis_as_of=basis_as_of,
            generation_id=generation_id,
            generation_content_hash=generation_content_hash,
            source=source,
            pit_note=pit_note,
        )

    peak_close, peak_date, last_close, null_reason = _compute_peak_kind_a(
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
            pit_note=pit_note,
        )

    pct = _round_pct(last_close / peak_close - 1.0)
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
            pit_note=pit_note,
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
    )
    evidence_hash = compute_evidence_hash(hash_inputs)

    observation: dict[str, Any] = {
        'contractId': CONTRACT_ID,
        'symbol': code,
        'asOf': resolved_as_of,
        'peakKind': PEAK_KIND,
        'historyStart': resolved_history,
        'priceBasis': price_basis,
        'peakClose': _round_price(peak_close),
        'peakDate': peak_date,
        'lastClose': _round_price(last_close),
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
    if pit_note:
        observation['pitLimitation'] = pit_note

    return observation


def _null_observation(
    *,
    symbol: str,
    as_of: str,
    knowledge_cutoff: str,
    history_start: str | None,
    price_basis: str,
    null_reason: str,
    basis_as_of: str | None,
    generation_id: str | None,
    generation_content_hash: str | None,
    source: str,
    pit_note: str | None = None,
) -> dict[str, Any]:
    resolved_history = history_start
    if resolved_history:
        try:
            resolved_history = _parse_session_date(resolved_history).isoformat()
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
    )
    observation: dict[str, Any] = {
        'contractId': CONTRACT_ID,
        'symbol': symbol,
        'asOf': as_of,
        'peakKind': PEAK_KIND,
        'historyStart': resolved_history,
        'priceBasis': price_basis,
        'peakClose': None,
        'peakDate': None,
        'lastClose': None,
        'pctBelowPeak': None,
        'source': source,
        'label': LABEL,
        'knowledgeCutoff': knowledge_cutoff,
        'evidenceHash': compute_evidence_hash(hash_inputs),
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
    base_dir: str | os.PathLike[str] | None = None,
    history_start: str | None = None,
    price_basis: str = DEFAULT_PRICE_BASIS,
) -> dict[str, Any] | None:
    """Attach-friendly wrapper used by ``build_evidence_pack``."""
    now = now or datetime.now(TZ_TPE)
    as_of = _last_tw_close_day(now).isoformat()
    knowledge_cutoff = now.astimezone(TZ_TPE).isoformat()
    return build_observation(
        symbol,
        as_of=as_of,
        knowledge_cutoff=knowledge_cutoff,
        history_start=history_start,
        price_basis=price_basis,
        bars=bars,
        base_dir=base_dir,
        now=now,
    )
