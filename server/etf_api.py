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
import ETF更新診斷 as tracker_diagnostics

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
    'runId': None,
    'report': None,
}
_tracker_lock = threading.Lock()

def _run_tracker_async():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    tracker = os.path.join(script_dir, 'etf_delta_tracker.py')
    start = time.time()
    run_id = _tracker_state['runId']
    trace = None

    def fail(code, message, output=''):
        report = None
        output = output + '\n' + message
        try:
            if trace:
                report = trace.finish(accepted=False, state='timeout' if code == -2 else 'error',
                                      errorCode=code, message=message)
                (trace.directory / (run_id + '.log')).write_text(output, encoding='utf-8')
        except Exception as exc:
            output += '\n診斷紀錄保存失敗：' + type(exc).__name__
        with _tracker_lock:
            _tracker_state.update(running=False, finishedAt=time.time(),
                                  lastDuration=round(time.time() - start, 1),
                                  lastReturnCode=code, lastOutput=output, report=report)

    try:
        trace = tracker_diagnostics.UpdateTrace(run_id)
        trace.record('process_start')
        if not os.path.isfile(tracker):
            fail(-1, '找不到 ETF 更新程式，未啟動抓取。')
            return
        env = dict(os.environ, ST_ETF_RUN_ID=run_id, PYTHONUTF8='1')
        # Use sys.executable so we hit the same Python that's running server.py
        proc = subprocess.run(
            [sys.executable, tracker],
            cwd=script_dir,
            capture_output=True, text=True,
            encoding='utf-8', errors='replace',
            timeout=300,
            env=env,
        )
        out = (proc.stdout or '') + ('\n' + proc.stderr if proc.stderr else '')
        report = tracker_diagnostics.read_report(run_id)
        if not report or report.get('state') == 'unfinished' or (proc.returncode and report.get('accepted')):
            fail(proc.returncode or -3, '更新程式未留下相符的終止報告，請檢查完整紀錄。', out)
            return
        directory = tracker_diagnostics.run_directory()
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (run_id + '.log')).write_text(out, encoding='utf-8')
        with _tracker_lock:
            _tracker_state.update({
                'running': False,
                'finishedAt': time.time(),
                'lastDuration': round(time.time() - start, 1),
                'lastReturnCode': proc.returncode,
                'lastOutput': out,
                'report': report,
            })
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ''
        if isinstance(partial, bytes):
            partial = partial.decode('utf-8', errors='replace')
        fail(-2, '更新逾時（5 分鐘）；請查看逐筆診斷紀錄。', partial)
    except Exception as e:
        fail(-3, 'ETF 更新例外：' + type(e).__name__)

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


def holding_quantity(holding):
    value = get_field(holding, 'shares', 'quantity', 'volume')
    return int(value) if value is not None else None

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

        current_meta = curr_raw.get(code, {}) if isinstance(curr_raw, dict) else {}
        previous_meta = prev_raw.get(code, {}) if isinstance(prev_raw, dict) else {}
        current_meta = current_meta if isinstance(current_meta, dict) else {}
        previous_meta = previous_meta if isinstance(previous_meta, dict) else {}
        comparison = {'state': 'comparable', 'message': '兩期資料可比較。'}
        if not curr_list:
            comparison = {'state': 'current_missing', 'message': '本期來源缺漏，不能判定減碼或出清。'}
        elif not prev_list:
            comparison = {'state': 'previous_missing', 'message': '缺少前期資料，不能判定新增或加碼。'}
        elif 'moneydj-top10' in (current_meta.get('source'), previous_meta.get('source')):
            comparison = {'state': 'limited_scope', 'message': '至少一期只有前十大部位，暫不判定持股異動。'}
        elif current_meta.get('source') != previous_meta.get('source'):
            comparison = {'state': 'source_changed', 'message': '兩期來源不同，暫不判定持股異動。'}
        elif (current_meta.get('holdingsSchema') != previous_meta.get('holdingsSchema')
              and any(h.get('instrumentType') == 'named_asset' for h in curr_list + prev_list)):
            comparison = {'state': 'schema_changed', 'message': '新增非股票部位辨識，需下一期同格式資料才能比較。'}
        elif current_meta or previous_meta:
            import datetime as dt
            try:
                current_day = dt.date.fromisoformat(current_meta.get('date') or '')
                previous_day = dt.date.fromisoformat(previous_meta.get('date') or '')
                target_day = etf_paths.snapshot_date(curr_file)
                if current_day == previous_day:
                    comparison = {'state': 'same_source_date', 'message': '來源尚未發布新一期資料，不能視為今日無異動。'}
                elif current_day < previous_day or current_day > target_day:
                    comparison = {'state': 'invalid_source_order', 'message': '來源日期順序異常，暫不判定異動。'}
                elif etf_paths.business_day_age(current_day, target_day) > 2:
                    comparison = {'state': 'source_stale', 'message': '本檔來源資料已過期，暫不判定異動。'}
            except (ValueError, TypeError):
                comparison = {'state': 'unknown_source_date', 'message': '缺少可核對的來源日期，暫不判定異動。'}

        def to_map(lst):
            m = {}
            for h in lst:
                sym = get_field(h, 'code','symbol','stock_code','ticker')
                if sym: m[(sym, h.get('market', 'TW'))] = h
            return m

        curr_map = to_map(curr_list)
        prev_map = to_map(prev_list)

        new_stocks, removed, changed = [], [], []

        for identity, h in curr_map.items():
            sym = identity[0]
            w = float(get_field(h,'weight','pct','weight_pct') or 0)
            if identity not in prev_map:
                new_stocks.append({
                    'rank':   get_field(h,'rank','holding_rank') or '-',
                    'code':   sym,
                    'market': h.get('market', 'TW'),
                    'instrumentType': h.get('instrumentType'),
                    'name':   get_field(h,'name','stock_name','company_name') or '',
                    'weight': w,
                    'shares': holding_quantity(h),
                })
            else:
                ph = prev_map[identity]
                pw = float(get_field(ph,'weight','pct','weight_pct') or 0)
                delta = round(w - pw, 4)
                cs = holding_quantity(h)
                ps = holding_quantity(ph)
                sdelta = cs - ps if cs is not None and ps is not None else None
                # v3.8: 以張數變化為主、權重變化為輔（對齊朋友報表）
                if sdelta not in (None, 0) or abs(delta) >= THRESHOLD:
                    changed.append({
                        'rank':         get_field(h,'rank','holding_rank') or '-',
                        'prev_rank':    get_field(ph,'rank','holding_rank') or '-',
                        'code':         sym,
                        'market': h.get('market', 'TW'),
                        'instrumentType': h.get('instrumentType'),
                        'name':         get_field(h,'name','stock_name','company_name') or '',
                        'prev_weight':  pw,
                        'curr_weight':  w,
                        'delta':        delta,
                        'prev_shares':  ps,
                        'curr_shares':  cs,
                        'shares_delta': sdelta,
                    })

        for identity, h in prev_map.items():
            sym = identity[0]
            if identity not in curr_map:
                removed.append({
                    'rank':        get_field(h,'rank','holding_rank') or '-',
                    'code':        sym,
                    'market': h.get('market', 'TW'),
                    'instrumentType': h.get('instrumentType'),
                    'name':        get_field(h,'name','stock_name','company_name') or '',
                    'prev_weight': float(get_field(h,'weight','pct','weight_pct') or 0),
                    'prev_shares': holding_quantity(h),
                })

        if comparison['state'] != 'comparable':
            new_stocks, removed, changed = [], [], []
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
                    'market': h.get('market', 'TW'),
                    'instrumentType': h.get('instrumentType'),
                    'name':   get_field(h, 'name', 'stock_name', 'company_name') or '',
                    'weight': float(get_field(h, 'weight', 'pct', 'weight_pct') or 0),
                    'shares': holding_quantity(h),
                })
        except Exception:
            pass

        # 即使「無變動」也輸出，讓 Top 10 看得到（v3.1 改：原本要 new/rm/chg 至少一個非空）
        if new_stocks or removed or changed or top10 or prev_list:
            etfs_out.append({
                'code':    code,
                'name':    ETF_NAME_MAP.get(code, code),
                'total':   len(curr_list),
                'new':     new_stocks,
                'removed': removed,
                'changed': changed,
                'top10':   top10,   # v3.1 新增：當前 Top 10 持股
                'comparison': comparison,
                'providerDate': current_meta.get('date'),
                'previousProviderDate': previous_meta.get('date'),
                'previousTop10': sorted(prev_list, key=lambda h: float(h.get('weight') or 0), reverse=True)[:10]
                                 if not curr_list else [],
            })

    return {
        'date':      curr_date,
        'prev_date': prev_date,
        'summary':   {'new': total_new, 'removed': total_rm, 'changed': total_chg},
        'etfs':      etfs_out,
    }

