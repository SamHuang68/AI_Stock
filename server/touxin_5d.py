#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""投信 5 日買超％／名次 observation (st-touxin-5d-v0, CONDITIONAL only).

Computes rolling 5-session trust net-buy shares, optional net-buy % vs 5d volume,
and cross-section rank. Does **not** write DecisionContext or FACT labels.
See ``docs/ST_TOUXIN_5D_NETBUY.md``.
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

from touxin_ledger import (
    TouxinRow,
    load_chip_history_fallback,
    query_rows_pit,
)

CONTRACT_ID = 'st-touxin-5d-v0'
WINDOW = 5
LABEL = 'CONDITIONAL'
EPISTEMIC = 'CONDITIONAL'
DISCLAIMER_KEY = 'st-touxin-5d-v0-non-recommendation'
DEFAULT_SOURCE_LEDGER = 'touxin_ledger/pit'
DEFAULT_SOURCE_FALLBACK = 'chip_history/snapshot'
UNIVERSE_LABEL = 'TW_LISTED_IN_LEDGER'


def _last_tw_close_day(now: datetime) -> date:
    local = now.astimezone(TZ_TPE)
    day = local.date()
    if local.time() < dtime(13, 30):
        day = day.fromordinal(day.toordinal() - 1)
    while day.weekday() >= 5:
        day = day.fromordinal(day.toordinal() - 1)
    return day


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


def _round_shares(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 4)


def _round_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 8)


def _window_sessions(rows: Sequence[TouxinRow], as_of: str, window: int) -> list[TouxinRow]:
    as_of_date = as_of[:10]
    eligible = [r for r in rows if r.session_date <= as_of_date]
    eligible.sort(key=lambda r: r.session_date)
    deduped: dict[str, TouxinRow] = {}
    for row in eligible:
        deduped[row.session_date] = row
    ordered = [deduped[k] for k in sorted(deduped)]
    return ordered[-window:]


def _aggregate_window(sessions: Sequence[TouxinRow]) -> dict[str, Any]:
    net = sum(r.trust_net_shares for r in sessions)
    vol_parts = [r.volume_shares for r in sessions if r.volume_shares is not None]
    volume5d = sum(vol_parts) if vol_parts and len(vol_parts) == len(sessions) else None
    net_pct = None
    pit_note = None
    if volume5d is not None and volume5d > 0:
        net_pct = net / volume5d
    elif sessions:
        pit_note = 'volume5d incomplete — netBuyPct withheld'
    return {
        'netBuyShares': _round_shares(net),
        'volume5d': _round_shares(volume5d),
        'netBuyPct': _round_ratio(net_pct),
        'pitNote': pit_note,
        'sessionDates': [r.session_date for r in sessions],
    }


def _rank_universe(
    as_of: str,
    knowledge_cutoff: str,
    *,
    window: int = WINDOW,
    base_dir: str | os.PathLike[str] | None = None,
) -> dict[str, dict[str, Any]]:
    all_rows = query_rows_pit(None, as_of=as_of, knowledge_cutoff=knowledge_cutoff, base_dir=base_dir)
    by_symbol: dict[str, list[TouxinRow]] = {}
    for row in all_rows:
        by_symbol.setdefault(row.symbol, []).append(row)
    metrics: dict[str, dict[str, Any]] = {}
    for sym, rows in by_symbol.items():
        sessions = _window_sessions(rows, as_of, window)
        if len(sessions) < window:
            continue
        agg = _aggregate_window(sessions)
        metrics[sym] = agg
    ranked = sorted(metrics.items(), key=lambda item: item[1]['netBuyShares'] or 0.0, reverse=True)
    universe_size = len(ranked)
    for rank, (sym, agg) in enumerate(ranked, start=1):
        agg['rankAmongUniverse'] = rank
        agg['universeSize'] = universe_size
        metrics[sym] = agg
    return metrics


def compute_evidence_hash(payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def build_observation(
    symbol: str,
    *,
    as_of: str,
    knowledge_cutoff: str,
    window: int = WINDOW,
    base_dir: str | os.PathLike[str] | None = None,
    chip_history_path: str | None = None,
) -> dict[str, Any]:
    code = str(symbol or '').strip().upper()
    pit_limitation = None
    source = DEFAULT_SOURCE_LEDGER

    ledger_rows = query_rows_pit(code, as_of=as_of, knowledge_cutoff=knowledge_cutoff, base_dir=base_dir)
    sessions = _window_sessions(ledger_rows, as_of, window)

    if len(sessions) < window:
        fallback_path = chip_history_path
        if fallback_path is None and base_dir is not None:
            fallback_path = os.path.join(os.fspath(base_dir), 'data', 'chip_history')
        fb_rows = load_chip_history_fallback(
            code,
            as_of=as_of,
            window=window,
            chip_history_path=fallback_path or os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                'data', 'chip_history',
            ),
        )
        if len(fb_rows) >= window:
            sessions = _window_sessions(fb_rows, as_of, window)
            source = DEFAULT_SOURCE_FALLBACK
            pit_limitation = (
                'chip_history snapshot fallback — no append-only ledger audit; '
                'volume may be missing; not ledger-backed'
            )

    agg = _aggregate_window(sessions) if len(sessions) >= window else {
        'netBuyShares': None,
        'volume5d': None,
        'netBuyPct': None,
        'pitNote': 'insufficient sessions for 5d window',
        'sessionDates': [r.session_date for r in sessions],
    }

    rank = None
    universe_size = None
    if len(sessions) >= window and source == DEFAULT_SOURCE_LEDGER:
        universe = _rank_universe(as_of, knowledge_cutoff, window=window, base_dir=base_dir)
        if code in universe:
            rank = universe[code].get('rankAmongUniverse')
            universe_size = universe[code].get('universeSize')

    if agg.get('pitNote') and pit_limitation:
        pit_limitation = f'{pit_limitation}; {agg["pitNote"]}'
    elif agg.get('pitNote'):
        pit_limitation = agg['pitNote']

    obs: dict[str, Any] = {
        'contractId': CONTRACT_ID,
        'symbol': code,
        'asOf': as_of[:10],
        'window': window,
        'netBuyShares': agg.get('netBuyShares'),
        'volume5d': agg.get('volume5d'),
        'netBuyPct': agg.get('netBuyPct'),
        'rankAmongUniverse': rank,
        'universe': UNIVERSE_LABEL if rank is not None else None,
        'universeSize': universe_size,
        'sessionDates': agg.get('sessionDates') or [],
        'source': source,
        'knowledgeCutoff': knowledge_cutoff,
        'pitLimitation': pit_limitation,
        'label': LABEL,
        'epistemic': EPISTEMIC,
        'disclaimerKey': DISCLAIMER_KEY,
        'hostApprovalHash': None,
        'shadowOnly': True,
        'actionAuthority': 'none',
        'decisionUse': 'research_only',
    }
    obs['evidenceHash'] = compute_evidence_hash({
        'contractId': CONTRACT_ID,
        'symbol': code,
        'asOf': obs['asOf'],
        'window': window,
        'netBuyShares': obs['netBuyShares'],
        'netBuyPct': obs['netBuyPct'],
        'rankAmongUniverse': rank,
        'source': source,
        'knowledgeCutoff': knowledge_cutoff,
        'sessionDates': obs['sessionDates'],
    })
    return obs


def build_for_evidence_pack(
    symbol: str,
    *,
    now: datetime | None = None,
    base_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any] | None:
    now = now or datetime.now(TZ_TPE)
    as_of = _last_tw_close_day(now).isoformat()
    knowledge_cutoff = now.astimezone(TZ_TPE).isoformat()
    return build_observation(
        symbol,
        as_of=as_of,
        knowledge_cutoff=knowledge_cutoff,
        base_dir=base_dir,
    )
