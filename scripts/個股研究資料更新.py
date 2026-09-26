"""沿用 datastore 與籌碼快照更新器，補齊指定期間並留下可追查紀錄。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import uuid
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
        row = {'at': datetime.now(timezone.utc).isoformat(), 'runId': run_id, 'event': event, **fields}
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
            count = datastore.upsert_bars('^TWII', 'TW', rows)
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
    trace('工作結束', ok=not failures, failures=failures, coveredDays=len(state), chipScope='僅上市 T86')
    return int(bool(failures))


if __name__ == '__main__':
    sys.exit(main())
