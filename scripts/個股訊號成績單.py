"""本機個股訊號成績單與前瞻批次；不連網、不更新行情、不建立排程。"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import datastore
import signal_stats_pool as pool
import stock_signals as ss
import 個股訊號研究 as research
import 個股訊號帳本 as ledger
from atomic_store import atomic_write_json, atomic_write_text

SOURCE_FILES = ['server/' + p for p in ['indicators.py', 'stock_signals.py', '個股訊號研究.py',
                '個股訊號帳本.py', 'signal_stats_pool.py', 'datastore.py', 'atomic_store.py']]
SOURCE_FILES.append('scripts/個股訊號成績單.py')


def engine_digest():
    return research.digest({p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in SOURCE_FILES})


def pct(value):
    return '—' if value is None else f'{value * 100:+.2f}%'


def interval(value):
    return '資料不足' if value is None else ' ～ '.join(pct(v) for v in value)


def render_report(result, receipt):
    study = result['research']
    selection = study['selection']
    rows = ['# 個股訊號成績單', '',
            f"計算時間：{result['generatedAt']}。資料期間：{result['window']['from']}～{result['window']['to']}。",
            f"共 {result['symbols']} 檔、15 種訊號；全部項目保留。價格未還原、未計費用，屬事件研究。", '',
            f"**候選結果：{selection['reason']}**", '',
            f"研究版本：`{study['version']}`。協定：`{receipt['protocolId']}`。",
            '前瞻批次尚未累積成熟結果；協定登錄不代表訊號已驗證。', '',
            '## 15 種訊號與同情境基準的差距', '',
            '以下均從下一交易日收盤起算。區間衡量季度等權平均報酬差距，樣本門檻不足時不顯示區間。', '',
            '| 訊號 | 天數 | 次數／股票／季度 | 原始報酬中位數 | 季度等權差距 | 季度等權差距區間 | 持有現股不利幅度第 10 百分位 |',
            '|---|---:|---|---:|---:|---|---:|']
    for signal in study['signals']:
        for h in signal['horizons']:
            a = h['all']
            rows.append(f"| {signal['label']} | {h['horizon']} | {a['n']}／{a['symbols']}／{a['quarters']} | "
                        f"{pct(a['medianRet'])} | {pct(a['blockMeanDeltaRet'])} | {interval(a['deltaRetCI95'])} | {pct(a['adverseP10'])} |")
    rows += ['', '## 固定情境：大盤與個股均為上升趨勢', '',
             '只依 2024 年以前已成熟的 5 日結果選擇偏多候選。保留期不通過時不改挑其他訊號。', '',
             '| 偏多訊號 | 訓練次數／股票／季度 | 訓練差距區間 | 訓練情境增量區間 | 2024 年起差距區間 | 2024 年起情境增量區間 |',
             '|---|---:|---|---|---|---|']
    for s in study['signals']:
        if s['direction'] != 'bull':
            continue
        h = next(x for x in s['horizons'] if x['horizon'] == 5)
        tr, chk = h['training'], h['temporalCheck']
        c = tr['context']
        rows.append(f"| {s['label']} | {c['n']}／{c['symbols']}／{c['quarters']} | {interval(c['deltaRetCI95'])} | "
                    f"{interval(tr['increment']['ci95'])} | {interval(chk['context']['deltaRetCI95'])} | {interval(chk['increment']['ci95'])} |")
    rsi = study.get('rsiRebound')
    if rsi:
        rows += ['', '## RSI 獨立假說：大盤非下降、個股仍下降', '',
                 rsi['selection']['reason'], '', *rsi['limitations'], '',
                 '| 天數 | 分段 | 次數／股票／季度 | 差距區間 | 情境增量區間 |',
                 '|---|---|---:|---|---|']
        for h in rsi['signals'][0]['horizons']:
            for key, label in [('training', '2024 年以前'), ('temporalCheck', '2024 年起')]:
                part = h[key]
                c = part['context']
                rows.append(f"| {h['horizon']} | {label} | {c['n']}／{c['symbols']}／{c['quarters']} | "
                            f"{interval(c['deltaRetCI95'])} | {interval(part['increment']['ci95'])} |")
    rows += ['', '## 覆蓋、限制與追蹤', '']
    rows += [f'- {note}' for note in study['limitations']]
    bc = study['benchmarkCoverage']
    rows += [f"- 指數情境覆蓋：{bc['from']}～{bc['to']}，共 {bc['bars']} 根；情境已成形 {bc['knownRegimeDays']} 日。",
             '- 區間門檻為至少 100 次、5 檔、8 季；次數很多但季度不足，仍標示資料不足。',
             f"- 與指數交易日不對齊的對照候選：{study['skipped'].get('missing_sessions', 0)} 筆／天數組合。"]
    rows += [f"- 未成熟或指標暖機事件：{study['skipped'].get('immature_or_warmup', 0)} 筆事件／天數組合。",
             f"- 缺少同日大盤或已成熟對照：{study['skipped'].get('missing_market_or_controls', 0)} 筆事件／天數組合。",
             '- 完整各股票覆蓋、年份差距與集中程度保留於「成績單.json」，來源為同資料夾的唯讀快照。',
             '- 前瞻追蹤使用相同輸出資料夾執行批次；只追加註冊後的當日已收盤事件，不回填歷史。',
             '- 「圖表 → 體檢 → 專業」內容延後到下一輪，本輪未新增閱讀深度。', '']
    return '\n'.join(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='本輪輸出與前瞻帳本資料夾')
    parser.add_argument('--db', type=Path, default=Path(datastore.DB_PATH), help='既有行情資料庫（唯讀）')
    parser.add_argument('--chips', type=Path, default=Path(pool.CHIP_HISTORY_PATH), help='既有籌碼資料夾（唯讀）')
    parser.add_argument('--mode', choices=['report', 'track'], default='report', help='產生成績單或追加前瞻結果')
    parser.add_argument('--cache-file', type=Path, help='選用：更新本機衍生統計快取，保留備份')
    parser.add_argument('--frozen-source', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output == Path(output.anchor) or output == args.db.resolve():
        parser.error('輸出必須是具名資料夾，不能是磁碟根目錄或來源資料庫')
    if args.cache_file:
        cache = args.cache_file.resolve()
        if (cache.is_relative_to(output) or cache.is_relative_to(args.chips.resolve()) or
                cache == args.db.resolve() or cache.suffix != '.json'):
            parser.error('快取必須是研究產物與來源之外的獨立 JSON，不能覆寫凍結證據')
    output.mkdir(parents=True, exist_ok=True)
    receipt_path = output / '執行紀錄.json'
    ledger_path = output / '個股訊號前瞻.sqlite3'
    if args.mode == 'track':
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        with datastore.read_snapshot(args.db) as conn:
            benchmark = datastore.get_bars_bulk(['^TWII'], connection=conn).get('^TWII') or []
            result = ledger.track(ledger_path, receipt['protocolId'],
                                  pool.iter_datastore('TW', connection=conn),
                                  ss.normalize_bars(benchmark), engine_digest(),
                                  chips=pool._load_all_chips(str(args.chips)))
            if receipt.get('rsiProtocolId'):
                result['rsiRebound'] = ledger.track(ledger_path, receipt['rsiProtocolId'],
                    pool.iter_datastore('TW', connection=conn), ss.normalize_bars(benchmark), engine_digest(),
                    chips=pool._load_all_chips(str(args.chips)))
        atomic_write_json(str(output / '前瞻狀態.json'), result, backup=True)
        print(json.dumps(result, ensure_ascii=False))
        return
    if receipt_path.exists() or (output / '來源快照.sqlite3').exists():
        parser.error('此資料夾已有凍結研究；請使用追蹤模式，或為新研究選擇另一資料夾')
    if not args.frozen_source:
        # 父程序僅凍結程式；研究由新程序載入快照中的模組，避免已匯入舊碼與磁碟新碼混用。
        source_dir = output / '程式快照'
        if source_dir.exists():
            parser.error('程式快照已存在，請保留舊結果並使用另一輸出資料夾')
        source_bytes = {p: (ROOT / p).read_bytes() for p in SOURCE_FILES}
        frozen_digest = research.digest({p: hashlib.sha256(b).hexdigest() for p, b in source_bytes.items()})
        if frozen_digest != engine_digest():
            raise RuntimeError('凍結期間程式變動，停止研究')
        for p, content in source_bytes.items():
            target = source_dir / p
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        command = [sys.executable, '-B', str(source_dir / 'scripts/個股訊號成績單.py'),
                   '--output', str(output), '--db', str(args.db.resolve()), '--chips', str(args.chips.resolve()),
                   '--frozen-source']
        if args.cache_file:
            command += ['--cache-file', str(args.cache_file.resolve())]
        return subprocess.run(command, check=False).returncode
    frozen_engine_digest = engine_digest()
    snapshot = output / '來源快照.sqlite3'
    with datastore.read_snapshot(args.db) as source:
        with closing(sqlite3.connect(snapshot)) as target:
            source.backup(target)
    chips = pool._load_all_chips(str(args.chips))
    atomic_write_json(str(output / '籌碼快照.json'), chips, backup=False)
    with datastore.read_snapshot(snapshot) as conn:
        result = pool.compute_snapshot(conn, chips=chips,
                                       progress=lambda n: print(f'已處理 {n} 檔', flush=True))
    study = result['research']
    if engine_digest() != frozen_engine_digest:
        raise RuntimeError('研究期間程式快照變動，拒絕登錄協定')
    protocol_id = ledger.register(ledger_path, study, frozen_engine_digest)
    rsi_id = ledger.register(ledger_path, study['rsiRebound'], frozen_engine_digest) if study.get('rsiRebound') else None
    receipt = {'protocolId': protocol_id, 'rsiProtocolId': rsi_id, 'engineDigest': frozen_engine_digest,
               'source': str(args.db.resolve()), 'snapshot': str(snapshot),
               'snapshotDigest': hashlib.sha256(snapshot.read_bytes()).hexdigest(),
               'chipDigest': research.digest(chips), 'externalCalls': 0,
               'registeredAt': datetime.now(ss._TZ['TW']).isoformat(), 'python': sys.version,
               'selection': study['selection'], 'reportDigest': research.digest(result)}
    atomic_write_json(str(output / '成績單.json'), result, backup=False)
    atomic_write_json(str(receipt_path), receipt, backup=False)
    atomic_write_text(str(output / '個股訊號成績單.md'), render_report(result, receipt), backup=False)
    if args.cache_file:
        path = args.cache_file.resolve()
        current = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        current['TW'] = result
        atomic_write_json(str(path), current, backup=True)
    print(json.dumps({'output': str(output), 'symbols': result['symbols'],
                      'selection': study['selection'], 'protocolId': protocol_id}, ensure_ascii=False))


if __name__ == '__main__':
    sys.exit(main() or 0)
