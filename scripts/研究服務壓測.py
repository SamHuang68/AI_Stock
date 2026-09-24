"""對明確指定的隔離 loopback 候選服務進行有界、唯讀混合負載驗證。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


PATHS = ('/health/live', '/research/workflow', '/updates', '/research/validation')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', required=True, help='隔離候選的 loopback 網址；不得指向正式服務')
    parser.add_argument('--seconds', type=int, default=300)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    base = urllib.parse.urlsplit(args.base_url)
    if (base.scheme != 'http' or base.hostname not in ('127.0.0.1', 'localhost', '::1')
            or not base.port or base.port in (18432, 18434, 18435) or base.path not in ('', '/')
            or base.query or base.fragment or base.username):
        parser.error('只接受明確指定隔離埠的 loopback HTTP 網址，禁止正式入口')
    if not 1 <= args.seconds <= 1800 or not 1 <= args.workers <= 8:
        parser.error('驗證時間須為 1–1800 秒，並行數須為 1–8')
    start = time.monotonic()
    lock = threading.Lock()
    samples: list[dict] = []
    # 每個 worker 自有 opener，禁止 redirect 把驗證轉成外部連線。
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            raise urllib.error.HTTPError(req.full_url, code, '禁止重新導向', headers, fp)

    def run(worker: int) -> None:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        iteration = 0
        while time.monotonic() - start < args.seconds:
            # 最多一個 worker 計算大型組合，其餘持續確認輕量讀取仍能回應。
            path = '/research/portfolio' if worker == 0 and iteration % 25 == 0 else PATHS[(iteration + worker) % len(PATHS)]
            before = time.monotonic()
            row = {'path': path, 'offsetSeconds': round(before - start, 3), 'worker': worker}
            try:
                req = urllib.request.Request(args.base_url.rstrip('/') + path, headers={'Accept': 'application/json', 'Cache-Control': 'no-cache'})
                with opener.open(req, timeout=45) as response:
                    body = response.read()
                    payload = json.loads(body)
                    row.update(status=response.status, bytes=len(body), ok=response.status == 200 and payload.get('ok') is not False)
            except Exception as exc:
                row.update(ok=False, error=type(exc).__name__ + ': ' + str(exc))
            row['latencyMs'] = round((time.monotonic() - before) * 1000, 3)
            with lock:
                samples.append(row)
            iteration += 1
            time.sleep(.2)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        list(executor.map(run, range(args.workers)))
    routes = {}
    for path in (*PATHS, '/research/portfolio'):
        rows = [row for row in samples if row['path'] == path]
        elapsed = sorted(row['latencyMs'] for row in rows)
        routes[path] = {'requests': len(rows), 'failures': sum(not row['ok'] for row in rows),
                        'medianMs': statistics.median(elapsed) if elapsed else None,
                        'p95Ms': elapsed[min(len(elapsed) - 1, int(len(elapsed) * .95))] if elapsed else None,
                        'maxMs': max(elapsed) if elapsed else None}
    result = {'completedAt': datetime.now(timezone.utc).isoformat(), 'baseUrl': args.base_url,
              'durationSeconds': round(time.monotonic() - start, 3), 'workers': args.workers,
              'readOnly': True, 'routes': routes, 'samples': samples,
              'limitations': ['限隔離候選與既有資料，未呼叫來源更新或模型。', '有界負載不能代替跨日運行或實體裝置驗收。']}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({key: value for key, value in result.items() if key != 'samples'}, ensure_ascii=False))
    return 1 if any(not row['ok'] for row in samples) else 0


if __name__ == '__main__':
    raise SystemExit(main())
