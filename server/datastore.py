#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
datastore.py — v4.0 本機時序資料骨幹（SQLite, 純 stdlib, 零 pip）

單一資料源:把 K 線存進本機 DB,讓 回測 / 選股 / 投組分析 / AI 副駕 都讀「同一份
乾淨、可重現、可離線」的資料,而不是各自即時打 Yahoo。這是 v4.0 的地基:
  - 圖表/即時：仍走原本的即時抓取(要最新報價)
  - 回測/選股/投組/AI：讀 DB(歷史深度 + 秒級查詢)

CLI（在專案根目錄跑）:
  python server\\datastore.py init                 # 建表
  python server\\datastore.py backfill 2330 TW     # 回補單檔(預設 10 年日線)
  python server\\datastore.py backfill 2330 TW 5y  # 指定區間
  python server\\datastore.py query 2330 5          # 看最近 5 根
  python server\\datastore.py stats                 # DB 概況
"""
import os, sys, json, time, sqlite3, urllib.request, urllib.error, random, threading
from contextlib import closing

# 進程內全域寫入鎖
_db_write_lock = threading.Lock()

# 凍結成 exe 時用 exe 目錄;一般執行(server/ 下)時用其上一層 → data/ 在專案根
if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_BASE, 'data', 'market.db')

SCHEMA = """
CREATE TABLE IF NOT EXISTS bars(
  symbol TEXT NOT NULL, market TEXT NOT NULL, ts INTEGER NOT NULL,
  open REAL, high REAL, low REAL, close REAL, volume REAL,
  PRIMARY KEY(symbol, ts)
);
CREATE INDEX IF NOT EXISTS idx_bars_sym_ts ON bars(symbol, ts);
CREATE TABLE IF NOT EXISTS meta(
  symbol TEXT PRIMARY KEY, market TEXT, name TEXT, last_update INTEGER
);
"""

def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute('PRAGMA journal_mode=WAL')     # 並發讀寫
    conn.execute('PRAGMA synchronous=NORMAL')
    return conn

def init_db():
    with closing(get_conn()) as conn:
        with conn:
            conn.executescript(SCHEMA)
    print('[db] ready:', DB_PATH)

def _yf_symbol(sym, market):
    if sym.startswith('^'):
        return sym
    return sym + '.TW' if market == 'TW' else sym

def fetch_yahoo_daily(sym, market, rng='10y', retries=3):
    """自 Yahoo v8 chart API 抓日線(query1/query2 雙端點 + 限流退避重試)。"""
    ysym = _yf_symbol(sym, market)
    last = None
    for attempt in range(retries):
        for host in ('query1', 'query2'):
            url = f'https://{host}.finance.yahoo.com/v8/finance/chart/{ysym}?range={rng}&interval=1d'
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=20) as r:
                    j = json.load(r)
                res = j['chart']['result'][0]
                ts = res['timestamp']
                q = res['indicators']['quote'][0]
                rows = []
                for i, t in enumerate(ts):
                    cl = q['close'][i]
                    if cl is None or cl <= 0:
                        continue
                    op = q['open'][i]
                    hi = q['high'][i]
                    lo = q['low'][i]
                    vol = q['volume'][i] if q['volume'][i] is not None else 0
                    
                    if op is None or op <= 0: op = cl
                    if hi is None or hi <= 0: hi = cl
                    if lo is None or lo <= 0: lo = cl
                    
                    rows.append((t, op, hi, lo, cl, vol))
                return rows
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 429:        # 被限流 → 兩端點都跳過,退避後整體重試
                    break
            except Exception as e:
                last = e
        if attempt < retries - 1:
            time.sleep(min(8, 0.8 * (2 ** attempt)) + random.random())   # 指數退避 + 抖動
    raise RuntimeError(f'fetch failed for {ysym}: {last}')

def upsert_bars(sym, market, rows, recompute_ind=True):
    with _db_write_lock:
        with closing(get_conn()) as conn:
            with conn:
                conn.executemany(
                    'INSERT OR REPLACE INTO bars(symbol,market,ts,open,high,low,close,volume) VALUES(?,?,?,?,?,?,?,?)',
                    [(sym, market, t, o, h, l, cl, v) for (t, o, h, l, cl, v) in rows])
                conn.execute('INSERT OR REPLACE INTO meta(symbol,market,name,last_update) '
                             'VALUES(?,?,COALESCE((SELECT name FROM meta WHERE symbol=?),?),?)',
                             (sym, market, sym, sym, int(time.time())))
    n = len(rows)
    if recompute_ind and n > 0:
        try:
            import ind_cache as ic
            ic.recompute_tip(sym, market)
        except Exception as e:
            print(f'[db] ind_tip recompute {sym}: {e}')
    return n

def backfill(sym, market='TW', rng='10y'):
    rows = fetch_yahoo_daily(sym, market, rng)
    n = upsert_bars(sym, market, rows)
    print(f'[db] {sym}.{market}: stored {n} bars ({rng})')
    return n

def fetch_tw_universe():
    """從 TWSE/TPEx OpenAPI 取上市+上櫃 4 位數普通股代號(排除 ETF 00xxx/權證 6 位)。
       與 server.py 的 _get_tw_universe 同來源,避免分歧。"""
    import re as _re
    code4 = _re.compile(r'^[1-9]\d{3}$')
    codes = set()
    for url in ('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL',
                'https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes'):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=20) as r:
                arr = json.loads(r.read())
            for row in arr:
                if not isinstance(row, dict):
                    continue
                cand = str(row.get('Code') or row.get('SecuritiesCompanyCode')
                           or row.get('證券代號') or row.get('股票代號') or '').strip()
                if code4.match(cand):
                    codes.add(cand); continue
                for v in row.values():
                    if code4.match(str(v).strip()):
                        codes.add(str(v).strip()); break
        except Exception as e:
            print(f'[universe] scan failed {url}: {e}')
    return sorted(codes)

def backfill_universe(market='TW', rng='5y', workers=4, resume=True):
    """一鍵回補全台股宇集:併發抓取(網路)+ 退避重試,主執行緒序列寫入(SQLite 單寫者)。
       resume=True 只補「DB 還沒有」的代號 → 重跑很快、專補限流漏掉的。冪等。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed
    init_db()
    codes = fetch_tw_universe()
    if not codes:
        print('[db] universe empty — 無法取得代號清單(檢查網路/TWSE OpenAPI)'); return
    if resume:
        with closing(get_conn()) as conn:
            have = {r[0] for r in conn.execute('SELECT DISTINCT symbol FROM bars').fetchall()}
        todo = [x for x in codes if x not in have]
        print(f'[db] 全宇集 {len(codes)} 檔,已有 {len(have)},本次補剩餘 {len(todo)} 檔 '
              f'(range={rng}, workers={workers})...')
    else:
        todo = codes
        print(f'[db] universe: {len(todo)} 檔 → 回補中 (range={rng}, workers={workers})...')
    if not todo:
        print('[db] 全部已在 DB,無需回補。'); return
    ok = fail = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_yahoo_daily, c, market, rng): c for c in todo}
        for i, fut in enumerate(as_completed(futs), 1):
            c = futs[fut]
            try:
                upsert_bars(c, market, fut.result())   # 主執行緒序列寫入
                ok += 1
            except Exception:
                fail += 1
            if i % 100 == 0:
                print(f'  ...{i}/{len(todo)}  ok={ok} fail={fail}  ({int(time.time()-t0)}s)')
    print(f'[db] done: ok={ok} fail={fail} / {len(todo)}  ({int(time.time()-t0)}s)')
    if fail:
        print('  提示:仍失敗多半是限流或無 Yahoo 資料的代號;再跑一次同指令會「只補剩餘」(resume),'
              '幾次後就收斂。限流嚴重可降併發:backfill-universe 5y 2')

def get_bars_bulk(codes):
    """一次取多檔 bars,回傳 {code: [(ts,o,h,l,c,v),...]} (依時間排序)。
       單一查詢,避免逐檔開連線 → 選股全宇集讀取秒級。"""
    codes = [str(c) for c in codes]
    if not codes:
        return {}
    out = {c: [] for c in codes}
    with closing(get_conn()) as conn:
        for i in range(0, len(codes), 800):          # 分批避開 SQLite 變數上限
            chunk = codes[i:i + 800]
            ph = ','.join('?' * len(chunk))
            cur = conn.execute(
                f'SELECT symbol,ts,open,high,low,close,volume FROM bars '
                f'WHERE symbol IN ({ph}) ORDER BY symbol, ts', chunk)
            for sym, ts, o, h, l, c, v in cur:
                lst = out.get(sym)
                if lst is not None:
                    lst.append((ts, o, h, l, c, v))
    return out

def last_ts(sym):
    with closing(get_conn()) as conn:
        r = conn.execute('SELECT MAX(ts) FROM bars WHERE symbol=?', (sym,)).fetchone()
    return r[0] if r and r[0] else None

def update(sym, market='TW'):
    """增量更新:已有資料 → 只抓近 1 個月補上(便宜);沒資料 → 全回補 10 年。"""
    if last_ts(sym):
        n = upsert_bars(sym, market, fetch_yahoo_daily(sym, market, '1mo'))
        print(f'[db] {sym}.{market}: refreshed {n} recent bars')
        return n
    return backfill(sym, market)

def get_bars(sym, limit=None):
    """回傳該檔 [(ts,o,h,l,c,v),...] 依時間排序;limit 取最近 N 根。"""
    with closing(get_conn()) as conn:
        rows = conn.execute(
            'SELECT ts,open,high,low,close,volume FROM bars WHERE symbol=? ORDER BY ts',
            (sym,)).fetchall()
    return rows[-limit:] if limit else rows

def _fetch_overall_margin_ratio_twse():
    """使用 TWSE 官方 OpenAPI 數據與公式計算最新台股大盤融資維持率。"""
    try:
        import json
        # 1. 取得每檔股票融資今日餘額 (張)
        url_margin = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
        req = urllib.request.Request(url_margin, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            rows_margin = json.loads(resp.read())
            
        per_stock = {}
        for r in rows_margin:
            if not isinstance(r, dict): continue
            code = r.get("股票代號")
            lots_str = r.get("融資今日餘額")
            if code and lots_str:
                try:
                    lots = float(str(lots_str).replace(",", ""))
                    per_stock[str(code).strip()] = lots
                except Exception: pass

        # 2. 取得每檔股票收盤價
        url_closes = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
        req = urllib.request.Request(url_closes, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            rows_closes = json.loads(resp.read())
            
        closes = {}
        for r in rows_closes:
            if not isinstance(r, dict): continue
            code = r.get("Code")
            cl_str = r.get("ClosingPrice")
            if code and cl_str:
                try:
                    cl = float(str(cl_str).replace(",", ""))
                    closes[str(code).strip()] = cl
                except Exception: pass

        # 3. 取得大盤總融資金額 (元)
        url_total = "https://www.twse.com.tw/exchangeReport/MI_MARGN?response=json&selectType=MS"
        req = urllib.request.Request(url_total, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read())
            
        total_loan = None
        if payload.get("stat") == "OK":
            for table in payload.get("tables", []):
                fields = table.get("fields") or []
                data = table.get("data") or []
                if "今日餘額" not in fields: continue
                idx = fields.index("今日餘額")
                for row in data:
                    if not row: continue
                    if "融資金額" in str(row[0]):
                        try:
                            val = float(str(row[idx]).replace(",", ""))
                            total_loan = val * 1000  # 仟元 -> 元
                            break
                        except Exception: pass
                if total_loan: break

        # 4. 計算加權擔保品市值
        if not per_stock or not closes or not total_loan or total_loan <= 0:
            return None
            
        collateral_value = 0.0
        for code, lots in per_stock.items():
            close = closes.get(code)
            if close is not None and lots > 0:
                collateral_value += lots * 1000.0 * close
                
        if collateral_value <= 0:
            return None
            
        ratio = (collateral_value / total_loan) * 100
        return ratio
    except Exception as e:
        print('[twse] margin ratio calculation failed:', e)
        return None

def backfill_margin_ratio():
    """從 afk13e43/Stock_Notice GitHub 下載大盤融資維持率歷史 CSV 並寫入 bars 表。"""
    url = 'https://raw.githubusercontent.com/afk13e43/Stock_Notice/main/history/tw_history.csv'
    try:
        import csv
        from datetime import datetime, date
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            lines = resp.read().decode('utf-8').splitlines()
        
        reader = csv.DictReader(lines)
        rows = []
        for row in reader:
            dt_str = row.get('date')
            ratio_str = row.get('margin_ratio_pct')
            if not dt_str or not ratio_str:
                continue
            try:
                dt = datetime.strptime(dt_str, '%Y-%m-%d')
                ts = int(dt.timestamp())
                val = float(ratio_str)
                if val <= 0:
                    continue
                rows.append((ts, val, val, val, val, 0))
            except Exception:
                continue
        
        if rows:
            upsert_bars('__MARGIN_RATIO__', 'TW', rows)
            print(f'[db] __MARGIN_RATIO__: stored {len(rows)} bars from CSV')
    except Exception as e:
        print('[db] csv backfill failed:', e)

    # 嘗試計算並追加今日最新值
    try:
        ratio = _fetch_overall_margin_ratio_twse()
        if ratio and ratio > 0:
            from datetime import datetime, date
            today = date.today()
            dt = datetime(today.year, today.month, today.day)
            ts = int(dt.timestamp())
            upsert_bars('__MARGIN_RATIO__', 'TW', [(ts, ratio, ratio, ratio, ratio, 0)])
            print(f'[db] __MARGIN_RATIO__: computed today value {ratio:.2f}%')
    except Exception as e:
        print('[db] today margin ratio compute failed:', e)
    return 0

def get_margin_ratio_bars():
    with closing(get_conn()) as conn:
        cur = conn.execute(
            "SELECT ts, open, high, low, close, volume FROM bars "
            "WHERE symbol = '__MARGIN_RATIO__' ORDER BY ts"
        )
        return cur.fetchall()

def _cli():
    a = sys.argv[1:]
    cmd = a[0] if a else 'init'
    if cmd == 'init':
        init_db()
    elif cmd == 'backfill':
        init_db()
        backfill(a[1], a[2] if len(a) > 2 else 'TW', a[3] if len(a) > 3 else '10y')
    elif cmd == 'backfill_margin':
        init_db()
        backfill_margin_ratio()
    elif cmd == 'update':
        init_db()
        update(a[1], a[2] if len(a) > 2 else 'TW')
    elif cmd == 'backfill-many':
        init_db()
        codes = [x.strip() for x in (a[1] if len(a) > 1 else '').split(',') if x.strip()]
        mk = a[2] if len(a) > 2 else 'TW'
        rng = a[3] if len(a) > 3 else '10y'
        ok = 0
        for code in codes:
            try:
                backfill(code, mk, rng); ok += 1
            except Exception as e:
                print(f'[db] {code}: FAIL {e}')
        print(f'[db] done: {ok}/{len(codes)} symbols')
    elif cmd == 'backfill-universe':
        backfill_universe('TW', a[1] if len(a) > 1 else '5y', int(a[2]) if len(a) > 2 else 8)
    elif cmd == 'update-universe':
        # 對已有檔做近月增量（舊實作 rng=1mo+resume 會跳過已有檔，等於沒更新）
        init_db()
        workers = int(a[1]) if len(a) > 1 else 6
        codes = fetch_tw_universe()
        print(f'[db] update-universe: {len(codes)} 檔, workers={workers}')
        from concurrent.futures import ThreadPoolExecutor, as_completed
        ok = fail = 0
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(update, c, 'TW'): c for c in codes}
            for i, fut in enumerate(as_completed(futs), 1):
                try:
                    fut.result(); ok += 1
                except Exception:
                    fail += 1
                if i % 200 == 0:
                    print(f'  ...{i}/{len(codes)} ok={ok} fail={fail}')
        print(f'[db] update-universe done ok={ok} fail={fail} ({int(time.time()-t0)}s)')
    elif cmd == 'prefetch':
        init_db()
        import ind_cache as ic
        codes = [x.strip() for x in (a[1] if len(a) > 1 else '').split(',') if x.strip()]
        depth = a[2] if len(a) > 2 else '5y'
        items = [{'t': c, 'm': 'TW'} for c in codes]
        print(json.dumps(ic.prefetch_many(items, depth=depth), ensure_ascii=False, indent=2))
    elif cmd == 'query':
        for ts, o, h, l, cl, v in get_bars(a[1], int(a[2]) if len(a) > 2 else 10):
            print(time.strftime('%Y-%m-%d', time.gmtime(ts)),
                  f'O {o} H {h} L {l} C {cl} V {int(v or 0)}')
    elif cmd == 'stats':
        with closing(get_conn()) as conn:
            n = conn.execute('SELECT COUNT(*), COUNT(DISTINCT symbol) FROM bars').fetchone()
        print(f'bars: {n[0]:,}  symbols: {n[1]:,}  db: {DB_PATH}')
        try:
            import ind_cache as ic
            print('ind_tip:', ic.status_summary())
        except Exception as e:
            print('ind_tip: (n/a)', e)
    else:
        print('usage: init | backfill SYM [TW|US] [range] | update SYM [TW|US] | '
              'backfill_margin | '
              'backfill-universe [range] [workers] | update-universe [workers] | '
              'prefetch "a,b,c" [depth] | '
              'backfill-many "a,b,c" [TW|US] [range] | query SYM [N] | stats')

if __name__ == '__main__':
    _cli()
