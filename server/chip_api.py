# -*- coding: utf-8 -*-
"""
籌碼資料層（效率版）
--------------------
問題：舊 /chip/<sym> 對每檔重抓 T86 / MI_MARGN / TWT72U / TWTB4U 全市場表；
      且 TWT72U/TWTB4U 的 rwd/zh 路徑已回 HTML → JSON 解析失敗、逐檔噴 log、拖慢面板。

解法：
  1. 非個股／ETF（指數 ^*、總經 __*__）→ 立刻空回
  2. 全市場表「同交易日只抓一次」進記憶體快照，各股 O(1) 查表
  3. 借券／當沖改走仍回 JSON 的 exchangeReport 端點
  4. 經 TrustedDataLayer（節流 + 熔斷）；壞源 neg-cache，不再逐檔重試
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.request
from datetime import date, timedelta
from typing import Any, Callable, Dict, Optional

_CODE_RE = re.compile(r'^\d{4,6}[A-Z]?$')

# 由 server.configure 注入
_YF_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json,*/*',
}
_src_fetch_json: Optional[Callable] = None
_SourceBreakerOpen = Exception
_chip_streak: Optional[Callable] = None
_chip_history_record: Optional[Callable] = None

_SNAP_LOCK = threading.Lock()
_SNAP: Dict[str, Dict[str, Any]] = {}   # key -> {ts, by_code|None, err}
_SNAP_OK_TTL = 1800.0    # 成功快照 30 分
_SNAP_NEG_TTL = 300.0    # 失敗 neg-cache 5 分


def configure(*, yf_headers=None, src_fetch_json=None, source_breaker_open=None,
              chip_streak=None, chip_history_record=None):
    global _YF_HEADERS, _src_fetch_json, _SourceBreakerOpen
    global _chip_streak, _chip_history_record
    if yf_headers:
        _YF_HEADERS = yf_headers
    if src_fetch_json:
        _src_fetch_json = src_fetch_json
    if source_breaker_open:
        _SourceBreakerOpen = source_breaker_open
    if chip_streak:
        _chip_streak = chip_streak
    if chip_history_record:
        _chip_history_record = chip_history_record


def is_equity_code(clean: str) -> bool:
    s = (clean or '').strip().upper()
    if not s or s.startswith('^') or s.startswith('__'):
        return False
    return bool(_CODE_RE.match(s))


def _num(v):
    try:
        return float(str(v).replace(',', '').replace(' ', '').replace('%', ''))
    except Exception:
        return None


def _fetch_json(url: str, timeout: float = 8):
    """優先走 TrustedDataLayer；否則直抓。HTML／空 body → None。"""
    if _src_fetch_json is not None:
        try:
            return _src_fetch_json('twse-chip', url, headers=_YF_HEADERS,
                                   timeout=timeout, retries=0)
        except _SourceBreakerOpen:
            return None
        except Exception:
            return None
    try:
        req = urllib.request.Request(url, headers=_YF_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
        if not raw or raw.lstrip()[:1] in (b'<', b''):
            return None
        return json.loads(raw)
    except Exception:
        return None


def _snap_get(key: str):
    with _SNAP_LOCK:
        ent = _SNAP.get(key)
        if not ent:
            return False, None  # miss
        ttl = _SNAP_NEG_TTL if ent.get('err') else _SNAP_OK_TTL
        if time.time() - ent['ts'] > ttl:
            return False, None
        return True, ent.get('by_code')  # hit (by_code may be None on neg)


def _snap_set(key: str, by_code, err: bool = False):
    with _SNAP_LOCK:
        _SNAP[key] = {'ts': time.time(), 'by_code': by_code, 'err': err}


def _idx(fields, *hints, default=0):
    for i, f in enumerate(fields or []):
        for h in hints:
            if h in str(f):
                return i
    return default


def _col(fields, row, *keywords, avoid=()):
    """依關鍵字挑欄。

    優先順序：
      1. 欄名完全等於 keyword
      2. 較長 keyword 的子字串命中
      3. 同分數時取較短欄名（較精準）

    避免『自營商買賣超股數』誤中『外資自營商買賣超股數』、
    『借券餘額』誤中『前日借券餘額』。
    avoid: 欄名含任一子字串則略過。
    """
    ranked = sorted(keywords, key=lambda k: -len(k))
    best = None  # (score, index); score = (exact, kw_len, -field_len)
    for i, f in enumerate(fields or []):
        fs = str(f).strip()
        if avoid and any(a in fs for a in avoid):
            continue
        for kw in ranked:
            if fs == kw:
                score = (3, len(kw), -len(fs))
            elif kw in fs:
                if '本日' in kw and '前日' in fs:
                    continue
                score = (2, len(kw), -len(fs))
            else:
                continue
            if best is None or score > best[0]:
                best = (score, i)
            break
    if best is None or best[1] >= len(row):
        return None
    return _num(row[best[1]])


def _t86_dealer(fields, row):
    """自營商合計：僅接受欄名完全等於『自營商買賣超股數』；缺則自行買賣+避險。"""
    for i, f in enumerate(fields or []):
        if str(f).strip() == '自營商買賣超股數':
            return _num(row[i]) if i < len(row) else None
    self_net = None
    hedge_net = None
    for i, f in enumerate(fields or []):
        fs = str(f).strip()
        if fs == '自營商買賣超股數(自行買賣)':
            self_net = _num(row[i]) if i < len(row) else None
        elif fs == '自營商買賣超股數(避險)':
            hedge_net = _num(row[i]) if i < len(row) else None
    if self_net is None and hedge_net is None:
        return None
    return (self_net or 0.0) + (hedge_net or 0.0)


def _margn_pair(fields, row, name):
    """MI_MARGN 個股表欄名重複（融資／融券各有『今日餘額』『買進』等）。

    name: '今日餘額' | '買進' | '賣出' | '前日餘額'
    回傳 (融資欄, 融券欄) 數值；單位與 TWSE 原始相同（餘額為張）。
    """
    idxs = [i for i, f in enumerate(fields or []) if str(f).strip() == name]
    a = _num(row[idxs[0]]) if len(idxs) > 0 and idxs[0] < len(row) else None
    b = _num(row[idxs[1]]) if len(idxs) > 1 and idxs[1] < len(row) else None
    return a, b


def snap_t86(tdate: str) -> Optional[Dict[str, dict]]:
    key = f'T86:{tdate}'
    hit, cached = _snap_get(key)
    if hit:
        return cached
    url = (f'https://www.twse.com.tw/rwd/zh/fund/T86?date={tdate}'
           f'&selectType=ALLBUT0999&response=json')
    data = _fetch_json(url)
    by = None
    if data and data.get('stat') in ('OK', 'ok') and data.get('data'):
        fields = data.get('fields') or []
        ic = _idx(fields, '證券代號', '代號')
        by = {}
        for row in data['data']:
            if not row or ic >= len(row):
                continue
            code = str(row[ic]).strip()
            if not code:
                continue
            by[code] = {
                # 外陸資：用『外陸資*』關鍵字，不會命中『外資自營商*』
                # （勿 avoid『外資自營商』——欄名常含『不含外資自營商』會被誤殺）
                'foreign': _col(fields, row, '外陸資買賣超股數(不含外資自營商)',
                                '外陸資買賣超股數', '外陸資'),
                'trust':   _col(fields, row, '投信買賣超股數', '投信'),
                'dealer':  _t86_dealer(fields, row),
                'total':   _col(fields, row, '三大法人買賣超股數'),
            }
    _snap_set(key, by, err=(by is None))
    return by


def snap_margn(tdate: str) -> Optional[Dict[str, dict]]:
    key = f'MARGN:{tdate}'
    hit, cached = _snap_get(key)
    if hit:
        return cached
    url = (f'https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN'
           f'?date={tdate}&selectType=ALL&response=json')
    data = _fetch_json(url)
    by = None
    if data and data.get('stat') in ('OK', 'ok'):
        by = {}
        for t in (data.get('tables') or []):
            rows = t.get('data') or []
            fields = t.get('fields') or []
            # 只吃個股彙總表（有『代號』）；略過『信用交易統計』摘要表
            if not any('代號' in str(f) for f in fields):
                continue
            if not rows:
                continue
            ic = _idx(fields, '證券代號', '股票', '代號')
            for row in rows:
                if not row or ic >= len(row):
                    continue
                code = str(row[ic]).strip()
                if not code or not code[0].isdigit():
                    continue
                # TWSE 欄名重複：第 1 組=融資、第 2 組=融券；餘額單位為張
                mb_lot, sb_lot = _margn_pair(fields, row, '今日餘額')
                # 具名欄位後備（若 TWSE 改版）
                if mb_lot is None:
                    mb_lot = _col(fields, row, '融資餘額', '融資今日餘額')
                if sb_lot is None:
                    sb_lot = _col(fields, row, '融券餘額', '融券今日餘額')
                m_buy, s_buy = _margn_pair(fields, row, '買進')
                m_sell, s_sell = _margn_pair(fields, row, '賣出')
                # 張 → 股（前端 chip_v3 以 /1000 顯示張）
                mb = mb_lot * 1000.0 if mb_lot is not None else None
                sb = sb_lot * 1000.0 if sb_lot is not None else None
                by[code] = {
                    'marginBalance': mb,
                    'shortBalance':  sb,
                    # 增減以張計（買進−賣出）；乘 1000 與餘額同單位（股）
                    'marginChange':  ((m_buy or 0) - (m_sell or 0)) * 1000.0
                                    if (m_buy is not None or m_sell is not None) else None,
                    'shortChange':   ((s_buy or 0) - (s_sell or 0)) * 1000.0
                                    if (s_buy is not None or s_sell is not None) else None,
                }
        if not by:
            by = None
    _snap_set(key, by, err=(by is None))
    return by


def snap_twt72u(tdate: str) -> Optional[Dict[str, dict]]:
    """借券餘額 — 用仍回 JSON 的 exchangeReport（rwd/zh 已變 HTML）。"""
    key = f'TWT72U:{tdate}'
    hit, cached = _snap_get(key)
    if hit:
        return cached
    url = (f'https://www.twse.com.tw/exchangeReport/TWT72U'
           f'?response=json&date={tdate}&selectType=ALL')
    data = _fetch_json(url, timeout=12)
    by = None
    if data and data.get('stat') in ('OK', 'ok') and data.get('data'):
        fields = data.get('fields') or []
        ic = _idx(fields, '證券代號', '代號')
        by = {}
        for row in data['data']:
            if not row or ic >= len(row):
                continue
            code = str(row[ic]).strip()
            if not code:
                continue
            by[code] = {
                'sellVolume': _col(fields, row, '本日異動股借券', '借券賣出'),
                'balance':    _col(fields, row, '本日借券餘額股', '本日借券餘額', '借券賣出餘額'),
            }
    _snap_set(key, by, err=(by is None))
    return by


def snap_twtb4u(tdate: str) -> Optional[Dict[str, dict]]:
    """當沖量 — exchangeReport（含 tables）。"""
    key = f'TWTB4U:{tdate}'
    hit, cached = _snap_get(key)
    if hit:
        return cached
    url = f'https://www.twse.com.tw/exchangeReport/TWTB4U?response=json&date={tdate}'
    data = _fetch_json(url, timeout=12)
    by = None
    if data and data.get('stat') in ('OK', 'ok'):
        by = {}
        tables = data.get('tables') or []
        # 若無 tables，退 fields/data
        candidates = tables if tables else [{'fields': data.get('fields'), 'data': data.get('data')}]
        for t in candidates:
            rows = t.get('data') or []
            fields = t.get('fields') or []
            if len(rows) < 10:
                continue
            ic = _idx(fields, '證券代號', '代號')
            # 確認有代號欄
            if not fields or ic >= len(fields) or '代號' not in str(fields[ic]):
                # 試找
                ic = _idx(fields, '證券代號', '代號', default=-1)
                if ic < 0:
                    continue
            for row in rows:
                if not row or ic >= len(row):
                    continue
                code = str(row[ic]).strip()
                if not code or not code[0].isdigit():
                    continue
                vol = _col(fields, row, '當日沖銷交易成交股數', '當沖成交股數', '成交股數')
                ratio = _col(fields, row, '當日沖銷交易比率', '當沖比')
                by[code] = {'volume': vol, 'ratioPct': ratio}
        if not by:
            by = None
    _snap_set(key, by, err=(by is None))
    return by


def resolve_t86_date(max_back: int = 8):
    """往回找最近有 T86 的交易日，回 (date, by_code|None)。"""
    for back in range(0, max_back):
        d = (date.today() - timedelta(days=back)).strftime('%Y%m%d')
        by = snap_t86(d)
        if by:
            return d, by
    return date.today().strftime('%Y%m%d'), None


def _tpex_inst(clean: str) -> Optional[dict]:
    url = 'https://www.tpex.org.tw/openapi/v1/tpex_3insti_daily_trading'
    try:
        if _src_fetch_json is not None:
            ta = _src_fetch_json('twse-chip', url, headers=_YF_HEADERS, timeout=8, retries=0)
        else:
            ta = _fetch_json(url)
    except Exception:
        return None
    if not isinstance(ta, list):
        return None
    NET = ('買賣超', 'netbuysell', 'net', 'diff', 'buysell')

    def pick(row, must, avoid=()):
        cand = None
        for k, v in row.items():
            kl = k.lower()
            if not any((m in k) or (m.lower() in kl) for m in must):
                continue
            if any((a in k) or (a.lower() in kl) for a in avoid):
                continue
            if any((n in k) or (n in kl) for n in NET):
                val = _num(v)
                if val is not None:
                    return val
            elif cand is None:
                cand = _num(v)
        return cand

    for row in ta:
        if not isinstance(row, dict):
            continue
        rc = ''
        for k, v in row.items():
            if ('代號' in k) or ('code' in k.lower()):
                rc = str(v).strip(); break
        if rc != clean:
            continue
        return {
            'foreign': pick(row, ('外資及陸資買賣超', 'foreigninvestor', 'foreign', '外資'),
                            avoid=('不含', 'exclud', 'dealer', '自營', 'hedge', '避險', 'self', '自行')),
            'trust':   pick(row, ('投信', 'investmenttrust', 'trust'),
                            avoid=('foreign', '外資', 'dealer', '自營')),
            'dealer':  pick(row, ('自營商買賣超', 'dealer', '自營'),
                            avoid=('foreign', '外資', 'hedge', '避險', 'self', '自行', 'propriet', '不含', 'exclud')),
            'total':   pick(row, ('三大法人', 'totalinstitution', 'institutionalinvestorstotal', 'total'),
                            avoid=('foreign', '外資', 'dealer', '自營', 'trust', '投信')),
            '_chipSource': 'TPEx',
        }
    return None


def build_chip(sym: str) -> dict:
    """組出 /chip 回應 dict（呼叫端負責 HTTP cache／寫出）。"""
    clean = (sym or '').replace('.TW', '').replace('.TWO', '').strip().upper()
    today = date.today().strftime('%Y%m%d')
    if not is_equity_code(clean):
        return {
            'symbol': sym, 'date': today, 'inst': None, 'margin': None,
            '_note': '非個股無籌碼（指數／總經／合成序列）',
        }

    tdate, t86 = resolve_t86_date()
    out = {'symbol': sym, 'date': tdate, 'inst': None, 'margin': None}

    if t86 and clean in t86:
        out['inst'] = dict(t86[clean])

    if out['inst'] is None:
        tp = _tpex_inst(clean)
        if tp:
            src = tp.pop('_chipSource', 'TPEx')
            out['inst'] = tp
            out['_chipSource'] = src

    marg = snap_margn(tdate)
    if marg and clean in marg:
        out['margin'] = marg[clean]

    lend = snap_twt72u(tdate)
    if lend and clean in lend:
        out['shortLend'] = lend[clean]

    dayt = snap_twtb4u(tdate)
    if dayt and clean in dayt:
        out['dayTrade'] = dayt[clean]

    if _chip_streak:
        try:
            out['streak'] = _chip_streak(clean)
        except Exception:
            pass
    if _chip_history_record:
        try:
            _chip_history_record(clean, out)
        except Exception:
            pass

    try:
        import tdcc_holders as th
        snap = th.stock_snapshot(clean)
        out['holders'] = {
            'ok': snap.get('ok'),
            'chartId': snap.get('chartId'),
            'last': snap.get('last'),
            'points': snap.get('points'),
            'risk': snap.get('risk'),
        }
    except Exception:
        out['holders'] = None

    return out
