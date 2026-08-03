# -*- coding: utf-8 -*-
"""pulse_extras.py — 脈動因子延伸資料（真實源，禁 mock）

提供：
  • sectors_light  — TWSE MI_INDEX type=IND 類股漲跌
  • tx_oi          — FinMind 台指期近月未平倉（日盤 position）
  • sbl_sell       — TWSE TWTASU 當日借券賣出成交量值（全市場合計）
  • nhnl           — 流動性樣本 250 日新高／新低家數（誠實標註樣本數）

設計：短逾時、可快取；失敗回 None，由 pulse_intel 進 pending。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_UA = {'User-Agent': 'Mozilla/5.0 (compatible; StockTerminal/5.0; +local)', 'Accept': 'application/json'}
_mem: Dict[str, Tuple[float, Any]] = {}


def _http_json(url: str, timeout: float = 8):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8', 'replace'))


def _fnum(v) -> Optional[float]:
    if v in (None, '', '-', '—', '--'):
        return None
    try:
        return float(str(v).replace(',', '').replace('+', '').strip())
    except Exception:
        return None


def _cache_get(key: str, ttl: float):
    hit = _mem.get(key)
    if hit and (time.time() - hit[0]) < ttl:
        return hit[1]
    return None


def _cache_set(key: str, val: Any):
    _mem[key] = (time.time(), val)


# ── 類股 ─────────────────────────────────────────────────────

def fetch_sectors_light(ttl: float = 300) -> Optional[Dict[str, Any]]:
    """TWSE MI_INDEX IND → [{name, changePct, close}]。"""
    ck = f'sectors:{date.today().isoformat()}'
    hit = _cache_get(ck, ttl)
    if hit is not None:
        return hit
    today = date.today()
    for back in range(0, 8):
        dd = (today - timedelta(days=back)).strftime('%Y%m%d')
        for url in (
            f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={dd}&type=IND&response=json',
            f'https://www.twse.com.tw/exchangeReport/MI_INDEX?date={dd}&type=IND&response=json',
        ):
            try:
                d = _http_json(url, timeout=8)
            except Exception:
                continue
            if d.get('stat') not in ('OK', 'ok'):
                continue
            sectors = _parse_sector_tables(d)
            if sectors:
                out = {'ok': True, 'date': dd, 'sectors': sectors, 'source': 'TWSE MI_INDEX IND'}
                _cache_set(ck, out)
                return out
    return None


def _parse_sector_tables(data: dict) -> List[dict]:
    out = []
    for t in data.get('tables') or []:
        title = str(t.get('title') or '')
        fields = t.get('fields') or []
        rows = t.get('data') or []
        strict = ('類' in title) and ('指數' in title or '漲跌' in title)
        loose = False
        if not strict and len(rows) >= 15 and rows:
            cell = str((rows[0][0] if isinstance(rows[0], list) and rows[0] else '') or '')
            if '類' in cell or '指數' in cell:
                loose = True
        fields_ok = any('收盤' in f for f in fields) and any('漲跌' in f for f in fields)
        if not (strict or loose) or not fields_ok:
            continue
        i_close = next((i for i, f in enumerate(fields) if '收盤' in f), 1)
        i_chg = next((i for i, f in enumerate(fields) if ('漲跌' in f) and ('幅' not in f) and ('%' not in f)), 2)
        i_pct = next((i for i, f in enumerate(fields) if '%' in f or '幅' in f), 3)
        for row in rows:
            if not row:
                continue
            name = str(row[0] or '').strip()
            if not name or ('類' not in name and '指數' not in name):
                continue
            close = _fnum(row[i_close] if i_close < len(row) else None)
            pct_raw = str(row[i_pct] if i_pct < len(row) else '').replace('%', '').replace(',', '')
            pct_raw = pct_raw.lstrip('+').strip('()')
            pct = _fnum(pct_raw)
            if close is None or pct is None:
                continue
            out.append({
                'name': name.replace('類指數', '').replace('指數', '').strip(),
                'close': close,
                'change': _fnum(row[i_chg] if i_chg < len(row) else None),
                'changePct': pct,
            })
        if out:
            return out
    return out


# ── 台指期 OI ────────────────────────────────────────────────

def fetch_tx_oi(ttl: float = 600) -> Optional[Dict[str, Any]]:
    """FinMind TaiwanFuturesDaily TX：近月（當日量最大）日盤 OI 與日變化。"""
    ck = f'txoi:{date.today().isoformat()}'
    hit = _cache_get(ck, ttl)
    if hit is not None:
        return hit
    end = date.today()
    start = end - timedelta(days=21)
    url = (
        'https://api.finmindtrade.com/api/v4/data?dataset=TaiwanFuturesDaily'
        f'&data_id=TX&start_date={start.isoformat()}&end_date={end.isoformat()}'
    )
    try:
        j = _http_json(url, timeout=12)
    except Exception as e:
        print('[pulse-extras] tx_oi', e)
        return None
    if j.get('status') not in (0, 200, '0', '200', None) and not j.get('data'):
        return None
    by_day: Dict[str, list] = {}
    for r in j.get('data') or []:
        if r.get('trading_session') != 'position':
            continue
        oi = _fnum(r.get('open_interest'))
        if oi is None or oi <= 0:
            continue
        d = str(r.get('date') or '')[:10]
        if d:
            by_day.setdefault(d, []).append(r)
    if len(by_day) < 2:
        return None
    days = sorted(by_day.keys())
    def best(day):
        return max(by_day[day], key=lambda x: float(x.get('volume') or 0))
    cur_d, prev_d = days[-1], days[-2]
    cur, prev = best(cur_d), best(prev_d)
    oi0, oi1 = float(cur['open_interest']), float(prev['open_interest'])
    if oi1 <= 0:
        return None
    px0, px1 = _fnum(cur.get('close')), _fnum(prev.get('close'))
    px_chg = ((px0 - px1) / px1 * 100.0) if (px0 and px1) else None
    out = {
        'ok': True,
        'date': cur_d,
        'prevDate': prev_d,
        'contract': str(cur.get('contract_date') or ''),
        'oi': oi0,
        'prevOi': oi1,
        'oiChg': oi0 - oi1,
        'oiChgPct': (oi0 - oi1) / oi1 * 100.0,
        'close': px0,
        'priceChgPct': px_chg,
        'volume': _fnum(cur.get('volume')),
        'source': 'FinMind TaiwanFuturesDaily TX',
    }
    _cache_set(ck, out)
    return out


# ── 借券賣出 ─────────────────────────────────────────────────

def fetch_sbl_sell(ttl: float = 600) -> Optional[Dict[str, Any]]:
    """TWSE TWTASU：當日融券賣出／借券賣出成交量值 → 全市場合計。"""
    ck = f'sbl:{date.today().isoformat()}'
    hit = _cache_get(ck, ttl)
    if hit is not None:
        return hit
    for url in (
        'https://www.twse.com.tw/exchangeReport/TWTASU?response=json',
        'https://www.twse.com.tw/rwd/zh/marginTrading/TWTASU?response=json',
    ):
        try:
            d = _http_json(url, timeout=10)
        except Exception as e:
            print('[pulse-extras] sbl', e)
            continue
        if d.get('stat') not in ('OK', 'ok'):
            continue
        rows = d.get('data') or []
        if not rows:
            continue
        margin_qty = margin_amt = sbl_qty = sbl_amt = 0.0
        for row in rows:
            if not row or len(row) < 5:
                continue
            margin_qty += _fnum(row[1]) or 0.0
            margin_amt += _fnum(row[2]) or 0.0
            sbl_qty += _fnum(row[3]) or 0.0
            sbl_amt += _fnum(row[4]) or 0.0
        # 日期：民國 title 或 date 欄
        ds = str(d.get('date') or '')
        if len(ds) == 8:
            ds = f'{ds[:4]}-{ds[4:6]}-{ds[6:8]}'
        out = {
            'ok': True,
            'date': ds or date.today().isoformat(),
            'marginSellQty': margin_qty,
            'marginSellAmt': margin_amt,
            'sblSellQty': sbl_qty,
            'sblSellAmt': sbl_amt,
            'sblSellYi': sbl_amt / 1e8,
            'marginSellYi': margin_amt / 1e8,
            'source': 'TWSE TWTASU',
            'title': d.get('title'),
        }
        _cache_set(ck, out)
        return out
    return None


# ── 250 日新高／新低（流動性樣本）────────────────────────────

# 流動權值／代表性樣本（上市為主）；誠實標註 sampleN，不做全市場幻想覆蓋
_NHNL_UNIVERSE = [
    '2330', '2317', '2454', '2303', '2382', '2308', '2891', '2881', '2882', '2884',
    '2886', '2892', '2885', '2880', '2801', '1216', '1301', '1303', '1326', '2002',
    '2603', '2609', '2615', '2412', '3045', '4904', '3711', '3034', '2379', '6669',
    '3443', '5274', '3661', '3035', '2327', '2345', '3008', '2357', '3231', '2408',
    '2912', '5871', '5876', '2207', '9910', '8454', '6505', '6770', '8046', '6488',
]


def fetch_nhnl_sample(ttl: float = 3600) -> Optional[Dict[str, Any]]:
    """流動性樣本 250 日新高／新低。
    優先本機 market.db；否則 Yahoo 並行抓取（預算內）。"""
    ck = f'nhnl:{date.today().isoformat()}'
    hit = _cache_get(ck, ttl)
    if hit is not None:
        return hit

    # 1) market.db
    db_path = os.path.join(_BASE, 'data', 'market.db')
    rows_map: Dict[str, List[Tuple]] = {}
    if os.path.isfile(db_path):
        try:
            import sqlite3
            with sqlite3.connect(db_path, timeout=5) as con:
                for code in _NHNL_UNIVERSE:
                    bars = con.execute(
                        'SELECT close FROM bars WHERE symbol=? AND market=? ORDER BY ts ASC',
                        (code, 'TW')).fetchall()
                    closes = [float(r[0]) for r in bars if r and r[0] is not None]
                    if len(closes) >= 250:
                        rows_map[code] = closes
        except Exception as e:
            print('[pulse-extras] nhnl db', e)

    source = 'market.db'
    # 2) Yahoo 補齊不足
    need = [c for c in _NHNL_UNIVERSE if c not in rows_map]
    if need:
        source = 'market.db+yahoo' if rows_map else 'yahoo'

        def _one(code: str):
            """直連 Yahoo chart，避免 import server 造成循環依賴。"""
            last_err = None
            for host in ('query1', 'query2'):
                url = f'https://{host}.finance.yahoo.com/v8/finance/chart/{code}.TW?range=1y&interval=1d'
                try:
                    j = _http_json(url, timeout=6)
                    res = (j.get('chart') or {}).get('result') or []
                    if not res:
                        continue
                    cls = ((res[0].get('indicators') or {}).get('quote') or [{}])[0].get('close') or []
                    closes = [float(x) for x in cls if x is not None]
                    return code, closes if len(closes) >= 200 else None  # 1y≈250；允許略少
                except Exception as e:
                    last_err = e
            return code, None

        with ThreadPoolExecutor(max_workers=8) as ex:
            futs = [ex.submit(_one, c) for c in need[:36]]
            try:
                for f in as_completed(futs, timeout=7):
                    try:
                        code, closes = f.result()
                    except Exception:
                        continue
                    if closes:
                        rows_map[code] = closes
            except Exception:
                for f in futs:
                    if f.done():
                        try:
                            code, closes = f.result()
                            if closes:
                                rows_map[code] = closes
                        except Exception:
                            pass

    if len(rows_map) < 12:
        return None

    nh = nl = 0
    for closes in rows_map.values():
        window = closes[-250:]
        last = window[-1]
        hi = max(window)
        lo = min(window)
        # 容許 0.15% 浮點／跳空誤差
        if last >= hi * 0.9985:
            nh += 1
        if last <= lo * 1.0015:
            nl += 1

    out = {
        'ok': True,
        'date': date.today().isoformat(),
        'newHighs': nh,
        'newLows': nl,
        'sampleN': len(rows_map),
        'universeN': len(_NHNL_UNIVERSE),
        'nhRatio': (nh / (nh + nl)) if (nh + nl) else None,
        'source': source,
        'note': f'流動性樣本 {len(rows_map)}/{len(_NHNL_UNIVERSE)} 檔（非全市場）',
    }
    _cache_set(ck, out)
    return out


def fetch_all(budget: float = 8.0) -> Dict[str, Any]:
    """並行抓取延伸因子，總預算 budget 秒。"""
    out = {'sectors': None, 'txOi': None, 'sbl': None, 'nhnl': None}
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix='pulse-x') as ex:
        futs = {
            ex.submit(fetch_sectors_light): 'sectors',
            ex.submit(fetch_tx_oi): 'txOi',
            ex.submit(fetch_sbl_sell): 'sbl',
            ex.submit(fetch_nhnl_sample): 'nhnl',
        }
        try:
            for f in as_completed(list(futs.keys()), timeout=budget):
                key = futs[f]
                try:
                    out[key] = f.result()
                except Exception as e:
                    print(f'[pulse-extras] {key}', e)
        except Exception:
            for f, key in futs.items():
                if f.done():
                    try:
                        out[key] = f.result()
                    except Exception:
                        pass
    return out
