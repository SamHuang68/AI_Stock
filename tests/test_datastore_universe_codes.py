"""datastore.fetch_tw_universe 只接受具名代號欄位，與 server._extract_tw_stock_codes 同一契約。"""
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import datastore  # noqa: E402


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FetchTwUniverseCodes(unittest.TestCase):
    def test_price_and_count_values_are_not_taken_as_codes(self):
        rows = [
            {'Code': '2330', 'ClosingPrice': '1234', 'TradeVolume': '5678'},
            {'SecuritiesCompanyCode': '6488', 'Close': '2345'},
            {'證券代號': '1101', '成交筆數': '3456'},
            {'Name': '無代號欄位', 'ClosingPrice': '7890', 'Date': '1141103'},
            {'Code': '0050', 'ClosingPrice': '4567'},
        ]
        with mock.patch.object(datastore.urllib.request, 'urlopen',
                               lambda *a, **k: _Resp(json.dumps(rows).encode())):
            self.assertEqual(datastore.fetch_tw_universe(), ['1101', '2330', '6488'])


if __name__ == '__main__':
    unittest.main()
