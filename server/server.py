#!/usr/bin/env python3
"""Stock Terminal local server — ThreadingHTTPServer + ThreadPoolExecutor + LRU cache + ETF Delta
   Tuned for GMKtec EVO-T1 (Core Ultra 9 285H / 96GB DDR5 / RTX 5080).
"""
import os, json, urllib.request, urllib.error, socketserver, glob, time, subprocess, sys, csv, io
from http.server import HTTPServer, SimpleHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import OrderedDict
from urllib.parse import urlparse, parse_qs, unquote, quote
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
    print('[etf-report] etf_report unavailable — using etf_report_lite (no pandas)')
try:
    import watch_daemon
except Exception as _e:
    watch_daemon = None
    print('[watch] daemon import failed:', _e)
try:
    import ai_local
except Exception as _e:
    ai_local = None
    print('[ai-local] module import failed:', _e)

from ai_api import (
    anthropic_messages as _anthropic_messages,
    load_ai_key as _load_ai_key,
)
from ai_routes import AiRoutesMixin
from etf_api import (
    find_etf_dir,
    list_etf_files,
)
from etf_routes import EtfRoutesMixin

PORT = 18432
# Core Ultra 9 285H = 6P + 8E + 2LP = 16 threads; oversubscribe for I/O-bound YF
MAX_WORKERS = max(32, (os.cpu_count() or 16) * 2)
LRU_MAX = 20000  # 96GB RAM → very generous cache

# ── 專案根目錄 ──
# 凍結成 .exe(PyInstaller)時用 exe 所在資料夾;一般執行(server/ 下)時用其上一層。
if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── Chip history (v3.8): 每日法人籌碼快照，用於連續買賣超天數 ──
CHIP_HISTORY_PATH = os.path.join(_BASE, 'data', 'chip_history')

# v3.9 P3: 畫線雲端記憶 — 存 draw_store.json {sym: [obj,...]}（gitignore）
DRAW_STORE_FILE = os.path.join(_BASE, 'data', 'draw_store.json')
_draw_lock = threading.Lock()
def _load_draw_store():
    try:
        with open(DRAW_STORE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}
def _save_draw_store(d):
    with open(DRAW_STORE_FILE, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False)

# v3.9 P4: 總經數據 — 美國走 FRED「免 API key」公開 CSV 下載端點 (fredgraph.csv)。
#   台灣 CPI 走 FRED 的 OECD 序列(避開 .tw 直連)；景氣對策信號走國發會 best-effort。
_macro_cache = {}   # {series_key: payload_bytes}
_macro_fail_until = {}  # series_key -> unix ts；失敗後短暫跳過，避免 /pulse 反覆卡死
MACRO_SERIES = {
    'us10y':            {'p': 'fred', 'id': 'DGS10',             'label': '美國10年期公債殖利率', 'unit': '%'},
    'us2y':             {'p': 'fred', 'id': 'DGS2',              'label': '美國2年期公債殖利率',  'unit': '%'},
    'spread10y2y':      {'p': 'fred', 'id': 'T10Y2Y',           'label': '美10Y-2Y利差(倒掛<0)', 'unit': '%'},
    'us_cpi':           {'p': 'fred', 'id': 'CPIAUCSL',          'label': '美國CPI指數',          'unit': ''},
    'us_cpi_yoy':       {'p': 'fred', 'id': 'CPALTT01USM659N',   'label': '美國CPI年增率(YoY)',   'unit': '%'},
    'fedfunds':         {'p': 'fred', 'id': 'FEDFUNDS',          'label': '美國聯邦基金利率',     'unit': '%'},
    'unrate':           {'p': 'fred', 'id': 'UNRATE',            'label': '美國失業率',           'unit': '%'},
    'baml_ig':          {'p': 'fred', 'id': 'BAMLCC0A0CMTRIV',   'label': '美林投資級公司債總報酬', 'unit': 'Index'},
    'baml_hy':          {'p': 'fred', 'id': 'BAMLHY0A0HYMTRIV',   'label': '美林高收益公司債總報酬', 'unit': 'Index'},
    'tw_discount_rate': {'p': 'fred', 'id': 'INTDSRTWM193N',     'label': '台灣央行重貼現率',     'unit': '%'},
    # CBC 利率走廊（種子／官網；FRED INTDSRTWM193N 已 404）
    'tw_discount':      {'p': 'cbc',  'id': 'discount',          'label': '台灣重貼現率',         'unit': '%'},
    'tw_secured_rate':  {'p': 'cbc',  'id': 'secured',           'label': '台灣擔保放款融通利率', 'unit': '%'},
    'tw_short_rate':    {'p': 'cbc',  'id': 'short',             'label': '台灣短期融通利率',     'unit': '%'},
    'tw_cpi':           {'p': 'twcpi',                           'label': '台灣CPI指數',          'unit': ''},
    'tw_light':         {'p': 'ndc',                             'label': '台灣景氣對策信號(分數)', 'unit': '分'},
}

def _fetch_fred_csv(series_id, cosd, timeout=8, retries=1):
    """FRED 免 key CSV：https://fred.stlouisfed.org/graph/fredgraph.csv?id=ID&cosd=YYYY-MM-DD
       回 [{date, value}]；缺值以 '.' 表示，略過。
       timeout/retries 可調：/pulse 路徑用短逾時，避免單源拖垮總覽刷新。"""
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={cosd}'
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'text/csv'})
    text = None
    last_err = None
    attempts = max(1, int(retries or 1))
    to = max(2.0, float(timeout or 8))
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(req, timeout=to) as resp:
                text = resp.read().decode('utf-8', 'replace')
            break
        except Exception as e:
            last_err = e
            if attempt + 1 < attempts:
                time.sleep(0.35 * (attempt + 1))
    if text is None:
        raise last_err if last_err else RuntimeError('fred fetch failed')
    pts = []
    for ln in text.splitlines()[1:]:           # 跳過表頭
        parts = ln.split(',')
        if len(parts) < 2:
            continue
        d, v = parts[0].strip(), parts[1].strip()
        if not d or v in ('.', ''):
            continue
        try:
            pts.append({'date': d, 'value': float(v)})
        except Exception:
            pass
    return pts

_macro_debug = {}   # 解析失敗時放樣本，供前端 note 顯示給使用者

def _norm_ym(s):
    """把各種年月格式正規化成 'YYYY-MM-01'。支援 2025M05 / 114M05 / 202505 / 11405(民國) / 114年05月。"""
    s = str(s).strip()
    up = s.upper()
    if 'M' in up:
        try:
            a, b = up.split('M'); y = int(a)
            if y < 1911: y += 1911
            return f'{y:04d}-{int(b):02d}-01'
        except Exception:
            pass
    digits = ''.join(ch for ch in s if ch.isdigit())
    try:
        if len(digits) == 6:                       # YYYYMM
            return f'{int(digits[:4]):04d}-{int(digits[4:6]):02d}-01'
        if len(digits) == 5:                       # 民國 YYYMM (例 11405)
            return f'{1911 + int(digits[:3]):04d}-{int(digits[3:5]):02d}-01'
        if len(digits) == 7:                       # 民國 YYYMMM? 取前3年後2月
            return f'{1911 + int(digits[:3]):04d}-{int(digits[3:5]):02d}-01'
    except Exception:
        return None
    return None

def _http_json(url, timeout=15):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': 'application/json,text/plain,*/*',
        'Accept-Language': 'zh-TW,zh;q=0.9',
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8-sig', 'replace'))

def _http_text(url, timeout=15):
    """抓原始文字。政府 CSV 常為 Big5，依序試多種編碼。"""
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': 'text/csv,application/json,text/plain,*/*',
        'Accept-Language': 'zh-TW,zh;q=0.9',
    })
    raw = None
    last_err = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            break
        except Exception as e:
            last_err = e
            time.sleep(1.2)
    if raw is None:
        raise last_err if last_err else RuntimeError('http_text failed')
    for enc in ('utf-8-sig', 'utf-8', 'big5', 'cp950'):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode('utf-8', 'replace')

def _rows_from_text(text):
    """格式自動偵測：開頭是 [ 或 { → JSON；否則當 CSV(含表頭) 解析成 dict 陣列。"""
    if not text:
        return []
    t = text.lstrip('﻿').strip()
    if t[:1] in '[{':
        try:
            return _flatten_rows(json.loads(t))
        except Exception:
            pass
    try:
        rdr = csv.DictReader(io.StringIO(text))
        return [dict(r) for r in rdr if any((v or '').strip() for v in r.values())]
    except Exception:
        return []

def _flatten_rows(data):
    """把 data.gov.tw / 各式 JSON 攤平成 dict 陣列。"""
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        # 常見包裝：{result:{records:[...]}} / {data:[...]} / {records:[...]}
        for path in (('result', 'records'), ('result', 'distribution'), ('data',), ('records',), ('rows',)):
            cur = data
            ok = True
            for p in path:
                if isinstance(cur, dict) and p in cur:
                    cur = cur[p]
                else:
                    ok = False; break
            if ok and isinstance(cur, list):
                return [r for r in cur if isinstance(r, dict)]
        # 退而求其次：第一個 list 值
        for v in data.values():
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
        return [data]
    return []

def _pick_field(row, prefer_substrs):
    """回傳第一個 key 含 prefer_substrs 任一子字串的 key。"""
    for sub in prefer_substrs:
        for k in row:
            if sub.lower() in str(k).lower():
                return k
    return None

_DATEK = ('年月', '日期', '時間', '月份', '期間', 'date', 'period', 'yyyymm', 'ym')

def _parse_macro_rows(rows, valkeys, months=0):
    """共用：rows(dict陣列) → [{date,value}]。valkeys=值欄位優先子字串清單(可多組)。"""
    if not rows:
        return [], None
    dk = _pick_field(rows[0], _DATEK)
    vk = None
    for group in valkeys:
        vk = _pick_field(rows[0], group)
        if vk:
            break
    if not dk or not vk:
        return [], f'keys={list(rows[0].keys())[:14]}'
    pts = []
    for r in rows:
        d = _norm_ym(r.get(dk))
        try:
            v = float(str(r.get(vk)).replace(',', '').strip())
        except Exception:
            continue
        if d:
            pts.append({'date': d, 'value': v})
    pts.sort(key=lambda x: x['date'])
    if months and len(pts) > months:
        pts = pts[-months:]
    return pts, (None if pts else f'keys={list(rows[0].keys())[:14]} sample={str(rows[0])[:240]}')

def _fetch_tw_cpi(months=120):
    """台灣 CPI — 政府資料開放平台固定轉導 (GET，格式自動偵測 JSON/CSV)。
       值優先總指數/指數，否則年增率。"""
    urls = ['https://quality.data.gov.tw/dq_download_json.php?nid=8001&md5_url=6b895696ff0a7f14b3017a048a1ad39c',
            'https://quality.data.gov.tw/dq_download_csv.php?nid=8001&md5_url=6b895696ff0a7f14b3017a048a1ad39c']
    last = None
    for url in urls:
        try:
            rows = _rows_from_text(_http_text(url))
            pts, dbg = _parse_macro_rows(rows, [('總指數', 'CPI', '指數'), ('年增率', '漲跌', 'value')], months)
            if pts:
                return pts
            last = dbg or 'empty'
        except Exception as e:
            last = 'ERR ' + str(e)
    _macro_debug['tw_cpi'] = last or '(無回應)'
    return []

def _fetch_tw_light():
    """台灣景氣對策信號(分數) — 國發會開放資料專區 (GET CSV/JSON，格式自動偵測)。
       主：wd.ndc.gov.tw/ndc/opendata/ndc0101.csv；備援：.json、data.gov.tw dataset 6334。"""
    candidates = ['https://wd.ndc.gov.tw/ndc/opendata/ndc0101.csv',
                  'https://wd.ndc.gov.tw/ndc/opendata/ndc0101.json']
    # 動態備援：data.gov.tw dataset 6334 當前資源
    try:
        meta = _http_json('https://data.gov.tw/api/v2/rest/dataset/6334', timeout=12)
        res = (meta.get('result') if isinstance(meta, dict) else None) or {}
        for d in (res.get('distribution') or res.get('resources') or []):
            u = d.get('resourceDownloadUrl') or d.get('downloadUrl') or d.get('url') or ''
            if u:
                candidates.append(u)
    except Exception:
        pass
    valkeys = [('對策信號分數', '景氣對策信號', '綜合分數', '分數', 'score', 'light')]
    last = None
    for url in candidates:
        try:
            rows = _rows_from_text(_http_text(url))
            pts, dbg = _parse_macro_rows(rows, valkeys)
            if pts:
                return pts
            last = dbg or 'empty'
        except Exception as e:
            last = 'ERR ' + str(e)
    _macro_debug['tw_light'] = last or '(無回應)'
    return []

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
def _round_px(p):
    """台股價格進位:< NT$50 保留 2 位小數(tick 0.01/0.05),>= 50 進到 1 位
       (高價 tick 較大,自然顯示為整數);順便去除浮點雜訊。"""
    try:
        p = float(p)
    except (TypeError, ValueError):
        return p
    return round(p, 2 if p < 50 else 1)


def _db_screener_arrays(code):
    """v4.0:從本機時序 DB(datastore)取該檔 (closes,highs,lows,vols) 供選股用。
       無資料或不足 70 根 → 回 None,讓呼叫端退回 Yahoo(DB 空時零行為差異)。"""
    try:
        import datastore
        rows = datastore.get_bars(str(code))
    except Exception:
        return None
    if not rows or len(rows) < 70:
        return None
    closes, highs, lows, vols = [], [], [], []
    for _ts, _o, _h, _l, _c, _v in rows:
        if _c is None:
            continue
        closes.append(_c)
        highs.append(_h if _h is not None else _c)
        lows.append(_l if _l is not None else _c)
        vols.append(_v if _v is not None else 0)
    if len(closes) < 70:
        return None
    return closes, highs, lows, vols


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

# ── 台股 code → 中文名 對照(快取一天)。Yahoo shortName 多為英文，改顯示中文簡稱 ──
_TW_NAMES = {'date': None, 'map': {}}
def _get_tw_names():
    from datetime import date as _date
    today = _date.today().strftime('%Y%m%d')
    if _TW_NAMES['date'] == today and _TW_NAMES['map']:
        return _TW_NAMES['map']
    
    m = {}
    # ── 本地備份讀取防線 ────────────────────────────────────
    # 優先載入上次成功儲存的名稱對照表，確保即使 OpenAPI 斷連或限流，依然有完整的股票代號可用
    data_dir = os.path.join(_BASE, 'data')
    backup_path = os.path.join(data_dir, 'tw_names_backup.json')
    if os.path.exists(backup_path):
        try:
            with open(backup_path, 'r', encoding='utf-8') as f:
                m = json.load(f)
        except Exception:
            pass

    def scan(url, code_keys, name_keys):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=20) as r:
                arr = json.loads(r.read())
            for row in arr:
                if not isinstance(row, dict):
                    continue
                code = ''
                for k in code_keys:
                    if row.get(k):
                        code = str(row[k]).strip(); break
                if not _CODE4.match(code):
                    for v in row.values():
                        s = str(v).strip()
                        if _CODE4.match(s):
                            code = s; break
                if not _CODE4.match(code):
                    continue
                name = ''
                for k in name_keys:
                    if row.get(k):
                        name = str(row[k]).strip(); break
                # 只收含中文字的名稱(濾掉英文/代號重複)
                if name and code not in m and any('一' <= ch <= '鿿' for ch in name):
                    m[code] = name
        except Exception as e:
            print(f'[names] scan failed {url}: {e}')

    scan('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL', ('Code',), ('Name', '名稱', '證券名稱'))
    scan('https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes',
         ('SecuritiesCompanyCode', 'Code', 'CompanyCode', '公司代號'),
         ('CompanyName', 'SecuritiesCompanyName', '公司名稱', '公司簡稱', 'Name', '名稱'))
    for ds in ('t187ap05_L', 't187ap05_O'):
        scan(f'https://openapi.twse.com.tw/v1/opendata/{ds}', ('公司代號', 'Code'), ('公司名稱', '公司簡稱', 'Name'))
    
    if m:
        # ── 「只增不減」安全覆寫 ──────────────────────────────
        # 只有在新掃描後的資料總數大於等於舊備份時才寫入，防範部分 API 失敗導致備份檔萎縮
        try:
            old_count = 0
            if os.path.exists(backup_path):
                with open(backup_path, 'r', encoding='utf-8') as f:
                    old_count = len(json.load(f))
            if len(m) >= old_count:
                os.makedirs(data_dir, exist_ok=True)
                with open(backup_path, 'w', encoding='utf-8') as f:
                    json.dump(m, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print('[names] backup save failed:', e)
            
        _TW_NAMES['date'] = today; _TW_NAMES['map'] = m
    return m


def _safe_sym(s):
    # 安全(v3.9 review):股票代號白名單,防止把惡意字元(/ @ : ? #)串進 Yahoo URL(SSRF)。
    # 允許:英數 + 指數/期貨/市場常見符號 . ^ = - % _(如 ^TWII、GC=F、2330.TW、%5ETWOII)。
    if not s or len(s) > 20:
        return False
    return all(c.isalnum() or c in '.^=-%_' for c in s)


# ── 個股期貨(含夜盤) 整批載入 (v3.9)：CID='' 一次抓全部，避免每檔打 MIS 被限流(520) ──
#   日盤 MarketType=0(期貨 -F/現貨 -S)、夜盤 MarketType=1(期貨 -M)。快取 45 秒。
_MIS_FUT = {'ts': 0, 'map': {}}
def _mis_load_futures():
    now = time.time()
    if _MIS_FUT['map'] and (now - _MIS_FUT['ts'] < 45):
        return _MIS_FUT['map']
    def all_rows(mt):
        payload = json.dumps({'MarketType': mt, 'SymbolType': 'F', 'KindID': '4', 'CID': '',
                              'ExpireMonth': '', 'RowSize': '全部', 'PageNo': '', 'SortColumn': '', 'AscDesc': 'A'}).encode('utf-8')
        last = None
        for _ in range(3):
            try:
                req = urllib.request.Request('https://mis.taifex.com.tw/futures/api/getQuoteList', data=payload, method='POST',
                    headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0',
                             'Origin': 'https://mis.taifex.com.tw', 'Referer': 'https://mis.taifex.com.tw/futures/'})
                with urllib.request.urlopen(req, timeout=12) as resp:
                    return (json.loads(resp.read()).get('RtData') or {}).get('QuoteList') or []
            except Exception as e:
                last = e; time.sleep(1.2)
        print(f'[stockfut] MIS load mt={mt} failed: {last}')
        return []
    day = all_rows('0'); night = all_rows('1')
    m = {}
    def sid(r): return str(r.get('SymbolID') or '')
    def ens(c): return m.setdefault(c, {})
    for r in day:
        s = sid(r)
        if s.endswith('-S'): ens(s[:-2])['daySpot'] = r          # 現貨 = CID-S
        elif s.endswith('-F'):
            c = s.split('-')[0][:-2]                              # 期貨 = CID+月年+-F → 去尾2碼=CID
            d = ens(c)
            if 'dayFut' not in d: d['dayFut'] = r                 # 第一筆=近月
    for r in night:
        s = sid(r)
        if s.endswith('-M'):
            c = s.split('-')[0][:-2]
            d = ens(c)
            if 'nightFut' not in d: d['nightFut'] = r
    if m:
        _MIS_FUT['ts'] = now; _MIS_FUT['map'] = m
    return m

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
    """從 TWSE/TPEx OpenAPI 全市場資料集找某股。資料集整批快取一天。
       dataset 名稱規則 (v3.8.1)：
         'XXX'            → https://openapi.twse.com.tw/v1/opendata/XXX  (舊行為)
         'exchangeReport/XXX' 等含 '/' → https://openapi.twse.com.tw/v1/<原樣>
         'tpex:XXX'       → https://www.tpex.org.tw/openapi/v1/XXX (上櫃)
       代號欄位同時認 中文(公司代號/證券代號) 與 英文(Code/SecuritiesCompanyCode)。"""
    from datetime import date as _date
    today = _date.today().strftime('%Y%m%d')
    for ds in dataset_names:
        cached = _openapi_ds.get(ds)
        if not cached or cached[0] != today:
            try:
                if ds.startswith('tpex:'):
                    url = f'https://www.tpex.org.tw/openapi/v1/{ds[5:]}'
                elif '/' in ds:
                    url = f'https://openapi.twse.com.tw/v1/{ds}'
                else:
                    url = f'https://openapi.twse.com.tw/v1/opendata/{ds}'
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    arr = json.loads(resp.read())
                idx = {}
                for row in arr:
                    code = (row.get('公司代號') or row.get('證券代號') or
                            row.get('Code') or row.get('SecuritiesCompanyCode') or
                            row.get('股票代號') or '').strip()
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

def _openapi_lookup_list(dataset_name):
    """回傳 TWSE OpenAPI 整個資料集 array（快取一天）。給事件行事曆等需整表掃描者用。"""
    from datetime import date as _date
    today = _date.today().strftime('%Y%m%d')
    cache_key = f'__list__{dataset_name}'
    cached = _openapi_ds.get(cache_key)
    if cached and cached[0] == today:
        return cached[1]
    try:
        url = f'https://openapi.twse.com.tw/v1/opendata/{dataset_name}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            arr = json.loads(resp.read())
        if not isinstance(arr, list):
            arr = []
        _openapi_ds[cache_key] = (today, arr)
        return arr
    except Exception as e:
        print(f'[openapi-list] {dataset_name} failed: {e}')
        _openapi_ds[cache_key] = (today, [])
        return []


# ── MOPS 公開資訊觀測站 月營收(補上櫃:官方 OpenAPI 無 per-company 上櫃端點) ──
_mops_rev_cache = {}   # market('otc'/'sii') -> (yyyymmdd, period('11505'), {code: {...}})
_MOPS_TR = _re.compile(r'<tr[^>]*>(.*?)</tr>', _re.I | _re.S)
_MOPS_TD = _re.compile(r'<td[^>]*>(.*?)</td>', _re.I | _re.S)
_MOPS_TAG = _re.compile(r'<[^>]+>')


def _mops_cell(s):
    s = _MOPS_TAG.sub('', s or '')
    return s.replace('&nbsp;', '').replace('　', '').replace('\xa0', '').strip()


def _parse_mops_t21sc03(html):
    """解析 MOPS 月營收彙總表(t21sc03)。資料列以 4 碼代號開頭;數字欄為 ASCII,
    即使 Big5 解碼把中文名弄亂,代號與數值仍可靠。
    欄序:0代號 1名稱 2當月營收 3上月營收 4去年當月 5上月增減% 6去年同月增減%
          7當月累計 8去年累計 9前期比較增減% 10備註(千元)。"""
    out = {}
    for tr in _MOPS_TR.findall(html):
        cells = [_mops_cell(c) for c in _MOPS_TD.findall(tr)]
        if len(cells) < 10:
            continue
        code = cells[0]
        if not _re.match(r'^\d{4}$', code):
            continue

        def gn(i):
            if i >= len(cells):
                return None
            t = cells[i].replace(',', '').replace('%', '').strip()
            if t in ('', '--', '---', 'N/A', '不適用'):
                return None
            try:
                return float(t)
            except Exception:
                return None
        out[code] = {'monthRev': gn(2), 'momPct': gn(5), 'yoyPct': gn(6),
                     'cumRev': gn(7), 'cumYoyPct': gn(9)}
    return out


def _mops_monthly_revenue(market, clean_code):
    """MOPS 月營收(market:'otc'上櫃 / 'sii'上市)。整批快取一天;往回找最近一個
    已公布月份(約次月 10 日)。回傳該股 dict 或 None。"""
    from datetime import date as _date
    today = _date.today().strftime('%Y%m%d')
    cached = _mops_rev_cache.get(market)
    if not cached or cached[0] != today:
        idx, period = {}, None
        y, mo = _date.today().year, _date.today().month
        done = False
        for _back in range(0, 4):
            yy, mm = y, mo - _back
            while mm <= 0:
                mm += 12; yy -= 1
            rocy = yy - 1911
            for host in ('https://mopsov.twse.com.tw', 'https://mops.twse.com.tw'):
                url = f'{host}/nas/t21/{market}/t21sc03_{rocy}_{mm}_0.html'
                try:
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=20) as resp:
                        raw = resp.read()
                    rows = _parse_mops_t21sc03(raw.decode('big5', 'replace'))
                    if rows:
                        idx, period = rows, f'{rocy}{mm:02d}'; done = True
                        break
                except Exception:
                    continue
            if done:
                break
        _mops_rev_cache[market] = (today, period, idx)
        cached = _mops_rev_cache[market]
    row = cached[2].get(clean_code)
    if row:
        row = dict(row); row['period'] = cached[1]
    return row

def _fundamental_score(out):
    """0~100 基本面分數：成長性 50% + 獲利性 50%。

    成長性：單月 YoY、累計 YoY — 用 tanh 軟飽和（避免 YoY 55% 直接頂到 100）。
      0%→50、±20%≈73/27、±50%≈88/12
    獲利性：營業利益率、稅後淨利率（可選毛利率）— margin%×3，約 33%→100。
    """
    import math
    rev = out.get('revenue') or {}
    inc = out.get('income') or {}

    def soft_growth(pct):
        try:
            return max(0.0, min(100.0, 50.0 + 50.0 * math.tanh(float(pct) / 40.0)))
        except Exception:
            return None

    def margin_score(m):
        try:
            return max(0.0, min(100.0, float(m) * 3.0))
        except Exception:
            return None

    growth = []
    if rev.get('yoyPct') is not None:
        g = soft_growth(rev['yoyPct'])
        if g is not None:
            growth.append(g)
    if rev.get('cumYoyPct') is not None:
        g = soft_growth(rev['cumYoyPct'])
        if g is not None:
            growth.append(g)

    profit = []
    for key in ('opMargin', 'netMargin', 'grossMargin'):
        if inc.get(key) is not None:
            m = margin_score(inc[key])
            if m is not None:
                profit.append(m)

    if not growth and not profit:
        return None
    if growth and profit:
        return round(0.5 * (sum(growth) / len(growth)) + 0.5 * (sum(profit) / len(profit)))
    parts = growth or profit
    return round(sum(parts) / len(parts))


def _is_index_sym(sym: str) -> bool:
    """任一市場指數代號（^ 開頭或常見別名）。"""
    s = (sym or '').strip().upper()
    return s.startswith('^') or s in ('TWII', 'TWOII', 'TAIEX')


def _is_tw_index_sym(sym: str) -> bool:
    """台股大盤指數（可走大盤體質評分）。美股 ^GSPC 等不可誤套。"""
    s = (sym or '').strip().upper().replace('.TW', '').replace('.TWO', '')
    return s in ('^TWII', '^TWOII', 'TWII', 'TWOII', 'TAIEX', '^TAIEX')


def _is_macro_sym(sym: str) -> bool:
    s = (sym or '').strip().upper()
    return s.startswith('__') and s.endswith('__')


def _is_tw_market_fund_sym(sym: str) -> bool:
    """可計算「大盤體質」的代號：台指／融資維持／台股合成序列。
       融資週期（__TW_MARGIN_CYCLE__）為獨立指標，不含在內。"""
    s = (sym or '').strip().upper().replace('.TW', '').replace('.TWO', '')
    if s in ('__TW_MARGIN_CYCLE__', '__MARGIN_CYCLE__'):
        return False
    if _is_tw_index_sym(s):
        return True
    if s in ('__MARGIN_RATIO__', '__MARGIN__'):
        return True
    if s.startswith('__TW_') and s.endswith('__'):
        return True
    return False


def _universe_median_pe():
    """從 data/universe.json twmeta 算上市櫃本益比中位數（濾掉異常）。"""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'universe.json')
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        pes = []
        for _code, m in (data.get('twmeta') or {}).items():
            if not isinstance(m, dict):
                continue
            pe = m.get('pe')
            try:
                pe = float(pe)
            except Exception:
                continue
            if 3 <= pe <= 80:
                pes.append(pe)
        if not pes:
            return None
        pes.sort()
        return round(pes[len(pes) // 2], 2)
    except Exception as e:
        print('[market-fund] median PE failed:', e)
        return None


def _score_tw_market(mf: dict, margin_meta: dict, median_pe) -> tuple:
    """大盤體質 0~100：量能 25% + 法人 25% + 融資安全 25% + 估值 25%。"""
    import math
    parts = []
    detail = {}

    # 量能：成交金額（元）— 8000億中性、1.2兆偏熱
    turns = (mf or {}).get('turnover') or []
    amt = turns[-1]['amount'] if turns else None
    if amt is not None:
        yi = float(amt) / 1e8  # 億
        # 400億→弱、8000億→50、12000億→高
        vol_sc = max(0.0, min(100.0, 50.0 + 50.0 * math.tanh((yi - 8000.0) / 4000.0)))
        parts.append(vol_sc)
        detail['turnoverYi'] = round(yi, 1)
        detail['volumeScore'] = round(vol_sc, 1)

    # 法人：外資+投信+自營 買賣差（元）— 以 ±300億 作軟飽和
    inst = (mf or {}).get('inst') or {}
    net = 0.0
    n_have = 0
    for k in ('foreign', 'trust', 'dealer'):
        if inst.get(k) is not None:
            net += float(inst[k])
            n_have += 1
    if n_have:
        yi_net = net / 1e8
        inst_sc = max(0.0, min(100.0, 50.0 + 50.0 * math.tanh(yi_net / 300.0)))
        parts.append(inst_sc)
        detail['instNetYi'] = round(yi_net, 1)
        detail['instScore'] = round(inst_sc, 1)

    # 融資維持率：越高越安全（相對 166% 中性；130% 危險）
    cur = (margin_meta or {}).get('current')
    if cur is not None:
        # 130→~15、150→~35、166→50、180→~65、200→~80
        m_sc = max(0.0, min(100.0, 50.0 + 50.0 * math.tanh((float(cur) - 166.0) / 30.0)))
        parts.append(m_sc)
        detail['marginRatio'] = round(float(cur), 2)
        detail['marginScore'] = round(m_sc, 1)
        rz = (margin_meta or {}).get('riskZone')
        if rz:
            detail['riskZone'] = rz.get('label')

    # 估值：全市場本益比中位數 — 越低越好（12→高分、25→中、40→低）
    if median_pe is not None:
        pe_sc = max(0.0, min(100.0, 50.0 - 50.0 * math.tanh((float(median_pe) - 18.0) / 12.0)))
        parts.append(pe_sc)
        detail['medianPE'] = median_pe
        detail['valuationScore'] = round(pe_sc, 1)

    if not parts:
        return None, detail
    return round(sum(parts) / len(parts)), detail


def _build_tw_market_fundamental(sym: str) -> dict:
    """^TWII / ^TWOII / __MARGIN_RATIO__ 大盤體質評分 payload。"""
    from datetime import date as _date
    today = _date.today().strftime('%Y%m%d')
    clean = (sym or '').replace('.TW', '').replace('.TWO', '').strip().upper()
    out = {
        'symbol': sym,
        'code': clean,
        'date': today,
        'market': 'TW',
        'kind': 'market',
        'title': '大盤體質',
        'revenue': None,
        'income': None,
        'score': None,
        'pillars': None,
        '_source': 'TWSE marketflow + margin + universe PE',
    }
    # 重用 /marketflow 快取
    mf = None
    try:
        key = f'marketflow:{_date.today().strftime("%Y-%m-%d")}'
        # marketflow cache key uses Y-m-d in handler... check: key = f'marketflow:{today.strftime("%Y-%m-%d")}'
        cached = _cache.get(f'marketflow:{_date.today().strftime("%Y-%m-%d")}')
        if cached:
            mf = json.loads(cached.decode('utf-8') if isinstance(cached, (bytes, bytearray)) else cached)
    except Exception:
        mf = None
    if mf is None:
        # 輕量同步抓（與 _handle_marketflow 同資料源）
        mf = {'turnover': [], 'inst': None, 'margin': None}
        try:
            ym1 = _date.today().strftime('%Y%m01')
            url = f'https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={ym1}&response=json'
            with urllib.request.urlopen(urllib.request.Request(url, headers=YF_HEADERS), timeout=12) as resp:
                d = json.loads(resp.read())
            if d.get('stat') in ('OK', 'ok'):
                fields = d.get('fields') or []
                rows = d.get('data') or []
                i_amt = next((i for i, f in enumerate(fields) if '成交金額' in f), 1)
                i_date = next((i for i, f in enumerate(fields) if '日期' in f), 0)
                for row in rows:
                    try:
                        amt = float(str(row[i_amt]).replace(',', ''))
                        mf['turnover'].append({'date': str(row[i_date]).strip(), 'amount': amt})
                    except Exception:
                        pass
        except Exception as e:
            print('[market-fund] FMTQIK', e)
        try:
            from datetime import timedelta
            for back in range(0, 7):
                dd = (_date.today() - timedelta(days=back)).strftime('%Y%m%d')
                url = f'https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate={dd}&type=day&response=json'
                with urllib.request.urlopen(urllib.request.Request(url, headers=YF_HEADERS), timeout=12) as resp:
                    d = json.loads(resp.read())
                if d.get('stat') not in ('OK', 'ok'):
                    continue
                fields = d.get('fields') or []
                rows = d.get('data') or []
                i_name = next((i for i, f in enumerate(fields) if '單位名稱' in f or '買賣別' in f), 0)
                i_net = next((i for i, f in enumerate(fields) if '買賣差' in f or '買賣超' in f), len(fields) - 1)
                inst = {'foreign': None, 'trust': None, 'dealer': None, 'date': dd}
                for row in rows:
                    nm = str(row[i_name])
                    try:
                        net = float(str(row[i_net]).replace(',', ''))
                    except Exception:
                        continue
                    if '外' in nm:
                        inst['foreign'] = (inst['foreign'] or 0) + net
                    elif '投信' in nm:
                        inst['trust'] = net
                    elif '自營' in nm:
                        inst['dealer'] = (inst['dealer'] or 0) + net
                if any(v is not None for k, v in inst.items() if k != 'date'):
                    mf['inst'] = inst
                    break
        except Exception as e:
            print('[market-fund] BFI82U', e)

    margin_meta = {}
    try:
        import margin_ratio as mr
        margin_meta = mr.meta_summary() or {}
    except Exception as e:
        print('[market-fund] margin meta', e)

    median_pe = _universe_median_pe()
    score, detail = _score_tw_market(mf, margin_meta, median_pe)
    out['score'] = score
    out['pillars'] = detail
    # 給前端類似 revenue/income 的可讀列（不走個股三率）
    out['marketRows'] = []
    if detail.get('turnoverYi') is not None:
        out['marketRows'].append({'k': '成交金額', 'v': f"{detail['turnoverYi']:.0f} 億", 'score': detail.get('volumeScore')})
    if detail.get('instNetYi') is not None:
        sign = '+' if detail['instNetYi'] >= 0 else ''
        out['marketRows'].append({'k': '三大法人合計', 'v': f"{sign}{detail['instNetYi']:.1f} 億", 'score': detail.get('instScore')})
    if detail.get('marginRatio') is not None:
        out['marketRows'].append({
            'k': '融資維持率',
            'v': f"{detail['marginRatio']:.2f}%" + (f"（{detail['riskZone']}）" if detail.get('riskZone') else ''),
            'score': detail.get('marginScore'),
        })
    if detail.get('medianPE') is not None:
        out['marketRows'].append({'k': '全市場本益比中位', 'v': f"{detail['medianPE']:.1f}x", 'score': detail.get('valuationScore')})
    try:
        import market_risk as mr
        out = mr.enrich_tw_market_fundamental(out)
    except Exception as e:
        print('[market-fund] enrich failed:', e)
        out.setdefault('direction', 'health')
        out.setdefault('summary', f"大盤體質 {score}" if score is not None else '大盤體質 —')
    return out


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
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json,*/*',
    'Accept-Language': 'en-US,en;q=0.9',
    'Referer': 'https://finance.yahoo.com/',
}

# Yahoo v10 quoteSummary 需 crumb；無 yfinance 時用 cookie jar 自取（進程內快取）
_yf_crumb_lock = threading.Lock()
_yf_crumb = {'value': None, 'ts': 0.0, 'opener': None}

# Yahoo keystats 死號負向快取：404/空 info 的代號 1 小時內不再 cascade
_YF_DEAD_LOCK = threading.Lock()
_YF_DEAD = {}  # sym -> expire_ts

def _yf_mark_dead(sym, ttl=3600):
    if not sym:
        return
    with _YF_DEAD_LOCK:
        _YF_DEAD[sym] = time.time() + ttl

def _yf_is_dead(sym):
    with _YF_DEAD_LOCK:
        exp = _YF_DEAD.get(sym)
        if not exp:
            return False
        if exp <= time.time():
            _YF_DEAD.pop(sym, None)
            return False
        return True


def _yahoo_crumb_opener(force=False):
    """回傳 (opener, crumb)。失敗回 (None, None)。"""
    import http.cookiejar
    global _yf_crumb
    now = time.time()
    with _yf_crumb_lock:
        if (not force and _yf_crumb['value'] and _yf_crumb['opener']
                and (now - _yf_crumb['ts']) < 3600):
            return _yf_crumb['opener'], _yf_crumb['value']
        cj = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        try:
            # 觸發 cookie（404 也沒關係，重點是 Set-Cookie）
            try:
                opener.open(urllib.request.Request('https://fc.yahoo.com', headers=YF_HEADERS), timeout=10)
            except Exception:
                pass
            try:
                opener.open(urllib.request.Request('https://finance.yahoo.com/', headers=YF_HEADERS), timeout=12)
            except Exception:
                pass
            resp = opener.open(
                urllib.request.Request('https://query1.finance.yahoo.com/v1/test/getcrumb', headers=YF_HEADERS),
                timeout=10,
            )
            crumb = resp.read().decode('utf-8', 'replace').strip()
            if not crumb or '<' in crumb or len(crumb) > 80:
                print('[yahoo-crumb] invalid crumb payload')
                return None, None
            _yf_crumb = {'value': crumb, 'ts': now, 'opener': opener}
            return opener, crumb
        except Exception as e:
            print('[yahoo-crumb] failed:', type(e).__name__, e)
            return None, None


def _yahoo_quote_summary(sym, modules='summaryDetail,defaultKeyStatistics,price,financialData'):
    """帶 crumb 打 v10 quoteSummary；回 result[0] dict 或 None。"""
    if _yf_is_dead(sym):
        return None
    opener, crumb = _yahoo_crumb_opener()
    if not opener or not crumb:
        return None
    url = (
        f'https://query1.finance.yahoo.com/v10/finance/quoteSummary/{quote(sym)}'
        f'?modules={modules}&crumb={quote(crumb)}'
    )
    try:
        with opener.open(urllib.request.Request(url, headers=YF_HEADERS), timeout=8) as resp:
            data = json.loads(resp.read().decode('utf-8', 'replace'))
        qs = data.get('quoteSummary') or {}
        result = qs.get('result') or []
        if result:
            return result[0]
        # crumb 過期 → 強制重取再試一次
        err = qs.get('error') or {}
        if err:
            opener, crumb = _yahoo_crumb_opener(force=True)
            if not opener or not crumb:
                return None
            url = (
                f'https://query1.finance.yahoo.com/v10/finance/quoteSummary/{quote(sym)}'
                f'?modules={modules}&crumb={quote(crumb)}'
            )
            with opener.open(urllib.request.Request(url, headers=YF_HEADERS), timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8', 'replace'))
            result = ((data.get('quoteSummary') or {}).get('result') or [])
            return result[0] if result else None
    except urllib.error.HTTPError as e:
        if e.code in (401, 404):
            _yf_mark_dead(sym)
        # 降噪：同代號死號只記 TrustedDataLayer，不逐檔 print
        _src_record('yahoo-keystats', False, 0, f'{e.code}')
    except Exception as e:
        _src_record('yahoo-keystats', False, 0, e)
    return None


YF_RANGE = os.environ.get('YF_RANGE', '5y')   # 5y 約 1250 K 線；可設 max / 10y / 2y
YF_INTERVAL = os.environ.get('YF_INTERVAL', '1d')

def get_margin_ratio_chart_json(rng=None):
    """相容轉發 → quote_api。"""
    import quote_api as qa
    return qa.get_margin_ratio_chart_json(rng)

def get_macro_track_chart_json(sym, rng=None):
    """相容轉發 → quote_api → macro_api。"""
    import quote_api as qa
    return qa.get_macro_track_chart_json(sym, rng)

try:
    import chart_registry as _cr
    _MACRO_TRACK_IDS = _cr.MACRO_TRACK_IDS
except Exception:
    _MACRO_TRACK_IDS = (
        '__TW_RATES__', '__TW_MARGIN_MIX__', '__TW_MARGIN_CYCLE__',
        '__US_RATES_CREDIT__', '__US_CPI_FIN__',
    )

def fetch_one(sym, rng=None, interval=None, nocache=False):
    """相容轉發 → quote_api.fetch_one（configure 後才有 cache／src_record）。"""
    import quote_api as qa
    return qa.fetch_one(sym, rng=rng, interval=interval, nocache=nocache)


# ════════════════════════════════════════════════════════════════════════════
# TrustedDataLayer (v3.9 Phase-0) — 對外資料源的 健檢 / 節流 / 熔斷 / 值驗證
# ----------------------------------------------------------------------------
# 正確控制流(非 GPT-OSS 流程圖的線性穿透):
#   呼叫者 → (各 handler 既有 _cache 先查) → _src_fetch_json[節流→熔斷檢查→抓取
#            →健檢登錄→指數退避重試] → _anom_quote 值合理性驗證 → 回傳。
#   SourceHealthChecker 是旁路:健康狀態存 _SRC_HEALTH,/health 端點 + 前端燈讀取。
# 設計原則:單機個人工具,不引入 Redis/CircuitBreaker 套件,純標準庫輕量實作。
# ════════════════════════════════════════════════════════════════════════════
_SRC_LOCK = threading.Lock()
_SRC_HEALTH = {}        # name -> dict(計數/時間/失敗連續數/熔斷到期)
_SRC_LAST_CALL = {}     # name -> 上次(預約)呼叫時間, 供節流
# 每源最小請求間隔(秒):TAIFEX MIS 易 520 故拉長;TWSE MIS 次之;yahoo 不節流(0)
_SRC_MIN_GAP = {'taifex-mis': 1.0, 'twse-mis': 0.3, 'twse-chip': 0.35, 'yahoo-keystats': 0.2}
_SRC_CB_THRESHOLD = 4   # 連續失敗達此數 → 開熔斷
_SRC_CB_COOLDOWN = 30.0 # 熔斷冷卻秒數(期間 fail-fast,不打外部源)


class SourceBreakerOpen(Exception):
    """熔斷開啟期間擲出,呼叫端應走備援或回快取/None。"""
    pass


def _src_record(name, ok, ms, err=None):
    with _SRC_LOCK:
        v = _SRC_HEALTH.get(name)
        if v is None:
            v = {'ok_ct': 0, 'err_ct': 0, 'last_ok': 0, 'last_err': 0,
                 'last_ms': None, 'fail_streak': 0, 'last_error': None, 'open_until': 0}
            _SRC_HEALTH[name] = v
        v['last_ms'] = ms
        if ok:
            v['ok_ct'] += 1; v['last_ok'] = time.time()
            v['fail_streak'] = 0; v['open_until'] = 0
        else:
            v['err_ct'] += 1; v['last_err'] = time.time()
            v['fail_streak'] += 1
            v['last_error'] = (str(err)[:160] if err else 'error')
            if v['fail_streak'] >= _SRC_CB_THRESHOLD:
                v['open_until'] = time.time() + _SRC_CB_COOLDOWN


# H2：注入 quote_api 依賴（須在 _cache / _src_record 就緒後）
try:
    import quote_api as _quote_api
    _quote_api.configure(
        cache=_cache,
        src_record=_src_record,
        yf_headers=YF_HEADERS,
        yf_range=YF_RANGE,
        yf_interval=YF_INTERVAL,
    )
except Exception as _qa_err:
    print('[server] quote_api.configure failed:', _qa_err)

def _src_breaker_open(name):
    with _SRC_LOCK:
        v = _SRC_HEALTH.get(name)
        return bool(v and time.time() < v['open_until'])


def _src_throttle(name):
    """per-source 最小間隔節流(粗略佔位,避免並發過衝外部源)。"""
    gap = _SRC_MIN_GAP.get(name)
    if not gap:
        return
    with _SRC_LOCK:
        last = _SRC_LAST_CALL.get(name, 0)
        wait = gap - (time.time() - last)
        _SRC_LAST_CALL[name] = max(time.time(), last + gap)
    if wait > 0:
        time.sleep(min(wait, 3.0))


def _src_fetch_json(name, url, headers=None, timeout=10, retries=1, data=None):
    """經 健檢/節流/熔斷/退避 的對外 JSON 抓取。
       熔斷開啟 → 擲 SourceBreakerOpen;最終失敗 → 擲原始例外。data 給定則為 POST。"""
    if _src_breaker_open(name):
        raise SourceBreakerOpen(name)
    last_exc = None
    for attempt in range(retries + 1):
        _src_throttle(name)
        t0 = time.time()
        try:
            req = urllib.request.Request(url, headers=headers or {}, data=data)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            parsed = json.loads(raw)
            _src_record(name, True, int((time.time() - t0) * 1000))
            return parsed
        except Exception as e:
            last_exc = e
            _src_record(name, False, int((time.time() - t0) * 1000), e)
            if attempt < retries:
                time.sleep(min(0.5 * (2 ** attempt), 4.0))   # 指數退避
    raise last_exc if last_exc else RuntimeError(name + ' fetch failed')


try:
    import chip_api as _chip_api
    _chip_api.configure(
        yf_headers=YF_HEADERS,
        src_fetch_json=_src_fetch_json,
        source_breaker_open=SourceBreakerOpen,
        chip_streak=_chip_streak,
        chip_history_record=_chip_history_record,
    )
except Exception as _ca_err:
    print('[server] chip_api.configure failed:', _ca_err)


def _src_snapshot():
    """供 /health:回各源摘要(成功率/最後成功幾秒前/熔斷狀態)。"""
    out = {}
    now = time.time()
    with _SRC_LOCK:
        for k, v in _SRC_HEALTH.items():
            total = v['ok_ct'] + v['err_ct']
            out[k] = {
                'healthy': v['fail_streak'] < _SRC_CB_THRESHOLD and not (now < v['open_until']),
                'okRate': round(v['ok_ct'] / total * 100, 1) if total else None,
                'calls': total,
                'lastOkAgo': round(now - v['last_ok'], 1) if v['last_ok'] else None,
                'lastErrAgo': round(now - v['last_err'], 1) if v['last_err'] else None,
                'lastMs': v['last_ms'],
                'failStreak': v['fail_streak'],
                'lastError': v['last_error'],
                'breakerOpen': now < v['open_until'],
            }
    return out


def _yf_prevclose(meta, allow_chart_prev=True):
    """單一可信昨收口徑 — 全站共用,避免各端點優先序不一造成漲幅亂跳。
       優先 regularMarketPreviousClose(真昨收) > previousClose > chartPreviousClose (限 allow_chart_prev=True)。"""
    if not meta:
        return None
    val = (meta.get('regularMarketPreviousClose')
           or meta.get('previousClose'))
    if val is not None:
        return val
    return meta.get('chartPreviousClose') if allow_chart_prev else None


def _anom_quote(price, prev, chg, kind='stock'):
    """報價值合理性驗證 — 攔 ^TWOII 419/+56% 這類假數字。
       回 (suspect:bool, reason:str|None)。kind='index' 對 price/prev 比值較寬鬆。"""
    if price is None or price <= 0:
        return True, 'price<=0/None'
    if prev is not None and prev > 0:
        ratio = price / prev
        if ratio > 1.5 or ratio < 0.5:
            return True, f'price/prev={ratio:.2f} 離譜'
    lim = 12.0 if kind == 'index' else 11.0   # 台股個股漲跌停±10%;指數日內極少>12%
    if chg is not None and abs(chg) > lim:
        return True, f'changePct={chg:.1f}% 超出 ±{lim:g}%'
    return False, None


# Yahoo 不可信標的 → 改走 TWSE MIS。 sym -> (ex_ch, code, kind)
_BAD_YF = {'^TWOII': ('otc_o00.tw', 'o00', 'index')}   # 櫃買:Yahoo 三端點三值,只信 MIS


def _twse_mis_index(ex_ch):
    """ex_ch('tse_t00.tw' 或 'tse_t00.tw|otc_o00.tw') →
       {code:{price,prevClose,changePct,name,open,high,low}}。
       走共用 _src_fetch_json('twse-mis'),享節流/熔斷/健檢。"""
    ms = int(time.time() * 1000)
    url = ('https://mis.twse.com.tw/stock/api/getStockInfo.jsp'
           f'?ex_ch={ex_ch}&json=1&delay=0&_={ms}')
    data = _src_fetch_json('twse-mis', url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': 'application/json', 'Accept-Language': 'zh-TW,zh;q=0.9',
        'Referer': 'https://mis.twse.com.tw/stock/index.jsp',
    }, timeout=10)

    def fnum(v):
        if v in (None, '', '-'):
            return None
        try:
            return float(str(v).replace(',', ''))
        except Exception:
            return None
    out = {}
    for it in (data.get('msgArray') or []):
        ch = it.get('ch') or ''
        code = 't00' if 't00' in ch else ('o00' if 'o00' in ch else ch)
        price = fnum(it.get('z'))
        if price is None:
            price = fnum(it.get('o'))      # 早盤尚無成交退開盤
        prev = fnum(it.get('y'))
        chg = ((price - prev) / prev * 100) if (price is not None and prev) else None
        out[code] = {
            'price': price, 'prevClose': prev, 'changePct': chg, 'name': it.get('n'),
            'open': fnum(it.get('o')), 'high': fnum(it.get('h')), 'low': fnum(it.get('l')),
        }
    return out


def _fetch_day_movers(n=8):
    """輕量漲跌幅排行：TWSE STOCK_DAY_ALL + TPEx 上櫃日收盤。
       回 {ok,date,gainers:[{code,name,price,change,changePct,value}], losers:[...], source}。
       供 Overview 儀表板；比 POST /screener 快兩個數量級。"""
    from datetime import date as _date

    def fnum(v):
        if v in (None, '', '-', '—'):
            return None
        try:
            return float(str(v).replace(',', '').replace('+', '').strip())
        except Exception:
            return None

    rows = []
    date_s = None

    def ingest_twse(arr):
        nonlocal date_s
        for r in arr or []:
            if not isinstance(r, dict):
                continue
            code = str(r.get('Code') or '').strip()
            name = str(r.get('Name') or '').strip()
            if not code or not name:
                continue
            # 排除權證／牛熊（名稱含購售，或非 4 碼個股／00 開頭 ETF）
            if any(k in name for k in ('購', '售', '牛證', '熊證', '認購', '認售')):
                continue
            is_stock = bool(_CODE4.match(code))
            is_etf = code.startswith('00') and len(code) <= 6
            if not (is_stock or is_etf):
                continue
            close = fnum(r.get('ClosingPrice'))
            chg = fnum(r.get('Change'))
            if close is None or chg is None:
                continue
            prev = close - chg
            if not prev:
                continue
            pct = chg / prev * 100.0
            # 權證漏網：單日 ±30% 以上且非槓桿 ETF 代號 → 略過
            if abs(pct) > 30 and not code.endswith(('L', 'R')):
                continue
            val = fnum(r.get('TradeValue'))
            date_s = date_s or str(r.get('Date') or '').strip() or None
            rows.append({
                'code': code, 'name': name, 'price': close, 'change': chg,
                'changePct': round(pct, 2), 'value': val, 'mkt': 'TW',
            })

    def ingest_tpex(arr):
        for r in arr or []:
            if not isinstance(r, dict):
                continue
            code = str(r.get('SecuritiesCompanyCode') or r.get('Code') or r.get('公司代號') or '').strip()
            name = str(r.get('CompanyName') or r.get('Name') or r.get('公司簡稱') or '').strip()
            if any(k in name for k in ('購', '售', '牛證', '熊證', '認購', '認售')):
                continue
            if not (_CODE4.match(code) or (code.startswith('00') and len(code) <= 6)):
                continue
            close = fnum(r.get('Close') or r.get('ClosingPrice') or r.get('收盤'))
            # TPEx 常見：Change / 漲跌
            chg = fnum(r.get('Change') or r.get('漲跌'))
            if close is None:
                continue
            if chg is None:
                # 有些欄位是百分比
                pct = fnum(r.get('ChangePercent') or r.get('漲跌幅'))
                if pct is None:
                    continue
            else:
                prev = close - chg
                if not prev:
                    continue
                pct = chg / prev * 100.0
            if abs(pct) > 30 and not code.endswith(('L', 'R')):
                continue
            if any(x['code'] == code for x in rows):
                continue
            rows.append({
                'code': code, 'name': name or code, 'price': close,
                'change': chg, 'changePct': round(pct, 2),
                'value': fnum(r.get('TradeValue') or r.get('成交金額')),
                'mkt': 'TW',
            })

    def _get_json(url, timeout=8):
        req = urllib.request.Request(
            url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())

    # TWSE + TPEx 並行（本函式可能在 thread pool 內執行，用獨立短線程避免巢狀死鎖）
    twse_rows = None
    tpex_rows = None
    err_twse = err_tpex = None

    def _twse():
        nonlocal twse_rows, err_twse
        try:
            twse_rows = _get_json(
                'https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL', timeout=8)
        except Exception as e:
            err_twse = e

    def _tpex():
        nonlocal tpex_rows, err_tpex
        try:
            tpex_rows = _get_json(
                'https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes', timeout=8)
        except Exception as e:
            err_tpex = e

    t1 = threading.Thread(target=_twse, daemon=True)
    t2 = threading.Thread(target=_tpex, daemon=True)
    t1.start(); t2.start()
    t1.join(9); t2.join(9)
    if twse_rows is not None:
        try:
            ingest_twse(twse_rows)
        except Exception as e:
            print('[movers] TWSE ingest', e)
    elif err_twse:
        print('[movers] TWSE', err_twse)
    if tpex_rows is not None:
        try:
            ingest_tpex(tpex_rows)
        except Exception as e:
            print('[movers] TPEx ingest', e)
    elif err_tpex:
        print('[movers] TPEx', err_tpex)

    if not rows:
        return {'ok': False, 'date': date_s, 'gainers': [], 'losers': [], 'source': None, 'error': 'no rows'}

    rows.sort(key=lambda x: x['changePct'], reverse=True)
    n = max(1, min(int(n or 8), 30))
    return {
        'ok': True,
        'date': date_s or _date.today().strftime('%Y%m%d'),
        'gainers': rows[:n],
        'losers': list(reversed(rows[-n:])),
        'source': 'TWSE STOCK_DAY_ALL + TPEx daily',
        'count': len(rows),
    }


def _macro_latest(series_key, years=10, timeout=8, retries=1, allow_fetch=True):
    """讀 MACRO_SERIES 最後一點（走 _macro_cache，與 /macro/<key> 同源）。失敗回 None。
       /pulse 請用 timeout<=4、retries=1，避免 FRED 不通時拖垮總覽。"""
    from datetime import date as _date, timedelta as _td
    spec = MACRO_SERIES.get(series_key)
    if not spec:
        return None
    today = _date.today()
    ckey = f'{series_key}:{years}:{today.strftime("%Y%m%d")}'
    cached = _macro_cache.get(ckey)
    d = None
    if cached:
        try:
            d = json.loads(cached.decode('utf-8') if isinstance(cached, (bytes, bytearray)) else cached)
        except Exception:
            d = None
    if d is None and allow_fetch:
        # 失敗冷卻：同一系列短時間不重抓
        until = _macro_fail_until.get(ckey) or 0
        if until > time.time():
            return None
        cosd = (today - _td(days=years * 366)).strftime('%Y-%m-%d')
        out = {
            'series': series_key, 'label': spec['label'], 'unit': spec.get('unit', ''),
            'points': [], 'source': None, 'note': None,
        }
        try:
            if spec['p'] == 'fred':
                out['points'] = _fetch_fred_csv(spec['id'], cosd, timeout=timeout, retries=retries)
                out['source'] = f'FRED {spec["id"]}'
            elif spec['p'] == 'twcpi':
                out['points'] = _fetch_tw_cpi(max(12, years * 12))
                out['source'] = '主計總處 PXWeb' if out['points'] else None
            elif spec['p'] == 'ndc':
                out['points'] = _fetch_tw_light()
                out['source'] = '國發會 NDC' if out['points'] else None
        except Exception as e:
            out['note'] = str(e)
            _macro_fail_until[ckey] = time.time() + 600  # 10 分鐘內略過
        if out['points']:
            body = json.dumps(out, ensure_ascii=False).encode()
            _macro_cache[ckey] = body
            _macro_fail_until.pop(ckey, None)
            d = out
        else:
            _macro_fail_until[ckey] = time.time() + 600
            return None
    pts = (d or {}).get('points') or []
    if not pts:
        return None
    last = pts[-1]
    return {
        'key': series_key,
        'label': d.get('label') or series_key,
        'unit': d.get('unit') or '',
        'date': last.get('date'),
        'value': last.get('value'),
        'source': d.get('source'),
    }


def _yf_batch_quotes(syms):
    """輕量 Yahoo 批次：[{symbol,name,price,changePct}]。並行抓取，總預算約 6s。"""
    labels = {
        '^DJI': '道瓊', '^GSPC': 'S&P 500', '^IXIC': '那斯達克',
        'CL=F': 'WTI 原油', 'DX-Y.NYB': '美元指數', 'DX=F': '美元指數',
    }

    def _one(sym):
        try:
            ov = _trusted_quote_override(sym)
            if ov and ov.get('price') is not None:
                return {
                    'symbol': sym, 'name': labels.get(sym, sym),
                    'price': ov['price'], 'changePct': ov.get('changePct'),
                    'source': ov.get('source') or 'override',
                }
            _, data, _ = fetch_one(sym, '5d', '1d', False)
            if not data:
                return None
            res = (json.loads(data).get('chart') or {}).get('result') or []
            if not res:
                return None
            m = res[0].get('meta') or {}
            cur = m.get('regularMarketPrice')
            if cur is None:
                cls = ((res[0].get('indicators') or {}).get('quote') or [{}])[0].get('close') or []
                cur = next((c for c in reversed(cls) if c is not None), None)
            prev = _yf_prevclose(m)
            if cur is None or not prev:
                return None
            return {
                'symbol': sym, 'name': labels.get(sym, m.get('shortName') or sym),
                'price': cur, 'changePct': (cur - prev) / prev * 100.0,
                'source': 'yahoo',
            }
        except Exception as e:
            print('[pulse-global]', sym, e)
            return None

    out = []
    # 獨立小池，避免佔滿全域 _pool 造成巢狀等待
    with ThreadPoolExecutor(max_workers=min(6, max(2, len(syms or [])))) as ex:
        futs = [ex.submit(_one, s) for s in (syms or [])]
        try:
            for f in as_completed(futs, timeout=6):
                try:
                    row = f.result()
                except Exception:
                    row = None
                if row:
                    out.append(row)
        except Exception:
            # 逾時：帶走已完成的
            for f in futs:
                if f.done():
                    try:
                        row = f.result()
                        if row:
                            out.append(row)
                    except Exception:
                        pass
    # 保序
    order = {s: i for i, s in enumerate(syms or [])}
    out.sort(key=lambda r: order.get(r.get('symbol'), 999))
    return out


def _trusted_quote_override(sym):
    """sym 若為 Yahoo 不可信標的 → 回 {price,prevClose,changePct,source} 否則 None。
       MIS 抓取/熔斷失敗時回 None,讓呼叫端走原 Yahoo 流程(不會比現況更糟)。"""
    spec = _BAD_YF.get(sym)
    if not spec:
        return None
    ex_ch, code, _kind = spec
    try:
        idx = _twse_mis_index(ex_ch).get(code) or {}
        if idx.get('price') is None:
            return None
        return {'price': idx['price'], 'prevClose': idx['prevClose'],
                'changePct': idx['changePct'], 'source': 'twse-mis'}
    except Exception:
        return None


def _run_selftests():
    """資料完整性核心函式單元測試(瀏覽器 /selftest 觸發,真函式真執行)。
       涵蓋:昨收口徑優先序、報價異常驗證、源熔斷狀態機。回 {passed,total,allPass,cases}。
       這幾處正是過去反覆踩 bug 的地方(漲幅亂跳/櫃買/520),有迴歸測試後改動不會悄悄壞掉。"""
    cases = []

    def ck(name, got, exp):
        cases.append({'name': name, 'pass': got == exp, 'got': got, 'exp': exp})

    # _yf_prevclose 昨收口徑優先序
    ck('prevclose:rmpc優先', _yf_prevclose({'regularMarketPreviousClose': 100, 'previousClose': 99, 'chartPreviousClose': 50}), 100)
    ck('prevclose:退previousClose', _yf_prevclose({'previousClose': 99, 'chartPreviousClose': 50}), 99)
    ck('prevclose:退chartPrev', _yf_prevclose({'chartPreviousClose': 50}), 50)
    ck('prevclose:空meta回None', _yf_prevclose({}), None)
    ck('prevclose:None回None', _yf_prevclose(None), None)

    # _anom_quote 報價異常驗證
    ck('anom:正常指數不suspect', _anom_quote(430, 429, 0.2, 'index')[0], False)
    ck('anom:櫃買419/267離譜', _anom_quote(419, 267, 56.9, 'index')[0], True)
    ck('anom:櫃買105過低', _anom_quote(105, 267, -60.7, 'index')[0], True)
    ck('anom:price<=0', _anom_quote(0, 100, 0, 'stock')[0], True)
    ck('anom:個股+10%正常', _anom_quote(110, 100, 10, 'stock')[0], False)
    ck('anom:個股+30%超漲停', _anom_quote(130, 100, 30, 'stock')[0], True)

    # _src 熔斷狀態機(用 __test__ 源,測完清掉不污染真源)
    try:
        _SRC_HEALTH.pop('__test__', None)
        for _ in range(_SRC_CB_THRESHOLD):
            _src_record('__test__', False, 5, 'x')
        ck('breaker:連敗後開啟', _src_breaker_open('__test__'), True)
        _src_record('__test__', True, 5)
        ck('breaker:成功後關閉', _src_breaker_open('__test__'), False)
    finally:
        _SRC_HEALTH.pop('__test__', None)

    passed = sum(1 for c in cases if c['pass'])
    return {'passed': passed, 'total': len(cases), 'allPass': passed == len(cases), 'cases': cases}

# ── Threading HTTP server ──────────────────────────────────────
class ThreadingHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64

class Handler(AiRoutesMixin, EtfRoutesMixin, SimpleHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'   # enables keep-alive

    def do_GET(self):
        p = self.path
        if p.startswith('/yf/batch'):
            self._handle_batch()
        elif p.startswith('/yf/'):
            sym = unquote(p[4:].split('?')[0])
            if not _safe_sym(sym): self._err('bad symbol', 400); return
            self._handle_single(sym)
        elif p.startswith('/etf-delta'):
            self._handle_etf_delta()
        elif p == '/etf-catalog' or p.startswith('/etf-catalog?'):
            self._handle_etf_catalog_get()
        elif p == '/etf-tracker/status' or p.startswith('/etf-tracker/status?'):
            self._handle_tracker_status()
        elif p == '/quote-batch' or p.startswith('/quote-batch?'):
            self._handle_quote_batch()
        elif p.startswith('/quote/'):
            sym = unquote(p[7:].split('?')[0])
            if not _safe_sym(sym): self._err('bad symbol', 400); return
            self._handle_quote(sym)
        elif p == '/bars' or p.startswith('/bars?'):
            self._handle_bars()
        elif p == '/universe' or p.startswith('/universe?'):
            self._handle_universe()
        elif p == '/datasources' or p.startswith('/datasources?'):
            self._handle_datasources()
        elif p.startswith('/chip/'):
            sym = unquote(p[6:].split('?')[0])
            self._handle_chip(sym)
        elif p.startswith('/holders/'):
            rest = unquote(p[9:].split('?')[0]).strip('/')
            self._handle_holders(rest)
        elif p.startswith('/keystats/'):
            sym = unquote(p[10:].split('?')[0])
            self._handle_keystats(sym)
        elif p.startswith('/fundamental/'):
            sym = unquote(p[13:].split('?')[0])
            self._handle_fundamental(sym)
        elif p.startswith('/valuation/'):
            sym = unquote(p[11:].split('?')[0])
            self._handle_valuation(sym)
        elif p == '/marketflow' or p.startswith('/marketflow?'):
            self._handle_marketflow()
        elif p == '/breadth' or p.startswith('/breadth?'):
            self._handle_breadth()
        elif p == '/pulse' or p.startswith('/pulse?'):
            self._handle_pulse()
        elif p == '/pulse/history' or p.startswith('/pulse/history?'):
            self._handle_pulse_history()
        elif p == '/sync' or p.startswith('/sync?'):
            self._handle_sync()
        elif p == '/sync/status' or p.startswith('/sync/status?'):
            self._handle_sync_status()
        elif p == '/movers' or p.startswith('/movers?'):
            self._handle_movers()
        elif p == '/inst-rank' or p.startswith('/inst-rank?'):
            self._handle_inst_rank()
        elif p == '/events' or p.startswith('/events?'):
            self._handle_events()
        elif p == '/sectors' or p.startswith('/sectors?'):
            self._handle_sectors()
        elif p == '/ai/local/status' or p.startswith('/ai/local/status?'):
            self._handle_ai_local_status()
        elif p == '/screener' or p.startswith('/screener?'):
            self._handle_screener_get()
        elif p == '/focus' or p.startswith('/focus?'):
            self._handle_focus()
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
        elif p == '/stockfut' or p.startswith('/stockfut?'):
            self._handle_stockfut()
        elif p == '/twindex' or p.startswith('/twindex?'):
            self._handle_twindex()
        elif p == '/margin_ratio' or p.startswith('/margin_ratio?'):
            self._handle_margin_ratio()
        elif p == '/search' or p.startswith('/search?'):
            self._handle_search()
        elif p == '/ai-key/status':
            self._handle_ai_key_status()
        elif p == '/ai-model' or p.startswith('/ai-model?'):
            self._handle_ai_model()
        elif p == '/twquote-batch' or p.startswith('/twquote-batch?'):
            self._handle_twquote_batch()
        elif p == '/twquote' or p.startswith('/twquote?'):
            self._handle_twquote()
        elif p == '/selftest' or p.startswith('/selftest?'):
            self._ok(json.dumps(_run_selftests(), ensure_ascii=False).encode())
        elif p.startswith('/draw/'):
            self._handle_draw_get(p[len('/draw/'):].split('?')[0])
        elif p == '/macro' or p.startswith('/macro?'):
            self._handle_macro('')
        elif p.startswith('/macro/'):
            self._handle_macro(p[len('/macro/'):].split('?')[0])
        elif p == '/health':
            d = find_etf_dir()
            files = list_etf_files()
            jobs = {}
            try:
                import quote_api as qa
                jobs = qa.jobs_snapshot()
            except Exception as e:
                jobs = {'error': str(e)}
            self._ok(json.dumps({
                'status': 'ok',
                'bind': '127.0.0.1',
                'port': PORT,
                'workers': MAX_WORKERS,
                'cpu_count': os.cpu_count(),
                'cache_used': len(_cache),
                'cache_max': LRU_MAX,
                'cache_ttl_seconds': getattr(_cache, '_ttl', None),
                'etf_delta_path': d or 'not found',
                'etf_history_files': len(files),
                'sources': _src_snapshot(),
                'jobs': jobs,  # H4：回補／刷新進度
            }, ensure_ascii=False, default=str).encode())
        else:
            # 安全(v3.9 review):SimpleHTTPRequestHandler 預設會把工作目錄所有檔當靜態檔服務。
            # 阻擋敏感檔被下載:金鑰設定(alert_config 含 telegram token/gmail 密碼)、原始碼(.py)、
            # 批次檔(.bat)、使用者資料(chip/etf 歷史、backups)、log。本機工具只需服務 UI 資產。
            _pl = p.split('?')[0].lower()
            _DENY_EXT = ('.py', '.pyc', '.bat', '.log', '.env')
            _DENY_SUB = ('alert_config', 'alert_rules', 'ai_key', '/chip_history', '/etf_history',
                         '/backups', '/__pycache__', '/.git', '/.claude')
            if '..' in _pl or _pl.endswith(_DENY_EXT) or any(s in _pl for s in _DENY_SUB):
                self._err('forbidden', 403); return
            super().do_GET()

    def _origin_ok(self):
        # CSRF 防護(v3.9 review):瀏覽器跨來源寫入會帶 Origin/Referer;非本站一律拒。
        # 同源 fetch 或非瀏覽器本機呼叫可能不帶 → 放行(本機單人工具)。
        o = self.headers.get('Origin') or self.headers.get('Referer') or ''
        if not o:
            return True
        return (o.startswith('http://localhost:%d' % PORT)
                or o.startswith('http://127.0.0.1:%d' % PORT))

    def do_POST(self):
        p = self.path.split('?')[0]
        if not self._origin_ok():
            self._err('forbidden (cross-origin)', 403); return
        if p == '/ai-key':
            self._handle_ai_key_set()
        elif p == '/ai-proxy':
            self._handle_ai_proxy()
        elif p == '/etf-catalog':
            self._handle_etf_catalog_post()
        elif p == '/etf-tracker/run':
            self._handle_tracker_run()
        elif p == '/screener':
            self._handle_screener_post()
        elif p == '/screen3':
            self._handle_screen3()
        elif p == '/portfolio':
            self._handle_portfolio()
        elif p == '/chain-momentum':
            self._handle_chain_momentum()
        elif p == '/ai/local':
            self._handle_ai_local()
        elif p == '/notify':
            self._handle_notify()
        elif p == '/universe/refresh':
            self._handle_universe_refresh()
        elif p == '/datasource/refresh':
            self._handle_datasource_refresh()
        elif p == '/macro/refresh' or p.startswith('/macro/refresh/'):
            # UI 一鍵更新追蹤圖（POST body 可帶 {id, dense, density, step, years}）
            try:
                n = int(self.headers.get('Content-Length') or 0)
            except Exception:
                n = 0
            body = {}
            if n > 0:
                try:
                    body = json.loads(self.rfile.read(n).decode('utf-8') or '{}')
                except Exception:
                    body = {}
            qs = parse_qs(urlparse(self.path).query)
            cid = (body.get('id') or (qs.get('id', [None])[0]) or 'ALL')
            if p.startswith('/macro/refresh/'):
                cid = p.split('/macro/refresh/', 1)[1].split('?')[0] or cid
            dense = body.get('dense', qs.get('dense', [True])[0])
            if isinstance(dense, str):
                dense = dense.lower() in ('1', 'true', 'yes')
            density = body.get('density') or (qs.get('density', [None])[0])
            step = body.get('step', qs.get('step', [None])[0])
            years = body.get('years', qs.get('years', [None])[0])
            try:
                step = int(step) if step not in (None, '') else None
            except Exception:
                step = None
            try:
                years = int(years) if years not in (None, '') else None
            except Exception:
                years = None
            try:
                import macro_track as mt
                data = mt.refresh_chart(
                    str(cid), dense=bool(dense), density=density, step=step, years=years,
                )
                self._ok(json.dumps(data, ensure_ascii=False).encode())
            except Exception as e:
                self._err('macro refresh failed: ' + str(e), 500)
        elif p == '/margin_ratio/backfill':
            self._handle_margin_ratio_backfill()
        elif p == '/ai-report':
            self._handle_ai_report()
        elif p == '/etf-reason':
            self._handle_etf_reason()
        elif p == '/ai-note':
            self._handle_ai_note()
        elif p == '/alert/rules':
            self._alert_post_rules()
        elif p == '/alert/config':
            self._alert_post_config()
        elif p == '/alert/test':
            self._alert_test()
        elif p == '/etf-report/email':
            self._etf_report_email()
        elif p == '/report-email':
            self._handle_report_email()
        elif p == '/watch/rules':
            self._watch_post_rules()
        elif p == '/watch/config':
            self._watch_post_config()
        elif p.startswith('/draw/'):
            self._handle_draw_post(p[len('/draw/'):])
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
            req_sym = futures[fut]
            _ret_sym, data, _ = fut.result()
            if data:
                try:
                    # 以請求代號為 key（覆寫路徑可能回傳 canonical id）
                    results[req_sym] = json.loads(data)
                except Exception:
                    pass
        self._ok(json.dumps(results).encode())

    def _handle_twquote(self):
        """台股個股『即時』報價 (v3.9) — TWSE MIS getStockInfo,真即時。
           解 Yahoo 免費台股分K 延遲~20min 的問題:盤中即時看盤用此源更新最新K棒。
           ?code=2330。回 {ok,price,open,high,low,prevClose,volume,name,time}。"""
        qs = parse_qs(urlparse(self.path).query)
        code = (qs.get('code', [''])[0] or '').strip().upper().replace('.TWO', '').replace('.TW', '')
        if not code:
            self._ok(b'{"ok":false}'); return

        def fnum(v):
            if v in (None, '', '-'):
                return None
            try:
                return float(str(v).replace(',', ''))
            except Exception:
                return None
        out = {'ok': False, 'code': code}
        for ex in ('tse_%s.tw' % code, 'otc_%s.tw' % code):
            try:
                ms = int(time.time() * 1000)
                url = ('https://mis.twse.com.tw/stock/api/getStockInfo.jsp'
                       '?ex_ch=%s&json=1&delay=0&_=%d' % (ex, ms))
                data = _src_fetch_json('twse-mis', url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                    'Accept': 'application/json', 'Accept-Language': 'zh-TW,zh;q=0.9',
                    'Referer': 'https://mis.twse.com.tw/stock/index.jsp',
                }, timeout=8)
                arr = data.get('msgArray') or []
                if not arr:
                    continue
                it = arr[0]
                # Data Integrity:只用最新『成交』價 z。z='-'(無撮合/收盤後)→ 不推估(試下一個 ex,
                #   都沒有就回 ok:false 讓前端保留上次真實值)。絕不用開盤價/委買賣價假裝成交價(會灌錯值)。
                price = fnum(it.get('z'))
                if price is None:
                    continue
                out = {'ok': True, 'code': code, 'price': price,
                       'open': fnum(it.get('o')), 'high': fnum(it.get('h')), 'low': fnum(it.get('l')),
                       'prevClose': fnum(it.get('y')), 'volume': fnum(it.get('v')),
                       'name': it.get('n'), 'time': it.get('t'), 'source': 'twse-mis'}
                break
            except SourceBreakerOpen:
                out['error'] = 'twse-mis breaker open'; break
            except Exception as e:
                out['error'] = str(e)
        self._ok(json.dumps(out, ensure_ascii=False).encode())

    def _handle_twquote_batch(self):
        """台股批次『即時』報價 (v3.9) — TWSE MIS 一次查多檔(自選股即時化用)。
           ?codes=2330,00631L,...。回 {code:{price,prevClose,changePct}}。
           每檔同送 tse_ 與 otc_ 兩 ex_ch(MIS 只回存在的);分塊避免過長。"""
        qs = parse_qs(urlparse(self.path).query)
        codes = [c.strip().upper().replace('.TWO', '').replace('.TW', '')
                 for c in (qs.get('codes', [''])[0]).split(',') if c.strip()]
        if not codes:
            self._ok(b'{}'); return

        def fnum(v):
            if v in (None, '', '-'):
                return None
            try:
                return float(str(v).replace(',', ''))
            except Exception:
                return None
        exs = []
        for c in codes:
            exs.append('tse_%s.tw' % c)
            exs.append('otc_%s.tw' % c)
        out = {}
        for i in range(0, len(exs), 50):                 # MIS 一次最多約 50~100 檔,保守分塊
            chunk = '|'.join(exs[i:i + 50])
            try:
                ms = int(time.time() * 1000)
                url = ('https://mis.twse.com.tw/stock/api/getStockInfo.jsp'
                       '?ex_ch=%s&json=1&delay=0&_=%d' % (chunk, ms))
                data = _src_fetch_json('twse-mis', url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                    'Accept': 'application/json', 'Accept-Language': 'zh-TW,zh;q=0.9',
                    'Referer': 'https://mis.twse.com.tw/stock/index.jsp',
                }, timeout=8)
                for it in (data.get('msgArray') or []):
                    code = (it.get('c') or '').strip()
                    price = fnum(it.get('z'))        # Data Integrity:只用最新成交價;z='-' 不推估,略過(前端保留上次值)
                    prev = fnum(it.get('y'))
                    if code and price is not None:
                        chg = ((price - prev) / prev * 100) if prev else None
                        out[code] = {'price': price, 'prevClose': prev, 'changePct': chg}
            except SourceBreakerOpen:
                break
            except Exception:
                continue
        self._ok(json.dumps(out, ensure_ascii=False).encode())





    def _handle_search(self):
        """台股名稱/代號搜尋 (v3.9) — 像 Yahoo 股市打公司名找股票。
           q 可為中文名(子字串)或代號(前綴)。回 {results:[{t,name,m}]}。
           資料源:_get_tw_names()(TWSE+櫃買+opendata,每日快取)。"""
        qs = parse_qs(urlparse(self.path).query)
        q = (qs.get('q', [''])[0] or '').strip()
        if not q:
            self._ok(b'{"results":[]}'); return
        if q.upper() in ('__MARGIN_RATIO__', '融資維持率', '大盤融資維持率'):
            self._ok(json.dumps({'results': [{'t': '__MARGIN_RATIO__', 'name': '大盤融資維持率', 'm': 'TW'}]}, ensure_ascii=False).encode())
            return
        # 籌碼集中度：集中2330 / holders:2330 / __HOLDERS_2330__
        import re as _re
        _hm = _re.match(r'^(?:集中|holders[:/]?|__HOLDERS_)(\d{4,6})(?:__)?$', q, _re.I)
        if _hm:
            code = _hm.group(1)
            tid = f'__HOLDERS_{code}__'
            self._ok(json.dumps({'results': [{'t': tid, 'name': f'{code} 籌碼集中度', 'm': 'TW'}]}, ensure_ascii=False).encode())
            return
        _macro_q = {
            '__TW_RATES__': ('台灣指標利率', 'TW'),
            '台利率': ('台灣指標利率', 'TW'),
            '重貼現率': ('台灣指標利率', 'TW'),
            '__TW_MARGIN_MIX__': ('上櫃／上市融資張數比年增', 'TW'),
            '融資比': ('上櫃／上市融資張數比年增', 'TW'),
            '__TW_MARGIN_CYCLE__': ('融資週期（槓桿臨界）', 'TW'),
            '融資週期': ('融資週期（槓桿臨界）', 'TW'),
            '槓桿臨界': ('融資週期（槓桿臨界）', 'TW'),
            '__US_RATES_CREDIT__': ('美國利率 vs 公司債總報酬', 'US'),
            '美利率債': ('美國利率 vs 公司債總報酬', 'US'),
            '__US_CPI_FIN__': ('美國CPI＆基準利率 vs 金融股', 'US'),
            'CPI金融': ('美國CPI＆基準利率 vs 金融股', 'US'),
        }
        if q.upper() in _macro_q or q in _macro_q:
            key = q.upper() if q.upper() in _macro_q else q
            # map alias to canonical id
            _alias_to_id = {
                '台利率': '__TW_RATES__', '重貼現率': '__TW_RATES__',
                '融資比': '__TW_MARGIN_MIX__',
                '融資週期': '__TW_MARGIN_CYCLE__', '槓桿臨界': '__TW_MARGIN_CYCLE__',
                '美利率債': '__US_RATES_CREDIT__', 'CPI金融': '__US_CPI_FIN__',
            }
            tid = key if key.startswith('__') else _alias_to_id.get(q, key)
            name, mkt = _macro_q.get(key) or _macro_q.get(q) or (tid, 'TW')
            if not tid.startswith('__'):
                tid = _alias_to_id.get(q, tid)
            self._ok(json.dumps({'results': [{'t': tid, 'name': name, 'm': mkt}]}, ensure_ascii=False).encode())
            return
        try:
            names = _get_tw_names()           # {code: name}
        except Exception:
            names = {}
        ql = q.lower()
        scored = []
        for code, name in names.items():
            if code == q:
                rank = 0                      # 代號完全相符
            elif code.startswith(q):
                rank = 1                      # 代號前綴
            elif name.startswith(q):
                rank = 2                      # 名稱開頭
            elif q in name:
                rank = 3                      # 名稱含
            elif ql in code.lower():
                rank = 4
            else:
                continue
            scored.append((rank, len(name), code, name))
        scored.sort(key=lambda x: (x[0], x[1], x[2]))
        out = [{'t': c, 'name': n, 'm': 'TW'} for _, _, c, n in scored[:25]]
        self._ok(json.dumps({'results': out}, ensure_ascii=False).encode())

    def _handle_quote_batch(self):
        """批次輕量報價 (v3.9) — 給自選股列用，取代 wl_live 的 5d batch。
           每檔用 range=1d(meta.chartPreviousClose=真昨收，避開 5d 日線 null 缺口
           導致抓到更舊一根當昨收的亂跳問題)。.TW 抓不到回退 .TWO。並發。
           回 {sym:{price, prevClose, changePct}}。"""
        qs = parse_qs(urlparse(self.path).query)
        syms = [s.strip() for s in qs.get('syms', [''])[0].split(',') if s.strip()]
        if not syms:
            self._ok(b'{}'); return
        def one(sym):
            ov = _trusted_quote_override(sym)   # ^TWOII 等 → 改走 TWSE MIS
            if ov:
                return sym, ov
            cands = [sym]
            if sym.endswith('.TW') and not sym.endswith('.TWO'):
                cands.append(sym[:-3] + '.TWO')
            for cand in cands:
                try:
                    _, data, _ = fetch_one(cand, '1d', '1d', True)
                    if not data:
                        continue
                    res = (json.loads(data).get('chart') or {}).get('result') or []
                    if not res:
                        continue
                    m = res[0].get('meta') or {}
                    cur = m.get('regularMarketPrice')
                    if cur is None:
                        cls = ((res[0].get('indicators') or {}).get('quote') or [{}])[0].get('close') or []
                        cur = next((c for c in reversed(cls) if c is not None), None)
                    prev = _yf_prevclose(m)
                    if cur is None or not prev:
                        continue
                    return sym, {'price': cur, 'prevClose': prev, 'changePct': (cur - prev) / prev * 100}
                except Exception:
                    continue
            return sym, None
        out = {}
        futs = {_pool.submit(one, s): s for s in syms}
        for f in as_completed(futs):
            try:
                k, v = f.result()
                if v: out[k] = v
            except Exception:
                pass
        self._ok(json.dumps(out, ensure_ascii=False).encode())

    def _handle_quote(self, sym):
        """Lightweight near-real-time quote.
        Yahoo's v7 /finance/quote (which had bid/ask) is gated behind crumb cookie auth
        since 2024 — unauthenticated requests get 401. We use v8 /finance/chart with
        range=1d&interval=1m and extract price/high/low/vol from meta + last bar.
        bid/ask are not available free; would need broker API.
        """
        from urllib.parse import unquote as _unq
        sym = _unq(sym)                     # 路徑未自動解碼:%5ETWOII → ^TWOII,否則 _BAD_YF 比對不到
        ov = _trusted_quote_override(sym)   # ^TWOII 等 Yahoo 壞標的 → TWSE MIS
        if ov:
            self._ok(json.dumps({
                'symbol': sym, 'price': ov['price'], 'prevClose': ov['prevClose'],
                'change': (ov['price'] - ov['prevClose']) if ov['prevClose'] else None,
                'changePct': ov['changePct'], 'source': ov['source'],
                'serverTime': int(time.time()), 'suspect': False,
            }, ensure_ascii=False).encode('utf-8'))
            return
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
                    prev_close = _yf_prevclose(meta)
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
                    _susp, _why = _anom_quote(last_close, prev_close, change_pct,
                                              'index' if sym.startswith('^') else 'stock')
                    out['suspect'] = _susp
                    if _susp:
                        out['suspectReason'] = _why
                    self._ok(json.dumps(out, ensure_ascii=False).encode('utf-8'))
                    return
                except urllib.error.HTTPError as e:
                    if e.code == 404: break
                    continue
                except Exception as e:
                    print(f'[quote] {candidate} via {base} error: {e}')
                    continue
        self._err('quote fetch failed for ' + sym, 502)






    def _handle_keystats(self, sym):
        raw_sym = (sym or '').strip()
        base_sym = raw_sym.replace('.TWO', '').replace('.TW', '')
        if base_sym == '__MARGIN_RATIO__' or raw_sym.startswith('__MARGIN_RATIO__'):
            try:
                import margin_ratio as mr
                m = mr.meta_summary()
                res = {
                    'shortName': m.get('name') or '大盤融資維持率',
                    'longName': m.get('longName') or '大盤融資維持率 (Margin Maintenance Ratio)',
                    'currency': 'TWD',
                    'regularMarketPrice': m.get('current'),
                    'regularMarketPreviousClose': m.get('previous'),
                    'fiftyTwoWeekHigh': m.get('max'),
                    'fiftyTwoWeekLow': m.get('min'),
                    'marketCap': None,
                    'marginMeta': {
                        'count': m.get('count'),
                        'firstDate': m.get('firstDate'),
                        'lastDate': m.get('lastDate'),
                        'avg': m.get('avg'),
                        'delta': m.get('delta'),
                        'deltaPct': m.get('deltaPct'),
                        'riskZone': m.get('riskZone'),
                        'riskZones': m.get('riskZones'),
                        'formula': m.get('formula'),
                        'source': m.get('source'),
                        'reference': m.get('reference'),
                    },
                }
                self._ok(json.dumps(res, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self._err('margin keystats failed: ' + str(e), 500)
            return
        # 台股大盤指數：回「市場摘要」而非個股本益比（Yahoo ^TWII.TW 會 404）
        if _is_tw_index_sym(base_sym) or _is_tw_market_fund_sym(base_sym):
            try:
                fund = _build_tw_market_fundamental(base_sym)
                pillars = fund.get('pillars') or {}
                import margin_ratio as mr
                m = mr.meta_summary() or {}
                res = {
                    'shortName': '加權指數' if 'TWII' in base_sym.upper() and 'TWO' not in base_sym.upper()
                                 else ('櫃買指數' if 'TWOII' in base_sym.upper() else '大盤'),
                    'currency': 'TWD',
                    'marketCap': None,
                    'trailingPE': pillars.get('medianPE'),
                    'priceToBook': None,
                    'dividendYield': None,
                    'eps': None,
                    'kind': 'market',
                    'marketMeta': {
                        'score': fund.get('score'),
                        'title': fund.get('title') or '大盤體質',
                        'rows': fund.get('marketRows') or [],
                        'pillars': pillars,
                        'marginRatio': m.get('current'),
                        'riskZone': (m.get('riskZone') or {}).get('label') if isinstance(m.get('riskZone'), dict) else m.get('riskZone'),
                    },
                    '_source': fund.get('_source') or 'TWSE marketflow + margin + universe PE',
                }
                self._ok(json.dumps(res, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self._err('market keystats failed: ' + str(e), 500)
            return
        # 其他指數／合成序列：明確空估值（避免 ^GSPC.TW / __US_*.TW）
        if _is_index_sym(base_sym) or _is_macro_sym(base_sym):
            res = {
                'shortName': base_sym,
                'marketCap': None, 'trailingPE': None, 'priceToBook': None,
                'dividendYield': None, 'eps': None,
                'kind': 'index' if _is_index_sym(base_sym) else 'macro',
                '_note': '指數／總經序列無個股估值欄位',
                '_source': 'n/a',
            }
            self._ok(json.dumps(res, ensure_ascii=False).encode('utf-8'))
            return
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

        def _merge(dst, src, keys, tag=None):
            for k in keys:
                if dst.get(k) is None and src.get(k) is not None:
                    dst[k] = src[k]
            if tag and (src.get('trailingPE') is not None or src.get('marketCap') is not None
                        or src.get('regularMarketPrice') is not None):
                dst['_source'] = (dst.get('_source', '') + '+' + tag).strip('+')

        def _apply_bwibbu(res_out, clean):
            """台股官方估值 — 優先於 Yahoo cascade（ETF／上櫃也適用）。"""
            if not clean or not clean[0].isdigit():
                return
            if not (res_out.get('trailingPE') is None or res_out.get('priceToBook') is None
                    or res_out.get('dividendYield') is None):
                return
            row = _openapi_lookup(['exchangeReport/BWIBBU_ALL', 'BWIBBU_ALL'], clean)
            src = 'TWSE BWIBBU'
            if not row:
                row = _openapi_lookup(['tpex:tpex_mainboard_peratio_analysis'], clean)
                src = 'TPEx peratio'
            if not row:
                return
            pe = (_pick_num(row, ['本益比']) or _pick_num(row, ['PEratio'])
                  or _pick_num(row, ['PriceEarningRatio']))
            pb = (_pick_num(row, ['股價淨值比']) or _pick_num(row, ['PBratio'])
                  or _pick_num(row, ['PriceBookRatio']))
            yld = _pick_num(row, ['殖利率']) or _pick_num(row, ['Yield'])
            if res_out.get('trailingPE') is None and pe is not None:
                res_out['trailingPE'] = pe
            if res_out.get('priceToBook') is None and pb is not None:
                res_out['priceToBook'] = pb
            if res_out.get('dividendYield') is None and yld is not None:
                res_out['dividendYield'] = yld
            if not res_out.get('shortName'):
                res_out['shortName'] = row.get('Name') or row.get('證券名稱')
            res_out['currency'] = res_out.get('currency') or 'TWD'
            res_out['_source'] = (res_out.get('_source', '') + '+' + src).strip('+')
            if res_out.get('eps') is None and pe and res_out.get('regularMarketPrice'):
                try:
                    res_out['eps'] = round(float(res_out['regularMarketPrice']) / float(pe), 2)
                except Exception:
                    pass

        def _fetch_all(s, allow_yahoo_heavy=True):
            """allow_yahoo_heavy=False：跳過 v10/html（已知死號或 ETF 已有官方估值）。"""
            clean = s.replace('.TWO', '').replace('.TW', '').strip().upper()
            is_tw = s.endswith('.TW') or s.endswith('.TWO') or (clean[:1].isdigit() and len(clean) <= 6)
            res_out = {'symbol': s, '_source': ''}

            # 台股：官方估值先填，減少 Yahoo 401/404 cascade
            if is_tw:
                _apply_bwibbu(res_out, clean)

            if _yf_is_dead(s):
                # 死號：只補 chart 價／名（若也死則跳過）
                allow_yahoo_heavy = False

            if allow_yahoo_heavy and not _yf_is_dead(s):
                yf = self._fetch_keystats_yfinance(s)
                _merge(res_out, yf,
                       ('trailingPE','forwardPE','eps','forwardEps','pegRatio','marketCap',
                        'priceToBook','dividendYield','shortName','longName','currency',
                        'earningsQuarterlyGrowth','revenueGrowth','earningsGrowth',
                        'regularMarketPrice','grossMargin','opMargin','netMargin','roe',
                        'sharesOutstanding'),
                       tag=(yf.get('_source') or 'yfinance') if not yf.get('_error') else None)
                if yf.get('_error') and 'empty' in str(yf.get('_error')):
                    _yf_mark_dead(s, ttl=1800)

            need_more = (res_out.get('trailingPE') is None or res_out.get('marketCap') is None
                         or res_out.get('eps') is None or res_out.get('priceToBook') is None)
            # 槓桿／反向 ETF 通常無 PE：有價+名即可，不再打 v10/html
            is_lev_etf = bool(clean.startswith('00') and clean[-1:] in ('L', 'R', 'U', 'S'))
            if need_more and allow_yahoo_heavy and not _yf_is_dead(s) and not is_lev_etf:
                v10 = self._fetch_keystats_v10(s)
                _merge(res_out, v10,
                       ('trailingPE','forwardPE','eps','forwardEps','pegRatio','marketCap',
                        'priceToBook','dividendYield','shortName','longName','currency',
                        'earningsQuarterlyGrowth','revenueGrowth','earningsGrowth',
                        'regularMarketPrice','grossMargin','opMargin','netMargin','roe',
                        'sharesOutstanding'),
                       tag=v10.get('_source') or 'v10')

            need_more = (res_out.get('trailingPE') is None or res_out.get('marketCap') is None
                         or res_out.get('eps') is None)
            if need_more and allow_yahoo_heavy and not _yf_is_dead(s) and not is_lev_etf:
                html_out = self._fetch_keystats_html(s)
                _merge(res_out, html_out,
                       ('trailingPE','eps','marketCap','priceToBook','dividendYield',
                        'shortName','currency','regularMarketPrice'),
                       tag='html')

            # chart meta（價／名）— 404 → mark dead
            if res_out.get('regularMarketPrice') is None or res_out.get('shortName') is None:
                if not _yf_is_dead(s):
                    try:
                        u = f'https://query1.finance.yahoo.com/v8/finance/chart/{quote(s)}?range=5d&interval=1d'
                        req = urllib.request.Request(u, headers=YF_HEADERS)
                        with urllib.request.urlopen(req, timeout=6) as resp:
                            jj = json.loads(resp.read().decode('utf-8', 'replace'))
                        meta = ((jj.get('chart') or {}).get('result') or [{}])[0].get('meta') or {}
                        if res_out.get('regularMarketPrice') is None and meta.get('regularMarketPrice') is not None:
                            res_out['regularMarketPrice'] = meta.get('regularMarketPrice')
                        if res_out.get('shortName') is None:
                            res_out['shortName'] = meta.get('shortName') or meta.get('longName')
                        if res_out.get('longName') is None:
                            res_out['longName'] = meta.get('longName')
                        if res_out.get('currency') is None:
                            res_out['currency'] = meta.get('currency')
                        if (res_out.get('eps') is None and res_out.get('trailingPE')
                                and res_out.get('regularMarketPrice')):
                            try:
                                res_out['eps'] = round(
                                    float(res_out['regularMarketPrice']) / float(res_out['trailingPE']), 2)
                            except Exception:
                                pass
                        res_out['_source'] = (res_out.get('_source', '') + '+chart').strip('+')
                    except urllib.error.HTTPError as e:
                        if e.code in (401, 404):
                            _yf_mark_dead(s)
                        _src_record('yahoo-keystats', False, 0, f'chart {e.code}')
                    except Exception:
                        _src_record('yahoo-keystats', False, 0, 'chart')

            # 市值推算
            if res_out.get('marketCap') is None:
                px = res_out.get('regularMarketPrice')
                shares = res_out.get('sharesOutstanding')
                if shares and px:
                    try:
                        res_out['marketCap'] = float(shares) * float(px)
                        res_out['_source'] = (res_out.get('_source', '') + '+shares*px').strip('+')
                    except Exception:
                        pass
            if res_out.get('marketCap') is None and clean[:1].isdigit():
                px = res_out.get('regularMarketPrice')
                try:
                    crow = _openapi_lookup(['opendata/t187ap03_L', 't187ap03_L'], clean)
                    if not crow:
                        crow = _openapi_lookup(['tpex:mopsfin_t187ap03_O'], clean)
                    if crow:
                        capital = _pick_num(crow, ['實收資本額'])
                        face_raw = crow.get('普通股每股面額') or crow.get('每股面額') or '10'
                        face = 10.0
                        try:
                            import re as _re2
                            mface = _re2.search(r'([\d.]+)', str(face_raw).replace(',', ''))
                            if mface:
                                face = float(mface.group(1)) or 10.0
                        except Exception:
                            face = 10.0
                        if capital and face > 0:
                            if px is None:
                                srow = _openapi_lookup(['exchangeReport/STOCK_DAY_ALL'], clean)
                                if srow:
                                    px = _pick_num(srow, ['ClosingPrice']) or _pick_num(srow, ['收盤'])
                                    if px is not None:
                                        res_out['regularMarketPrice'] = px
                            if px:
                                shares = float(capital) / float(face)
                                res_out['marketCap'] = shares * float(px)
                                res_out['sharesOutstanding'] = shares
                                res_out['currency'] = res_out.get('currency') or 'TWD'
                                res_out['_source'] = (res_out.get('_source', '') + '+TWSE資本額').strip('+')
                except Exception:
                    pass
            if res_out.get('marketCap') is None and res_out.get('sharesOutstanding') and res_out.get('regularMarketPrice'):
                try:
                    res_out['marketCap'] = float(res_out['sharesOutstanding']) * float(res_out['regularMarketPrice'])
                    res_out['_source'] = (res_out.get('_source', '') + '+shares*px').strip('+')
                except Exception:
                    pass
            # 台股再補一次官方估值（Yahoo 可能補了價）
            if is_tw:
                _apply_bwibbu(res_out, clean)
            return res_out

        out = _fetch_all(sym)

        # .TW miss → .TWO：僅在「尚無估值／市值」且 .TWO 未列死號時試一次（不再整串 cascade 兩輪）
        if (sym.endswith('.TW') and not sym.endswith('.TWO')
            and out.get('trailingPE') is None and out.get('eps') is None
            and out.get('marketCap') is None):
            otc = sym[:-3] + '.TWO'
            if not _yf_is_dead(otc):
                otc_out = _fetch_all(otc, allow_yahoo_heavy=True)
                if (otc_out.get('trailingPE') is not None or otc_out.get('eps') is not None
                    or otc_out.get('marketCap') is not None or otc_out.get('regularMarketPrice') is not None):
                    out = otc_out
                    out['_resolved'] = otc

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
            out['sharesOutstanding'] = (
                info.get('sharesOutstanding') or info.get('impliedSharesOutstanding')
            )
            # 殖利率:yfinance 的 dividendYield 在不同版本是小數(0.025)或百分比(2.5),
            # 舊的「<1 就×100」會把真實低於 1% 的殖利率(如台達電 0.59%)誤放大成 59%。
            # 改:優先用「每股配息 ÷ 價格」無歧義計算;無配息率才退回 dividendYield(僅極小值當比例×100)
            # 並夾合理範圍(離譜值視為資料異常→不顯示,避免誤導)。
            _price = info.get('regularMarketPrice') or info.get('currentPrice') or info.get('previousClose')
            _drate = info.get('trailingAnnualDividendRate') or info.get('dividendRate')
            _yld = None
            if isinstance(_drate, (int, float)) and isinstance(_price, (int, float)) and _price > 0:
                _yld = _drate / _price * 100.0
            else:
                dy = info.get('dividendYield')
                if isinstance(dy, (int, float)):
                    _yld = dy * 100.0 if dy < 0.3 else dy
            if isinstance(_yld, (int, float)) and (_yld < 0 or _yld > 40):
                _yld = None
            out['dividendYield'] = _yld
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
            eg = info.get('earningsGrowth')
            out['earningsGrowth']    = (eg * 100) if eg is not None else None
            # 三率：yfinance 多為 0~1 小數 → 轉成百分比，供 /fundamental 美股評分
            def _margin_pct(v):
                if v is None:
                    return None
                try:
                    x = float(v)
                except Exception:
                    return None
                if abs(x) <= 1.5:
                    x *= 100.0
                return round(x, 2)
            out['grossMargin'] = _margin_pct(info.get('grossMargins'))
            out['opMargin']    = _margin_pct(info.get('operatingMargins'))
            out['netMargin']   = _margin_pct(info.get('profitMargins'))
            roe = info.get('returnOnEquity')
            out['roe'] = _margin_pct(roe)
        except Exception as e:
            print(f'[keystats-yf] {sym} failed: {e}')
            out['_error'] = str(e)
        return out

    def _fetch_keystats_v10(self, sym):
        """Yahoo v10 quoteSummary — 只走 crumb；死號／401／404 負向快取，不再打無 crumb（必 401）。"""
        out = {'symbol': sym, '_source': 'yahoo-v10'}
        if _yf_is_dead(sym):
            out['_error'] = 'dead-cached'
            return out
        try:
            r0 = _yahoo_quote_summary(sym)
            if not r0:
                out['_error'] = 'no result'
                return out
            out['_source'] = 'yahoo-v10-crumb'
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
            out['sharesOutstanding'] = (
                raw(ks, 'sharesOutstanding') or raw(pr, 'sharesOutstanding')
                or raw(fd, 'sharesOutstanding')
            )
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
            eg = raw(fd, 'earningsGrowth')
            out['earningsGrowth'] = (eg * 100) if eg is not None else None
            def _margin_pct(v):
                if v is None:
                    return None
                try:
                    x = float(v)
                except Exception:
                    return None
                if abs(x) <= 1.5:
                    x *= 100.0
                return round(x, 2)
            out['grossMargin'] = _margin_pct(raw(fd, 'grossMargins'))
            out['opMargin']    = _margin_pct(raw(fd, 'operatingMargins'))
            out['netMargin']   = _margin_pct(raw(fd, 'profitMargins'))
            out['roe']         = _margin_pct(raw(fd, 'returnOnEquity'))
        except urllib.error.HTTPError as e:
            if e.code in (401, 404):
                _yf_mark_dead(sym)
            out['_error'] = str(e.code)
        except Exception as e:
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
        except urllib.error.HTTPError as e:
            if e.code in (401, 404):
                _yf_mark_dead(sym)
            out['_error'] = str(e.code)
        except Exception as e:
            out['_error'] = str(e)
        return out

    def _handle_holders(self, rest):
        """籌碼集中度（TDCC 集保股權分散）。
           /holders/2330 — 快照+評分
           /holders/chart/2330 — 多序列圖
           /holders/refresh — 更新當週
           /holders/backfill?weeks=104 — 背景回補
        """
        try:
            import tdcc_holders as th
        except Exception as e:
            self._err('tdcc_holders import failed: ' + str(e), 500); return
        rest = (rest or '').strip()
        qs = parse_qs(urlparse(self.path).query)
        if rest in ('refresh', 'update'):
            try:
                data = th.refresh_latest()
                self._ok(json.dumps(data, ensure_ascii=False).encode()); return
            except Exception as e:
                self._err('holders refresh failed: ' + str(e), 500); return
        if rest in ('backfill', 'archive'):
            weeks = int(qs.get('weeks', ['104'])[0] or 104)
            th.start_background_backfill(weeks=weeks)
            self._ok(json.dumps({'ok': True, 'started': True, 'weeks': weeks}, ensure_ascii=False).encode()); return
        if rest.startswith('chart/'):
            code = rest.split('/', 1)[1].strip()
            if not code:
                self._err('missing code', 400); return
            try:
                data = th.get_chart(code, ensure=True)
                self._ok(json.dumps(data, ensure_ascii=False).encode()); return
            except Exception as e:
                self._err('holders chart failed: ' + str(e), 500); return
        # snapshot
        code = rest.split('/')[0].strip()
        if not code:
            self._err('missing code', 400); return
        try:
            data = th.stock_snapshot(code)
            self._ok(json.dumps(data, ensure_ascii=False).encode()); return
        except Exception as e:
            self._err('holders failed: ' + str(e), 500); return

    def _handle_chip(self, sym):
        """法人籌碼面板 — 委派 chip_api（全市場快照 + 熔斷 + 非個股短路）。"""
        import chip_api as ca
        clean = sym.replace('.TW', '').replace('.TWO', '').strip().upper()
        from datetime import date as _date
        today = _date.today().strftime('%Y%m%d')
        # 個股短快取（全市場表另有 30 分快照）
        key = f'chip:{clean}:{today}'
        c = _cache.get(key)
        if c is not None:
            self._ok(c); return
        out = ca.build_chip(sym)
        body = json.dumps(out, ensure_ascii=False).encode()
        # 非個股也 cache，避免指數切來切去重打
        _cache.set(key, body, ttl=120)
        self._ok(body)

    def _handle_fundamental(self, sym):
        """基本面：成長 + 獲利三率 + 評分 0~100。
           TW 個股：TWSE OpenAPI；US 個股：Yahoo keystats
           大盤指數（^TWII/^TWOII）／融資維持率：大盤體質（量能+法人+融資+估值）"""
        from datetime import date as _date
        today = _date.today().strftime('%Y%m%d')
        clean = sym.replace('.TW', '').replace('.TWO', '').strip().upper()
        # 籌碼集中度圖（__HOLDERS_2330__）
        try:
            import tdcc_holders as th
            if th.is_holders_sym(clean) or th.parse_holders_sym(clean):
                key = f'fund:HOLD:{clean}:{today}'
                c = _cache.get(key)
                if c is not None:
                    self._ok(c); return
                out = th.fundamental_payload(clean)
                body = json.dumps(out, ensure_ascii=False).encode()
                _cache.set(key, body)
                self._ok(body)
                return
        except Exception as e:
            print('[fundamental] holders failed:', e)
        # 融資週期（槓桿臨界）— 獨立指標，不走大盤體質
        if clean in ('__TW_MARGIN_CYCLE__', '__MARGIN_CYCLE__'):
            key = f'fund:MCYCLE:{today}'
            c = _cache.get(key)
            if c is not None:
                self._ok(c); return
            try:
                import margin_cycle as mc
                out = mc.fundamental_payload(sym)
                body = json.dumps(out, ensure_ascii=False).encode()
                _cache.set(key, body)
                self._ok(body)
            except Exception as e:
                print('[fundamental] margin cycle failed:', e)
                self._ok(json.dumps({
                    'symbol': sym, 'code': clean, 'date': today,
                    'market': 'TW', 'kind': 'margin_cycle', 'title': '融資週期',
                    'revenue': None, 'income': None, 'score': None,
                    '_note': '融資週期計算失敗：' + str(e),
                }, ensure_ascii=False).encode())
            return
        # 台股大盤／融資維持／台合成序列 → 大盤體質（非個股財報）
        if _is_tw_market_fund_sym(clean):
            key = f'fund:MKT:{clean}:{today}'
            c = _cache.get(key)
            if c is not None:
                self._ok(c); return
            out = _build_tw_market_fundamental(sym)
            body = json.dumps(out, ensure_ascii=False).encode()
            _cache.set(key, body)
            self._ok(body)
            return
        # 美總經追蹤圖：市場風險評分（非公司財報）
        if clean in ('__US_RATES_CREDIT__', '__US_CPI_FIN__'):
            key = f'fund:RISK:{clean}:{today}'
            c = _cache.get(key)
            if c is not None:
                self._ok(c); return
            try:
                import macro_track as mt
                import market_risk as mr
                chart = mt.get_chart(clean)
                risk = (chart.get('risk') if isinstance(chart, dict) else None) or {}
                if not risk:
                    risk = (mr.build_us_rates_credit_risk(chart.get('series') or [])
                            if clean == '__US_RATES_CREDIT__'
                            else mr.build_us_cpi_fin_risk(chart.get('series') or []))
                out = {
                    'symbol': sym, 'code': clean, 'date': today,
                    'market': 'US',
                    'kind': 'market_risk',
                    'title': risk.get('title') or '市場風險',
                    'direction': 'alert',
                    'revenue': None, 'income': None,
                    'score': risk.get('score'),
                    'label': risk.get('label'),
                    'summary': risk.get('summary'),
                    'plainSummary': risk.get('plainSummary'),
                    'pillars': risk.get('pillars'),
                    'marketRows': risk.get('marketRows') or [],
                    'algo': risk.get('algo'),
                    '_source': risk.get('_source') or 'macro_track + market_risk',
                }
                body = json.dumps(out, ensure_ascii=False).encode()
                _cache.set(key, body)
                self._ok(body)
            except Exception as e:
                print('[fundamental] US market risk failed:', e)
                self._ok(json.dumps({
                    'symbol': sym, 'code': clean, 'date': today,
                    'market': 'US', 'kind': 'market_risk', 'title': '市場風險',
                    'revenue': None, 'income': None, 'score': None,
                    '_note': '市場風險計算失敗：' + str(e),
                }, ensure_ascii=False).encode())
            return
        # 美總經／其他指數／合成序列：無公司財報，回明確空狀態（勿誤走 Yahoo 公司）
        if _is_macro_sym(clean) or _is_index_sym(clean):
            is_us = clean.startswith('__US_') or (clean.startswith('^') and not _is_tw_index_sym(clean))
            out = {
                'symbol': sym, 'code': clean, 'date': today,
                'market': 'US' if is_us else 'TW',
                'kind': 'macro' if _is_macro_sym(clean) else 'index',
                'title': '總經序列' if _is_macro_sym(clean) else '指數',
                'revenue': None, 'income': None, 'score': None,
                '_note': ('總經追蹤圖無個股基本面評分' if _is_macro_sym(clean)
                          else '非台股大盤指數，無大盤體質／公司財報評分'),
            }
            self._ok(json.dumps(out, ensure_ascii=False).encode()); return

        is_tw = bool(_CODE4.match(clean)) or sym.endswith('.TW') or sym.endswith('.TWO')
        key = f'fund:{"TW" if is_tw else "US"}:{clean}:{today}'
        c = _cache.get(key)
        if c is not None:
            self._ok(c); return

        out = {
            'symbol': sym, 'code': clean, 'date': today,
            'market': 'TW' if is_tw else 'US',
            'revenue': None, 'income': None, 'score': None,
        }

        if not is_tw:
            # 美股：共用 /keystats 鏈（yfinance → v10 → html），對齊成長／三率後走同一套 _fundamental_score
            ks = self._fetch_keystats_yfinance(clean)
            need = (
                ks.get('revenueGrowth') is None
                and ks.get('earningsGrowth') is None
                and ks.get('grossMargin') is None
                and ks.get('opMargin') is None
                and ks.get('netMargin') is None
                and ks.get('eps') is None
            )
            if need or (
                ks.get('grossMargin') is None and ks.get('opMargin') is None
                and ks.get('revenueGrowth') is None
            ):
                v10 = self._fetch_keystats_v10(clean)
                for k in ('revenueGrowth', 'earningsGrowth', 'earningsQuarterlyGrowth',
                          'grossMargin', 'opMargin', 'netMargin', 'roe', 'eps',
                          'regularMarketPrice', '_source'):
                    if ks.get(k) is None and v10.get(k) is not None:
                        ks[k] = v10[k]
            # 成長：營收 YoY + 盈餘成長（季／年；有哪個用哪個）
            yoy = ks.get('revenueGrowth')
            earn = ks.get('earningsGrowth')
            if earn is None:
                earn = ks.get('earningsQuarterlyGrowth')
            if yoy is not None or earn is not None:
                out['revenue'] = {
                    'period': 'Yahoo TTM',
                    'monthRev': None,
                    'yoyPct': yoy,
                    'momPct': None,
                    'cumRev': None,
                    'cumYoyPct': earn,
                    'label': '營收／盈餘成長',
                }
            if (ks.get('grossMargin') is not None or ks.get('opMargin') is not None
                    or ks.get('netMargin') is not None or ks.get('eps') is not None):
                out['income'] = {
                    'period': 'Yahoo TTM',
                    'sales': None,
                    'eps': ks.get('eps'),
                    'grossMargin': ks.get('grossMargin'),
                    'opMargin': ks.get('opMargin'),
                    'netMargin': ks.get('netMargin'),
                    'roe': ks.get('roe'),
                }
            out['_source'] = ks.get('_source') or 'yahoo-keystats'
            if ks.get('_error') and not out['revenue'] and not out['income']:
                out['_error'] = ks.get('_error')
            out['score'] = _fundamental_score(out)
            body = json.dumps(out, ensure_ascii=False).encode()
            _cache.set(key, body)
            self._ok(body)
            return

        # ── 台股 ──────────────────────────────────────────────
        # 月營收（欄位用「含子字串」模糊比對：TWSE 欄位有前綴如「營業收入-當月營收」）
        rev = _openapi_lookup(['t187ap05_L', 'tpex:mopsfin_t187ap05_O'], clean)
        if rev:
            out['revenue'] = {
                'period':    rev.get('資料年月'),
                'monthRev':  _pick_num(rev, ['當月營收'], ['累計']),
                'yoyPct':    _pick_num(rev, ['去年同月增減']),
                'momPct':    _pick_num(rev, ['上月比較增減']),
                'cumRev':    _pick_num(rev, ['當月累計營收']),
                'cumYoyPct': _pick_num(rev, ['累計', '前期比較增減']),
            }
        # 官方 OpenAPI 無 per-company 上櫃月營收 → 退 MOPS 公開資訊觀測站(otc;上市 sii 備援)
        if not (out['revenue'] and out['revenue'].get('monthRev') is not None):
            for mk in ('otc', 'sii'):
                mr = _mops_monthly_revenue(mk, clean)
                if mr and mr.get('monthRev') is not None:
                    out['revenue'] = {
                        'period':    mr.get('period'),
                        'monthRev':  mr.get('monthRev'),
                        'yoyPct':    mr.get('yoyPct'),
                        'momPct':    mr.get('momPct'),
                        'cumRev':    mr.get('cumRev'),
                        'cumYoyPct': mr.get('cumYoyPct'),
                    }
                    out['_revSource'] = 'MOPS:' + mk
                    break
        # 綜合損益表 → 三率（同樣模糊比對，避免全形/半形括號差異 例 營業毛利（毛損））
        inc = _openapi_lookup(['t187ap06_L_ci', 'tpex:mopsfin_t187ap06_O_ci', 't187ap06_L'], clean)
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

    def _handle_valuation(self, sym):
        """長線估值錨 (v3.8 #2 本益比河流)：當前 PER/PBR/殖利率 + EPS_ttm。
           TW: TWSE OpenAPI BWIBBU_ALL（上市個股本益比/殖利率/股價淨值比）。
           US: 走 /keystats 的 trailingPE / priceToBook（Yahoo）。
           前端用此 EPS_ttm × 倍數 + 歷史股價算河流帶與便宜/昂貴百分位。"""
        from datetime import date as _date
        today = _date.today().strftime('%Y%m%d')
        clean = sym.replace('.TW', '').replace('.TWO', '').strip().upper()
        is_tw = bool(_CODE4.match(clean)) or sym.endswith('.TW') or sym.endswith('.TWO')
        key = f'val:{clean}:{today}'
        c = _cache.get(key)
        if c is not None:
            self._ok(c); return
        out = {'symbol': sym, 'code': clean, 'date': today, 'market': 'TW' if is_tw else 'US',
               'per': None, 'pbr': None, 'yieldPct': None, 'epsTtm': None, 'price': None}
        if is_tw:
            # v3.8.1：BWIBBU_ALL 正確路徑是 exchangeReport/（舊 opendata/ 404），
            # 且該資料集是英文欄位(Code/PEratio/PBratio/DividendYield)、無收盤價。
            # 上櫃股 TWSE 查不到 → 退 TPEx peratio 資料集。
            row = _openapi_lookup(['exchangeReport/BWIBBU_ALL', 'BWIBBU_ALL'], clean)
            out['_source'] = 'TWSE BWIBBU_ALL'
            if not row:
                row = _openapi_lookup(['tpex:tpex_mainboard_peratio_analysis'], clean)
                out['_source'] = 'TPEx peratio'
            if row:
                out['per']      = (_pick_num(row, ['本益比']) or _pick_num(row, ['PEratio'])
                                   or _pick_num(row, ['PriceEarningRatio']))
                out['pbr']      = (_pick_num(row, ['股價淨值比']) or _pick_num(row, ['PBratio'])
                                   or _pick_num(row, ['PriceBookRatio']))
                out['yieldPct'] = _pick_num(row, ['殖利率']) or _pick_num(row, ['Yield'])
                out['price']    = _pick_num(row, ['收盤']) or _pick_num(row, ['ClosingPrice'])
            else:
                out['_source'] = None
                print(f'[valuation] {clean}: not in BWIBBU_ALL / TPEx peratio')
            # 收盤價備援 1：TWSE 全市場日收盤
            if out['price'] is None:
                srow = _openapi_lookup(['exchangeReport/STOCK_DAY_ALL'], clean)
                if srow:
                    out['price'] = _pick_num(srow, ['ClosingPrice']) or _pick_num(srow, ['收盤'])
            # 收盤價備援 2：Yahoo 即時（.TW 再試 .TWO）
            if out['price'] is None:
                for suf in ('.TW', '.TWO'):
                    try:
                        u = f'https://query1.finance.yahoo.com/v8/finance/chart/{clean}{suf}?range=1d&interval=1d'
                        req = urllib.request.Request(u, headers=YF_HEADERS)
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            jj = json.loads(resp.read())
                        p = ((jj.get('chart', {}).get('result') or [{}])[0].get('meta') or {}).get('regularMarketPrice')
                        if p:
                            out['price'] = p
                            break
                    except Exception:
                        pass
            if out['per'] and out['price']:
                out['epsTtm'] = round(out['price'] / out['per'], 2)
        else:
            # 美股 (v3.8.1)：直打 v10 quoteSummary 需 crumb 常 401 → 全 None。
            # 改共用 /keystats 的取得鏈：yfinance(內建 cookie/crumb) → v10 → HTML scrape。
            # 三個 helper 已統一鍵名：trailingPE/priceToBook/dividendYield(%)/eps/regularMarketPrice。
            ks = self._fetch_keystats_yfinance(clean)
            if ks.get('trailingPE') is None and ks.get('eps') is None and ks.get('marketCap') is None:
                v10 = self._fetch_keystats_v10(clean)
                for k in ('trailingPE', 'priceToBook', 'dividendYield', 'eps', 'regularMarketPrice'):
                    if ks.get(k) is None and v10.get(k) is not None:
                        ks[k] = v10[k]
                if v10.get('trailingPE') is not None:
                    ks['_source'] = 'yahoo-v10'
            if ks.get('trailingPE') is None and ks.get('eps') is None:
                h = self._fetch_keystats_html(clean)
                for k in ('trailingPE', 'priceToBook', 'dividendYield', 'eps', 'regularMarketPrice'):
                    if ks.get(k) is None and h.get(k) is not None:
                        ks[k] = h[k]
                if h.get('trailingPE') is not None:
                    ks['_source'] = 'yahoo-html'
            out['_source']  = ks.get('_source')
            out['per']      = ks.get('trailingPE')
            out['pbr']      = ks.get('priceToBook')
            out['yieldPct'] = ks.get('dividendYield')   # helper 已轉成 %
            out['epsTtm']   = ks.get('eps')
            out['price']    = ks.get('regularMarketPrice')
            # EPS 缺但有 PER+價 → 反推；PER 缺但有 EPS+價 → 反推
            if out['epsTtm'] is None and out['per'] and out['price']:
                out['epsTtm'] = round(out['price'] / out['per'], 2)
            if out['per'] is None and out['epsTtm'] and out['price'] and out['epsTtm'] > 0:
                out['per'] = round(out['price'] / out['epsTtm'], 2)
            if out['per'] is None and out['epsTtm'] is None:
                print(f'[valuation] US {clean}: yfinance/v10/html 全失敗 ({ks.get("_error")})')
        body = json.dumps(out, ensure_ascii=False).encode()
        _cache.set(key, body, ttl=1800)
        self._ok(body)

    def _handle_marketflow(self):
        """大盤資金流儀表板 (v3.8 #3)：
           • 量能趨勢 FMTQIK（近月每日成交金額，呼應 8000億→1.2兆）
           • 三大法人買賣金額 BFI82U（外資/投信/自營 買賣差）
           • 融資融券大盤 MI_MARGN tables[0] 摘要
           僅 TW。整批快取 30 分。"""
        from datetime import date as _date
        today = _date.today()
        key = f'marketflow:{today.strftime("%Y%m%d")}'
        c = _cache.get(key)
        if c is not None:
            self._ok(c); return
        out = {'date': today.strftime('%Y-%m-%d'), 'turnover': [], 'inst': None, 'margin': None}
        ym1 = today.strftime('%Y%m01')
        # 量能趨勢 FMTQIK（當月每日；金額單位元）
        try:
            url = f'https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={ym1}&response=json'
            req = urllib.request.Request(url, headers=YF_HEADERS)
            with urllib.request.urlopen(req, timeout=12) as resp:
                d = json.loads(resp.read())
            if d.get('stat') in ('OK', 'ok'):
                fields = d.get('fields') or []
                rows = d.get('data') or []
                i_date = next((i for i, f in enumerate(fields) if '日期' in f), 0)
                i_amt  = next((i for i, f in enumerate(fields) if '成交金額' in f), 1)
                i_idx  = next((i for i, f in enumerate(fields) if '指數' in f), None)
                i_chg  = next((i for i, f in enumerate(fields) if '漲跌點數' in f), None)
                for row in rows:
                    try:
                        amt = float(str(row[i_amt]).replace(',', ''))
                    except Exception:
                        continue
                    rec = {'date': str(row[i_date]).strip(), 'amount': amt}
                    if i_idx is not None:
                        try: rec['index'] = float(str(row[i_idx]).replace(',', ''))
                        except Exception: pass
                    if i_chg is not None:
                        try: rec['chg'] = float(str(row[i_chg]).replace(',', ''))
                        except Exception: pass
                    out['turnover'].append(rec)
        except Exception as e:
            print(f'[marketflow] FMTQIK failed: {e}')
        # 三大法人買賣金額 BFI82U（往前找最近一個有資料的交易日）
        try:
            from datetime import timedelta
            for back in range(0, 7):
                dd = (today - timedelta(days=back)).strftime('%Y%m%d')
                url = f'https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate={dd}&type=day&response=json'
                req = urllib.request.Request(url, headers=YF_HEADERS)
                with urllib.request.urlopen(req, timeout=12) as resp:
                    d = json.loads(resp.read())
                if d.get('stat') not in ('OK', 'ok'):
                    continue
                fields = d.get('fields') or []
                rows = d.get('data') or []
                i_name = next((i for i, f in enumerate(fields) if '單位名稱' in f or '買賣別' in f), 0)
                i_net  = next((i for i, f in enumerate(fields) if '買賣差' in f or '買賣超' in f), len(fields) - 1)
                inst = {'foreign': None, 'trust': None, 'dealer': None, 'date': dd}
                for row in rows:
                    nm = str(row[i_name])
                    try: net = float(str(row[i_net]).replace(',', ''))
                    except Exception: continue
                    if '外' in nm: inst['foreign'] = (inst['foreign'] or 0) + net
                    elif '投信' in nm: inst['trust'] = net
                    elif '自營' in nm: inst['dealer'] = (inst['dealer'] or 0) + net
                if any(v is not None for k, v in inst.items() if k != 'date'):
                    out['inst'] = inst
                    break
        except Exception as e:
            print(f'[marketflow] BFI82U failed: {e}')
        # 融資融券大盤摘要 MI_MARGN tables[0]
        try:
            url = f'https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={today.strftime("%Y%m%d")}&selectType=ALL&response=json'
            req = urllib.request.Request(url, headers=YF_HEADERS)
            with urllib.request.urlopen(req, timeout=12) as resp:
                d = json.loads(resp.read())
            if d.get('stat') in ('OK', 'ok'):
                tables = d.get('tables') or []
                if tables:
                    t0 = tables[0]
                    fields = t0.get('fields') or []
                    rows = t0.get('data') or []
                    summ = {}
                    for row in rows:
                        label = str(row[0]) if row else ''
                        if '融資' in label and '金額' in label:
                            try: summ['marginAmt'] = float(str(row[-1]).replace(',', ''))
                            except Exception: pass
                    out['margin'] = {'raw': rows[:6]} if rows else None
        except Exception as e:
            print(f'[marketflow] MI_MARGN failed: {e}')
        body = json.dumps(out, ensure_ascii=False).encode()
        _cache.set(key, body, ttl=1800)
        self._ok(body)

    def _handle_pulse(self):
        """市場脈動情報 (merge tw-pulse-terminal UX)：因子帳本 + 雙軌健康／風險。
           GET /pulse → pulse_intel.build_pulse_intel(...) + 即時快照欄位。
           重用 breadth / marketflow / txf / sectors 快取與 _build_tw_market_fundamental；
           缺資料進 pendingFactors，不捏造分數。快取 45s。"""
        from datetime import date as _date
        qs = parse_qs(urlparse(self.path).query)
        force = (qs.get('refresh', ['0'])[0] or '0') in ('1', 'true', 'yes')
        key = f'pulse:v1:{_date.today().strftime("%Y%m%d")}:{int(time.time() // 45)}'
        if not force:
            c = _cache.get(key)
            if c is not None:
                self._ok(c); return

        def _loads(raw):
            if raw is None:
                return None
            try:
                return json.loads(raw.decode('utf-8') if isinstance(raw, (bytes, bytearray)) else raw)
            except Exception:
                return None

        def _cache_first(keys):
            for k in keys:
                d = _loads(_cache.get(k))
                if d is not None:
                    return d
            return None

        today = _date.today()
        ymd = today.strftime('%Y%m%d')
        y_m_d = today.strftime('%Y-%m-%d')

        # 延伸因子與體質並行：OI／借券／NHNL／類股（獨立 executor，避免佔滿全域 pool）
        extras_fut = None
        try:
            import pulse_extras as _pulse_extras
            extras_budget = 7.5 if force else 5.5
            extras_fut = _pool.submit(lambda b=extras_budget: _pulse_extras.fetch_all(budget=b))
        except Exception as e:
            print('[pulse] extras submit', e)

        # 1) 體質（權威來源）
        fund = {}
        try:
            fund = _build_tw_market_fundamental('^TWII') or {}
        except Exception as e:
            print('[pulse] fundamental', e)
            fund = {}

        # 2) 廣度／指數／法人 — 優先快取（由 /breadth /marketflow 預熱）
        bd = _cache_first([f'breadth:v1:{ymd}'])
        mf = _cache_first([f'marketflow:{ymd}', f'marketflow:{y_m_d}'])
        sec = _cache_first([
            f'sectors:{ymd}',
            f'sectors:TW:yahoo:{ymd}',
            f'sectors:TW:{ymd}',
        ])
        txf = _cache_first([f'txf:{int(time.time() // 20)}', f'txf:{int(time.time() // 20) - 1}'])

        # 廣度／盤後快取未命中時不呼叫其他 _handle_*（會弄亂 HTTP 回應）。
        # 改以背景預熱：完整度下降並進 pending；使用者開過「廣度／盤後」後自動變完整。
        # 指數可直取 MIS；台指期可直取既有解析（不經 _handle_txf）。
        indices = (bd or {}).get('indices') or {}
        if not (indices.get('t00') or {}).get('price'):
            try:
                indices = _twse_mis_index('tse_t00.tw|otc_o00.tw') or {}
            except Exception as e:
                print('[pulse] twindex', e)
                indices = indices or {}

        stocks = (bd or {}).get('stocks') if bd else None
        inst = (mf or {}).get('inst') if mf else None
        if inst is None and bd:
            inst = bd.get('inst')

        # 夜盤：快取未命中則輕量直取（與 _handle_txf 同源 helper）
        txf_night = None
        if txf and txf.get('ok'):
            n = txf.get('night')
            if n and n.get('price') is not None:
                txf_night = n
            elif txf.get('price') is not None and (
                txf.get('session') == 'night' or txf.get('ampRate') is not None
            ):
                txf_night = txf
        if txf_night is None:
            try:
                n = self._txf_mis_session(1)
                if n and n.get('price') is not None:
                    txf_night = n
            except Exception as e:
                print('[pulse] txf night', e)

        sectors = []
        if isinstance(sec, dict):
            sectors = sec.get('sectors') or sec.get('list') or []
        elif isinstance(sec, list):
            sectors = sec

        # 延伸因子（類股／OI／借券賣出／250日 NHNL）— 與體質並行，失敗進 pending
        extras = {'sectors': None, 'txOi': None, 'sbl': None, 'nhnl': None}
        if extras_fut is not None:
            try:
                extras = extras_fut.result(timeout=8.0) or extras
            except Exception as e:
                print('[pulse] extras', e)
                extras = {'sectors': None, 'txOi': None, 'sbl': None, 'nhnl': None}

        if not sectors:
            ex_sec = extras.get('sectors') if isinstance(extras, dict) else None
            if isinstance(ex_sec, dict) and ex_sec.get('sectors'):
                sectors = ex_sec.get('sectors') or []
                try:
                    _cache.set(
                        f'sectors:{ymd}',
                        json.dumps({'ok': True, 'sectors': sectors, 'source': ex_sec.get('source')},
                                   ensure_ascii=False).encode(),
                        ttl=300,
                    )
                except Exception:
                    pass

        tx_oi = extras.get('txOi') if isinstance(extras, dict) else None
        sbl = extras.get('sbl') if isinstance(extras, dict) else None
        nhnl = extras.get('nhnl') if isinstance(extras, dict) else None

        sources = {
            'twindex': bool((indices.get('t00') or {}).get('price') is not None),
            'breadth': bool(stocks and stocks.get('advRatio') is not None),
            'marketflow': bool(mf and (mf.get('turnover') or mf.get('inst'))),
            'health': fund.get('score') is not None,
            'margin': (fund.get('pillars') or {}).get('marginRatio') is not None,
            'valuation': (fund.get('pillars') or {}).get('medianPE') is not None,
            'txf': bool(txf_night and txf_night.get('price') is not None),
            'sectors': bool(sectors),
            'txOi': bool(isinstance(tx_oi, dict) and tx_oi.get('oi') is not None
                         and tx_oi.get('oiChgPct') is not None),
            'sbl': bool(isinstance(sbl, dict) and sbl.get('sblSellYi') is not None),
            'nhnl': bool(isinstance(nhnl, dict) and nhnl.get('sampleN')
                         and nhnl.get('newHighs') is not None
                         and nhnl.get('newLows') is not None),
        }

        try:
            import pulse_intel as pi
            out = pi.build_pulse_intel(
                health_score=fund.get('score'),
                pillars=fund.get('pillars'),
                market_rows=fund.get('marketRows'),
                summary=fund.get('summary'),
                stocks=stocks,
                indices=indices,
                inst=inst or {},
                txf_night=txf_night,
                sectors=sectors,
                sources_present=sources,
                tx_oi=tx_oi if isinstance(tx_oi, dict) else None,
                sbl=sbl if isinstance(sbl, dict) else None,
                nhnl=nhnl if isinstance(nhnl, dict) else None,
            )
        except Exception as e:
            print('[pulse] build', e)
            out = {'ok': False, 'error': f'pulse build failed: {e}'}

        # 附帶列表資料供前端一次渲染（減少 round-trip）
        out['date'] = (bd or {}).get('date')
        out['breadthOk'] = bool(bd and bd.get('ok'))
        out['indices'] = indices
        out['stocks'] = stocks
        out['inst'] = inst
        out['txf'] = txf_night
        out['marketflow'] = {
            'turnover': (mf or {}).get('turnover'),
            'inst': inst,
        } if mf else None
        out['sectors'] = sectors
        out['extras'] = {
            'txOi': tx_oi if isinstance(tx_oi, dict) else None,
            'sbl': sbl if isinstance(sbl, dict) else None,
            'nhnl': nhnl if isinstance(nhnl, dict) else None,
            'sectorsSource': (extras.get('sectors') or {}).get('source')
            if isinstance(extras.get('sectors'), dict) else None,
        }
        out['updatedAt'] = time.strftime('%Y-%m-%dT%H:%M:%S')

        # ── Overview 儀表板擴充（對齊 tw-pulse 參考圖）──────────────
        # movers / global / macro 並行；總預算 ~8s（FRED 在此環境常逾時，必須 fail-fast）
        PULSE_SIDE_BUDGET = 8.0

        def _job_movers():
            m = _cache_first([f'movers:v1:{ymd}'])
            if m is not None:
                return m
            try:
                m = _fetch_day_movers(8)
                if m and m.get('ok'):
                    _cache.set(f'movers:v1:{ymd}', json.dumps(m, ensure_ascii=False).encode(), ttl=300)
                return m
            except Exception as e:
                print('[pulse] movers', e)
                return {'ok': False, 'gainers': [], 'losers': []}

        def _job_global():
            gkey = f'pulse-global:{int(time.time() // 120)}'
            g = _cache_first([gkey])
            if g is not None:
                return g
            try:
                g = _yf_batch_quotes(['^DJI', '^GSPC', '^IXIC', 'CL=F', 'DX-Y.NYB'])
                if not any(x.get('symbol') == 'DX-Y.NYB' for x in (g or [])):
                    # 僅在缺美元指數時補一槍，不重抓整批
                    extra = _yf_batch_quotes(['DX=F'])
                    if extra:
                        g = list(g or []) + list(extra)
                _cache.set(gkey, json.dumps(g, ensure_ascii=False).encode(), ttl=120)
                return g
            except Exception as e:
                print('[pulse] global', e)
                return []

        def _job_macro():
            """快取優先；未命中才短逾時抓 FRED（timeout=3, retries=1）。"""
            u10 = None
            eco_rows = []
            try:
                u10 = _macro_latest('us10y', years=5, timeout=3, retries=1)
            except Exception as e:
                print('[pulse] us10y', e)
            for mk in ('unrate', 'us_cpi_yoy', 'tw_cpi'):
                try:
                    # 先只讀快取；沒有再短抓（tw_cpi 走政府源，允許稍長）
                    row = _macro_latest(mk, years=10, timeout=3, retries=1,
                                        allow_fetch=(mk == 'tw_cpi'))
                    if row is None and mk != 'tw_cpi':
                        row = _macro_latest(mk, years=10, timeout=3, retries=1, allow_fetch=True)
                    if row:
                        eco_rows.append(row)
                except Exception as e:
                    print('[pulse] macro', mk, e)
            return u10, eco_rows

        movers = {'ok': False, 'gainers': [], 'losers': []}
        global_q = []
        us10y = None
        eco = []
        # 獨立 executor：並行等待用 wait()，不再串行 .result(25)+.result(20)
        try:
            from concurrent.futures import wait as _fut_wait
            with ThreadPoolExecutor(max_workers=3, thread_name_prefix='pulse-side') as _pex:
                f_m = _pex.submit(_job_movers)
                f_g = _pex.submit(_job_global)
                f_e = _pex.submit(_job_macro)
                done, _pending = _fut_wait([f_m, f_g, f_e], timeout=PULSE_SIDE_BUDGET)
                if f_m in done:
                    try:
                        movers = f_m.result() or movers
                    except Exception as e:
                        print('[pulse] movers result', e)
                if f_g in done:
                    try:
                        global_q = f_g.result() or []
                    except Exception as e:
                        print('[pulse] global result', e)
                if f_e in done:
                    try:
                        us10y, eco = f_e.result()
                        eco = eco or []
                    except Exception as e:
                        print('[pulse] macro result', e)
                else:
                    # macro 逾時：仍試讀既有快取（不觸發網路）
                    try:
                        us10y = _macro_latest('us10y', years=5, allow_fetch=False)
                        for mk in ('unrate', 'us_cpi_yoy', 'tw_cpi'):
                            row = _macro_latest(mk, years=10, allow_fetch=False)
                            if row:
                                eco.append(row)
                    except Exception:
                        pass
        except Exception as e:
            print('[pulse] overview parallel', e)

        # 事件快訊（非新聞爬蟲）
        flash = []
        try:
            ev = _cache_first([f'events:{ymd}:', f'events:{ymd}'])
            if isinstance(ev, dict):
                rev = ev.get('revenue') or {}
                if rev.get('nextPublishBy'):
                    if rev.get('daysAway') is not None:
                        flash.append({
                            'time': str(rev.get('nextPublishBy')),
                            'title': f"月營收時程 {rev.get('forMonth') or ''}（尚餘 {rev.get('daysAway')} 天）",
                            'cat': '總經',
                        })
                    else:
                        flash.append({
                            'time': str(rev.get('nextPublishBy')),
                            'title': f"月營收時程 {rev.get('nextPublishBy')}",
                            'cat': '總經',
                        })
                for x in (ev.get('exDividend') or [])[:6]:
                    flash.append({
                        'time': x.get('date') or '',
                        'title': f"除權息 {x.get('code') or ''} {x.get('name') or ''} {x.get('type') or ''}".strip(),
                        'cat': '個股',
                        'code': x.get('code'),
                    })
        except Exception:
            pass
        if not flash:
            flash.append({
                'time': out.get('updatedAt') or '',
                'title': '事件中樞待命（除權息／營收時程）；非新聞爬蟲',
                'cat': '系統',
            })

        # 成交金額（億）— breadth.turnover 優先，否則 marketflow 末日
        turnover_yi = None
        to_bd = (bd or {}).get('turnover') or {}
        for k in ('stockAmt', 'totalAmt'):
            if to_bd.get(k) is not None:
                try:
                    turnover_yi = float(to_bd[k]) / 1e8
                    break
                except Exception:
                    pass
        if turnover_yi is None and mf:
            turns = mf.get('turnover') or []
            if turns and turns[-1].get('amount') is not None:
                turnover_yi = float(turns[-1]['amount']) / 1e8
        # 前日比（若有兩日）
        turnover_chg = None
        if mf and (mf.get('turnover') or []) and len(mf['turnover']) >= 2:
            try:
                a = float(mf['turnover'][-1]['amount'])
                b = float(mf['turnover'][-2]['amount'])
                if b:
                    turnover_chg = (a - b) / b * 100.0
            except Exception:
                pass

        t00 = indices.get('t00') or {}
        o00 = indices.get('o00') or {}
        st = stocks or {}
        up, dn, flat = st.get('up'), st.get('down'), st.get('unchanged')
        ls_ratio = None
        if up is not None and dn not in (None, 0):
            try:
                ls_ratio = round(float(up) / float(dn), 2)
            except Exception:
                ls_ratio = None

        skip = ('加權', '櫃買', '寶島', '公司治理', '中型', '電子工業', '未含')
        sec_ranked = []
        for s in sectors or []:
            if not isinstance(s, dict):
                continue
            nm = str(s.get('name') or '')
            cp = s.get('changePct')
            if not nm or cp is None or any(k in nm for k in skip):
                continue
            sec_ranked.append({'name': nm, 'changePct': cp, 'close': s.get('close')})
        sec_ranked.sort(key=lambda x: x['changePct'], reverse=True)

        foreign = (inst or {}).get('foreign')
        trust = (inst or {}).get('trust')
        dealer = (inst or {}).get('dealer')
        total_yi = None
        if any(v is not None for v in (foreign, trust, dealer)):
            total_yi = ((foreign or 0) + (trust or 0) + (dealer or 0)) / 1e8

        out['movers'] = movers
        out['global'] = global_q
        out['us10y'] = us10y
        out['economy'] = eco
        out['flash'] = flash
        out['overview'] = {
            'strip': {
                't00': t00,
                'o00': o00,
                'turnoverYi': round(turnover_yi, 1) if turnover_yi is not None else None,
                'turnoverChgPct': round(turnover_chg, 2) if turnover_chg is not None else None,
                'up': up, 'down': dn, 'flat': flat,
                'advRatio': st.get('advRatio'),
                'lsRatio': ls_ratio,
                'dataLabel': '官方盤後／即時混成' if out.get('breadthOk') else '部分資料可用',
            },
            'ohlc': {
                'open': t00.get('open'), 'high': t00.get('high'), 'low': t00.get('low'),
                'prevClose': t00.get('prevClose'), 'price': t00.get('price'),
                'changePct': t00.get('changePct'), 'name': t00.get('name') or '加權指數',
            },
            'institutional': {
                'foreign': foreign, 'trust': trust, 'dealer': dealer,
                'totalYi': round(total_yi, 1) if total_yi is not None else None,
                'date': (inst or {}).get('date'),
            },
            'sectorsRanked': sec_ranked[:12],
            'lsRatio': ls_ratio,
        }

        # Yahoo 補齊加權 OHLC（MIS 若缺 h/l）— 最多等 3s，不拖垮整包
        ohlc = out['overview']['ohlc']
        if ohlc.get('high') is None or ohlc.get('low') is None or ohlc.get('open') is None:
            _ohlc_box = {'data': None, 'err': None}

            def _ohlc_job():
                try:
                    _, data, _ = fetch_one('^TWII', '5d', '1d', False)
                    _ohlc_box['data'] = data
                except Exception as e:
                    _ohlc_box['err'] = e

            th = threading.Thread(target=_ohlc_job, daemon=True)
            th.start()
            th.join(3.0)
            if _ohlc_box['data']:
                try:
                    res = (json.loads(_ohlc_box['data']).get('chart') or {}).get('result') or []
                    if res:
                        q = ((res[0].get('indicators') or {}).get('quote') or [{}])[0]

                        def _last(arr):
                            for x in reversed(arr or []):
                                if x is not None:
                                    return x
                            return None

                        if ohlc.get('open') is None:
                            ohlc['open'] = _last(q.get('open'))
                        if ohlc.get('high') is None:
                            ohlc['high'] = _last(q.get('high'))
                        if ohlc.get('low') is None:
                            ohlc['low'] = _last(q.get('low'))
                        ohlc['source'] = (ohlc.get('source') or '') + '+yahoo'
                except Exception as e:
                    print('[pulse] twii ohlc', e)
            elif _ohlc_box['err']:
                print('[pulse] twii ohlc', _ohlc_box['err'])

        body = json.dumps(out, ensure_ascii=False).encode()
        if out.get('ok'):
            _cache.set(key, body, ttl=45)
            # 寫入脈動歷史庫（增量 merge；失敗不擋回應）
            try:
                import pulse_history as ph
                ph.save_pulse_score(out)
            except Exception as e:
                print('[pulse] history save', e)
        self._ok(body)

    def _handle_pulse_history(self):
        """GET /pulse/history?kind=breadth|institutional|index|pulse&n=40"""
        qs = parse_qs(urlparse(self.path).query)
        kind = (qs.get('kind', ['breadth'])[0] or 'breadth').lower()
        n = qs.get('n', ['40'])[0]
        try:
            n = int(n)
        except Exception:
            n = 40
        try:
            import pulse_history as ph
            self._ok(json.dumps(ph.history(kind=kind, n=n), ensure_ascii=False).encode())
        except Exception as e:
            self._err('pulse history failed: ' + str(e), 500)

    def _handle_sync(self):
        """POST/GET /sync?days=40&full=0 — 背景預抓歷史庫，僅 merge 新日。"""
        qs = parse_qs(urlparse(self.path).query)
        days = qs.get('days', ['40'])[0]
        try:
            days = max(5, min(120, int(days)))
        except Exception:
            days = 40
        force = (qs.get('full', ['0'])[0] or '0') in ('1', 'true', 'yes')
        try:
            import pulse_history as ph
            started = ph.start_background_sync(days=days, force_full=force)
            self._ok(json.dumps({
                'ok': True, 'started': bool(started),
                'message': '同步已啟動（背景 merge）' if started else '同步進行中',
                'status': ph.status(),
            }, ensure_ascii=False).encode())
        except Exception as e:
            self._err('sync failed: ' + str(e), 500)

    def _handle_sync_status(self):
        try:
            import pulse_history as ph
            self._ok(json.dumps(ph.status(), ensure_ascii=False).encode())
        except Exception as e:
            self._err('sync status failed: ' + str(e), 500)

    def _handle_movers(self):
        """輕量漲跌幅排行 GET /movers?n=8 — TWSE+TPEx 日收盤，供 Overview。"""
        from datetime import date as _date
        qs = parse_qs(urlparse(self.path).query)
        n = qs.get('n', ['8'])[0]
        try:
            n = int(n)
        except Exception:
            n = 8
        force = (qs.get('refresh', ['0'])[0] or '0') in ('1', 'true', 'yes')
        key = f'movers:v1:{_date.today().strftime("%Y%m%d")}'
        if not force:
            c = _cache.get(key)
            if c is not None:
                self._ok(c); return
        out = _fetch_day_movers(n)
        body = json.dumps(out, ensure_ascii=False).encode()
        if out.get('ok'):
            _cache.set(key, body, ttl=300)
        self._ok(body)

    def _handle_breadth(self):
        """大盤廣度 (v5.0 S2)：TWSE MI_INDEX type=MS 漲跌家數 + 即時指數 + 體質摘要。
           GET /breadth → {
             ok, date, source,
             stocks:{up,limitUp,down,limitDown,unchanged,unmatched,n/a,traded,advRatio,net},
             market:{...同欄位，整體市場含權證 ETF},
             turnover:{stockAmt,totalAmt,stockShares,stockTrades},
             indices:{t00,o00}, score, pillars, marketRows, inst, summary
           }
           盤中若當日尚無 MS，往前找最近交易日（最多 12 天）。快取 120s。"""
        import re as _re
        from datetime import date as _date, timedelta

        qs = parse_qs(urlparse(self.path).query)
        force = (qs.get('refresh', ['0'])[0] or '0') in ('1', 'true', 'yes')
        key = f'breadth:v1:{_date.today().strftime("%Y%m%d")}'
        if not force:
            c = _cache.get(key)
            if c is not None:
                self._ok(c); return

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
            """'892(113)' → (892, 113)；無括號則 (n, None)。"""
            t = str(s or '').replace(',', '').strip()
            m = _re.match(r'^([0-9.]+)\((\d+)\)$', t)
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
            """rows: [[類型, 整體市場, 股票], ...]；col=1 整體 / col=2 股票。"""
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
        }

        # ── 1) TWSE MI_INDEX MS：漲跌家數 + 成交統計 ───────────────
        ms_date = None
        tables = None
        for back in range(0, 12):
            dd = (_date.today() - timedelta(days=back)).strftime('%Y%m%d')
            for url in (
                f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={dd}&type=MS&response=json',
                f'https://www.twse.com.tw/exchangeReport/MI_INDEX?date={dd}&type=MS&response=json',
            ):
                try:
                    req = urllib.request.Request(url, headers=YF_HEADERS)
                    with urllib.request.urlopen(req, timeout=12) as resp:
                        d = json.loads(resp.read())
                    if d.get('stat') not in ('OK', 'ok'):
                        continue
                    tables = d.get('tables') or []
                    if not tables:
                        # 舊版扁平 data8
                        data8 = d.get('data8')
                        if data8:
                            tables = [{'title': '漲跌證券數合計', 'data': data8}]
                    if tables:
                        ms_date = dd
                        out['source'] = 'TWSE MI_INDEX MS'
                        break
                except Exception as e:
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

        # ── 2) 即時指數（MIS）────────────────────────────────────
        try:
            out['indices'] = _twse_mis_index('tse_t00.tw|otc_o00.tw')
        except Exception as e:
            print('[breadth] twindex', e)
            out['indices'] = {}

        # ── 3) 大盤體質 + 法人（重用既有建置，失敗不擋廣度）────────
        try:
            fund = _build_tw_market_fundamental('^TWII')
            out['score'] = fund.get('score')
            out['pillars'] = fund.get('pillars')
            out['marketRows'] = fund.get('marketRows')
            out['summary'] = fund.get('summary')
        except Exception as e:
            print('[breadth] fundamental', e)

        try:
            mf_key = f'marketflow:{_date.today().strftime("%Y%m%d")}'
            # marketflow 實際 key 用 Ymd 無連字號（見 _handle_marketflow）
            cached_mf = _cache.get(mf_key)
            if cached_mf is None:
                cached_mf = _cache.get(f'marketflow:{_date.today().strftime("%Y-%m-%d")}')
            if cached_mf:
                mf = json.loads(cached_mf.decode('utf-8') if isinstance(cached_mf, (bytes, bytearray)) else cached_mf)
                out['inst'] = mf.get('inst')
        except Exception:
            pass

        if not out['ok'] and not out['error']:
            out['error'] = '尚無最近交易日之漲跌家數（可能為休市或 TWSE 尚未公布）'

        body = json.dumps(out, ensure_ascii=False).encode()
        _cache.set(key, body, ttl=120)
        self._ok(body)

    def _handle_inst_rank(self):
        """外資/投信買賣超排行榜 (v3.8 #4)：T86 全表排序 + chip_history 連續天數。
           ?who=foreign|trust ?side=buy|sell ?n=30"""
        from datetime import date as _date, timedelta
        qs = parse_qs(urlparse(self.path).query)
        who  = (qs.get('who',  ['foreign'])[0]).lower()
        side = (qs.get('side', ['buy'])[0]).lower()
        n    = min(int(qs.get('n', ['30'])[0] or 30), 100)
        today = _date.today()
        key = f'instrank:{today.strftime("%Y%m%d")}'
        cached = _cache.get(key)
        rows_data = None
        if cached is not None:
            rows_data = json.loads(cached)
        else:
            # 往前找最近有資料的交易日
            for back in range(0, 7):
                dd = (today - timedelta(days=back)).strftime('%Y%m%d')
                try:
                    url = f'https://www.twse.com.tw/rwd/zh/fund/T86?date={dd}&selectType=ALLBUT0999&response=json'
                    req = urllib.request.Request(url, headers=YF_HEADERS)
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        d = json.loads(resp.read())
                    if d.get('stat') not in ('OK', 'ok'):
                        continue
                    fields = d.get('fields') or []
                    raw = d.get('data') or []
                    i_code = next((i for i, f in enumerate(fields) if '證券代號' in f), 0)
                    i_name = next((i for i, f in enumerate(fields) if '證券名稱' in f), 1)
                    i_for  = next((i for i, f in enumerate(fields) if '外陸資買賣超股數' in f),
                              next((i for i, f in enumerate(fields) if '外資買賣超' in f or ('外' in f and '買賣超' in f)), None))
                    i_tru  = next((i for i, f in enumerate(fields) if '投信買賣超股數' in f),
                              next((i for i, f in enumerate(fields) if '投信' in f and '買賣超' in f), None))
                    parsed = []
                    for r in raw:
                        def num(i):
                            try: return float(str(r[i]).replace(',', '').strip())
                            except Exception: return None
                        parsed.append({
                            'code': str(r[i_code]).strip(),
                            'name': str(r[i_name]).strip(),
                            'foreign': num(i_for) if i_for is not None else None,
                            'trust':   num(i_tru) if i_tru is not None else None,
                        })
                    rows_data = {'date': dd, 'rows': parsed}
                    _cache.set(key, json.dumps(rows_data, ensure_ascii=False).encode(), ttl=1800)
                    break
                except Exception as e:
                    print(f'[inst-rank] T86 {dd} failed: {e}')
        if not rows_data:
            self._ok(json.dumps({'who': who, 'side': side, 'date': '', 'list': [], '_msg': 'T86 unavailable'}, ensure_ascii=False).encode())
            return
        field = 'foreign' if who == 'foreign' else 'trust'
        items = [x for x in rows_data['rows'] if x.get(field) is not None]
        items.sort(key=lambda x: x[field], reverse=(side == 'buy'))
        top = items[:n]
        # 連續天數（單位：張，順便 /1000）
        for x in top:
            try:
                st = _chip_streak(x['code'])
                x['streak'] = st.get(field) if st else None
            except Exception:
                x['streak'] = None
            if x.get(field) is not None:
                x['lots'] = round(x[field] / 1000)
        self._ok(json.dumps({'who': who, 'side': side, 'date': rows_data['date'], 'list': top}, ensure_ascii=False).encode())

    def _handle_events(self):
        """事件行事曆 (v3.8 #1)：
           • 月營收：規則制——每月 10 日前公布上月營收（永遠可算）
           • 除權除息預告：TWSE OpenAPI 多個資料集嘗試
           • 法說會：TWSE OpenAPI 法說會一覽（best-effort）
           ?code=2330 可只看單檔除權息。"""
        from datetime import date as _date, timedelta
        qs = parse_qs(urlparse(self.path).query)
        code = (qs.get('code', [''])[0]).replace('.TW', '').replace('.TWO', '').strip().upper()
        today = _date.today()
        key = f'events:{today.strftime("%Y%m%d")}:{code}'
        c = _cache.get(key)
        if c is not None:
            self._ok(c); return
        out = {'date': today.strftime('%Y-%m-%d'), 'revenue': None, 'exDividend': [], 'conference': []}
        # 月營收規則：本月 10 日前公布上月；若已過 10 日則下次是下月 10 日
        try:
            if today.day <= 10:
                rev_date = today.replace(day=10)
            else:
                nm = (today.replace(day=28) + timedelta(days=10)).replace(day=10)
                rev_date = nm
            last_month = (today.replace(day=1) - timedelta(days=1)).strftime('%Y-%m')
            out['revenue'] = {'nextPublishBy': rev_date.strftime('%Y-%m-%d'),
                              'forMonth': last_month,
                              'daysAway': (rev_date - today).days}
        except Exception as e:
            print(f'[events] revenue rule failed: {e}')
        # 除權除息預告（嘗試多個資料集名稱，欄位用模糊比對）
        for ds in ('TWT48U', 'TWTAWU', 'TWT49U'):
            try:
                arr = _openapi_lookup_list(ds)
                if not arr:
                    continue
                cnt = 0
                for row in arr:
                    rc = (row.get('股票代號') or row.get('證券代號') or row.get('公司代號') or '').strip()
                    if code and rc != code:
                        continue
                    date_v = (row.get('除權息日期') or row.get('除權除息日期') or row.get('資料日期')
                              or row.get('停止過戶日期') or '')
                    name_v = row.get('股票名稱') or row.get('證券名稱') or row.get('名稱') or ''
                    typ = row.get('除權息') or row.get('權息') or ''
                    if date_v:
                        out['exDividend'].append({'code': rc, 'name': name_v, 'date': date_v, 'type': typ})
                        cnt += 1
                    if cnt >= (200 if not code else 20):
                        break
                if out['exDividend']:
                    break
            except Exception as e:
                print(f'[events] exDividend {ds} failed: {e}')
        body = json.dumps(out, ensure_ascii=False).encode()
        _cache.set(key, body, ttl=3600)
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

    def _focus_score(self, i):
        """多訊號組合 → (買分, 買訊號[], 空分, 空訊號[])。焦點掃描用:綜合趨勢/動能/量價/RSI。"""
        c = i.get('close'); chg = i.get('changePct') or 0
        s5, s20, s60 = i.get('sma5'), i.get('sma20'), i.get('sma60')
        s20p, s60p = i.get('sma20_prev'), i.get('sma60_prev')
        rsi = i.get('rsi14'); vr = i.get('volRatio') or 0
        h20, l20 = i.get('high20'), i.get('low20')
        buy, short, bs, ss = [], [], 0.0, 0.0
        if s5 and s20 and s60 and s5 > s20 > s60: bs += 2; buy.append('多頭排列')
        if s60 and c > s60: bs += 1; buy.append('站上季線')
        if s20 and s60 and s20p and s60p and s20p <= s60p and s20 > s60: bs += 2; buy.append('20/60金叉')
        if h20 and c > h20 and vr > 1.3: bs += 2; buy.append('帶量突破月高')
        if vr > 1.5 and chg > 0: bs += 1.5; buy.append('帶量上漲')
        if rsi and 50 <= rsi <= 70: bs += 1; buy.append('RSI轉強')
        if rsi and rsi < 35 and s60 and c > s60: bs += 1; buy.append('超賣反彈')
        if s60 and s60p and abs(c - s60) / s60 < 0.025 and s60 > s60p: bs += 1; buy.append('回測季線撐')
        if s5 and s20 and s60 and s5 < s20 < s60: ss += 2; short.append('空頭排列')
        if s60 and c < s60: ss += 1; short.append('跌破季線')
        if s20 and s60 and s20p and s60p and s20p >= s60p and s20 < s60: ss += 2; short.append('20/60死叉')
        if l20 and c < l20 and vr > 1.3: ss += 2; short.append('帶量破月低')
        if vr > 1.5 and chg < 0: ss += 1.5; short.append('帶量下跌')
        if rsi and rsi > 72 and chg < 0: ss += 1.5; short.append('過熱回落')
        return bs, buy, ss, short

    def _handle_focus(self):
        """GET /focus — 自動焦點掃描:全台股跑多訊號組合,回最強做多/做空焦點。
           回 {ok, scanned, buy:[{sym,name,close,changePct,rsi14,score,signals}], short:[...]}。"""
        try:
            _uni = _get_tw_universe()
        except Exception:
            _uni = []
        qs = parse_qs(urlparse(self.path).query)
        sector = (qs.get('sector', [''])[0] or '').strip()
        syms = list(set(_uni or self._TW_TOP200))
        if sector and sector not in ('全部', 'all', ''):
            try:
                smap = _get_tw_sectors()
                want = _TECH_SECTORS if sector == '__TECH__' else {sector}
                syms = [s for s in syms if smap.get(str(s).replace('.TW', '').replace('.TWO', '')) in want]
            except Exception:
                pass
        buy, short, scanned = [], [], 0
        futures = {_pool.submit(fetch_one, s + '.TW' if not s.endswith('.TW') else s): s for s in syms}
        for fut in as_completed(futures):
            sym, data, _ = fut.result()
            if not data:
                continue
            try:
                res = (json.loads(data).get('chart', {}).get('result', [{}])[0])
                ts = res.get('timestamp') or []
                q = (res.get('indicators', {}).get('quote') or [{}])[0]
                meta = res.get('meta', {})
                if len(ts) < 70:
                    continue
                rc = q.get('close') or []; rh = q.get('high') or []; rl = q.get('low') or []; rv = q.get('volume') or []
                closes, highs, lows, vols, tv = [], [], [], [], []
                for k in range(min(len(ts), len(rc))):
                    cc = rc[k]
                    if cc is None:
                        continue
                    closes.append(cc)
                    highs.append(rh[k] if k < len(rh) and rh[k] is not None else cc)
                    lows.append(rl[k] if k < len(rl) and rl[k] is not None else cc)
                    vols.append(rv[k] if k < len(rv) and rv[k] is not None else 0)
                    tv.append(ts[k])
                if len(closes) < 70:
                    continue
                rmt = meta.get('regularMarketTime'); rmp = meta.get('regularMarketPrice')
                if rmt and isinstance(rmp, (int, float)) and rmp > 0 and tv and rmt - tv[-1] > 20 * 3600:
                    sv = sum(vols[-5:]) / 5 if len(vols) >= 5 else 0
                    closes.append(float(rmp)); highs.append(float(rmp)); lows.append(float(rmp)); vols.append(sv)
                scanned += 1
                ind = self._calc_ind(closes, highs, lows, vols)
                bscore, bsig, sscore, ssig = self._focus_score(ind)
                code = sym.replace('.TW', '').replace('.TWO', '')
                name = _get_tw_names().get(code) or meta.get('shortName') or code
                base = {'sym': code, 'name': name, 'close': round(ind['close'], 2),
                        'changePct': round(ind['changePct'], 2),
                        'rsi14': round(ind['rsi14'], 1) if ind['rsi14'] else None}
                if bscore >= 3 and bscore > sscore:
                    r = dict(base); r['score'] = round(bscore, 1); r['signals'] = bsig; buy.append(r)
                elif sscore >= 3 and sscore > bscore:
                    r = dict(base); r['score'] = round(sscore, 1); r['signals'] = ssig; short.append(r)
            except Exception:
                continue
        buy.sort(key=lambda x: (-x['score'], -(x['changePct'] or 0)))
        short.sort(key=lambda x: (-x['score'], (x['changePct'] or 0)))
        self._ok(json.dumps({'ok': True, 'scanned': scanned, 'buy': buy[:20], 'short': short[:20]}, ensure_ascii=False).encode())

    def _handle_bars(self):
        """v4.0: GET /bars?sym=2330&market=TW → 本機 DB 日線 {candles:[{time,open,high,low,close,volume}]}。
           DB 沒有/太少則即時抓 Yahoo 5y 並寫回(供回測深度歷史用)。"""
        try:
            qs = parse_qs(urlparse(self.path).query)
            sym = (qs.get('sym', [''])[0]).strip()
            market = (qs.get('market', ['TW'])[0]).strip() or 'TW'
            if not sym:
                self._err('missing sym', 400); return
            code = sym.replace('.TW', '').replace('.TWO', '')
            rows = []
            try:
                import datastore
                rows = datastore.get_bars(code)
                if not rows or len(rows) < 80:
                    fetched = datastore.fetch_yahoo_daily(code, market, '5y')
                    if fetched:
                        datastore.upsert_bars(code, market, fetched)
                        rows = datastore.get_bars(code)
            except Exception as e:
                print('[bars] datastore failed:', e)
            candles = [{'time': r[0], 'open': r[1], 'high': r[2], 'low': r[3],
                        'close': r[4], 'volume': r[5]} for r in (rows or [])]
            self._ok(json.dumps({'sym': code, 'candles': candles}).encode())
        except Exception as e:
            self._err('bars failed: ' + str(e), 500)

    def _handle_universe(self):
        """GET /universe → 全台股+美股 code↔name lookup(權威判市場 / 補名 / 驗存在)。讀快取,缺則建。"""
        try:
            import universe
            self._ok(json.dumps(universe.load(), ensure_ascii=False).encode())
        except Exception as e:
            self._err('universe failed: ' + str(e), 500)

    def _handle_universe_refresh(self):
        """POST /universe/refresh → 重抓 TWSE/TPEx/ETF + NASDAQ directory,更新快取。回 counts(新上市即時收錄)。"""
        try:
            import universe
            data = universe.build()
            self._ok(json.dumps({'ok': True, 'updated': data.get('updated'),
                                 'counts': data.get('counts')}, ensure_ascii=False).encode())
        except Exception as e:
            self._err('universe refresh failed: ' + str(e), 500)

    def _handle_datasources(self):
        """GET /datasources → 資料源管理表(每源:提供者/可靠度/最後更新/筆數)。"""
        try:
            import datasources
            self._ok(json.dumps(datasources.list_sources(), ensure_ascii=False).encode())
        except Exception as e:
            self._err('datasources failed: ' + str(e), 500)

    def _handle_datasource_refresh(self):
        """POST /datasource/refresh body:{id, density?, dense?, step?, years?} → 一鍵更新該來源。"""
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length) or b'{}')
            import datasources
            step = body.get('step')
            years = body.get('years')
            try:
                step = int(step) if step not in (None, '') else None
            except Exception:
                step = None
            try:
                years = int(years) if years not in (None, '') else None
            except Exception:
                years = None
            self._ok(json.dumps(datasources.refresh(
                (body.get('id') or '').strip(),
                density=body.get('density'),
                dense=body.get('dense'),
                step=step,
                years=years,
            ), ensure_ascii=False).encode())
        except Exception as e:
            self._err('datasource refresh failed: ' + str(e), 500)

    def _handle_notify(self):
        """v4.0: POST /notify  body:{text, subject?} → 用 alert_config 的 Telegram/Email 寄出
           (把 AI 副駕分析等留存,不會關掉就消失)。回 {ok, results}。"""
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length) or b'{}')
        except Exception as e:
            self._err('bad body: ' + str(e), 400); return
        if not alert_daemon:
            self._err('alert 模組未載入', 500); return
        text = (body.get('text') or '').strip()
        if not text:
            self._err('text 為空', 400); return
        try:
            cfg = alert_daemon.load_config()
            ok, results = alert_daemon.notify(cfg, text, body.get('subject') or 'Stock Terminal AI 副駕')
            self._ok(json.dumps({'ok': ok, 'results': results}, ensure_ascii=False).encode())
        except Exception as e:
            self._err('notify failed: ' + str(e), 500)



    def _handle_chain_momentum(self):
        """v4.0: POST /chain-momentum  body:{stages:[{stage,codes:[...]}]}
           → 每段 5/20/60 日動能(讀本機 DB)+ 領漲成分股。台股紅漲綠跌。"""
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length) or b'{}')
        except Exception as e:
            self._err('bad body: ' + str(e), 400); return
        stages = body.get('stages') or []
        if not stages:
            self._err('no stages', 400); return
        import datastore
        allcodes = []
        for st in stages:
            allcodes += [str(c) for c in (st.get('codes') or [])]
        bulk = datastore.get_bars_bulk(list(set(allcodes)))
        names = _get_tw_names()

        def ret(rows, n):
            if not rows or len(rows) <= n:
                return None
            c0 = rows[-1 - n][4]; c1 = rows[-1][4]
            return (c1 / c0 - 1) * 100 if c0 else None

        out = []
        for st in stages:
            codes = [str(c) for c in (st.get('codes') or [])]
            per = []
            for c in codes:
                rows = bulk.get(c)
                r20 = ret(rows, 20)
                if r20 is not None:
                    per.append((c, ret(rows, 5), r20, ret(rows, 60)))
            if not per:
                out.append({'stage': st.get('stage'), 'n': 0}); continue

            def avg(i):
                vals = [p[i] for p in per if p[i] is not None]
                return round(sum(vals) / len(vals), 2) if vals else None
            leaders = sorted(per, key=lambda p: p[2], reverse=True)[:2]
            out.append({
                'stage': st.get('stage'), 'n': len(per),
                'mom5': avg(1), 'mom20': avg(2), 'mom60': avg(3),
                'leaders': [{'code': l[0], 'name': names.get(l[0]) or l[0], 'ret20': round(l[2], 2)} for l in leaders],
            })
        # 近 8 週輪動軌跡:每週各段平均報酬 → 當週領漲段(資金輪動到哪一段)
        rotation = []
        for w in range(7, -1, -1):                 # 由最舊(前7週)到本週
            start = -(w + 1) * 5
            end = (-w * 5) if w > 0 else None
            best, bestret = None, None
            for st in stages:
                rs = []
                for c in [str(x) for x in (st.get('codes') or [])]:
                    rows = bulk.get(c)
                    if not rows or len(rows) < (w + 1) * 5 + 1:
                        continue
                    seg = rows[start:end] if end is not None else rows[start:]
                    if len(seg) < 2 or not seg[0][4]:
                        continue
                    rs.append((seg[-1][4] / seg[0][4] - 1) * 100)
                if rs:
                    m = sum(rs) / len(rs)
                    if bestret is None or m > bestret:
                        bestret, best = m, st.get('stage')
            rotation.append({'week': '本週' if w == 0 else ('前%d週' % w),
                             'stage': best, 'ret': round(bestret, 1) if bestret is not None else None})
        self._ok(json.dumps({'stages': out, 'rotation': rotation}, ensure_ascii=False).encode())

    def _handle_portfolio(self):
        """v4.0: POST /portfolio  body:{holdings:[{sym,weight}]} 或 {symbols:[...]}
           → 投組風險(相關性/波動/VaR/Beta/產業曝險)。讀本機 DB,缺的代號先即時回補。"""
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length) or b'{}')
        except Exception as e:
            self._err('bad body: ' + str(e), 400); return
        holdings = body.get('holdings') or [{'sym': s, 'weight': 1} for s in (body.get('symbols') or [])]
        if not holdings:
            self._err('no holdings', 400); return
        try:
            import portfolio, datastore
            codes = [str(h.get('sym', '')).replace('.TW', '').replace('.TWO', '') for h in holdings]
            for c in [x for x in codes if x] + ['^TWII']:   # 確保持倉+大盤基準在 DB
                try:
                    r = datastore.get_bars(c)
                    if not r or len(r) < 80:
                        f = datastore.fetch_yahoo_daily(c, 'TW', '5y')
                        if f:
                            datastore.upsert_bars(c, 'TW', f)
                except Exception:
                    pass
            out = portfolio.compute(holdings, sectors_map=_get_tw_sectors(), names_map=_get_tw_names())
            self._ok(json.dumps(out, ensure_ascii=False).encode())
        except Exception as e:
            self._err('portfolio failed: ' + str(e), 500)

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
        # v4.0:一次把全宇集在 DB 的 bars 撈出(單一查詢,秒級);DB 沒有的才退回 Yahoo(DB 空時零差異)
        results = []
        ind_cache = {}
        need_yahoo = []
        try:
            import datastore
            _db_all = datastore.get_bars_bulk([str(s).replace('.TW', '').replace('.TWO', '') for s in syms])
        except Exception:
            _db_all = {}
        for _s in syms:
            _code = str(_s).replace('.TW', '').replace('.TWO', '')
            _rows = _db_all.get(_code)
            if not _rows or len(_rows) < 70:
                need_yahoo.append(_s); continue
            _cl = [r[4] for r in _rows]
            
            # 異常檢測：若資料庫最新兩日價格出現巨大斷層 (如除權息/分割/異常值) 導致變動 > 11% ➔ 丟給 Yahoo 重抓權威昨收
            if len(_cl) >= 2:
                _db_chg = (_cl[-1] - _cl[-2]) / _cl[-2] * 100
                if abs(_db_chg) > 11.0:
                    need_yahoo.append(_s); continue

            _hi = [r[2] if r[2] is not None else r[4] for r in _rows]
            _lo = [r[3] if r[3] is not None else r[4] for r in _rows]
            _vo = [r[5] if r[5] is not None else 0 for r in _rows]
            try:
                _ind = self._screener_ind_cached(_code, _rows, _cl, _hi, _lo, _vo)
                if self._screener_match(preset or custom, _ind, _cl, _hi, _vo):
                    results.append({
                        'sym': _code,
                        'name': _get_tw_names().get(_code) or _code,
                        'close': _ind['close'], 'changePct': _ind['changePct'],
                        'rsi14': round(_ind['rsi14'], 1) if _ind['rsi14'] else None,
                        'volRatio': round(_ind['volRatio'], 2) if _ind['volRatio'] else None,
                        'sma5': round(_ind['sma5'], 2) if _ind['sma5'] else None,
                        'sma20': round(_ind['sma20'], 2) if _ind['sma20'] else None,
                        'sma60': round(_ind['sma60'], 2) if _ind['sma60'] else None,
                    })
            except Exception:
                pass
        # H5：Yahoo 補洞限流，避免 DB 空時一次打爆對外 API
        _yahoo_cap = 120
        _yahoo_truncated = max(0, len(need_yahoo) - _yahoo_cap)
        need_yahoo = need_yahoo[:_yahoo_cap]
        # Fetch DB-misses in parallel using existing fetch_one with nocache=True
        futures = {_pool.submit(fetch_one, s + '.TW' if not s.endswith('.TW') else s, nocache=True): s for s in need_yahoo}
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
                # 昨收優先級：優先使用無斷層的 closes[-2]，否則退回官方昨收，防止 long range 下 chartPreviousClose 誤用
                _pc = None
                if len(closes) >= 2:
                    _tmp_chg = (closes[-1] - closes[-2]) / closes[-2] * 100
                    if abs(_tmp_chg) <= 11.0:
                        _pc = closes[-2]
                if _pc is None:
                    _pc = _yf_prevclose(meta, allow_chart_prev=False)
                _chg = ((closes[-1] - _pc) / _pc * 100) if (_pc and _pc > 0) else ind['changePct']
                if self._screener_match(preset or custom, ind, closes, highs, vols):
                    results.append({
                        'sym': sym.replace('.TW','').replace('.TWO',''),
                        'name': _get_tw_names().get(sym.replace('.TW','').replace('.TWO','')) or meta.get('shortName') or meta.get('symbol') or sym,
                        'close': ind['close'], 'changePct': round(_chg, 2),
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
        self._ok(json.dumps({
            'results': results,
            'scanned': len(syms),
            'matched': len(results),
            'yahooFetched': len(need_yahoo),
            'yahooTruncated': _yahoo_truncated,
        }, ensure_ascii=False).encode())

    # H5：選股指標短 TTL 快取（同收盤簽名 60s 內不重算 RSI/SMA）
    _SCREENER_IND_CACHE = {}
    _SCREENER_IND_TTL = 60.0

    def _screener_ind_cached(self, code, rows, closes, highs, lows, vols):
        try:
            last = rows[-1]
            sig = (len(rows), last[0], last[4])
        except Exception:
            return self._calc_ind(closes, highs, lows, vols)
        now = time.time()
        ent = Handler._SCREENER_IND_CACHE.get(code)
        if ent and ent[0] == sig and ent[2] > now:
            return ent[1]
        ind = self._calc_ind(closes, highs, lows, vols)
        Handler._SCREENER_IND_CACHE[code] = (sig, ind, now + Handler._SCREENER_IND_TTL)
        if len(Handler._SCREENER_IND_CACHE) > 4000:
            # 丟棄過期
            Handler._SCREENER_IND_CACHE = {
                k: v for k, v in Handler._SCREENER_IND_CACHE.items() if v[2] > now
            }
        return ind

    def _calc_ind(self, closes, highs, lows, vols):
        n = len(closes)
        try:
            import indicators as _ind
            def sma(p, idx):
                return _ind.sma(closes, p, idx)
            rsi = _ind.rsi_wilders(closes, 14)
        except Exception:
            def sma(p, idx):
                if idx + 1 < p: return None
                return sum(closes[idx-p+1:idx+1]) / p
            def calc_rsi_wilders(prices, period=14):
                if len(prices) <= period:
                    return None
                gains, losses = [], []
                for i in range(1, len(prices)):
                    diff = prices[i] - prices[i-1]
                    gains.append(diff if diff > 0 else 0.0)
                    losses.append(-diff if diff < 0 else 0.0)
                avg_gain = sum(gains[:period]) / period
                avg_loss = sum(losses[:period]) / period
                for i in range(period, len(gains)):
                    avg_gain = (avg_gain * (period - 1) + gains[i]) / period
                    avg_loss = (avg_loss * (period - 1) + losses[i]) / period
                if avg_loss == 0:
                    return 100.0
                rs = avg_gain / avg_loss
                return 100.0 - (100.0 / (1.0 + rs))
            rsi = calc_rsi_wilders(closes, 14)
        # Vol ratio
        v5 = sum(vols[-5:]) / 5 if len(vols) >= 5 else 0
        v20 = sum(vols[-20:]) / 20 if len(vols) >= 20 else 0
        volRatio = v5/v20 if v20 > 0 else 0
        return {
            'close': _round_px(closes[-1]), 'prev': closes[-2] if n >= 2 else None,
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


    def _handle_etf_reason(self):
        """POST /etf-reason — ETF 異動 AI 一句話原因推導 (v3.9 P5)。
           body: {apiKey, code, name, etfs:[...], action, sharesDelta, weightDelta}
           伺服器補基本面(月營收YoY/三率)做上下文，呼叫 Anthropic 回一句話。"""
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length) or b'{}')
        except Exception as e:
            self._err('bad body: ' + str(e), 400); return
        api_key = (body.get('apiKey') or '').strip() or _load_ai_key()
        if not api_key:
            self._err('apiKey required', 400); return
        code = (body.get('code') or '').strip().upper()
        etfs = body.get('etfs') or []
        action = body.get('action') or '加碼'
        # 補基本面
        fund_txt = ''
        try:
            rev = _openapi_lookup(['t187ap05_L', 't187ap05_O'], code)
            yoy = _pick_num(rev, ['去年同月增減']) if rev else None
            inc = _openapi_lookup(['t187ap06_L_ci', 't187ap06_O_ci', 't187ap06_L', 't187ap06_O'], code)
            gm = nm = None
            if inc:
                sales = _pick_num(inc, ['營業收入'], ['成本', '毛利', '費用', '外', '淨額'])
                gross = _pick_num(inc, ['營業毛利'])
                net = _pick_num(inc, ['本期淨利']) or _pick_num(inc, ['本期綜合損益總額'])
                if sales:
                    gm = round(gross / sales * 100, 1) if gross else None
                    nm = round(net / sales * 100, 1) if net else None
            parts = []
            if yoy is not None: parts.append(f'月營收YoY {yoy}%')
            if gm is not None: parts.append(f'毛利率 {gm}%')
            if nm is not None: parts.append(f'淨利率 {nm}%')
            fund_txt = '、'.join(parts) if parts else '(基本面資料暫缺)'
        except Exception:
            fund_txt = '(基本面資料暫缺)'
        prompt = (
            f'你是台股研究分析師。請用「一句話」(繁體中文、40字內、有觀點)解讀為何近期有主動型 ETF '
            f'{action} 個股 {code}。\n'
            f'相關 ETF：{("、".join(map(str, etfs)) or "多檔主動ETF")}\n'
            f'{code} 近期基本面：{fund_txt}\n'
            f'{action}幅度：約 {body.get("sharesDelta", "?")} 股 / 權重變化 {body.get("weightDelta", "?")}%\n'
            f'要求：以代號為準，若不確定公司名稱就只用代號，嚴禁臆測；'
            f'結合台灣 AI 供應鏈結構偏多視角但點出短線風險；只回一句話，不要前綴。'
        )
        try:
            text, _ = _anthropic_messages(
                api_key, [{'role': 'user', 'content': prompt}], max_tokens=300,
            )
            self._ok(json.dumps({'ok': True, 'reason': text, 'fund': fund_txt}, ensure_ascii=False).encode())
        except urllib.error.HTTPError as e:
            self._err(f'Anthropic HTTP {e.code}: ' + e.read().decode('utf-8', 'replace')[:300], 502)
        except Exception as e:
            self._err('etf-reason failed: ' + str(e), 500)


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
            subject = html = text = None
            if etf_report:
                try:
                    subject, html = etf_report.build_report_html(delta, mode)
                    text = etf_report.build_report_text(delta)
                except Exception:
                    html = None
            if not html:
                # etf_report 不可用(打包已排除 pandas/matplotlib / dev 未裝)→ 純 stdlib 報表。
                # 絕不再寄原始 JSON。
                import etf_report_lite
                subject, html, text = etf_report_lite.build(delta, mode)
            cfg = alert_daemon.load_config()
            ok, msg = alert_daemon.push_email(cfg, subject, text, html=html)
            if ok:
                alert_daemon._log('ETF report emailed: ' + subject)
            self._ok(json.dumps({'ok': ok, 'results': {'email': msg}}, ensure_ascii=False).encode())
        except Exception as e:
            self._err('email report failed: ' + str(e), 500)

    def _handle_report_email(self):
        """POST /report-email — 把 AI 報告 HTML 寄給『自訂收件者』(重用已設定的 Email SMTP)。
           body: {to, subject, html}。與 /etf-report/email 不同:收件者可指定,非設定檔固定的 to。"""
        if not alert_daemon:
            self._err('email module unavailable', 503); return
        try:
            body = self._read_json_body() or {}
        except Exception as e:
            self._err('bad body: ' + str(e), 400); return
        to = (body.get('to') or '').strip()
        subject = (body.get('subject') or 'Stock Terminal AI 報告').strip()
        html = body.get('html') or ''
        if '@' not in to:
            self._err('需有效收件者 email', 400); return
        if not html:
            self._err('html required', 400); return
        em = (alert_daemon.load_config() or {}).get('email', {})
        if not em.get('user') or not em.get('app_password'):
            self._err('Email 未設定:請先在通知設定填寄件帳號/應用程式密碼', 400); return
        try:
            import smtplib, ssl
            from email.mime.text import MIMEText
            msg = MIMEText(html, 'html', 'utf-8')
            msg['Subject'] = subject
            msg['From'] = em['user']
            msg['To'] = to
            ctx = ssl.create_default_context()
            with smtplib.SMTP(em.get('smtp_host', 'smtp.gmail.com'), int(em.get('smtp_port', 587)), timeout=20) as s:
                s.starttls(context=ctx)
                s.login(em['user'], em['app_password'])
                s.sendmail(em['user'], [to], msg.as_string())
            self._ok(json.dumps({'ok': True, 'to': to}, ensure_ascii=False).encode())
        except Exception as e:
            self._err('send failed: ' + str(e), 502)

    def _txf_fnum(self, d, *keys):
        for k in keys:
            v = (d or {}).get(k)
            if v not in (None, '', '-'):
                try:
                    return float(str(v).replace(',', '').replace('%', ''))
                except Exception:
                    pass
        return None

    def _txf_mis_session(self, market_type):
        """TAIFEX MIS 台指期近月：MarketType 0=日盤、1=夜盤。
           近月以成交量最大列為準（夜盤 QuoteList 常缺 CMonth）。"""
        url = 'https://mis.taifex.com.tw/futures/api/getQuoteList'
        payload = json.dumps({
            'MarketType': str(market_type), 'SymbolType': 'F', 'KindID': '1', 'CID': 'TXF',
            'ExpireMonth': '', 'RowSize': '全部', 'PageNo': '', 'SortColumn': '', 'AscDesc': 'A',
        }).encode('utf-8')
        req = urllib.request.Request(url, data=payload, method='POST', headers={
            'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0',
            'Origin': 'https://mis.taifex.com.tw', 'Referer': 'https://mis.taifex.com.tw/futures/',
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        rows = (data.get('RtData') or {}).get('QuoteList') or []
        if not rows:
            return None
        best, best_vol = None, -1.0
        for row in rows:
            last = self._txf_fnum(row, 'CLastPrice', 'CLast', 'LastPrice')
            if last is None:
                continue
            vol = self._txf_fnum(row, 'CTotalVolume') or 0.0
            if vol > best_vol:
                best, best_vol = row, vol
        if best is None:
            best = rows[0]
        price = self._txf_fnum(best, 'CLastPrice', 'CLast', 'LastPrice')
        prev = self._txf_fnum(best, 'CRefPrice', 'CYDClose', 'RefPrice')
        high = self._txf_fnum(best, 'CHighPrice')
        low = self._txf_fnum(best, 'CLowPrice')
        opn = self._txf_fnum(best, 'COpenPrice')
        amp = self._txf_fnum(best, 'CAmpRate')
        vol = self._txf_fnum(best, 'CTotalVolume')
        chg = self._txf_fnum(best, 'CDiffRate', 'DiffRate')
        if chg is None and price is not None and prev:
            chg = (price - prev) / prev * 100.0
        if amp is None and high is not None and low is not None and prev:
            amp = (high - low) / prev * 100.0
        change = None
        if price is not None and prev is not None:
            change = price - prev
        sess = 'night' if str(market_type) == '1' else 'day'
        return {
            'price': price, 'prevClose': prev, 'change': change,
            'changePct': (round(chg, 4) if chg is not None else None),
            'open': opn, 'high': high, 'low': low,
            'ampRate': (round(amp, 4) if amp is not None else None),
            'volume': vol, 'time': best.get('CTime') or '',
            'session': sess, 'sessionLabel': '夜盤' if sess == 'night' else '日盤',
            'name': best.get('DispCName') or best.get('CName') or '台指期近一',
            'source': 'taifex-mis-' + sess,
        }

    def _txf_yahoo_quote(self):
        """Yahoo TW 期貨頁 WTX&：成交/昨收/開高低 + 漲跌%。"""
        import re as _re2
        url = 'https://tw.stock.yahoo.com/quote/WTX%26'
        req = urllib.request.Request(url, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Accept-Language': 'zh-TW,zh;q=0.9',
        })
        with urllib.request.urlopen(req, timeout=12) as resp:
            html = resp.read().decode('utf-8', 'replace')

        def span_num(label):
            m = _re2.search(
                label + r'</span>\s*<span[^>]*>\s*([0-9,]+\.?[0-9]*)\s*</span>',
                html,
            )
            if m:
                try:
                    return float(m.group(1).replace(',', ''))
                except Exception:
                    return None
            # 去標籤備援
            txt = _re2.sub(r'<[^>]+>', ' ', html).replace('\xa0', ' ')
            m2 = _re2.search(label + r'[^\d\-]{0,12}([\d,]+\.\d{2})', txt)
            if m2:
                try:
                    return float(m2.group(1).replace(',', ''))
                except Exception:
                    return None
            return None

        price = span_num('成交')
        prev = span_num('昨收')
        opn = span_num('開盤')
        high = span_num('最高')
        low = span_num('最低')
        txt = _re2.sub(r'<[^>]+>', ' ', html).replace('\xa0', ' ')
        mpct = _re2.search(r'漲幅[^\d\-]{0,12}([\d.]+)\s*%', txt)
        pctmag = float(mpct.group(1)) if mpct else None
        chg = None
        if price is not None and prev:
            chg = (price - prev) / prev * 100.0
        elif pctmag is not None and price is not None and prev:
            chg = pctmag * (1 if price >= prev else -1)
        if price is None:
            return None, {
                'price_label_hit': price, 'prev_label_hit': prev,
                'has_成交': '成交' in txt, 'has_昨收': '昨收' in txt,
            }
        amp = None
        if high is not None and low is not None and prev:
            amp = (high - low) / prev * 100.0
        change = (price - prev) if (price is not None and prev is not None) else None
        return {
            'price': price, 'prevClose': prev, 'change': change,
            'changePct': (round(chg, 4) if chg is not None else None),
            'open': opn, 'high': high, 'low': low,
            'ampRate': (round(amp, 4) if amp is not None else None),
            'volume': None, 'time': '',
            'session': None, 'sessionLabel': None,
            'name': '台指期近一', 'source': 'yahoo-tw',
        }, None

    def _txf_is_night_hours(self):
        """台指期夜盤時段（台北）：15:00–05:00。"""
        try:
            from datetime import datetime, timezone, timedelta
            tw = datetime.now(timezone(timedelta(hours=8)))
            hm = tw.hour * 100 + tw.minute
            return hm >= 1500 or hm < 500
        except Exception:
            return False

    def _handle_txf(self):
        """台指期近一(含夜盤波動) — Yahoo TW + TAIFEX MIS 日/夜盤。
           回 {ok, price, prevClose, change, changePct, open, high, low, ampRate,
               volume, session, sessionLabel, time, name, source, night:{...}}。
           night 永遠附夜盤近月 OHLC/振幅，供夜盤面板「台指期夜盤波動」。"""
        key = f'txf:{int(time.time() // 20)}'   # 20s 快取
        c = _cache.get(key)
        if c is not None:
            self._ok(c); return

        debug = {}
        yahoo = None
        try:
            yahoo, ydbg = self._txf_yahoo_quote()
            if ydbg:
                debug['yahoo'] = ydbg
        except Exception as e:
            debug['yahoo_error'] = str(e)

        night = None
        day = None
        try:
            night = self._txf_mis_session(1)
        except Exception as e:
            debug['taifex_night_error'] = str(e)
        try:
            day = self._txf_mis_session(0)
        except Exception as e:
            debug['taifex_day_error'] = str(e)

        # 主報價：夜盤時段或 Yahoo≈夜盤價 → 夜盤；否則日盤；再退 Yahoo
        primary = None
        if night and night.get('price') is not None and (
            self._txf_is_night_hours()
            or (yahoo and yahoo.get('price') is not None
                and abs(yahoo['price'] - night['price']) <= max(2.0, night['price'] * 0.0005))
            or (not day or day.get('price') is None)
        ):
            primary = dict(night)
            # Yahoo 同期 OHLC 可補 MIS 缺欄
            if yahoo:
                for k in ('open', 'high', 'low', 'ampRate', 'prevClose', 'changePct', 'change'):
                    if primary.get(k) is None and yahoo.get(k) is not None:
                        primary[k] = yahoo[k]
                if primary.get('source') and yahoo.get('source'):
                    primary['source'] = yahoo['source'] + '+' + primary['source']
        elif day and day.get('price') is not None:
            primary = dict(day)
            if yahoo:
                for k in ('open', 'high', 'low', 'ampRate', 'prevClose', 'changePct', 'change'):
                    if primary.get(k) is None and yahoo.get(k) is not None:
                        primary[k] = yahoo[k]
        elif yahoo and yahoo.get('price') is not None:
            primary = dict(yahoo)
            primary['session'] = 'night' if self._txf_is_night_hours() else 'day'
            primary['sessionLabel'] = '夜盤' if primary['session'] == 'night' else '日盤'

        if primary is None:
            self._ok(json.dumps(
                {'ok': False, 'error': '兩來源皆無法解析', 'debug': debug},
                ensure_ascii=False,
            ).encode())
            return

        # 夜盤波動區塊：優先 MIS 夜盤；若無則主報價已是夜盤時複用
        night_block = None
        src_night = night if (night and night.get('price') is not None) else None
        if src_night is None and primary.get('session') == 'night':
            src_night = primary
        if src_night is not None:
            night_block = {
                'price': src_night.get('price'),
                'prevClose': src_night.get('prevClose'),
                'change': src_night.get('change'),
                'changePct': src_night.get('changePct'),
                'open': src_night.get('open'),
                'high': src_night.get('high'),
                'low': src_night.get('low'),
                'ampRate': src_night.get('ampRate'),
                'volume': src_night.get('volume'),
                'time': src_night.get('time') or '',
                'session': 'night',
                'sessionLabel': '夜盤',
                'source': src_night.get('source') or 'taifex-mis-night',
            }

        out = {
            'ok': True,
            'price': primary.get('price'),
            'prevClose': primary.get('prevClose'),
            'change': primary.get('change'),
            'changePct': primary.get('changePct'),
            'open': primary.get('open'),
            'high': primary.get('high'),
            'low': primary.get('low'),
            'ampRate': primary.get('ampRate'),
            'volume': primary.get('volume'),
            'time': primary.get('time') or '',
            'session': primary.get('session') or ('night' if self._txf_is_night_hours() else 'day'),
            'sessionLabel': primary.get('sessionLabel') or (
                '夜盤' if (primary.get('session') or '') == 'night' else '日盤'
            ),
            'name': primary.get('name') or '台指期近一',
            'source': primary.get('source') or 'unknown',
            'night': night_block,
        }
        body = json.dumps(out, ensure_ascii=False).encode()
        _cache.set(key, body)
        self._ok(body)

    def _stockfut_one(self, cid, m):
        """從整批快取 m 算單一個股期 {ok,price,changePct,現%,領先,session...}。"""
        def fnum(d, *keys):
            for k in keys:
                v = (d or {}).get(k)
                if v not in (None, '', '-'):
                    try: return float(str(v).replace(',', '').replace('%', ''))
                    except Exception: pass
            return None
        e = m.get(cid) or {}
        day_fut, day_spot, night_fut = e.get('dayFut'), e.get('daySpot'), e.get('nightFut')
        spot_prev = fnum(day_spot, 'CRefPrice', 'CYDClose')
        spot_last = fnum(day_spot, 'CLastPrice', 'CLast')
        spot_chg = fnum(day_spot, 'CDiffRate')
        if spot_chg is None and spot_last is not None and spot_prev:
            spot_chg = (spot_last - spot_prev) / spot_prev * 100
        nf_last = fnum(night_fut, 'CLastPrice', 'CLast')
        df_last = fnum(day_fut, 'CLastPrice', 'CLast')
        if nf_last is not None:
            fut_last, sess, frow = nf_last, 'night', night_fut
        elif df_last is not None:
            fut_last, sess, frow = df_last, 'day', day_fut
        else:
            fut_last, sess, frow = None, None, (day_fut or night_fut)
        fut_pct = None
        if fut_last is not None and spot_prev:
            fut_pct = (fut_last - spot_prev) / spot_prev * 100
        elif frow:
            fut_pct = fnum(frow, 'CDiffRate')
        lead = None if (fut_pct is None or spot_chg is None) else round(fut_pct - spot_chg, 2)
        return {'ok': fut_last is not None, 'cid': cid, 'price': fut_last,
                'prevClose': spot_prev, 'changePct': (round(fut_pct, 2) if fut_pct is not None else None),
                'name': (frow.get('DispCName') if frow else cid),
                'contract': str((frow or {}).get('SymbolID') or ''), 'session': sess,
                'spotPrice': spot_last, 'spotChangePct': (round(spot_chg, 2) if spot_chg is not None else None),
                'lead': lead, 'source': 'taifex-mis'}

    def _handle_stockfut(self):
        """個股期貨(含夜盤)即時報價 — TAIFEX MIS 整批(避免限流 520)。
           ?cid=CDF 回單一；?cids=CDF,DHF,... 回 {results:[...]}。
           日夜合併(夜盤近月-M 有成交→夜盤,否則日盤-F)，期%/現% 同昨收基準，領先=期%−現%。"""
        qs = parse_qs(urlparse(self.path).query)
        cids_raw = (qs.get('cids', [''])[0]).strip()
        cid = (qs.get('cid', [''])[0] or qs.get('code', [''])[0]).strip().upper()
        m = _mis_load_futures()
        if cids_raw:
            cids = [x.strip().upper() for x in cids_raw.split(',') if x.strip()]
            results = [self._stockfut_one(c, m) for c in cids]
            body = json.dumps({'ok': any(r['ok'] for r in results), 'results': results,
                               'loaded': len(m)}, ensure_ascii=False).encode()
            self._ok(body); return
        if not cid:
            self._err('cid or cids required (e.g. ?cid=CDF)', 400); return
        out = self._stockfut_one(cid, m)
        if not out.get('ok'):
            out['debug'] = {'loaded': len(m), 'hasCid': cid in m}
        self._ok(json.dumps(out, ensure_ascii=False).encode())

    def _handle_twindex(self):
        """台股大盤即時指數 (v3.8 修 Yahoo ^TWII 早盤落後一日 bug)：
           TWSE MIS 即時——加權 tse_t00.tw、櫃買 otc_o00.tw。
           回 {ok, indices:{t00:{price,prevClose,changePct}, o00:{...}}, source}。
           盤前/休市 z 可能為 '-' → price 回 None，前端就保留 Yahoo 值不覆寫。"""
        import re as _re3
        key = f'twindex:{int(time.time() // 15)}'   # 15s 快取
        c = _cache.get(key)
        if c is not None:
            self._ok(c); return
        out = {'ok': False, 'indices': {}, 'source': None}
        try:
            # 走共用 TrustedDataLayer(節流/熔斷/健檢) — 同 ^TWOII 改路由用的源
            out['indices'] = _twse_mis_index('tse_t00.tw|otc_o00.tw')
            out['ok'] = any(v.get('price') is not None for v in out['indices'].values())
            out['source'] = 'twse-mis'
        except SourceBreakerOpen:
            out['error'] = 'twse-mis breaker open'
        except Exception as e:
            out['error'] = str(e)
        body = json.dumps(out, ensure_ascii=False).encode()
        if out['ok']:
            _cache.set(key, body)
        self._ok(body)

    def _handle_margin_ratio_backfill(self):
        """POST /margin_ratio/backfill — 背景回補歷史（full=1 從 2001 起）。"""
        try:
            length = int(self.headers.get('Content-Length', 0) or 0)
            body = json.loads(self.rfile.read(length) or b'{}') if length else {}
        except Exception:
            body = {}
        qs = parse_qs(urlparse(self.path).query)
        full = bool(body.get('full')) or (qs.get('full', ['0'])[0] in ('1', 'true'))
        max_days = body.get('max') or (qs.get('max', [None])[0])
        md = int(max_days) if max_days else None
        try:
            import margin_ratio as mr
            started = mr.start_background_backfill(full=full, max_days=md)
            m = mr.meta_summary()
            m['backfillStarted'] = bool(started)
            self._ok(json.dumps(m, ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            self._err('margin backfill failed: ' + str(e), 500)

    def _handle_margin_ratio(self):
        """GET /margin_ratio — 大盤融資維持率 meta（歷史深度、風險區、回補狀態）。
           ?action=backfill&full=1 可觸發背景歷史回補。"""
        qs = parse_qs(urlparse(self.path).query)
        action = (qs.get('action', [''])[0] or '').strip().lower()
        try:
            import margin_ratio as mr
            if action == 'backfill':
                full = (qs.get('full', ['0'])[0] or '0') in ('1', 'true', 'yes')
                max_days = qs.get('max', [None])[0]
                md = int(max_days) if max_days else None
                started = mr.start_background_backfill(full=full, max_days=md)
                m = mr.meta_summary()
                m['backfillStarted'] = bool(started)
                self._ok(json.dumps(m, ensure_ascii=False).encode('utf-8'))
                return
            if action == 'today':
                mr.refresh_today(force=True)
            self._ok(json.dumps(mr.meta_summary(), ensure_ascii=False).encode('utf-8'))
        except Exception as e:
            self._err('margin_ratio failed: ' + str(e), 500)

    # ── 總經數據 (v3.9 P4) + MacroMicro 追蹤圖 (v4.1) ─────────
    def _handle_macro(self, series):
        from datetime import date as _date, timedelta as _td
        series = (series or '').strip()
        # /macro/charts — 多序列追蹤圖目錄
        if series in ('charts', 'track', 'track/list'):
            try:
                import macro_track as mt
                self._ok(json.dumps({'charts': mt.list_charts()}, ensure_ascii=False).encode()); return
            except Exception as e:
                self._err('macro charts list failed: ' + str(e), 500); return
        # /macro/chart/<ID> — 完整多序列
        if series.startswith('chart/') or series.startswith('track/'):
            cid = series.split('/', 1)[1].strip()
            qs = parse_qs(urlparse(self.path).query)
            yrs = qs.get('years', ['25'])[0]
            try:
                yrs = max(1, min(40, int(yrs)))
            except Exception:
                yrs = 25
            try:
                import macro_track as mt
                data = mt.get_chart(cid, years=yrs)
                self._ok(json.dumps(data, ensure_ascii=False).encode()); return
            except KeyError:
                self._err('unknown macro chart: ' + cid, 404); return
            except Exception as e:
                self._err('macro chart failed: ' + str(e), 500); return
        # /macro/track/backfill-mix — 觸發融資比回補（query years/step）
        if series in ('backfill-mix', 'track/backfill-mix'):
            qs = parse_qs(urlparse(self.path).query)
            start = qs.get('start', ['2018-01-01'])[0]
            step = int(qs.get('step', ['14'])[0] or 14)
            def _run():
                try:
                    import macro_track as mt
                    y, m, d = map(int, start.split('-'))
                    n = mt.backfill_margin_mix(_date(y, m, d), step_days=max(1, step))
                    print('[macro_track] backfill-mix done', n)
                except Exception as e:
                    print('[macro_track] backfill-mix failed', e)
            threading.Thread(target=_run, daemon=True).start()
            self._ok(json.dumps({'ok': True, 'started': True, 'start': start, 'step': step}).encode()); return

        # /macro/refresh 或 /macro/refresh/<ID> — UI 一鍵更新（免 CLI）
        if series == 'refresh' or series.startswith('refresh/'):
            qs = parse_qs(urlparse(self.path).query)
            cid = 'ALL'
            if series.startswith('refresh/'):
                cid = series.split('/', 1)[1].strip() or 'ALL'
            cid = (qs.get('id', [cid])[0] or cid).strip()
            dense = (qs.get('dense', ['1'])[0] or '1').lower() in ('1', 'true', 'yes')
            density = qs.get('density', [None])[0]
            step = qs.get('step', [None])[0]
            years = qs.get('years', [None])[0]
            try:
                step = int(step) if step not in (None, '') else None
            except Exception:
                step = None
            try:
                years = int(years) if years not in (None, '') else None
            except Exception:
                years = None
            try:
                import macro_track as mt
                data = mt.refresh_chart(cid, dense=dense, density=density, step=step, years=years)
                self._ok(json.dumps(data, ensure_ascii=False).encode()); return
            except Exception as e:
                self._err('macro refresh failed: ' + str(e), 500); return

        if series == '' or series == 'list':
            cat = [{'key': k, 'label': v['label'], 'unit': v.get('unit', ''), 'provider': v['p']}
                   for k, v in MACRO_SERIES.items()]
            try:
                import macro_track as mt
                charts = mt.list_charts()
            except Exception:
                charts = []
            self._ok(json.dumps({'series': cat, 'charts': charts}, ensure_ascii=False).encode()); return
        spec = MACRO_SERIES.get(series)
        if not spec:
            self._err('unknown macro series: ' + series, 404); return
        qs = parse_qs(urlparse(self.path).query)
        yrs = qs.get('years', ['10'])[0]
        try:
            yrs = max(1, min(30, int(yrs)))
        except Exception:
            yrs = 10
        today = _date.today()
        cosd = (today - _td(days=yrs * 366)).strftime('%Y-%m-%d')
        ckey = f'{series}:{yrs}:{today.strftime("%Y%m%d")}'
        cached = _macro_cache.get(ckey)
        if cached:
            self._ok(cached); return
        out = {'series': series, 'label': spec['label'], 'unit': spec.get('unit', ''),
               'points': [], 'source': None, 'note': None}
        try:
            if spec['p'] == 'fred':
                out['points'] = _fetch_fred_csv(spec['id'], cosd)
                out['source'] = f'FRED {spec["id"]}'
                if not out['points']:
                    out['note'] = '查無資料（FRED 端點未回傳）'
            elif spec['p'] == 'twcpi':
                yrs2 = qs.get('years', ['10'])[0]
                try: mlen = max(12, min(360, int(yrs2) * 12))
                except Exception: mlen = 120
                out['points'] = _fetch_tw_cpi(mlen)
                out['source'] = '主計總處 PXWeb' if out['points'] else None
                if not out['points']:
                    out['note'] = '主計總處 CPI 解析失敗。樣本：' + (_macro_debug.get('tw_cpi', '(無回應)'))
            elif spec['p'] == 'ndc':
                out['points'] = _fetch_tw_light()
                out['source'] = '國發會 NDC' if out['points'] else None
                if not out['points']:
                    out['note'] = '國發會景氣信號解析失敗。樣本：' + (_macro_debug.get('tw_light', '(無回應)'))
            elif spec['p'] == 'cbc':
                # 台灣央行利率走廊（種子／抓取）
                import macro_track as mt
                cbc = mt.load_cbc_daily()
                key = spec.get('id') or series
                out['points'] = cbc.get(key, [])
                out['source'] = 'CBC'
                if not out['points']:
                    out['note'] = 'CBC 利率種子空白'
        except Exception as e:
            out['note'] = '抓取失敗：' + str(e)
        body = json.dumps(out, ensure_ascii=False).encode()
        if out['points']:
            _macro_cache[ckey] = body
        self._ok(body)

    # ── 三合一選股 技術+基本面+籌碼 (v3.9 P4) ───────────────
    def _handle_screen3(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length) or b'{}')
        except Exception as e:
            self._err('bad body: ' + str(e), 400); return
        tech = body.get('tech') or {}
        fund = body.get('fund') or {}
        chip = body.get('chip') or {}
        try:
            _uni = _get_tw_universe()
        except Exception:
            _uni = []
        syms = list(set(body.get('symbols') or _uni or self._TW_TOP200))
        sector = (body.get('sector') or '').strip()
        if sector and sector not in ('全部', 'all', ''):
            try:
                smap = _get_tw_sectors()
                want = _TECH_SECTORS if sector == '__TECH__' else {sector}
                syms = [s for s in syms if smap.get(str(s).replace('.TW', '').replace('.TWO', '')) in want]
            except Exception as e:
                print('[screen3] sector filter failed:', e)

        def fnum(x):
            try: return float(x)
            except Exception: return None

        # ── 1) 技術面：平行抓 K 線 + _calc_ind，先篩出 survivors ──
        survivors = []
        futures = {_pool.submit(fetch_one, s + '.TW' if not s.endswith('.TW') else s): s for s in syms}
        for fut in as_completed(futures):
            sym, data, _ = fut.result()
            if not data:
                continue
            try:
                parsed = json.loads(data)
                res = parsed.get('chart', {}).get('result', [{}])[0]
                ts = res.get('timestamp') or []
                q = (res.get('indicators', {}).get('quote') or [{}])[0]
                meta = res.get('meta', {})
                raw_c = q.get('close') or []
                if len(ts) < 70:
                    continue
                closes, highs, lows, vols = [], [], [], []
                rh, rl, rv = q.get('high') or [], q.get('low') or [], q.get('volume') or []
                for i in range(min(len(ts), len(raw_c))):
                    c = raw_c[i]
                    if c is None: continue
                    closes.append(c)
                    highs.append(rh[i] if i < len(rh) and rh[i] is not None else c)
                    lows.append(rl[i] if i < len(rl) and rl[i] is not None else c)
                    vols.append(rv[i] if i < len(rv) and rv[i] is not None else 0)
                if len(closes) < 70:
                    continue
                ind = self._calc_ind(closes, highs, lows, vols)
                # 漲跌% 同樣改以官方昨收為基準(避免資料缺口/除權息造成離譜值)
                _pc = _yf_prevclose(meta)
                if _pc and _pc > 0:
                    ind['changePct'] = round((closes[-1] - _pc) / _pc * 100, 2)
                if not self._screen3_tech(tech, ind):
                    continue
                survivors.append({
                    'sym': sym.replace('.TW', '').replace('.TWO', ''),
                    'name': _get_tw_names().get(sym.replace('.TW', '').replace('.TWO', '')) or meta.get('shortName') or meta.get('symbol') or sym,
                    'ind': ind,
                })
            except Exception:
                continue

        # ── 2) 基本面 + 籌碼（O(1) 查表，資料集已快取一天）──
        results = []
        want_fund = any(v not in (None, '', False) for v in fund.values())
        want_chip = any(v not in (None, '', False) for v in chip.values())
        for row in survivors:
            code = row['sym']
            ind = row['ind']
            rec = {
                'sym': code, 'name': row['name'],
                'close': ind['close'],
                'changePct': round(ind['changePct'], 2) if ind['changePct'] is not None else None,
                'rsi14': round(ind['rsi14'], 1) if ind['rsi14'] else None,
                'volRatio': round(ind['volRatio'], 2) if ind['volRatio'] else None,
            }
            ok = True
            # 基本面
            if want_fund:
                revrow = _openapi_lookup(['t187ap05_L', 't187ap05_O'], code)
                yoy = _pick_num(revrow, ['去年同月增減']) if revrow else None
                valrow = _openapi_lookup(['exchangeReport/BWIBBU_ALL', 'BWIBBU_ALL'], code) or \
                    _openapi_lookup(['tpex:tpex_mainboard_peratio_analysis'], code)
                per = ydiv = None
                if valrow:
                    per = _pick_num(valrow, ['本益比']) or fnum(valrow.get('PEratio'))
                    ydiv = _pick_num(valrow, ['殖利率']) or fnum(valrow.get('DividendYield'))
                rec['revYoy'] = round(yoy, 1) if yoy is not None else None
                rec['per'] = per
                rec['yield'] = ydiv
                if fund.get('revYoyMin') is not None and not (yoy is not None and yoy >= fnum(fund['revYoyMin'])):
                    ok = False
                if ok and fund.get('perMax') is not None and not (per is not None and per <= fnum(fund['perMax'])):
                    ok = False
                if ok and fund.get('yieldMin') is not None and not (ydiv is not None and ydiv >= fnum(fund['yieldMin'])):
                    ok = False
            # 籌碼
            if ok and want_chip:
                st = _chip_streak(code) or {'foreign': 0, 'trust': 0}
                rec['foreignStreak'] = st.get('foreign')
                rec['trustStreak'] = st.get('trust')
                if chip.get('trustBuyDays') is not None and not (st.get('trust', 0) >= int(chip['trustBuyDays'])):
                    ok = False
                if ok and chip.get('foreignBuyDays') is not None and not (st.get('foreign', 0) >= int(chip['foreignBuyDays'])):
                    ok = False
            if ok:
                results.append(rec)

        results.sort(key=lambda x: x.get('changePct') or 0, reverse=True)
        self._ok(json.dumps({'results': results[:80], 'scanned': len(syms),
                             'techPass': len(survivors), 'matched': len(results)},
                            ensure_ascii=False).encode())

    def _screen3_tech(self, tech, i):
        """技術面條件 (全部需成立)。空條件 → 直接通過。"""
        if not i.get('close'):
            return False
        c = i['close']
        def has(k): return tech.get(k) not in (None, '', False)
        try:
            if tech.get('aboveSma20') and not (i.get('sma20') and c > i['sma20']): return False
            if tech.get('aboveSma60') and not (i.get('sma60') and c > i['sma60']): return False
            if tech.get('bullishAlign') and not (i.get('sma5') and i.get('sma20') and i.get('sma60')
                                                 and i['sma5'] > i['sma20'] > i['sma60']): return False
            if has('rsiMin') and not (i.get('rsi14') is not None and i['rsi14'] >= float(tech['rsiMin'])): return False
            if has('rsiMax') and not (i.get('rsi14') is not None and i['rsi14'] <= float(tech['rsiMax'])): return False
            if has('volRatioMin') and not (i.get('volRatio') and i['volRatio'] >= float(tech['volRatioMin'])): return False
            if tech.get('newHigh20') and not (i.get('high20') and c >= i['high20']): return False
        except Exception:
            return False
        return True

    # ── 畫線雲端記憶 (v3.9 P3) ─────────────────────────────
    def _handle_draw_get(self, sym):
        sym = unquote(sym or '')
        store = _load_draw_store()
        self._ok(json.dumps({'sym': sym, 'objects': store.get(sym, [])}, ensure_ascii=False).encode())

    def _handle_draw_post(self, sym):
        sym = unquote(sym or '')
        if not sym:
            self._err('missing sym', 400); return
        try:
            body = self._read_json_body()
            objs = body.get('objects') if isinstance(body, dict) else body
            if not isinstance(objs, list):
                self._err('objects must be a list', 400); return
            with _draw_lock:
                store = _load_draw_store()
                if objs:
                    store[sym] = objs
                else:
                    store.pop(sym, None)
                _save_draw_store(store)
            self._ok(json.dumps({'ok': True, 'sym': sym, 'count': len(objs)}).encode())
        except Exception as e:
            self._err('save draw failed: ' + str(e), 500)

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
    os.chdir(_BASE)
    try:
        import slog as _slog
        _slog.setup('INFO')
        _log = _slog.get_logger('server')
    except Exception:
        _log = None
    d = find_etf_dir()
    files = list_etf_files()
    # v5.0：脈動歷史庫 init + 背景增量同步（只 merge 新日）
    try:
        import pulse_history as _ph
        _ph.init_db()
        _ph.start_background_sync(days=40, force_full=False)
        _ph_msg = f'Pulse history DB: {_ph.DB_PATH} (background merge sync started)'
    except Exception as _phe:
        _ph_msg = f'Pulse history unavailable: {_phe}'
    _msg = (
        f'Stock Terminal v5.0: http://127.0.0.1:{PORT}/stock_terminal_v2.html\n'
        f'Workers: {MAX_WORKERS}  |  LRU cache: {LRU_MAX} symbols (ttl={getattr(_cache, "_ttl", "?")}s)\n'
        f'ETF delta path: {d or "NOT FOUND — set ETF_DELTA_PATH in server.py"}\n'
        f'ETF history files: {len(files)}\n'
        f'{_ph_msg}\n'
        f'Bind: 127.0.0.1:{PORT} (loopback only — housekeeping)'
    )
    if _log:
        for line in _msg.split('\n'):
            _log.info(line)
    else:
        print(_msg)
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
    if getattr(sys, 'frozen', False):
        # 打包成 app 時:啟動後自動開瀏覽器(開發模式由 .bat 開,不重複)
        try:
            import webbrowser
            threading.Timer(1.4, lambda: webbrowser.open(f'http://127.0.0.1:{PORT}/stock_terminal_v2.html')).start()
        except Exception:
            pass
    # H0：只聽 loopback，避免 18432 暴露到區網／公網
    ThreadingHTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
