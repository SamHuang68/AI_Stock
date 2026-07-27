#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
macro_track.py — MacroMicro 風格多序列總經／籌碼追蹤圖

圖表：
  __TW_RATES__         台灣指標利率（重貼現／擔保放款／短期融通）
  __TW_MARGIN_MIX__    上櫃／上市融資張數比年增率 vs 加權
  __US_RATES_CREDIT__  美國基準利率+10Y vs 美林 IG/HY 總報酬
  __US_CPI_FIN__       美國 CPI YoY + 基準利率 vs 金融類股(XLF)

資料來源：
  - CBC 英文利率走廊頁（種子 CSV + 可即時重抓）
  - TWSE MI_MARGN(MS) + TPEx margin/balance（融資張數）
  - FRED（優先；雲端常逾時）→ 備援：
      · Fed Funds：NY Fed EFFR API
      · 10Y：Fed H.15 / Yahoo ^TNX
      · BAML IG/HY：Yahoo LQD / HYG 還原收盤（總報酬代理）
      · CPI YoY：BLS CUUR0000SA0 自算年增
  - Yahoo（^TWII / XLF / LQD / HYG / ^TNX）
"""
from __future__ import annotations

import csv
import json
import os
import re
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from html import unescape
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
CBC_DAILY = os.path.join(DATA, 'cbc_policy_rates.csv')
CBC_CHANGES = os.path.join(DATA, 'cbc_policy_rate_changes.csv')
MARGIN_MIX_CSV = os.path.join(DATA, 'tw_margin_mix_daily.csv')
DB_PATH = os.path.join(DATA, 'macro_track.db')
SEED_DIR = os.path.join(DATA, 'macro_seeds')

UA = {'User-Agent': 'Mozilla/5.0 (compatible; StockTerminal/4.1; +local)'}
UA_BROWSER = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/csv,application/json,text/html,*/*',
}


# ── Chart registry (metadata for API + frontend) ──────────────
CHARTS: Dict[str, Dict[str, Any]] = {
    '__TW_RATES__': {
        'id': '__TW_RATES__',
        'name': '台灣指標利率',
        'shortName': '台利率',
        'market': 'TW',
        'defaultRange': 'max',
        'years': 25,
        'description': '央行利率走廊：重貼現／擔保放款融通／短期融通',
        'series': [
            {'key': 'discount', 'name': '重貼現率', 'scale': 'left', 'color': '#38BDF8', 'style': 'line', 'unit': '%'},
            {'key': 'secured',  'name': '擔保放款融通利率', 'scale': 'left', 'color': '#F87171', 'style': 'line', 'unit': '%'},
            {'key': 'short',    'name': '短期融通利率', 'scale': 'left', 'color': '#4ADE80', 'style': 'line', 'unit': '%'},
        ],
    },
    '__TW_MARGIN_MIX__': {
        'id': '__TW_MARGIN_MIX__',
        'name': '上櫃／上市融資張數比年增',
        'shortName': '融資比YoY',
        'market': 'TW',
        'defaultRange': 'max',
        'years': 20,
        'description': '上櫃融資張數÷上市融資張數 年增率 vs 加權指數',
        'series': [
            {'key': 'yoy', 'name': '上櫃/上市融資比年增率', 'scale': 'left', 'color': '#38BDF8', 'style': 'line', 'unit': '%'},
            {'key': 'twii', 'name': '加權指數', 'scale': 'right', 'color': '#F87171', 'style': 'line', 'unit': '',
             'source': 'yahoo', 'symbol': '^TWII'},
        ],
    },
    '__US_RATES_CREDIT__': {
        'id': '__US_RATES_CREDIT__',
        'name': '美國利率 vs 公司債總報酬',
        'shortName': '美利率債',
        'market': 'US',
        'defaultRange': 'max',
        'years': 25,
        'description': 'Fed＋10Y vs 美林 IG／HY 總報酬（FRED 優先；備援 LQD/HYG）',
        'series': [
            {'key': 'fedfunds', 'name': '基準利率', 'scale': 'left', 'color': '#94A3B8', 'style': 'line', 'unit': '%',
             'source': 'fred', 'fred': 'FEDFUNDS', 'fallback': 'nyfed_effr', 'seed': 'fedfunds.csv'},
            {'key': 'us10y', 'name': '10年期公債殖利率', 'scale': 'left', 'color': '#D4A574', 'style': 'line', 'unit': '%',
             'source': 'fred', 'fred': 'DGS10', 'fallback': 'h15_10y', 'seed': 'us10y.csv'},
            {'key': 'baml_ig', 'name': '美林投資級總報酬', 'scale': 'right', 'color': '#6B9BB8', 'style': 'line', 'unit': '',
             'source': 'fred', 'fred': 'BAMLCC0A0CMTRIV', 'fallback': 'yahoo_adj', 'symbol': 'LQD', 'seed': 'baml_ig.csv'},
            {'key': 'baml_hy', 'name': '美林高收益總報酬', 'scale': 'right', 'color': '#B89595', 'style': 'line', 'unit': '',
             'source': 'fred', 'fred': 'BAMLHY0A0HYMTRIV', 'fallback': 'yahoo_adj', 'symbol': 'HYG', 'seed': 'baml_hy.csv'},
        ],
    },
    '__US_CPI_FIN__': {
        'id': '__US_CPI_FIN__',
        'name': '美國CPI＆基準利率 vs 金融股',
        'shortName': 'CPI金融',
        'market': 'US',
        'defaultRange': 'max',
        'years': 20,
        'description': 'CPI YoY＋Fed vs 金融類股(XLF 代理總報酬)',
        'series': [
            {'key': 'us_cpi_yoy', 'name': 'CPI年增率', 'scale': 'left', 'color': '#7DD3FC', 'style': 'histogram', 'unit': '%',
             'source': 'fred', 'fred': 'CPALTT01USM659N', 'fallback': 'bls_cpi_yoy', 'seed': 'us_cpi_yoy.csv'},
            {'key': 'fedfunds', 'name': '基準利率', 'scale': 'left', 'color': '#4ADE80', 'style': 'histogram', 'unit': '%',
             'source': 'fred', 'fred': 'FEDFUNDS', 'fallback': 'nyfed_effr', 'seed': 'fedfunds.csv'},
            {'key': 'xlf', 'name': '金融類股(XLF)', 'scale': 'right', 'color': '#F59E0B', 'style': 'line', 'unit': '',
             'source': 'yahoo', 'symbol': 'XLF', 'seed': 'xlf.csv'},
        ],
    },
    '__TW_MARGIN_CYCLE__': {
        'id': '__TW_MARGIN_CYCLE__',
        'name': '融資週期（槓桿臨界）',
        'shortName': '融資週期',
        'market': 'TW',
        'defaultRange': 'max',
        'years': 20,
        'description': '維持率臨界＋融資餘額熱度＋券資結構，觀察牛熊槓桿週期',
        'series': [
            {'key': 'margin_ratio', 'name': '融資維持率', 'scale': 'left', 'color': '#6B9BB8', 'style': 'line', 'unit': '%'},
            {'key': 'margin_yoy', 'name': '融資餘額年增率', 'scale': 'left', 'color': '#B89595', 'style': 'line', 'unit': '%'},
            {'key': 'ss_ratio', 'name': '券資比', 'scale': 'left', 'color': '#8FA88F', 'style': 'line', 'unit': '%'},
            {'key': 'twii', 'name': '加權指數', 'scale': 'right', 'color': '#D4A574', 'style': 'line', 'unit': ''},
        ],
    },
}


def list_charts() -> List[Dict[str, Any]]:
    return [
        {
            'id': c['id'], 'name': c['name'], 'shortName': c['shortName'],
            'market': c['market'], 'description': c.get('description', ''),
            'series': [{'key': s['key'], 'name': s['name'], 'scale': s['scale'], 'color': s['color'], 'style': s.get('style', 'line')}
                       for s in c['series']],
        }
        for c in CHARTS.values()
    ]


def is_macro_chart(sym: str) -> bool:
    return str(sym or '').upper() in CHARTS


# ── SQLite helpers ────────────────────────────────────────────
def _db() -> sqlite3.Connection:
    os.makedirs(DATA, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS margin_mix (
             d TEXT PRIMARY KEY,
             listed REAL NOT NULL,
             otc REAL NOT NULL,
             ratio REAL,
             yoy REAL
           )'''
    )
    conn.commit()
    return conn


def _http_json(url: str, timeout: int = 25) -> Any:
    req = urllib.request.Request(url, headers={**UA, 'Accept': 'application/json,text/html,*/*'})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    text = raw.decode('utf-8-sig', 'replace')
    return json.loads(text)


def _http_text(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode('utf-8', 'replace')


# ── CBC policy rates ──────────────────────────────────────────
def scrape_cbc_rate_changes() -> List[Tuple[date, float, float, float]]:
    """抓 CBC 英文利率走廊頁（分頁），回 (date, discount, secured, short)。"""
    seen: Dict[str, Tuple[date, float, float, float]] = {}
    for page in range(1, 40):
        url = f'https://www.cbc.gov.tw/en/lp-695-2-{page}-20.html'
        try:
            t = _http_text(url, timeout=20)
        except Exception as e:
            print('[macro_track] CBC page', page, 'fail:', e)
            break
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', t, re.S | re.I)
        n = 0
        for r in rows:
            cells = re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, re.S | re.I)
            cells = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
            cells = [unescape(c).replace('\xa0', ' ').strip() for c in cells]
            cells = [c for c in cells if c]
            if len(cells) < 4 or not re.match(r'\d{4}/\d{1,2}/\d{1,2}', cells[0]):
                continue
            y, m, d = map(int, cells[0].split('/'))
            try:
                seen[cells[0]] = (date(y, m, d), float(cells[1]), float(cells[2]), float(cells[3]))
                n += 1
            except Exception:
                pass
        if n == 0:
            break
        time.sleep(0.15)
    out = sorted(seen.values(), key=lambda x: x[0])
    return out


def save_cbc_changes(changes: List[Tuple[date, float, float, float]]) -> None:
    os.makedirs(DATA, exist_ok=True)
    with open(CBC_CHANGES, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['date', 'discount', 'secured', 'short'])
        for c in changes:
            w.writerow([c[0].isoformat(), c[1], c[2], c[3]])
    # expand daily
    if not changes:
        return
    out = []
    i = 0
    cur = None
    d = changes[0][0]
    end = date.today()
    while d <= end:
        while i < len(changes) and changes[i][0] <= d:
            cur = changes[i]
            i += 1
        if cur:
            out.append({'date': d.isoformat(), 'discount': cur[1], 'secured': cur[2], 'short': cur[3]})
        d += timedelta(days=1)
    with open(CBC_DAILY, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['date', 'discount', 'secured', 'short'])
        w.writeheader()
        w.writerows(out)


def load_cbc_daily() -> Dict[str, List[Dict[str, Any]]]:
    """回 {discount:[], secured:[], short:[]}。若無種子則試 scrape。"""
    if not os.path.isfile(CBC_DAILY):
        try:
            ch = scrape_cbc_rate_changes()
            if ch:
                save_cbc_changes(ch)
        except Exception as e:
            print('[macro_track] CBC scrape failed:', e)
    series = {'discount': [], 'secured': [], 'short': []}
    if not os.path.isfile(CBC_DAILY):
        return series
    with open(CBC_DAILY, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            d = row['date']
            for k in series:
                try:
                    series[k].append({'date': d, 'value': float(row[k])})
                except Exception:
                    pass
    return series


# ── TWSE / TPEx margin lots ───────────────────────────────────
def _parse_num(x: Any) -> Optional[float]:
    if x is None:
        return None
    s = str(x).replace(',', '').replace('%', '').strip()
    if not s or s in ('--', 'null', 'None'):
        return None
    try:
        return float(s)
    except Exception:
        return None


def fetch_twse_listed_margin_lots(d: date) -> Optional[float]:
    """上市融資餘額（交易單位／張）。"""
    ds = d.strftime('%Y%m%d')
    url = f'https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={ds}&selectType=MS&response=json'
    try:
        j = _http_json(url, timeout=20)
    except Exception as e:
        print('[macro_track] TWSE', ds, e)
        return None
    if str(j.get('stat', '')).upper() not in ('OK', ''):
        return None
    for t in j.get('tables') or []:
        for row in t.get('data') or []:
            if not row:
                continue
            if '融資(交易單位)' in str(row[0]) or str(row[0]).startswith('融資'):
                # 今日餘額通常在最後一欄或 fields 對應
                fields = t.get('fields') or []
                idx = None
                for i, f in enumerate(fields):
                    if '今日餘額' in str(f):
                        idx = i
                        break
                if idx is None:
                    idx = len(row) - 1
                return _parse_num(row[idx] if idx < len(row) else row[-1])
    return None


def fetch_tpex_otc_margin_lots(d: date) -> Optional[float]:
    """上櫃融資餘額（張）— 加總各股資餘額。"""
    # API 接受 YYYY/MM/DD 或 YYYYMMDD
    for ds in (d.strftime('%Y/%m/%d'), d.strftime('%Y%m%d')):
        url = f'https://www.tpex.org.tw/www/zh-tw/margin/balance?date={ds}&id=&response=json'
        try:
            j = _http_json(url, timeout=25)
        except Exception as e:
            print('[macro_track] TPEx', ds, e)
            continue
        tables = j.get('tables') or []
        if not tables:
            continue
        t = tables[0]
        fields = t.get('fields') or []
        idx = None
        for i, f in enumerate(fields):
            if str(f).startswith('資餘額') or str(f) == '資餘額':
                idx = i
                break
        if idx is None:
            idx = 6
        total = 0.0
        n = 0
        for row in t.get('data') or []:
            v = _parse_num(row[idx] if idx < len(row) else None)
            if v is not None:
                total += v
                n += 1
        if n > 0:
            return total
    return None


def upsert_margin_mix(d: date, listed: float, otc: float) -> None:
    ratio = (otc / listed * 100.0) if listed and listed > 0 else None
    yoy = None
    prev = d.replace(year=d.year - 1) if d.month != 2 or d.day != 29 else d.replace(year=d.year - 1, day=28)
    # look up ~1y ago within ±5 days
    conn = _db()
    try:
        rows = conn.execute(
            'SELECT d, ratio FROM margin_mix WHERE d BETWEEN ? AND ? ORDER BY ABS(julianday(d)-julianday(?)) LIMIT 1',
            ((prev - timedelta(days=5)).isoformat(), (prev + timedelta(days=5)).isoformat(), prev.isoformat()),
        ).fetchall()
        if rows and rows[0][1] is not None and ratio is not None and rows[0][1] != 0:
            yoy = (ratio / float(rows[0][1]) - 1.0) * 100.0
        conn.execute(
            'INSERT OR REPLACE INTO margin_mix(d, listed, otc, ratio, yoy) VALUES (?,?,?,?,?)',
            (d.isoformat(), listed, otc, ratio, yoy),
        )
        conn.commit()
    finally:
        conn.close()


def refresh_margin_mix_today() -> Optional[Dict[str, Any]]:
    d = date.today()
    # try today then walk back up to 10 calendar days (weekends/holidays)
    for i in range(0, 12):
        dd = d - timedelta(days=i)
        if dd.weekday() >= 5:
            continue
        listed = fetch_twse_listed_margin_lots(dd)
        time.sleep(0.2)
        otc = fetch_tpex_otc_margin_lots(dd)
        if listed and otc:
            upsert_margin_mix(dd, listed, otc)
            return {'date': dd.isoformat(), 'listed': listed, 'otc': otc}
        time.sleep(0.15)
    return None


def load_margin_mix_yoy() -> List[Dict[str, Any]]:
    """優先 DB，其次 CSV seed。啟動時若 DB 空則匯入 CSV。"""
    _maybe_import_margin_mix_csv()
    _recompute_all_yoy()
    pts: List[Dict[str, Any]] = []
    conn = _db()
    try:
        rows = conn.execute(
            'SELECT d, yoy FROM margin_mix WHERE yoy IS NOT NULL ORDER BY d'
        ).fetchall()
        pts = [{'date': r[0], 'value': float(r[1])} for r in rows]
    finally:
        conn.close()
    if pts:
        return pts
    if os.path.isfile(MARGIN_MIX_CSV):
        with open(MARGIN_MIX_CSV, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                try:
                    if row.get('yoy') not in (None, '', 'None'):
                        pts.append({'date': row['date'], 'value': float(row['yoy'])})
                except Exception:
                    pass
    return pts


def _maybe_import_margin_mix_csv() -> None:
    if not os.path.isfile(MARGIN_MIX_CSV):
        return
    conn = _db()
    try:
        n = conn.execute('SELECT COUNT(*) FROM margin_mix').fetchone()[0]
        if n > 0:
            return
        with open(MARGIN_MIX_CSV, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                try:
                    d = row['date']
                    listed = float(row['listed'])
                    otc = float(row['otc'])
                    ratio = float(row['ratio']) if row.get('ratio') not in (None, '', 'None') else (
                        (otc / listed * 100.0) if listed else None
                    )
                    yoy = float(row['yoy']) if row.get('yoy') not in (None, '', 'None') else None
                    conn.execute(
                        'INSERT OR REPLACE INTO margin_mix(d, listed, otc, ratio, yoy) VALUES (?,?,?,?,?)',
                        (d, listed, otc, ratio, yoy),
                    )
                except Exception:
                    pass
        conn.commit()
    finally:
        conn.close()


def _recompute_all_yoy() -> None:
    """依 ratio 重算全部 YoY（插入順序不會再影響結果）。"""
    conn = _db()
    try:
        rows = conn.execute('SELECT d, ratio FROM margin_mix ORDER BY d').fetchall()
        if len(rows) < 2:
            return
        by_d = {r[0]: r[1] for r in rows if r[1] is not None}
        dates = sorted(by_d.keys())
        for d in dates:
            ratio = by_d[d]
            try:
                y, m, day = map(int, d.split('-'))
                prev = date(y - 1, m, day) if not (m == 2 and day == 29) else date(y - 1, 2, 28)
            except Exception:
                continue
            # nearest within ±10 days
            best = None
            best_abs = 999
            for dd, rr in by_d.items():
                try:
                    dt = date.fromisoformat(dd)
                except Exception:
                    continue
                gap = abs((dt - prev).days)
                if gap <= 10 and gap < best_abs:
                    best_abs = gap
                    best = rr
            yoy = None
            if best is not None and best != 0 and ratio is not None:
                yoy = (float(ratio) / float(best) - 1.0) * 100.0
            conn.execute('UPDATE margin_mix SET yoy=? WHERE d=?', (yoy, d))
        conn.commit()
    finally:
        conn.close()


def export_margin_mix_csv() -> None:
    conn = _db()
    try:
        rows = conn.execute('SELECT d, listed, otc, ratio, yoy FROM margin_mix ORDER BY d').fetchall()
    finally:
        conn.close()
    with open(MARGIN_MIX_CSV, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['date', 'listed', 'otc', 'ratio', 'yoy'])
        for r in rows:
            w.writerow(r)


def backfill_margin_mix(start: date, end: Optional[date] = None, step_days: int = 7) -> int:
    """抽樣回補（預設每週一筆）以建立 YoY。"""
    end = end or date.today()
    d = start
    ok = 0
    while d <= end:
        if d.weekday() < 5:
            listed = fetch_twse_listed_margin_lots(d)
            time.sleep(0.25)
            otc = fetch_tpex_otc_margin_lots(d)
            if listed and otc:
                upsert_margin_mix(d, listed, otc)
                ok += 1
                if ok % 20 == 0:
                    print(f'[macro_track] margin_mix backfill ok={ok} last={d}')
            time.sleep(0.2)
        d += timedelta(days=step_days)
    export_margin_mix_csv()
    return ok


# ── Seed CSV helpers ──────────────────────────────────────────
def _seed_path(name: str) -> str:
    return os.path.join(SEED_DIR, name)


def _load_seed_csv(name: Optional[str]) -> List[Dict[str, Any]]:
    if not name:
        return []
    path = _seed_path(name)
    if not os.path.isfile(path):
        return []
    pts: List[Dict[str, Any]] = []
    with open(path, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            try:
                pts.append({'date': row['date'][:10], 'value': float(row['value'])})
            except Exception:
                pass
    return pts


def _save_seed_csv(name: str, pts: List[Dict[str, Any]]) -> None:
    if not name or not pts:
        return
    os.makedirs(SEED_DIR, exist_ok=True)
    path = _seed_path(name)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['date', 'value'])
        for p in pts:
            w.writerow([p['date'], p['value']])


# ── FRED / Yahoo / NY Fed / H.15 / BLS adapters ───────────────
# FRED 在部分網路（含台灣家用／雲端 egress）常連不上：一次失敗即熔斷整進程，
# 改走 NY Fed / H.15 / BLS / Yahoo 備援，避免 8s×N 序列 Timeout 刷屏拖慢 mkt-bar。
_FRED_LOCK = threading.Lock()
_FRED_CIRCUIT_OPEN = False
_FRED_CIRCUIT_REASON = ''


def fred_circuit_open() -> bool:
    return _FRED_CIRCUIT_OPEN or (
        os.environ.get('MACRO_SKIP_FRED', '').strip().lower() in ('1', 'true', 'yes')
    )


def _fred_timeout_sec() -> float:
    raw = os.environ.get('MACRO_FRED_TIMEOUT', '3').strip()
    try:
        return max(1.0, min(15.0, float(raw)))
    except Exception:
        return 3.0


def _fred_points(series_id: str, years: int = 25) -> List[Dict[str, Any]]:
    """FRED CSV；失敗回 []。熔斷後整進程不再打 FRED（備援／種子接手）。"""
    global _FRED_CIRCUIT_OPEN, _FRED_CIRCUIT_REASON
    if fred_circuit_open():
        return []
    cosd = (date.today() - timedelta(days=years * 366)).strftime('%Y-%m-%d')
    url = f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={cosd}'
    # 序列化：並發請求只允許一次實際連線；其餘在熔斷後立刻跳過
    with _FRED_LOCK:
        if fred_circuit_open():
            return []
        try:
            req = urllib.request.Request(url, headers=UA_BROWSER)
            with urllib.request.urlopen(req, timeout=_fred_timeout_sec()) as resp:
                text = resp.read().decode('utf-8', 'replace')
        except Exception as e:
            _FRED_CIRCUIT_OPEN = True
            _FRED_CIRCUIT_REASON = f'{type(e).__name__}: {e}'
            print(
                f'[macro_track] FRED circuit OPEN after {series_id} '
                f'({_FRED_CIRCUIT_REASON}) — skip FRED for this process; use seed/fallback'
            )
            return []
    if not text or ('DATE' not in text[:80].upper() and 'observation' not in text[:80].lower()):
        # 非 CSV（挑戰頁／空）— 也視為 FRED 不可用，避免每序列重試
        with _FRED_LOCK:
            if not _FRED_CIRCUIT_OPEN:
                _FRED_CIRCUIT_OPEN = True
                snippet = (text[:120].replace('\n', ' ') if text else '(empty)')
                _FRED_CIRCUIT_REASON = f'non-csv: {snippet}'
                print(
                    f'[macro_track] FRED circuit OPEN after {series_id} '
                    f'({_FRED_CIRCUIT_REASON}) — skip FRED for this process; use seed/fallback'
                )
        return []
    pts = []
    for ln in text.splitlines()[1:]:
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


def _yahoo_closes(symbol: str, years: int = 25, adj: bool = False) -> List[Dict[str, Any]]:
    """Yahoo chart API 日線；adj=True 用還原收盤（總報酬代理）。"""
    end = int(time.time())
    start = end - max(1, years) * 366 * 24 * 3600
    if years >= 25:
        start = int(datetime(1990, 1, 1, tzinfo=timezone.utc).timestamp())
    url = (
        f'https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(symbol)}'
        f'?period1={start}&period2={end}&interval=1d&events=div%7Csplit'
    )
    try:
        j = _http_json(url, timeout=35)
    except Exception as e:
        print('[macro_track] Yahoo', symbol, e)
        return []
    res = (j.get('chart') or {}).get('result') or []
    if not res:
        return []
    r0 = res[0]
    ts = r0.get('timestamp') or []
    q = ((r0.get('indicators') or {}).get('quote') or [{}])[0]
    closes = q.get('close') or []
    if adj:
        adj_arr = ((r0.get('indicators') or {}).get('adjclose') or [{}])[0].get('adjclose') or []
        if adj_arr:
            closes = adj_arr
    pts = []
    for t, c in zip(ts, closes):
        if c is None:
            continue
        try:
            d = datetime.fromtimestamp(int(t), tz=timezone.utc).strftime('%Y-%m-%d')
            pts.append({'date': d, 'value': float(c)})
        except Exception:
            pass
    return pts


def _nyfed_effr(years: int = 25) -> List[Dict[str, Any]]:
    """NY Fed 有效聯邦基金利率（EFFR）日資料，約自 2000 起。"""
    end = date.today()
    start = end - timedelta(days=years * 366)
    if start.year < 2000:
        start = date(2000, 1, 1)
    url = (
        'https://markets.newyorkfed.org/api/rates/unsecured/all/search.json'
        f'?startDate={start.isoformat()}&endDate={end.isoformat()}'
    )
    try:
        j = _http_json(url, timeout=45)
    except Exception as e:
        print('[macro_track] NYFed EFFR', e)
        return []
    pts = []
    for row in j.get('refRates') or []:
        if row.get('type') != 'EFFR':
            continue
        v = row.get('percentRate')
        d = row.get('effectiveDate')
        if v is None or not d:
            continue
        try:
            pts.append({'date': str(d)[:10], 'value': float(v)})
        except Exception:
            pass
    pts.sort(key=lambda x: x['date'])
    return pts


def _h15_us10y(years: int = 25) -> List[Dict[str, Any]]:
    """Fed H.15 美國 10 年期公債殖利率（日）。"""
    # 含 1M–30Y 公債；RIFLGFCY10_N.B = 10Y
    url = (
        'https://www.federalreserve.gov/datadownload/Output.aspx'
        '?rel=H15&series=5b9c777616870aa8125d0ce9dff88011'
        '&lastobs=&from=01/01/2000&to=12/31/2030'
        '&filetype=csv&label=include&layout=seriescolumn'
    )
    try:
        req = urllib.request.Request(url, headers=UA_BROWSER)
        with urllib.request.urlopen(req, timeout=40) as resp:
            text = resp.read().decode('utf-8', 'replace')
    except Exception as e:
        print('[macro_track] H.15', e)
        return []
    lines = text.splitlines()
    header_idx = None
    col = None
    for i, ln in enumerate(lines):
        if 'Time Period' in ln and 'RIFLGFCY10' in ln:
            header_idx = i
            parts = next(csv.reader([ln]))
            for j, h in enumerate(parts):
                if 'RIFLGFCY10' in h:
                    col = j
                    break
            break
    if header_idx is None or col is None:
        # fallback Yahoo ^TNX
        return _yahoo_closes('^TNX', years=years)
    pts = []
    for ln in lines[header_idx + 1:]:
        parts = next(csv.reader([ln]))
        if len(parts) <= col:
            continue
        d, v = parts[0].strip(), parts[col].strip()
        if not d or not v or v in ('.', 'ND', 'n.a.'):
            continue
        try:
            pts.append({'date': d[:10], 'value': float(v)})
        except Exception:
            pass
    return pts


def _bls_cpi_yoy(years: int = 25) -> List[Dict[str, Any]]:
    """BLS CPI-U NSA（CUUR0000SA0）→ 年增率 %。公開 API 每次最多約 10 年，分段抓。"""
    end_y = date.today().year
    start_y = max(1980, end_y - years - 1)
    by_ym: Dict[Tuple[int, int], float] = {}
    y = start_y
    while y <= end_y:
        y2 = min(y + 9, end_y)
        payload = json.dumps({
            'seriesid': ['CUUR0000SA0'],
            'startyear': str(y),
            'endyear': str(y2),
        }).encode()
        try:
            req = urllib.request.Request(
                'https://api.bls.gov/publicAPI/v2/timeseries/data/',
                data=payload,
                headers={**UA_BROWSER, 'Content-Type': 'application/json'},
            )
            with urllib.request.urlopen(req, timeout=40) as resp:
                d = json.loads(resp.read().decode('utf-8', 'replace'))
            series = ((d.get('Results') or {}).get('series') or [{}])[0]
            for row in series.get('data') or []:
                per = str(row.get('period') or '')
                if not per.startswith('M'):
                    continue
                try:
                    yy = int(row['year'])
                    mm = int(per[1:])
                    by_ym[(yy, mm)] = float(row['value'])
                except Exception:
                    pass
        except Exception as e:
            print('[macro_track] BLS CPI', y, e)
        y = y2 + 1
        time.sleep(0.2)
    keys = sorted(by_ym.keys())
    pts = []
    for yy, mm in keys:
        prev = by_ym.get((yy - 1, mm))
        cur = by_ym[(yy, mm)]
        if prev is None or prev == 0:
            continue
        yoy = (cur / prev - 1.0) * 100.0
        pts.append({'date': f'{yy:04d}-{mm:02d}-01', 'value': round(yoy, 4)})
    return pts


def _filter_years(pts: List[Dict[str, Any]], years: int) -> List[Dict[str, Any]]:
    if not pts or years <= 0:
        return pts
    cut = (date.today() - timedelta(days=years * 366)).isoformat()
    return [p for p in pts if p.get('date', '') >= cut]


def _resolve_series_points(
    s: Dict[str, Any], years: int, force_live: bool = False
) -> Tuple[List[Dict[str, Any]], str]:
    """
    解析單序列：預設優先本地 seed（圖表秒開）；force_live=True（更新鈕）才打網路。
    線上順序：FRED（可熔斷）→ fallback → 合併回寫 seed。
    """
    seed_name = s.get('seed')
    seed_pts = _load_seed_csv(seed_name)

    # 一般讀圖：有種子就直接用，避免 FRED Timeout 拖慢每次切換
    if seed_pts and not force_live:
        return seed_pts, f'seed:{seed_name}'

    live: List[Dict[str, Any]] = []
    note = ''

    src = s.get('source')
    if src == 'fred' and s.get('fred'):
        live = _fred_points(s['fred'], years)
        if live:
            note = f"FRED {s['fred']}"
    elif src == 'yahoo' and s.get('symbol'):
        live = _yahoo_closes(s['symbol'], years=years, adj=True)
        if live:
            note = f"Yahoo {s['symbol']}"

    if not live:
        fb = s.get('fallback')
        if fb == 'nyfed_effr':
            live = _nyfed_effr(years)
            if live:
                note = 'NY Fed EFFR'
        elif fb == 'h15_10y':
            live = _h15_us10y(years)
            if live:
                note = 'Fed H.15 10Y'
            if not live:
                live = _yahoo_closes('^TNX', years=years)
                if live:
                    note = 'Yahoo ^TNX'
        elif fb == 'yahoo_adj' and s.get('symbol'):
            live = _yahoo_closes(s['symbol'], years=years, adj=True)
            if live:
                note = f"Yahoo {s['symbol']} adj (BAML proxy)"
        elif fb == 'bls_cpi_yoy':
            live = _bls_cpi_yoy(years)
            if live:
                note = 'BLS CPI-U NSA YoY'

    if live:
        # merge: prefer live, keep older seed points not in live
        by_d = {p['date']: p for p in seed_pts}
        for p in live:
            by_d[p['date']] = p
        merged = [by_d[k] for k in sorted(by_d.keys())]
        try:
            _save_seed_csv(seed_name, merged)
        except Exception as e:
            print('[macro_track] save seed', seed_name, e)
        return merged, note or 'live'

    if seed_pts:
        return seed_pts, f'seed:{seed_name}'
    return [], 'empty'


# ── Chart assembly ────────────────────────────────────────────
def get_chart(chart_id: str, years: Optional[int] = None,
              force_live: bool = False) -> Dict[str, Any]:
    cid = str(chart_id or '').upper()
    meta = CHARTS.get(cid)
    if not meta:
        raise KeyError('unknown chart ' + cid)
    yrs = years if years is not None else int(meta.get('years') or 20)
    yrs = max(1, min(40, int(yrs)))

    out_series: List[Dict[str, Any]] = []

    if cid == '__TW_RATES__':
        cbc = load_cbc_daily()
        for s in meta['series']:
            pts = _filter_years(cbc.get(s['key'], []), yrs)
            out_series.append({
                'key': s['key'], 'name': s['name'], 'scale': s['scale'],
                'color': s['color'], 'style': s.get('style', 'line'), 'unit': s.get('unit', ''),
                'points': pts, 'source': 'CBC',
            })

    elif cid == '__TW_MARGIN_MIX__':
        try:
            refresh_margin_mix_today()
        except Exception as e:
            print('[macro_track] refresh margin mix:', e)
        yoy = _filter_years(load_margin_mix_yoy(), yrs)
        s0 = meta['series'][0]
        out_series.append({
            'key': s0['key'], 'name': s0['name'], 'scale': s0['scale'],
            'color': s0['color'], 'style': s0.get('style', 'line'), 'unit': s0.get('unit', ''),
            'points': yoy, 'source': 'TWSE+TPEx',
        })
        twii = _filter_years(_yahoo_closes('^TWII', yrs), yrs)
        s1 = meta['series'][1]
        out_series.append({
            'key': s1['key'], 'name': s1['name'], 'scale': s1['scale'],
            'color': s1['color'], 'style': s1.get('style', 'line'), 'unit': s1.get('unit', ''),
            'points': twii, 'source': 'Yahoo ^TWII',
        })

    elif cid in ('__US_RATES_CREDIT__', '__US_CPI_FIN__'):
        for s in meta['series']:
            pts, note = _resolve_series_points(s, yrs, force_live=force_live)
            out_series.append({
                'key': s['key'], 'name': s['name'], 'scale': s['scale'],
                'color': s['color'], 'style': s.get('style', 'line'), 'unit': s.get('unit', ''),
                'points': _filter_years(pts, yrs),
                'source': note,
            })

    elif cid == '__TW_MARGIN_CYCLE__':
        import margin_cycle as mc
        full = mc.get_chart(years=yrs, force_refresh=True)
        return full

    else:
        raise KeyError(cid)

    out = {
        'id': meta['id'],
        'name': meta['name'],
        'shortName': meta['shortName'],
        'market': meta['market'],
        'description': meta.get('description', ''),
        'years': yrs,
        'series': out_series,
        'ok': any(len(s.get('points') or []) > 0 for s in out_series),
        'defaultViewMode': 'rebase' if cid in ('__US_RATES_CREDIT__', '__US_CPI_FIN__') else 'raw',
    }
    # 美總經圖：附加市場風險評分（利率／信用／通膨／金融股）
    if cid in ('__US_RATES_CREDIT__', '__US_CPI_FIN__'):
        try:
            import market_risk as mr
            mr.attach_risk_to_chart(cid, out)
        except Exception as e:
            print('[macro_track] market_risk attach failed:', e)
    return out


def points_to_yf_like(points: List[Dict[str, Any]], symbol: str, name: str) -> Dict[str, Any]:
    """把主序列轉成 Yahoo chart 形狀，供舊 /yf/__XXX__ 路徑相容。"""
    ts, closes = [], []
    for p in points:
        try:
            d = datetime.strptime(p['date'][:10], '%Y-%m-%d')
            ts.append(int(d.replace(tzinfo=None).timestamp()))
            closes.append(float(p['value']))
        except Exception:
            continue
    meta = {
        'symbol': symbol,
        'shortName': name,
        'currency': 'TWD' if symbol.startswith('__TW') else 'USD',
        'regularMarketPrice': closes[-1] if closes else None,
        'instrumentType': 'MUTUALFUND',
    }
    return {
        'chart': {
            'result': [{
                'meta': meta,
                'timestamp': ts,
                'indicators': {'quote': [{'close': closes, 'open': closes, 'high': closes, 'low': closes,
                                          'volume': [0] * len(closes)}]},
            }],
            'error': None,
        }
    }


def primary_points_for_yf(chart_id: str) -> Dict[str, Any]:
    """給 /yf/__CHART__ 用：取左軸第一條有資料的序列。"""
    data = get_chart(chart_id)
    primary = None
    for s in data.get('series') or []:
        if s.get('scale') == 'left' and s.get('points'):
            primary = s
            break
    if not primary:
        for s in data.get('series') or []:
            if s.get('points'):
                primary = s
                break
    pts = (primary or {}).get('points') or []
    return points_to_yf_like(pts, data['id'], data['name'])


# ── 一鍵更新（UI 按鈕用，免 CLI）────────────────────────────
_REFRESH_LOCK = {'running': False, 'last': None, 'note': ''}

# 密度預設：step=抽樣間隔天數；years=往回幾年；dense=是否啟動歷史回補
DENSITY_PRESETS = {
    'today':  {'label': '僅今日', 'step': 0,  'years': 0,  'dense': False},
    'month':  {'label': '月抽樣', 'step': 30, 'years': 8,  'dense': True},
    'biweek': {'label': '雙週',   'step': 14, 'years': 10, 'dense': True},
    'week':   {'label': '週抽樣', 'step': 7,  'years': 12, 'dense': True},
    'day':    {'label': '日(最密)', 'step': 1, 'years': 5,  'dense': True},
}


def resolve_density(density: Optional[str] = None, dense: Optional[bool] = None,
                    step: Optional[int] = None, years: Optional[int] = None) -> Dict[str, Any]:
    """合併 UI 密度選項與顯式 step/years。"""
    key = str(density or '').strip().lower() or None
    preset = DENSITY_PRESETS.get(key) if key else None
    if preset:
        out = dict(preset)
        out['key'] = key
    else:
        # 相容舊 dense 旗標
        if dense is False:
            out = dict(DENSITY_PRESETS['today'])
            out['key'] = 'today'
        else:
            out = dict(DENSITY_PRESETS['month'])
            out['key'] = 'month'
    if step is not None:
        try:
            out['step'] = max(0, int(step))
        except Exception:
            pass
    if years is not None:
        try:
            out['years'] = max(0, min(25, int(years)))
        except Exception:
            pass
    out['dense'] = bool(out.get('step', 0) > 0 and out.get('years', 0) > 0 and out.get('dense', True))
    if out.get('step', 0) <= 0:
        out['dense'] = False
    return out


def status_summary() -> Dict[str, Any]:
    """給 /datasources 與 UI 顯示用。"""
    out: Dict[str, Any] = {
        'charts': {},
        'refresh': dict(_REFRESH_LOCK),
        'densityPresets': [
            {'key': k, 'label': v['label'], 'step': v['step'], 'years': v['years']}
            for k, v in DENSITY_PRESETS.items()
        ],
    }
    # CBC
    cbc_n = 0
    if os.path.isfile(CBC_DAILY):
        try:
            with open(CBC_DAILY, encoding='utf-8') as f:
                cbc_n = max(0, sum(1 for _ in f) - 1)
        except Exception:
            pass
    out['charts']['__TW_RATES__'] = {
        'updated': int(os.path.getmtime(CBC_DAILY)) if os.path.isfile(CBC_DAILY) else 0,
        'count': cbc_n,
        'name': CHARTS['__TW_RATES__']['name'],
    }
    # margin mix
    mix_n = 0
    try:
        conn = _db()
        mix_n = conn.execute('SELECT COUNT(*) FROM margin_mix WHERE yoy IS NOT NULL').fetchone()[0]
        conn.close()
    except Exception:
        pass
    mix_path = MARGIN_MIX_CSV if os.path.isfile(MARGIN_MIX_CSV) else DB_PATH
    out['charts']['__TW_MARGIN_MIX__'] = {
        'updated': int(os.path.getmtime(mix_path)) if os.path.isfile(mix_path) else 0,
        'count': mix_n,
        'name': CHARTS['__TW_MARGIN_MIX__']['name'],
    }
    # US seeds
    for cid in ('__US_RATES_CREDIT__', '__US_CPI_FIN__'):
        seeds = [s.get('seed') for s in CHARTS[cid]['series'] if s.get('seed')]
        paths = [_seed_path(n) for n in seeds if n and os.path.isfile(_seed_path(n))]
        n = 0
        ts = 0
        for p in paths:
            ts = max(ts, int(os.path.getmtime(p)))
            try:
                with open(p, encoding='utf-8') as f:
                    n = max(n, max(0, sum(1 for _ in f) - 1))
            except Exception:
                pass
        out['charts'][cid] = {
            'updated': ts,
            'count': n,
            'name': CHARTS[cid]['name'],
        }
    return out


def refresh_chart(chart_id: str, dense: bool = False, density: Optional[str] = None,
                  step: Optional[int] = None, years: Optional[int] = None) -> Dict[str, Any]:
    """
    一鍵更新單一追蹤圖。
    density / step / years 控制融資比歷史回補密度（免 CLI）。
    """
    dens = resolve_density(density=density, dense=dense, step=step, years=years)
    cid = str(chart_id or '').upper().strip()
    if cid in ('ALL', '*', 'MACRO_TRACKS'):
        return refresh_all(dense=dens['dense'], density=dens.get('key'),
                           step=dens.get('step'), years=dens.get('years'))
    if cid not in CHARTS:
        return {'ok': False, 'error': 'unknown chart ' + cid}

    result: Dict[str, Any] = {'ok': True, 'id': cid, 'actions': [], 'density': dens}

    if cid == '__TW_RATES__':
        try:
            ch = scrape_cbc_rate_changes()
            if ch:
                save_cbc_changes(ch)
                result['actions'].append({'action': 'scrape-cbc', 'changes': len(ch)})
                result['count'] = len(ch)
            else:
                # 至少確認種子可讀
                cbc = load_cbc_daily()
                n = len(cbc.get('discount') or [])
                result['actions'].append({'action': 'load-seed', 'points': n})
                result['count'] = n
                if n == 0:
                    result['ok'] = False
                    result['error'] = 'CBC 抓取失敗且無種子'
        except Exception as e:
            result['ok'] = False
            result['error'] = str(e)

    elif cid == '__TW_MARGIN_MIX__':
        try:
            today = refresh_margin_mix_today()
            _recompute_all_yoy()
            export_margin_mix_csv()
            yoy_n = len(load_margin_mix_yoy())
            result['actions'].append({'action': 'refresh-today', 'row': today, 'yoyPoints': yoy_n})
            result['count'] = yoy_n
            if dens.get('dense') and dens.get('step', 0) > 0 and dens.get('years', 0) > 0:
                step_days = int(dens['step'])
                yrs = int(dens['years'])
                start = date.today() - timedelta(days=yrs * 365)
                result['started'] = True
                result['note'] = f'已背景回補自 {start.isoformat()}（每 {step_days} 日 · {yrs} 年）'
                result['actions'].append({
                    'action': 'backfill-mix',
                    'start': start.isoformat(),
                    'step': step_days,
                    'years': yrs,
                    'density': dens.get('key'),
                })

                def _run():
                    _REFRESH_LOCK['running'] = True
                    _REFRESH_LOCK['note'] = f"backfill-mix step={step_days}"
                    try:
                        n = backfill_margin_mix(start, step_days=step_days)
                        _recompute_all_yoy()
                        export_margin_mix_csv()
                        _REFRESH_LOCK['last'] = {
                            'ok': True, 'n': n, 'at': time.time(),
                            'step': step_days, 'years': yrs,
                        }
                    except Exception as e:
                        _REFRESH_LOCK['last'] = {'ok': False, 'error': str(e), 'at': time.time()}
                    finally:
                        _REFRESH_LOCK['running'] = False
                        _REFRESH_LOCK['note'] = ''

                import threading
                threading.Thread(target=_run, daemon=True).start()
        except Exception as e:
            result['ok'] = False
            result['error'] = str(e)

    elif cid == '__TW_MARGIN_CYCLE__':
        try:
            import margin_cycle as mc
            today = mc.refresh_today()
            result['actions'].append({'action': 'refresh-ms-today', 'row': today})
            yrs = int(dens.get('years') or years or 8)
            step_days = int(dens.get('step') or step or 14)
            mc.start_background_backfill(years=yrs, step_days=step_days)
            result['started'] = True
            result['note'] = f'已更新今日信用統計，並背景回補約 {yrs} 年（每 {step_days} 日）'
            rows = mc.load_ms_rows()
            result['count'] = len(rows)
            result['actions'].append({
                'action': 'backfill-ms', 'years': yrs, 'step': step_days, 'points': len(rows),
            })
        except Exception as e:
            result['ok'] = False
            result['error'] = str(e)

    elif cid in ('__US_RATES_CREDIT__', '__US_CPI_FIN__'):
        try:
            # 強制走線上（FRED→備援）並回寫 seed；FRED 熔斷後仍走備援
            data = get_chart(
                cid,
                years=int(CHARTS[cid].get('years') or 25),
                force_live=True,
            )
            counts = {s['key']: len(s.get('points') or []) for s in data.get('series') or []}
            result['actions'].append({'action': 'seed-us', 'counts': counts, 'sources': {
                s['key']: s.get('source') for s in data.get('series') or []
            }, 'fredCircuit': fred_circuit_open()})
            result['count'] = sum(counts.values())
            result['ok'] = bool(data.get('ok'))
            if not result['ok']:
                result['error'] = '美國序列抓取失敗'
        except Exception as e:
            result['ok'] = False
            result['error'] = str(e)

    return result


def refresh_all(dense: bool = False, density: Optional[str] = None,
                step: Optional[int] = None, years: Optional[int] = None) -> Dict[str, Any]:
    """一次更新四張追蹤圖。"""
    dens = resolve_density(density=density, dense=dense, step=step, years=years)
    out = {'ok': True, 'results': {}, 'started': False, 'density': dens}
    for cid in CHARTS:
        # 融資比套用密度；其他圖不受 step 影響
        use_dense = dens['dense'] if cid == '__TW_MARGIN_MIX__' else False
        r = refresh_chart(
            cid,
            dense=use_dense or (cid == '__TW_MARGIN_MIX__' and dens['dense']),
            density=dens.get('key') if cid == '__TW_MARGIN_MIX__' else 'today',
            step=dens.get('step') if cid == '__TW_MARGIN_MIX__' else None,
            years=dens.get('years') if cid == '__TW_MARGIN_MIX__' else None,
        )
        out['results'][cid] = r
        if not r.get('ok'):
            out['ok'] = False
        if r.get('started'):
            out['started'] = True
            out['note'] = r.get('note') or out.get('note')
    return out


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('cmd', choices=['scrape-cbc', 'backfill-mix', 'demo', 'export-mix', 'seed-us', 'refresh'])
    ap.add_argument('--start', default='2015-01-01')
    ap.add_argument('--step', type=int, default=14)
    ap.add_argument('--years', type=int, default=25)
    ap.add_argument('--id', default='ALL')
    ap.add_argument('--dense', action='store_true')
    ap.add_argument('--density', default='month', help='today|month|biweek|week|day')
    args = ap.parse_args()
    if args.cmd == 'scrape-cbc':
        ch = scrape_cbc_rate_changes()
        save_cbc_changes(ch)
        print('CBC changes', len(ch))
    elif args.cmd == 'backfill-mix':
        y, m, d = map(int, args.start.split('-'))
        n = backfill_margin_mix(date(y, m, d), step_days=args.step)
        print('backfilled', n)
    elif args.cmd == 'export-mix':
        export_margin_mix_csv()
        print('exported', MARGIN_MIX_CSV)
    elif args.cmd == 'seed-us':
        for cid in ('__US_RATES_CREDIT__', '__US_CPI_FIN__'):
            c = get_chart(cid, years=args.years)
            print(cid, 'ok', c['ok'], [(s['key'], len(s['points']), s.get('source')) for s in c['series']])
        print('seeds written under', SEED_DIR)
    elif args.cmd == 'refresh':
        print(json.dumps(
            refresh_chart(args.id, dense=args.dense, density=args.density, step=args.step, years=args.years),
            ensure_ascii=False, indent=2,
        ))
    elif args.cmd == 'demo':
        for cid in CHARTS:
            try:
                c = get_chart(cid, years=10)
                print(cid, 'ok', c['ok'], [(s['key'], len(s['points']), s.get('source')) for s in c['series']])
            except Exception as e:
                print(cid, 'ERR', e)
