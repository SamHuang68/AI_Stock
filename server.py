#!/usr/bin/env python3
"""Stock Terminal local server — ThreadingHTTPServer + ThreadPoolExecutor + LRU cache + ETF Delta
   Tuned for GMKtec EVO-T1 (Core Ultra 9 285H / 96GB DDR5 / RTX 5080).
"""
import os, json, urllib.request, urllib.error, socketserver, glob, time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import OrderedDict
from urllib.parse import urlparse, parse_qs
import threading

PORT = 18432
# Core Ultra 9 285H = 6P + 8E + 2LP = 16 threads; oversubscribe for I/O-bound YF
MAX_WORKERS = max(32, (os.cpu_count() or 16) * 2)
LRU_MAX = 20000  # 96GB RAM → very generous cache

# ── ETF Delta path ──────────────────────────────────────────────
ETF_DELTA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'etf_history')
_ETF_FALLBACKS = [
    ETF_DELTA_PATH,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'etf_history'),
]

ETF_NAME_MAP = {
    '00992A':'主動群益科技創新','00981A':'主動統一台股增長',
    '00987A':'主動台新優勢成長','00994A':'主動第一金台股優',
    '00982A':'主動群益台灣強棒','00995A':'主動中信台灣卓越',
    '00980A':'主動野村臺灣優選','00991A':'主動復華未來50',
    '00996A':'主動兆豐台灣豐收','00984A':'主動安聯台灣高息',
}

# ── LRU cache ───────────────────────────────────────────────────
class LRUCache:
    def __init__(self, maxsize):
        self._d = OrderedDict()
        self._max = maxsize
        self._lock = threading.Lock()
    def get(self, k):
        with self._lock:
            if k not in self._d: return None
            self._d.move_to_end(k)
            return self._d[k]
    def set(self, k, v):
        with self._lock:
            if k in self._d: self._d.move_to_end(k)
            self._d[k] = v
            if len(self._d) > self._max:
                self._d.popitem(last=False)
    def __len__(self):
        return len(self._d)

_cache = LRUCache(LRU_MAX)
_pool  = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='yf')

YF_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json,*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://finance.yahoo.com/',
}

YF_RANGE = os.environ.get('YF_RANGE', '5y')   # 5y 約 1250 K 線；可設 max / 10y / 2y
YF_INTERVAL = os.environ.get('YF_INTERVAL', '1d')

def fetch_one(sym, rng=None, interval=None):
    rng = rng or YF_RANGE
    interval = interval or YF_INTERVAL
    cache_key = f'{sym}|{interval}|{rng}'
    cached = _cache.get(cache_key)
    if cached is not None:
        return sym, cached, True
    if sym.endswith('.TW') and not sym.endswith('.TWO'):
        candidates = [sym, sym[:-3]+'.TWO']
    elif sym.endswith('.TWO'):
        candidates = [sym, sym[:-4]+'.TW']
    else:
        candidates = [sym]
    for candidate in candidates:
        for base in ('query1', 'query2'):
            url = f'https://{base}.finance.yahoo.com/v8/finance/chart/{candidate}?interval={interval}&range={rng}'
            try:
                req = urllib.request.Request(url, headers=YF_HEADERS)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                parsed = json.loads(data)
                if parsed.get('chart', {}).get('result'):
                    _cache.set(cache_key, data)
                    return sym, data, False
            except urllib.error.HTTPError as e:
                if e.code == 404: break
                continue
            except Exception:
                continue
    return sym, None, False

# ── ETF Delta helpers ──────────────────────────────────────────
def find_etf_dir():
    for p in _ETF_FALLBACKS:
        if p and os.path.isdir(p):
            return p
    return None

def list_etf_files():
    d = find_etf_dir()
    if not d: return []
    return sorted(glob.glob(os.path.join(d, 'top10_active_etf_holdings_*.json')))

def parse_holdings_json(data):
    """Flexible parser — handles multiple JSON schema variants."""
    result = {}
    if isinstance(data, dict):
        for k, v in data.items():
            if k in ('date','updated','meta','summary'): continue
            if isinstance(v, list):
                result[k] = v
            elif isinstance(v, dict):
                if 'holdings' in v:
                    result[k] = v['holdings']
                elif 'data' in v:
                    result[k] = v['data']
        if 'etfs' in data:
            etfs = data['etfs']
            if isinstance(etfs, dict):
                for code, etf in etfs.items():
                    result[code] = etf.get('holdings', etf) if isinstance(etf, dict) else etf
            elif isinstance(etfs, list):
                for etf in etfs:
                    code = etf.get('code') or etf.get('etf_code', '')
                    result[code] = etf.get('holdings', [])
    elif isinstance(data, list):
        for etf in data:
            code = etf.get('code') or etf.get('etf_code', '')
            if code:
                result[code] = etf.get('holdings', [])
    return result

def get_field(h, *keys):
    for k in keys:
        if k in h: return h[k]
    return None

def compute_etf_delta(files, date=None):
    if len(files) < 2: return None
    if date:
        target = [f for f in files if date in os.path.basename(f)]
        if not target: return None
        curr_file = target[-1]
        idx = files.index(curr_file)
        if idx == 0: return None
        prev_file = files[idx - 1]
    else:
        curr_file = files[-1]
        prev_file = files[-2]

    def extract_date(f):
        return os.path.basename(f).replace('top10_active_etf_holdings_','').replace('.json','')

    curr_date = extract_date(curr_file)
    prev_date = extract_date(prev_file)

    with open(curr_file, encoding='utf-8') as f:
        curr_raw = json.load(f)
    with open(prev_file, encoding='utf-8') as f:
        prev_raw = json.load(f)

    curr_all = parse_holdings_json(curr_raw)
    prev_all = parse_holdings_json(prev_raw)

    THRESHOLD = 0.5
    all_codes = sorted(set(curr_all) | set(prev_all))

    etfs_out = []
    total_new = total_rm = total_chg = 0

    for code in all_codes:
        curr_list = curr_all.get(code, [])
        prev_list = prev_all.get(code, [])

        def to_map(lst):
            m = {}
            for h in lst:
                sym = get_field(h, 'code','symbol','stock_code','ticker')
                if sym: m[sym] = h
            return m

        curr_map = to_map(curr_list)
        prev_map = to_map(prev_list)

        new_stocks, removed, changed = [], [], []

        for sym, h in curr_map.items():
            w = float(get_field(h,'weight','pct','weight_pct') or 0)
            if sym not in prev_map:
                new_stocks.append({
                    'rank':   get_field(h,'rank','holding_rank') or '-',
                    'code':   sym,
                    'name':   get_field(h,'name','stock_name','company_name') or '',
                    'weight': w,
                    'shares': int(get_field(h,'shares','quantity','volume') or 0),
                })
            else:
                pw = float(get_field(prev_map[sym],'weight','pct','weight_pct') or 0)
                delta = round(w - pw, 4)
                if abs(delta) >= THRESHOLD:
                    changed.append({
                        'rank':        get_field(h,'rank','holding_rank') or '-',
                        'code':        sym,
                        'name':        get_field(h,'name','stock_name','company_name') or '',
                        'prev_weight': pw,
                        'curr_weight': w,
                        'delta':       delta,
                    })

        for sym, h in prev_map.items():
            if sym not in curr_map:
                removed.append({
                    'rank':        get_field(h,'rank','holding_rank') or '-',
                    'code':        sym,
                    'name':        get_field(h,'name','stock_name','company_name') or '',
                    'prev_weight': float(get_field(h,'weight','pct','weight_pct') or 0),
                })

        changed.sort(key=lambda x: abs(x['delta']), reverse=True)
        total_new += len(new_stocks)
        total_rm  += len(removed)
        total_chg += len(changed)

        if new_stocks or removed or changed:
            etfs_out.append({
                'code':    code,
                'name':    ETF_NAME_MAP.get(code, code),
                'total':   len(curr_list),
                'new':     new_stocks,
                'removed': removed,
                'changed': changed,
            })

    return {
        'date':      curr_date,
        'prev_date': prev_date,
        'summary':   {'new': total_new, 'removed': total_rm, 'changed': total_chg},
        'etfs':      etfs_out,
    }

# ── Threading HTTP server ──────────────────────────────────────
class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

class Handler(SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'   # enables keep-alive

    def do_GET(self):
        p = self.path
        if p.startswith('/yf/batch'):
            self._handle_batch()
        elif p.startswith('/yf/'):
            sym = p[4:].split('?')[0]
            self._handle_single(sym)
        elif p.startswith('/etf-delta'):
            self._handle_etf_delta()
        elif p.startswith('/quote/'):
            sym = p[7:].split('?')[0]
            self._handle_quote(sym)
        elif p == '/health':
            d = find_etf_dir()
            files = list_etf_files()
            self._ok(json.dumps({
                'status': 'ok',
                'workers': MAX_WORKERS,
                'cpu_count': os.cpu_count(),
                'cache_used': len(_cache),
                'cache_max': LRU_MAX,
                'etf_delta_path': d or 'not found',
                'etf_history_files': len(files),
            }).encode())
        else:
            super().do_GET()

    def end_headers(self):
        if hasattr(self, 'path') and self.path.endswith('.html'):
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
            self.send_header('Pragma', 'no-cache')
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def _ok(self, body, ct='application/json'):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(200)
        if ct.startswith('application/json'):
            ct = ct + '; charset=utf-8'
        self.send_header('Content-Type', ct)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _err(self, msg, code=404):
        body = json.dumps({'error': msg}, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_single(self, sym):
        qs = parse_qs(urlparse(self.path).query)
        rng      = qs.get('range',    [None])[0]
        interval = qs.get('interval', [None])[0]
        _, data, _ = fetch_one(sym, rng, interval)
        if data:
            self._ok(data)
        else:
            self._err('fetch failed', 502)

    def _handle_batch(self):
        qs = parse_qs(urlparse(self.path).query)
        syms = [s.strip() for s in qs.get('syms', [''])[0].split(',') if s.strip()]
        rng      = qs.get('range',    [None])[0]
        interval = qs.get('interval', [None])[0]
        if not syms:
            self._ok(b'{}'); return
        results = {}
        futures = {_pool.submit(fetch_one, s, rng, interval): s for s in syms}
        for fut in as_completed(futures):
            sym, data, _ = fut.result()
            if data:
                try: results[sym] = json.loads(data)
                except Exception: pass
        self._ok(json.dumps(results).encode())

    def _handle_quote(self, sym):
        """Lightweight near-real-time quote.
        Yahoo's v7 /finance/quote (which had bid/ask) is gated behind crumb cookie auth
        since 2024 — unauthenticated requests get 401. We use v8 /finance/chart with
        range=1d&interval=1m and extract price/high/low/vol from meta + last bar.
        bid/ask are not available free; would need broker API.
        """
        candidates = []
        if sym.endswith('.TW') and not sym.endswith('.TWO'):
            candidates = [sym, sym[:-3]+'.TWO']
        elif sym.endswith('.TWO'):
            candidates = [sym, sym[:-4]+'.TW']
        else:
            candidates = [sym]
        for candidate in candidates:
            for base in ('query1', 'query2'):
                url = f'https://{base}.finance.yahoo.com/v8/finance/chart/{candidate}?interval=1m&range=1d'
                try:
                    req = urllib.request.Request(url, headers=YF_HEADERS)
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        raw = resp.read()
                    parsed = json.loads(raw)
                    res = parsed.get('chart', {}).get('result')
                    if not res: continue
                    r0 = res[0]
                    meta = r0.get('meta', {})
                    # Extract last available 1m bar values
                    quotes = (r0.get('indicators', {}).get('quote') or [{}])[0]
                    ts = r0.get('timestamp') or []
                    # find last non-null close
                    closes = quotes.get('close') or []
                    highs  = quotes.get('high')  or []
                    lows   = quotes.get('low')   or []
                    vols   = quotes.get('volume') or []
                    last_idx = None
                    for i in range(len(closes) - 1, -1, -1):
                        if closes[i] is not None:
                            last_idx = i
                            break
                    last_close = closes[last_idx] if last_idx is not None else meta.get('regularMarketPrice')
                    # day high/low from meta (more reliable) or compute from intraday
                    day_high = meta.get('regularMarketDayHigh')
                    day_low  = meta.get('regularMarketDayLow')
                    if day_high is None and highs:
                        day_high = max([h for h in highs if h is not None] or [None])
                    if day_low is None and lows:
                        day_low = min([l for l in lows if l is not None] or [None])
                    prev_close = meta.get('chartPreviousClose') or meta.get('previousClose')
                    change = (last_close - prev_close) if (last_close is not None and prev_close) else None
                    change_pct = (change / prev_close * 100) if (change is not None and prev_close) else None
                    # cumulative volume from meta or sum of intraday
                    day_vol = meta.get('regularMarketVolume')
                    if day_vol is None and vols:
                        day_vol = sum(v for v in vols if v is not None)
                    out = {
                        'symbol':       meta.get('symbol', sym),
                        'price':        last_close,
                        'change':       change,
                        'changePct':    change_pct,
                        'open':         meta.get('regularMarketOpen'),
                        'high':         day_high,
                        'low':          day_low,
                        'prevClose':    prev_close,
                        'volume':       day_vol,
                        'bid':          None,                 # Yahoo v7 closed; needs broker API
                        'ask':          None,
                        'bidSize':      None,
                        'askSize':      None,
                        'marketState':  meta.get('marketState'),  # PRE/REGULAR/POST/CLOSED
                        'currency':     meta.get('currency'),
                        'serverTime':   int(time.time()),
                        'lastBarTime':  ts[last_idx] if last_idx is not None else None,
                        'source':       'yahoo-v8-chart',
                    }
                    self._ok(json.dumps(out, ensure_ascii=False).encode('utf-8'))
                    return
                except urllib.error.HTTPError as e:
                    if e.code == 404: break
                    continue
                except Exception as e:
                    print(f'[quote] {candidate} via {base} error: {e}')
                    continue
        self._err('quote fetch failed for ' + sym, 502)

    def _handle_etf_delta(self):
        files = list_etf_files()
        d = find_etf_dir() or 'not found'
        if self.path.startswith('/etf-delta/list'):
            dates = [os.path.basename(f).replace('top10_active_etf_holdings_','').replace('.json','') for f in files]
            self._ok(json.dumps({'dates': dates, 'dir': d}).encode())
            return
        if len(files) < 2:
            msg = (f'need ≥2 history files; found {len(files)} in dir={d}. '
                   f'執行 etf_delta_tracker.py 累積每日快照')
            self._err(msg)
            return
        qs = parse_qs(urlparse(self.path).query)
        date = qs.get('date', [None])[0]
        try:
            result = compute_etf_delta(files, date)
        except Exception as e:
            self._err(str(e), 500); return
        if result is None:
            self._err('delta compute failed'); return
        self._ok(json.dumps(result, ensure_ascii=False).encode())

    def log_message(self, fmt, *args):
        pass  # silent

if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    d = find_etf_dir()
    files = list_etf_files()
    print(f'Stock Terminal: http://localhost:{PORT}/stock_terminal.html')
    print(f'Workers: {MAX_WORKERS}  |  LRU cache: {LRU_MAX} symbols  |  CPU: {os.cpu_count()}')
    print(f'ETF delta path: {d or "NOT FOUND — set ETF_DELTA_PATH in server.py"}')
    print(f'ETF history files: {len(files)}')
    ThreadingHTTPServer(('localhost', PORT), Handler).serve_forever()
