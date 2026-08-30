#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日資料快照備份 (v3.9 Phase-2)
把 chip_history/ 與 etf_history/(核心資產:法人籌碼與 ETF 持股快照)壓成帶日期
時間戳的 zip,存到 backups/,並只保留最近 KEEP 份(自動刪舊)。純標準庫,無外部依賴。
用法:  python backup_data.py        (或排程 daily_backup.bat)
"""
import os
import sys
import glob
import zipfile
import datetime

import etf_paths

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(BASE, 'backups')
KEEP = 14                                       # 保留最近幾份(約兩週交易日)


def source_dirs():
    return [
        ('chip_history', os.path.join(BASE, 'data', 'chip_history')),
        ('etf_history', str(etf_paths.resolve_history_dir())),
    ]


def main():
    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    out = os.path.join(BACKUP_DIR, 'data_snapshot_%s.zip' % stamp)

    n = 0
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for d, full in source_dirs():
            if not os.path.isdir(full):
                print('[backup] skip (not found): %s' % d)
                continue
            for f in glob.glob(os.path.join(full, '**', '*'), recursive=True):
                if os.path.isfile(f):
                    rel = os.path.relpath(f, full)
                    z.write(f, os.path.join('data', d, rel))
                    n += 1

    size_kb = os.path.getsize(out) / 1024.0
    print('[backup] wrote %s (%d files, %.1f KB)' % (out, n, size_kb))

    if n == 0:
        # 沒有任何來源檔 → 刪掉空 zip,避免占名額
        try:
            os.remove(out)
        except OSError:
            pass
        print('[backup] WARNING: 0 files — 來源資料夾尚無快照,未產生備份')
        return 0

    # 只保留最近 KEEP 份(檔名含時間戳,字典序=時間序)
    zips = sorted(glob.glob(os.path.join(BACKUP_DIR, 'data_snapshot_*.zip')))
    for old in zips[:-KEEP]:
        try:
            os.remove(old)
            print('[backup] pruned old: %s' % os.path.basename(old))
        except OSError as e:
            print('[backup] prune failed %s: %s' % (old, e))

    return 0


if __name__ == '__main__':
    sys.exit(main())
