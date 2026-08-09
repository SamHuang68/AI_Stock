# -*- coding: utf-8 -*-
"""pulse_extras.py — 脈動因子延伸資料（真實源，禁 mock）

公開 JSON 欄位（camelCase，與 /pulse.extras 對齊）：
  sectors → {ok, date, sectors:[{name, changePct, close}], source}
  txOi    → {ok, date, contract, oi, oiChgPct, priceChgPct, ...}
  sbl     → {ok, date, sblSellYi, marginSellYi, ...}
  nhnl    → {ok, newHighs, newLows, sampleN, note, ...}

設計：短逾時、可快取；失敗回 None，由 pulse_intel 進 pending。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_UA = {'User-Agent': 'Mozilla/5.0 (compatible; StockTerminal/5.0; +local)', 'Accept': 'application/json'}
_mem: Dict[str, Tuple[float, Any]] = {}

NHNL_MIN_BARS = 250
NHNL_MIN_SAMPLE = 12
NHNL_YAHOO_WORKERS = 6
NHNL_YAHOO_BUDGET = 7.0


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
            except Exception as e:
                print('[pulse-extras] sectors', dd, type(e).__name__, e)
                continue
            if d.get('stat') not in ('OK', 'ok'):
                continue
            sectors = parse_sector_tables(d)
            if sectors:
                out = {'ok': True, 'date': dd, 'sectors': sectors, 'source': 'TWSE MI_INDEX IND'}
                _cache_set(ck, out)
                return out
    return None


def parse_sector_tables(data: dict) -> List[dict]:
    """解析 MI_INDEX IND tables → 類股列（供單測）。"""
    out: List[dict] = []
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

def compute_tx_oi(by_day: Dict[str, list]) -> Optional[Dict[str, Any]]:
    """由日→列 計算同契約 OI 變化。換月無法對齊時回 None（進 pending）。"""
    if len(by_day) < 2:
        return None
    days = sorted(by_day.keys())

    def best(day: str, contract: Optional[str] = None):
        rows = by_day.get(day) or []
        if contract is not None:
            rows = [r for r in rows if str(r.get('contract_date') or '') == contract]
        if not rows:
            return None
        return max(rows, key=lambda x: float(x.get('volume') or 0))

    cur_d = days[-1]
    cur = best(cur_d)
    if not cur:
        return None
    contract = str(cur.get('contract_date') or '')
    if not contract:
        return None

    prev = prev_d = None
    for d in reversed(days[:-1]):
        p = best(d, contract)
        if p is not None:
            prev, prev_d = p, d
            break
    if prev is None or prev_d is None:
        # 換月週：不同契約 OI 不可直接相減
        return None

    oi0 = _fnum(cur.get('open_interest'))
    oi1 = _fnum(prev.get('open_interest'))
    if oi0 is None or oi1 is None or oi1 <= 0:
        return None
    px0, px1 = _fnum(cur.get('close')), _fnum(prev.get('close'))
    px_chg = ((px0 - px1) / px1 * 100.0) if (px0 and px1) else None
    return {
        'ok': True,
        'date': cur_d,
        'prevDate': prev_d,
        'contract': contract,
        'oi': float(oi0),
        'prevOi': float(oi1),
        'oiChg': float(oi0) - float(oi1),
        'oiChgPct': (float(oi0) - float(oi1)) / float(oi1) * 100.0,
        'close': px0,
        'priceChgPct': px_chg,
        'volume': _fnum(cur.get('volume')),
        'source': 'FinMind TaiwanFuturesDaily TX',
    }


def fetch_tx_oi(ttl: float = 600) -> Optional[Dict[str, Any]]:
    """FinMind TaiwanFuturesDaily TX：近月同契約日盤 OI 與日變化。"""
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
        print('[pulse-extras] tx_oi', type(e).__name__, e)
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
    out = compute_tx_oi(by_day)
    if out:
        _cache_set(ck, out)
    return out


# ── 借券賣出 ─────────────────────────────────────────────────

def aggregate_sbl_rows(rows: list, ds: str = '', title: Any = None) -> Optional[Dict[str, Any]]:
    """TWTASU data 列 → 全市場合計（供單測）。"""
    if not rows:
        return None
    margin_qty = margin_amt = sbl_qty = sbl_amt = 0.0
    n = 0
    for row in rows:
        if not row or len(row) < 5:
            continue
        margin_qty += _fnum(row[1]) or 0.0
        margin_amt += _fnum(row[2]) or 0.0
        sbl_qty += _fnum(row[3]) or 0.0
        sbl_amt += _fnum(row[4]) or 0.0
        n += 1
    if n <= 0:
        return None
    if len(ds) == 8 and ds.isdigit():
        ds = f'{ds[:4]}-{ds[4:6]}-{ds[6:8]}'
    return {
        'ok': True,
        'date': ds or date.today().isoformat(),
        'marginSellQty': margin_qty,
        'marginSellAmt': margin_amt,
        'sblSellQty': sbl_qty,
        'sblSellAmt': sbl_amt,
        'sblSellYi': sbl_amt / 1e8,
        'marginSellYi': margin_amt / 1e8,
        'source': 'TWSE TWTASU',
        'title': title,
    }


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
            print('[pulse-extras] sbl', type(e).__name__, e)
            continue
        if d.get('stat') not in ('OK', 'ok'):
            continue
        out = aggregate_sbl_rows(d.get('data') or [], str(d.get('date') or ''), d.get('title'))
        if out:
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


def count_nhnl(closes_map: Dict[str, List[float]], min_bars: int = NHNL_MIN_BARS) -> Optional[Dict[str, Any]]:
    """流動性樣本 NHNL。不足 min_bars 的序列排除；樣本 < NHNL_MIN_SAMPLE → None。"""
    usable = {c: closes for c, closes in closes_map.items() if closes and len(closes) >= min_bars}
    if len(usable) < NHNL_MIN_SAMPLE:
        return None
    nh = nl = 0
    for closes in usable.values():
        window = closes[-min_bars:]
        last = window[-1]
        hi = max(window)
        lo = min(window)
        # 平坦窗不雙計；容許 0.15% 浮點／跳空
        if hi <= lo * 1.0001:
            continue
        if last >= hi * 0.9985:
            nh += 1
        elif last <= lo * 1.0015:
            nl += 1
    return {
        'ok': True,
        'date': date.today().isoformat(),
        'newHighs': nh,
        'newLows': nl,
        'sampleN': len(usable),
        'universeN': len(_NHNL_UNIVERSE),
        'windowBars': min_bars,
        'nhRatio': (nh / (nh + nl)) if (nh + nl) else None,
        'note': f'流動性樣本 {len(usable)}/{len(_NHNL_UNIVERSE)} 檔（非全市場）',
    }


def fetch_nhnl_sample(ttl: float = 3600) -> Optional[Dict[str, Any]]:
    """流動性樣本 250 日新高／新低。優先 market.db；否則 Yahoo（需 ≥250 根）。"""
    ck = f'nhnl:{date.today().isoformat()}'
    hit = _cache_get(ck, ttl)
    if hit is not None:
        return hit

    rows_map: Dict[str, List[float]] = {}
    db_path = os.path.join(_BASE, 'data', 'market.db')
    if os.path.isfile(db_path):
        try:
            import sqlite3
            with sqlite3.connect(db_path, timeout=5) as con:
                for code in _NHNL_UNIVERSE:
                    bars = con.execute(
                        'SELECT close FROM bars WHERE symbol=? AND market=? ORDER BY ts ASC',
                        (code, 'TW')).fetchall()
                    closes = [float(r[0]) for r in bars if r and r[0] is not None]
                    if len(closes) >= NHNL_MIN_BARS:
                        rows_map[code] = closes
        except Exception as e:
            print('[pulse-extras] nhnl db', type(e).__name__, e)

    source = 'market.db'
    need = [c for c in _NHNL_UNIVERSE if c not in rows_map]
    if need:
        source = 'market.db+yahoo' if rows_map else 'yahoo'

        def _one(code: str):
            """直連 Yahoo chart，避免 import server 造成循環依賴。"""
            for host in ('query1', 'query2'):
                # 2y 確保交易日 ≥250；不足仍排除，不冒充 250 日
                url = f'https://{host}.finance.yahoo.com/v8/finance/chart/{code}.TW?range=2y&interval=1d'
                try:
                    j = _http_json(url, timeout=6)
                    res = (j.get('chart') or {}).get('result') or []
                    if not res:
                        continue
                    cls = ((res[0].get('indicators') or {}).get('quote') or [{}])[0].get('close') or []
                    closes = [float(x) for x in cls if x is not None]
                    # 鐵律：不足 250 根不得冒充 250 日新高／新低
                    return code, closes if len(closes) >= NHNL_MIN_BARS else None
                except Exception as e:
                    print('[pulse-extras] nhnl yahoo', code, host, type(e).__name__)
            return code, None

        with ThreadPoolExecutor(max_workers=NHNL_YAHOO_WORKERS, thread_name_prefix='nhnl') as ex:
            futs = [ex.submit(_one, c) for c in need[:36]]
            try:
                for f in as_completed(futs, timeout=NHNL_YAHOO_BUDGET):
                    try:
                        code, closes = f.result()
                    except Exception as e:
                        print('[pulse-extras] nhnl fut', type(e).__name__, e)
                        continue
                    if closes:
                        rows_map[code] = closes
            except Exception as e:
                print('[pulse-extras] nhnl budget', type(e).__name__, e)
                for f in futs:
                    if f.done():
                        try:
                            code, closes = f.result()
                            if closes:
                                rows_map[code] = closes
                        except Exception:
                            pass

    out = count_nhnl(rows_map)
    if out:
        out['source'] = source
        _cache_set(ck, out)
    return out


def fetch_all(budget: float = 8.0) -> Dict[str, Any]:
    """並行抓取延伸因子，總預算 budget 秒。回傳固定鍵：sectors/txOi/sbl/nhnl。"""
    out: Dict[str, Any] = {'sectors': None, 'txOi': None, 'sbl': None, 'nhnl': None}
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
                    print(f'[pulse-extras] {key}', type(e).__name__, e)
        except Exception as e:
            print('[pulse-extras] fetch_all budget', type(e).__name__, e)
            for f, key in futs.items():
                if f.done():
                    try:
                        out[key] = f.result()
                    except Exception as e2:
                        print(f'[pulse-extras] {key} late', type(e2).__name__, e2)
    return out
