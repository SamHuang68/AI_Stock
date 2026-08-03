# -*- coding: utf-8 -*-
"""pulse_history.py — TW Pulse 歷史庫（SQLite）+ 增量 merge 同步

策略：
  1) 首次／缺口：回補最近 N 個交易日（預設 40）
  2) 日常：只抓「DB 最大日期之後」的新日 → merge upsert
  3) 資料集：breadth / institutional / index(^TWII/^TWOII) / pulse_score

路徑：data/pulse_history.db（不進 git 敏感區；可分享空殼）
CLI：
  python server/pulse_history.py sync
  python server/pulse_history.py status
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
import time
import urllib.request
from contextlib import closing
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.path.join(_BASE, 'data', 'pulse_history.db')
_lock = threading.Lock()
_sync_state = {
    'running': False,
    'lastStart': None,
    'lastEnd': None,
    'lastOk': None,
    'lastError': None,
    'lastResult': None,
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS breadth_daily(
  d TEXT PRIMARY KEY,
  up INTEGER, down INTEGER, flat INTEGER,
  limit_up INTEGER, limit_down INTEGER,
  adv_ratio REAL, net INTEGER,
  source TEXT, updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS inst_daily(
  d TEXT PRIMARY KEY,
  foreign_net REAL, trust_net REAL, dealer_net REAL, total_net REAL,
  source TEXT, updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS index_daily(
  symbol TEXT NOT NULL, d TEXT NOT NULL,
  open REAL, high REAL, low REAL, close REAL, change_pct REAL, volume REAL,
  source TEXT, updated_at INTEGER,
  PRIMARY KEY(symbol, d)
);
CREATE TABLE IF NOT EXISTS pulse_score_daily(
  d TEXT PRIMARY KEY,
  health REAL, risk REAL, total REAL, completeness REAL,
  status_text TEXT, tone TEXT, payload TEXT,
  updated_at INTEGER
);
CREATE TABLE IF NOT EXISTS sync_meta(
  dataset TEXT PRIMARY KEY,
  data_date TEXT,
  last_success INTEGER,
  status TEXT,
  note TEXT,
  rows INTEGER
);
"""

_UA = {'User-Agent': 'Mozilla/5.0 (compatible; StockTerminal/5.0; +local)', 'Accept': 'application/json'}


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute('PRAGMA journal_mode=WAL')
    c.execute('PRAGMA synchronous=NORMAL')
    return c


def init_db():
    with _lock:
        with closing(_conn()) as conn:
            with conn:
                conn.executescript(SCHEMA)


def _set_meta(conn, dataset: str, data_date: Optional[str], status: str, note: str = '', rows: int = 0):
    conn.execute(
        'INSERT OR REPLACE INTO sync_meta(dataset,data_date,last_success,status,note,rows) VALUES(?,?,?,?,?,?)',
        (dataset, data_date, int(time.time()) if status in ('同步完成', '部分資料可用') else None,
         status, note, rows),
    )


def _max_date(conn, table: str, col: str = 'd') -> Optional[str]:
    row = conn.execute(f'SELECT MAX({col}) FROM {table}').fetchone()
    return row[0] if row and row[0] else None


def _http_json(url: str, timeout: int = 18):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8', 'replace'))


def _fnum(v):
    if v in (None, '', '-', '—'):
        return None
    try:
        return float(str(v).replace(',', '').replace('+', '').strip())
    except Exception:
        return None


# ── fetchers ─────────────────────────────────────────────────

def _fetch_twse_index_month(yyyymm: str) -> List[dict]:
    """MI_INDEX type=IND 當月加權／櫃買列 → [{d,t00_close,o00_close,...}] 簡化：用 Yahoo for OHLC."""
    return []


def fetch_index_yahoo(symbol: str, rng: str = '3mo') -> List[Tuple]:
    """回 [(d,o,h,l,c,pct,vol)] ISO date。"""
    ysym = symbol if symbol.startswith('^') else symbol
    last = None
    for host in ('query1', 'query2'):
        url = f'https://{host}.finance.yahoo.com/v8/finance/chart/{ysym}?range={rng}&interval=1d'
        try:
            j = _http_json(url, timeout=20)
            res = (j.get('chart') or {}).get('result') or []
            if not res:
                continue
            r0 = res[0]
            ts = r0.get('timestamp') or []
            q = ((r0.get('indicators') or {}).get('quote') or [{}])[0]
            out = []
            prev = None
            for i, t in enumerate(ts):
                cl = (q.get('close') or [None])[i] if i < len(q.get('close') or []) else None
                if cl is None:
                    continue
                op = (q.get('open') or [None])[i]
                hi = (q.get('high') or [None])[i]
                lo = (q.get('low') or [None])[i]
                vol = (q.get('volume') or [None])[i]
                if op is None:
                    op = cl
                if hi is None:
                    hi = cl
                if lo is None:
                    lo = cl
                d = datetime.utcfromtimestamp(t).strftime('%Y-%m-%d')
                pct = ((cl - prev) / prev * 100.0) if prev else None
                out.append((d, float(op), float(hi), float(lo), float(cl), pct, float(vol or 0)))
                prev = cl
            return out
        except Exception as e:
            last = e
    if last:
        raise RuntimeError(str(last))
    return []


def fetch_breadth_day(yyyymmdd: str) -> Optional[dict]:
    """單日 TWSE MI_INDEX MS 漲跌家數。"""
    import re
    for url in (
        f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={yyyymmdd}&type=MS&response=json',
        f'https://www.twse.com.tw/exchangeReport/MI_INDEX?date={yyyymmdd}&type=MS&response=json',
    ):
        try:
            d = _http_json(url, timeout=14)
            if d.get('stat') not in ('OK', 'ok'):
                continue
            tables = d.get('tables') or []
            rows = None
            for t in tables:
                title = str(t.get('title') or '')
                if '漲跌' in title or '證券' in title:
                    rows = t.get('data') or []
                    if rows:
                        break
            if not rows and tables:
                rows = tables[0].get('data') or []
            ad = {'up': None, 'down': None, 'flat': None, 'limit_up': None, 'limit_down': None}

            def pair(cell):
                t = str(cell or '').replace(',', '').strip()
                m = re.match(r'^([0-9.]+)\((\d+)\)$', t)
                if m:
                    return int(float(m.group(1))), int(m.group(2))
                n = _fnum(t)
                return (int(n), None) if n is not None else (None, None)

            for row in rows or []:
                if not row:
                    continue
                label = str(row[0])
                # 股票欄通常 col=2；整體 col=1 — 優先股票
                cell = row[2] if len(row) > 2 else (row[1] if len(row) > 1 else None)
                if '上漲' in label:
                    ad['up'], ad['limit_up'] = pair(cell)
                elif '下跌' in label:
                    ad['down'], ad['limit_down'] = pair(cell)
                elif '持平' in label:
                    ad['flat'], _ = pair(cell)
            if ad['up'] is None and ad['down'] is None:
                return None
            u, dn = ad['up'] or 0, ad['down'] or 0
            den = u + dn
            return {
                'd': f'{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}',
                'up': ad['up'], 'down': ad['down'], 'flat': ad['flat'],
                'limit_up': ad['limit_up'], 'limit_down': ad['limit_down'],
                'adv_ratio': round(u / den, 4) if den else None,
                'net': (u - dn) if ad['up'] is not None and ad['down'] is not None else None,
                'source': 'TWSE MI_INDEX MS',
            }
        except Exception:
            continue
    return None


def fetch_inst_day(yyyymmdd: str) -> Optional[dict]:
    """BFI82U 三大法人合計（元）。"""
    url = f'https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate={yyyymmdd}&type=day&response=json'
    try:
        d = _http_json(url, timeout=14)
        if d.get('stat') not in ('OK', 'ok'):
            return None
        fields = d.get('fields') or []
        rows = d.get('data') or []
        i_name = next((i for i, f in enumerate(fields) if '單位名稱' in f or '買賣別' in f), 0)
        i_net = next((i for i, f in enumerate(fields) if '買賣差' in f or '買賣超' in f), len(fields) - 1)
        foreign = trust = dealer = None
        for row in rows:
            nm = str(row[i_name])
            try:
                net = float(str(row[i_net]).replace(',', ''))
            except Exception:
                continue
            if '外' in nm:
                foreign = (foreign or 0) + net
            elif '投信' in nm:
                trust = net
            elif '自營' in nm:
                dealer = (dealer or 0) + net
        if foreign is None and trust is None and dealer is None:
            return None
        total = (foreign or 0) + (trust or 0) + (dealer or 0)
        return {
            'd': f'{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}',
            'foreign_net': foreign, 'trust_net': trust, 'dealer_net': dealer,
            'total_net': total, 'source': 'TWSE BFI82U',
        }
    except Exception:
        return None


# ── merge sync ───────────────────────────────────────────────

def sync(days: int = 40, force_full: bool = False) -> Dict[str, Any]:
    """增量同步：只補 DB 缺口／最近日。回摘要。"""
    init_db()
    if _sync_state['running']:
        return {'ok': False, 'error': 'sync already running', 'state': status()}
    _sync_state['running'] = True
    _sync_state['lastStart'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    _sync_state['lastError'] = None
    result = {
        'ok': True, 'breadth': 0, 'inst': 0, 'index': 0, 'skipped': 0,
        'datasets': [], 'mode': 'full' if force_full else 'merge',
    }
    try:
        today = date.today()
        with _lock:
            with closing(_conn()) as conn:
                # ── indices：Yahoo 一次抓 3mo，upsert 全部（天然 merge）──
                idx_n = 0
                for sym in ('^TWII', '^TWOII'):
                    try:
                        rows = fetch_index_yahoo(sym, '3mo')
                        now = int(time.time())
                        for d, o, h, l, c, pct, vol in rows:
                            conn.execute(
                                'INSERT OR REPLACE INTO index_daily(symbol,d,open,high,low,close,change_pct,volume,source,updated_at) '
                                'VALUES(?,?,?,?,?,?,?,?,?,?)',
                                (sym, d, o, h, l, c, pct, vol, 'yahoo', now))
                            idx_n += 1
                        last_d = rows[-1][0] if rows else None
                        _set_meta(conn, f'index:{sym}', last_d, '同步完成' if rows else '同步失敗',
                                  '' if rows else 'no rows', len(rows))
                    except Exception as e:
                        _set_meta(conn, f'index:{sym}', None, '同步失敗', str(e)[:160], 0)
                result['index'] = idx_n
                conn.commit()

                # ── breadth / inst：自 max_date+1 走到今天（跳週末）──
                max_b = None if force_full else _max_date(conn, 'breadth_daily')
                max_i = None if force_full else _max_date(conn, 'inst_daily')
                start_b = today - timedelta(days=days)
                if max_b:
                    try:
                        start_b = max(start_b, datetime.strptime(max_b, '%Y-%m-%d').date() + timedelta(days=1))
                    except Exception:
                        pass
                start_i = today - timedelta(days=days)
                if max_i:
                    try:
                        start_i = max(start_i, datetime.strptime(max_i, '%Y-%m-%d').date() + timedelta(days=1))
                    except Exception:
                        pass

                b_n = i_n = 0
                # 若已是最新交易日則 skipped
                cur = min(start_b, start_i)
                if cur > today:
                    result['skipped'] = 1
                dcur = start_b
                while dcur <= today:
                    if dcur.weekday() < 5:
                        ymd = dcur.strftime('%Y%m%d')
                        row = fetch_breadth_day(ymd)
                        if row:
                            conn.execute(
                                'INSERT OR REPLACE INTO breadth_daily(d,up,down,flat,limit_up,limit_down,adv_ratio,net,source,updated_at) '
                                'VALUES(?,?,?,?,?,?,?,?,?,?)',
                                (row['d'], row['up'], row['down'], row['flat'], row['limit_up'], row['limit_down'],
                                 row['adv_ratio'], row['net'], row['source'], int(time.time())))
                            b_n += 1
                        time.sleep(0.25)
                    dcur += timedelta(days=1)
                _set_meta(conn, 'breadth', _max_date(conn, 'breadth_daily'),
                          '同步完成' if b_n or max_b else '部分資料可用',
                          f'merged {b_n} days', b_n)

                dcur = start_i
                while dcur <= today:
                    if dcur.weekday() < 5:
                        ymd = dcur.strftime('%Y%m%d')
                        row = fetch_inst_day(ymd)
                        if row:
                            conn.execute(
                                'INSERT OR REPLACE INTO inst_daily(d,foreign_net,trust_net,dealer_net,total_net,source,updated_at) '
                                'VALUES(?,?,?,?,?,?,?)',
                                (row['d'], row['foreign_net'], row['trust_net'], row['dealer_net'],
                                 row['total_net'], row['source'], int(time.time())))
                            i_n += 1
                        time.sleep(0.25)
                    dcur += timedelta(days=1)
                _set_meta(conn, 'institutional', _max_date(conn, 'inst_daily'),
                          '同步完成' if i_n or max_i else '部分資料可用',
                          f'merged {i_n} days', i_n)

                result['breadth'] = b_n
                result['inst'] = i_n
                conn.commit()

                # datasets snapshot
                for r in conn.execute('SELECT dataset,data_date,last_success,status,note,rows FROM sync_meta ORDER BY dataset'):
                    result['datasets'].append({
                        'dataset': r[0], 'dataDate': r[1], 'lastSuccess': r[2],
                        'status': r[3], 'note': r[4], 'rows': r[5],
                    })

        _sync_state['lastOk'] = time.strftime('%Y-%m-%dT%H:%M:%S')
        _sync_state['lastResult'] = result
        return result
    except Exception as e:
        _sync_state['lastError'] = str(e)
        result['ok'] = False
        result['error'] = str(e)
        return result
    finally:
        _sync_state['running'] = False
        _sync_state['lastEnd'] = time.strftime('%Y-%m-%dT%H:%M:%S')


def save_pulse_score(payload: dict) -> None:
    """把當次 /pulse 分數寫入歷史（以資料日或今天為鍵）。"""
    init_db()
    d = (payload.get('date') or date.today().strftime('%Y%m%d'))
    if len(d) == 8 and '-' not in d:
        d = f'{d[:4]}-{d[4:6]}-{d[6:8]}'
    with _lock:
        with closing(_conn()) as conn:
            with conn:
                conn.execute(
                    'INSERT OR REPLACE INTO pulse_score_daily(d,health,risk,total,completeness,status_text,tone,payload,updated_at) '
                    'VALUES(?,?,?,?,?,?,?,?,?)',
                    (d, payload.get('healthScore'), payload.get('riskScore'), payload.get('totalScore'),
                     payload.get('dataCompleteness'), payload.get('statusText'), payload.get('tone'),
                     json.dumps({
                         'positiveFactorScore': payload.get('positiveFactorScore'),
                         'datasetsOk': payload.get('datasetsOk'),
                         'datasetsTotal': payload.get('datasetsTotal'),
                     }, ensure_ascii=False), int(time.time())))


def history(kind: str = 'breadth', n: int = 40) -> Dict[str, Any]:
    init_db()
    n = max(1, min(int(n or 40), 120))
    with closing(_conn()) as conn:
        if kind == 'breadth':
            rows = conn.execute(
                'SELECT d,up,down,flat,limit_up,limit_down,adv_ratio,net FROM breadth_daily ORDER BY d DESC LIMIT ?',
                (n,)).fetchall()
            return {'ok': True, 'kind': kind, 'rows': [
                {'date': r[0], 'up': r[1], 'down': r[2], 'flat': r[3], 'limitUp': r[4], 'limitDown': r[5],
                 'advRatio': r[6], 'net': r[7], 'lsRatio': (round(r[1] / r[2], 2) if r[1] and r[2] else None)}
                for r in rows
            ]}
        if kind in ('inst', 'institutional'):
            rows = conn.execute(
                'SELECT d,foreign_net,trust_net,dealer_net,total_net FROM inst_daily ORDER BY d DESC LIMIT ?',
                (n,)).fetchall()
            return {'ok': True, 'kind': 'institutional', 'rows': [
                {'date': r[0], 'foreign': r[1], 'trust': r[2], 'dealer': r[3], 'total': r[4],
                 'foreignYi': None if r[1] is None else round(r[1] / 1e8, 1),
                 'trustYi': None if r[2] is None else round(r[2] / 1e8, 1),
                 'dealerYi': None if r[3] is None else round(r[3] / 1e8, 1),
                 'totalYi': None if r[4] is None else round(r[4] / 1e8, 1)}
                for r in rows
            ]}
        if kind in ('index', 'twii'):
            sym = '^TWII' if kind != 'twoii' else '^TWOII'
            if kind == 'index':
                sym = '^TWII'
            rows = conn.execute(
                'SELECT d,open,high,low,close,change_pct,volume FROM index_daily WHERE symbol=? ORDER BY d DESC LIMIT ?',
                (sym, n)).fetchall()
            return {'ok': True, 'kind': kind, 'symbol': sym, 'rows': [
                {'date': r[0], 'open': r[1], 'high': r[2], 'low': r[3], 'close': r[4],
                 'changePct': r[5], 'volume': r[6]} for r in rows
            ]}
        if kind in ('pulse', 'score'):
            rows = conn.execute(
                'SELECT d,health,risk,total,completeness,status_text,tone FROM pulse_score_daily ORDER BY d DESC LIMIT ?',
                (n,)).fetchall()
            return {'ok': True, 'kind': 'pulse', 'rows': [
                {'date': r[0], 'health': r[1], 'risk': r[2], 'total': r[3],
                 'completeness': r[4], 'statusText': r[5], 'tone': r[6]} for r in rows
            ]}
    return {'ok': False, 'error': f'unknown kind {kind}'}


def status() -> Dict[str, Any]:
    init_db()
    datasets = []
    with closing(_conn()) as conn:
        for r in conn.execute('SELECT dataset,data_date,last_success,status,note,rows FROM sync_meta ORDER BY dataset'):
            datasets.append({
                'dataset': r[0], 'dataDate': r[1], 'lastSuccess': r[2],
                'status': r[3], 'note': r[4], 'rows': r[5],
            })
        counts = {
            'breadth': conn.execute('SELECT COUNT(*) FROM breadth_daily').fetchone()[0],
            'institutional': conn.execute('SELECT COUNT(*) FROM inst_daily').fetchone()[0],
            'index': conn.execute('SELECT COUNT(*) FROM index_daily').fetchone()[0],
            'pulseScore': conn.execute('SELECT COUNT(*) FROM pulse_score_daily').fetchone()[0],
        }
    return {
        'ok': True,
        'db': DB_PATH,
        'running': _sync_state['running'],
        'lastStart': _sync_state['lastStart'],
        'lastEnd': _sync_state['lastEnd'],
        'lastOk': _sync_state['lastOk'],
        'lastError': _sync_state['lastError'],
        'lastResult': _sync_state['lastResult'],
        'counts': counts,
        'datasets': datasets,
        'version': '5.0',
    }


def start_background_sync(days: int = 40, force_full: bool = False):
    if _sync_state['running']:
        return False

    def _run():
        print('[pulse-history] sync start days=', days, 'full=', force_full)
        r = sync(days=days, force_full=force_full)
        print('[pulse-history] sync done', r.get('ok'), 'b', r.get('breadth'), 'i', r.get('inst'), 'x', r.get('index'))

    threading.Thread(target=_run, daemon=True).start()
    return True


if __name__ == '__main__':
    cmd = sys.argv[1] if len(sys.argv) > 1 else 'status'
    if cmd == 'sync':
        days = int(sys.argv[2]) if len(sys.argv) > 2 else 40
        print(json.dumps(sync(days=days), ensure_ascii=False, indent=2))
    elif cmd == 'status':
        print(json.dumps(status(), ensure_ascii=False, indent=2))
    else:
        print('usage: pulse_history.py sync|status')
