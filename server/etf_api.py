# -*- coding: utf-8 -*-
"""ETF delta / catalog / tracker（從 server.py 拆出 · H2 續）"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import Any, Dict, List, Optional

import etf_paths
from etf_weight_rankings import build_weight_rankings_from_history

try:
    import slog
    log = slog.get_logger('etf_api')
except Exception:
    log = None

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)

ETF_DELTA_PATH = str(etf_paths.resolve_history_dir())
ETF_CATALOG_FILE = os.path.join(_BASE, 'data', 'etf_catalog.json')

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

# ── ETF Delta helpers ──────────────────────────────────────────
def find_etf_dir():
    path = str(etf_paths.resolve_history_dir())
    return path if os.path.isdir(path) else None

def list_etf_files():
    return [str(path) for path in etf_paths.list_snapshot_files()]

def etf_history_status():
    return etf_paths.history_status()

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

def _load_enabled_etf_codes(market=None):
    """讀 etf_catalog.json，回傳目前 enabled=true 的 ETF 代號集合（uppercase）"""
    if not os.path.isfile(ETF_CATALOG_FILE):
        return None   # None = 不做 server 端過濾（fallback 給全部）
    try:
        with open(ETF_CATALOG_FILE, encoding='utf-8') as f:
            cat = json.load(f)
        enabled = set()
        for c in cat.get('categories', []):
            for e in c.get('etfs', []):
                if e.get('enabled') and (market is None or str(e.get('market') or 'TW').upper() == market):
                    code = (e.get('code') or '').strip().upper()
                    if code: enabled.add(code)
        return enabled  # 空集合表示全部停用，不得退回全部可見。
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
        has_baseline = bool(curr_map and prev_map)

        for sym, h in (curr_map.items() if has_baseline else []):
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

        for sym, h in (prev_map.items() if has_baseline else []):
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
                'has_baseline': has_baseline,
                'new':     new_stocks,
                'removed': removed,
                'changed': changed,
                'top10':   top10,   # v3.1 新增：當前 Top 10 持股
            })

    # 週末或來源未更新時，依每檔 ETF 的真正資料日找基準；不以下載日推論交易。
    previous_snapshots = []
    current_index = files.index(curr_file)
    for history_file in reversed(files[max(0, current_index - 20):current_index]):
        try:
            with open(history_file, encoding='utf-8') as handle:
                previous_snapshots.append(json.load(handle))
        except (OSError, ValueError):
            previous_snapshots.append(None)  # 壞檔是明確障礙，不跳過來挑選比較結果。
    rankings = build_weight_rankings_from_history(curr_raw, previous_snapshots, allowed_codes=_load_enabled_etf_codes('TW'))
    return {
        'date':      curr_date,
        'prev_date': prev_date,
        'summary':   {'new': total_new, 'removed': total_rm, 'changed': total_chg},
        'etfs':      etfs_out,
        'weight_rankings': rankings,
    }

