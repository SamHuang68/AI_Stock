#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
fix_moves.py — 補完 modularize.py 沒搬到的前端檔。

讀 build_v2.py 裡所有 src/<分類>/<檔> 路徑，凡是「該位置沒有、但根目錄有」的，
就用檔案搬移補進去（不靠 git，避免 git mv 的邊界失敗）。冪等，可重複跑。
"""
import os, re, shutil

ROOT = os.path.dirname(os.path.abspath(__file__))
txt = open(os.path.join(ROOT, 'build_v2.py'), encoding='utf-8').read()
paths = re.findall(r"['\"](src/[a-z]+/[\w.-]+\.(?:js|css))['\"]", txt)

moved, ok, problem = [], 0, []
for rel in paths:
    dst = os.path.join(ROOT, rel)
    if os.path.isfile(dst):
        ok += 1
        continue
    base = os.path.basename(rel)
    src = os.path.join(ROOT, base)
    if os.path.isfile(src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        moved.append(f'{base}  →  {rel}')
    else:
        problem.append(rel)

print('=' * 56)
print(f'已在定位: {ok}   本次補搬: {len(moved)}   仍缺: {len(problem)}')
print('=' * 56)
for m in moved:
    print('  moved  ' + m)
for p in problem:
    print('  ?? 找不到來源: ' + p)
print('\n下一步:  python build_v2.py   （應印出 [OK] wrote ...）')
