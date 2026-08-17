# -*- coding: utf-8 -*-
"""
margin_cycle.py — 台股「融資週期／槓桿臨界」獨立指標

代號: __TW_MARGIN_CYCLE__

主圖序列：
  - 融資維持率（左軸，含 166／150／140／130 臨界線）
  - 融資餘額年增率（左軸，%）
  - 券資比 = 融券張數／融資張數 ×100（左軸，%）
  - 加權指數（右軸）

評分（direction=cycle，0~100）：
  越高＝槓桿擴張／偏熱擁擠；越低＝去槓桿／清算區（常近熊末或急殺後）
  三支柱等權：
    1. 維持率位置 — 相對 166% 中性（低→清算、高→擴張餘裕）
    2. 融資熱度 — 上市融資餘額 YoY（高→擁擠）
    3. 券資結構 — 券資比偏高→偏空擁擠／短底特徵（拉低週期分）；偏低→多方主導（抬高）

資料：
  - 維持率：margin_ratio.get_bars / meta
  - 融資／融券張數：TWSE MI_MARGN selectType=MS（SQLite 快取 + 背景回補）
  - 加權：Yahoo ^TWII
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
DB_PATH = os.path.join(DATA, 'margin_cycle.db')
SYMBOL = '__TW_MARGIN_CYCLE__'
TZ_TPE = timezone(timedelta(hours=8))

UA = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json,text/plain,*/*',
}

RISK_ZONES = [
    {'level': 130.0, 'label': '危險 130%', 'color': '#ef4444', 'hint': '斷頭／清算臨界'},
    {'level': 140.0, 'label': '警戒 140%', 'color': '#f97316', 'hint': '偏弱警戒'},
    {'level': 150.0, 'label': '偏弱 150%', 'color': '#eab308', 'hint': '低於長期中位'},
    {'level': 166.0, 'label': '門檻 166%', 'color': '#38bdf8', 'hint': '法定維持門檻參考'},
]

ALGO = {
    'id': SYMBOL,
    'title': '融資週期 · 槓桿臨界',
    'direction': 'cycle',
    'pillars': [
        {
            'key': 'mmPosition',
            'name': '維持率位置',
            'weight': '⅓',
            'plain': '融資維持率愈低，愈接近去槓桿／清算區；愈高代表保證金緩衝愈厚、槓桿尚可擴張。',
            'formula': '維持率分 = 50 + 50·tanh((維持率−166)/30)',
        },
        {
            'key': 'marginHeat',
            'name': '融資熱度',
            'weight': '⅓',
            'plain': '上市融資餘額年增愈高，代表市場加碼融資愈猛，偏熱／擁擠。',
            'formula': '熱度分 = 50 + 50·tanh(融資餘額YoY% / 25)',
        },
        {
            'key': 'shortStructure',
            'name': '券資結構',
            'weight': '⅓',
            'plain': '券資比（融券÷融資）偏高，常是空方擁擠、接近短線轉折；偏低則多方主導。',
            'formula': '結構分 = 50 − 50·tanh((券資比%−2.5)/2.0)',
        },
    ],
    'aggregate': '總分 = 有資料支柱簡單平均。0~30 清算區、30~55 修復、55~75 偏熱、75~100 擁擠高潮。',
    'viewNote': '維持率臨界線 166／150／140／130 畫在主圖；分數依最新快照，不隨縮放重算。',
}

_http_lock = threading.Lock()
_last_http = 0.0
_backfill_lock = threading.Lock()
_backfill_state = {
    'running': False, 'phase': '', 'done': 0, 'total': 0,
    'last_error': '', 'started_at': 0, 'finished_at': 0,
}


def _throttle(gap: float = 0.75):
    global _last_http
    with _http_lock:
        now = time.time()
        w = gap - (now - _last_http)
        if w > 0:
            time.sleep(w)
        _last_http = time.time()


def _fnum(x) -> Optional[float]:
    if x is None:
        return None
    s = str(x).strip().replace(',', '').replace('%', '')
    if not s or s in ('--', '-', '—', 'None', 'null'):
        return None
    try:
        v = float(s)
        return None if v != v else v
    except Exception:
        return None


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


def _tanh_map(x: float, center: float, scale: float) -> float:
    if scale == 0:
        return 50.0
    return _clamp(50.0 + 50.0 * math.tanh((float(x) - center) / scale))


def _db() -> sqlite3.Connection:
    os.makedirs(DATA, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS margin_ms (
             d TEXT PRIMARY KEY,
             margin_lots REAL,
             short_lots REAL,
             margin_amt_k REAL,
             ss_ratio REAL
           )'''
    )
    conn.commit()
    return conn


def fetch_ms_day(d: date) -> Optional[Dict[str, Any]]:
    """抓 TWSE MI_MARGN MS：融資／融券張數、融資金額(仟元)。"""
    ds = d.strftime('%Y%m%d')
    url = f'https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date={ds}&selectType=MS&response=json'
    try:
        _throttle()
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read()
        j = json.loads(raw.decode('utf-8-sig'))
    except Exception as e:
        print('[margin_cycle] MS', ds, e)
        return None
    if str(j.get('stat', '')).upper() not in ('OK',):
        return None
    margin_lots = short_lots = margin_amt_k = None
    for t in j.get('tables') or []:
        fields = t.get('fields') or []
        if not fields:
            continue
        idx_bal = None
        for i, f in enumerate(fields):
            if '今日餘額' in str(f):
                idx_bal = i
                break
        if idx_bal is None:
            continue
        for row in t.get('data') or []:
            if not row:
                continue
            label = str(row[0])
            v = _fnum(row[idx_bal] if idx_bal < len(row) else row[-1])
            if '融資(交易單位)' in label or (label.startswith('融資') and '金額' not in label and '交易' in label):
                margin_lots = v
            elif label.startswith('融資') and '交易單位' in label:
                margin_lots = v
            elif '融券(交易單位)' in label or (label.startswith('融券') and '交易' in label):
                short_lots = v
            elif '融資金額' in label:
                margin_amt_k = v
    # 寬鬆：第一欄純「融資」且無金額
    if margin_lots is None or short_lots is None:
        for t in j.get('tables') or []:
            fields = t.get('fields') or []
            idx_bal = next((i for i, f in enumerate(fields) if '今日餘額' in str(f)), None)
            if idx_bal is None:
                continue
            for row in t.get('data') or []:
                label = str(row[0]) if row else ''
                v = _fnum(row[idx_bal] if idx_bal < len(row) else None)
                if margin_lots is None and label.startswith('融資') and '金額' not in label:
                    margin_lots = v
                if short_lots is None and label.startswith('融券'):
                    short_lots = v
                if margin_amt_k is None and '融資金額' in label:
                    margin_amt_k = v
    if margin_lots is None and short_lots is None and margin_amt_k is None:
        return None
    ss = None
    if margin_lots and margin_lots > 0 and short_lots is not None:
        ss = short_lots / margin_lots * 100.0
    return {
        'date': d.isoformat(),
        'margin_lots': margin_lots,
        'short_lots': short_lots,
        'margin_amt_k': margin_amt_k,
        'ss_ratio': ss,
    }


def upsert_ms(row: Dict[str, Any]) -> None:
    conn = _db()
    try:
        conn.execute(
            'INSERT OR REPLACE INTO margin_ms(d, margin_lots, short_lots, margin_amt_k, ss_ratio) VALUES (?,?,?,?,?)',
            (row['date'], row.get('margin_lots'), row.get('short_lots'),
             row.get('margin_amt_k'), row.get('ss_ratio')),
        )
        conn.commit()
    finally:
        conn.close()


def refresh_today() -> Optional[Dict[str, Any]]:
    today = date.today()
    for i in range(0, 12):
        d = today - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        row = fetch_ms_day(d)
        if row:
            upsert_ms(row)
            return row
    return None


def load_ms_rows() -> List[Dict[str, Any]]:
    conn = _db()
    try:
        rows = conn.execute(
            'SELECT d, margin_lots, short_lots, margin_amt_k, ss_ratio FROM margin_ms ORDER BY d'
        ).fetchall()
    finally:
        conn.close()
    out = []
    for d, ml, sl, amt, ss in rows:
        out.append({
            'date': d,
            'margin_lots': ml,
            'short_lots': sl,
            'margin_amt_k': amt,
            'ss_ratio': ss,
        })
    return out


def _percentile_rank(values: List[float], current: float) -> float:
    vals = sorted(float(x) for x in values if x is not None and math.isfinite(float(x)))
    if not vals:
        return 0.0
    below = sum(1 for x in vals if x < current)
    equal = sum(1 for x in vals if x == current)
    return (below + max(0, equal - 1) / 2.0) / max(1, len(vals) - 1) * 100.0


def margin_balance_state(rows: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Return a slow crowding brake from official margin-balance history.

    This state can only reduce a research ceiling.  It must never be used as a
    standalone buy/sell signal because high balances can persist in a trend.
    """
    clean = []
    for row in rows if rows is not None else load_ms_rows():
        try:
            d = date.fromisoformat(str(row.get('date'))[:10])
            value = float(row.get('margin_amt_k'))
        except (TypeError, ValueError):
            continue
        if math.isfinite(value) and value >= 0:
            clean.append((d, value))
    clean.sort(key=lambda x: x[0])
    if not clean:
        return {
            'available': False, 'reason': 'local_margin_history_unavailable',
            'source': 'TWSE MI_MARGN MS', 'role': 'risk_brake_only',
        }
    last_date, current = clean[-1]
    trailing = [(d, value) for d, value in clean if d >= last_date - timedelta(days=364)]
    percentile = _percentile_rank([value for _, value in trailing], current)
    target = last_date - timedelta(days=28)
    prior_candidates = [(d, value) for d, value in clean if d <= target]
    prior = prior_candidates[-1] if prior_candidates else None
    change4w = ((current / prior[1] - 1.0) * 100.0) if prior and prior[1] else None
    direction = 'unknown'
    if change4w is not None:
        direction = 'rising' if change4w > 2.0 else ('decreasing' if change4w < -2.0 else 'flat')
    return {
        'available': True,
        'value': round(current, 2), 'unit': 'thousand_TWD', 'asOf': last_date.isoformat(),
        'percentile52w': round(percentile, 1),
        'change4wPct': round(change4w, 2) if change4w is not None else None,
        'direction': direction, 'samples52w': len(trailing),
        'source': 'TWSE MI_MARGN MS',
        'reference': 'latest listed-market margin balance versus trailing 52-week observations',
        'role': 'risk_brake_only',
        'confidence': 'medium' if len(trailing) >= 100 else 'low',
    }


def _yoy_series(rows: List[Dict[str, Any]], key: str = 'margin_lots') -> List[Dict[str, Any]]:
    by_d = {r['date']: r.get(key) for r in rows if r.get(key) is not None}
    dates = sorted(by_d.keys())
    pts = []
    for ds in dates:
        try:
            y, m, day = map(int, ds.split('-'))
            prev = date(y - 1, m, day) if not (m == 2 and day == 29) else date(y - 1, 2, 28)
        except Exception:
            continue
        cur = by_d[ds]
        if cur is None or cur == 0:
            continue
        # nearest within ±10d
        best = None
        best_dist = 99
        for delta in range(-10, 11):
            pd = (prev + timedelta(days=delta)).isoformat()
            if pd in by_d and by_d[pd]:
                dist = abs(delta)
                if dist < best_dist:
                    best_dist = dist
                    best = by_d[pd]
        if best is None or best == 0:
            continue
        pts.append({'date': ds, 'value': (float(cur) / float(best) - 1.0) * 100.0})
    return pts


def _ss_series(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    pts = []
    for r in rows:
        if r.get('ss_ratio') is not None:
            pts.append({'date': r['date'], 'value': float(r['ss_ratio'])})
    return pts


def _margin_ratio_points(years: int = 20) -> List[Dict[str, Any]]:
    try:
        import margin_ratio as mr
        mr.ensure_seed_loaded()
        bars = mr.get_bars()
    except Exception as e:
        print('[margin_cycle] margin_ratio bars', e)
        return []
    if not bars:
        return []
    cutoff = (date.today() - timedelta(days=int(years) * 365)).isoformat()
    pts = []
    for ts, _o, _h, _l, cl, _v in bars:
        if cl is None:
            continue
        d = datetime.fromtimestamp(int(ts), tz=TZ_TPE).date().isoformat()
        if d < cutoff:
            continue
        pts.append({'date': d, 'value': float(cl)})
    return pts


def _twii_points(years: int = 20) -> List[Dict[str, Any]]:
    try:
        import macro_track as mt
        return mt._filter_years(mt._yahoo_closes('^TWII', years), years)
    except Exception as e:
        print('[margin_cycle] twii', e)
        return []


def backfill(start: Optional[date] = None, end: Optional[date] = None,
             step_days: int = 7) -> int:
    """抽樣回補 MS 信用統計。"""
    start = start or date(2018, 1, 2)
    end = end or date.today()
    step = max(1, int(step_days))
    existing = {r['date'] for r in load_ms_rows()}
    days = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5 and cur.isoformat() not in existing:
            days.append(cur)
        cur += timedelta(days=step)
    n = 0
    _backfill_state.update({
        'running': True, 'phase': 'ms', 'done': 0, 'total': len(days),
        'last_error': '', 'started_at': time.time(), 'finished_at': 0,
    })
    try:
        for d in days:
            try:
                row = fetch_ms_day(d)
                if row:
                    upsert_ms(row)
                    n += 1
            except Exception as e:
                _backfill_state['last_error'] = str(e)
            _backfill_state['done'] = _backfill_state.get('done', 0) + 1
        # 補最新
        refresh_today()
    finally:
        _backfill_state['running'] = False
        _backfill_state['finished_at'] = time.time()
        _backfill_state['phase'] = 'done'
    return n


def start_background_backfill(years: int = 8, step_days: int = 14):
    if _backfill_state.get('running'):
        return False
    start = date.today() - timedelta(days=int(years) * 365)

    def _run():
        with _backfill_lock:
            try:
                n = backfill(start=start, step_days=step_days)
                print('[margin_cycle] backfill done', n)
            except Exception as e:
                print('[margin_cycle] backfill failed', e)
                _backfill_state['last_error'] = str(e)
                _backfill_state['running'] = False

    try:
        import job_queue as jq
        if jq.is_busy('margin_cycle'):
            return False
        r = jq.submit(
            'margin_cycle', _run,
            meta={'years': years, 'step_days': step_days, 'start': start.isoformat()},
        )
        return bool(r.get('queued'))
    except Exception:
        threading.Thread(target=_run, daemon=True).start()
        return True


def _label_cycle(score: Optional[float]) -> str:
    if score is None:
        return '資料不足'
    if score >= 75:
        return '擁擠高潮'
    if score >= 55:
        return '偏熱'
    if score >= 30:
        return '修復／中性'
    return '清算區'


def score_cycle(mm: Optional[float], yoy: Optional[float],
                ss_ratio: Optional[float]) -> Tuple[Optional[float], Dict[str, Any]]:
    detail: Dict[str, Any] = {}
    parts = []
    if mm is not None:
        sc = _tanh_map(mm, 166.0, 30.0)
        parts.append(sc)
        detail['marginRatio'] = round(float(mm), 2)
        detail['mmScore'] = round(sc, 1)
        zone = None
        for z in RISK_ZONES:
            if float(mm) <= z['level']:
                zone = z
                break
        if zone:
            detail['riskZone'] = zone.get('label')
    if yoy is not None:
        sc = _tanh_map(yoy, 0.0, 25.0)
        parts.append(sc)
        detail['marginYoyPct'] = round(float(yoy), 2)
        detail['heatScore'] = round(sc, 1)
    if ss_ratio is not None:
        sc = _clamp(50.0 - 50.0 * math.tanh((float(ss_ratio) - 2.5) / 2.0))
        parts.append(sc)
        detail['ssRatioPct'] = round(float(ss_ratio), 3)
        detail['ssScore'] = round(sc, 1)
    if not parts:
        return None, detail
    avg = sum(parts) / len(parts)
    detail['score'] = round(avg, 1)
    return round(avg, 1), detail


def build_risk_payload(mm: Optional[float], yoy: Optional[float],
                       ss_ratio: Optional[float]) -> Dict[str, Any]:
    score, detail = score_cycle(mm, yoy, ss_ratio)
    label = _label_cycle(score)
    rows = []
    if detail.get('mmScore') is not None:
        rows.append({
            'k': '維持率位置',
            'v': f"{detail['marginRatio']:.2f}%" + (f"（{detail['riskZone']}）" if detail.get('riskZone') else ''),
            'score': detail['mmScore'],
        })
    if detail.get('heatScore') is not None:
        y = detail['marginYoyPct']
        rows.append({
            'k': '融資熱度',
            'v': f"餘額YoY {y:+.1f}%",
            'score': detail['heatScore'],
        })
    if detail.get('ssScore') is not None:
        rows.append({
            'k': '券資結構',
            'v': f"券資比 {detail['ssRatioPct']:.2f}%",
            'score': detail['ssScore'],
        })
    plain = (
        f'目前融資週期約 {score} 分（{label}）。'
        if score is not None else
        '融資週期資料暫缺。'
    )
    plain += '分數愈高＝槓桿愈擴張／偏熱；愈低＝去槓桿／清算區（常近急殺或熊末）。'
    if rows:
        plain += ' 支柱：' + '、'.join(f"{r['k']} {int(round(r['score']))}" for r in rows) + '。'
    return {
        'kind': 'margin_cycle',
        'title': '融資週期',
        'direction': 'cycle',
        'score': score,
        'label': label,
        'summary': f'融資週期 {score} · {label}' if score is not None else '融資週期 —',
        'plainSummary': plain,
        'pillars': {
            'mmPosition': detail.get('mmScore'),
            'marginHeat': detail.get('heatScore'),
            'shortStructure': detail.get('ssScore'),
        },
        'marketRows': rows,
        'algo': ALGO,
        'riskZones': RISK_ZONES,
        '_source': 'TWSE MI_MARGN(MS) + 大盤融資維持率 + ^TWII',
    }


def get_chart(years: int = 20, force_refresh: bool = True) -> Dict[str, Any]:
    yrs = max(1, min(40, int(years or 20)))
    if force_refresh:
        try:
            refresh_today()
        except Exception as e:
            print('[margin_cycle] refresh_today', e)
    # 若歷史太少，觸發背景回補
    rows = load_ms_rows()
    if len(rows) < 40:
        start_background_backfill(years=min(yrs, 10), step_days=14)

    mm_pts = _margin_ratio_points(yrs)
    yoy_pts = _yoy_series(rows, 'margin_lots')
    # 裁切 years
    cutoff = (date.today() - timedelta(days=yrs * 365)).isoformat()
    yoy_pts = [p for p in yoy_pts if p['date'] >= cutoff]
    ss_pts = [p for p in _ss_series(rows) if p['date'] >= cutoff]
    twii = _twii_points(yrs)

    series = [
        {
            'key': 'margin_ratio', 'name': '融資維持率', 'scale': 'left',
            'color': '#6B9BB8', 'style': 'line', 'unit': '%',
            'points': mm_pts, 'source': 'margin_ratio',
        },
        {
            'key': 'twii', 'name': '加權指數', 'scale': 'right',
            'color': '#D4A574', 'style': 'line', 'unit': '',
            'points': twii, 'source': 'Yahoo ^TWII',
        },
    ]
    # 輔助序列：預設可由圖例開啟；尺度與維持率不同，前端預設關閉
    if yoy_pts:
        series.append({
            'key': 'margin_yoy', 'name': '融資餘額年增率', 'scale': 'left',
            'color': '#B89595', 'style': 'line', 'unit': '%',
            'points': yoy_pts, 'source': 'TWSE MI_MARGN MS',
            'defaultVisible': False,
        })
    if ss_pts:
        series.append({
            'key': 'ss_ratio', 'name': '券資比', 'scale': 'left',
            'color': '#8FA88F', 'style': 'line', 'unit': '%',
            'points': ss_pts, 'source': 'TWSE MI_MARGN MS',
            'defaultVisible': False,
        })

    last_mm = mm_pts[-1]['value'] if mm_pts else None
    last_yoy = yoy_pts[-1]['value'] if yoy_pts else None
    last_ss = ss_pts[-1]['value'] if ss_pts else None
    # 若 YoY 尚無，用最新列與一年前估算
    if last_yoy is None and rows:
        tmp = _yoy_series(rows, 'margin_lots')
        if tmp:
            last_yoy = tmp[-1]['value']
    risk = build_risk_payload(last_mm, last_yoy, last_ss)

    return {
        'id': SYMBOL,
        'name': '融資週期（槓桿臨界）',
        'shortName': '融資週期',
        'market': 'TW',
        'description': '維持率臨界＋融資餘額熱度＋券資結構，觀察牛熊槓桿週期',
        'years': yrs,
        'series': series,
        'ok': any(len(s.get('points') or []) > 0 for s in series),
        'defaultViewMode': 'raw',
        'riskLines': RISK_ZONES,
        'risk': risk,
        'backfill': dict(_backfill_state),
    }


def fundamental_payload(sym: str = SYMBOL) -> Dict[str, Any]:
    """給 /fundamental 用的 payload。"""
    chart = get_chart(years=5, force_refresh=True)
    risk = chart.get('risk') or {}
    today = date.today().strftime('%Y%m%d')
    return {
        'symbol': sym,
        'code': SYMBOL,
        'date': today,
        'market': 'TW',
        'kind': 'margin_cycle',
        'title': risk.get('title') or '融資週期',
        'direction': 'cycle',
        'revenue': None,
        'income': None,
        'score': risk.get('score'),
        'label': risk.get('label'),
        'summary': risk.get('summary'),
        'plainSummary': risk.get('plainSummary'),
        'pillars': risk.get('pillars'),
        'marketRows': risk.get('marketRows') or [],
        'algo': risk.get('algo') or ALGO,
        'riskZones': RISK_ZONES,
        '_source': risk.get('_source') or 'TWSE MI_MARGN + margin_ratio',
    }


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--backfill', action='store_true')
    ap.add_argument('--years', type=int, default=8)
    ap.add_argument('--step', type=int, default=14)
    ap.add_argument('--today', action='store_true')
    args = ap.parse_args()
    if args.today:
        print(refresh_today())
    if args.backfill:
        start = date.today() - timedelta(days=args.years * 365)
        print('backfill', backfill(start=start, step_days=args.step))
    c = get_chart(years=10)
    print('ok', c['ok'], 'risk', (c.get('risk') or {}).get('summary'))
    for s in c['series']:
        print(s['key'], len(s['points'] or []))
