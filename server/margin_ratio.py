#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
margin_ratio.py — 台股大盤融資維持率（對齊 MacroMicro / TWSE 定義）

公式（與 https://www.macromicro.me/charts/53117/taiwan-taiex-maintenance-margin 一致）:
  大盤融資維持率 = 所有融資股票市值 / 大盤融資餘額 × 100
  分子 = Σ(融資今日餘額_張 × 1000 × 收盤價)，且「不含 ETF」
  分母 = TWSE 信用交易統計「融資金額(仟元)」今日餘額 × 1000

資料策略:
  1) 本地 seed CSV（data/margin_ratio_history.csv）— 多年歷史一次載入
  2) TWSE 歷史日回溯（selectType=STOCK 排除 ETF）— 可補缺口 / 全歷史
  3) 今日即時：OpenAPI MI_MARGN + STOCK_DAY_ALL + MS 融資金額（同樣排除 ETF）
  4) 可選 FINMIND_TOKEN → TaiwanTotalExchangeMarginMaintenance 加速回補

符號: __MARGIN_RATIO__
DB: bars(symbol='__MARGIN_RATIO__', market='TW', OHLC=ratio, volume=0)
時間戳: Asia/Taipei 當日 00:00
"""
from __future__ import annotations

import csv
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# 與 datastore 同根
if getattr(sys, 'frozen', False):
    _BASE = os.path.dirname(sys.executable)
else:
    _BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATA_DIR = os.path.join(_BASE, 'data')
SEED_CSV = os.path.join(DATA_DIR, 'margin_ratio_history.csv')
SYMBOL = '__MARGIN_RATIO__'
MARKET = 'TW'
TZ_TPE = timezone(timedelta(hours=8))

# 風險區間參考線（前端 price line / meta 共用）
RISK_ZONES = [
    {'level': 130.0, 'label': '危險區 130%', 'color': '#ef4444', 'hint': '歷史極端低檔／斷頭潮警戒'},
    {'level': 140.0, 'label': '警戒 140%', 'color': '#f97316', 'hint': '偏弱區'},
    {'level': 150.0, 'label': '偏弱 150%', 'color': '#eab308', 'hint': '低於長期中位'},
    {'level': 166.0, 'label': '維持門檻 166%', 'color': '#38bdf8', 'hint': '個股維持率法定參考'},
]

_UA = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'application/json,text/plain,*/*',
}
_http_lock = threading.Lock()
_last_http_ts = 0.0
_HTTP_GAP = 0.85  # TWSE 禮貌間隔（秒）

_backfill_lock = threading.Lock()
_backfill_state = {
    'running': False,
    'phase': '',
    'done': 0,
    'total': 0,
    'last_error': '',
    'started_at': 0,
    'finished_at': 0,
}
_refresh_lock = threading.Lock()
_last_today_refresh = 0.0
_seed_ensured = False
_seed_ensured_n = 0
_TODAY_REFRESH_TTL = 300  # 今日值最短 5 分鐘重算一次


def _throttle():
    global _last_http_ts
    with _http_lock:
        now = time.time()
        wait = _HTTP_GAP - (now - _last_http_ts)
        if wait > 0:
            time.sleep(wait)
        _last_http_ts = time.time()


def _http_json(url: str, timeout: int = 25) -> dict | list:
    _throttle()
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    if not raw or len(raw) < 2:
        raise RuntimeError(f'empty body for {url}')
    # TWSE 偶爾回 HTML／空白，先擋掉
    head = raw.lstrip()[:1]
    if head not in (b'{', b'['):
        raise RuntimeError(f'non-json body for {url}: {raw[:80]!r}')
    for enc in ('utf-8-sig', 'utf-8', 'cp950', 'big5'):
        try:
            return json.loads(raw.decode(enc))
        except Exception:
            continue
    raise RuntimeError(f'decode failed for {url}')


def _fnum(x) -> Optional[float]:
    if x is None:
        return None
    s = str(x).strip().replace(',', '').replace('%', '')
    if not s or s in ('--', '-', '—', '查無資料'):
        return None
    try:
        v = float(s)
        if v != v:  # NaN
            return None
        return v
    except Exception:
        return None


def _date_to_ts(d: date) -> int:
    return int(datetime(d.year, d.month, d.day, tzinfo=TZ_TPE).timestamp())


def _ts_to_date(ts: int) -> date:
    return datetime.fromtimestamp(int(ts), tz=TZ_TPE).date()


def _parse_ymd(s: str) -> Optional[date]:
    s = (s or '').strip()
    for fmt in ('%Y-%m-%d', '%Y%m%d'):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def _is_etf_code(code: str) -> bool:
    """MacroMicro 註：分子不含 ETF。台股 ETF 代號多為 00xx / 009xxx（含 6 碼）。"""
    c = str(code or '').strip()
    if not c or not c[0].isdigit():
        return True
    if c.startswith('00') and len(c) in (4, 5, 6):
        return True
    return False


def _is_stock_code(code: str) -> bool:
    c = str(code or '').strip()
    if not c or c in ('\u3000', '合計', '總計'):
        return False
    if not c[0].isdigit():
        return False
    return not _is_etf_code(c)


# ── TWSE parsers ──────────────────────────────────────────────
def _parse_loan_from_tables(tables: Sequence[dict]) -> Optional[float]:
    """從信用交易統計表取出融資金額(仟元)今日餘額 → 轉為「元」。"""
    for t in tables or []:
        fields = t.get('fields') or []
        data = t.get('data') or []
        if not fields or '今日餘額' not in fields:
            continue
        if fields and fields[0] not in ('項目',):
            # 有些回傳第一欄名不同，仍嘗試找「融資金額」列
            pass
        idx = fields.index('今日餘額')
        for row in data:
            if not row:
                continue
            if '融資金額' in str(row[0]):
                v = _fnum(row[idx])
                if v is not None and v > 0:
                    return v * 1000.0  # 仟元 → 元
    return None


def _parse_lots_from_tables(tables: Sequence[dict], exclude_etf: bool = True) -> Dict[str, float]:
    lots: Dict[str, float] = {}
    for t in tables or []:
        fields = t.get('fields') or []
        data = t.get('data') or []
        if '代號' not in fields or '今日餘額' not in fields:
            continue
        ic = fields.index('代號')
        # fields 內有兩個「今日餘額」：第一個屬融資
        ibal = fields.index('今日餘額')
        for row in data:
            if not row or len(row) <= max(ic, ibal):
                continue
            code = str(row[ic]).strip()
            if exclude_etf:
                if not _is_stock_code(code):
                    continue
            else:
                if not code or not code[0].isdigit():
                    continue
            bal = _fnum(row[ibal])
            if bal is None or bal < 0:
                continue
            lots[code] = bal
    return lots


def _fetch_closes_for_date(d: date) -> Dict[str, float]:
    """TWSE MI_INDEX 收盤價（官方僅自 2004-02-11 起）。"""
    ymd = d.strftime('%Y%m%d')
    try:
        payload = _http_json(
            f'https://www.twse.com.tw/exchangeReport/MI_INDEX'
            f'?response=json&date={ymd}&type=ALLBUT0999'
        )
    except Exception:
        return {}
    closes: Dict[str, float] = {}
    if str(payload.get('stat', '')).upper() not in ('OK',):
        return closes
    for t in payload.get('tables') or []:
        fields = t.get('fields') or []
        if '證券代號' not in fields or '收盤價' not in fields:
            continue
        ic, ip = fields.index('證券代號'), fields.index('收盤價')
        for row in t.get('data') or []:
            if not row or len(row) <= max(ic, ip):
                continue
            code = str(row[ic]).strip()
            cl = _fnum(row[ip])
            if cl is not None and cl > 0:
                closes[code] = cl
        break
    return closes


# Yahoo 收盤價快取（補 TWSE MI_INDEX 2004-02-11 以前的官方缺口）
_MI_INDEX_START = date(2004, 2, 11)
_yahoo_series_cache: Dict[str, Dict[date, float]] = {}
_yahoo_fail: set = set()


def _fetch_yahoo_series(code: str, start: date, end: date) -> Dict[date, float]:
    """抓單一代號日線收盤（.TW / .TWO），結果快取於記憶體。404 快速跳過。"""
    code = str(code).strip()
    if code in _yahoo_series_cache:
        return _yahoo_series_cache[code]
    if code in _yahoo_fail:
        return {}
    p1 = int(datetime(start.year, start.month, start.day, tzinfo=TZ_TPE).timestamp()) - 86400
    p2 = int(datetime(end.year, end.month, end.day, tzinfo=TZ_TPE).timestamp()) + 86400
    mapping: Dict[date, float] = {}
    for suf in ('.TW', '.TWO'):
        # 每個後綴只打 query1；404 立刻換後綴，避免 4 倍節流浪費
        url = (
            f'https://query1.finance.yahoo.com/v8/finance/chart/'
            f'{urllib.parse.quote(code + suf)}'
            f'?interval=1d&period1={p1}&period2={p2}'
        )
        try:
            _throttle()
            req = urllib.request.Request(url, headers=_UA)
            with urllib.request.urlopen(req, timeout=25) as resp:
                raw = resp.read()
            payload = json.loads(raw.decode('utf-8'))
            res = (payload.get('chart') or {}).get('result') or []
            if not res:
                continue
            ts_list = res[0].get('timestamp') or []
            q = (res[0].get('indicators') or {}).get('quote') or [{}]
            closes = (q[0] or {}).get('close') or []
            for i, ts in enumerate(ts_list):
                if i >= len(closes) or closes[i] is None:
                    continue
                try:
                    cl = float(closes[i])
                except Exception:
                    continue
                if cl <= 0:
                    continue
                mapping[datetime.fromtimestamp(int(ts), tz=TZ_TPE).date()] = cl
            if mapping:
                _yahoo_series_cache[code] = mapping
                return mapping
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue  # 試下一個後綴
            continue
        except Exception:
            continue
    _yahoo_fail.add(code)
    _yahoo_series_cache[code] = {}
    return {}


def _closes_from_yahoo(codes_ordered: Sequence[str], d: date,
                       span_start: Optional[date] = None,
                       span_end: Optional[date] = None,
                       min_hits: int = 30) -> Dict[str, float]:
    """依優先序取 Yahoo 收盤；已快取／已失敗者秒回，其餘逐檔補齊。"""
    span_start = span_start or date(2000, 12, 1)
    span_end = span_end or date(2004, 3, 1)
    out: Dict[str, float] = {}
    for code in codes_ordered:
        if not code or not str(code)[0].isdigit():
            continue
        c = str(code)
        series = _fetch_yahoo_series(c, span_start, span_end)
        cl = series.get(d)
        if cl is not None and cl > 0:
            out[c] = cl
    return out


def _fetch_margin_tables(d: date, select_type: str) -> List[dict]:
    ymd = d.strftime('%Y%m%d')
    # RWD 端點對 STOCK 回傳個股列較完整；exchangeReport 對 MS/ALL 穩定
    if select_type.upper() == 'STOCK':
        url = (
            f'https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN'
            f'?date={ymd}&selectType=STOCK&response=json'
        )
    else:
        url = (
            f'https://www.twse.com.tw/exchangeReport/MI_MARGN'
            f'?response=json&date={ymd}&selectType={urllib.parse.quote(select_type)}'
        )
    payload = _http_json(url)
    if str(payload.get('stat', '')).upper() not in ('OK',):
        return []
    return list(payload.get('tables') or [])


def _margin_lots_and_loan(d: date) -> Tuple[Dict[str, float], Optional[float]]:
    stock_tables = _fetch_margin_tables(d, 'STOCK')
    lots = _parse_lots_from_tables(stock_tables, exclude_etf=True)
    loan = _parse_loan_from_tables(stock_tables)
    if not lots:
        try:
            all_tables = _fetch_margin_tables(d, 'ALL')
        except Exception:
            all_tables = []
        lots = _parse_lots_from_tables(all_tables, exclude_etf=True)
        if loan is None:
            loan = _parse_loan_from_tables(all_tables)
    if loan is None:
        for st in ('MS', 'ALL'):
            try:
                loan = _parse_loan_from_tables(_fetch_margin_tables(d, st))
            except Exception:
                loan = None
            if loan is not None:
                break
    return lots, loan


def compute_ratio_for_date(d: date) -> Optional[float]:
    """計算指定交易日大盤融資維持率（分子不含 ETF）。失敗回 None。

    收盤價來源：
      1) TWSE MI_INDEX（≥ 2004-02-11）
      2) Yahoo 個股日線快取（補 2001～2004-02-10 官方缺口）
    """
    try:
        lots, loan = _margin_lots_and_loan(d)
        if not lots or not loan or loan <= 0:
            return None

        closes = _fetch_closes_for_date(d) if d >= _MI_INDEX_START else {}
        if not closes:
            # 官方無收盤價（或當日 MI_INDEX 失敗）→ Yahoo 後備
            # 融資餘額大的優先，提高覆蓋率並利於早停
            ordered = [c for c, _ in sorted(lots.items(), key=lambda kv: kv[1], reverse=True)]
            closes = _closes_from_yahoo(
                ordered, d,
                span_start=date(2000, 12, 1),
                span_end=max(d, date(2004, 3, 15)),
                min_hits=30,
            )
        if not closes:
            return None

        collateral = 0.0
        used = 0
        for code, lot in lots.items():
            if lot <= 0:
                continue
            cl = closes.get(code)
            if cl is None:
                continue
            collateral += lot * 1000.0 * cl
            used += 1
        # 早期年份 Yahoo 覆蓋率較低；至少要有一定代表性
        min_used = 30 if d < _MI_INDEX_START else 50
        if used < min_used or collateral <= 0:
            return None
        return collateral / loan * 100.0
    except Exception as e:
        print(f'[margin] compute {d.isoformat()} failed: {e}')
        return None


def _parse_exchange_date(value) -> Optional[date]:
    """解析 TWSE 西元 YYYYMMDD 或民國 YYYMMDD 日期。"""
    raw = ''.join(ch for ch in str(value or '') if ch.isdigit())
    try:
        if len(raw) == 8:
            return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        if len(raw) == 7:
            return date(int(raw[:3]) + 1911, int(raw[3:5]), int(raw[5:7]))
    except ValueError:
        return None
    return None


def _coherent_live_exchange_date(rows_closes, margin_summary) -> Optional[date]:
    """現股收盤與融資總額必須屬於同一交易日，否則拒絕混算。"""
    stock_date = next(
        (_parse_exchange_date(r.get('Date')) for r in rows_closes
         if isinstance(r, dict) and _parse_exchange_date(r.get('Date'))),
        None,
    ) if isinstance(rows_closes, list) else None
    margin_date = _parse_exchange_date(
        margin_summary.get('date') if isinstance(margin_summary, dict) else None
    )
    if stock_date is None or margin_date is None or stock_date != margin_date:
        return None
    return stock_date


def fetch_latest_ratio_live() -> Optional[Tuple[date, float]]:
    """最新交易日：回傳交易所日期與融資維持率，禁止用本機日期代替資料日期。"""
    try:
        rows_margin = _http_json('https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN')
        per_stock: Dict[str, float] = {}
        if isinstance(rows_margin, list):
            for r in rows_margin:
                if not isinstance(r, dict):
                    continue
                code = str(r.get('股票代號') or '').strip()
                if not _is_stock_code(code):
                    continue
                lots = _fnum(r.get('融資今日餘額'))
                if lots is not None and lots >= 0:
                    per_stock[code] = lots

        rows_closes = _http_json('https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL')
        closes: Dict[str, float] = {}
        if isinstance(rows_closes, list):
            for r in rows_closes:
                if not isinstance(r, dict):
                    continue
                code = str(r.get('Code') or '').strip()
                cl = _fnum(r.get('ClosingPrice'))
                if code and cl is not None and cl > 0:
                    closes[code] = cl

        ms = _http_json(
            'https://www.twse.com.tw/exchangeReport/MI_MARGN?response=json&selectType=MS'
        )
        exchange_date = _coherent_live_exchange_date(rows_closes, ms)
        if exchange_date is None:
            print('[margin] latest snapshot rejected: STOCK_DAY_ALL / MI_MARGN dates missing or mismatched')
            return None
        total_loan = _parse_loan_from_tables(ms.get('tables') or [])
        if not per_stock or not closes or not total_loan or total_loan <= 0:
            return None
        collateral = 0.0
        for code, lots in per_stock.items():
            cl = closes.get(code)
            if cl is None or lots <= 0:
                continue
            collateral += lots * 1000.0 * cl
        if collateral <= 0:
            return None
        return exchange_date, collateral / total_loan * 100.0
    except Exception as e:
        print('[margin] today live compute failed:', e)
        return None


def fetch_today_ratio_live() -> Optional[float]:
    """相容舊呼叫端：只回傳最新交易日的融資維持率數值。"""
    sample = fetch_latest_ratio_live()
    return sample[1] if sample else None


# ── Seed / FinMind / persistence helpers ─────────────────────
def _import_datastore():
    try:
        import datastore as ds
        return ds
    except ImportError:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import datastore as ds
        return ds


def load_seed_csv(path: str = SEED_CSV) -> List[Tuple[int, float]]:
    """回傳 [(ts, ratio), ...]；支援 date,margin_ratio_pct 或 date,ratio。"""
    out: List[Tuple[int, float]] = []
    if not os.path.isfile(path):
        return out
    try:
        with open(path, 'r', encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            for row in reader:
                d = _parse_ymd(row.get('date') or row.get('Date') or '')
                ratio = _fnum(
                    row.get('margin_ratio_pct')
                    or row.get('ratio')
                    or row.get('TotalExchangeMarginMaintenance')
                    or row.get('value')
                )
                if d is None or ratio is None or ratio <= 0:
                    continue
                out.append((_date_to_ts(d), float(ratio)))
    except Exception as e:
        print('[margin] seed load failed:', e)
    return out


def save_seed_csv(rows: Sequence[Tuple[int, float]], path: str = SEED_CSV) -> int:
    """rows: [(ts, ratio), ...] → 寫入正規化 CSV。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    uniq: Dict[int, float] = {}
    for ts, ratio in rows:
        if ratio and ratio > 0:
            uniq[int(ts)] = float(ratio)
    ordered = sorted(uniq.items())
    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(['date', 'margin_ratio_pct'])
        for ts, ratio in ordered:
            w.writerow([_ts_to_date(ts).isoformat(), f'{ratio:.6f}'])
    return len(ordered)


def _fetch_github_bootstrap() -> List[Tuple[int, float]]:
    """相容舊版短歷史 CSV（afk13e43），僅作 bootstrap。"""
    url = 'https://raw.githubusercontent.com/afk13e43/Stock_Notice/main/history/tw_history.csv'
    out: List[Tuple[int, float]] = []
    try:
        _throttle()
        req = urllib.request.Request(url, headers=_UA)
        with urllib.request.urlopen(req, timeout=15) as resp:
            lines = resp.read().decode('utf-8').splitlines()
        reader = csv.DictReader(lines)
        for row in reader:
            d = _parse_ymd(row.get('date') or '')
            ratio = _fnum(row.get('margin_ratio_pct'))
            if d is None or ratio is None or ratio <= 0:
                continue
            out.append((_date_to_ts(d), float(ratio)))
    except Exception as e:
        print('[margin] github bootstrap failed:', e)
    return out


def _fetch_finmind_history(start: date, end: Optional[date] = None) -> List[Tuple[int, float]]:
    """可選：FINMIND_TOKEN → TaiwanTotalExchangeMarginMaintenance。"""
    token = (os.environ.get('FINMIND_TOKEN') or os.environ.get('FINMIND_API_TOKEN') or '').strip()
    if not token:
        return []
    end = end or date.today()
    url = (
        'https://api.finmindtrade.com/api/v4/data'
        f'?dataset=TaiwanTotalExchangeMarginMaintenance'
        f'&start_date={start.isoformat()}&end_date={end.isoformat()}'
        f'&token={urllib.parse.quote(token)}'
    )
    out: List[Tuple[int, float]] = []
    try:
        payload = _http_json(url, timeout=60)
        if payload.get('status') != 200:
            print('[margin] FinMind:', payload.get('msg'))
            return []
        for row in payload.get('data') or []:
            d = _parse_ymd(str(row.get('date') or ''))
            ratio = _fnum(row.get('TotalExchangeMarginMaintenance'))
            if d is None or ratio is None or ratio <= 0:
                continue
            out.append((_date_to_ts(d), float(ratio)))
    except Exception as e:
        print('[margin] FinMind fetch failed:', e)
    return out


def _trading_days_from_yahoo(start: date, end: date) -> List[date]:
    """用 ^TWII 日線 period1/period2 推交易日清單（避免 range=max 變稀疏）。"""
    p1 = int(datetime(start.year, start.month, start.day, tzinfo=TZ_TPE).timestamp()) - 86400
    p2 = int(datetime(end.year, end.month, end.day, tzinfo=TZ_TPE).timestamp()) + 86400
    url = (
        'https://query1.finance.yahoo.com/v8/finance/chart/%5ETWII'
        f'?interval=1d&period1={p1}&period2={p2}'
    )
    days: List[date] = []
    try:
        payload = _http_json(url, timeout=45)
        res = (payload.get('chart') or {}).get('result') or []
        if not res:
            # 後備：query2
            url2 = url.replace('query1', 'query2')
            payload = _http_json(url2, timeout=45)
            res = (payload.get('chart') or {}).get('result') or []
        if not res:
            return days
        for ts in res[0].get('timestamp') or []:
            d = datetime.fromtimestamp(int(ts), tz=TZ_TPE).date()
            if start <= d <= end:
                days.append(d)
    except Exception as e:
        print('[margin] yahoo calendar failed:', e)
    # 若 Yahoo 仍過稀，退回平日列舉
    if len(days) < max(10, (end - start).days // 10):
        print(f'[margin] yahoo calendar sparse ({len(days)}) — fallback weekdays')
        days = []
        cur = start
        while cur <= end:
            if cur.weekday() < 5:
                days.append(cur)
            cur += timedelta(days=1)
    return sorted(set(days))


def _existing_dates(ds) -> set:
    rows = ds.get_margin_ratio_bars() if hasattr(ds, 'get_margin_ratio_bars') else []
    return {_ts_to_date(ts) for ts, *_ in rows}


def _store_points(ds, points: Iterable[Tuple[int, float]]) -> int:
    rows = []
    for ts, ratio in points:
        if ratio is None or ratio <= 0:
            continue
        v = float(ratio)
        rows.append((int(ts), v, v, v, v, 0))
    if not rows:
        return 0
    return ds.upsert_bars(SYMBOL, MARKET, rows)


def ensure_seed_loaded(ds=None) -> int:
    """把本地 seed CSV 灌進 DB。若 seed 不存在／過短，不採用第三方短序列當權威，
    改以近期 TWSE 官方重算（分子不含 ETF）建立可用起點。"""
    global _seed_ensured, _seed_ensured_n
    # 同進程重複呼叫（多條 API / worker 初始化）只灌一次，避免刷屏與重複 upsert
    if _seed_ensured and _seed_ensured_n > 0:
        return _seed_ensured_n
    ds = ds or _import_datastore()
    ds.init_db()
    points = load_seed_csv(SEED_CSV)
    if len(points) < 60:
        print(f'[margin] seed shallow ({len(points)}) — computing recent TWSE history…')
        # 近 ~4 個月交易日快速建立可用圖（同時寫入 seed）
        end = datetime.now(TZ_TPE).date()
        start = end - timedelta(days=140)
        have = { _ts_to_date(ts) for ts, _ in points }
        calendar = _trading_days_from_yahoo(start, end)
        fresh: List[Tuple[int, float]] = list(points)
        for d in calendar:
            if d in have:
                continue
            ratio = compute_ratio_for_date(d)
            if ratio and ratio > 0:
                fresh.append((_date_to_ts(d), float(ratio)))
                have.add(d)
        if fresh:
            points = sorted({ts: r for ts, r in fresh}.items())
            save_seed_csv(points, SEED_CSV)
    if not points:
        return 0
    n = _store_points(ds, points)
    print(f'[margin] seed → DB {n} bars (file={SEED_CSV})')
    _seed_ensured = True
    _seed_ensured_n = n
    return n


def refresh_today(force: bool = False) -> Optional[float]:
    """刷新今日值（TTL 節流）。"""
    global _last_today_refresh
    now = time.time()
    if not force and (now - _last_today_refresh) < _TODAY_REFRESH_TTL:
        return None
    with _refresh_lock:
        if not force and (time.time() - _last_today_refresh) < _TODAY_REFRESH_TTL:
            return None
        sample = fetch_latest_ratio_live()
        _last_today_refresh = time.time()
        if sample:
            exchange_date, ratio = sample
        else:
            exchange_date, ratio = None, None
        if exchange_date is not None and ratio and ratio > 0:
            ds = _import_datastore()
            ds.init_db()
            _store_points(ds, [(_date_to_ts(exchange_date), ratio)])
            # 同步 append seed
            try:
                seed = dict(load_seed_csv(SEED_CSV))
                seed[_date_to_ts(exchange_date)] = ratio
                save_seed_csv(sorted(seed.items()), SEED_CSV)
            except Exception:
                pass
            print(f'[margin] latest session {exchange_date.isoformat()} = {ratio:.4f}%')
            return ratio
        return None


def backfill_history(
    start: Optional[date] = None,
    end: Optional[date] = None,
    resume: bool = True,
    max_days: Optional[int] = None,
    prefer_finmind: bool = True,
) -> dict:
    """
    歷史回補：
      - 預設 start=2001-01-05（TWSE/FinMind 資料起點）
      - resume=True 跳過 DB 已有日期
      - 先試 FinMind（有 token），再逐日 TWSE 計算缺口
    """
    ds = _import_datastore()
    ds.init_db()
    start = start or date(2001, 1, 5)
    end = end or datetime.now(TZ_TPE).date()

    if not _backfill_lock.acquire(blocking=False):
        return {'ok': False, 'error': 'backfill already running', 'state': dict(_backfill_state)}

    _backfill_state.update({
        'running': True, 'phase': 'init', 'done': 0, 'total': 0,
        'last_error': '', 'started_at': time.time(), 'finished_at': 0,
    })
    try:
        ensure_seed_loaded(ds)

        # FinMind 快路徑
        if prefer_finmind:
            _backfill_state['phase'] = 'finmind'
            fm = _fetch_finmind_history(start, end)
            if fm:
                _store_points(ds, fm)
                seed = dict(load_seed_csv(SEED_CSV))
                seed.update(fm)
                save_seed_csv(sorted(seed.items()), SEED_CSV)
                print(f'[margin] FinMind stored {len(fm)} points')

        have = _existing_dates(ds) if resume else set()
        calendar = _trading_days_from_yahoo(start, end)
        if not calendar:
            # 後備：逐日（含週末，compute 會因無資料回 None）
            calendar = []
            cur = start
            while cur <= end:
                if cur.weekday() < 5:
                    calendar.append(cur)
                cur += timedelta(days=1)

        todo = [d for d in calendar if d not in have]
        if max_days is not None:
            todo = todo[: max(0, int(max_days))]
        _backfill_state['total'] = len(todo)
        _backfill_state['phase'] = 'twse'
        print(f'[margin] TWSE backfill todo={len(todo)} (resume={resume}, {start}→{end})')

        ok = fail = 0
        batch_seed: List[Tuple[int, float]] = []
        for i, d in enumerate(todo, 1):
            _backfill_state['done'] = i
            ratio = compute_ratio_for_date(d)
            if ratio and ratio > 0:
                _store_points(ds, [(_date_to_ts(d), ratio)])
                batch_seed.append((_date_to_ts(d), ratio))
                ok += 1
            else:
                fail += 1
            if i % 20 == 0:
                if batch_seed:
                    seed = dict(load_seed_csv(SEED_CSV))
                    seed.update(batch_seed)
                    save_seed_csv(sorted(seed.items()), SEED_CSV)
                    batch_seed = []
                print(f'  ...{i}/{len(todo)} ok={ok} fail={fail}')

        if batch_seed:
            seed = dict(load_seed_csv(SEED_CSV))
            seed.update(batch_seed)
            save_seed_csv(sorted(seed.items()), SEED_CSV)

        # 今日
        _backfill_state['phase'] = 'today'
        refresh_today(force=True)

        rows = get_bars()
        _backfill_state['phase'] = 'done'
        return {
            'ok': True,
            'ok_days': ok,
            'fail_days': fail,
            'bars': len(rows),
            'first': _ts_to_date(rows[0][0]).isoformat() if rows else None,
            'last': _ts_to_date(rows[-1][0]).isoformat() if rows else None,
        }
    except Exception as e:
        _backfill_state['last_error'] = str(e)
        print('[margin] backfill failed:', e)
        return {'ok': False, 'error': str(e)}
    finally:
        _backfill_state['running'] = False
        _backfill_state['finished_at'] = time.time()
        _backfill_lock.release()


def backfill_margin_ratio(full: bool = False, max_days: Optional[int] = None) -> int:
    """
    相容舊 CLI / server 呼叫：
      - 預設：載入 seed + 刷新今日（快速）
      - full=True：啟動完整歷史回補（阻塞）
    """
    ds = _import_datastore()
    ds.init_db()
    ensure_seed_loaded(ds)
    if full:
        start = date(2001, 1, 5)
        backfill_history(start=start, resume=True, max_days=max_days)
    else:
        # 若歷史過短，背景提示；此處只保證 seed + 今日
        rows = get_bars()
        if len(rows) < 200:
            print('[margin] history shallow (<200) — run: python server/margin_ratio.py backfill --full')
        refresh_today(force=False)
    return len(get_bars())


def start_background_backfill(full: bool = False, max_days: Optional[int] = None):
    if _backfill_state.get('running'):
        return False
    try:
        import job_queue as jq
        if jq.is_busy('margin_ratio'):
            return False
    except Exception:
        jq = None

    if not _backfill_lock.acquire(blocking=False):
        return False
    _backfill_state['running'] = True
    _backfill_state['phase'] = 'queued'
    _backfill_state['started_at'] = time.time()

    def _run():
        try:
            _backfill_lock.release()
            if full:
                backfill_history(start=date(2001, 1, 5), resume=True, max_days=max_days)
            else:
                try:
                    _backfill_state['phase'] = 'seed+today'
                    ensure_seed_loaded()
                    refresh_today(force=False)
                finally:
                    _backfill_state['running'] = False
                    _backfill_state['phase'] = 'done'
                    _backfill_state['finished_at'] = time.time()
        except Exception as e:
            _backfill_state['last_error'] = str(e)
            _backfill_state['running'] = False
            print('[margin] bg backfill:', e)
            try:
                if _backfill_lock.locked():
                    _backfill_lock.release()
            except Exception:
                pass

    if jq is not None:
        r = jq.submit('margin_ratio', _run, meta={'full': full, 'max_days': max_days})
        if not r.get('queued'):
            # 還原佔位
            _backfill_state['running'] = False
            _backfill_state['phase'] = 'idle'
            try:
                if _backfill_lock.locked():
                    _backfill_lock.release()
            except Exception:
                pass
            return False
        return True
    threading.Thread(target=_run, daemon=True, name='margin-backfill').start()
    return True


def get_bars() -> List[Tuple]:
    ds = _import_datastore()
    ds.init_db()
    with closing(ds.get_conn()) as conn:
        cur = conn.execute(
            "SELECT ts, open, high, low, close, volume FROM bars "
            "WHERE symbol = ? ORDER BY ts",
            (SYMBOL,),
        )
        return cur.fetchall()


def get_bars_filtered(range_key: str = 'max') -> List[Tuple]:
    rows = get_bars()
    if not rows:
        return rows
    rk = (range_key or 'max').lower()
    days_map = {
        '5d': 5, '1d': 5, '1mo': 31, '3mo': 93, '6mo': 186,
        '1y': 366, '2y': 732, '5y': 1826, '10y': 3652, 'ytd': None, 'max': None,
    }
    if rk == 'ytd':
        y0 = date(datetime.now(TZ_TPE).year, 1, 1)
        ts0 = _date_to_ts(y0)
        return [r for r in rows if r[0] >= ts0]
    n = days_map.get(rk)
    if n is None:
        return rows
    cutoff = _date_to_ts(datetime.now(TZ_TPE).date() - timedelta(days=n))
    return [r for r in rows if r[0] >= cutoff]


def meta_summary() -> dict:
    rows = get_bars()
    if not rows:
        return {
            'symbol': SYMBOL,
            'name': '大盤融資維持率',
            'count': 0,
            'riskZones': RISK_ZONES,
            'formula': 'Σ(融資張數×1000×收盤價, 不含ETF) / 融資金額 × 100',
            'source': 'TWSE',
            'backfill': dict(_backfill_state),
        }
    closes = [r[4] for r in rows if r[4] is not None]
    cur = closes[-1]
    prev = closes[-2] if len(closes) >= 2 else cur
    zone = None
    for z in RISK_ZONES:
        if cur <= z['level']:
            zone = z
            break
    return {
        'symbol': SYMBOL,
        'name': '大盤融資維持率',
        'longName': '台灣加權・大盤融資維持率 (Margin Maintenance Ratio)',
        'count': len(rows),
        'firstDate': _ts_to_date(rows[0][0]).isoformat(),
        'lastDate': _ts_to_date(rows[-1][0]).isoformat(),
        'current': round(cur, 4),
        'previous': round(prev, 4),
        'delta': round(cur - prev, 4),
        'deltaPct': round((cur - prev) / prev * 100, 4) if prev else 0.0,
        'min': round(min(closes), 4),
        'max': round(max(closes), 4),
        'avg': round(sum(closes) / len(closes), 4),
        'riskZone': zone,
        'riskZones': RISK_ZONES,
        'formula': 'Σ(融資張數×1000×收盤價, 不含ETF) / 融資金額 × 100',
        'source': 'TWSE (MacroMicro-aligned)',
        'reference': 'https://www.macromicro.me/charts/53117/taiwan-taiex-maintenance-margin',
        'backfill': dict(_backfill_state),
    }


def chart_json(range_key: str = 'max') -> bytes:
    """Yahoo v8 相容 JSON（供 /yf/__MARGIN_RATIO__）。"""
    # 輕量更新：seed（若空）+ 今日 TTL
    rows = get_bars()
    if not rows:
        ensure_seed_loaded()
        start_background_backfill(full=True)
        rows = get_bars()
    else:
        # 不阻塞；背景刷新今日
        try:
            start_background_backfill(full=False)
        except Exception:
            pass

    rows = get_bars_filtered(range_key)
    if not rows:
        rows = get_bars()

    timestamps, opens, highs, lows, closes, volumes = [], [], [], [], [], []
    for ts, o, h, l, cl, v in rows:
        timestamps.append(int(ts))
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(cl)
        volumes.append(int(v or 0))

    last_px = closes[-1] if closes else None
    prev_close = closes[-2] if len(closes) >= 2 else last_px
    last_ts = timestamps[-1] if timestamps else int(time.time())
    first_ts = timestamps[0] if timestamps else int(time.time())

    res = {
        'chart': {
            'result': [{
                'meta': {
                    'currency': 'TWD',
                    'symbol': SYMBOL,
                    'exchangeName': 'TAI',
                    'instrumentType': 'INDEX',
                    'shortName': '大盤融資維持率',
                    'longName': '大盤融資維持率 (Margin Maintenance Ratio)',
                    'firstTradeDate': first_ts,
                    'regularMarketTime': last_ts,
                    'gmtoffset': 28800,
                    'timezone': 'TST',
                    'exchangeTimezoneName': 'Asia/Taipei',
                    'regularMarketPrice': last_px,
                    'regularMarketPreviousClose': prev_close,
                    'chartPreviousClose': prev_close,
                    'previousClose': prev_close,
                    'scale': 3,
                    'priceHint': 2,
                    'dataGranularity': '1d',
                    'range': range_key or 'max',
                    'validRanges': ['1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max'],
                },
                'timestamp': timestamps,
                'indicators': {
                    'quote': [{
                        'open': opens,
                        'high': highs,
                        'low': lows,
                        'close': closes,
                        'volume': volumes,
                    }]
                },
            }],
            'error': None,
        }
    }
    return json.dumps(res, ensure_ascii=False).encode('utf-8')


def _cli():
    args = sys.argv[1:]
    cmd = args[0] if args else 'status'
    if cmd in ('status', 'meta'):
        print(json.dumps(meta_summary(), ensure_ascii=False, indent=2))
    elif cmd == 'seed':
        n = ensure_seed_loaded()
        print('seed bars:', n)
    elif cmd == 'today':
        print(refresh_today(force=True))
    elif cmd == 'backfill':
        full = '--full' in args or 'full' in args
        max_days = None
        for i, a in enumerate(args):
            if a == '--max' and i + 1 < len(args):
                max_days = int(args[i + 1])
            if a.startswith('--start='):
                start = _parse_ymd(a.split('=', 1)[1])
                end = date.today()
                print(json.dumps(backfill_history(start=start, end=end, max_days=max_days), ensure_ascii=False, indent=2))
                return
        if full:
            print(json.dumps(backfill_history(max_days=max_days), ensure_ascii=False, indent=2))
        else:
            print('bars:', backfill_margin_ratio(full=False))
    elif cmd == 'compute':
        d = _parse_ymd(args[1]) if len(args) > 1 else date.today()
        print(d, compute_ratio_for_date(d))
    else:
        print('usage: status | seed | today | backfill [--full] [--max N] [--start=YYYY-MM-DD] | compute YYYY-MM-DD')


if __name__ == '__main__':
    _cli()
