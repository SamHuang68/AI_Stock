"""審查 D-04：MIS 個股期整批抓取失效時，不可讓每個請求各自串行重試。不連網。"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import server  # noqa: E402

_REAL_SLEEP = time.sleep  # server.time 就是全域 time，patch 之後仍需真的等待


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class MisFuturesNegativeCacheTest(unittest.TestCase):
    def setUp(self):
        self.saved = dict(server._MIS_FUT)
        server._MIS_FUT.update(ts=0, map={}, failTs=0)
        self.calls = 0
        self.clock = [1_000_000.0]

    def tearDown(self):
        server._MIS_FUT.clear()
        server._MIS_FUT.update(self.saved)

    def _fail(self, *args, **kwargs):
        self.calls += 1
        raise OSError('MIS 520')

    def _load(self, urlopen):
        with mock.patch.object(server.urllib.request, 'urlopen', side_effect=urlopen), \
                mock.patch.object(server.time, 'sleep'), \
                mock.patch.object(server.time, 'time', side_effect=lambda: self.clock[0]), \
                contextlib.redirect_stdout(io.StringIO()):
            return server._mis_load_futures()

    def test_failure_is_cached_briefly_then_retried(self):
        self.assertEqual(self._load(self._fail), {})
        self.assertEqual(self.calls, 2 * server._MIS_FUT_ATTEMPTS)   # 日盤、夜盤各 2 次，舊版各 3 次
        self.clock[0] += 30
        self.assertEqual(self._load(self._fail), {})
        self.assertEqual(self.calls, 2 * server._MIS_FUT_ATTEMPTS)   # 60 秒內不再打 MIS
        self.clock[0] += 31
        self._load(self._fail)
        self.assertEqual(self.calls, 4 * server._MIS_FUT_ATTEMPTS)

    def test_concurrent_requests_share_one_fetch(self):
        def slow_fail(*args, **kwargs):
            _REAL_SLEEP(0.2)   # 讓 5 個請求同時卡在抓取中；沒有鎖時會各自打 MIS
            return self._fail()

        with mock.patch.object(server.urllib.request, 'urlopen', side_effect=slow_fail), \
                mock.patch.object(server.time, 'sleep'), \
                contextlib.redirect_stdout(io.StringIO()):
            threads = [threading.Thread(target=server._mis_load_futures) for _ in range(5)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(10)
        self.assertEqual(self.calls, 2 * server._MIS_FUT_ATTEMPTS)

    def test_success_clears_failure_and_is_cached(self):
        server._MIS_FUT['failTs'] = self.clock[0] - 120
        rows = {'0': [{'SymbolID': 'CDFK6-F'}, {'SymbolID': 'CDF-S'}], '1': [{'SymbolID': 'CDFK6-M'}]}

        def ok(req, timeout):
            self.calls += 1
            market = json.loads(req.data.decode())['MarketType']
            return _Resp(json.dumps({'RtData': {'QuoteList': rows[market]}}).encode())

        m = self._load(ok)
        self.assertEqual(set(m['CDF']), {'dayFut', 'daySpot', 'nightFut'})
        self.assertEqual(server._MIS_FUT['failTs'], 0)
        self.assertIs(self._load(ok), m)
        self.assertEqual(self.calls, 2)


if __name__ == '__main__':
    unittest.main()
