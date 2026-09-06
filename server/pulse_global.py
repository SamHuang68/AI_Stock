#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pulse global quote batching for /pulse overview panel."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from deadline import collect_named


@dataclass
class PulseGlobalDeps:
    quote_pool: Any = None
    trusted_quote_override: Callable[[str], dict | None] | None = None
    fetch_one: Callable[..., Any] | None = None
    yf_mktbar_day_change: Callable[[dict], dict | None] | None = None


_deps = PulseGlobalDeps()


def configure(**kwargs: Any) -> None:
    for key, value in kwargs.items():
        setattr(_deps, key, value)


def yf_batch_quotes(syms: list[str] | None) -> list[dict]:
    """Lightweight Yahoo batch for pulse global influence panel."""
    labels = {
        '^DJI': '道瓊', '^GSPC': 'S&P500', '^IXIC': 'NASDAQ',
        'CL=F': '原油', 'GC=F': '黃金', 'HG=F': '銅', 'SI=F': '白銀',
        'DX-Y.NYB': '美元指數', 'DX=F': '美元指數',
        '^VIX': 'VIX 波動', 'TWD=X': '美元／台幣',
        '^SOX': '費半', '^N225': '日經', '^KS11': '韓國', '^HSI': '恆生',
        'NVDA': 'NVIDIA', 'AVGO': 'Broadcom', 'TSM': '台積電ADR',
        '2330.TW': '台積電', '0050.TW': '元大台灣50',
    }
    roles = {
        'GC=F': '避險指標',
        'HG=F': '產業景氣循環',
        '^VIX': '恐慌指標',
        'CL=F': '能源景氣',
        'DX-Y.NYB': '資金流向',
        'DX=F': '資金流向',
    }

    def _one(sym: str):
        try:
            ov = _deps.trusted_quote_override(sym) if _deps.trusted_quote_override else None
            if ov and ov.get('price') is not None:
                row = {
                    'symbol': sym, 'name': labels.get(sym, sym),
                    'price': ov['price'], 'changePct': ov.get('changePct'),
                    'prevClose': ov.get('prevClose'),
                    'source': ov.get('source') or 'override',
                    'asOf': ov.get('asOf'),
                    'session': ov.get('session') or 'latest_available',
                    'referenceType': ov.get('referenceType') or 'previous_close',
                }
                if sym in roles:
                    row['role'] = roles[sym]
                return row
            _, data, _ = _deps.fetch_one(sym, '5d', '1d', False)
            if not data:
                return None
            res = (json.loads(data).get('chart') or {}).get('result') or []
            if not res:
                return None
            q = _deps.yf_mktbar_day_change(res[0])
            if not q:
                return None
            m = res[0].get('meta') or {}
            row = {
                'symbol': sym,
                'name': labels.get(sym, m.get('shortName') or sym),
                'price': q['price'],
                'changePct': q['changePct'],
                'prevClose': q['prevClose'],
                'source': 'yahoo-mktbar',
                'asOf': (time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(int(m.get('regularMarketTime'))))
                         if m.get('regularMarketTime') else None),
                'session': str(m.get('marketState') or 'latest_available').lower(),
                'referenceType': 'previous_regular_close',
            }
            if sym in roles:
                row['role'] = roles[sym]
            return row
        except Exception as e:
            print('[pulse-global]', sym, e)
            return None

    out: list[dict] = []
    jobs = {str(sym): _deps.quote_pool.submit(_one, sym) for sym in (syms or [])}
    values, outcomes = collect_named(jobs, timeout=6.0, executor=_deps.quote_pool)
    out.extend(row for row in values.values() if row)
    if any(value != 'ok' for value in outcomes.values()):
        print('[pulse-global] bounded outcomes', outcomes)
    order = {s: i for i, s in enumerate(syms or [])}
    out.sort(key=lambda r: order.get(r.get('symbol'), 999))
    return out
