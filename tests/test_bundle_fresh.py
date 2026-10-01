#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""追蹤中的 stock_terminal_v2.html 必須等於目前原始碼的重建結果。

啟動腳本與隔離主機的 stage 都會重跑 build_v2.py，所以過期的追蹤檔不會影響
日常使用；但直接 `python server/server.py`、或任何不重建就取用追蹤檔的人，
會拿到舊版（例如 9/30 的圖表尺寸修正沒進到追蹤檔）。這個測試讓 CI 擋下這種漂移。

比對前先遮掉 `?v=<12 碼雜湊>` 並統一換行：該雜湊是對 src 檔原始位元組取的，
Windows(CRLF) 與 Linux(LF) 結果不同，逐位元組比對會永遠誤報。遮掉後仍能抓到
模板、內嵌腳本、模組清單、樣式區塊的任何變動。
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_CACHE_BUSTER = re.compile(rb'\?v=[0-9a-f]{12}')


def _normalize(data: bytes) -> bytes:
    return _CACHE_BUSTER.sub(b'?v=X', data.replace(b'\r\n', b'\n'))


class BundleFreshnessTests(unittest.TestCase):
    def test_tracked_bundle_matches_rebuild(self):
        with tempfile.TemporaryDirectory() as temp:
            built = Path(temp) / 'rebuilt.html'
            subprocess.run(
                [sys.executable, str(ROOT / 'build_v2.py'), '--out', str(built)],
                cwd=ROOT, check=True, capture_output=True)
            expected = _normalize(built.read_bytes()).decode('utf-8').splitlines()
            actual = _normalize((ROOT / 'stock_terminal_v2.html').read_bytes()).decode('utf-8').splitlines()
        if expected != actual:
            first = next((i for i, (a, b) in enumerate(zip(expected, actual)) if a != b),
                         min(len(expected), len(actual)))
            self.fail(
                'stock_terminal_v2.html 與目前原始碼的重建結果不一致'
                f'（第 {first + 1} 行起不同；重建 {len(expected)} 行、追蹤檔 {len(actual)} 行）。\n'
                '請執行 `python build_v2.py` 並把更新後的 stock_terminal_v2.html 一起提交。')


if __name__ == '__main__':
    unittest.main()
