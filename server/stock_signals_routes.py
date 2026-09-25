# -*- coding: utf-8 -*-
"""HTTP boundary + 資料載入 for 個股訊號引擎（/stock-signals*）。

資料來源沿用既有管線，不另開新抓取：
* 日 K：``datastore``（本機 SQLite，與 /bars、選股、回測同一份）；缺資料或落後時才用
  ``datastore.fetch_yahoo_daily`` 增量補抓並寫回（與 /bars 相同行為）。
* 籌碼：``data/chip_history/<yyyymmdd>.json``（與 server._chip_streak 同源）。

盤中最後一根 K 只放在記憶體、標示「盤中暫定」，收盤後才寫回 DB，
避免把半根 K 永久存成日線。
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

try:
    from . import stock_signals as ss
    from .atomic_store import StoreCorruptError, atomic_write_json, load_json
    from .http_boundary import BodyReadError, read_json_body
except ImportError:
    import stock_signals as ss
    from atomic_store import StoreCorruptError, atomic_write_json, load_json
    from http_boundary import BodyReadError, read_json_body

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHIP_HISTORY_PATH = os.path.join(_BASE, 'data', 'chip_history')
WATCHLIST_FILE = os.path.join(_BASE, 'data', 'stock_signal_watchlist.json')

_SYM_RE = re.compile(r'^[A-Z0-9^][A-Z0-9.\-^]{0,14}$')
MAX_BATCH = 40
PUSH_MODES = ('off', 'digest', 'realtime')

# 交易時段（當地時間）：開盤、收盤、收盤後多久視為最終日 K
_SESSION = {
    'TW': ((9, 0), (13, 30), timedelta(minutes=30)),
    'US': ((9, 30), (16, 0), timedelta(minutes=30)),
}

_cache_lock = threading.Lock()
_cache: Dict[Tuple[str, str, bool], Tuple[float, Dict[str, Any]]] = {}
_remote_fail: Dict[Tuple[str, str], float] = {}   # 補抓失敗的 neg-cache：10 分鐘內直接用本機資料
REMOTE_FAIL_TTL = 600.0
_db_ready = False


def infer_market(sym: str, market: Optional[str] = None) -> str:
    m = (market or '').strip().upper()
    if m in ('TW', 'US'):
        return m
    s = (sym or '').strip().upper()
    return 'TW' if (s[:1].isdigit() or s.startswith('^TW')) else 'US'


def clean_symbol(sym: str) -> Optional[str]:
    s = (sym or '').strip().upper().replace('.TWO', '').replace('.TW', '')
    return s if _SYM_RE.match(s) else None


def _now_local(market: str, now: Optional[datetime] = None) -> datetime:
    tz = ss._TZ.get(market, ss._TZ['TW'])
    if now is None:
        return datetime.now(tz)
    return now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)


def session_state(market: str, last_bar_date: Optional[str],
                  now: Optional[datetime] = None) -> Dict[str, Any]:
    """最後一根 K 是否仍在盤中；以及目前應該看到的最新交易日（週末退回週五；假日無法得知，僅多抓一次）。"""
    local = _now_local(market, now)
    (oh, om), (ch, cm), settle = _SESSION.get(market, _SESSION['TW'])
    open_t = local.replace(hour=oh, minute=om, second=0, microsecond=0)
    final_t = local.replace(hour=ch, minute=cm, second=0, microsecond=0) + settle
    weekday = local.weekday() < 5
    today = local.date().isoformat()
    provisional = bool(weekday and last_bar_date == today and open_t <= local < final_t)
    expected = local.date()
    if not weekday or local < open_t:
        expected -= timedelta(days=1)
        while expected.weekday() >= 5:
            expected -= timedelta(days=1)
    return {'provisional': provisional, 'expectedLastDate': expected.isoformat(),
            'sessionOpen': bool(weekday and open_t <= local < final_t), 'localTime': local.isoformat()}


# ── 日 K 載入 ────────────────────────────────────────────────
def _datastore():
    global _db_ready
    import datastore
    if not _db_ready:
        datastore.init_db()
        _db_ready = True
    return datastore


def _fetch_remote(code: str, market: str, rng: str) -> List[tuple]:
    ds = _datastore()
    if market != 'TW' or code.startswith('^'):
        return ds.fetch_yahoo_daily(code, market, rng, retries=2)
    try:
        return ds.fetch_yahoo_daily(code, 'TW', rng, retries=2)
    except Exception:
        # 上櫃股 Yahoo 代號為 .TWO；datastore._yf_symbol 只補 .TW，這裡直接帶完整代號
        return ds.fetch_yahoo_daily(code + '.TWO', 'US', rng, retries=2)


def load_bars(code: str, market: str, *, allow_network: bool = True,
              now: Optional[datetime] = None) -> Dict[str, Any]:
    """回傳 {'bars': [...], 'source': 'local-db'|'local-db+yahoo', 'provisional': bool, 'error': str|None}"""
    ds = _datastore()
    rows = ds.get_bars(code, market=market)
    bars = ss.normalize_bars(rows, market)
    source = 'local-db'
    error = None
    last = bars[-1]['date'] if bars else None
    sess = session_state(market, last, now)
    need_full = len(bars) < 130
    behind = (last or '') < sess['expectedLastDate']
    live_extra: List[Dict[str, Any]] = []
    if allow_network and _remote_fail.get((code, market), 0) > time.time():
        allow_network = False
        error = '近 10 分鐘內無法連線更新日線，先使用本機資料'
    if allow_network and (need_full or behind or sess['sessionOpen']):
        gap_days = (date.fromisoformat(sess['expectedLastDate']) - date.fromisoformat(last)).days if last else 9999
        rng = '5y' if need_full or gap_days > 80 else ('3mo' if gap_days > 4 else '5d')
        try:
            fetched = _fetch_remote(code, market, rng)
        except Exception as exc:  # 網路失敗：保留本機資料並標示
            fetched = []
            error = f'無法連線更新日線（{type(exc).__name__}），使用本機資料'
            _remote_fail[(code, market)] = time.time() + REMOTE_FAIL_TTL
        if fetched:
            fresh = ss.normalize_bars(fetched, market)
            today = _now_local(market, now).date().isoformat()
            today_live = session_state(market, today, now)['provisional']
            # 盤中半根 K 不寫回 DB（收盤後的下一次抓取才寫入最終值）
            final_rows = [row for row in fetched
                          if not (today_live and ss.bar_date(row[0], market) == today)]
            if final_rows:
                ds.upsert_bars(code, market, final_rows)
                rows = ds.get_bars(code, market=market)
                bars = ss.normalize_bars(rows, market)
            if today_live and fresh and fresh[-1]['date'] == today:
                live_extra = [fresh[-1]]
            source = 'local-db+yahoo'
    if live_extra and (not bars or bars[-1]['date'] < live_extra[0]['date']):
        bars = bars + live_extra
    last = bars[-1]['date'] if bars else None
    sess = session_state(market, last, now)
    stale_days = ((date.fromisoformat(sess['expectedLastDate']) - date.fromisoformat(last)).days
                  if last else None)
    return {'bars': bars, 'source': source, 'provisional': sess['provisional'],
            'staleDays': max(0, stale_days) if stale_days is not None else None,
            'error': error}


def analyze_symbol(code: str, market: str, *, with_stats: bool = True,
                   allow_network: bool = True, now: Optional[datetime] = None,
                   bars_loader: Optional[Callable[..., Dict[str, Any]]] = None,
                   chip_dir: Optional[str] = None, use_cache: bool = True) -> Dict[str, Any]:
    """載入資料並產生體檢；結果依盤中／盤後分別快取 5／30 分鐘。"""
    key = (code, market, bool(with_stats))
    now_ts = time.time()
    if use_cache:
        with _cache_lock:
            hit = _cache.get(key)
        if hit and hit[0] > now_ts:
            return hit[1]
    loader = bars_loader or load_bars
    loaded = loader(code, market, allow_network=allow_network, now=now)
    chips = ss.load_chip_series(code, chip_dir or CHIP_HISTORY_PATH, 60) if market == 'TW' else []
    result = ss.analyze(loaded['bars'], symbol=code, market=market, chips=chips,
                        provisional_last=loaded.get('provisional', False), with_stats=with_stats)
    result['dataSource'] = loaded.get('source')
    result['staleDays'] = loaded.get('staleDays')
    if loaded.get('error'):
        result['dataWarning'] = loaded['error']
    result['generatedAt'] = datetime.now(ss._TZ['TW']).isoformat(timespec='seconds')
    ttl = 300 if loaded.get('provisional') else 1800
    if use_cache:
        with _cache_lock:
            _cache[key] = (now_ts + ttl, result)
            if len(_cache) > 400:
                for k in [k for k, v in _cache.items() if v[0] <= now_ts]:
                    _cache.pop(k, None)
    return result


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()
    _remote_fail.clear()


# ── 自選股清單（供收盤摘要／即時推播）───────────────────────
def load_watchlist() -> List[Dict[str, str]]:
    try:
        data = load_json(WATCHLIST_FILE, default={}, expected_type=dict)
    except StoreCorruptError:
        return []
    out = []
    for it in data.get('symbols') or []:
        code = clean_symbol(str((it or {}).get('sym') or ''))
        if code:
            out.append({'sym': code, 'market': infer_market(code, (it or {}).get('market'))})
    return out


def save_watchlist(items: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    seen, clean = set(), []
    for it in items[:200]:
        code = clean_symbol(str((it or {}).get('sym') or (it or {}).get('t') or ''))
        if not code or code.startswith('^') or code.startswith('__'):
            continue
        market = infer_market(code, (it or {}).get('market') or (it or {}).get('m'))
        if (code, market) in seen:
            continue
        seen.add((code, market))
        clean.append({'sym': code, 'market': market})
    atomic_write_json(WATCHLIST_FILE, {'symbols': clean,
                                       'updatedAt': datetime.now(ss._TZ['TW']).isoformat(timespec='seconds')},
                      backup=True, private=True)
    return clean


def _parse_batch(raw: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for part in (raw or '').split(','):
        part = part.strip()
        if not part:
            continue
        sym, _, mkt = part.partition(':')
        code = clean_symbol(sym)
        if code and (code, infer_market(code, mkt)) not in out:
            out.append((code, infer_market(code, mkt)))
    return out[:MAX_BATCH]


class StockSignalsRoutesMixin:
    def _stock_signals_query(self) -> Dict[str, List[str]]:
        return parse_qs(urlparse(self.path).query)

    def _handle_stock_signals(self):
        qs = self._stock_signals_query()
        code = clean_symbol((qs.get('sym') or qs.get('symbol') or [''])[0])
        if not code:
            self._err('sym query parameter is required', 400)
            return
        market = infer_market(code, (qs.get('market') or [''])[0])
        cache_only = (qs.get('cacheOnly') or ['0'])[0] == '1'
        try:
            result = analyze_symbol(code, market, allow_network=not cache_only)
        except Exception as exc:
            self._err(f'stock signals failed: {type(exc).__name__}', 500)
            return
        self._ok(json.dumps(result, ensure_ascii=False).encode('utf-8'))

    def _handle_stock_signals_batch(self):
        qs = self._stock_signals_query()
        items = _parse_batch((qs.get('syms') or [''])[0])
        if not items:
            self._err('syms query parameter is required (e.g. 2330,2454,AAPL:US)', 400)
            return

        def one(it):
            code, market = it
            try:
                return ss.compact(analyze_symbol(code, market, with_stats=False))
            except Exception as exc:
                return {'symbol': code, 'market': market, 'ok': False,
                        'reason': 'ERROR', 'message': type(exc).__name__}

        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(one, items))
        payload = {'contractVersion': ss.CONTRACT_VERSION, 'engine': ss.ENGINE_ID,
                   'items': rows, 'disclaimer': ss.DISCLAIMER}
        self._ok(json.dumps(payload, ensure_ascii=False).encode('utf-8'))

    def _handle_stock_signals_catalog(self):
        payload = {'contractVersion': ss.CONTRACT_VERSION, 'engine': ss.ENGINE_ID,
                   'minSample': ss.MIN_SAMPLE, 'horizons': list(ss.STAT_HORIZONS),
                   'signals': ss.catalog(), 'disclaimer': ss.DISCLAIMER}
        self._ok(json.dumps(payload, ensure_ascii=False).encode('utf-8'))

    def _handle_stock_signals_watchlist_post(self):
        try:
            body = read_json_body(self, max_bytes=64 * 1024)
        except BodyReadError as exc:
            self._err(str(exc), exc.status)
            return
        items = body.get('symbols') if isinstance(body, dict) else None
        if not isinstance(items, list):
            self._err('symbols must be a list', 400)
            return
        saved = save_watchlist(items)
        self._ok(json.dumps({'ok': True, 'count': len(saved)}).encode('utf-8'))

    def _handle_stock_signals_push_config_get(self):
        import signal_digest
        self._ok(json.dumps(signal_digest.status(), ensure_ascii=False).encode('utf-8'))

    def _handle_stock_signals_push_config_post(self):
        import signal_digest
        try:
            body = read_json_body(self, max_bytes=4096)
        except BodyReadError as exc:
            self._err(str(exc), exc.status)
            return
        mode = str((body or {}).get('mode') or '').strip()
        if mode not in PUSH_MODES:
            self._err('mode must be one of off / digest / realtime', 400)
            return
        try:
            signal_digest.set_mode(mode)
        except Exception as exc:
            self._err(f'save push config failed: {type(exc).__name__}', 500)
            return
        self._ok(json.dumps(signal_digest.status(), ensure_ascii=False).encode('utf-8'))

    def _handle_stock_signals_digest_preview(self):
        import signal_digest
        qs = self._stock_signals_query()
        market = infer_market('', (qs.get('market') or ['TW'])[0])
        try:
            text = signal_digest.build_digest(market, allow_network=False)
        except Exception as exc:
            self._err(f'digest preview failed: {type(exc).__name__}', 500)
            return
        self._ok(json.dumps({'market': market, 'text': text}, ensure_ascii=False).encode('utf-8'))
