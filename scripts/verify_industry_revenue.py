#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verify industry monthly-revenue aggregates from OpenAPI caches (or fixture offline)."""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'server'))

import industry_revenue  # noqa: E402


def main() -> int:
    fixture = os.path.join(ROOT, 'tests', 'fixtures', 'industry_revenue_sample.json')
    with open(fixture, 'r', encoding='utf-8') as f:
        rows = json.load(f)
    agg = industry_revenue.build_from_openapi_rows(rows)
    print(json.dumps({
        'mode': 'fixture',
        'ok': agg.get('ok'),
        'periodLabel': agg.get('periodLabel'),
        'market': agg.get('market'),
        'topIndustries': (agg.get('industries') or [])[:5],
        'flash': industry_revenue.market_flash_title(agg),
    }, ensure_ascii=False, indent=2))
    if not agg.get('ok'):
        return 1

    try:
        import server as st  # noqa: WPS433
        industry_revenue.configure(st._openapi_lookup_list)
        live = industry_revenue.get_aggregate(force=True)
        print(json.dumps({
            'mode': 'live_openapi',
            'ok': live.get('ok'),
            'periodLabel': live.get('periodLabel'),
            'stockCount': live.get('stockCount'),
            'market': live.get('market'),
            'source': live.get('source'),
        }, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(json.dumps({'mode': 'live_openapi', 'ok': False, 'error': str(exc)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
