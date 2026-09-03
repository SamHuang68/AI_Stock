#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台股名稱來源只能信任具名代號欄位，避免價格／日期污染名稱快取。"""
import os
import sys
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))

import server as st_server  # noqa: E402
import universe  # noqa: E402


class TestTwNameIntegrity(unittest.TestCase):
    def test_server_stock_universe_never_uses_price_as_symbol(self):
        rows = [
            {'Code': '00675L', 'Name': '富邦臺灣加權正2', 'Transaction': '1000'},
            {'SecuritiesCompanyCode': '5347', 'CompanyName': '世界', 'Close': '152'},
        ]
        self.assertEqual(st_server._extract_tw_stock_codes(rows), {'5347'})

    def test_name_pairs_never_fall_back_to_arbitrary_four_digit_value(self):
        rows = [
            {'Code': '00679B', 'Name': '元大美債20年', 'ClosingPrice': '2749'},
            {'Code': '2330', 'Name': '台積電', 'ClosingPrice': '2410'},
        ]
        names = st_server._extract_tw_name_pairs(rows, ('Code',), ('Name',))
        self.assertEqual(names, {'2330': '台積電'})
        self.assertNotIn('2749', names)

    def test_universe_keeps_real_symbol_and_does_not_invent_price_symbol(self):
        rows = [
            {'Code': '00679B', 'Name': '元大美債20年', 'ClosingPrice': '2749'},
            {'Code': '2330', 'Name': '台積電', 'ClosingPrice': '2410'},
        ]
        with mock.patch.object(universe, '_fetch_json', return_value=rows), \
                mock.patch('builtins.open', side_effect=FileNotFoundError):
            names = universe.fetch_tw()
        self.assertEqual(names.get('2330'), '台積電')
        self.assertEqual(names.get('00679B'), '元大美債20年')
        self.assertNotIn('2749', names)


if __name__ == '__main__':
    unittest.main()
