#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""密集刷新壓力測：驗證 http_client 連線池／重試是否穩定。

用法（伺服器需已在 :18432 跑著，且為此 PR 程式）：
  python scripts/stress_http_client.py
  python scripts/stress_http_client.py --rounds 40 --workers 8
  python scripts/stress_http_client.py --path /txf

說明：
  - tip 線有 /pulse；本基建 PR 以 main 為底時可能沒有 /pulse。
  - 預設會自動探測可用路徑（優先會觸發外呼者）。
  - 看 /health.httpClient.reused 是否上升、錯誤／WinError 10053 是否接近 0。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

# 候選：先試 tip 聚合，再試 main 常見外呼路徑
CANDIDATE_PATHS = (
    '/pulse?refresh=1',
    '/breadth?refresh=1',
    '/txf',
    '/twindex',
    '/marketflow',
    '/yf/batch?symbols=%5EGSPC,GC=F,HG=F',
    '/macro/economy?years=5',
    '/health',
)


def _get(url: str, timeout: float = 45):
    req = urllib.request.Request(url, headers={'User-Agent': 'stress-http-client/1.0'})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return {
                'ok': True,
                'status': int(resp.status),
                'ms': int((time.time() - t0) * 1000),
                'bytes': len(body),
                'err': None,
            }
    except urllib.error.HTTPError as e:
        try:
            e.read()
        except Exception:
            pass
        return {
            'ok': False,
            'status': int(e.code),
            'ms': int((time.time() - t0) * 1000),
            'bytes': 0,
            'err': f'HTTPError: HTTP Error {e.code}: {e.reason}',
        }
    except Exception as e:
        return {
            'ok': False,
            'status': None,
            'ms': int((time.time() - t0) * 1000),
            'bytes': 0,
            'err': f'{type(e).__name__}: {e}',
        }


def _load_health(base: str):
    url = base.rstrip('/') + '/health'
    req = urllib.request.Request(url, headers={'User-Agent': 'stress-http-client/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8')), None
    except Exception as e:
        return None, f'{type(e).__name__}: {e}'


def _pick_path(base: str, preferred: str | None) -> str:
    if preferred:
        r = _get(base.rstrip('/') + preferred, timeout=20)
        if r['ok'] and r['status'] == 200:
            return preferred
        print(f'[warn] --path {preferred} 不可用 ({r.get("status")} {r.get("err")})，改自動探測')
    for path in CANDIDATE_PATHS:
        r = _get(base.rstrip('/') + path, timeout=20)
        if r['ok'] and r['status'] == 200:
            return path
    return '/health'


def main():
    ap = argparse.ArgumentParser(description='Stock Terminal http_client stress')
    ap.add_argument('--base', default='http://127.0.0.1:18432')
    ap.add_argument('--rounds', type=int, default=30, help='總請求數')
    ap.add_argument('--workers', type=int, default=6, help='並發數')
    ap.add_argument('--path', default='', help='指定路徑；空白則自動探測')
    args = ap.parse_args()

    base = args.base.rstrip('/')
    before, herr = _load_health(base)
    if before is None:
        print('[FAIL] 無法讀取 /health — 請先啟動 server（本 PR 分支）')
        print(' detail:', herr)
        return 2
    if before.get('httpClient') is None:
        print('[FAIL] /health 無 httpClient 欄位 — 目前跑的不是本 PR 程式，請重啟 server')
        return 2

    path = _pick_path(base, args.path.strip() or None)
    print(f'== stress start == base={base} path={path} rounds={args.rounds} workers={args.workers}')
    if path == '/health':
        print('[warn] 僅打到 /health（不觸發外呼）；reused 可能不增加，仍可看錯誤率')
    print('[health before]', json.dumps(before.get('httpClient'), ensure_ascii=False))

    url = base + path
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
            key = r.get('status')
            statuses[key] = statuses.get(key, 0) + 1
            if i % 5 == 0 or i == args.rounds:
                print(f'  progress {i}/{args.rounds} ok={ok_n} err={err_n}')
    elapsed = time.time() - t0

    after, _ = _load_health(base)
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
    err_delta = int(hc_after.get('errors') or 0) - int(hc_before.get('errors') or 0)
    print(f' delta requests={req_delta} reused={reused_delta} retries='
          f'{int(hc_after.get("retries") or 0) - int(hc_before.get("retries") or 0)}'
          f' errors={err_delta}')

    win_hits = [e for e in errs if '10053' in e or '10054' in e or 'WinError' in e]
    if errs:
        print('\n sample errors:')
        for e in errs[:8]:
            print('  -', e)

    fail = False
    if err_n > max(2, args.rounds // 10):
        print('\n[FAIL] 錯誤率偏高（>10% 或 >2 次）')
        fail = True
    if path != '/health' and reused_delta < 1 and req_delta >= 5:
        print('\n[WARN] reused 沒有上升 — 外源可能不給 Keep-Alive；只要無 WinError 仍可合')
    if win_hits:
        print(f'\n[FAIL] 出現 Windows 連線中斷 {len(win_hits)} 次')
        fail = True
    if not fail and err_n == 0:
        print('\n[PASS] 密集刷新穩定，可考慮合併 PR')
        if int(hc_before.get('reused') or 0) > 0 or reused_delta > 0:
            print('       （httpClient.reused 已有複用跡象）')
    elif not fail:
        print('\n[PASS-with-soft-errors] 錯誤在容忍內，請人工看 sample errors 後再合')
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
