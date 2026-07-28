# -*- coding: utf-8 -*-
"""
tdcc_holders.py — 台股籌碼集中度（集保股權分散表）

資料：TDCC 開放資料「集保戶股權分散表」每週快照
  https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5
歷史回補：wirelessr/tdcc-opendata-archive（官方只留當週）

定義（對齊市場慣用「神秘金字塔」口徑）：
  - 總股東人數 = 持股分級 17（合計）人數
  - 大股東持有率 = 分級 12~15 占集保比例合計（≥400 張）
  - 千張大戶比率 = 分級 15 占集保比例（≥1,000,001 股）

代號圖表：__HOLDERS_2330__ （中間為 4~6 碼股號）
API：
  get_stock(code) / get_chart(code) / refresh_latest() / backfill_archive()
"""
from __future__ import annotations

import csv
import io
import json
import math
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
DB_PATH = os.path.join(DATA, 'tdcc_holders.db')

TDCC_URL = 'https://smart.tdcc.com.tw/opendata/getOD.ashx?id=1-5'
ARCHIVE_RAW = (
    'https://raw.githubusercontent.com/wirelessr/tdcc-opendata-archive/main/snapshots/'
    '{year}/{ymd}.csv'
)

UA = {
    'User-Agent': 'Mozilla/5.0 (compatible; StockTerminal/4.1; TDCC holders)',
    'Accept': 'text/csv,text/plain,*/*',
}

# 持股分級：12–15 = ≥400 張（400,001 股以上）
MAJOR_LEVELS = (12, 13, 14, 15)
MEGA_LEVEL = 15
TOTAL_LEVEL = 17

ALGO = {
    'id': 'TDCC_HOLDERS',
    'title': '籌碼集中度 · 集保股權分散',
    'direction': 'concentrate',  # 越高＝越集中（偏多方籌碼結構）
    'pillars': [
        {
            'key': 'majorLevel',
            'name': '大股東水位',
            'weight': '⅓',
            'plain': '≥400 張股東合計持股比例愈高，籌碼愈集中在大戶。',
            'formula': '水位分 = 50 + 50·tanh((大股東持有率%−55)/20)',
        },
        {
            'key': 'majorMomentum',
            'name': '集中動能',
            'weight': '⅓',
            'plain': '近 4 週大股東持有率上升＝主力在收；下降＝在散。',
            'formula': '動能分 = 50 + 50·tanh(大股東持有率4週變化pp / 1.5)',
        },
        {
            'key': 'holdersMomentum',
            'name': '人數動能',
            'weight': '⅓',
            'plain': '總股東人數下降＝籌碼集中；上升＝散戶化。',
            'formula': '人數分 = 50 − 50·tanh(股東人數4週變化% / 3)',
        },
    ],
    'aggregate': (
        '總分 = 有資料支柱平均。'
        '另偵測背離：大股東↑且人數↑幅度大 → 標「散戶化背離」；'
        '大股東↑且人數↓ → 標「集中確認」。'
    ),
    'viewNote': '資料為集保每週最後營業日；非即時。來源 TDCC 開放資料，非爬神秘金字塔。',
}

_SYM_RE = re.compile(r'^__HOLDERS_([0-9A-Z]{4,6})__$', re.I)

_http_lock = threading.Lock()
_last_http = 0.0
_refresh_lock = threading.Lock()
_backfill_state = {
    'running': False, 'phase': '', 'done': 0, 'total': 0,
    'last_error': '', 'started_at': 0, 'finished_at': 0,
}


def _throttle(gap: float = 0.35):
    global _last_http
    with _http_lock:
        now = time.time()
        w = gap - (now - _last_http)
        if w > 0:
            time.sleep(w)
        _last_http = time.time()


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _tanh_map(x: float, center: float, scale: float) -> float:
    if scale == 0:
        return 50.0
    return _clamp(50.0 + 50.0 * math.tanh((float(x) - center) / scale))


def parse_holders_sym(sym: str) -> Optional[str]:
    s = (sym or '').strip().upper()
    m = _SYM_RE.match(s)
    if m:
        return m.group(1)
    # HOLDERS:2330 / holders/2330
    if s.startswith('HOLDERS:') or s.startswith('HOLDERS/'):
        return re.sub(r'[^0-9A-Z]', '', s.split(':', 1)[-1].split('/', 1)[-1])[:6] or None
    return None


def holders_chart_id(code: str) -> str:
    return f'__HOLDERS_{_norm_code(code)}__'


def _norm_code(code: str) -> str:
    return str(code or '').strip().upper().replace('.TW', '').replace('.TWO', '')


def is_holders_sym(sym: str) -> bool:
    return parse_holders_sym(sym) is not None


def _db() -> sqlite3.Connection:
    os.makedirs(DATA, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS holders_week (
             d TEXT NOT NULL,
             code TEXT NOT NULL,
             holders INTEGER,
             major_pct REAL,
             mega_pct REAL,
             major_holders INTEGER,
             PRIMARY KEY (d, code)
           )'''
    )
    conn.execute('CREATE INDEX IF NOT EXISTS idx_holders_code ON holders_week(code, d)')
    conn.commit()
    return conn


def _http_bytes(url: str, timeout: int = 90) -> bytes:
    _throttle()
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _parse_csv_bytes(raw: bytes) -> List[Dict[str, Any]]:
    """回傳每檔彙總列（非原始分級列）。"""
    text = raw.decode('utf-8-sig', 'replace')
    # 統一換行
    f = io.StringIO(text)
    reader = csv.DictReader(f)
    if not reader.fieldnames:
        return []
    # 欄名正規化
    def col(*names):
        for n in names:
            for h in reader.fieldnames:
                if h and n in h.replace(' ', ''):
                    return h
        return None

    c_date = col('資料日期')
    c_code = col('證券代號')
    c_lv = col('持股分級')
    c_ppl = col('人數')
    c_pct = col('占集保庫存數比例', '佔集保庫存數比例')
    if not all([c_date, c_code, c_lv, c_ppl, c_pct]):
        # fallback positional
        rows_raw = list(csv.reader(io.StringIO(text)))
        return _parse_positional(rows_raw)

    # code -> accum
    acc: Dict[str, Dict[str, Any]] = {}
    snap_date = None
    for row in reader:
        try:
            code = str(row.get(c_code) or '').strip()
            if not code or not code[0].isdigit():
                continue
            lv = int(float(str(row.get(c_lv) or '0').strip() or 0))
            ppl = int(float(str(row.get(c_ppl) or '0').replace(',', '') or 0))
            pct = float(str(row.get(c_pct) or '0').replace(',', '') or 0)
            ds = str(row.get(c_date) or '').strip()
            if len(ds) == 8 and ds.isdigit():
                snap_date = f'{ds[0:4]}-{ds[4:6]}-{ds[6:8]}'
            a = acc.setdefault(code, {
                'holders': None, 'major_pct': 0.0, 'mega_pct': 0.0, 'major_holders': 0,
            })
            if lv == TOTAL_LEVEL:
                a['holders'] = ppl
            if lv in MAJOR_LEVELS:
                a['major_pct'] += pct
                a['major_holders'] += ppl
            if lv == MEGA_LEVEL:
                a['mega_pct'] = pct
        except Exception:
            continue
    if not snap_date:
        return []
    out = []
    for code, a in acc.items():
        if a['holders'] is None:
            continue
        out.append({
            'date': snap_date,
            'code': code,
            'holders': int(a['holders']),
            'major_pct': round(float(a['major_pct']), 4),
            'mega_pct': round(float(a['mega_pct']), 4),
            'major_holders': int(a['major_holders']),
        })
    return out


def _parse_positional(rows_raw: List[List[str]]) -> List[Dict[str, Any]]:
    if not rows_raw:
        return []
    start = 1 if rows_raw and '資料' in ''.join(rows_raw[0]) else 0
    acc: Dict[str, Dict[str, Any]] = {}
    snap_date = None
    for row in rows_raw[start:]:
        if len(row) < 6:
            continue
        try:
            ds, code, lv_s, ppl_s, _shares, pct_s = row[0], row[1].strip(), row[2], row[3], row[4], row[5]
            if not code or not code[0].isdigit():
                continue
            lv = int(float(lv_s))
            ppl = int(float(str(ppl_s).replace(',', '') or 0))
            pct = float(str(pct_s).replace(',', '') or 0)
            ds = str(ds).strip()
            if len(ds) == 8 and ds.isdigit():
                snap_date = f'{ds[0:4]}-{ds[4:6]}-{ds[6:8]}'
            a = acc.setdefault(code, {
                'holders': None, 'major_pct': 0.0, 'mega_pct': 0.0, 'major_holders': 0,
            })
            if lv == TOTAL_LEVEL:
                a['holders'] = ppl
            if lv in MAJOR_LEVELS:
                a['major_pct'] += pct
                a['major_holders'] += ppl
            if lv == MEGA_LEVEL:
                a['mega_pct'] = pct
        except Exception:
            continue
    if not snap_date:
        return []
    return [{
        'date': snap_date,
        'code': code,
        'holders': int(a['holders']),
        'major_pct': round(float(a['major_pct']), 4),
        'mega_pct': round(float(a['mega_pct']), 4),
        'major_holders': int(a['major_holders']),
    } for code, a in acc.items() if a['holders'] is not None]


def upsert_rows(rows: List[Dict[str, Any]]) -> int:
    if not rows:
        return 0
    conn = _db()
    n = 0
    try:
        for r in rows:
            conn.execute(
                '''INSERT OR REPLACE INTO holders_week
                   (d, code, holders, major_pct, mega_pct, major_holders)
                   VALUES (?,?,?,?,?,?)''',
                (r['date'], r['code'], r['holders'], r['major_pct'], r['mega_pct'], r['major_holders']),
            )
            n += 1
        conn.commit()
    finally:
        conn.close()
    return n


def refresh_latest() -> Dict[str, Any]:
    """抓當週 TDCC 開放資料並寫入 DB。"""
    raw = _http_bytes(TDCC_URL, timeout=120)
    rows = _parse_csv_bytes(raw)
    n = upsert_rows(rows)
    d = rows[0]['date'] if rows else None
    return {'ok': True, 'date': d, 'count': n, 'source': 'tdcc-opendata'}


def _archive_url_for(d: date) -> str:
    ymd = d.strftime('%Y-%m-%d')
    return ARCHIVE_RAW.format(year=d.year, ymd=ymd)


def fetch_archive_day(d: date) -> Optional[List[Dict[str, Any]]]:
    url = _archive_url_for(d)
    try:
        raw = _http_bytes(url, timeout=60)
        if not raw or len(raw) < 100:
            return None
        return _parse_csv_bytes(raw)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        print('[tdcc] archive', d, e)
        return None
    except Exception as e:
        print('[tdcc] archive', d, e)
        return None


def backfill_archive(weeks: int = 104, step: int = 1) -> int:
    """
    自 archive 回補近 N 週。archive 檔名為資料日期（多為週五）。
    以每週五為錨，找不到則前後各試 3 日。
    """
    weeks = max(4, min(260, int(weeks)))
    _backfill_state.update({
        'running': True, 'phase': 'archive', 'done': 0, 'total': weeks,
        'last_error': '', 'started_at': time.time(), 'finished_at': 0,
    })
    existing = set()
    conn = _db()
    try:
        existing = {r[0] for r in conn.execute('SELECT DISTINCT d FROM holders_week').fetchall()}
    finally:
        conn.close()

    # 對齊到最近週五
    today = date.today()
    fri = today - timedelta(days=(today.weekday() - 4) % 7)
    total_ins = 0
    try:
        for i in range(weeks):
            anchor = fri - timedelta(weeks=i * step)
            _backfill_state['done'] = i + 1
            # 已有則跳過
            if any((anchor + timedelta(days=k)).isoformat() in existing for k in range(-3, 4)):
                continue
            got = None
            for k in (0, -1, 1, -2, 2, -3, 3):
                d = anchor + timedelta(days=k)
                rows = fetch_archive_day(d)
                if rows:
                    got = rows
                    break
            if not got:
                continue
            n = upsert_rows(got)
            total_ins += n
            existing.add(got[0]['date'])
            print(f'[tdcc] backfill {got[0]["date"]} rows={n}')
    except Exception as e:
        _backfill_state['last_error'] = str(e)
        print('[tdcc] backfill failed', e)
    finally:
        _backfill_state['running'] = False
        _backfill_state['finished_at'] = time.time()
        _backfill_state['phase'] = 'done'
    return total_ins


def start_background_backfill(weeks: int = 104):
    if _backfill_state.get('running'):
        return False
    try:
        import job_queue as jq
        if jq.is_busy('tdcc_holders'):
            return False

        def _run():
            with _refresh_lock:
                try:
                    refresh_latest()
                except Exception as e:
                    print('[tdcc] refresh_latest', e)
                try:
                    n = backfill_archive(weeks=weeks)
                    print('[tdcc] backfill done inserted-ish', n)
                except Exception as e:
                    print('[tdcc] backfill', e)

        r = jq.submit('tdcc_holders', _run, meta={'weeks': weeks})
        return bool(r.get('queued'))
    except Exception:
        # fallback：無 queue 時維持舊行為
        def _run():
            with _refresh_lock:
                try:
                    refresh_latest()
                except Exception as e:
                    print('[tdcc] refresh_latest', e)
                try:
                    n = backfill_archive(weeks=weeks)
                    print('[tdcc] backfill done inserted-ish', n)
                except Exception as e:
                    print('[tdcc] backfill', e)

        import threading
        threading.Thread(target=_run, daemon=True).start()
        return True


def load_stock_series(code: str) -> List[Dict[str, Any]]:
    code = _norm_code(code)
    conn = _db()
    try:
        rows = conn.execute(
            '''SELECT d, holders, major_pct, mega_pct, major_holders
               FROM holders_week WHERE code=? ORDER BY d''',
            (code,),
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            'date': d,
            'holders': holders,
            'major_pct': major_pct,
            'mega_pct': mega_pct,
            'major_holders': major_holders,
        }
        for d, holders, major_pct, mega_pct, major_holders in rows
    ]


def _label(score: Optional[float], divergence: Optional[str]) -> str:
    if divergence == 'retailization':
        return '散戶化背離'
    if divergence == 'confirm':
        base = '集中確認'
    else:
        base = None
    if score is None:
        return '資料不足'
    if score >= 70:
        lab = '高度集中'
    elif score >= 55:
        lab = '集中中'
    elif score >= 45:
        lab = '中性'
    elif score >= 30:
        lab = '偏發散'
    else:
        lab = '發散'
    if base and score >= 55:
        return f'{lab}·{base}'
    if divergence == 'retailization':
        return '散戶化背離'
    return lab


def score_concentration(series: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not series:
        return {
            'kind': 'holders',
            'title': '籌碼集中度',
            'direction': 'concentrate',
            'score': None,
            'label': '資料不足',
            'summary': '籌碼集中度 —',
            'plainSummary': '尚無集保週資料。',
            'marketRows': [],
            'algo': ALGO,
            '_source': 'TDCC 集保戶股權分散表',
        }
    last = series[-1]
    # 找約 4 週前（資料為週頻，回看 4 筆）
    prev = series[-5] if len(series) >= 5 else (series[0] if len(series) >= 2 else None)

    major = last.get('major_pct')
    holders = last.get('holders')
    major_ch = None
    holders_ch_pct = None
    if prev and major is not None and prev.get('major_pct') is not None:
        major_ch = float(major) - float(prev['major_pct'])
    if prev and holders and prev.get('holders'):
        holders_ch_pct = (float(holders) / float(prev['holders']) - 1.0) * 100.0

    parts = []
    detail: Dict[str, Any] = {}
    rows = []

    if major is not None:
        sc = _tanh_map(major, 55.0, 20.0)
        parts.append(sc)
        detail['majorPct'] = round(float(major), 2)
        detail['majorLevelScore'] = round(sc, 1)
        rows.append({'k': '大股東水位', 'v': f'{float(major):.2f}%（≥400張）', 'score': round(sc, 1)})

    if major_ch is not None:
        sc = _tanh_map(major_ch, 0.0, 1.5)
        parts.append(sc)
        detail['majorCh4w'] = round(major_ch, 3)
        detail['majorMomScore'] = round(sc, 1)
        rows.append({
            'k': '集中動能',
            'v': f"4週 {major_ch:+.2f}pp",
            'score': round(sc, 1),
        })

    if holders_ch_pct is not None:
        sc = _clamp(50.0 - 50.0 * math.tanh(holders_ch_pct / 3.0))
        parts.append(sc)
        detail['holdersCh4wPct'] = round(holders_ch_pct, 3)
        detail['holdersMomScore'] = round(sc, 1)
        rows.append({
            'k': '人數動能',
            'v': f"4週人數 {holders_ch_pct:+.2f}%",
            'score': round(sc, 1),
        })

    # 背離
    divergence = None
    if major_ch is not None and holders_ch_pct is not None:
        if major_ch > 0.15 and holders_ch_pct > 1.0:
            divergence = 'retailization'  # 大戶比例升但人數大增 → 散戶湧入風險
        elif major_ch > 0.1 and holders_ch_pct < -0.5:
            divergence = 'confirm'

    score = round(sum(parts) / len(parts), 1) if parts else None
    # 散戶化背離時略降分
    if score is not None and divergence == 'retailization':
        score = round(max(0.0, score - 12.0), 1)
    if score is not None and divergence == 'confirm':
        score = round(min(100.0, score + 5.0), 1)

    label = _label(score, divergence)
    detail['holders'] = holders
    detail['megaPct'] = last.get('mega_pct')
    detail['date'] = last.get('date')
    detail['divergence'] = divergence

    plain = (
        f'目前籌碼集中度約 {score} 分（{label}）。'
        if score is not None else
        '籌碼集中度資料暫缺。'
    )
    plain += '分數愈高＝大戶愈集中；愈低＝愈發散。'
    if major is not None:
        plain += f' 大股東（≥400張）持有 {float(major):.2f}%'
    if holders is not None:
        plain += f'、股東人數 {int(holders):,}'
    plain += '。'
    if divergence == 'retailization':
        plain += ' 注意：大股東比例上升但人數同步大增，可能是散戶化背離。'
    elif divergence == 'confirm':
        plain += ' 大股東上升且人數下降，集中訊號較乾淨。'

    if last.get('mega_pct') is not None:
        rows.append({'k': '千張大戶', 'v': f"{float(last['mega_pct']):.2f}%", 'score': None})
    if holders is not None:
        rows.insert(0, {
            'k': '總股東人數',
            'v': f'{int(holders):,}',
            'score': detail.get('holdersMomScore'),
        })

    return {
        'kind': 'holders',
        'title': '籌碼集中度',
        'direction': 'concentrate',
        'score': score,
        'label': label,
        'summary': f'籌碼集中度 {score} · {label}' if score is not None else '籌碼集中度 —',
        'plainSummary': plain,
        'pillars': {
            'majorLevel': detail.get('majorLevelScore'),
            'majorMomentum': detail.get('majorMomScore'),
            'holdersMomentum': detail.get('holdersMomScore'),
        },
        'marketRows': rows,
        'detail': detail,
        'algo': ALGO,
        '_source': 'TDCC 集保戶股權分散表（≥400張＝大股東）',
    }


def get_chart(code: str, ensure: bool = True) -> Dict[str, Any]:
    code = _norm_code(code)
    if ensure:
        conn = _db()
        try:
            n = conn.execute('SELECT COUNT(*) FROM holders_week').fetchone()[0]
        finally:
            conn.close()
        if n < 50:
            start_background_backfill(weeks=120)
        else:
            # 輕量：若最新週過舊則刷新
            series = load_stock_series(code)
            need = True
            if series:
                try:
                    last_d = datetime.strptime(series[-1]['date'], '%Y-%m-%d').date()
                    need = (date.today() - last_d).days > 10
                except Exception:
                    need = True
            if need:
                try:
                    refresh_latest()
                except Exception as e:
                    print('[tdcc] refresh', e)

    series = load_stock_series(code)
    risk = score_concentration(series)

    holders_pts = [{'date': r['date'], 'value': float(r['holders'])} for r in series if r.get('holders') is not None]
    major_pts = [{'date': r['date'], 'value': float(r['major_pct'])} for r in series if r.get('major_pct') is not None]

    out_series = [
        {
            'key': 'holders', 'name': '總股東人數', 'scale': 'left',
            'color': '#6B9BB8', 'style': 'histogram', 'unit': '',
            'points': holders_pts, 'source': 'TDCC',
        },
        {
            'key': 'major_pct', 'name': '大股東持有率(≥400張)', 'scale': 'right',
            'color': '#D4A574', 'style': 'line', 'unit': '%',
            'points': major_pts, 'source': 'TDCC',
        },
    ]
    cid = holders_chart_id(code)
    return {
        'id': cid,
        'code': code,
        'name': f'{code} 籌碼集中度',
        'shortName': f'{code}集中',
        'market': 'TW',
        'description': '集保股東人數 vs 大股東持有率（≥400張）',
        'years': None,
        'series': out_series,
        'ok': any(len(s.get('points') or []) > 0 for s in out_series),
        'defaultViewMode': 'raw',
        'risk': risk,
        'backfill': dict(_backfill_state),
    }


def fundamental_payload(sym: str) -> Dict[str, Any]:
    code = parse_holders_sym(sym) or _norm_code(sym)
    chart = get_chart(code, ensure=True)
    risk = chart.get('risk') or {}
    today = date.today().strftime('%Y%m%d')
    return {
        'symbol': holders_chart_id(code),
        'code': code,
        'date': today,
        'market': 'TW',
        'kind': 'holders',
        'title': risk.get('title') or '籌碼集中度',
        'direction': 'concentrate',
        'revenue': None,
        'income': None,
        'score': risk.get('score'),
        'label': risk.get('label'),
        'summary': risk.get('summary'),
        'plainSummary': risk.get('plainSummary'),
        'pillars': risk.get('pillars'),
        'marketRows': risk.get('marketRows') or [],
        'algo': risk.get('algo') or ALGO,
        '_source': risk.get('_source'),
    }


def stock_snapshot(code: str) -> Dict[str, Any]:
    """給個股籌碼面板用的精簡快照（不開圖）。"""
    code = _norm_code(code)
    series = load_stock_series(code)
    if len(series) < 1:
        # 嘗試刷新當週後再讀
        try:
            refresh_latest()
        except Exception:
            pass
        series = load_stock_series(code)
    risk = score_concentration(series)
    last = series[-1] if series else None
    return {
        'code': code,
        'chartId': holders_chart_id(code),
        'ok': bool(series),
        'last': last,
        'points': len(series),
        'risk': risk,
    }


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--refresh', action='store_true')
    ap.add_argument('--backfill', type=int, default=0, help='weeks')
    ap.add_argument('--code', default='2330')
    args = ap.parse_args()
    if args.refresh:
        print(refresh_latest())
    if args.backfill:
        print('backfill', backfill_archive(weeks=args.backfill))
    c = get_chart(args.code, ensure=False)
    print(c['id'], c['ok'], (c.get('risk') or {}).get('summary'))
    for s in c['series']:
        print(s['key'], len(s['points']))
