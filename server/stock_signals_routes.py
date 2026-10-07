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
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

try:
    from . import stock_signals as ss
    from .atomic_store import StoreCorruptError, atomic_write_json, load_json
    from .http_boundary import BodyReadError, read_json_body
    from .deadline import BoundedExecutor, Deadline
except ImportError:
    import stock_signals as ss
    from atomic_store import StoreCorruptError, atomic_write_json, load_json
    from http_boundary import BodyReadError, read_json_body
    from deadline import BoundedExecutor, Deadline

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHIP_HISTORY_PATH = os.path.join(_BASE, 'data', 'chip_history')
WATCHLIST_FILE = os.path.join(_BASE, 'data', 'stock_signal_watchlist.json')

_SYM_RE = re.compile(r'^[A-Z0-9^][A-Z0-9.\-^]{0,14}$')
MAX_BATCH = 40
PUSH_MODES = ('off', 'digest', 'realtime')

# 交易時段（當地時間）：開盤、收盤、收盤後多久視為最終日 K
_SESSION = ss.DAILY_SESSIONS

_cache_lock = threading.Lock()
_cache: Dict[Tuple[str, str, bool], Tuple[float, Dict[str, Any]]] = {}
_remote_fail: Dict[Tuple[str, str], float] = {}   # 補抓失敗的 neg-cache：10 分鐘內直接用本機資料
REMOTE_FAIL_TTL = 600.0
REMOTE_FETCH_SECONDS = 8.0
_remote_pool = BoundedExecutor(max_workers=4, max_in_flight=4, prefix='stock-health-source')


class SourceBusyError(TimeoutError):
    """本機來源工作額滿；不代表上游失聯，不記入失聯負快取。"""


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
    """依市場共用已核對日曆，避免假日／半日收市誤判新鮮度。"""
    if market == 'US':
        try:
            from .us_equity_calendar import session_state as us_state
        except ImportError:
            from us_equity_calendar import session_state as us_state
        return us_state(last_bar_date, _now_local(market, now))
    try:
        from .台股交易參考 import session
    except ImportError:
        from 台股交易參考 import session
    local = _now_local(market, now)
    (oh, om), (ch, cm), settle = _SESSION.get(market, _SESSION['TW'])
    open_t = local.replace(hour=oh, minute=om, second=0, microsecond=0)
    final_t = local.replace(hour=ch, minute=cm, second=0, microsecond=0) + settle
    def closed(day):
        return session(day)['status'] == 'closed' if market == 'TW' else day.weekday() >= 5
    calendar = session(local.date()) if market == 'TW' else None
    weekday = not closed(local.date())
    today = local.date().isoformat()
    if calendar and calendar['status'] == 'unknown':
        return {'provisional': last_bar_date == today, 'expectedLastDate': None,
                'sessionOpen': False, 'calendar': calendar, 'localTime': local.isoformat()}
    provisional = bool(weekday and last_bar_date == today and open_t <= local < final_t)
    expected = local.date()
    if not weekday or local < open_t:
        expected -= timedelta(days=1)
        while closed(expected):
            expected -= timedelta(days=1)
    expected_known = market != 'TW' or session(expected)['status'] != 'unknown'
    return {'provisional': provisional, 'expectedLastDate': expected.isoformat() if expected_known else None,
            'sessionOpen': bool(weekday and open_t <= local < final_t and
                                (calendar is None or calendar['status'] == 'scheduled')),
            'calendar': calendar, 'localTime': local.isoformat()}


# ── 日 K 載入 ────────────────────────────────────────────────
def _datastore():
    # server.py 在接收請求前完成 schema／備份；讀取體檢不可再次等待全域寫鎖。
    # 腳本呼叫者亦須先在啟動／維護邊界初始化，不能以 GET 隱式建表或遷移。
    import datastore
    return datastore


def _fetch_remote(code: str, market: str, rng: str) -> List[tuple]:
    ds = _datastore()
    deadline = Deadline(REMOTE_FETCH_SECONDS)
    future = _remote_pool.submit(ds.fetch_yahoo_daily, code, market, rng, retries=2, deadline=deadline)
    if future is None:
        raise SourceBusyError('行情更新工作繁忙')
    done, _ = wait([future], timeout=deadline.remaining())
    if future not in done:
        # 瀏覽器取消無法停止阻塞中的來源連線。限制等待時間及背景工作數，
        # 遲到的來源結果不再交回載入流程，因此不會寫入資料庫。
        future.cancel()
        _remote_pool.note_timeouts(1)
        raise TimeoutError('行情更新超過本次時間預算')
    try:
        return future.result()
    except TimeoutError as exc:
        raise TimeoutError('行情來源逾時') from exc


def load_bars(code: str, market: str, *, allow_network: bool = True,
              now: Optional[datetime] = None) -> Dict[str, Any]:
    """回傳 {'bars': [...], 'source': 'local-db'|'local-db+yahoo', 'provisional': bool, 'error': str|None}"""
    ds = _datastore()
    rows = ds.get_bars(code, market=market)
    bars = ss.normalize_bars(rows, market)
    source = 'local-db'
    error = None
    retry_soon = False
    last = bars[-1]['date'] if bars else None
    sess = session_state(market, last, now)
    expected = sess['expectedLastDate']
    if expected is None:
        error = '尚無該年度官方交易日曆；資料新鮮度待確認，不以平日推定落後'
    need_full = len(bars) < 130
    behind = expected is not None and (last or '') < expected
    live_extra: List[Dict[str, Any]] = []
    if allow_network and _remote_fail.get((code, market), 0) > time.time():
        allow_network = False
        retry_soon = True
        error = '最近一次行情更新未完成，暫用本機資料；重試間隔10分鐘'
    if allow_network and (need_full or behind or sess['sessionOpen']):
        gap_days = (date.fromisoformat(expected) - date.fromisoformat(last)).days if last and expected else 9999
        rng = '5y' if need_full or gap_days > 80 else ('3mo' if gap_days > 4 else '5d')
        try:
            fetched = _fetch_remote(code, market, rng)
        except Exception as exc:  # 網路失敗：保留本機資料並標示
            fetched = []
            retry_soon = isinstance(exc, TimeoutError)
            error = (f'{exc}，先使用本機資料；請核對資料日期'
                     if isinstance(exc, TimeoutError) else
                     f'無法連線更新日線（{type(exc).__name__}），使用本機資料')
            if not isinstance(exc, SourceBusyError):
                _remote_fail[(code, market)] = time.time() + REMOTE_FAIL_TTL
        if fetched:
            fresh = ss.normalize_bars(fetched, market)
            today = _now_local(market, now).date().isoformat()
            today_live = session_state(market, today, now)['provisional']
            # 盤中半根 K 不寫回 DB（收盤後的下一次抓取才寫入最終值）
            final_rows = [row for row in fetched
                          if not (today_live and ss.bar_date(row[0], market) == today)]
            if market == 'US':
                try:
                    from .us_equity_calendar import session as us_session
                except ImportError:
                    from us_equity_calendar import session as us_session
                final_rows = [row for row in final_rows if ss.bar_date(row[0], market)
                              and us_session(ss.bar_date(row[0], market))['status'] != 'closed']
            if final_rows:
                ds.upsert_bars(code, market, final_rows, source='Yahoo Finance')
                rows = ds.get_bars(code, market=market)
                bars = ss.normalize_bars(rows, market)
            if today_live and fresh and fresh[-1]['date'] == today:
                live_extra = [fresh[-1]]
            source = 'local-db+yahoo'
            revision = ds.source_revision_status(code, market)
            if revision['count']:
                error = '來源有歷史修訂，首次日線已保留；價格基準仍須核對，不以新來源靜默覆寫'
    if live_extra and (not bars or bars[-1]['date'] < live_extra[0]['date']):
        bars = bars + live_extra
    last = bars[-1]['date'] if bars else None
    sess = session_state(market, last, now)
    stale_days = ((date.fromisoformat(sess['expectedLastDate']) - date.fromisoformat(last)).days
                  if last and sess['expectedLastDate'] else None)
    return {'bars': bars, 'source': source, 'provisional': sess['provisional'],
            'staleDays': max(0, stale_days) if stale_days is not None else None,
            'error': error, 'retrySoon': retry_soon, 'session': sess}


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
    if with_stats and result.get('ok'):
        try:
            import signal_stats_pool as pool
            pool.attach(result, pool.load_cached(market))
        except Exception:
            pass   # 合併統計是加值資訊；快取壞掉不影響個股體檢
    if loaded.get('session'):
        result.setdefault('session', {}).update(loaded['session'])
        if market == 'US' and (loaded['session'].get('calendar') or {}).get('status') == 'unknown':
            result['session']['note'] = ('交易日曆待確認：當日日線尚不能標為最終值。'
                                        if loaded['session'].get('provisional') else
                                        '交易日曆待確認：保留最後已知日線，最新應有交易日尚不能確認。')
    result['dataSource'] = loaded.get('source')
    result['staleDays'] = loaded.get('staleDays')
    if loaded.get('error'):
        result['dataWarning'] = loaded['error']
    result['generatedAt'] = datetime.now(ss._TZ['TW']).isoformat(timespec='seconds')
    try:
        from 個股資料品質 import assess
        import signal_stats_pool as pool
        import datastore as ds
        with ds.read_snapshot() as connection:
            benchmark_code = '^TWII' if market == 'TW' else '^GSPC'
            raw = ds.get_bars_bulk([benchmark_code], market=market, connection=connection).get(benchmark_code) or []
        result['dataQuality'] = assess(result, ss.normalize_bars(raw, market), pool.load_cached(market), now)
    except Exception:
        result['dataQuality'] = {'status': 'unknown', 'label': '資料品質待確認', 'items': [],
                                 'notes': ['本機品質資料無法讀取；不代表資料已齊全。']}
    ttl = 300 if loaded.get('provisional') else 1800
    # 來源逾時／額滿及負快取期間的結果只短暫快取，避免再次延長降級結果。
    if loaded.get('retrySoon'):
        ttl = min(ttl, 60)
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
        started = time.perf_counter()
        try:
            result = dict(analyze_symbol(code, market, allow_network=not cache_only))
            # 與瀏覽器端總耗時區分，供下次定點驗收判斷排隊／傳輸或來源處理。
            # 不修改共用分析快取，也不把此時間稱為完整 HTTP 往返。
            result['requestTiming'] = {
                'serverElapsedMs': round((time.perf_counter() - started) * 1000, 3),
                'scope': 'handler-to-payload',
            }
        except Exception as exc:
            self._err(f'stock signals failed: {type(exc).__name__}', 500)
            return
        self._ok(json.dumps(result, ensure_ascii=False).encode('utf-8'))

    def _handle_stock_signals_batch(self):
        qs = self._stock_signals_query()
        cache_only = (qs.get('cacheOnly') or ['0'])[0] == '1'
        items = _parse_batch((qs.get('syms') or [''])[0])
        if not items:
            self._err('syms query parameter is required (e.g. 2330,2454,AAPL:US)', 400)
            return

        def one(it):
            code, market = it
            try:
                result = analyze_symbol(code, market, with_stats=False, allow_network=not cache_only,
                                        use_cache=not cache_only)
                row = ss.compact(result)
                row['eventReview'] = [{key: event.get(key) for key in (
                    'signalId', 'label', 'direction', 'date', 'barsAgo', 'status', 'statusLabel',
                    'statusDate', 'provisional', 'detail', 'plain', 'rule', 'audit', 'invalidation', 'evidenceId')}
                    for event in result.get('events', [])]
                for key in ('dataQuality', 'dataSource', 'dataWarning'):
                    row[key] = result.get(key)
                return row
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
        ai_digest = (body or {}).get('aiDigest')
        try:
            signal_digest.set_mode(mode, ai_digest=None if ai_digest is None else bool(ai_digest))
        except Exception as exc:
            self._err(f'save push config failed: {type(exc).__name__}', 500)
            return
        self._ok(json.dumps(signal_digest.status(), ensure_ascii=False).encode('utf-8'))

    def _handle_stock_signals_explain(self):
        """POST {sym, market}：AI 白話解讀（只引用體檢證據，逐句驗證；無 Key 或失敗回規則模板）。"""
        import ai_api
        import signal_narrative
        try:
            body = read_json_body(self, max_bytes=4096)
        except BodyReadError as exc:
            self._err(str(exc), exc.status)
            return
        code = clean_symbol(str((body or {}).get('sym') or ''))
        if not code:
            self._err('sym is required', 400)
            return
        market = infer_market(code, (body or {}).get('market'))
        try:
            result = analyze_symbol(code, market, allow_network=False)
            narrative = signal_narrative.explain(result, ai_api.load_ai_key())
        except Exception as exc:
            self._err(f'explain failed: {type(exc).__name__}', 500)
            return
        if narrative.get('source') == 'claude':
            try:
                import postmarket_report
                import wavedeck_bus as wdb
                usage = narrative.get('usage') or {}
                wdb.record_st_cloud(usd=postmarket_report.estimate_cost_usd(
                    narrative.get('model') or '', usage.get('input_tokens') or 0,
                    usage.get('output_tokens') or 0), calls=1)
            except Exception:
                pass
        self._ok(json.dumps(narrative, ensure_ascii=False).encode('utf-8'))

    def _handle_stock_signals_pooled(self):
        import job_queue
        import signal_stats_pool as pool
        qs = self._stock_signals_query()
        market = infer_market('', (qs.get('market') or ['TW'])[0])
        cached = pool.load_cached(market)
        payload = {
            'market': market, 'available': bool(cached),
            'running': job_queue.is_busy(pool.JOB_PREFIX + market),
            'minSample': pool.POOLED_MIN_SAMPLE, 'minSymbols': pool.MIN_SYMBOLS,
        }
        if cached:
            payload.update({k: cached.get(k) for k in
                            ('generatedAt', 'symbols', 'window', 'method', 'caveats', 'elapsedSec', 'priceSensitivity')})
            payload['scoreboard'] = pool.scoreboard(cached)
            research = cached.get('research') or {}
            payload['research'] = {k: research.get(k) for k in ('version', 'policy', 'selection', 'limitations', 'benchmarkCoverage', 'rsiRebound')}
        self._ok(json.dumps(payload, ensure_ascii=False).encode('utf-8'))

    def _handle_stock_research_status(self):
        import 個股研究維護 as maintenance
        try:
            if (self._stock_signals_query().get('comparison') or ['0'])[0] == '1':
                import 個股前瞻對照 as comparison
                import signal_stats_pool as pool
                payload = comparison.read_report(maintenance.paths()[1], pool.load_cached('TW'))
                self._ok(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
                return
            before = (self._stock_signals_query().get('reportBefore') or [None])[0]
            if before is not None and (len(before) > 19 or not before.isdecimal() or not 0 < int(before) < 9223372036854775807):
                self._err('報告分頁位置無效', 400)
                return
            self._ok(json.dumps(maintenance.status(int(before) if before else None), ensure_ascii=False).encode('utf-8'))
        except Exception as exc:
            self._err('研究狀態讀取失敗：' + type(exc).__name__, 500)

    def _handle_stock_research_refresh(self):
        import 個股研究維護 as maintenance
        try:
            body = read_json_body(self, max_bytes=4096)
        except BodyReadError as exc:
            self._err(str(exc), exc.status)
            return
        if isinstance(body, dict) and 'checkEvidence' in body:
            if body['checkEvidence'] is not True or len(body) != 1:
                self._err('證據檢查須單獨指定且為真', 400)
                return
            self._ok(json.dumps(maintenance.submit_evidence(), ensure_ascii=False).encode('utf-8'))
            return
        if isinstance(body, dict) and 'setSchedule' in body:
            if not isinstance(body['setSchedule'], bool):
                self._err('每日更新設定必須是布林值', 400)
                return
            self._ok(json.dumps(maintenance.configure_schedule(body['setSchedule']), ensure_ascii=False).encode('utf-8'))
            return
        if not isinstance(body, dict) or any(not isinstance(body.get(k, False), bool) for k in ('enableDaily', 'downloadSources')):
            self._err('每日留存設定必須是布林值', 400)
            return
        self._ok(json.dumps(maintenance.submit(body.get('enableDaily', False), body.get('downloadSources', False)), ensure_ascii=False).encode('utf-8'))

    def _handle_stock_signals_pooled_refresh(self):
        import job_queue
        import signal_stats_pool as pool
        try:
            body = read_json_body(self, max_bytes=4096)
        except BodyReadError as exc:
            self._err(str(exc), exc.status)
            return
        market = infer_market('', (body or {}).get('market') or 'TW')

        def job():
            pool.refresh(market)
            clear_cache()   # 讓下一次個股體檢帶上新的合併統計

        res = job_queue.submit(pool.JOB_PREFIX + market, job, meta={'market': market})
        self._ok(json.dumps({'market': market, **res}, ensure_ascii=False).encode('utf-8'))

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
