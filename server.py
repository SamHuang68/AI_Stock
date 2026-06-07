#!/usr/bin/env python3
"""Stock Terminal local server — ThreadingHTTPServer + ThreadPoolExecutor + LRU cache + ETF Delta
   Tuned for GMKtec EVO-T1 (Core Ultra 9 285H / 96GB DDR5 / RTX 5080).
"""
import os, json, urllib.request, urllib.error, socketserver, glob, time, subprocess, sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import OrderedDict
from urllib.parse import urlparse, parse_qs
import threading
try:
    import alert_daemon
except Exception as _e:
    alert_daemon = None
    print('[alert] daemon import failed:', _e)
try:
    import etf_report
except Exception as _e:
    etf_report = None
    print('[etf-report] module import failed:', _e)
try:
    import watch_daemon
except Exception as _e:
    watch_daemon = None
    print('[watch] daemon import failed:', _e)

PORT = 18432
# Core Ultra 9 285H = 6P + 8E + 2LP = 16 threads; oversubscribe for I/O-bound YF
MAX_WORKERS = max(32, (os.cpu_count() or 16) * 2)
LRU_MAX = 20000  # 96GB RAM → very generous cache

# ── ETF Delta path ──────────────────────────────────────────────
ETF_DELTA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'etf_history')
ETF_CATALOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'etf_catalog.json')
_ETF_FALLBACKS = [
    ETF_DELTA_PATH,
    os.path.join(os.path.dirname(os.path.abspath(__file__)), 'etf_history'),
]

# ── Chip history (v3.8): 每日法人籌碼快照，用於連續買賣超天數 ──
CHIP_HISTORY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chip_history')

def _chip_history_record(clean_code, chip_out):
    """把今日某股的 inst.total 記到 chip_history/<date>.json (彙總多股)"""
    from datetime import date as _date
    inst = (chip_out or {}).get('inst') or {}
    if inst.get('total') is None:
        return
    os.makedirs(CHIP_HISTORY_PATH, exist_ok=True)
    fn = os.path.join(CHIP_HISTORY_PATH, _date.today().strftime('%Y%m%d') + '.json')
    day = {}
    if os.path.isfile(fn):
        try:
            with open(fn, encoding='utf-8') as f: day = json.load(f)
        except Exception: day = {}
    day[clean_code] = {
        'foreign': inst.get('foreign'), 'trust': inst.get('trust'),
        'dealer': inst.get('dealer'), 'total': inst.get('total'),
    }
    with open(fn, 'w', encoding='utf-8') as f:
        json.dump(day, f, ensure_ascii=False)

_openapi_ds = {}   # dataset name → (date, {code: row})

# ── 全台股普通股代號宇集（上市 TWSE + 上櫃 TPEx），當日快取 ──
import re as _re
_TW_UNIVERSE = {'date': None, 'codes': []}
_CODE4 = _re.compile(r'^[1-9]\d{3}$')   # 4 位數普通股；排除 ETF(00xxx)/權證(6 位)

def _get_tw_universe():
    from datetime import date as _date
    today = _date.today().strftime('%Y%m%d')
    if _TW_UNIVERSE['date'] == today and _TW_UNIVERSE['codes']:
        return _TW_UNIVERSE['codes']
    codes = set()

    def _scan(url):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=20) as r:
                arr = json.loads(r.read())
            for row in arr:
                if not isinstance(row, dict):
                    continue
                # 優先抓常見欄位，否則掃所有值找 4 位數代號
                cand = (row.get('Code') or row.get('SecuritiesCompanyCode')
                        or row.get('證券代號') or row.get('股票代號') or '')
                cand = str(cand).strip()
                if _CODE4.match(cand):
                    codes.add(cand); continue
                for v in row.values():
                    s = str(v).strip()
                    if _CODE4.match(s):
                        codes.add(s); break
        except Exception as e:
            print(f'[universe] scan failed {url}: {e}')

    # 上市（TWSE）所有個股當日行情 → 取代號
    _scan('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL')
    # 上櫃（TPEx）主板當日收盤
    _scan('https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes')

    out = sorted(codes)
    if out:
        _TW_UNIVERSE['date'] = today
        _TW_UNIVERSE['codes'] = out
    return out

# ── 產業別對照（code → 產業別），用月營收資料集(含上市櫃)的「產業別」欄 ──
_TW_SECTORS = {'date': None, 'map': {}}
# 科技電子整合群（macro）：涵蓋常見電子相關產業別
_TECH_SECTORS = {'半導體業', '電腦及週邊設備業', '光電業', '通信網路業',
                 '電子零組件業', '電子通路業', '其他電子業', '資訊服務業'}

def _get_tw_sectors():
    from datetime import date as _date
    today = _date.today().strftime('%Y%m%d')
    if _TW_SECTORS['date'] == today and _TW_SECTORS['map']:
        return _TW_SECTORS['map']
    m = {}
    for ds in ('t187ap05_L', 't187ap05_O'):
        try:
            url = f'https://openapi.twse.com.tw/v1/opendata/{ds}'
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=15) as r:
                arr = json.loads(r.read())
            for row in arr:
                code = (row.get('公司代號') or '').strip()
                ind = (row.get('產業別') or '').strip()
                if code and ind:
                    m[code] = ind
        except Exception as e:
            print(f'[sectors] {ds} failed: {e}')
    if m:
        _TW_SECTORS['date'] = today
        _TW_SECTORS['map'] = m
    return m

def _pick_num(row, includes, excludes=()):
    """從 row 找第一個 key 同時包含 includes 全部子字串、且不含任何 excludes 的值 → float。
       用來吸收 TWSE OpenAPI 欄位的前綴(營業收入-)與全形/半形括號差異。"""
    for k, v in row.items():
        if all(s in k for s in includes) and not any(e in k for e in excludes):
            try:
                return float(str(v).replace(',', '').strip())
            except Exception:
                return None
    return None

def _openapi_lookup(dataset_names, clean_code):
    """從 TWSE OpenAPI 全市場資料集找某股。資料集整批快取一天。"""
    from datetime import date as _date
    today = _date.today().strftime('%Y%m%d')
    for ds in dataset_names:
        cached = _openapi_ds.get(ds)
        if not cached or cached[0] != today:
            try:
                url = f'https://openapi.twse.com.tw/v1/opendata/{ds}'
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    arr = json.loads(resp.read())
                idx = {}
                for row in arr:
                    code = (row.get('公司代號') or row.get('證券代號') or '').strip()
                    if code:
                        idx[code] = row
                _openapi_ds[ds] = (today, idx)
                cached = _openapi_ds[ds]
            except Exception as e:
                print(f'[fundamental] openapi {ds} failed: {e}')
                _openapi_ds[ds] = (today, {})
                cached = _openapi_ds[ds]
        row = cached[1].get(clean_code)
        if row:
            return row
    return None

def _fundamental_score(out):
    """0~100 基本面分數：成長性(營收YoY+累計YoY) + 獲利性(三率)"""
    score, parts = 0, 0
    rev = out.get('revenue') or {}
    inc = out.get('income') or {}
    if rev.get('yoyPct') is not None:
        y = rev['yoyPct']
        score += max(0, min(100, 50 + y)); parts += 1   # YoY 0% → 50 分
    if rev.get('cumYoyPct') is not None:
        score += max(0, min(100, 50 + rev['cumYoyPct'])); parts += 1
    if inc.get('netMargin') is not None:
        score += max(0, min(100, inc['netMargin'] * 3)); parts += 1   # 淨利率 33%→100
    if inc.get('opMargin') is not None:
        score += max(0, min(100, inc['opMargin'] * 3)); parts += 1
    if not parts:
        return None
    return round(score / parts)

def _chip_streak(clean_code):
    """從 chip_history 反向算外資/投信連續買(>0)賣(<0)超天數"""
    if not os.path.isdir(CHIP_HISTORY_PATH):
        return None
    files = sorted(glob.glob(os.path.join(CHIP_HISTORY_PATH, '*.json')), reverse=True)
    series = {'foreign': [], 'trust': []}
    for fn in files[:60]:
        try:
            with open(fn, encoding='utf-8') as f: day = json.load(f)
        except Exception:
            continue
        rec = day.get(clean_code)
        if not rec:
            continue
        for k in series:
            if rec.get(k) is not None:
                series[k].append(rec[k])
    def streak(vals):
        if not vals:
            return 0
        sign = 1 if vals[0] > 0 else (-1 if vals[0] < 0 else 0)
        if sign == 0:
            return 0
        n = 0
        for v in vals:
            if (v > 0 and sign > 0) or (v < 0 and sign < 0):
                n += 1
            else:
                break
        return n * sign  # 正=連買天數, 負=連賣天數
    return {'foreign': streak(series['foreign']), 'trust': streak(series['trust'])}

# ── Tracker run state (for /etf-tracker/run + /etf-tracker/status) ──
_tracker_state = {
    'running':       False,
    'startedAt':     None,
    'finishedAt':    None,
    'lastDuration':  None,   # seconds
    'lastReturnCode': None,
    'lastOutput':    '',
}
_tracker_lock = threading.Lock()

def _run_tracker_async():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    tracker = os.path.join(script_dir, 'etf_delta_tracker.py')
    if not os.path.isfile(tracker):
        with _tracker_lock:
            _tracker_state.update({
                'running': False, 'finishedAt': time.time(),
                'lastReturnCode': -1, 'lastOutput': 'etf_delta_tracker.py not found',
            })
        return
    start = time.time()
    try:
        # Use sys.executable so we hit the same Python that's running server.py
        proc = subprocess.run(
            [sys.executable, tracker],
            cwd=script_dir,
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=300,
        )
        out = (proc.stdout or '') + ('\n' + proc.stderr if proc.stderr else '')
        with _tracker_lock:
            _tracker_state.update({
                'running': False,
                'finishedAt': time.time(),
                'lastDuration': round(time.time() - start, 1),
                'lastReturnCode': proc.returncode,
                'lastOutput': out[-4000:],   # keep last 4KB
            })
    except subprocess.TimeoutExpired:
        with _tracker_lock:
            _tracker_state.update({
                'running': False,
                'finishedAt': time.time(),
                'lastDuration': round(time.time() - start, 1),
                'lastReturnCode': -2,
                'lastOutput': 'tracker timed out (5 minutes)',
            })
    except Exception as e:
        with _tracker_lock:
            _tracker_state.update({
                'running': False,
                'finishedAt': time.time(),
                'lastDuration': round(time.time() - start, 1),
                'lastReturnCode': -3,
                'lastOutput': f'exception: {e}',
            })

ETF_NAME_MAP = {
    '00992A':'主動群益科技創新','00981A':'主動統一台股增長',
    '00987A':'主動台新優勢成長','00994A':'主動第一金台股優',
    '00982A':'主動群益台灣強棒','00995A':'主動中信台灣卓越',
    '00980A':'主動野村臺灣優選','00991A':'主動復華未來50',
    '00996A':'主動兆豐台灣豐收','00984A':'主動安聯台灣高息',
}

# ── LRU cache with TTL ──────────────────────────────────────────
# v3.6 加 TTL（預設 60 秒）：原本沒 TTL 造成的「stale price 隨機重現」根因 ——
# 若 server 啟動後第一次 Yahoo 查到時資料正在 query1/query2 同步落差期間，
# 整份回應（含 regularMarketPrice、整個 K 線陣列）會被永久 cache，後續任何
# loadSym / heatmap / sectors 全都吃這份過時快照。TTL 後最久 60 秒過期，
# 下一次抓會重新打 Yahoo，自然吃到最新狀態。
# 短 TTL（60s）對效能影響可忽略：同一張線型 60s 內被反覆點仍走 cache；
# 而每分鐘整批數十 symbol 的 Screener 也只多抓一次。
class LRUCache:
    def __init__(self, maxsize, ttl_seconds=60):
        self._d = OrderedDict()        # key → (value, expire_ts)
        self._max = maxsize
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
    def get(self, k):
        with self._lock:
            ent = self._d.get(k)
            if ent is None: return None
            val, exp = ent
            if exp <= time.time():
                # expired — drop from cache so next set() doesn't trip max
                self._d.pop(k, None)
                return None
            self._d.move_to_end(k)
            return val
    def set(self, k, v, ttl=None):
        with self._lock:
            exp = time.time() + (ttl if ttl is not None else self._ttl)
            if k in self._d: self._d.move_to_end(k)
            self._d[k] = (v, exp)
            if len(self._d) > self._max:
                self._d.popitem(last=False)
    def __len__(self):
        return len(self._d)

_cache = LRUCache(LRU_MAX, ttl_seconds=60)
_pool  = ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix='yf')

YF_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'application/json,*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://finance.yahoo.com/',
}

YF_RANGE = os.environ.get('YF_RANGE', '5y')   # 5y 約 1250 K 線；可設 max / 10y / 2y
YF_INTERVAL = os.environ.get('YF_INTERVAL', '1d')

def fetch_one(sym, rng=None, interval=None, nocache=False):
    """Fetch Yahoo chart JSON for sym. nocache=True bypasses _cache entirely
    (used by wl_live_v3.js so each watchlist poll always gets fresh data —
    the LRUCache has no TTL so cached entries would otherwise serve forever)."""
    rng = rng or YF_RANGE
    interval = interval or YF_INTERVAL
    cache_key = f'{sym}|{interval}|{rng}'
    if not nocache:
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
                    if not nocache:
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

def _load_enabled_etf_codes():
    """讀 etf_catalog.json，回傳目前 enabled=true 的 ETF 代號集合（uppercase）"""
    if not os.path.isfile(ETF_CATALOG_FILE):
        return None   # None = 不做 server 端過濾（fallback 給全部）
    try:
        with open(ETF_CATALOG_FILE, encoding='utf-8') as f:
            cat = json.load(f)
        enabled = set()
        for c in cat.get('categories', []):
            for e in c.get('etfs', []):
                if e.get('enabled'):
                    code = (e.get('code') or '').strip().upper()
                    if code: enabled.add(code)
        return enabled if enabled else None
    except Exception as e:
        print(f'[catalog filter] load failed: {e}')
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

    # ── 過濾：只保留 catalog 內 enabled=true 的 ETF（隱藏舊 009 殘留）──
    enabled_codes = _load_enabled_etf_codes()
    if enabled_codes is not None:
        all_codes = [c for c in all_codes if c.upper() in enabled_codes]

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
                ph = prev_map[sym]
                pw = float(get_field(ph,'weight','pct','weight_pct') or 0)
                delta = round(w - pw, 4)
                cs = int(get_field(h,'shares','quantity','volume') or 0)
                ps = int(get_field(ph,'shares','quantity','volume') or 0)
                sdelta = cs - ps
                # v3.8: 以張數變化為主、權重變化為輔（對齊朋友報表）
                if sdelta != 0 or abs(delta) >= THRESHOLD:
                    changed.append({
                        'rank':         get_field(h,'rank','holding_rank') or '-',
                        'prev_rank':    get_field(ph,'rank','holding_rank') or '-',
                        'code':         sym,
                        'name':         get_field(h,'name','stock_name','company_name') or '',
                        'prev_weight':  pw,
                        'curr_weight':  w,
                        'delta':        delta,
                        'prev_shares':  ps,
                        'curr_shares':  cs,
                        'shares_delta': sdelta,
                    })

        for sym, h in prev_map.items():
            if sym not in curr_map:
                removed.append({
                    'rank':        get_field(h,'rank','holding_rank') or '-',
                    'code':        sym,
                    'name':        get_field(h,'name','stock_name','company_name') or '',
                    'prev_weight': float(get_field(h,'weight','pct','weight_pct') or 0),
                    'prev_shares': int(get_field(h,'shares','quantity','volume') or 0),
                })

        changed.sort(key=lambda x: abs(x.get('shares_delta') or 0), reverse=True)
        total_new += len(new_stocks)
        total_rm  += len(removed)
        total_chg += len(changed)

        # ── Top 10 當前持股（按 weight 降冪）— 給前端顯示「投資標的一覽」 ──
        top10 = []
        try:
            sorted_curr = sorted(
                curr_list,
                key=lambda h: float(get_field(h, 'weight', 'pct', 'weight_pct') or 0),
                reverse=True,
            )[:10]
            for h in sorted_curr:
                top10.append({
                    'rank':   get_field(h, 'rank', 'holding_rank') or '-',
                    'code':   get_field(h, 'code', 'symbol', 'stock_code', 'ticker') or '',
                    'name':   get_field(h, 'name', 'stock_name', 'company_name') or '',
                    'weight': float(get_field(h, 'weight', 'pct', 'weight_pct') or 0),
                    'shares': int(get_field(h, 'shares', 'quantity', 'volume') or 0),
                })
        except Exception:
            pass

        # 即使「無變動」也輸出，讓 Top 10 看得到（v3.1 改：原本要 new/rm/chg 至少一個非空）
        if new_stocks or removed or changed or top10:
            etfs_out.append({
                'code':    code,
                'name':    ETF_NAME_MAP.get(code, code),
                'total':   len(curr_list),
                'new':     new_stocks,
                'removed': removed,
                'changed': changed,
                'top10':   top10,   # v3.1 新增：當前 Top 10 持股
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
        elif p == '/etf-catalog' or p.startswith('/etf-catalog?'):
            self._handle_etf_catalog_get()
        elif p == '/etf-tracker/status' or p.startswith('/etf-tracker/status?'):
            self._handle_tracker_status()
        elif p.startswith('/quote/'):
            sym = p[7:].split('?')[0]
            self._handle_quote(sym)
        elif p.startswith('/chip/'):
            sym = p[6:].split('?')[0]
            self._handle_chip(sym)
        elif p.startswith('/keystats/'):
            sym = p[10:].split('?')[0]
            self._handle_keystats(sym)
        elif p.startswith('/fundamental/'):
            sym = p[13:].split('?')[0]
            self._handle_fundamental(sym)
        elif p == '/sectors' or p.startswith('/sectors?'):
            self._handle_sectors()
        elif p == '/screener' or p.startswith('/screener?'):
            self._handle_screener_get()
        elif p == '/alert/status' or p.startswith('/alert/status?'):
            self._alert_status()
        elif p == '/alert/rules' or p.startswith('/alert/rules?'):
            self._alert_get_rules()
        elif p == '/alert/config' or p.startswith('/alert/config?'):
            self._alert_get_config()
        elif p == '/watch/status' or p.startswith('/watch/status?'):
            self._watch_status()
        elif p == '/txf' or p.startswith('/txf?'):
            self._handle_txf()
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

    def do_POST(self):
        p = self.path.split('?')[0]
        if p == '/etf-catalog':
            self._handle_etf_catalog_post()
        elif p == '/etf-tracker/run':
            self._handle_tracker_run()
        elif p == '/screener':
            self._handle_screener_post()
        elif p == '/ai-report':
            self._handle_ai_report()
        elif p == '/alert/rules':
            self._alert_post_rules()
        elif p == '/alert/config':
            self._alert_post_config()
        elif p == '/alert/test':
            self._alert_test()
        elif p == '/etf-report/email':
            self._etf_report_email()
        elif p == '/watch/rules':
            self._watch_post_rules()
        elif p == '/watch/config':
            self._watch_post_config()
        else:
            self._err('not found', 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

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
        # nocache=1 → bypass LRU. Used by wl_live_v3.js so watchlist polling
        # always gets fresh Yahoo data (LRUCache has no TTL).
        nocache  = qs.get('nocache',  ['0'])[0] == '1'
        if not syms:
            self._ok(b'{}'); return
        results = {}
        futures = {_pool.submit(fetch_one, s, rng, interval, nocache): s for s in syms}
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
                url = f'https://{base}.finance.yahoo.com/v8/finance/chart/{candidate}?interval=1m&range=1d&includePrePost=true'
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
                        'marketState':  meta.get('marketState'),  # PRE/REGULAR/POST/POSTPOST/CLOSED
                        # v3.8: 盤後/盤前延伸交易 (主要美股；台股個股無真實盤後波動)
                        'postMarketPrice':     meta.get('postMarketPrice'),
                        'postMarketChangePct': meta.get('postMarketChangePercent'),
                        'preMarketPrice':      meta.get('preMarketPrice'),
                        'preMarketChangePct':  meta.get('preMarketChangePercent'),
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

    def _handle_etf_catalog_get(self):
        """回傳 etf_catalog.json 內容（含全部 ETF 不論 enabled 與否）"""
        if not os.path.isfile(ETF_CATALOG_FILE):
            self._err('etf_catalog.json not found', 404); return
        try:
            with open(ETF_CATALOG_FILE, 'rb') as f:
                data = f.read()
            self._ok(data)
        except Exception as e:
            self._err('read catalog failed: ' + str(e), 500)

    def _handle_etf_catalog_post(self):
        """接收前端 JSON 更新 catalog，整檔覆寫"""
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length > 0 else b''
            # Validate it parses
            obj = json.loads(body.decode('utf-8'))
            if 'categories' not in obj:
                self._err('invalid catalog: missing categories', 400); return
            # Backup current file before overwrite
            if os.path.isfile(ETF_CATALOG_FILE):
                bk = ETF_CATALOG_FILE + '.bak'
                try:
                    import shutil
                    shutil.copyfile(ETF_CATALOG_FILE, bk)
                except Exception: pass
            with open(ETF_CATALOG_FILE, 'w', encoding='utf-8') as f:
                json.dump(obj, f, ensure_ascii=False, indent=2)
            n = sum(1 for c in obj.get('categories', []) for e in c.get('etfs', []) if e.get('enabled'))
            self._ok(json.dumps({'ok': True, 'enabledCount': n}).encode())
        except json.JSONDecodeError as e:
            self._err('invalid JSON: ' + str(e), 400)
        except Exception as e:
            self._err('save catalog failed: ' + str(e), 500)

    def _handle_tracker_run(self):
        """POST /etf-tracker/run — 啟動背景 thread 跑 etf_delta_tracker.py"""
        with _tracker_lock:
            if _tracker_state['running']:
                self._err('tracker already running', 409); return
            _tracker_state.update({
                'running': True, 'startedAt': time.time(),
                'finishedAt': None, 'lastReturnCode': None, 'lastOutput': '',
            })
        t = threading.Thread(target=_run_tracker_async, daemon=True)
        t.start()
        self._ok(json.dumps({'ok': True, 'started': True}).encode())

    def _handle_tracker_status(self):
        """GET /etf-tracker/status — 回傳當前狀態"""
        with _tracker_lock:
            state = dict(_tracker_state)
        self._ok(json.dumps(state, ensure_ascii=False).encode())

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

    # ──────────────────────────────────────────────────────────
    # v3.0 endpoints
    # ──────────────────────────────────────────────────────────
    def _handle_keystats(self, sym):
        """Fetch market cap / P/E / EPS / PEG / growth.
        v3.5 strategy (because Yahoo v10 quoteSummary now requires crumb auth):
          1) yfinance.Ticker(sym).info  — handles cookie/crumb internally (PRIMARY)
          2) Yahoo v10 quoteSummary direct (fallback, may fail without crumb)
          3) Yahoo Finance HTML scrape  (last resort)
        For TW (.TW) symbols that miss, retry with .TWO (OTC / 興櫃).
        Cache 1 hour per symbol.
        """
        key = f'keystats:{sym}:{int(time.time() // 3600)}'
        c = _cache.get(key)
        if c is not None:
            self._ok(c); return

        out = self._fetch_keystats_yfinance(sym)

        # TW main board miss → try .TWO
        if (sym.endswith('.TW') and not sym.endswith('.TWO')
            and out.get('trailingPE') is None and out.get('eps') is None
            and out.get('marketCap') is None):
            otc = sym[:-3] + '.TWO'
            otc_out = self._fetch_keystats_yfinance(otc)
            if (otc_out.get('trailingPE') is not None or otc_out.get('eps') is not None
                or otc_out.get('marketCap') is not None):
                out = otc_out
                out['_resolved'] = otc

        # Fallback 1: v10 direct (may still work for some symbols)
        if (out.get('trailingPE') is None and out.get('eps') is None
            and out.get('marketCap') is None):
            v10 = self._fetch_keystats_v10(sym)
            for k in ('trailingPE','forwardPE','eps','forwardEps','pegRatio','marketCap',
                      'priceToBook','dividendYield','shortName','longName','currency',
                      'earningsQuarterlyGrowth','revenueGrowth','regularMarketPrice'):
                if out.get(k) is None and v10.get(k) is not None:
                    out[k] = v10[k]
            if v10.get('trailingPE') is not None:
                out['_source'] = (out.get('_source','') + '+v10').strip('+')

        # Fallback 2: HTML scrape
        if (out.get('trailingPE') is None and out.get('eps') is None
            and out.get('marketCap') is None):
            html_out = self._fetch_keystats_html(sym)
            for k in ('trailingPE','eps','marketCap','priceToBook','dividendYield',
                      'shortName','currency'):
                if out.get(k) is None and html_out.get(k) is not None:
                    out[k] = html_out[k]
            if html_out.get('trailingPE') is not None:
                out['_source'] = (out.get('_source','') + '+html').strip('+')

        body = json.dumps(out, ensure_ascii=False).encode()
        _cache.set(key, body)
        self._ok(body)

    def _fetch_keystats_yfinance(self, sym):
        """yfinance handles Yahoo's crumb/cookie auth — most reliable in 2026."""
        out = {'symbol': sym, '_source': 'yfinance'}
        try:
            import yfinance as yf
        except ImportError:
            out['_error'] = 'yfinance not installed (run: pip install yfinance)'
            return out
        try:
            t = yf.Ticker(sym)
            info = t.info or {}
            if not info or (info.get('regularMarketPrice') is None
                            and info.get('previousClose') is None):
                out['_error'] = 'yfinance returned empty info'
                return out
            out['trailingPE']        = info.get('trailingPE')
            out['forwardPE']         = info.get('forwardPE')
            out['priceToBook']       = info.get('priceToBook')
            out['eps']               = (info.get('trailingEps')
                                        or info.get('epsTrailingTwelveMonths'))
            out['forwardEps']        = info.get('forwardEps')
            # yfinance has both 'pegRatio' (legacy) and 'trailingPegRatio' (newer)
            out['pegRatio']          = (info.get('trailingPegRatio')
                                        or info.get('pegRatio'))
            out['marketCap']         = info.get('marketCap')
            dy = info.get('dividendYield')
            # yfinance returns yield either as 0-1 (decimal) or 0-100 already, depending on version
            if dy is not None and isinstance(dy, (int, float)):
                out['dividendYield'] = dy * 100 if dy < 1 else dy
            else:
                out['dividendYield'] = None
            out['currency']          = info.get('currency')
            # Prefer longName (英文全名) for non-TW; for TW use shortName if it's Chinese
            sn = info.get('shortName')
            ln = info.get('longName')
            out['shortName']         = sn or ln
            out['longName']          = ln
            out['regularMarketPrice']= (info.get('regularMarketPrice')
                                        or info.get('currentPrice'))
            qg = info.get('earningsQuarterlyGrowth')
            out['earningsQuarterlyGrowth'] = (qg * 100) if qg is not None else None
            rg = info.get('revenueGrowth')
            out['revenueGrowth']     = (rg * 100) if rg is not None else None
        except Exception as e:
            print(f'[keystats-yf] {sym} failed: {e}')
            out['_error'] = str(e)
        return out

    def _fetch_keystats_v10(self, sym):
        """Yahoo v10 quoteSummary — returns clean JSON for exact symbol.
        Modules: summaryDetail (PE, marketCap, yield), defaultKeyStatistics
        (EPS, pegRatio, forwardEps), price (shortName), financialData (growth%).
        """
        out = {'symbol': sym, '_source': 'yahoo-v10'}
        try:
            modules = 'summaryDetail,defaultKeyStatistics,price,financialData'
            url = f'https://query1.finance.yahoo.com/v10/finance/quoteSummary/{sym}?modules={modules}'
            req = urllib.request.Request(url, headers=YF_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8', 'replace'))
            qs = data.get('quoteSummary') or {}
            result = qs.get('result') or []
            if not result:
                err = qs.get('error')
                out['_error'] = str(err) if err else 'no result'
                return out
            r0 = result[0]
            sd = r0.get('summaryDetail') or {}
            ks = r0.get('defaultKeyStatistics') or {}
            pr = r0.get('price') or {}
            fd = r0.get('financialData') or {}
            def raw(d, k):
                v = d.get(k)
                if isinstance(v, dict): return v.get('raw')
                return v
            out['trailingPE']    = raw(sd, 'trailingPE')
            out['forwardPE']     = raw(sd, 'forwardPE') or raw(ks, 'forwardPE')
            out['priceToBook']   = raw(ks, 'priceToBook') or raw(sd, 'priceToBook')
            out['eps']           = raw(ks, 'trailingEps')
            out['forwardEps']    = raw(ks, 'forwardEps')
            out['pegRatio']      = raw(ks, 'pegRatio')
            out['marketCap']     = raw(sd, 'marketCap') or raw(pr, 'marketCap')
            dy = raw(sd, 'dividendYield')
            out['dividendYield'] = (dy * 100) if dy is not None else None
            out['currency']      = pr.get('currency') or sd.get('currency')
            out['shortName']     = pr.get('shortName')
            out['longName']      = pr.get('longName')
            out['regularMarketPrice'] = raw(pr, 'regularMarketPrice')
            qg = raw(fd, 'earningsQuarterlyGrowth')
            out['earningsQuarterlyGrowth'] = (qg * 100) if qg is not None else None
            rg = raw(fd, 'revenueGrowth')
            out['revenueGrowth'] = (rg * 100) if rg is not None else None
        except Exception as e:
            print(f'[keystats-v10] {sym} failed: {e}')
            out['_error'] = str(e)
        return out

    def _fetch_keystats_html(self, sym):
        """Legacy HTML scrape fallback (regex on Yahoo Finance quote page)."""
        out = {'symbol': sym, '_source': 'yahoo-html'}
        try:
            url = f'https://finance.yahoo.com/quote/{sym}'
            req = urllib.request.Request(url, headers=YF_HEADERS)
            with urllib.request.urlopen(req, timeout=12) as resp:
                html = resp.read().decode('utf-8', 'replace')
            import re as _re
            # Anchor: find a JSON region that contains the exact symbol to avoid
            # cross-symbol contamination ("Bitcoin USD" leaking into 3529 search etc.)
            sym_quoted = '"symbol":"' + sym + '"'
            anchor = html.find(sym_quoted)
            search_region = html[anchor:anchor+50000] if anchor >= 0 else html
            patterns = {
                'marketCap':       r'"marketCap":\s*\{[^}]*"raw":\s*([\d.eE+-]+)',
                'trailingPE':      r'"trailingPE":\s*\{[^}]*"raw":\s*([\d.eE+-]+)',
                'priceToBook':     r'"priceToBook":\s*\{[^}]*"raw":\s*([\d.eE+-]+)',
                'dividendYield':   r'"trailingAnnualDividendYield":\s*\{[^}]*"raw":\s*([\d.eE+-]+)',
                'eps':             r'"epsTrailingTwelveMonths":\s*\{[^}]*"raw":\s*([\d.eE+-]+)',
                'currency':        r'"currency":\s*"([A-Z]+)"',
                'shortName':       r'"shortName":\s*"([^"]+)"',
            }
            for k, pat in patterns.items():
                m = _re.search(pat, search_region)
                if m:
                    val = m.group(1)
                    if k in ('currency','shortName'):
                        out[k] = val
                    else:
                        try: out[k] = float(val)
                        except: pass
            if out.get('dividendYield') is not None:
                out['dividendYield'] *= 100
        except Exception as e:
            print(f'[keystats-html] {sym} failed: {e}')
            out['_error'] = str(e)
        return out

    def _handle_chip(self, sym):
        """法人籌碼面板：三大法人買賣超 + 融資融券"""
        # Cache by sym+date
        from datetime import date as _date
        today = _date.today().strftime('%Y%m%d')
        key = f'chip:{sym}:{today}'
        c = _cache.get(key)
        if c is not None:
            self._ok(c); return
        # TWSE T86 三大法人買賣超
        clean = sym.replace('.TW', '').replace('.TWO', '').strip().upper()
        out = {'symbol': sym, 'date': today, 'inst': None, 'margin': None}
        try:
            url = f'https://www.twse.com.tw/rwd/zh/fund/T86?date={today}&selectType=ALLBUT0999&response=json'
            req = urllib.request.Request(url, headers=YF_HEADERS)
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
            data = json.loads(raw)
            if data.get('stat') in ('OK', 'ok'):
                # Find this symbol's row
                rows = data.get('data') or []
                fields = data.get('fields') or []
                idx_code = next((i for i,f in enumerate(fields) if '證券代號' in f), 0)
                for row in rows:
                    if row[idx_code].strip() == clean:
                        # Extract foreign, investment trust, dealer
                        def col(keyword, fallback=None):
                            for i, f in enumerate(fields):
                                if keyword in f:
                                    try: return float(row[i].replace(',', '').replace(' ', ''))
                                    except: return fallback
                            return fallback
                        out['inst'] = {
                            'foreign':       col('外陸資買賣超股數') or col('外資'),
                            'trust':         col('投信買賣超股數') or col('投信'),
                            'dealer':        col('自營商買賣超股數') or col('自營商'),
                            'total':         col('三大法人買賣超股數'),
                        }
                        break
        except Exception as e:
            print(f'[chip] T86 fetch failed for {sym}: {e}')
        # TWSE 融資融券 MI_MARGN
        try:
            url2 = f'https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={today}&selectType=ALL&response=json'
            req2 = urllib.request.Request(url2, headers=YF_HEADERS)
            with urllib.request.urlopen(req2, timeout=10) as resp:
                raw2 = resp.read()
            data2 = json.loads(raw2)
            if data2.get('stat') in ('OK', 'ok'):
                # tables[1] is per-stock data (tables[0] is header summary)
                tables = data2.get('tables') or []
                stock_rows = []
                for t in tables:
                    if t.get('title', '').find('信用') >= 0 or len(t.get('data', [])) > 100:
                        stock_rows = t.get('data', [])
                        fields = t.get('fields', [])
                        break
                if stock_rows and fields:
                    idx_code = next((i for i,f in enumerate(fields) if '股票' in f or '證券代號' in f), 0)
                    for row in stock_rows:
                        if row[idx_code].strip() == clean:
                            def col2(keyword, fallback=None):
                                for i, f in enumerate(fields):
                                    if keyword in f:
                                        try: return float(row[i].replace(',', '').replace(' ', ''))
                                        except: return fallback
                                return fallback
                            out['margin'] = {
                                'marginBalance':  col2('融資餘額'),
                                'shortBalance':   col2('融券餘額'),
                                'marginChange':   col2('融資-買進') or col2('融資增'),
                                'shortChange':    col2('融券-賣出') or col2('融券增'),
                            }
                            break
        except Exception as e:
            print(f'[chip] MI_MARGN fetch failed for {sym}: {e}')
        # 借券賣出餘額 TWT72U (v3.8)
        try:
            url3 = f'https://www.twse.com.tw/rwd/zh/marginTrading/TWT72U?date={today}&selectType=ALL&response=json'
            req3 = urllib.request.Request(url3, headers=YF_HEADERS)
            with urllib.request.urlopen(req3, timeout=10) as resp:
                data3 = json.loads(resp.read())
            if data3.get('stat') in ('OK', 'ok'):
                fields = data3.get('fields') or []
                rows = data3.get('data') or []
                idx_code = next((i for i, f in enumerate(fields) if '股票' in f or '代號' in f), 1)
                for row in rows:
                    if str(row[idx_code]).strip() == clean:
                        def col3(keyword, fb=None):
                            for i, f in enumerate(fields):
                                if keyword in f:
                                    try: return float(str(row[i]).replace(',', '').replace(' ', ''))
                                    except: return fb
                            return fb
                        out['shortLend'] = {
                            'sellVolume':  col3('借券賣出') or col3('當日賣出'),
                            'balance':     col3('借券賣出餘額') or col3('餘額'),
                        }
                        break
        except Exception as e:
            print(f'[chip] TWT72U fetch failed for {sym}: {e}')
        # 當沖比 TWTB4U (v3.8): 當沖成交量 / 總成交量
        try:
            url4 = f'https://www.twse.com.tw/rwd/zh/afterTrading/TWTB4U?date={today}&response=json'
            req4 = urllib.request.Request(url4, headers=YF_HEADERS)
            with urllib.request.urlopen(req4, timeout=10) as resp:
                data4 = json.loads(resp.read())
            if data4.get('stat') in ('OK', 'ok'):
                fields = data4.get('fields') or []
                rows = data4.get('data') or []
                idx_code = next((i for i, f in enumerate(fields) if '代號' in f), 0)
                for row in rows:
                    if str(row[idx_code]).strip() == clean:
                        def col4(keyword, fb=None):
                            for i, f in enumerate(fields):
                                if keyword in f:
                                    try: return float(str(row[i]).replace(',', '').replace(' ', '').replace('%', ''))
                                    except: return fb
                            return fb
                        dt_vol = col4('當日沖銷交易成交股數') or col4('當沖成交股數') or col4('成交股數')
                        out['dayTrade'] = {
                            'volume':  dt_vol,
                            'ratioPct': col4('當日沖銷交易比率') or col4('當沖比'),
                        }
                        break
        except Exception as e:
            print(f'[chip] TWTB4U fetch failed for {sym}: {e}')
        # 法人連續買賣超天數 (v3.8): 讀 chip_history 快照
        try:
            out['streak'] = _chip_streak(clean)
        except Exception as e:
            print(f'[chip] streak calc failed for {sym}: {e}')
        # 寫入今日 chip_history 快照供日後連續天數計算
        try:
            _chip_history_record(clean, out)
        except Exception:
            pass
        body = json.dumps(out, ensure_ascii=False).encode()
        _cache.set(key, body)
        self._ok(body)

    def _handle_fundamental(self, sym):
        """基本面 (v3.8)：月營收 YoY/MoM + 損益表三率 + 基本面評分
           資料源：TWSE OpenAPI 全市場資料集 (上市 _L / 上櫃 _O)，整批快取一天"""
        from datetime import date as _date
        today = _date.today().strftime('%Y%m%d')
        clean = sym.replace('.TW', '').replace('.TWO', '').strip().upper()
        key = f'fund:{clean}:{today}'
        c = _cache.get(key)
        if c is not None:
            self._ok(c); return
        out = {'symbol': sym, 'code': clean, 'date': today, 'revenue': None, 'income': None, 'score': None}
        # 月營收（欄位用「含子字串」模糊比對：TWSE 欄位有前綴如「營業收入-當月營收」）
        rev = _openapi_lookup(['t187ap05_L', 't187ap05_O'], clean)
        if rev:
            out['revenue'] = {
                'period':    rev.get('資料年月'),
                'monthRev':  _pick_num(rev, ['當月營收'], ['累計']),
                'yoyPct':    _pick_num(rev, ['去年同月增減']),
                'momPct':    _pick_num(rev, ['上月比較增減']),
                'cumRev':    _pick_num(rev, ['當月累計營收']),
                'cumYoyPct': _pick_num(rev, ['累計', '前期比較增減']),
            }
        # 綜合損益表 → 三率（同樣模糊比對，避免全形/半形括號差異 例 營業毛利（毛損））
        inc = _openapi_lookup(['t187ap06_L_ci', 't187ap06_O_ci', 't187ap06_L', 't187ap06_O'], clean)
        if inc:
            sales = _pick_num(inc, ['營業收入'], ['成本', '毛利', '費用', '外', '淨額'])
            gross = _pick_num(inc, ['營業毛利'])
            op = _pick_num(inc, ['營業利益'])
            net = _pick_num(inc, ['本期淨利']) or _pick_num(inc, ['本期綜合損益總額']) \
                or _pick_num(inc, ['淨利', '母公司'])
            eps = _pick_num(inc, ['基本每股盈餘'])
            pct = lambda a, b: round(a / b * 100, 2) if (a is not None and b) else None
            out['income'] = {
                'period':       inc.get('資料年度') or inc.get('資料季別') or inc.get('年度'),
                'sales':        sales, 'eps': eps,
                'grossMargin':  pct(gross, sales),
                'opMargin':     pct(op, sales),
                'netMargin':    pct(net, sales),
            }
        # 基本面評分 0~100（成長性/獲利性二維簡版）
        out['score'] = _fundamental_score(out)
        body = json.dumps(out, ensure_ascii=False).encode()
        _cache.set(key, body)
        self._ok(body)

    def _handle_sectors(self):
        """產業熱力圖：依市場切換資料來源
        v3.2 改版：
          • mkt=US → 11 個 SPDR Select Sector ETFs (XLE/XLF/XLK/XLV/XLY/XLP/XLI/XLB/XLU/XLRE/XLC)
          • mkt=TW → 先試 TWSE MI_INDEX；失敗時用 24 個代表性個股按類股分組（Yahoo 後備）
          • ?nocache=1 強制重抓
        """
        qs = parse_qs(urlparse(self.path).query)
        mkt = (qs.get('mkt', ['TW'])[0] or 'TW').upper()
        nocache = qs.get('nocache', ['0'])[0] == '1'

        if mkt == 'US':
            return self._handle_sectors_us(nocache=nocache)
        return self._handle_sectors_tw(nocache=nocache)

    # ── US: SPDR Select Sector ETFs（11 大產業）─────────────────
    def _handle_sectors_us(self, nocache=False):
        from datetime import date as _date
        key = f'sectors:US:{_date.today().strftime("%Y%m%d")}'
        if not nocache:
            cached = _cache.get(key)
            if cached is not None:
                self._ok(cached); return
        SPDR = [
            ('XLE',  '能源 Energy'),
            ('XLF',  '金融 Financials'),
            ('XLK',  '科技 Technology'),
            ('XLV',  '醫療 Healthcare'),
            ('XLY',  '非必需消費 Cons. Discr.'),
            ('XLP',  '必需消費 Cons. Staples'),
            ('XLI',  '工業 Industrials'),
            ('XLB',  '原物料 Materials'),
            ('XLU',  '公用事業 Utilities'),
            ('XLRE', '不動產 Real Estate'),
            ('XLC',  '通訊 Communication'),
        ]
        sectors = []
        for sym, name in SPDR:
            try:
                # 改 range=5d：用多根 K 線交叉驗證 Yahoo 落後狀況。
                # 原本 range=1d + chartPreviousClose 在 Yahoo 雙伺服器資料不同步時
                # 會把上上日 close 當「昨天」，算出錯誤 %。
                _, raw, _ = fetch_one(sym, rng='5d', interval='1d', nocache=nocache)
                d = json.loads(raw)
                res = (d.get('chart') or {}).get('result') or []
                if not res: continue
                r0 = res[0]
                meta = r0.get('meta') or {}
                ts = r0.get('timestamp') or []
                raw_closes = (r0.get('indicators',{}).get('quote') or [{}])[0].get('close') or []
                valid = [(ts[i], raw_closes[i]) for i in range(min(len(ts), len(raw_closes)))
                         if raw_closes[i] is not None and ts[i] is not None]
                if not valid: continue
                last_t, last_c = valid[-1]
                rmt = meta.get('regularMarketTime')
                rmp = meta.get('regularMarketPrice')
                # Yahoo 日線落後修正：rmt 比 last K 晚 > 20h → rmp 是今天、last_c 是昨天
                if (rmt and rmp is not None and isinstance(rmp,(int,float)) and rmp > 0
                        and rmt - last_t > 20 * 3600):
                    cur, prev = float(rmp), float(last_c)
                else:
                    cur = float(last_c)
                    prev = float(valid[-2][1]) if len(valid) >= 2 else (meta.get('chartPreviousClose') or meta.get('previousClose'))
                if cur is None or prev is None or prev == 0: continue
                chg = cur - prev
                pct = chg / prev * 100
                sectors.append({'name': name, 'close': float(cur), 'change': float(chg), 'changePct': float(pct), 'symbol': sym})
            except Exception as e:
                print(f'[sectors-us] {sym} failed: {e}')
        if sectors:
            body = json.dumps({'date': _date.today().strftime('%Y-%m-%d'), 'market': 'US', 'sectors': sectors}, ensure_ascii=False).encode()
            _cache.set(key, body)
            self._ok(body)
        else:
            self._ok(json.dumps({'date': '', 'market': 'US', 'sectors': [], '_msg': 'SPDR ETFs all failed'}, ensure_ascii=False).encode())

    # ── TW: TWSE MI_INDEX → Yahoo 代理股後備 ───────────────────
    def _handle_sectors_tw(self, nocache=False):
        from datetime import date as _date, timedelta
        qs = parse_qs(urlparse(self.path).query)
        nocache = qs.get('nocache', ['0'])[0] == '1'

        def parse_twse_indices(raw_json):
            """從 TWSE MI_INDEX 回應抓出類股指數 list。
            傳回 [{name, close, change, changePct}, ...]，找不到回 []。"""
            try:
                data = json.loads(raw_json) if isinstance(raw_json, (bytes, bytearray, str)) else raw_json
            except Exception:
                return []
            tables = data.get('tables') or []
            for t in tables:
                title = t.get('title', '') or ''
                fields = t.get('fields', []) or []
                rows = t.get('data', []) or []

                # 1) title 嚴格比對：類 + (指數|漲跌)
                strict_match = ('類' in title) and ('指數' in title or '漲跌' in title)
                # 2) 寬鬆比對：≥ 20 行 + 首欄文字含「類」或「指數」(典型 ~30 個 TWSE 類股)
                loose_match = False
                if not strict_match and len(rows) >= 20 and rows:
                    first = rows[0]
                    if isinstance(first, list) and first:
                        cell = str(first[0] or '')
                        if '類' in cell or '指數' in cell:
                            loose_match = True
                # 3) fields 比對：必須有「收盤」與「漲跌」欄
                fields_ok = (
                    any('收盤' in f for f in fields) and
                    any('漲跌' in f for f in fields)
                )
                if not (strict_match or loose_match) or not fields_ok:
                    continue

                idx_name = 0
                idx_close = next((i for i,f in enumerate(fields) if '收盤' in f), 1)
                idx_chg   = next((i for i,f in enumerate(fields) if ('漲跌' in f) and ('幅' not in f) and ('%' not in f)), 2)
                idx_pct   = next((i for i,f in enumerate(fields) if '%' in f or '幅' in f), 3)
                out_list = []
                for row in rows:
                    try:
                        name = (row[idx_name] or '').strip()
                    except Exception:
                        continue
                    if not name:
                        continue
                    # 過濾：必須是類股指數（非單一股票）。判斷：名稱含「類」或「指數」
                    if '類' not in name and '指數' not in name:
                        continue
                    try:
                        close = float(str(row[idx_close]).replace(',','').replace(' ','').replace('--',''))
                    except Exception:
                        continue
                    try:
                        chg = float(str(row[idx_chg]).replace(',','').replace(' ','').replace('--','0'))
                    except Exception:
                        chg = 0.0
                    try:
                        pct_raw = str(row[idx_pct]).replace(',','').replace('%','').replace(' ','').replace('--','0')
                        # TWSE 偶有 "+1.23" 帶正號 / 或 "(1.23)" 表負，都吃掉
                        pct_raw = pct_raw.lstrip('+').strip('()')
                        pct = float(pct_raw) if pct_raw else 0.0
                    except Exception:
                        pct = 0.0
                    if close is None:
                        continue
                    out_list.append({
                        'name': name.replace('類指數', '').replace('指數', '').strip(),
                        'close': close,
                        'change': chg,
                        'changePct': pct,
                    })
                if out_list:
                    return out_list
            return []

        urls_template = [
            'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={date}&type=IND&response=json',
            'https://www.twse.com.tw/exchangeReport/MI_INDEX?date={date}&type=IND&response=json',
        ]

        for back in range(7):
            d = _date.today() - timedelta(days=back)
            date_str = d.strftime('%Y%m%d')
            key = f'sectors:{date_str}'

            if not nocache:
                cached = _cache.get(key)
                if cached is not None:
                    try:
                        obj = json.loads(cached)
                        if obj.get('sectors'):
                            self._ok(cached); return
                    except Exception:
                        pass

            sectors = []
            last_err = None
            for tmpl in urls_template:
                try:
                    url = tmpl.format(date=date_str)
                    req = urllib.request.Request(url, headers=YF_HEADERS)
                    with urllib.request.urlopen(req, timeout=10) as resp:
                        raw = resp.read()
                    sectors = parse_twse_indices(raw)
                    if sectors:
                        print(f'[sectors] OK date={date_str} via {tmpl.split("?")[0][-20:]} -> {len(sectors)} sectors')
                        break
                except Exception as e:
                    last_err = str(e)
                    continue
            if not sectors and last_err:
                print(f'[sectors] {date_str} all endpoints failed: {last_err}')

            if sectors:
                out = {'date': date_str, 'sectors': sectors}
                body = json.dumps(out, ensure_ascii=False).encode()
                _cache.set(key, body)
                self._ok(body)
                return

        # ── TWSE 7 天都失敗 → Yahoo 後備：用代表性個股按類股分組算平均 ──
        print('[sectors-tw] TWSE failed for 7 days, falling back to Yahoo proxy stocks')
        try:
            yahoo_sectors = self._fetch_tw_sectors_via_yahoo(nocache=nocache)
            if yahoo_sectors:
                from datetime import date as _date
                out = {
                    'date': _date.today().strftime('%Y-%m-%d'),
                    'market': 'TW',
                    'sectors': yahoo_sectors,
                    '_source': 'yahoo-proxy',
                }
                body = json.dumps(out, ensure_ascii=False).encode()
                _cache.set(f'sectors:TW:yahoo:{_date.today().strftime("%Y%m%d")}', body)
                self._ok(body)
                return
        except Exception as e:
            print(f'[sectors-tw] Yahoo fallback also failed: {e}')

        body = json.dumps({'date': '', 'market': 'TW', 'sectors': [], '_msg': 'TWSE + Yahoo both failed'}, ensure_ascii=False).encode()
        self._ok(body)

    # ── Yahoo 後備：24 個代表性個股按類股分組 ─────────────────────
    # 每個類股取 2~3 檔代表股，等權平均當作該類漲跌
    TW_SECTOR_PROXIES = {
        '半導體':     ['2330', '2454', '2303'],     # 台積電 / 聯發科 / 聯電
        '電子下游':   ['2317', '2382', '2308'],     # 鴻海 / 廣達 / 台達電
        '金融':       ['2882', '2891', '2884'],     # 國泰金 / 中信金 / 玉山金
        '食品':       ['1216', '1227'],             # 統一 / 佳格
        '塑膠':       ['1301', '1303', '1326'],     # 台塑 / 南亞 / 台化
        '鋼鐵':       ['2002', '2027'],             # 中鋼 / 大成鋼
        '紡織纖維':   ['1402', '1476'],             # 遠東新 / 儒鴻
        '電機機械':   ['1503', '1504'],             # 士電 / 東元
        '化學':       ['1722', '1707'],             # 台肥 / 葡萄王
        '生技醫療':   ['4904', '3105'],             # 遠傳 (錯誤已知) — 改為實際生技
        '航運':       ['2603', '2609', '2615'],     # 長榮 / 陽明 / 萬海
        '汽車':       ['2207', '2204'],             # 和泰車 / 中華
        '營建':       ['2548', '2545'],             # 華固 / 皇翔
        '觀光':       ['2727', '2731'],             # 王品 / 雄獅
        '電信':       ['2412', '3045'],             # 中華電 / 台灣大
        '油電燃氣':   ['9907', '9917'],             # 統一實 (用作能源 proxy) / 中保
        '玻璃陶瓷':   ['1802', '1815'],             # 台玻 / 富喬
        '造紙':       ['1903', '1904'],             # 士紙 / 正隆
        '橡膠':       ['2105', '2104'],             # 正新 / 中橡
        '貿易百貨':   ['2912', '2915'],             # 統一超 / 潤泰全
    }

    def _fetch_tw_sectors_via_yahoo(self, nocache=False):
        """用 Yahoo Finance 抓代表性個股，按類股分組算等權平均漲跌 %。
        失敗的代表股自動跳過；類股至少要有 1 檔成功才回傳。"""
        out_sectors = []
        for sector_name, codes in self.TW_SECTOR_PROXIES.items():
            pct_list = []
            close_sum = 0.0; close_n = 0
            for code in codes:
                sym = code + '.TW'
                try:
                    # 改 range=5d 並用 last K vs rmt 對齊判斷（同 sectors-us 修法）
                    _, raw, _ = fetch_one(sym, rng='5d', interval='1d', nocache=nocache)
                    d = json.loads(raw)
                    res = (d.get('chart') or {}).get('result') or []
                    if not res: continue
                    r0 = res[0]
                    meta = r0.get('meta') or {}
                    ts = r0.get('timestamp') or []
                    raw_closes = (r0.get('indicators',{}).get('quote') or [{}])[0].get('close') or []
                    valid = [(ts[i], raw_closes[i]) for i in range(min(len(ts), len(raw_closes)))
                             if raw_closes[i] is not None and ts[i] is not None]
                    if not valid: continue
                    last_t, last_c = valid[-1]
                    rmt = meta.get('regularMarketTime')
                    rmp = meta.get('regularMarketPrice')
                    if (rmt and rmp is not None and isinstance(rmp,(int,float)) and rmp > 0
                            and rmt - last_t > 20 * 3600):
                        cur, prev = float(rmp), float(last_c)
                    else:
                        cur = float(last_c)
                        prev = float(valid[-2][1]) if len(valid) >= 2 else (meta.get('chartPreviousClose') or meta.get('previousClose'))
                    if cur is None or prev is None or prev == 0: continue
                    pct_list.append((cur - prev) / prev * 100)
                    close_sum += float(cur); close_n += 1
                except Exception as e:
                    print(f'[sectors-tw/yahoo] {sym} fail: {e}')
                    continue
            if pct_list:
                avg_pct = sum(pct_list) / len(pct_list)
                avg_close = close_sum / close_n if close_n else 0
                out_sectors.append({
                    'name': sector_name,
                    'close': round(avg_close, 2),
                    'change': round(avg_close * avg_pct / 100, 2),
                    'changePct': round(avg_pct, 2),
                    'proxies': codes,
                })
        return out_sectors

    # ── Screener: built-in TW Top-200 + filter on candles ─────
    _TW_TOP200 = [
        # Top 50 weighted
        '2330','2317','2454','2308','2382','2412','2881','6505','1303','2882','2891','2002','3711','1301',
        '2886','2884','2885','5871','3045','2887','2890','2912','1216','2603','2618','5876','3034','5880',
        '2880','2207','2883','1101','1102','2892','9910','2379','2474','1326','2105','2357','1402','2395',
        '6669','2615','1605','3008','2227','2345','2049','2027',
        # Top 51-150 popular
        '6770','3231','3037','2376','2376','3036','3231','6781','5269','5283','2049','2891','8046','3653',
        '6488','6679','3661','3037','6770','2376','3035','8210','6770','3023','6789','2049','2376',
        # Add common ETFs to scan too
        '0050','0056','00878','00919','00929','00939','00940','00713','00891','00892','006208',
    ]

    def _handle_screener_get(self):
        """GET /screener — return preset filter list + symbol pool"""
        presets = [
            # ── 多方 / 進場 ──
            {'key':'breakout_20',    'name':'突破 20 日新高 + 量增',  'desc':'抓動能爆發初期','side':'long'},
            {'key':'rsi_oversold',   'name':'RSI 超賣 + 站上 SMA60',  'desc':'多頭趨勢中的超賣反彈點','side':'long'},
            {'key':'bullish_align',  'name':'均線多頭排列',            'desc':'SMA5 > SMA20 > SMA60，強勢結構','side':'long'},
            {'key':'pullback_sma60', 'name':'回測 SMA60 不破',         'desc':'多頭趨勢回檔買進點','side':'long'},
            {'key':'pullback_sma20', 'name':'回測 SMA20 不破',         'desc':'強勢股短線回檔買點','side':'long'},
            {'key':'vol_spike',      'name':'量增 2x 且收紅',          'desc':'籌碼異動 + 短線買盤','side':'long'},
            {'key':'cross_golden',   'name':'近 5 日黃金交叉',          'desc':'SMA20 上穿 SMA60','side':'long'},
            {'key':'near_52w_low',   'name':'逼近 60 日低檔',          'desc':'落底區間，搏反彈（風險高）','side':'long'},
            {'key':'top_gainers',    'name':'漲幅榜 Top',              'desc':'今日漲幅最大（追勢/強勢觀察）','side':'long'},
            # ── 空方 / 跌幅 / 出場警示 ──
            {'key':'top_losers',     'name':'跌幅榜 Top',              'desc':'今日跌幅最大（賣壓/弱勢）','side':'short'},
            {'key':'breakdown_20',   'name':'跌破 20 日新低 + 量增',  'desc':'空頭動能啟動、停損警示','side':'short'},
            {'key':'bearish_align',  'name':'均線空頭排列',            'desc':'SMA5 < SMA20 < SMA60，弱勢結構','side':'short'},
            {'key':'death_cross',    'name':'近 5 日死亡交叉',          'desc':'SMA20 下穿 SMA60，趨勢轉空','side':'short'},
            {'key':'break_sma60_dn', 'name':'跌破 SMA60',              'desc':'跌破季線，中期轉弱','side':'short'},
            {'key':'rsi_overbought', 'name':'RSI 過熱 (>75)',          'desc':'短線過熱，留意回檔/停利','side':'short'},
            {'key':'high_vol_drop',  'name':'帶量下跌 (出貨)',         'desc':'量增 2x 且收黑，疑似出貨','side':'short'},
        ]
        try:
            _uni = _get_tw_universe()
        except Exception:
            _uni = []
        try:
            _sec = sorted(set(_get_tw_sectors().values()))
        except Exception:
            _sec = []
        out = {'presets': presets, 'symbolCount': len(_uni) or len(set(self._TW_TOP200)),
               'sectors': _sec}
        self._ok(json.dumps(out, ensure_ascii=False).encode())

    def _handle_screener_post(self):
        """POST /screener — body: {preset:'...', symbols:[...] (optional)} or {custom:'...'}"""
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length) or b'{}')
        except Exception as e:
            self._err('bad body: ' + str(e), 400); return
        preset = body.get('preset')
        custom = body.get('custom')
        # 預設掃全台股宇集（上市+上櫃普通股）；抓不到才退回精選清單
        try:
            _uni = _get_tw_universe()
        except Exception:
            _uni = []
        syms = list(set(body.get('symbols') or _uni or self._TW_TOP200))
        # 產業別篩選：sector='__TECH__' 科技電子整合，或單一產業別名稱
        sector = (body.get('sector') or '').strip()
        if sector and sector not in ('全部', 'all', ''):
            try:
                smap = _get_tw_sectors()
                want = _TECH_SECTORS if sector == '__TECH__' else {sector}
                syms = [s for s in syms if smap.get(str(s).replace('.TW', '').replace('.TWO', '')) in want]
            except Exception as e:
                print('[screener] sector filter failed:', e)
        # Fetch all syms in parallel using existing fetch_one
        results = []
        ind_cache = {}
        futures = {_pool.submit(fetch_one, s + '.TW' if not s.endswith('.TW') else s): s for s in syms}
        for fut in as_completed(futures):
            sym, data, _ = fut.result()
            if not data: continue
            try:
                parsed = json.loads(data)
                res = parsed.get('chart', {}).get('result', [{}])[0]
                ts = res.get('timestamp') or []
                q = (res.get('indicators',{}).get('quote') or [{}])[0]
                meta = res.get('meta', {})
                if len(ts) < 70: continue
                # Build per-bar arrays — pair (timestamp, close) and filter null closes
                raw_closes = q.get('close') or []
                raw_highs  = q.get('high')  or []
                raw_lows   = q.get('low')   or []
                raw_vols   = q.get('volume') or []
                closes, highs, lows, vols, ts_valid = [], [], [], [], []
                for i in range(min(len(ts), len(raw_closes))):
                    c = raw_closes[i]
                    if c is None: continue
                    closes.append(c)
                    highs.append(raw_highs[i] if i < len(raw_highs) and raw_highs[i] is not None else c)
                    lows.append(raw_lows[i]  if i < len(raw_lows)  and raw_lows[i]  is not None else c)
                    vols.append(raw_vols[i]  if i < len(raw_vols)  and raw_vols[i]  is not None else 0)
                    ts_valid.append(ts[i])
                if len(closes) < 70: continue
                # ── Yahoo data freshness fix ──────────────────────────
                # Yahoo 部分台股 ETF/個股 daily K 線會落後 regularMarketPrice
                # 一天。如 2454 5/28 收 4410，但 candles[-1] 仍是 5/27 4640。
                # 偵測：regularMarketTime 比 last candle ts 晚 > 20h → 合成
                # 今日 K 線（OHLC = rmp, vol 用近 5 日均量）。
                rmt = meta.get('regularMarketTime')
                rmp = meta.get('regularMarketPrice')
                if (rmt and rmp is not None and isinstance(rmp, (int, float)) and rmp > 0
                        and ts_valid and rmt - ts_valid[-1] > 20 * 3600):
                    syn_vol = sum(vols[-5:]) / 5 if len(vols) >= 5 else 0
                    closes.append(float(rmp))
                    highs.append(float(rmp))
                    lows.append(float(rmp))
                    vols.append(syn_vol)
                    ts_valid.append(rmt)
                ind = self._calc_ind(closes, highs, lows, vols)
                if self._screener_match(preset or custom, ind, closes, highs, vols):
                    results.append({
                        'sym': sym.replace('.TW','').replace('.TWO',''),
                        'name': meta.get('shortName') or meta.get('symbol') or sym,
                        'close': ind['close'], 'changePct': ind['changePct'],
                        'rsi14': round(ind['rsi14'],1) if ind['rsi14'] else None,
                        'volRatio': round(ind['volRatio'],2) if ind['volRatio'] else None,
                        'sma5': round(ind['sma5'],2) if ind['sma5'] else None,
                        'sma20': round(ind['sma20'],2) if ind['sma20'] else None,
                        'sma60': round(ind['sma60'],2) if ind['sma60'] else None,
                    })
            except Exception as e:
                continue
        # 空方/跌幅類 → 由跌最多排序（升冪）；其餘 → 漲幅降冪
        _bear = {'top_losers', 'breakdown_20', 'bearish_align', 'death_cross',
                 'break_sma60_dn', 'high_vol_drop', 'near_52w_low'}
        asc = (preset in _bear)
        results.sort(key=lambda x: x.get('changePct') or 0, reverse=not asc)
        # 漲/跌幅榜只取前 40 檔避免整包
        if preset in ('top_gainers', 'top_losers'):
            results = results[:40]
        self._ok(json.dumps({'results': results, 'scanned': len(syms), 'matched': len(results)}, ensure_ascii=False).encode())

    def _calc_ind(self, closes, highs, lows, vols):
        n = len(closes)
        def sma(p, idx):
            if idx + 1 < p: return None
            return sum(closes[idx-p+1:idx+1]) / p
        # RSI 14
        g = l = 0
        for i in range(n-14, n):
            if i < 1: continue
            d = closes[i] - closes[i-1]
            if d > 0: g += d
            else: l -= d
        rsi = 100 if l == 0 else 100 - 100/(1 + g/l)
        # Vol ratio
        v5 = sum(vols[-5:]) / 5 if len(vols) >= 5 else 0
        v20 = sum(vols[-20:]) / 20 if len(vols) >= 20 else 0
        volRatio = v5/v20 if v20 > 0 else 0
        return {
            'close': closes[-1], 'prev': closes[-2] if n >= 2 else None,
            'changePct': (closes[-1] - closes[-2])/closes[-2]*100 if n >= 2 else 0,
            'sma5': sma(5, n-1), 'sma20': sma(20, n-1), 'sma60': sma(60, n-1),
            'sma5_prev': sma(5, n-2), 'sma60_prev': sma(60, n-2),
            'sma20_prev': sma(20, n-2), 'rsi14': rsi, 'volRatio': volRatio,
            'high20': max(highs[-21:-1]) if len(highs) >= 21 else None,
            'high60': max(highs[-61:-1]) if len(highs) >= 61 else None,
            'low20': min(lows[-21:-1]) if len(lows) >= 21 else None,
            'low60': min(lows[-61:-1]) if len(lows) >= 61 else None,
        }

    def _screener_match(self, preset, i, closes, highs, vols):
        if not i.get('close'): return False
        c = i['close']
        if preset == 'breakout_20':
            return i['high20'] and c > i['high20'] and i['volRatio'] and i['volRatio'] > 1.5
        if preset == 'rsi_oversold':
            return i['rsi14'] and i['rsi14'] < 35 and i['sma60'] and c > i['sma60']
        if preset == 'bullish_align':
            return all([i['sma5'], i['sma20'], i['sma60']]) and i['sma5'] > i['sma20'] > i['sma60']
        if preset == 'pullback_sma60':
            return i['sma60'] and abs(c - i['sma60']) / i['sma60'] < 0.02 and i['sma60_prev'] and i['sma60'] > i['sma60_prev']
        if preset == 'vol_spike':
            return i['volRatio'] and i['volRatio'] > 2 and i['prev'] and c > i['prev']
        if preset == 'cross_golden':
            return all([i['sma20'], i['sma60'], i['sma20_prev'], i['sma60_prev']]) \
                   and i['sma20_prev'] <= i['sma60_prev'] and i['sma20'] > i['sma60']
        if preset == 'pullback_sma20':
            return i['sma20'] and abs(c - i['sma20']) / i['sma20'] < 0.015 \
                   and i['sma20_prev'] and i['sma20'] > i['sma20_prev']
        if preset == 'near_52w_low':
            return i['low60'] and c <= i['low60'] * 1.03
        if preset == 'top_gainers':
            return i['changePct'] is not None    # 全收，靠排序取前段
        # ── 空方 / 跌幅 ──
        if preset == 'top_losers':
            return i['changePct'] is not None
        if preset == 'breakdown_20':
            return i['low20'] and c < i['low20'] and i['volRatio'] and i['volRatio'] > 1.5
        if preset == 'bearish_align':
            return all([i['sma5'], i['sma20'], i['sma60']]) and i['sma5'] < i['sma20'] < i['sma60']
        if preset == 'death_cross':
            return all([i['sma20'], i['sma60'], i['sma20_prev'], i['sma60_prev']]) \
                   and i['sma20_prev'] >= i['sma60_prev'] and i['sma20'] < i['sma60']
        if preset == 'break_sma60_dn':
            return i['sma60'] and i['prev'] and i['sma60_prev'] \
                   and i['prev'] >= i['sma60_prev'] and c < i['sma60']
        if preset == 'rsi_overbought':
            return i['rsi14'] and i['rsi14'] > 75
        if preset == 'high_vol_drop':
            return i['volRatio'] and i['volRatio'] > 2 and i['prev'] and c < i['prev']
        return False

    def _handle_ai_report(self):
        """POST /ai-report — body: {apiKey, positions, watches, marketSym (optional)}"""
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length) or b'{}')
        except Exception as e:
            self._err('bad body: ' + str(e), 400); return
        api_key = body.get('apiKey', '').strip()
        if not api_key:
            self._err('apiKey required (use sk-ant-...)', 400); return
        positions = body.get('positions') or {}
        watches   = body.get('watches') or {}
        market    = body.get('marketSym') or '^TWII'
        # Build prompt
        pos_lines = []
        for code, p in positions.items():
            pos_lines.append(f"  - {code}: 進場 {p.get('entry')}、{p.get('shares')} 股、停利 {p.get('target') or '無'}、停損 {p.get('stop') or '無'}、現價 {p.get('lastPrice') or '?'}")
        watch_lines = []
        for code, w in watches.items():
            sigs = w.get('signals', []) if isinstance(w, dict) else []
            triggered = [s for s in sigs if s.get('lastEval',{}).get('status') == 'trigger']
            watch_lines.append(f"  - {code}: {len(sigs)} 訊號、{len(triggered)} 觸發")
        prompt = (
            f'你是專業台股研究分析師。請為這個人撰寫今日盤前簡報。\n\n'
            f'# 持倉清單\n' + ('\n'.join(pos_lines) if pos_lines else '  (無)') + '\n\n'
            f'# 觀察清單\n' + ('\n'.join(watch_lines) if watch_lines else '  (無)') + '\n\n'
            f'請輸出 Markdown 格式報告，含：\n'
            f'1. 📊 大盤總結（基於昨日 {market} 表現）\n'
            f'2. 💼 持倉檢視（每檔含表現、注意事項、行動建議）\n'
            f'3. 👁 觀察清單重點（觸發訊號分析）\n'
            f'4. 🎯 今日 3 大重點\n\n'
            f'語言：繁體中文、口語化、有觀點。長度約 500~800 字。\n\n'
            f'【重要】股票一律以「代號」為準（上面清單給的就是正確代號）。'
            f'提到公司名稱時務必與代號正確對應；若你不百分之百確定某代號對應的公司名稱，'
            f'就只用代號稱呼，嚴禁臆測或填入可能錯誤的名稱（例如不可把 2408 寫成旺宏）。'
        )
        # Call Anthropic API
        try:
            req_body = json.dumps({
                'model': 'claude-sonnet-4-6',
                'max_tokens': 2048,
                'messages': [{'role':'user', 'content': prompt}],
            }).encode('utf-8')
            req = urllib.request.Request(
                'https://api.anthropic.com/v1/messages',
                data=req_body,
                headers={
                    'Content-Type':       'application/json',
                    'x-api-key':          api_key,
                    'anthropic-version':  '2023-06-01',
                },
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
            text = ''
            for block in data.get('content', []):
                if block.get('type') == 'text':
                    text += block.get('text', '')
            self._ok(json.dumps({'ok': True, 'report': text, 'model': data.get('model')}).encode())
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8', 'replace')
            self._err(f'Anthropic API HTTP {e.code}: {err_body[:500]}', 502)
        except Exception as e:
            self._err('AI report failed: ' + str(e), 500)

    # ── Alert daemon endpoints (v3.8) ──────────────────────
    def _read_json_body(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length > 0 else b'{}'
        return json.loads(body.decode('utf-8'))

    def _alert_status(self):
        if not alert_daemon:
            self._err('alert daemon unavailable', 503); return
        self._ok(json.dumps(alert_daemon.status(), ensure_ascii=False).encode())

    def _alert_get_rules(self):
        if not alert_daemon:
            self._err('alert daemon unavailable', 503); return
        self._ok(json.dumps(alert_daemon.load_rules(), ensure_ascii=False).encode())

    def _alert_post_rules(self):
        if not alert_daemon:
            self._err('alert daemon unavailable', 503); return
        try:
            rules = self._read_json_body()
            if not isinstance(rules, list):
                self._err('rules must be a list', 400); return
            alert_daemon.save_rules(rules)
            self._ok(json.dumps({'ok': True, 'count': len(rules)}).encode())
        except Exception as e:
            self._err('save rules failed: ' + str(e), 500)

    def _alert_get_config(self):
        if not alert_daemon:
            self._err('alert daemon unavailable', 503); return
        cfg = alert_daemon.load_config()
        # 遮蔽敏感欄位
        safe = json.loads(json.dumps(cfg))
        if safe.get('telegram', {}).get('bot_token'):
            safe['telegram']['bot_token'] = '***set***'
        if safe.get('email', {}).get('app_password'):
            safe['email']['app_password'] = '***set***'
        self._ok(json.dumps(safe, ensure_ascii=False).encode())

    def _alert_post_config(self):
        if not alert_daemon:
            self._err('alert daemon unavailable', 503); return
        try:
            incoming = self._read_json_body()
            cur = alert_daemon.load_config()
            # 合併：'***set***' 代表前端沒改，保留原值
            for sect in ('telegram', 'email'):
                if isinstance(incoming.get(sect), dict):
                    for k, v in incoming[sect].items():
                        if v == '***set***':
                            continue
                        cur.setdefault(sect, {})[k] = v
                    incoming.pop(sect)
            cur.update(incoming)
            alert_daemon.save_config(cur)
            if cur.get('enabled') and alert_daemon:
                alert_daemon.start()
            self._ok(json.dumps({'ok': True}).encode())
        except Exception as e:
            self._err('save config failed: ' + str(e), 500)

    def _alert_test(self):
        if not alert_daemon:
            self._err('alert daemon unavailable', 503); return
        try:
            cfg = alert_daemon.load_config()
            ok, results = alert_daemon.notify(cfg, '✅ Stock Terminal 測試推播 — 設定成功', '測試')
            self._ok(json.dumps({'ok': ok, 'results': results}, ensure_ascii=False).encode())
        except Exception as e:
            self._err('test push failed: ' + str(e), 500)

    def _etf_report_email(self):
        """POST /etf-report/email — 伺服器自建富文字 HTML 報表並用已設定 Email 寄出"""
        if not alert_daemon:
            self._err('alert daemon unavailable', 503); return
        try:
            mode = 'full'
            try:
                mode = (self._read_json_body() or {}).get('mode', 'full')
            except Exception:
                pass
            # 自抓 /etf-delta
            with urllib.request.urlopen(f'http://localhost:{PORT}/etf-delta', timeout=30) as r:
                delta = json.loads(r.read())
            if delta.get('error'):
                self._err('etf-delta error: ' + str(delta.get('error')), 502); return
            if etf_report:
                subject, html = etf_report.build_report_html(delta, mode)
                text = etf_report.build_report_text(delta)
            else:
                subject, html, text = 'ETF 報表', None, json.dumps(delta)[:2000]
            cfg = alert_daemon.load_config()
            ok, msg = alert_daemon.push_email(cfg, subject, text, html=html)
            if ok:
                alert_daemon._log('ETF report emailed: ' + subject)
            self._ok(json.dumps({'ok': ok, 'results': {'email': msg}}, ensure_ascii=False).encode())
        except Exception as e:
            self._err('email report failed: ' + str(e), 500)

    def _handle_txf(self):
        """台指期近一(含夜盤) — 主: Yahoo TW 期貨頁(WTX&) 內嵌 JSON；備援: TAIFEX MIS。
           回 {ok, price, prevClose, changePct, name, source}；失敗回 debug 供修正。"""
        import re as _re2
        key = f'txf:{int(time.time() // 20)}'   # 20s 快取
        c = _cache.get(key)
        if c is not None:
            self._ok(c); return

        # ── 主來源：Yahoo TW 期貨頁 WTX&（使用者指定）──
        try:
            url = 'https://tw.stock.yahoo.com/future/WTX&'
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                'Accept-Language': 'zh-TW,zh;q=0.9',
            })
            with urllib.request.urlopen(req, timeout=12) as resp:
                html = resp.read().decode('utf-8', 'replace')

            # 頁面 SSR；台指期主報價用「成交/昨收/漲幅」標籤(相對行情表的上市大盤
            # 用「價位/漲跌(%)」不同標籤)，故去標籤後抓這些就不會抓到大盤。
            txt = _re2.sub(r'<[^>]+>', ' ', html)
            txt = txt.replace(' ', ' ')

            def near(label, text):
                # label 後面(可跨空白/標點)第一個帶兩位小數的數字
                m = _re2.search(label + r'[^\d\-]{0,12}([\d,]+\.\d{2})', text)
                if m:
                    try: return float(m.group(1).replace(',', ''))
                    except: pass
                return None

            price = near('成交', txt)
            prev = near('昨收', txt)
            mpct = _re2.search(r'漲幅[^\d\-]{0,12}([\d.]+)\s*%', txt)
            pctmag = float(mpct.group(1)) if mpct else None
            chg = None
            if price is not None and prev:
                chg = (price - prev) / prev * 100          # 帶正負號
            elif pctmag is not None and price is not None and prev:
                chg = pctmag * (1 if price >= prev else -1)
            if price is not None:
                out = {'ok': True, 'price': price, 'prevClose': prev, 'changePct': chg,
                       'name': '台指期近一', 'source': 'yahoo-tw'}
                body = json.dumps(out, ensure_ascii=False).encode()
                _cache.set(key, body); self._ok(body); return
            yahoo_debug = {'price_label_hit': price, 'prev_label_hit': prev,
                           'has_成交': '成交' in txt, 'has_昨收': '昨收' in txt,
                           'sample': txt[txt.find('台指期近一'): txt.find('台指期近一') + 400] if '台指期近一' in txt else txt[:300]}
        except Exception as e:
            yahoo_debug = {'yahoo_error': str(e)}

        # ── 備援：TAIFEX MIS ──
        try:
            url = 'https://mis.taifex.com.tw/futures/api/getQuoteList'
            payload = json.dumps({'MarketType': '0', 'SymbolType': 'F', 'KindID': '1', 'CID': 'TXF',
                                  'ExpireMonth': '', 'RowSize': '全部', 'PageNo': '', 'SortColumn': '', 'AscDesc': 'A'}).encode('utf-8')
            req = urllib.request.Request(url, data=payload, method='POST', headers={
                'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0',
                'Origin': 'https://mis.taifex.com.tw', 'Referer': 'https://mis.taifex.com.tw/futures/'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            rows = (data.get('RtData') or {}).get('QuoteList') or []
            if rows:
                def fnum(d, *keys):
                    for k in keys:
                        v = d.get(k)
                        if v not in (None, '', '-'):
                            try: return float(str(v).replace(',', '').replace('%', ''))
                            except: pass
                    return None
                row = rows[0]
                price = fnum(row, 'CLastPrice', 'CLast', 'LastPrice')
                prev = fnum(row, 'CRefPrice', 'CYDClose', 'RefPrice')
                chg = fnum(row, 'CDiffRate', 'DiffRate')
                if chg is None and price is not None and prev:
                    chg = (price - prev) / prev * 100
                if price is not None:
                    out = {'ok': True, 'price': price, 'prevClose': prev, 'changePct': chg,
                           'name': row.get('DispCName') or '台指期', 'source': 'taifex'}
                    body = json.dumps(out, ensure_ascii=False).encode()
                    _cache.set(key, body); self._ok(body); return
        except Exception as e:
            yahoo_debug['taifex_error'] = str(e)

        self._ok(json.dumps({'ok': False, 'error': '兩來源皆無法解析', 'debug': yahoo_debug}, ensure_ascii=False).encode())

    # ── WATCH 後端偵測端點 (v3.8) ──────────────────────────
    def _watch_status(self):
        if not watch_daemon:
            self._err('watch daemon unavailable', 503); return
        self._ok(json.dumps(watch_daemon.status(), ensure_ascii=False).encode())

    def _watch_post_rules(self):
        if not watch_daemon:
            self._err('watch daemon unavailable', 503); return
        try:
            rules = self._read_json_body()
            if not isinstance(rules, dict):
                self._err('rules must be an object', 400); return
            watch_daemon.save_rules(rules)
            self._ok(json.dumps({'ok': True, 'count': len(rules)}).encode())
        except Exception as e:
            self._err('save watch rules failed: ' + str(e), 500)

    def _watch_post_config(self):
        if not (watch_daemon and alert_daemon):
            self._err('watch/alert daemon unavailable', 503); return
        try:
            inc = self._read_json_body()
            cur = alert_daemon.load_config()
            if 'enabled' in inc:
                cur['watch_enabled'] = bool(inc['enabled'])
            if 'poll_seconds' in inc:
                cur['watch_poll_seconds'] = int(inc['poll_seconds'])
            alert_daemon.save_config(cur)
            if cur.get('watch_enabled'):
                watch_daemon.start()
            self._ok(json.dumps({'ok': True, 'watch_enabled': cur.get('watch_enabled')}).encode())
        except Exception as e:
            self._err('save watch config failed: ' + str(e), 500)

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
    if alert_daemon:
        try:
            _ac = alert_daemon.load_config()
            if _ac.get('enabled'):
                alert_daemon.start()
                print('[alert] daemon started (poll %ss)' % _ac.get('poll_seconds', 60))
            else:
                print('[alert] daemon idle (enable in alert_config.json or UI)')
            if watch_daemon and _ac.get('watch_enabled'):
                watch_daemon.start()
                print('[watch] daemon started (poll %ss)' % _ac.get('watch_poll_seconds', 300))
        except Exception as _e:
            print('[alert] start failed:', _e)
    ThreadingHTTPServer(('localhost', PORT), Handler).serve_forever()
