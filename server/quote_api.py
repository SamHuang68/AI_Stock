# -*- coding: utf-8 -*-
"""
報價／特殊圖 fetch 層（H2 從 server.py 拆出）

configure() 由 server 啟動時注入 cache／src_record，避免循環 import。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import unquote

import chart_registry as cr

try:
    import slog
    log = slog.get_logger('quote_api')
except Exception:
    log = None

_CFG: Dict[str, Any] = {
    'cache': None,
    'src_record': None,
    'yf_headers': None,
    'yf_range': '5y',
    'yf_interval': '1d',
}


def configure(*, cache, src_record, yf_headers, yf_range='5y', yf_interval='1d') -> None:
    _CFG['cache'] = cache
    _CFG['src_record'] = src_record
    _CFG['yf_headers'] = yf_headers
    _CFG['yf_range'] = yf_range
    _CFG['yf_interval'] = yf_interval


def get_margin_ratio_chart_json(rng=None):
    try:
        import margin_ratio as mr
        return mr.chart_json(range_key=(rng or 'max'))
    except Exception as e:
        if log:
            log.exception('get_margin_ratio_chart_json failed')
        else:
            print('[quote_api] get_margin_ratio_chart_json failed:', e)
        return b'{"chart":{"result":null,"error":"failed"}}'


def get_macro_track_chart_json(sym, rng=None):
    try:
        import macro_api as ma
        return ma.get_macro_track_chart_json(sym, rng)
    except Exception as e:
        if log:
            log.exception('get_macro_track_chart_json failed')
        else:
            print('[quote_api] get_macro_track_chart_json failed:', e)
        return {'chart': {'result': None, 'error': str(e)}}


def _resolve_macro_id(sym_up: str) -> Optional[str]:
    ids = cr.MACRO_TRACK_IDS
    if sym_up in ids:
        return sym_up
    for x in ids:
        if sym_up.startswith(x.rstrip('_')) or sym_up == x:
            return x if x in ids else None
    return None


def fetch_one(sym, rng=None, interval=None, nocache=False) -> Tuple[str, Any, bool]:
    """回 (symbol, data_bytes_or_dict_or_None, from_cache)。"""
    cache = _CFG['cache']
    src_record: Optional[Callable] = _CFG['src_record']
    yf_headers = _CFG['yf_headers'] or {}
    yf_range = _CFG['yf_range']
    yf_interval = _CFG['yf_interval']

    if sym == '__MARGIN_RATIO__' or str(sym).startswith('__MARGIN_RATIO__'):
        try:
            data = get_margin_ratio_chart_json(rng)
            return '__MARGIN_RATIO__', data, False
        except Exception as e:
            if log:
                log.warning('fetch_one margin_ratio: %s', e)
            return '__MARGIN_RATIO__', None, False

    # TDCC 集中度
    try:
        import tdcc_holders as th
        code = th.parse_holders_sym(sym)
        if code:
            cid = th.holders_chart_id(code)
            chart = th.get_chart(code, ensure=True)
            try:
                import macro_track as mt
                primary = cr.pick_primary_series(chart.get('series') or [], cid)
                pts = (primary or {}).get('points') or []
                data = mt.points_to_yf_like(pts, cid, chart.get('name') or cid)
                return cid, json.dumps(data).encode(), False
            except Exception:
                return cid, json.dumps(chart).encode(), False
    except Exception as e:
        if log:
            log.warning('fetch_one holders: %s', e)

    # 櫃買／台指期
    try:
        import tw_index_charts as tic
        _raw = unquote(str(sym or ''))
        if tic.is_tw_index_chart_sym(_raw) or tic.is_tw_index_chart_sym(str(sym or '')):
            canon = '__TXF__' if 'TXF' in str(sym).upper() else '^TWOII'
            cache_key = f'{canon}|1d|{rng or "max"}'
            if cache is not None and not nocache:
                cached = cache.get(cache_key)
                if cached is not None:
                    return canon, cached, True
            data = tic.chart_json(canon, range_key=(rng or 'max'))
            if cache is not None and not nocache and data:
                cache.set(cache_key, data)
            return canon, data, False
    except Exception as e:
        if log:
            log.warning('fetch_one tw_index: %s', e)

    _sym_up = str(sym or '').upper()
    cid = _resolve_macro_id(_sym_up)
    if cid:
        try:
            data = get_macro_track_chart_json(cid, rng)
            body = data if isinstance(data, (bytes, bytearray)) else json.dumps(data).encode()
            return cid, body, False
        except Exception as e:
            if log:
                log.warning('fetch_one macro: %s', e)
            return sym, None, False

    rng = rng or yf_range
    interval = interval or yf_interval
    cache_key = f'{sym}|{interval}|{rng}'
    if cache is not None and not nocache:
        cached = cache.get(cache_key)
        if cached is not None:
            return sym, cached, True
    if str(sym).endswith('.TW') and not str(sym).endswith('.TWO'):
        candidates = [sym, sym[:-3] + '.TWO']
    elif str(sym).endswith('.TWO'):
        candidates = [sym, sym[:-4] + '.TW']
    else:
        candidates = [sym]
    _t0 = time.time()
    for candidate in candidates:
        for base in ('query1', 'query2'):
            url = f'https://{base}.finance.yahoo.com/v8/finance/chart/{candidate}?interval={interval}&range={rng}'
            try:
                req = urllib.request.Request(url, headers=yf_headers)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                parsed = json.loads(data)
                if parsed.get('chart', {}).get('result'):
                    if cache is not None and not nocache:
                        cache.set(cache_key, data)
                    if src_record:
                        src_record('yahoo', True, int((time.time() - _t0) * 1000))
                    return sym, data, False
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    break
                continue
            except Exception:
                continue
    if src_record:
        src_record('yahoo', False, int((time.time() - _t0) * 1000), 'all candidates failed')
    return sym, None, False


def jobs_snapshot() -> Dict[str, Any]:
    """彙整各模組回補／刷新狀態，供 /health。"""
    out: Dict[str, Any] = {}
    try:
        import macro_track as mt
        lock = getattr(mt, '_REFRESH_LOCK', None) or {}
        out['macro_track'] = {
            'running': bool(lock.get('running')),
            'note': lock.get('note') or '',
            'last': lock.get('last'),
        }
    except Exception as e:
        out['macro_track'] = {'error': str(e)}
    try:
        import margin_cycle as mc
        st = getattr(mc, '_backfill_state', None) or {}
        out['margin_cycle'] = dict(st)
    except Exception as e:
        out['margin_cycle'] = {'error': str(e)}
    try:
        import tdcc_holders as th
        st = getattr(th, '_backfill_state', None) or {}
        out['tdcc_holders'] = dict(st)
    except Exception as e:
        out['tdcc_holders'] = {'error': str(e)}
    try:
        import margin_ratio as mr
        st = getattr(mr, '_backfill_state', None) or getattr(mr, 'backfill_state', None)
        out['margin_ratio'] = dict(st) if isinstance(st, dict) else {'note': 'no state attr'}
    except Exception as e:
        out['margin_ratio'] = {'error': str(e)}
    try:
        import job_queue as jq
        out['queue'] = jq.status()
    except Exception as e:
        out['queue'] = {'error': str(e)}
    return out
