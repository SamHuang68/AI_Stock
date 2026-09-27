"""研究品質與維護工作；持久狀態、共用佇列、離線每日留存。"""
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import datastore
import job_queue
import signal_stats_pool as pool
import stock_signals as ss
from atomic_store import atomic_write_json, load_json
import 每日個股留存 as daily

ROOT = Path(__file__).resolve().parents[1]
JOB = 'stock-research-maintenance'
_thread = None


def paths():
    data = Path(datastore.DB_PATH).parent
    return data / 'stock_research_maintenance.json', data / 'stock_daily_observations.sqlite3'


def inventory():
    with datastore.read_snapshot() as conn:
        bulk = datastore.get_bars_bulk(['^TWII'], connection=conn)
        benchmark = ss.normalize_bars(bulk.get('^TWII') or [])
        rows = conn.execute("SELECT symbol,max(ts) FROM bars WHERE market='TW' GROUP BY symbol").fetchall()
    latest = benchmark[-1]['date'] if benchmark else None
    eligible = [(s, ss.bar_date(ts)) for s, ts in rows if pool._TICKER_RE['TW'].match(s)]
    return {'benchmarkAsOf': latest, 'symbols': len(eligible),
            'alignedSymbols': sum(day == latest for _, day in eligible) if latest else 0,
            'olderSymbols': sum(day < latest for _, day in eligible) if latest else None,
            'note': '依本機指數已知交易日比較；不代表已核對官方休市表。'}


def status():
    state_path, ledger = paths()
    state = load_json(str(state_path), default={}, expected_type=dict)
    busy = job_queue.is_busy(JOB)
    if state.get('status') in ('queued', 'running') and not busy:
        state = {**state, 'status': 'interrupted', 'message': '上次工作未正常完成，可重新執行；原始資料保留。'}
    return {'running': busy, 'job': state, 'observations': daily.status(ledger),
            'inventory': inventory(), 'externalCallsOnRefresh': 0}


def run(*, enable_daily=False, download_sources=False, now=None):
    state_path, ledger = paths()
    injected_now = now
    now = now or datetime.now(ss._TZ['TW'])
    run_id = uuid.uuid4().hex
    state = {'runId': run_id, 'status': 'running', 'startedAt': now.isoformat(), 'steps': [], 'externalCalls': 0}
    trace_path = state_path.parent.parent / 'logs' / 'stock_research_maintenance.jsonl'
    trace_path.parent.mkdir(parents=True, exist_ok=True)

    def save(event, **details):
        state['updatedAt'] = datetime.now(ss._TZ['TW']).isoformat()
        atomic_write_json(str(state_path), state, backup=True)
        with trace_path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps({'at': state['updatedAt'], 'runId': run_id, 'event': event, **details}, ensure_ascii=False) + '\n')

    def step(name, action):
        item = {'label': name, 'status': 'running'}
        state['steps'].append(item)
        save('步驟開始', step=name)
        start = time.monotonic()
        try:
            detail = action()
        except Exception as exc:
            item.update(status='failed', error=type(exc).__name__)
            save('步驟失敗', step=name, error=type(exc).__name__)
            raise
        item.update(status='partial' if detail and detail.get('status') == 'partial' else 'completed',
                    elapsedSec=round(time.monotonic() - start, 2), detail=detail)
        save('步驟完成', step=name)
        return detail

    save('工作開始')
    try:
        if download_sources:
            state['externalCalls'] = '使用者同意本次 Yahoo／TWSE 來源更新'
            def sources():
                data = Path(datastore.DB_PATH).parent
                covered = load_json(str(data / 'stock_research_coverage.json'), default={}, expected_type=dict)
                latest = max(covered, default=None)
                start = datetime.strptime(latest, '%Y%m%d').date() if latest else (now - timedelta(days=14)).date()
                start = max(start, (now - timedelta(days=365)).date())
                logfile = trace_path.parent / ('stock_research_source_' + run_id + '.log')
                command = [sys.executable, '-B', str(ROOT / 'scripts/個股研究資料更新.py'),
                           '--start', str(start), '--end', str(now.date()), '--data-dir', str(data), '--adjustments']
                with logfile.open('w', encoding='utf-8') as handle:
                    done = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, timeout=10800,
                        env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1', 'ST_RESEARCH_PARENT_RUN': run_id})
                if done.returncode not in (0, 1):
                    raise RuntimeError('資料補齊程序未正常結束')
                return {'status': 'completed' if done.returncode == 0 else 'partial',
                        'reason': '來源補齊完成' if done.returncode == 0 else '部分來源未取得，保留缺漏並繼續檢查覆蓋'}
            step('補齊既有大盤、上市籌碼與還原來源', sources)
        step('檢查本機資料覆蓋', inventory)
        if enable_daily:
            step('啟用本機每日事件留存', lambda: daily.enable(ledger, injected_now))
        def recalculate():
            value = pool.refresh('TW')
            import stock_signals_routes
            stock_signals_routes.clear_cache()
            return {'symbols': value['symbols'], 'dataThrough': value['window']['to'],
                    'generatedAt': value['generatedAt'], 'selection': value['research']['selection'],
                    'adjustedSymbols': value.get('priceSensitivity', {}).get('coveredSymbols', 0)}
        step('重算歷史統計與還原成本研究', recalculate)
        step('追加當日觀察及成熟結果', lambda: capture(injected_now))
        partial = any(s['status'] == 'partial' for s in state['steps'])
        state.update(status='partial' if partial else 'completed',
                     message='部分來源仍缺資料；已完成本機重算，請核對覆蓋。' if partial else
                     '本機重算完成；請核對資料截止日，重算不代表外部資料已補齊。')
        save('工作完成')
        if enable_daily:
            start_daemon()
        return state
    except Exception as exc:
        state.update(status='failed', message='研究維護失敗；已完成步驟與既有結果保留。', error=type(exc).__name__)
        save('工作失敗', error=type(exc).__name__)
        raise


def submit(enable_daily=False, download_sources=False):
    return job_queue.submit(JOB, lambda: run(enable_daily=enable_daily, download_sources=download_sources),
                            meta={'scope': '本機研究', 'downloadSources': download_sources})


def capture(now=None):
    _, ledger = paths()
    if not ledger.exists():
        return {'status': 'disabled', 'reason': '尚未啟用每日留存'}
    chips = pool._load_all_chips(str(Path(datastore.DB_PATH).parent / 'chip_history'))
    with datastore.read_snapshot() as conn:
        benchmark = ss.normalize_bars(datastore.get_bars_bulk(['^TWII'], connection=conn).get('^TWII') or [])
        codes = datastore.list_symbols('TW', ss.MIN_BARS, connection=conn)
        return daily.capture(ledger, pool.iter_datastore('TW', symbols=codes, connection=conn), benchmark, chips, now=now)


def start_daemon():
    global _thread
    if not paths()[1].exists() or (_thread and _thread.is_alive()):
        return
    def loop():
        while True:
            current = datetime.now(ss._TZ['TW'])
            if current.weekday() < 5 and (current.hour, current.minute) >= (14, 0):
                try:
                    job_queue.submit('stock-daily-observation', capture, meta={'externalCalls': 0})
                except Exception:
                    pass  # 工作錯誤由 job_queue 留下記錄；下輪可重試，不更新完成狀態。
            time.sleep(600)
    _thread = threading.Thread(target=loop, name='stock-daily-observation', daemon=True)
    _thread.start()
