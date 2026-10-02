"""使用者選定標的的受限回補；讀取不抓資料，寫入沿用首次價格契約。"""
import copy
import json
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

import datastore
import job_queue
from stock_signals import _TZ, bar_date

_lock = threading.RLock()
_active = None
_cancel = threading.Event()
RANGES = {'1mo': 31, '3mo': 93, '1y': 366, '3y': 1096, '5y': 1827}


class Cancelled(RuntimeError):
    pass


class Budget:
    def __init__(self, event, *, seconds=600, requests=240):
        self.event, self.ends, self.limit = event, time.monotonic() + seconds, requests
        self.used, self.last = 0, 0.0

    def check(self):
        if self.event.is_set():
            raise Cancelled('已取消；已完成月份保留，未完成月份可稍後重試')
        if self.remaining() <= 0:
            raise TimeoutError('本次更新已達十分鐘時間上限')

    def remaining(self):
        return max(0, self.ends - time.monotonic())

    def expired(self):
        self.check()
        return False

    def before_request(self):
        self.check()
        if self.used >= self.limit:
            raise RuntimeError('本次更新已達來源請求上限，請分段續補')
        self.event.wait(max(0, 1.2 - (time.monotonic() - self.last)))
        self.check()
        self.used += 1
        self.last = time.monotonic()

    def get_json(self, url):
        import hashlib
        self.before_request()
        if self.remaining() < 0.05:
            raise TimeoutError('剩餘時間不足以取得來源資料')
        with urlopen(Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}),
                     timeout=min(15, self.remaining())) as response:
            raw = response.read(12_000_001)
        self.check()
        if len(raw) > 12_000_000:
            raise ValueError('來源內容超出大小限制')
        return json.loads(raw), hashlib.sha256(raw).hexdigest()


def validate(body):
    if not isinstance(body, dict):
        raise ValueError('更新設定必須為物件')
    symbols = body.get('symbols')
    if not isinstance(symbols, list) or not 1 <= len(symbols) <= 5:
        raise ValueError('每次須明示選擇 1 至 5 個標的，不自動處理整份觀察清單')
    result = []
    for item in symbols:
        if not isinstance(item, dict):
            raise ValueError('標的須包含 symbol 與 market')
        symbol, market = str(item.get('symbol', '')).strip().upper(), item.get('market')
        if market not in ('TW', 'US') or not re.fullmatch(r'[A-Z0-9^.\-]{1,20}', symbol):
            raise ValueError('標的或市場格式無效')
        if market == 'US' and (symbol.endswith(('.TW', '.TWO')) or symbol in ('^TWII', '^TWOII', '^TWO', 'TXF', 'WTX')):
            raise ValueError('標的代號與所選市場不符')
        symbol = symbol.removesuffix('.TW').removesuffix('.TWO') if market == 'TW' else symbol
        if market == 'TW' and not re.fullmatch(r'\d{4,6}[A-Z]?', symbol):
            raise ValueError('台股更新僅接受股票或 ETF 代號')
        if market == 'US' and not re.fullmatch(r'\^?[A-Z][A-Z0-9.\-]{0,18}', symbol):
            raise ValueError('美股代號格式無效')
        row = {'symbol': symbol, 'market': market}
        if row not in result:
            result.append(row)
    period = body.get('range', '1y')
    kind = body.get('kind', 'history')
    if not isinstance(period, str) or period not in RANGES or kind not in ('history', 'official'):
        raise ValueError('更新範圍或來源類型無效')
    if kind == 'official' and (len(result) != 1 or result[0]['market'] != 'TW' or not re.fullmatch(r'\d{4}', result[0]['symbol']) or period not in ('1y', '3y', '5y')):
        raise ValueError('官方研究每次只核對一個上市四碼標的與 1／3／5 年；上櫃／其他商品涵蓋尚未支援')
    return result, period, kind


def status():
    with _lock:
        return copy.deepcopy(_active) if _active else {'status': 'idle', 'cacheOnly': True}


def cancel(job_id):
    with _lock:
        if not _active or _active['jobId'] != job_id or _active['status'] not in ('queued', 'running'):
            raise ValueError('沒有符合的進行中工作')
        _cancel.set()
        if _active['status'] == 'queued':
            _active.update(status='cancelled', error='已取消排隊工作；不再取得來源或寫入資料', finishedAt=time.time(), sourceRequests=0)
            return {'ok': True, 'jobId': job_id, 'status': 'cancelled', 'message': _active['error']}
        _active['status'] = 'cancelling'
        return {'ok': True, 'jobId': job_id, 'status': 'cancelling', 'message': '等待目前來源請求結束，最長約 20 秒；回傳後不再寫入該批次'}


def _run(symbols, period, kind, budget, job_id):
    global _active
    with _lock:
        if not _active or _active['jobId'] != job_id or _active['status'] == 'cancelled':
            return
        _active['status'] = 'running'
    final_status, error = 'completed', None
    try:
        budget.check()
        datastore.init_db()
        for item in symbols:
            budget.check()
            symbol, market = item['symbol'], item['market']
            if kind == 'official':
                from 台股日線 import seed_research
                result = seed_research(Path(datastore.DB_PATH), symbol, int(period[:-1]), fetch=budget.get_json, check=budget.check)
            else:
                now = datetime.now(_TZ[market])
                cutoff = now.date() if (now.hour, now.minute) >= ((18, 0) if market == 'TW' else (16, 30)) else now.date() - timedelta(days=1)
                start = cutoff - timedelta(days=RANGES[period])
                with datastore.read_snapshot() as conn:
                    covered = conn.execute('SELECT start_date,end_date FROM bar_fetch_coverage WHERE market=? AND symbol=? AND source=? AND start_date<=? ORDER BY end_date DESC LIMIT 1',
                                           (market, symbol, 'Yahoo Finance', start.isoformat())).fetchone()
                if covered and covered[1] >= cutoff.isoformat():
                    result = {'symbol': symbol, 'market': market, 'reused': True, 'inserted': 0,
                              'queryCoverage': list(covered), 'coverageMeaning': '曾成功取得的來源查詢期間；不保證停牌或缺日已補齊'}
                else:
                    # 已有足夠深度只從最後日期前七天續補，避免固定一個月留下缺口。
                    query_start = max(start, datetime.fromisoformat(covered[1]).date() - timedelta(days=7)) if covered else start
                    start_ts = int(datetime.combine(query_start, datetime.min.time(), _TZ[market]).timestamp())
                    rows = datastore.fetch_yahoo_daily(symbol, market, period, retries=1, start_ts=start_ts, deadline=budget)
                    budget.check()
                    rows = [r for r in rows if query_start.isoformat() <= bar_date(r[0], market) <= cutoff.isoformat()]
                    if not rows:
                        raise ValueError('來源沒有已完成的日線；未寫入')
                    result = datastore.merge_source_bars(symbol, market, rows, 'Yahoo Finance', check=budget.check,
                                                         fetched_range=(start.isoformat(), cutoff.isoformat()))
            with _lock:
                _active['results'].append(result)
                _active['completed'] += 1
    except Cancelled as exc:
        final_status, error = 'cancelled', str(exc)
    except Exception as exc:
        final_status, error = ('cancelled' if budget.event.is_set() else 'failed'), str(exc)[:240]
    finally:
        with _lock:
            if _active and _active['jobId'] == job_id:
                _active.update(status=final_status, error=error, finishedAt=time.time(), sourceRequests=budget.used)


def submit(body):
    global _active, _cancel
    symbols, period, kind = validate(body)
    with _lock:
        if _active and _active['status'] in ('queued', 'running', 'cancelling'):
            return {'ok': False, 'reason': 'busy', **status()}
        _cancel = threading.Event()
        _active = {'jobId': uuid.uuid4().hex, 'status': 'queued', 'symbols': symbols, 'range': period,
                   'kind': kind, 'source': 'TWSE' if kind == 'official' else 'Yahoo Finance',
                   'createdAt': time.time(), 'completed': 0, 'results': [], 'error': None,
                   'limits': {'symbols': 5, 'years': 5, 'seconds': 600, 'officialRequests': 240},
                   'policy': '沿用首次價格；來源修訂另存；不自動更新整份觀察清單'}
        budget = Budget(_cancel)
        job_id = _active['jobId']
        queued = job_queue.submit('selected-daily-cache:' + job_id, lambda: _run(symbols, period, kind, budget, job_id))
        if not queued['ok']:
            _active.update(status='failed', error='共用工作佇列忙碌，請稍後重試')
        return {'ok': queued['ok'], **status()}
