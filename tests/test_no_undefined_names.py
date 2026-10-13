"""模組層級漏掉 import 時，函式內的 NameError 會被外層 `except Exception` 吞掉，功能悄悄失效。

實例：server.py 沒有 `import math`，但 `_fetch_day_movers`、`_handle_twquote`、`_handle_quote_batch`、
`_db_screener_arrays`、`_tag_industry` 都用到 `math.isfinite`，全包在 try/except 裡 → 總覽漲跌幅排行永遠
「無資料」、個股即時報價的備援永遠取不到數字，且沒有任何錯誤訊息。

既有測試抓不到，因為它們用 AST 只取出單一函式，再手動塞進 `{'math': math, ...}` 這類命名空間——
測試自己補了正式程式缺的名稱。所以這裡用兩層防線：
  1. 靜態：pyflakes 掃描全部 Python 檔，不允許任何 undefined name。
  2. 行為：載入真正的 server 模組（不注入任何全域），餵假資料跑 `_fetch_day_movers`。
"""
from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

try:
    from pyflakes import api as pyflakes_api, reporter as pyflakes_reporter
except ImportError:  # pragma: no cover - CI 以 requirements-ci.txt 安裝
    pyflakes_api = pyflakes_reporter = None

_UNDEFINED = ('UndefinedName', 'UndefinedLocal', 'UndefinedExport')


class _Collect(pyflakes_reporter.Reporter if pyflakes_reporter else object):
    def __init__(self):
        self.found = []

    def unexpectedError(self, filename, message):
        self.found.append(f'{filename}: {message}')

    def syntaxError(self, filename, message, lineno, offset, text):
        self.found.append(f'{filename}:{lineno}: syntax error: {message}')

    def flake(self, message):
        if type(message).__name__ in _UNDEFINED:
            self.found.append(f'{message.filename}:{message.lineno}: {message.message % message.message_args}')


def _python_files():
    skip = {'__pycache__', 'node_modules', '.git', 'research', 'scratch'}
    for path in sorted(ROOT.rglob('*.py')):
        rel = path.relative_to(ROOT).parts
        if skip.intersection(rel):
            continue
        yield path


@unittest.skipIf(pyflakes_api is None, 'pyflakes 未安裝（requirements-ci.txt 會安裝）')
class NoUndefinedNames(unittest.TestCase):
    def test_no_python_file_uses_an_undefined_name(self):
        collector = _Collect()
        for path in _python_files():
            pyflakes_api.check(path.read_text(encoding='utf-8'), str(path.relative_to(ROOT)), collector)
        self.assertEqual(collector.found, [], '以下名稱未定義（常見原因：漏了 import）：\n' + '\n'.join(collector.found))


class DayMoversRunsWithoutInjectedGlobals(unittest.TestCase):
    def test_day_movers_returns_rows_from_real_module(self):
        import server

        rows = [
            {'Date': '1151006', 'Code': '2330', 'Name': '台積電', 'ClosingPrice': '1,050.00', 'Change': '15.00', 'TradeValue': '50,000,000'},
            {'Date': '1151006', 'Code': '2317', 'Name': '鴻海', 'ClosingPrice': '200.00', 'Change': '-3.00', 'TradeValue': '9,000,000'},
        ]

        # movers 經由 http_client 抓取；假造點必須是它，否則測試會實際連到官方站台。
        def fake_fetch_json(url, **kwargs):
            if 'STOCK_DAY_ALL' in url:
                return rows
            if 'tpex' in url:
                return []
            raise OSError('offline test: ' + url)

        with mock.patch('http_client.fetch_json', fake_fetch_json), \
                mock.patch.object(server, '_get_tw_sectors', return_value={'2330': '半導體業', '2317': '其他電子業'}), \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('離線測試禁止額外網路請求')) as external:
            out = server._fetch_day_movers(5)
        external.assert_not_called()
        self.assertTrue(out.get('ok'), out)
        # 只有兩檔、n=5：兩個榜單都會列出兩檔，重點是「有資料」且排序正確（數字解析要成功）。
        self.assertEqual(out['gainers'][0]['code'], '2330')
        self.assertEqual(out['gainers'][0]['price'], 1050.0)
        self.assertAlmostEqual(out['gainers'][0]['changePct'], 1.45, places=2)
        self.assertEqual(out['losers'][0]['code'], '2317')
        self.assertAlmostEqual(out['losers'][0]['changePct'], -1.48, places=2)


if __name__ == '__main__':
    unittest.main()
