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
from 台股交易參考 import session, instrument

ROOT = Path(__file__).resolve().parents[1]
JOB = 'stock-research-maintenance'
REPORT_JOB = 'stock-evidence-report'
_thread = None


def schedule_status():
    data = Path(datastore.DB_PATH).parent
    config = load_json(str(data / 'stock_daily_schedule.json'), default={}, expected_type=dict)
    return {'enabled': config.get('enabled') is True, 'consentAt': config.get('consentAt'),
            'times': ['18:30', '19:30', '20:30'], 'scope': 'TWSE／TPEx 官方批次日線及法人、Yahoo 大盤日線',
            'lastSources': load_json(str(data / 'stock_daily_sources.json'), default={}, expected_type=dict)}


def configure_schedule(enabled):
    if not isinstance(enabled, bool):
        raise ValueError('每日來源更新設定必須是布林值')
    data = Path(datastore.DB_PATH).parent
    config = {'enabled': enabled, 'consentAt': datetime.now(ss._TZ['TW']).isoformat(),
              'scope': schedule_status()['scope'], 'source': '擁有者明確設定',
              'paidModelCalls': False, 'uploadLedger': False}
    atomic_write_json(str(data / 'stock_daily_schedule.json'), config, backup=True)
    if enabled:
        daily.enable(paths()[1])
        start_daemon()
    return schedule_status()


def scheduled_update(day):
    # 已排隊但使用者隨後停用的工作不再外送。
    if not schedule_status()['enabled']:
        return {'status': 'disabled'}
    import 個股每日資料 as sources
    try:
        result = sources.run(day)
        observed = capture()
    except Exception as exc:
        try:
            check_evidence(recalculate=True, errors=['每日來源更新或留存失敗：' + type(exc).__name__])
        except Exception:
            import logging
            logging.getLogger(__name__).exception('來源失敗後的證據回報已失敗')
        raise
    # 來源部分完成也產生報告；重算只讀本機，不增加來源或模型呼叫。
    check_evidence(recalculate=True)
    return {'sources': result, 'observations': observed}


def schedule_tick(current):
    """持久的每日三次時段；重新啟動也不重複無界外送。"""
    config = schedule_status()
    if not config['enabled'] or session(current.date())['status'] != 'scheduled':
        return False
    if current.hour >= 21:
        return False
    minutes = current.hour * 60 + current.minute
    slots = [value for value in (18 * 60 + 30, 19 * 60 + 30, 20 * 60 + 30) if value <= minutes]
    if not slots:
        return False
    if config['lastSources'].get('sessionDate') == current.date().isoformat() and config['lastSources'].get('status') == 'completed':
        return False
    key = current.date().isoformat() + '/' + str(slots[-1])
    filename = Path(datastore.DB_PATH).parent / 'stock_daily_attempts.json'
    attempts = load_json(str(filename), default={}, expected_type=dict)
    if key in attempts:
        return False
    # 先留下時段收據再交佇列，避免工作已外送、程序重啟卻還沒有收據。
    attempts[key] = {'queuedAt': current.isoformat(), 'run': 'stock-daily-sources', 'status': 'reserved'}
    atomic_write_json(str(filename), attempts, backup=True)
    submitted = job_queue.submit('stock-daily-sources', lambda: scheduled_update(current.date().isoformat()),
                                 meta={'sessionDate': current.date().isoformat(), 'consentAt': config['consentAt']})
    if submitted.get('queued'):
        attempts[key]['status'] = 'queued'
        atomic_write_json(str(filename), attempts, backup=True)
        return True
    return False


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
    today = datetime.now(ss._TZ['TW']).date().isoformat()
    known = [{**instrument(s, today), 'localAsOf': day,
              'sourceDateConflict': day >= instrument(s, today)['stopDate']}
             for s, day in eligible if instrument(s, today)]
    return {'benchmarkAsOf': latest, 'symbols': len(eligible),
            'alignedSymbols': sum(day == latest for _, day in eligible) if latest else 0,
            'olderSymbols': sum(day < latest for _, day in eligible) if latest else None,
            'calendar': session(today), 'knownInactive': known,
            'note': '對齊數保留全部本機股票；已知終止交易另列，不當成一般資料延遲。日曆僅涵蓋已核對的年度與臨時休市。'}


def report_path():
    return Path(datastore.DB_PATH).parent / 'stock_evidence_reports.sqlite3'


def status(report_before=None):
    state_path, ledger = paths()
    state = load_json(str(state_path), default={}, expected_type=dict)
    busy = job_queue.is_busy(JOB)
    if state.get('status') in ('queued', 'running') and not busy:
        state = {**state, 'status': 'interrupted', 'message': '上次工作未正常完成，可重新執行；原始資料保留。'}
    import 證據限制回報 as reports
    report = reports.read_reports(report_path(), report_before)
    report.update(running=job_queue.is_busy(REPORT_JOB), dailyTime='20:40',
                  note='來源更新後檢查；每日20:40起於下一次背景檢查結報（約10分鐘內，工作繁忙時依序排隊），需主機運行。歷史報告完整保留。')
    return {'running': busy, 'job': state, 'observations': daily.status(ledger), 'evidenceReports': report,
            'schedule': schedule_status(), 'sourceRevisions': datastore.source_revision_status(),
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
        step('驗證三項證據限制並留下報告', lambda: check_evidence(now=injected_now))
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


def check_evidence(*, recalculate=False, nightly_day=None, now=None, errors=None):
    """同一佇列內執行，報告失敗會留存；不啟動外部擷取。"""
    import 證據限制回報 as reports
    now = now or datetime.now(ss._TZ['TW'])
    if now.tzinfo is None:
        raise ValueError('回報時間須含時區')
    now = now.astimezone(ss._TZ['TW'])
    errors = list(errors or [])
    cache_file = str(Path(datastore.DB_PATH).parent / 'stock_signal_pooled_stats.json')
    try:
        if recalculate:
            pool.refresh('TW', chip_dir=str(Path(datastore.DB_PATH).parent / 'chip_history'), cache_file=cache_file)
            import stock_signals_routes
            stock_signals_routes.clear_cache()
    except Exception as exc:
        errors.append('本機研究重算失敗：' + type(exc).__name__ + '；保留上次結果並標示此次失敗。')
    cached = pool.load_cached('TW', cache_file=cache_file)
    try:
        with datastore.read_snapshot() as conn:
            inv, sessions = reports.collect_inventory(conn, now)
        observations = reports.forward_status(paths()[1], sessions)
        revisions = datastore.source_revision_status()
    except Exception as exc:
        errors.append('本機證據讀取失敗：' + type(exc).__name__)
        inv, observations, revisions = {}, {}, {}
    report = reports.build_report(cached, inv, observations, schedule_status()['lastSources'], revisions,
                                  now=now, errors=errors)
    if nightly_day:
        report['scheduledDay'] = nightly_day
    report_id = reports.save_report(report_path(), report, nightly_day=nightly_day)
    if report['execution'] == 'failed':
        raise RuntimeError('證據檢查未通過，失敗原因已留存在報告 ' + str(report_id))
    return {'status': 'completed', 'reportId': report_id, 'externalCalls': 0}


def submit_evidence():
    return job_queue.submit(REPORT_JOB, lambda: check_evidence(recalculate=True), meta={'externalCalls': 0})


def report_tick(current):
    """每日本機結報，休市照常報告；中斷未留下結報時，下次檢查可補執行。"""
    import 證據限制回報 as reports
    if (current.hour, current.minute) < (20, 40):
        return False
    last = reports.read_reports(report_path())
    if last.get('nightlyDay') == current.date().isoformat():
        return False
    return job_queue.submit(REPORT_JOB, lambda: check_evidence(nightly_day=current.date().isoformat()),
                            meta={'externalCalls': 0, 'sessionDate': current.date().isoformat()}).get('queued', False)


def start_daemon():
    global _thread
    if not paths()[1].exists() or (_thread and _thread.is_alive()):
        return
    def loop():
        while True:
            current = datetime.now(ss._TZ['TW'])
            try:
                report_tick(current)
            except Exception:
                import logging
                logging.getLogger(__name__).exception('每日證據結報檢查失敗')
            if current.weekday() < 5 and 14 <= current.hour < 21:
                try:
                    schedule_tick(current)
                    last = daily.status(paths()[1]).get('lastRun') or {}
                    if last.get('sessionDate') != current.date().isoformat() or last.get('status') not in ('completed', 'closed'):
                        job_queue.submit('stock-daily-observation', capture, meta={'externalCalls': 0})
                except Exception:
                    # 保留排程階段失敗；不能因背景 thread 無輸出就誤判仍正常。
                    import logging
                    logging.getLogger(__name__).exception('每日個股排程檢查失敗')
            time.sleep(600)
    _thread = threading.Thread(target=loop, name='stock-daily-observation', daemon=True)
    _thread.start()
