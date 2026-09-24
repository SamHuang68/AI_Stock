#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aggregate listed monthly revenue (OpenAPI t187ap05_L / t187ap05_O) by issuer industry.

Uses the same ``sector_flow.normalize_sector_name`` join key as heat / sector turnover.
No external /www/revenue scrapers — recompute only from cached OpenAPI rows.
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from datetime import date
from typing import Any, Callable, Iterable

import sector_flow


RowLoader = Callable[[str], list[dict[str, Any]] | None]

_loader: RowLoader | None = None
_cache: dict[str, Any] = {'day': None, 'agg': None}


def configure(loader: RowLoader | None) -> None:
    global _loader
    _loader = loader


def pick_num(row: dict[str, Any] | None, includes: tuple[str, ...], excludes: tuple[str, ...] = ()) -> float | None:
    if not row:
        return None
    for k, v in row.items():
        if all(s in k for s in includes) and not any(e in k for e in excludes):
            try:
                return float(str(v).replace(',', '').replace('%', '').strip())
            except (TypeError, ValueError):
                return None
    return None


def _code_from_row(row: dict[str, Any]) -> str:
    return str(
        row.get('公司代號') or row.get('證券代號') or row.get('Code') or row.get('SecuritiesCompanyCode') or ''
    ).strip()


def format_period_label(raw: Any) -> str | None:
    text = re.sub(r'\D', '', str(raw or ''))
    if len(text) == 5 and text[:3].isdigit():
        yy = int(text[:3]) + 1911
        return f'{yy}-{text[3:5]}'
    if len(text) == 6 and text[:4].isdigit():
        return f'{text[:4]}-{text[4:6]}'
    if len(text) == 7 and text[:3].isdigit():
        yy = int(text[:3]) + 1911
        return f'{yy}-{text[3:5]}'
    return str(raw).strip() or None


def parse_stock_row(row: dict[str, Any]) -> dict[str, Any] | None:
    code = _code_from_row(row)
    industry = str(row.get('產業別') or '').strip()
    if not code or not industry:
        return None
    month_rev = pick_num(row, ('當月營收',), ('累計',))
    prev_rev = pick_num(row, ('上月營收',), ('增減', '累計'))
    if prev_rev is None:
        prev_rev = pick_num(row, ('上月', '營收'), ('增減', '累計'))
    ly_rev = pick_num(row, ('去年同月',), ('增減',))
    if ly_rev is None:
        ly_rev = pick_num(row, ('去年', '營收'), ('增減', '累計'))
    yoy_pct = pick_num(row, ('去年同月增減',))
    mom_pct = pick_num(row, ('上月比較增減',))
    if mom_pct is None:
        mom_pct = pick_num(row, ('上月', '增減'), ('去年', '累計'))
    return {
        'code': code,
        'industry': industry,
        'industryKey': sector_flow.normalize_sector_name(industry),
        'periodRaw': row.get('資料年月'),
        'monthRev': month_rev,
        'prevMonthRev': prev_rev,
        'lastYearMonthRev': ly_rev,
        'yoyPct': yoy_pct,
        'momPct': mom_pct,
    }


def merge_openapi_rows(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dedupe by code; later rows override (tpex supplement after TWSE)."""
    by_code: dict[str, dict[str, Any]] = {}
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        parsed = parse_stock_row(raw)
        if parsed:
            by_code[parsed['code']] = parsed
    return list(by_code.values())


def _pct_delta(cur: float | None, base: float | None) -> float | None:
    if cur is None or base is None or base == 0:
        return None
    return round((cur - base) / abs(base) * 100.0, 2)


def aggregate_stocks(stocks: list[dict[str, Any]]) -> dict[str, Any]:
    if not stocks:
        return {'ok': False, 'reason': 'no_rows'}

    period_counter: Counter[str] = Counter()
    for s in stocks:
        pr = str(s.get('periodRaw') or '').strip()
        if pr:
            period_counter[pr] += 1
    period_raw = period_counter.most_common(1)[0][0] if period_counter else None
    period_label = format_period_label(period_raw)

    market_month = 0.0
    market_prev = 0.0
    market_ly = 0.0
    market_yoy_weighted = 0.0
    market_yoy_weight = 0.0
    grow = decline = flat = 0

    buckets: dict[str, dict[str, Any]] = defaultdict(lambda: {
        'industry': '',
        'industryKey': '',
        'monthRev': 0.0,
        'prevMonthRev': 0.0,
        'lastYearMonthRev': 0.0,
        'stockCount': 0,
        'growCount': 0,
        'declineCount': 0,
        'flatCount': 0,
        'yoyWeightedSum': 0.0,
        'yoyWeight': 0.0,
        'leader': None,
        'laggard': None,
    })

    for s in stocks:
        mr = s.get('monthRev')
        if mr is None:
            continue
        mr = float(mr)
        market_month += mr
        if s.get('prevMonthRev') is not None:
            market_prev += float(s['prevMonthRev'])
        if s.get('lastYearMonthRev') is not None:
            market_ly += float(s['lastYearMonthRev'])
        yoy = s.get('yoyPct')
        if yoy is not None:
            yf = float(yoy)
            if yf > 0.05:
                grow += 1
            elif yf < -0.05:
                decline += 1
            else:
                flat += 1
            if mr > 0:
                market_yoy_weighted += yf * mr
                market_yoy_weight += mr

        key = s.get('industryKey') or sector_flow.normalize_sector_name(s.get('industry'))
        b = buckets[key]
        b['industry'] = b['industry'] or s.get('industry')
        b['industryKey'] = key
        b['monthRev'] += mr
        b['stockCount'] += 1
        if s.get('prevMonthRev') is not None:
            b['prevMonthRev'] += float(s['prevMonthRev'])
        if s.get('lastYearMonthRev') is not None:
            b['lastYearMonthRev'] += float(s['lastYearMonthRev'])
        if yoy is not None:
            yf = float(yoy)
            if yf > 0.05:
                b['growCount'] += 1
            elif yf < -0.05:
                b['declineCount'] += 1
            else:
                b['flatCount'] += 1
            if mr > 0:
                b['yoyWeightedSum'] += yf * mr
                b['yoyWeight'] += mr
            leader = b.get('leader')
            laggard = b.get('laggard')
            if leader is None or yf > leader['yoyPct']:
                b['leader'] = {'code': s['code'], 'yoyPct': round(yf, 2)}
            if laggard is None or yf < laggard['yoyPct']:
                b['laggard'] = {'code': s['code'], 'yoyPct': round(yf, 2)}

    if market_month <= 0:
        return {'ok': False, 'reason': 'no_month_rev', 'periodLabel': period_label}

    market_yoy = _pct_delta(market_month, market_ly)
    if market_yoy is None and market_yoy_weight > 0:
        market_yoy = round(market_yoy_weighted / market_yoy_weight, 2)
    market_mom = _pct_delta(market_month, market_prev)

    industries_out: list[dict[str, Any]] = []
    by_key: dict[str, dict[str, Any]] = {}
    for key, b in buckets.items():
        if b['monthRev'] <= 0:
            continue
        share = round(b['monthRev'] / market_month * 100.0, 3)
        yoy_ind = _pct_delta(b['monthRev'], b['lastYearMonthRev'] if b['lastYearMonthRev'] else None)
        if yoy_ind is None and b['yoyWeight'] > 0:
            yoy_ind = round(b['yoyWeightedSum'] / b['yoyWeight'], 2)
        mom_ind = _pct_delta(b['monthRev'], b['prevMonthRev'] if b['prevMonthRev'] else None)
        row = {
            'industry': b['industry'],
            'industryKey': key,
            'monthRevThousand': round(b['monthRev'], 2),
            'sharePct': share,
            'yoyPct': yoy_ind,
            'momPct': mom_ind,
            'stockCount': b['stockCount'],
            'growCount': b['growCount'],
            'declineCount': b['declineCount'],
            'flatCount': b['flatCount'],
            'leader': b.get('leader'),
            'laggard': b.get('laggard'),
        }
        industries_out.append(row)
        by_key[key] = row

    industries_out.sort(key=lambda x: (-(x.get('sharePct') or 0), x.get('industry') or ''))

    top_yoy = sorted(
        [x for x in industries_out if x.get('yoyPct') is not None],
        key=lambda x: x['yoyPct'],
        reverse=True,
    )
    bottom_yoy = sorted(
        [x for x in industries_out if x.get('yoyPct') is not None],
        key=lambda x: x['yoyPct'],
    )

    return {
        'ok': True,
        'periodRaw': period_raw,
        'periodLabel': period_label,
        'unit': 'thousand_ntd',
        'source': 'TWSE/TPEx OpenAPI t187ap05_L + t187ap05_O',
        'stockCount': len([s for s in stocks if s.get('monthRev') is not None]),
        'market': {
            'monthRevThousand': round(market_month, 2),
            'monthRevYi': round(market_month / 1e5, 2),
            'yoyPct': market_yoy,
            'momPct': market_mom,
            'growCount': grow,
            'declineCount': decline,
            'flatCount': flat,
        },
        'industries': industries_out,
        'byIndustryKey': by_key,
        'yoyLeaders': top_yoy[:3],
        'yoyLaggards': bottom_yoy[:3],
        'note': (
            '月營收為基本面月頻，非盤中輪動；金融保險等產業常於次月 15 日前才陸續公布，'
            '合計可能隨披露而修正。'
        ),
    }


def build_from_openapi_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    return aggregate_stocks(merge_openapi_rows(rows))


DEFAULT_DATASETS = ('t187ap05_L', 't187ap05_O', 'tpex:mopsfin_t187ap05_O')


def get_aggregate(*, force: bool = False, loader: RowLoader | None = None) -> dict[str, Any]:
    today = date.today().strftime('%Y%m%d')
    if not force and _cache.get('day') == today and _cache.get('agg'):
        return _cache['agg']
    load = loader or _loader
    if load is None:
        return {'ok': False, 'reason': 'no_loader'}
    merged: list[dict[str, Any]] = []
    for ds in DEFAULT_DATASETS:
        try:
            chunk = load(ds) or []
            if chunk:
                merged.extend(chunk)
        except Exception:
            continue
    agg = build_from_openapi_rows(merged)
    if agg.get('ok'):
        _cache['day'] = today
        _cache['agg'] = agg
    return agg


def _match_industry_key(sector_name: str, by_key: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    key = sector_flow.normalize_sector_name(sector_name)
    if key in by_key:
        return by_key[key]
    sk = key.lower()
    for k, row in by_key.items():
        if k.lower() == sk or sk in k.lower() or k.lower() in sk:
            return row
    return None


def attach_sector_revenue(
    sectors: Iterable[dict[str, Any]] | None,
    agg: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    by_key = (agg or {}).get('byIndustryKey') or {}
    out: list[dict[str, Any]] = []
    for raw in sectors or []:
        if not isinstance(raw, dict):
            continue
        row = dict(raw)
        if not by_key:
            out.append(row)
            continue
        hit = _match_industry_key(row.get('sector') or row.get('name') or '', by_key)
        if hit:
            row['revenueSharePct'] = hit.get('sharePct')
            row['revenueYoyPct'] = hit.get('yoyPct')
            row['revenueMomPct'] = hit.get('momPct')
            row['revenueGrowCount'] = hit.get('growCount')
            row['revenueDeclineCount'] = hit.get('declineCount')
            row['revenueStockCount'] = hit.get('stockCount')
            row['revenueLeaderCode'] = (hit.get('leader') or {}).get('code')
            row['revenueLaggardCode'] = (hit.get('laggard') or {}).get('code')
            row['revenuePeriodLabel'] = (agg or {}).get('periodLabel')
        out.append(row)
    return out


def market_flash_title(agg: dict[str, Any] | None) -> str | None:
    if not agg or not agg.get('ok'):
        return None
    mkt = agg.get('market') or {}
    label = agg.get('periodLabel') or '—'
    yi = mkt.get('monthRevYi')
    yoy = mkt.get('yoyPct')
    mom = mkt.get('momPct')
    parts = [f'月營收 {label} 上市櫃合計']
    if yi is not None:
        parts.append(f'{yi:.1f} 億')
    if yoy is not None:
        parts.append(f'YoY {yoy:+.1f}%')
    if mom is not None:
        parts.append(f'MoM {mom:+.1f}%')
    parts.append('（千元口徑·OpenAPI）')
    note = agg.get('note') or ''
    if '15' in note:
        parts.append('保險等可能至15日才齊')
    return ' '.join(parts)


def market_flash_item(agg: dict[str, Any] | None) -> dict[str, Any] | None:
    title = market_flash_title(agg)
    if not title:
        return None
    return {
        'time': (agg or {}).get('periodLabel') or '',
        'title': title,
        'cat': '總經',
        'mkt': 'TW',
        'source': 'industry_revenue_openapi',
    }
