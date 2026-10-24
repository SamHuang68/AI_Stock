"""沿用 datastore 與籌碼快照更新器，補齊指定期間並留下可追查紀錄。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
from data_paths import binding_for, data_path
from runtime_storage import assert_write_allowed


def run_update(argv=None, *, parent_run_id=None, trace_output=None, deadline_monotonic=None):
    """Run inside the owning backend; this function never acquires a lease."""
    binding = binding_for(code_root=ROOT)
    parser = argparse.ArgumentParser(description='更新既有大盤日線與上市法人資料；不呼叫模型')
    parser.add_argument('--start', type=date.fromisoformat, required=True)
    parser.add_argument('--end', type=date.fromisoformat, required=True)
    parser.add_argument('--benchmark-range', choices=['10y'])
    parser.add_argument('--data-dir', type=Path, default=data_path(binding=binding))
    parser.add_argument('--adjustments', action='store_true', help='明確授權後才使用：補取本機股票的還原快照')
    parser.add_argument('--symbols', help='限制還原快照代號，以逗號分隔；省略為本機全部股票')
    parser.add_argument('--workers', type=int, choices=range(1, 5), default=4, help='來源下載併發數，最多四個；資料寫入仍循序執行')
    args = parser.parse_args(argv)
    if not args.start <= args.end <= date.today() or (args.end - args.start).days > 370:
        parser.error('日期必須由舊到新、不得包含未來，單次最多 370 日')
    data = args.data_dir.absolute()
    if binding.mode != 'legacy' and data != data_path(binding=binding):
        parser.error('--data-dir 與已綁定資料根不符；請使用後端更新中心')
    assert_write_allowed(data / 'market.db', binding=binding, must_exist=True)
    if not (data / 'market.db').is_file():
        parser.error('找不到既有 market.db；不自動建立另一份資料庫')
    # Delay writable consumer imports until ownership is proven.
    import datastore
    import chip_history_tracker as tracker
    from atomic_store import atomic_write_json, load_json
    from deadline import Deadline
    deadline = None if deadline_monotonic is None else Deadline(max(0, deadline_monotonic - time.monotonic()))
    def check_budget():
        if deadline is not None and deadline.expired():
            raise TimeoutError('研究來源更新時間預算已用盡；既有資料保留，請由更新中心續作')
    check_budget()
    if binding.mode == 'legacy':
        datastore.DB_PATH = str(data / 'market.db')
        tracker.CHIP_HISTORY_PATH = str(data / 'chip_history')
    elif Path(datastore.DB_PATH) != data / 'market.db':
        raise RuntimeError('後端 datastore 與資料綁定不一致')
    run_id = uuid.uuid4().hex
    def trace(event, **fields):
        row = {'at': datetime.now(timezone.utc).isoformat(), 'runId': run_id,
               'parentRunId': parent_run_id or os.environ.get('ST_RESEARCH_PARENT_RUN'), 'event': event, **fields}
        target = data / 'stock_research_update.jsonl'
        assert_write_allowed(target, binding=binding)
        with target.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
        print(json.dumps(row, ensure_ascii=False), file=trace_output, flush=True)
    trace('工作開始', start=str(args.start), end=str(args.end), database=str(data / 'market.db'))
    state_path = data / 'stock_research_coverage.json'
    state = load_json(str(state_path), default={}, expected_type=dict)
    failures = []
    try:
        before = datastore.last_ts('^TWII')
        trace('大盤來源開始', host='finance.yahoo.com', symbol='^TWII', before=before)
        if args.benchmark_range:
            # 完整重建歷史由既有來源提供；保留 SQLite 中其他代號。
            receipt = {}
            budget_args = {'deadline': deadline} if deadline is not None else {}
            rows = datastore.fetch_yahoo_daily('^TWII', 'TW', args.benchmark_range, receipt_out=receipt, **budget_args)
            check_budget()
            from stock_signals import bar_date, _TZ
            current = datetime.now(_TZ['TW'])
            rows = [r for r in rows if bar_date(r[0], 'TW') < current.date().isoformat()
                    or (bar_date(r[0], 'TW') == current.date().isoformat() and current.hour >= 14)]
            if not rows:
                raise ValueError('來源沒有已收盤日線')
            count = datastore.upsert_bars('^TWII', 'TW', rows, source='Yahoo Finance', ingest_receipt=receipt)
        else:
            count = datastore.update('^TWII')
        check_budget()
        trace('大盤資料已提交', rows=count, after=datastore.last_ts('^TWII'))
    except TimeoutError:
        raise
    except Exception as exc:
        failures.append('benchmark')
        trace('大盤更新失敗', errorType=type(exc).__name__)
    day = args.start
    while day <= args.end:
        check_budget()
        key = day.strftime('%Y%m%d')
        fn = data / 'chip_history' / (key + '.json')
        known = state.get(key) or {}
        valid = fn.exists() and known.get('sha256') == hashlib.sha256(fn.read_bytes()).hexdigest()
        if day.weekday() < 5 and not valid:
            start = time.monotonic()
            trace('籌碼來源開始', host='www.twse.com.tw', sessionDate=str(day))
            try:
                count = tracker.parse_and_save(key, directory=str(data / 'chip_history'))
                check_budget()
                if count:
                    state[key] = {'rows': count, 'source': 'TWSE/T86', 'scope': '上市',
                                  'sha256': hashlib.sha256(fn.read_bytes()).hexdigest(),
                                  'fetchedAt': datetime.now(timezone.utc).isoformat()}
                    atomic_write_json(str(state_path), state, backup=True)
                trace('籌碼來源完成', sessionDate=str(day), rows=count,
                      state='已提交' if count else '來源無資料，未視為已補齊',
                      elapsedMs=round((time.monotonic() - start) * 1000))
            except TimeoutError:
                raise
            except Exception as exc:
                failures.append(key)
                trace('籌碼更新失敗', sessionDate=str(day), errorType=type(exc).__name__)
            time.sleep(.25)
        day += timedelta(days=1)
    if args.adjustments:
        check_budget()
        import 個股還原研究 as adjusted
        from stock_signals import bar_date
        benchmark_ts = datastore.last_ts('^TWII')
        benchmark_day = bar_date(benchmark_ts) if benchmark_ts else None
        codes = args.symbols.split(',') if args.symbols else datastore.list_symbols('TW', 1)
        result = adjusted.refresh_snapshots(codes, expected_day=benchmark_day,
            append_missing=True, trace=trace, workers=args.workers, deadline=deadline)
        check_budget()
        if result['status'] != 'completed':
            failures.extend('adjustment:' + code for code, item in result['results'].items()
                            if item['status'] != 'completed')
            failures.extend('adjustment:' + code for code in result['pendingSymbols'])
    trace('工作結束', ok=not failures, failures=failures, coveredDays=len(state), chipScope='僅上市 T86')
    return int(bool(failures))


def main(argv=None):
    binding = binding_for(code_root=ROOT)
    if binding.mode != 'legacy':
        raise RuntimeError('此模式禁止獨立研究寫入程序；請由已登記 Stock Terminal 的更新中心提交研究資料維護')
    return run_update(argv)


if __name__ == '__main__':
    sys.exit(main())
