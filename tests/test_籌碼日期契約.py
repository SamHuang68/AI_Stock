#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三大法人個股資料須保留官方交易日，不得以執行日冒充。"""
import json
import importlib.util
import os
import sys
import tempfile
import unittest
from datetime import date
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SERVER_DIR = os.path.join(ROOT, 'server')
sys.path.insert(0, SERVER_DIR)

import chip_api as chip  # noqa: E402
import macro_track as macro  # noqa: E402

SPEC = importlib.util.spec_from_file_location('st_server_chip_date_test', os.path.join(SERVER_DIR, 'server.py'))
if SPEC is None or SPEC.loader is None:
    raise RuntimeError('無法載入 Stock Terminal server')
st_server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(st_server)


class TestChipDateContract(unittest.TestCase):
    def test_exchange_date_normalizes_roc_and_rejects_future(self):
        with mock.patch.object(chip, '_taipei_today', return_value=date(2026, 9, 3)):
            self.assertEqual(chip._exchange_date_yyyymmdd('1150902'), '20260902')
            self.assertEqual(chip._exchange_date_yyyymmdd('2026-09-02'), '20260902')
            self.assertIsNone(chip._exchange_date_yyyymmdd('1150904'))
            self.assertIsNone(chip._exchange_date_yyyymmdd('無日期'))

    def test_tpex_row_carries_authoritative_date(self):
        payload = [{
            'Date': '1150902', 'SecuritiesCompanyCode': '3529',
            'ForeignInvestorsNetBuySell': '-251839',
            'InvestmentTrustNetBuySell': '-40000',
            'DealerNetBuySell': '-36560',
            'InstitutionalInvestorsTotalNetBuySell': '-328399',
        }]
        original = chip._src_fetch_json
        chip._src_fetch_json = lambda *args, **kwargs: payload
        try:
            with mock.patch.object(chip, '_taipei_today', return_value=date(2026, 9, 3)):
                row = chip._tpex_inst('3529')
        finally:
            chip._src_fetch_json = original
        self.assertEqual(row['date'], '20260902')
        self.assertEqual(row['total'], -328399.0)

    def test_history_filename_uses_source_date(self):
        with tempfile.TemporaryDirectory() as td, \
                mock.patch.object(st_server, 'CHIP_HISTORY_PATH', td):
            st_server._chip_history_record('3529', {
                'instDate': '20260902',
                'inst': {'foreign': -251839, 'trust': -40000,
                         'dealer': -36560, 'total': -328399},
            })
            self.assertTrue(os.path.isfile(os.path.join(td, '20260902.json')))
            self.assertFalse(os.path.isfile(os.path.join(td, '20260903.json')))
            with open(os.path.join(td, '20260902.json'), encoding='utf-8') as f:
                self.assertEqual(json.load(f)['3529']['total'], -328399)


class TestServerMacroSourceContract(unittest.TestCase):
    def test_fixed_source_failure_never_falls_back_to_unadjusted_yahoo(self):
        with mock.patch.object(
            macro,
            '_resolve_series_points',
            return_value=([], 'canonical:yahoo_adj · 指定來源無資料'),
        ), mock.patch.object(macro, '_yahoo_closes') as raw_yahoo:
            points, source = st_server._macro_resolve_points(
                'baml_hy', years=5, force_live=True,
            )
        raw_yahoo.assert_not_called()
        self.assertEqual(points, [])
        self.assertEqual(source, 'canonical:yahoo_adj · 指定來源無資料')


if __name__ == '__main__':
    unittest.main()
