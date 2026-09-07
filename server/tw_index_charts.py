#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tw_index_charts.py — 台股指數／台指期可信日線（覆寫 Yahoo 壞源）

  ^TWOII / TWOII  → TPEx 官方「日成交量值指數」st41（櫃買指數收盤）
  __TXF__         → FinMind TaiwanFuturesDaily（TX 近月，prefer 日盤 position）

Yahoo ^TWOII 日線各端點數值互斥（曾見 419/269/105），不可用。
台指期無穩定 Yahoo 連續合約代號；日線改走 FinMind + 本地 CSV 快取。
1天（range=1d + 分 K）改解析 Yahoo TW WTX& 頁內嵌 1 分走勢（含夜盤 15:00–05:00）。

輸出：Yahoo v8 chart 相容 JSON，供 /yf/^TWOII、/yf/__TXF__。
"""
from __future__ import annotations

import csv
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
import re

if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(_BASE, 'data')
TWOII_CSV = os.path.join(DATA_DIR, 'twoii_daily.csv')
TXF_CSV = os.path.join(DATA_DIR, 'txf_daily.csv')
TZ_TPE = timezone(timedelta(hours=8))

_UA = {
    'User-Agent': 'Mozilla/5.0 (compatible; StockTerminal/5.0; +local)',
    'Accept': 'application/json,text/plain,*/*',
}
_lock = threading.Lock()
_http_lock = threading.Lock()
_last_http = 0.0
_HTTP_GAP = 0.35

# 記憶體快取：symbol -> (mtime_or_build_ts, rows)
_mem: Dict[str, Tuple[float, List[Tuple]]] = {}
_REFRESH_TTL = 300.0  # 5 分鐘內不重抓外部
_WTX_HTML_TTL = 20.0
_wtx_html_cache: Tuple[float, str] = (0.0, '')
_TXF_INTRADAY_INTERVALS = frozenset({'1m', '2m', '5m', '15m', '30m', '60m', '1h'})
_WTX_QUOTE_URL = 'https://tw.stock.yahoo.com/quote/WTX%26'


def _throttle():
    global _last_http
    with _http_lock:
        now = time.time()
        wait = _HTTP_GAP - (now - _last_http)
        if wait > 0:
            time.sleep(wait)
        _last_http = time.time()


def _http_json(url: str, timeout: int = 25):
    _throttle()
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8', 'replace'))


def _roc_to_iso(s: str) -> Optional[str]:
    """'115/07/23' 或 '115/7/23' → '2026-07-23'。"""
    s = (s or '').strip().replace('-', '/')
    parts = s.split('/')
    if len(parts) != 3:
        return None
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        if y < 1911:
            y += 1911
        return date(y, m, d).isoformat()
    except Exception:
        return None


def _iso_to_ts(iso: str) -> int:
    d = datetime.strptime(iso[:10], '%Y-%m-%d').replace(tzinfo=TZ_TPE)
    return int(d.timestamp())


def _range_days(range_key: Optional[str]) -> Optional[int]:
    rk = (range_key or 'max').lower()
    return {
        '1d': 5, '5d': 10, '1mo': 35, '3mo': 100, '6mo': 200,
        'ytd': None, '1y': 280, '2y': 560, '5y': 1400, '10y': 2800, 'max': None,
    }.get(rk, None)


def _filter_rows(rows: List[Tuple], range_key: Optional[str]) -> List[Tuple]:
    if not rows:
        return rows
    rk = (range_key or 'max').lower()
    if rk == 'ytd':
        start = date.today().replace(month=1, day=1).isoformat()
        return [r for r in rows if r[0] >= start]
    n = _range_days(rk)
    if n is None:
        return rows
    return rows[-n:] if len(rows) > n else rows


def _read_csv(path: str) -> List[Tuple]:
    if not os.path.isfile(path):
        return []
    out = []
    try:
        with open(path, encoding='utf-8') as f:
            rd = csv.DictReader(f)
            for row in rd:
                try:
                    iso = row['date'][:10]
                    o = float(row['open']); h = float(row['high'])
                    l = float(row['low']); c = float(row['close'])
                    v = float(row.get('volume') or 0)
                    out.append((iso, o, h, l, c, v))
                except Exception:
                    continue
    except Exception as e:
        print('[tw-index] read csv failed', path, e)
    out.sort(key=lambda r: r[0])
    return out


def _write_csv(path: str, rows: List[Tuple]):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['date', 'open', 'high', 'low', 'close', 'volume'])
        for r in rows:
            w.writerow(list(r[:6]))
    os.replace(tmp, path)


# ── 櫃買指數 ^TWOII（TPEx st41）────────────────────────────────

def _fetch_twoii_month(year: int, month: int) -> List[Tuple]:
    """抓單月櫃買指數。回傳 (iso, o,h,l,c,vol)。"""
    roc_y = year - 1911
    d = f'{roc_y}/{month:02d}/01'
    url = (
        'https://www.tpex.org.tw/web/stock/aftertrading/daily_trading_index/'
        f'st41_result.php?l=zh-tw&d={urllib.parse.quote(d)}&o=json'
    )
    try:
        j = _http_json(url, timeout=20)
    except Exception as e:
        print('[tw-index] st41', d, e)
        return []
    tables = j.get('tables') or []
    data = (tables[0].get('data') if tables else None) or []
    rows = []
    prev_c = None
    for row in data:
        if not row or len(row) < 5:
            continue
        iso = _roc_to_iso(str(row[0]))
        if not iso:
            continue
        try:
            c = float(str(row[4]).replace(',', ''))
        except Exception:
            continue
        try:
            chg = float(str(row[5]).replace(',', '')) if row[5] is not None else None
        except Exception:
            chg = None
        # 用昨收還原開盤近似；高低取 O/C 包絡（官方 st41 無口高／口低）
        if chg is not None:
            prev = c - chg
        elif prev_c is not None:
            prev = prev_c
        else:
            prev = c
        o, h, l = prev, max(prev, c), min(prev, c)
        rows.append((iso, o, h, l, c, 0.0))
        prev_c = c
    return rows


def _live_twoii_close() -> Optional[Tuple[str, float, float]]:
    """MIS otc_o00 → (iso, price, prevClose)。"""
    try:
        url = 'https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=otc_o00.tw&json=1&delay=0'
        j = _http_json(url, timeout=10)
        arr = j.get('msgArray') or []
        if not arr:
            return None
        m = arr[0]
        px = float(m.get('z') or m.get('y') or 0)
        prev = float(m.get('y') or 0)
        d = str(m.get('d') or '')
        if len(d) == 8:
            iso = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
        else:
            iso = date.today().isoformat()
        if px > 0:
            return iso, px, prev if prev > 0 else px
    except Exception as e:
        print('[tw-index] MIS TWOII', e)
    return None


def ensure_twoii(years: int = 6, force: bool = False) -> List[Tuple]:
    """載入／增量更新櫃買指數日線。"""
    with _lock:
        now = time.time()
        cached = _mem.get('^TWOII')
        if cached and not force and (now - cached[0]) < _REFRESH_TTL and cached[1]:
            return cached[1]

        rows = _read_csv(TWOII_CSV)
        last = rows[-1][0] if rows else None
        today = date.today()
        # 決定要抓的月份起點
        if last:
            try:
                start = datetime.strptime(last, '%Y-%m-%d').date().replace(day=1)
            except Exception:
                start = date(today.year - years, 1, 1)
        else:
            start = date(today.year - years, 1, 1)

        by_date: Dict[str, Tuple] = {r[0]: r for r in rows}
        y, m = start.year, start.month
        while (y, m) <= (today.year, today.month):
            for r in _fetch_twoii_month(y, m):
                by_date[r[0]] = r
            m += 1
            if m > 12:
                m = 1
                y += 1

        # 盤中／今日：用 MIS 覆寫最後收盤
        live = _live_twoii_close()
        if live:
            iso, px, prev = live
            o = prev
            by_date[iso] = (iso, o, max(o, px), min(o, px), px, 0.0)

        out = [by_date[k] for k in sorted(by_date)]
        if out:
            _write_csv(TWOII_CSV, out)
        _mem['^TWOII'] = (now, out)
        return out


# ── 台指期 __TXF__（FinMind 近月連續）────────────────────────

def _fetch_txf_finmind(start: str, end: str) -> List[Tuple]:
    """FinMind TaiwanFuturesDaily TX → 每日近月（position 日盤優先）。"""
    url = (
        'https://api.finmindtrade.com/api/v4/data?'
        + urllib.parse.urlencode({
            'dataset': 'TaiwanFuturesDaily',
            'data_id': 'TX',
            'start_date': start,
            'end_date': end,
        })
    )
    token = (os.environ.get('FINMIND_TOKEN') or os.environ.get('FINMIND_API_TOKEN') or '').strip()
    headers = dict(_UA)
    if token:
        headers['Authorization'] = f'Bearer {token}'
    try:
        _throttle()
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            j = json.loads(resp.read().decode('utf-8', 'replace'))
    except Exception as e:
        print('[tw-index] FinMind TX', e)
        return []
    if j.get('status') not in (0, 200, '0', '200', None) and j.get('msg') not in (None, 'success'):
        # FinMind 成功時常 status=200 msg=success
        if not j.get('data'):
            print('[tw-index] FinMind TX bad', j.get('status'), j.get('msg'))
            return []
    data = j.get('data') or []
    by_day: Dict[str, list] = {}
    for r in data:
        cd = str(r.get('contract_date') or '')
        if '/' in cd:
            continue
        try:
            c = float(r.get('close') or 0)
        except Exception:
            continue
        if c <= 0:
            continue
        d = str(r.get('date') or '')[:10]
        if not d:
            continue
        by_day.setdefault(d, []).append(r)

    out = []
    for d in sorted(by_day):
        rows = by_day[d]
        # prefer 日盤 position（有結算／OI），其次 after_market
        day = [r for r in rows if r.get('trading_session') == 'position']
        pool = day or [r for r in rows if r.get('trading_session') == 'after_market'] or rows
        best = max(pool, key=lambda r: float(r.get('volume') or 0))
        try:
            o = float(best.get('open') or best['close'])
            h = float(best.get('max') or best.get('high') or best['close'])
            l = float(best.get('min') or best.get('low') or best['close'])
            c = float(best['close'])
            v = float(best.get('volume') or 0)
        except Exception:
            continue
        out.append((d, o, h, l, c, v))
    return out


def _live_txf_close() -> Optional[Tuple[str, float, float]]:
    """沿用 server /txf 同源：Yahoo TW 頁或略過（由呼叫端合併）。"""
    return None  # chart 路徑由 ensure 後端合併；即時 cell 仍走 /txf


def ensure_txf(years: int = 5, force: bool = False) -> List[Tuple]:
    with _lock:
        now = time.time()
        cached = _mem.get('__TXF__')
        if cached and not force and (now - cached[0]) < _REFRESH_TTL and cached[1]:
            return cached[1]

        rows = _read_csv(TXF_CSV)
        today = date.today()
        if rows:
            try:
                last = datetime.strptime(rows[-1][0], '%Y-%m-%d').date()
                # 重抓最後 14 天（合約換月／修正）
                start = (last - timedelta(days=14)).isoformat()
            except Exception:
                start = (today - timedelta(days=365 * years)).isoformat()
        else:
            start = (today - timedelta(days=365 * years)).isoformat()
        end = today.isoformat()

        fresh = _fetch_txf_finmind(start, end)
        by_date: Dict[str, Tuple] = {r[0]: r for r in rows}
        for r in fresh:
            by_date[r[0]] = r
        out = [by_date[k] for k in sorted(by_date)]
        if out:
            _write_csv(TXF_CSV, out)
        _mem['__TXF__'] = (now, out)
        return out


def is_txf_intraday_request(range_key: Optional[str], interval: Optional[str]) -> bool:
    """僅「1天」視圖用分 K（Yahoo TW WTX& 當日／夜盤）；其餘週期仍走 FinMind 日線。"""
    rk = str(range_key or '').strip().lower()
    iv = str(interval or '').strip().lower()
    if rk != '1d':
        return False
    if iv in ('1d', '1wk', '1w', '1wkly'):
        return False
    return iv in _TXF_INTRADAY_INTERVALS or iv in ('', '1m')


def _js_json_array(blob: str, key: str) -> Optional[list]:
    token = '"' + key + '":['
    i = blob.find(token)
    if i < 0:
        token = '"' + key + '": ['
        i = blob.find(token)
    if i < 0:
        return None
    start = blob.find('[', i)
    if start < 0:
        return None
    depth = 0
    for j in range(start, len(blob)):
        ch = blob[j]
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(blob[start:j + 1])
                except Exception:
                    return None
    return None


def _js_num(blob: str, key: str) -> Optional[float]:
    m = re.search(r'"' + re.escape(key) + r'"\s*:\s*(-?[0-9]+(?:\.[0-9]+)?)', blob)
    if not m:
        return None
    try:
        return float(m.group(1))
    except Exception:
        return None


def parse_wtx_intraday_embed(html: str) -> Optional[Dict[str, Any]]:
    """從 Yahoo TW WTX& 頁 App.main 抽出當日 1 分 K（含夜盤 15:00–05:00）。"""
    if not html:
        return None
    m = re.search(r'root\.App\.main\s*=\s*(\{.*?\})\s*;\s*\n', html, re.S)
    blob = m.group(1) if m else html
    # 鎖定走勢圖區塊，避免頁面其它 timestamp 陣列
    mark = blob.find('"dataGranularity":"1m"')
    if mark < 0:
        mark = blob.find('"dataGranularity": "1m"')
    if mark < 0:
        blob = html
        mark = blob.find('"dataGranularity":"1m"')
        if mark < 0:
            mark = blob.find('"dataGranularity": "1m"')
    if mark >= 0:
        blob = blob[max(0, mark - 8000):]
    ts = _js_json_array(blob, 'timestamp')
    closes = _js_json_array(blob, 'close')
    if not ts or not closes:
        return None
    opens = _js_json_array(blob, 'open') or []
    highs = _js_json_array(blob, 'high') or []
    lows = _js_json_array(blob, 'low') or []
    vols = _js_json_array(blob, 'volume') or []
    n = min(len(ts), len(closes))
    out_ts, o, h, l, c, v = [], [], [], [], [], []
    for i in range(n):
        px = closes[i]
        if px is None:
            continue
        try:
            t = int(ts[i])
            close_px = float(px)
        except Exception:
            continue
        if t <= 0 or close_px <= 0:
            continue
        def _at(arr, default):
            try:
                val = arr[i]
                return float(val) if val is not None else default
            except Exception:
                return default
        out_ts.append(t)
        c.append(close_px)
        o.append(_at(opens, close_px))
        h.append(_at(highs, close_px))
        l.append(_at(lows, close_px))
        try:
            vv = vols[i]
            v.append(int(float(vv)) if vv is not None else 0)
        except Exception:
            v.append(0)
    if not out_ts:
        return None
    last_px = c[-1]
    prev = _js_num(blob, 'chartPreviousClose') or _js_num(blob, 'previousClose')
    rmp = _js_num(blob, 'regularMarketPrice') or last_px
    return {
        'timestamp': out_ts,
        'open': o, 'high': h, 'low': l, 'close': c, 'volume': v,
        'regularMarketPrice': rmp,
        'chartPreviousClose': prev,
        'previousClose': prev,
    }


def _resample_ohlc(parsed: Dict[str, Any], bucket_sec: int) -> Dict[str, Any]:
    if bucket_sec <= 60:
        return parsed
    ts, o, h, l, c, v = (parsed['timestamp'], parsed['open'], parsed['high'],
                         parsed['low'], parsed['close'], parsed['volume'])
    buckets: Dict[int, List[int]] = {}
    order: List[int] = []
    for i, t in enumerate(ts):
        b = t - (t % bucket_sec)
        if b not in buckets:
            buckets[b] = []
            order.append(b)
        buckets[b].append(i)
    nts, no, nh, nl, nc, nv = [], [], [], [], [], []
    for b in order:
        idx = buckets[b]
        nts.append(b)
        no.append(o[idx[0]])
        nh.append(max(h[i] for i in idx))
        nl.append(min(l[i] for i in idx))
        nc.append(c[idx[-1]])
        nv.append(sum(v[i] for i in idx))
    out = dict(parsed)
    out.update({'timestamp': nts, 'open': no, 'high': nh, 'low': nl, 'close': nc, 'volume': nv})
    return out


def _wtx_quote_html(force: bool = False) -> str:
    """與 /txf Yahoo TW 同源：WTX& 報價頁（含當日 1 分走勢）。"""
    global _wtx_html_cache
    now = time.time()
    cached_at, cached_html = _wtx_html_cache
    if not force and cached_html and (now - cached_at) < _WTX_HTML_TTL:
        return cached_html
    req = urllib.request.Request(_WTX_QUOTE_URL, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept-Language': 'zh-TW,zh;q=0.9',
        'Accept': 'text/html,application/xhtml+xml',
    })
    with urllib.request.urlopen(req, timeout=12) as resp:
        html = resp.read().decode('utf-8', 'replace')
    _wtx_html_cache = (now, html)
    return html


def chart_json_txf_intraday(interval: str = '1m') -> bytes:
    """台指期 1 天：Yahoo TW WTX& 當日 1 分 K（夜盤+日盤時段）。"""
    html = _wtx_quote_html()
    parsed = parse_wtx_intraday_embed(html)
    if not parsed:
        raise ValueError('WTX embed missing 1m bars')
    iv = str(interval or '1m').lower()
    bucket = {'1m': 60, '2m': 120, '5m': 300, '15m': 900, '30m': 1800, '60m': 3600, '1h': 3600}.get(iv, 60)
    parsed = _resample_ohlc(parsed, bucket)
    ts, opens, highs, lows, closes, vols = (
        parsed['timestamp'], parsed['open'], parsed['high'],
        parsed['low'], parsed['close'], parsed['volume'])
    last_px = parsed.get('regularMarketPrice') or closes[-1]
    prev = parsed.get('chartPreviousClose') or parsed.get('previousClose')
    if not (prev and prev > 0) and len(closes) >= 2:
        prev = closes[0]
    gran = '1m' if bucket <= 60 else ('5m' if bucket == 300 else iv)
    meta = {
        'currency': 'TWD',
        'symbol': '__TXF__',
        'exchangeName': 'TAI',
        'instrumentType': 'FUTURE',
        'shortName': '台指期近月',
        'longName': '台指期近月',
        'firstTradeDate': ts[0],
        'regularMarketTime': ts[-1],
        'gmtoffset': 28800,
        'timezone': 'TST',
        'exchangeTimezoneName': 'Asia/Taipei',
        'regularMarketPrice': last_px,
        'regularMarketPreviousClose': prev,
        'chartPreviousClose': prev,
        'previousClose': prev,
        'dataGranularity': gran,
        'range': '1d',
        'validRanges': ['1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max'],
        '_source': 'yahoo-tw-WTX 1m',
    }
    body = {
        'chart': {
            'result': [{
                'meta': meta,
                'timestamp': ts,
                'indicators': {
                    'quote': [{
                        'open': opens, 'high': highs, 'low': lows,
                        'close': closes, 'volume': vols,
                    }],
                },
            }],
            'error': None,
        }
    }
    return json.dumps(body, ensure_ascii=False).encode()


def _yf_payload(symbol: str, name: str, rows: List[Tuple], range_key: Optional[str]) -> bytes:
    rows = _filter_rows(rows, range_key)
    if not rows:
        return json.dumps({
            'chart': {'result': None, 'error': f'no data for {symbol}'},
        }, ensure_ascii=False).encode()

    ts, opens, highs, lows, closes, vols = [], [], [], [], [], []
    for iso, o, h, l, c, v in rows:
        ts.append(_iso_to_ts(iso))
        opens.append(o); highs.append(h); lows.append(l); closes.append(c)
        vols.append(int(v or 0))
    last_px = closes[-1]
    prev = closes[-2] if len(closes) >= 2 else last_px
    meta = {
        'currency': 'TWD',
        'symbol': symbol,
        'exchangeName': 'TAI',
        'instrumentType': 'FUTURE' if symbol == '__TXF__' else 'INDEX',
        'shortName': name,
        'longName': name,
        'firstTradeDate': ts[0],
        'regularMarketTime': ts[-1],
        'gmtoffset': 28800,
        'timezone': 'TST',
        'exchangeTimezoneName': 'Asia/Taipei',
        'regularMarketPrice': last_px,
        'regularMarketPreviousClose': prev,
        'chartPreviousClose': prev,
        'previousClose': prev,
        'dataGranularity': '1d',
        'range': range_key or 'max',
        'validRanges': ['1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max'],
        '_source': 'TPEx st41' if 'TWOII' in symbol else 'FinMind TaiwanFuturesDaily TX',
    }
    body = {
        'chart': {
            'result': [{
                'meta': meta,
                'timestamp': ts,
                'indicators': {
                    'quote': [{
                        'open': opens, 'high': highs, 'low': lows,
                        'close': closes, 'volume': vols,
                    }],
                },
            }],
            'error': None,
        }
    }
    return json.dumps(body, ensure_ascii=False).encode()


def chart_json(symbol: str, range_key: Optional[str] = 'max') -> bytes:
    """回傳 Yahoo-compatible chart JSON bytes。"""
    sym = (symbol or '').strip().upper()
    if sym in ('^TWOII', 'TWOII', '%5ETWOII'):
        rows = ensure_twoii()
        return _yf_payload('^TWOII', '櫃買指數', rows, range_key)
    if sym in ('__TXF__', 'TXF', '__TXF'):
        rows = ensure_txf()
        return _yf_payload('__TXF__', '台指期近月', rows, range_key)
    raise ValueError(f'unsupported symbol {symbol}')


def is_tw_index_chart_sym(sym: str) -> bool:
    s = (sym or '').strip().upper()
    return s in ('^TWOII', 'TWOII', '%5ETWOII', '__TXF__', 'TXF', '__TXF')


def recent_closes(symbol: str, n: int = 30, allow_network: bool = False) -> List[float]:
    """近 n 日收盤價（舊→新）。預設只讀記憶體／CSV，不觸發網路。

    allow_network=True 時走 ensure_*（可能補齊過期 CSV）。
    """
    sym = (symbol or '').strip().upper()
    rows: List[Tuple] = []
    if sym in ('^TWOII', 'TWOII', '%5ETWOII'):
        if allow_network:
            try:
                rows = ensure_twoii()
            except Exception as e:
                print('[tw-index] recent_closes TWOII net', e)
                rows = []
        if not rows:
            cached = _mem.get('^TWOII')
            rows = (cached[1] if cached else None) or _read_csv(TWOII_CSV)
    elif sym in ('__TXF__', 'TXF', '__TXF'):
        if allow_network:
            try:
                rows = ensure_txf()
            except Exception as e:
                print('[tw-index] recent_closes TXF net', e)
                rows = []
        if not rows:
            cached = _mem.get('__TXF__')
            rows = (cached[1] if cached else None) or _read_csv(TXF_CSV)
    else:
        return []
    out: List[float] = []
    for r in rows[-max(1, int(n)):]:
        try:
            c = float(r[4])
            if c > 0:
                out.append(c)
        except Exception:
            continue
    return out


def recent_rows(symbol: str, n: int = 80, allow_network: bool = False) -> List[dict]:
    """Recent official/local-cache OHLC rows (oldest -> newest) with session dates."""
    sym = (symbol or '').strip().upper()
    rows: List[Tuple] = []
    if sym in ('^TWOII', 'TWOII', '%5ETWOII'):
        if allow_network:
            try:
                rows = ensure_twoii()
            except Exception as exc:
                print('[tw-index] recent_rows TWOII net', exc)
        if not rows:
            cached = _mem.get('^TWOII')
            rows = (cached[1] if cached else None) or _read_csv(TWOII_CSV)
    elif sym in ('__TXF__', 'TXF', '__TXF'):
        if allow_network:
            try:
                rows = ensure_txf()
            except Exception as exc:
                print('[tw-index] recent_rows TXF net', exc)
        if not rows:
            cached = _mem.get('__TXF__')
            rows = (cached[1] if cached else None) or _read_csv(TXF_CSV)
    return [
        {'date': row[0], 'open': row[1], 'high': row[2], 'low': row[3],
         'close': row[4], 'volume': row[5], 'session': 'day'}
        for row in rows[-max(1, int(n or 80)):]
    ]
