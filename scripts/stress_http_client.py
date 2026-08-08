#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""密集刷新壓力測：驗證 http_client 連線池／重試是否穩定。

用法（伺服器需已在 :18432 跑著，且為此 PR 程式）：
  python scripts/stress_http_client.py
  python scripts/stress_http_client.py --rounds 40 --workers 8
  python scripts/stress_http_client.py --base http://127.0.0.1:18432

看什麼：
  - errors / WinError 10053 應接近 0
  - /health.httpClient.reused 應明顯上升（有 Keep-Alive 複用）
  - 多數 /pulse 應 HTTP 200
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed


def _get(url: str, timeout: float = 30):
    req = urllib.request.Request(url, headers={'User-Agent': 'stress-http-client/1.0'})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return {
                'ok': True,
                'status': resp.status,
                'ms': int((time.time() - t0) * 1000),
                'bytes': len(body),
                'err': None,
            }
    except Exception as e:
        return {
            'ok': False,
            'status': getattr(e, 'code', None),
            'ms': int((time.time() - t0) * 1000),
            'bytes': 0,
            'err': f'{type(e).__name__}: {e}',
        }


def _health(base: str):
    r = _get(base.rstrip('/') + '/health', timeout=10)
    if not r['ok']:
        return None, r
    try:
        with urllib.request.urlopen(base.rstrip('/') + '/health', timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8')), r
    except Exception:
        return None, r


def main():
    ap = argparse.ArgumentParser(description='Stock Terminal http_client stress')
    ap.add_argument('--base', default='http://127.0.0.1:18432')
    ap.add_argument('--rounds', type=int, default=30, help='總請求數（預設打 /pulse）')
    ap.add_argument('--workers', type=int, default=6, help='並發數')
    ap.add_argument('--path', default='/pulse?refresh=1', help='壓力路徑')
    args = ap.parse_args()

    base = args.base.rstrip('/')
    print(f'== stress start == base={base} path={args.path} rounds={args.rounds} workers={args.workers}')

    before, br = _health(base)
    if before is None:
        print('[FAIL] 無法讀取 /health — 請先啟動 server（本 PR 分支）')
        print(' detail:', br.get('err'))
        return 2
    if before.get('httpClient') is None:
        print('[FAIL] /health 無 httpClient 欄位 — 目前跑的不是本 PR 程式，請重啟 server')
        return 2

    print('[health before]', json.dumps(before.get('httpClient'), ensure_ascii=False))

    url = base + (args.path if args.path.startswith('/') else '/' + args.path)
    ok_n = err_n = 0
    statuses = {}
    errs = []
    lat = []

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = [ex.submit(_get, url, 45) for _ in range(args.rounds)]
        for i, f in enumerate(as_completed(futs), 1):
            r = f.result()
            lat.append(r['ms'])
            if r['ok'] and r['status'] == 200:
                ok_n += 1
            else:
                err_n += 1
                errs.append(r.get('err') or f'status={r.get("status")}')
            statuses[r.get('status')] = statuses.get(r.get('status'), 0) + 1
            if i % 5 == 0 or i == args.rounds:
                print(f'  progress {i}/{args.rounds} ok={ok_n} err={err_n}')
    elapsed = time.time() - t0

    after, _ = _health(base)
    hc_before = before.get('httpClient') or {}
    hc_after = (after or {}).get('httpClient') or {}

    lat_sorted = sorted(lat)
    p50 = lat_sorted[len(lat_sorted) // 2] if lat_sorted else None
    p95 = lat_sorted[int(len(lat_sorted) * 0.95)] if lat_sorted else None

    print('\n== result ==')
    print(f' elapsed: {elapsed:.1f}s')
    print(f' ok/err:  {ok_n}/{err_n}')
    print(f' status:  {statuses}')
    print(f' latency: p50={p50}ms p95={p95}ms max={max(lat) if lat else None}ms')
    print(f' httpClient before: {hc_before}')
    print(f' httpClient after:  {hc_after}')

    reused_delta = int(hc_after.get('reused') or 0) - int(hc_before.get('reused') or 0)
    req_delta = int(hc_after.get('requests') or 0) - int(hc_before.get('requests') or 0)
    print(f' delta requests={req_delta} reused={reused_delta} retries='
          f'{int(hc_after.get("retries") or 0) - int(hc_before.get("retries") or 0)}')

    win_hits = [e for e in errs if '10053' in e or '10054' in e or 'WinError' in e]
    if errs:
        print('\n sample errors:')
        for e in errs[:8]:
            print('  -', e)

    # 判定
    fail = False
    if err_n > max(2, args.rounds // 10):
        print('\n[FAIL] 錯誤率偏高（>10% 或 >2 次）')
        fail = True
    if reused_delta < 1 and req_delta >= 5:
        print('\n[WARN] reused 沒有上升 — 可能外源不給 Keep-Alive，或路徑未走 http_client')
    if win_hits:
        print(f'\n[FAIL] 出現 Windows 連線中斷 {len(win_hits)} 次')
        fail = True
    if not fail and err_n == 0:
        print('\n[PASS] 密集刷新穩定，可考慮合併 PR')
    elif not fail:
        print('\n[PASS-with-soft-errors] 錯誤在容忍內，請人工看 sample errors 後再合')
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
