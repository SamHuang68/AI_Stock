"""datasources.py — 資料源集中管理(registry)+ 一鍵更新。

把全 app 的資料源做成一張表:每個來源標明「提供者 / 可靠度 / 本地資料 / 最後更新 / 筆數」,
可更新的提供一鍵 refresh。確保資料來自可靠來源、且能即時更新。

可靠度 reliability:
  official  — 官方(TWSE / TPEx / TAIFEX / NASDAQ Trader)
  vendor    — 第三方(Yahoo Finance / MoneyDJ)
  local     — 本地維護(目錄檔)
更新類型 kind:
  file   — 本地快取檔(可一鍵重抓)
  db     — SQLite 時序庫(可一鍵更新近月)
  daily  — 記憶體日快取(每日自動;更新=清快取下次重抓)
  live   — 即時抓取(無快取,永遠最新,無需更新)
"""
import glob
import json
import os
import subprocess
import sys
import time

if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
    _PYEXE = sys.executable          # frozen:用自己(不會有獨立 python)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _PYEXE = sys.executable
DATA = os.path.join(_BASE, 'data')
SRV = os.path.dirname(os.path.abspath(__file__))


def _mtime(path):
    try:
        return int(os.path.getmtime(path))
    except Exception:
        return 0


def _newest_glob(pat):
    files = glob.glob(pat)
    ts = max((_mtime(f) for f in files), default=0)
    return ts, len(files)


def _spawn(script, *args):
    """背景跑 tracker 腳本(非阻塞)。frozen 環境無獨立 python 則回提示。"""
    if getattr(sys, 'frozen', False):
        return {'ok': False, 'error': '打包版無獨立 Python,請用排程或原始碼版執行此更新'}
    path = os.path.join(SRV, script)
    if not os.path.exists(path):
        return {'ok': False, 'error': f'找不到 {script}'}
    try:
        subprocess.Popen([_PYEXE, path, *args], cwd=_BASE,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {'ok': True, 'started': True, 'note': '已在背景開始更新,完成後重整即可看到'}
    except Exception as e:
        return {'ok': False, 'error': str(e)}


# ── 各來源狀態 ──────────────────────────────────────────────
def _st_universe():
    p = os.path.join(DATA, 'universe.json')
    n = 0
    try:
        d = json.load(open(p, encoding='utf-8'))
        c = d.get('counts', {})
        n = (c.get('tw', 0) or 0) + (c.get('us', 0) or 0)
    except Exception:
        pass
    return {'updated': _mtime(p), 'count': n}


def _st_db():
    p = os.path.join(DATA, 'market.db')
    n = 0
    try:
        import sqlite3
        con = sqlite3.connect(p)
        n = con.execute('SELECT COUNT(*) FROM meta').fetchone()[0]
        con.close()
    except Exception:
        pass
    return {'updated': _mtime(p), 'count': n}


def _st_etf():
    ts, n = _newest_glob(os.path.join(DATA, 'etf_history', '*.json'))
    return {'updated': ts, 'count': n}


def _st_chip():
    ts, n = _newest_glob(os.path.join(DATA, 'chip_history', '*.json'))
    return {'updated': ts, 'count': n}


def _st_catalog():
    p = os.path.join(DATA, 'etf_catalog.json')
    n = 0
    try:
        d = json.load(open(p, encoding='utf-8'))
        n = sum(len(g.get('etfs', [])) for g in d.get('categories', []))
    except Exception:
        pass
    return {'updated': _mtime(p), 'count': n}


def _st_margin_ratio():
    p = os.path.join(DATA, 'margin_ratio_history.csv')
    n = 0
    try:
        import sqlite3
        db = os.path.join(DATA, 'market.db')
        con = sqlite3.connect(db)
        n = con.execute(
            "SELECT COUNT(*) FROM bars WHERE symbol='__MARGIN_RATIO__'"
        ).fetchone()[0]
        con.close()
    except Exception:
        pass
    return {'updated': _mtime(p), 'count': n}


# ── Registry(順序即顯示順序) ──────────────────────────────
def _registry():
    return [
        {'id': 'universe', 'name': '代號庫(台股+美股)', 'provider': 'TWSE / TPEx OpenAPI · NASDAQ Trader',
         'reliability': 'official', 'kind': 'file', 'updatable': True,
         'desc': '全台股(含 ETF/上櫃)+ 美股 代號↔名稱,判市場與驗證存在', 'status': _st_universe()},
        {'id': 'db', 'name': '本機日線歷史庫', 'provider': 'Yahoo Finance v8',
         'reliability': 'vendor', 'kind': 'db', 'updatable': True,
         'desc': '全市場日線(選股/回測/投組共用);更新=補近月', 'status': _st_db()},
        {'id': 'margin_ratio', 'name': '大盤融資維持率', 'provider': 'TWSE (MacroMicro-aligned)',
         'reliability': 'official', 'kind': 'db', 'updatable': True,
         'desc': 'Σ(融資市值,不含ETF)/融資金額；seed CSV + TWSE 歷史回補 + 今日即時',
         'status': _st_margin_ratio()},
        {'id': 'etf', 'name': '主動 ETF 每日持股', 'provider': 'MoneyDJ + TWSE',
         'reliability': 'vendor', 'kind': 'file', 'updatable': True,
         'desc': '主動 ETF 完整持股快照,算每日加減碼 delta', 'status': _st_etf()},
        {'id': 'chip', 'name': '法人籌碼(三大法人)', 'provider': 'TWSE',
         'reliability': 'official', 'kind': 'file', 'updatable': True,
         'desc': '外資/投信/自營買賣超,累積連買賣天數', 'status': _st_chip()},
        {'id': 'catalog', 'name': 'ETF 目錄', 'provider': '本地維護',
         'reliability': 'local', 'kind': 'file', 'updatable': False,
         'desc': 'ETF 分類庫(前端 ⚙ 管理或編輯 etf_catalog.json)', 'status': _st_catalog()},
        {'id': 'twfund', 'name': '估值 / 月營收 / 名稱 / 產業', 'provider': 'TWSE / TPEx OpenAPI',
         'reliability': 'official', 'kind': 'daily', 'updatable': False,
         'desc': '本益比/殖利率/股價淨值比、月營收三率、代號中文名、產業別 — 每日自動快取', 'status': {'updated': 0, 'count': 0}},
        {'id': 'live', 'name': '即時報價 / 指數 / 台指期', 'provider': 'Yahoo · TWSE MIS · TAIFEX MIS',
         'reliability': 'official', 'kind': 'live', 'updatable': False,
         'desc': 'K 線、加權/櫃買即時、台指期夜盤 — 即時抓取,永遠最新', 'status': {'updated': 0, 'count': 0}},
    ]


def list_sources():
    return {'sources': _registry(), 'now': int(time.time())}


def refresh(sid):
    if sid == 'universe':
        try:
            import universe
            d = universe.build()
            return {'ok': True, 'count': d['counts']['tw'] + d['counts']['us']}
        except Exception as e:
            return {'ok': False, 'error': str(e)}
    if sid == 'db':
        return _spawn('datastore.py', 'update')
    if sid == 'margin_ratio':
        return _spawn('margin_ratio.py', 'backfill', '--full')
    if sid == 'etf':
        return _spawn('etf_delta_tracker.py')
    if sid == 'chip':
        return _spawn('chip_history_tracker.py')
    return {'ok': False, 'error': f'{sid} 無可用的一鍵更新(即時/自動/本地維護來源)'}
