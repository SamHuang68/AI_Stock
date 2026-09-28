"""沿用 datastore 與籌碼快照更新器，補齊指定期間並留下可追查紀錄。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import datastore
import chip_history_tracker as tracker
from atomic_store import atomic_write_json, load_json


def main(argv=None):
    parser = argparse.ArgumentParser(description='更新既有大盤日線與上市法人資料；不呼叫模型')
    parser.add_argument('--start', type=date.fromisoformat, required=True)
    parser.add_argument('--end', type=date.fromisoformat, required=True)
    parser.add_argument('--benchmark-range', choices=['10y'])
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data')
    parser.add_argument('--adjustments', action='store_true', help='明確授權後才使用：補取本機股票的還原快照')
    parser.add_argument('--symbols', help='限制還原快照代號，以逗號分隔；省略為本機全部股票')
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=4, help='來源下載併發數，最多四個；資料寫入仍循序執行')
    args = parser.parse_args(argv)
    if not args.start <= args.end <= date.today() or (args.end - args.start).days > 370:
        parser.error('日期必須由舊到新、不得包含未來，單次最多 370 日')
    data = args.data_dir.resolve()
    if not (data / 'market.db').is_file():
        parser.error('找不到既有 market.db；不自動建立另一份資料庫')
    datastore.DB_PATH = str(data / 'market.db')
    tracker.CHIP_HISTORY_PATH = str(data / 'chip_history')
    run_id = uuid.uuid4().hex
    def trace(event, **fields):
        row = {'at': datetime.now(timezone.utc).isoformat(), 'runId': run_id,
               'parentRunId': os.environ.get('ST_RESEARCH_PARENT_RUN'), 'event': event, **fields}
        with (data / 'stock_research_update.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        print(json.dumps(row, ensure_ascii=False), flush=True)
    trace('工作開始', start=str(args.start), end=str(args.end), database=str(data / 'market.db'))
    state_path = data / 'stock_research_coverage.json'
    state = load_json(str(state_path), default={}, expected_type=dict)
    failures = []
    try:
        before = datastore.last_ts('^TWII')
        trace('大盤來源開始', host='finance.yahoo.com', symbol='^TWII', before=before)
        if args.benchmark_range:
            # 完整重建歷史由既有來源提供；保留 SQLite 中其他代號。
            rows = datastore.fetch_yahoo_daily('^TWII', 'TW', args.benchmark_range)
            from stock_signals import bar_date, _TZ
            current = datetime.now(_TZ['TW'])
            rows = [r for r in rows if bar_date(r[0], 'TW') < current.date().isoformat()
                    or (bar_date(r[0], 'TW') == current.date().isoformat() and current.hour >= 14)]
            if not rows:
                raise ValueError('來源沒有已收盤日線')
            count = datastore.upsert_bars('^TWII', 'TW', rows, source='Yahoo Finance')
        else:
            count = datastore.update('^TWII')
        trace('大盤資料已提交', rows=count, after=datastore.last_ts('^TWII'))
    except Exception as exc:
        failures.append('benchmark')
        trace('大盤更新失敗', errorType=type(exc).__name__)
    day = args.start
    while day <= args.end:
        key = day.strftime('%Y%m%d')
        fn = data / 'chip_history' / (key + '.json')
        known = state.get(key) or {}
        valid = fn.exists() and known.get('sha256') == hashlib.sha256(fn.read_bytes()).hexdigest()
        if day.weekday() < 5 and not valid:
            start = time.monotonic()
            trace('籌碼來源開始', host='www.twse.com.tw', sessionDate=str(day))
            try:
                count = tracker.parse_and_save(key)
                if count:
                    state[key] = {'rows': count, 'source': 'TWSE/T86', 'scope': '上市',
                                  'sha256': hashlib.sha256(fn.read_bytes()).hexdigest(),
                                  'fetchedAt': datetime.now(timezone.utc).isoformat()}
                    atomic_write_json(str(state_path), state, backup=True)
                trace('籌碼來源完成', sessionDate=str(day), rows=count,
                      state='已提交' if count else '來源無資料，未視為已補齊',
                      elapsedMs=round((time.monotonic() - start) * 1000))
            except Exception as exc:
                failures.append(key)
                trace('籌碼更新失敗', sessionDate=str(day), errorType=type(exc).__name__)
            time.sleep(.25)
        day += timedelta(days=1)
    if args.adjustments:
        import signal_stats_pool as pool
        import 個股還原研究 as adjusted
        from stock_signals import bar_date, normalize_bars, _TZ
        benchmark_ts = datastore.last_ts('^TWII')
        benchmark_day = bar_date(benchmark_ts) if benchmark_ts else None
        codes = args.symbols.split(',') if args.symbols else datastore.list_symbols('TW', 1)
        tasks = {}
        for code in codes:
            if not pool._TICKER_RE['TW'].fullmatch(code):
                continue
            with datastore.read_snapshot() as conn:
                previous = adjusted.load_snapshot(conn, code)
                existing_rows = datastore.get_bars_bulk([code], connection=conn).get(code) or []
            bars = normalize_bars(existing_rows)
            if not bars:
                continue
            fetched = datetime.fromtimestamp(previous['fetchedAt'], _TZ['TW']) if previous else None
            current = datetime.now(_TZ['TW'])
            if (previous and fetched.date() == current.date()
                    and (current.hour < 14 or fetched.hour >= 14)
                    and benchmark_day is not None
                    and max((r['date'] for r in previous.get('rows', [])), default='') >= benchmark_day
                    and adjusted.adjusted_bars(bars, previous) is not None):
                trace('還原來源沿用當日快照', symbol=code)
                continue
            # 明確期間保留日線粒度；range=max 可能被來源自動改成月線。
            tasks[code] = min(r[0] for r in existing_rows) - 86400
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {}
            for code, start_ts in tasks.items():
                trace('還原來源排程', symbol=code, host='finance.yahoo.com', startTimestamp=start_ts)
                futures[executor.submit(datastore.fetch_yahoo_daily, code, 'TW', '10y',
                                        with_research=True, start_ts=start_ts)] = code
            for future in as_completed(futures):
                code = futures[future]
                try:
                    pack = future.result()
                    count = adjusted.save_snapshot(code, 'TW', pack)
                    current = datetime.now(_TZ['TW'])
                    # 依交易日期去重，避免來源時間戳不同造成同一天兩根日線。
                    existing = {bar_date(r[0]) for r in datastore.get_bars(code)}
                    first_day = min(existing)
                    # 查詢緩衝只用來確保首日完整，不能讓每次重跑都向前增加一天。
                    fresh = list({bar_date(r[0]): r for r in pack['rows'] if first_day <= bar_date(r[0]) and bar_date(r[0]) not in existing and
                                  (bar_date(r[0]) < current.date().isoformat() or
                                   (bar_date(r[0]) == current.date().isoformat() and current.hour >= 14))}.values())
                    if fresh:
                        datastore.upsert_bars(code, 'TW', fresh, source='Yahoo Finance')
                    trace('還原來源完成', symbol=code, rows=count, appendedBars=len(fresh))
                except Exception as exc:
                    failures.append('adjustment:' + code)
                    trace('還原來源失敗', symbol=code, errorType=type(exc).__name__, reason=str(exc)[:400])
    trace('工作結束', ok=not failures, failures=failures, coveredDays=len(state), chipScope='僅上市 T86')
    return int(bool(failures))


if __name__ == '__main__':
    sys.exit(main())
