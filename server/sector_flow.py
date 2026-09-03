#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Scope-safe sector participation and turnover-share calculations."""
from __future__ import annotations

import math
import re
from datetime import date
from typing import Any, Iterable


def _number(value: Any) -> float | None:
    try:
        value = float(str(value).replace(',', '').replace('+', '').strip())
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def normalize_session_date(value: Any) -> str | None:
    """Return YYYYMMDD for Gregorian/ROC exchange dates."""
    text = re.sub(r'\D', '', str(value or ''))
    if len(text) == 8 and text[:4].isdigit():
        return text
    if len(text) == 7 and text[:3].isdigit():
        return f'{int(text[:3]) + 1911:04d}{text[3:]}'
    return None


def parse_twse_daily_stock_table(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Normalize a dated MI_INDEX ALLBUT0999 stock table to STOCK_DAY_ALL fields."""
    if not isinstance(payload, dict) or payload.get('stat') not in (None, 'OK'):
        return []
    session = normalize_session_date(payload.get('date'))
    for table in payload.get('tables') or []:
        fields = table.get('fields') or []
        if '證券代號' not in fields or '成交金額' not in fields or '收盤價' not in fields:
            continue
        pos = {str(name): index for index, name in enumerate(fields)}
        out = []
        for values in table.get('data') or []:
            def at(name):
                index = pos.get(name)
                return values[index] if index is not None and index < len(values) else None
            diff = _number(at('漲跌價差'))
            sign = str(at('漲跌(+/-)') or '').strip()
            if diff is not None and ('-' in sign or '−' in sign):
                diff = -abs(diff)
            elif diff is not None and '+' in sign:
                diff = abs(diff)
            out.append({
                'Code': str(at('證券代號') or '').strip(),
                'Name': str(at('證券名稱') or '').strip(),
                'TradeValue': at('成交金額'),
                'ClosingPrice': at('收盤價'),
                'Change': diff,
                'Date': session,
            })
        return out
    return []


def normalize_sector_name(value: Any) -> str:
    """Normalize TWSE index labels and issuer industry labels to one join key."""
    text = re.sub(r'\s+', '', str(value or ''))
    for suffix in ('類指數', '產業指數', '指數'):
        if text.endswith(suffix):
            text = text[:-len(suffix)]
    for suffix in ('工業', '事業', '產業', '類', '業'):
        if text.endswith(suffix) and len(text) > len(suffix) + 1:
            text = text[:-len(suffix)]
            break
    aliases = {
        '電腦及週邊設備': '電腦及週邊設備',
        '建材營造': '建材營造',
        '金融保險': '金融保險',
        '貿易百貨': '貿易百貨',
        '油電燃氣': '油電燃氣',
    }
    return aliases.get(text, text)


def attach_sector_metrics(
    sectors: Iterable[dict[str, Any]] | None,
    *,
    industry_turnover_yi: dict[str, Any] | None = None,
    return20_by_sector: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Join same-day stock turnover and official sector-index history by normalized industry key."""
    turnover = {
        normalize_sector_name(key): _number(value)
        for key, value in (industry_turnover_yi or {}).items()
    }
    returns = {
        normalize_sector_name(key): _number(value)
        for key, value in (return20_by_sector or {}).items()
    }
    out = []
    for raw in sectors or []:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        key = normalize_sector_name(row.get('sector') or row.get('name'))
        if turnover:
            row['turnoverEligible'] = key in turnover and turnover.get(key) is not None
            if row['turnoverEligible']:
                row['turnoverYi'] = turnover[key]
                row['turnoverScope'] = 'TWSE_COMMON_STOCKS_BY_INDUSTRY'
        if key in returns and returns[key] is not None:
            row['return20Pct'] = returns[key]
            row['return20Source'] = 'TWSE MI_INDEX IND daily close'
        out.append(row)
    return out


def build_sector_flow(
    sectors: Iterable[dict[str, Any]] | None,
    *,
    market_scope: str = 'TWSE',
    source: str = 'unknown',
    as_of: str | None = None,
    total_turnover_yi: float | None = None,
    benchmark_return20_pct: float | None = None,
    proxy_basket: bool = False,
) -> dict[str, Any]:
    """Enrich sector rows without labelling price participation as fund flow."""
    raw = [dict(x) for x in (sectors or []) if isinstance(x, dict)]
    total_turnover_yi = _number(total_turnover_yi)
    valid_change = [x for x in raw if _number(x.get('changePct')) is not None]
    eligible_rows = [x for x in raw if x.get('turnoverEligible') is not False]
    turnover_rows = [x for x in eligible_rows if _number(x.get('turnoverYi', x.get('turnover'))) is not None]
    turnover_coverage = len(turnover_rows) / len(eligible_rows) if eligible_rows else 0.0
    rows: list[dict[str, Any]] = []
    shares: list[float] = []

    for row in raw:
        change = _number(row.get('changePct'))
        turnover = _number(row.get('turnoverYi', row.get('turnover')))
        return20 = _number(row.get('return20Pct'))
        rs20 = _number(row.get('rs20VsBenchmarkPct'))
        if rs20 is None and return20 is not None and benchmark_return20_pct is not None:
            rs20 = return20 - float(benchmark_return20_pct)
        share = None
        if turnover is not None and total_turnover_yi not in (None, 0) and total_turnover_yi > 0:
            share = max(0.0, turnover / total_turnover_yi * 100.0)
            shares.append(share)
        enriched = dict(row)
        enriched.update({
            'sector': row.get('sector') or row.get('name'),
            'marketScope': row.get('marketScope') or market_scope,
            'changePct': round(change, 4) if change is not None else None,
            'turnoverYi': round(turnover, 2) if turnover is not None else None,
            'marketSharePct': round(share, 3) if share is not None else None,
            'shareDelta5dPctPoint': _number(row.get('shareDelta5dPctPoint')),
            'rs20VsBenchmarkPct': round(rs20, 3) if rs20 is not None else None,
            'breadthPct': _number(row.get('breadthPct')),
            'sampleCoveragePct': _number(row.get('sampleCoveragePct')),
            'source': row.get('source') or source,
            'asOf': row.get('asOf') or as_of,
            'proxyBasket': bool(row.get('proxyBasket', proxy_basket)),
            'turnoverEligible': row.get('turnoverEligible'),
            'turnoverScope': row.get('turnoverScope'),
            'return20Source': row.get('return20Source'),
        })
        rows.append(enriched)

    participation = None
    if valid_change:
        participation = sum(1 for x in valid_change if float(x['changePct']) > 0) / len(valid_change) * 100.0
    scope_consistent = all(str(x.get('marketScope') or market_scope) == market_scope for x in raw)
    flow_eligible = bool(shares) and turnover_coverage >= 0.80 and scope_consistent and not proxy_basket
    hhi = sum((s / 100.0) ** 2 for s in shares) * 10000.0 if flow_eligible else None
    top3 = sum(sorted(shares, reverse=True)[:3]) if flow_eligible else None
    mode = 'turnover' if flow_eligible else ('partial_turnover' if shares else 'participation_proxy')
    return {
        'ok': bool(rows),
        'marketScope': market_scope,
        'source': source,
        'asOf': as_of,
        'mode': mode,
        'flowEligible': flow_eligible,
        'label': ('成交額資金流' if flow_eligible else
                  ('部分成交額（不可當完整資金流）' if shares else '漲跌參與（無產業成交額）')),
        'participationPct': round(participation, 2) if participation is not None else None,
        'turnoverCoveragePct': round(turnover_coverage * 100.0, 2),
        'turnoverScope': next((x.get('turnoverScope') for x in rows if x.get('turnoverScope')), None),
        'top3SharePct': round(top3, 3) if top3 is not None else None,
        'hhi': round(hhi, 2) if hhi is not None else None,
        'rows': rows,
    }
