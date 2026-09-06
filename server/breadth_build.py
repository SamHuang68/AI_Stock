#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Build /breadth and /pulse shared breadth payload."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from datetime import date, timedelta
from typing import Any, Callable


def breadth_trace(base_dir: str, event: str, **fields: Any) -> None:
    """Persistent, bounded diagnostic trail for official breadth freshness."""
    try:
        path = os.path.join(base_dir, 'logs', 'breadth_trace.jsonl')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        row = {'ts': time.strftime('%Y-%m-%dT%H:%M:%S'), 'event': event, **fields}
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + '\n')
        if os.path.getsize(path) > 256 * 1024:
            with open(path, 'r', encoding='utf-8') as fh:
                tail = fh.readlines()[-500:]
            with open(path, 'w', encoding='utf-8') as fh:
                fh.writelines(tail)
    except Exception:
        pass


def build_breadth_payload(
    cache: Any,
    *,
    force: bool = False,
    base_dir: str,
    yf_headers: dict[str, str],
    twse_mis_index: Callable[..., dict],
    build_tw_market_fundamental: Callable[..., dict],
) -> dict:
    """Build breadth payload; writes breadth:v1:{ymd} cache entry."""
    key = f'breadth:v1:{date.today().strftime("%Y%m%d")}'
    if not force:
        c = cache.get(key)
        if c is not None:
            try:
                cached = json.loads(c.decode('utf-8') if isinstance(c, (bytes, bytearray)) else c)
                breadth_trace(base_dir, 'cache_hit', cache_key=key, payload_date=cached.get('date'),
                              limit_up=(cached.get('stocks') or {}).get('limitUp'),
                              limit_down=(cached.get('stocks') or {}).get('limitDown'))
                return cached
            except Exception:
                pass

    def _num(s):
        if s is None:
            return None
        t = str(s).replace(',', '').strip()
        if not t or t in ('-', '—'):
            return None
        try:
            return float(t)
        except Exception:
            return None

    def _pair(s):
        t = str(s or '').replace(',', '').strip()
        m = re.match(r'^([0-9.]+)\((\d+)\)$', t)
        if m:
            return int(float(m.group(1))), int(m.group(2))
        n = _num(t)
        return (int(n), None) if n is not None else (None, None)

    def _empty_ad():
        return {
            'up': None, 'limitUp': None, 'down': None, 'limitDown': None,
            'unchanged': None, 'unmatched': None, 'na': None,
            'traded': None, 'advRatio': None, 'net': None,
        }

    def _fill_ad(rows, col):
        ad = _empty_ad()
        for row in rows or []:
            if not row:
                continue
            label = str(row[0])
            cell = row[col] if len(row) > col else None
            if '上漲' in label:
                ad['up'], ad['limitUp'] = _pair(cell)
            elif '下跌' in label:
                ad['down'], ad['limitDown'] = _pair(cell)
            elif '持平' in label:
                ad['unchanged'], _ = _pair(cell)
            elif '未成交' in label:
                ad['unmatched'], _ = _pair(cell)
            elif '無比價' in label:
                ad['na'], _ = _pair(cell)
        u, d = ad['up'], ad['down']
        if u is not None and d is not None:
            ad['net'] = u - d
            den = u + d
            ad['advRatio'] = round(u / den, 4) if den > 0 else None
            flat = ad['unchanged'] or 0
            ad['traded'] = u + d + flat
        return ad

    out = {
        'ok': False,
        'date': None,
        'source': None,
        'stocks': _empty_ad(),
        'market': _empty_ad(),
        'turnover': None,
        'indices': {},
        'score': None,
        'pillars': None,
        'marketRows': None,
        'inst': None,
        'summary': None,
        'error': None,
        'limitDef': '證交所 MI_INDEX「股票」欄：上漲／下跌括號內＝漲停／跌停家數（上市普通股官方統計）',
    }

    ms_date = None
    tables = None
    for back in range(0, 12):
        dd = (date.today() - timedelta(days=back)).strftime('%Y%m%d')
        for url in (
            f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={dd}&type=MS&response=json',
            f'https://www.twse.com.tw/exchangeReport/MI_INDEX?date={dd}&type=MS&response=json',
        ):
            try:
                req = urllib.request.Request(url, headers=yf_headers)
                with urllib.request.urlopen(req, timeout=12) as resp:
                    d = json.loads(resp.read())
                if d.get('stat') not in ('OK', 'ok'):
                    breadth_trace(base_dir, 'official_rejected', requested_date=dd, url=url,
                                  stat=d.get('stat'), response_date=d.get('date'))
                    continue
                tables = d.get('tables') or []
                if not tables:
                    data8 = d.get('data8')
                    if data8:
                        tables = [{'title': '漲跌證券數合計', 'data': data8}]
                if tables:
                    ms_date = dd
                    out['source'] = 'TWSE MI_INDEX MS'
                    breadth_trace(base_dir, 'official_selected', requested_date=dd, url=url,
                                  response_date=d.get('date'), tables=len(tables))
                    break
            except Exception as e:
                breadth_trace(base_dir, 'official_error', requested_date=dd, url=url, error=str(e))
                print(f'[breadth] MI_INDEX {dd}: {e}')
                continue
        if ms_date:
            break

    if tables:
        out['date'] = f'{ms_date[:4]}-{ms_date[4:6]}-{ms_date[6:]}'
        for t in tables:
            title = str(t.get('title') or t.get('subtitle') or '')
            rows = t.get('data') or []
            has_ad = ('漲跌證券數' in title) or any(
                '上漲' in str((r or [''])[0]) for r in rows[:3]
            )
            if has_ad and any('上漲' in str((r or [''])[0]) for r in rows):
                out['market'] = _fill_ad(rows, 1)
                out['stocks'] = _fill_ad(rows, 2)
                out['ok'] = out['stocks'].get('up') is not None
            fields = t.get('fields') or []
            if '大盤統計' in title or any('成交金額' in str(f) for f in fields):
                stock_row = next((r for r in rows if r and str(r[0]).startswith('1.')), None)
                total_row = next((r for r in rows if r and '總計' in str(r[0])), None)
                sec_row = next((r for r in rows if r and '證券合計' in str(r[0])), None)
                pick = sec_row or stock_row
                if pick:
                    out['turnover'] = {
                        'stockAmt': _num(pick[1]) if len(pick) > 1 else None,
                        'stockShares': _num(pick[2]) if len(pick) > 2 else None,
                        'stockTrades': _num(pick[3]) if len(pick) > 3 else None,
                        'totalAmt': _num(total_row[1]) if total_row and len(total_row) > 1 else None,
                    }
        breadth_trace(base_dir, 'payload_built', payload_date=out.get('date'), source=out.get('source'),
                      limit_up=(out.get('stocks') or {}).get('limitUp'),
                      limit_down=(out.get('stocks') or {}).get('limitDown'))

    try:
        out['indices'] = twse_mis_index('tse_t00.tw|otc_o00.tw')
    except Exception as e:
        print('[breadth] twindex', e)
        out['indices'] = {}

    try:
        fund = build_tw_market_fundamental('^TWII')
        out['score'] = fund.get('score')
        out['pillars'] = fund.get('pillars')
        out['marketRows'] = fund.get('marketRows')
        out['summary'] = fund.get('summary')
    except Exception as e:
        print('[breadth] fundamental', e)

    try:
        mf_key = f'marketflow:{date.today().strftime("%Y%m%d")}'
        cached_mf = cache.get(mf_key)
        if cached_mf is None:
            cached_mf = cache.get(f'marketflow:{date.today().strftime("%Y-%m-%d")}')
        if cached_mf:
            mf = json.loads(cached_mf.decode('utf-8') if isinstance(cached_mf, (bytes, bytearray)) else cached_mf)
            out['inst'] = mf.get('inst')
    except Exception:
        pass

    if not out['ok'] and not out['error']:
        out['error'] = '尚無最近交易日之漲跌家數（可能為休市或 TWSE 尚未公布）'

    body = json.dumps(out, ensure_ascii=False).encode()
    cache.set(key, body, ttl=120)
    return out
