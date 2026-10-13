"""備援路徑的失敗必須看得見（共用規則 0014）：程式錯誤不能被「回傳預設值」悄悄吞掉。

這些測試直接用真正的 server 模組，不注入任何全域；對照舊行為：`except Exception: return None`
會讓缺 import 的 NameError 變成「無資料」，沒有任何輸出。
"""
from __future__ import annotations

import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import log_once  # noqa: E402
import server  # noqa: E402

TWSE_ROWS = [
    {'Date': '1151006', 'Code': '2330', 'Name': '台積電', 'ClosingPrice': '1,050.00', 'Change': '15.00', 'TradeValue': '50,000,000'},
    {'Date': '1151006', 'Code': '2317', 'Name': '鴻海', 'ClosingPrice': '200.00', 'Change': '-3.00', 'TradeValue': '9,000,000'},
]


def _fake_fetch_json(url, **kwargs):
    if 'STOCK_DAY_ALL' in url:
        return TWSE_ROWS
    if 'tpex' in url:
        return []
    raise AssertionError('測試未明列的來源：' + url)


def _run_day_movers():
    out = io.StringIO()
    with mock.patch('http_client.fetch_json', _fake_fetch_json), \
            mock.patch.object(server, '_get_tw_sectors', return_value={'2330': '半導體業', '2317': '其他電子業'}), \
            mock.patch('urllib.request.urlopen', side_effect=AssertionError('離線測試禁止額外來源')) as extra, \
            mock.patch('http_client._HostPool.acquire', side_effect=AssertionError('離線測試禁止連線池外連')) as pool, \
            mock.patch('socket.create_connection', side_effect=AssertionError('離線測試禁止 socket 外連')) as network, \
            contextlib.redirect_stdout(out):
        result = server._fetch_day_movers(5)
    extra.assert_not_called()
    pool.assert_not_called()
    network.assert_not_called()
    return result, out.getvalue()


class NumericParsersDoNotSwallowProgramErrors(unittest.TestCase):
    def test_with_a_healthy_module_the_ranking_has_rows_and_no_ingest_error_is_logged(self):
        result, output = _run_day_movers()
        self.assertTrue(result.get('ok'), result)
        self.assertEqual(result['gainers'][0]['code'], '2330')
        self.assertEqual(result['losers'][0]['code'], '2317')
        self.assertEqual(result['gainers'][0]['price'], 1050.0)
        self.assertNotIn('[movers] TWSE ingest', output)

    def test_a_missing_global_is_logged_instead_of_silently_producing_no_rows(self):
        saved = server.__dict__.pop('math')                    # 模擬當年的缺 import
        try:
            _, output = _run_day_movers()
        finally:
            server.__dict__['math'] = saved
        self.assertIn('[movers] TWSE ingest', output)
        self.assertIn("name 'math' is not defined", output)


class FallbackPathsLeaveARecord(unittest.TestCase):
    def setUp(self):
        log_once.reset_for_tests()

    def call_screener(self, error):
        out = io.StringIO()
        with mock.patch('datastore.get_bars', side_effect=error), contextlib.redirect_stdout(out):
            result = server._db_screener_arrays('2330')
        return result, out.getvalue()

    def test_db_failure_still_falls_back_to_none_but_is_logged_once(self):
        result, first = self.call_screener(RuntimeError('db locked'))
        self.assertIsNone(result)                              # 呼叫端仍退回 Yahoo，行為不變
        self.assertIn('[screener-db]', first)
        self.assertIn('RuntimeError: db locked', first)
        _, again = self.call_screener(RuntimeError('db locked'))
        self.assertEqual(again, '')                            # 限頻：不洗版

    def test_a_different_error_type_is_logged_immediately(self):
        self.call_screener(RuntimeError('db locked'))
        _, text = self.call_screener(NameError("name 'x' is not defined"))
        self.assertIn('NameError', text)


if __name__ == '__main__':
    unittest.main()
