# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import sector_flow  # noqa: E402


class SectorFlowTest(unittest.TestCase):
    def test_dated_twse_stock_table_normalizes_roc_date_and_signed_change(self):
        payload = {
            'stat': 'OK', 'date': '1150813',
            'tables': [{'fields': ['證券代號', '證券名稱', '成交金額', '收盤價', '漲跌(+/-)', '漲跌價差'],
                        'data': [['2330', '台積電', '12,345,678', '2,435.00', '-', '15.00']]}],
        }
        rows = sector_flow.parse_twse_daily_stock_table(payload)
        self.assertEqual(rows[0]['Date'], '20260813')
        self.assertEqual(rows[0]['TradeValue'], '12,345,678')
        self.assertEqual(rows[0]['Change'], -15.0)

    def test_official_industry_turnover_joins_index_names_without_double_counting_rollups(self):
        rows = sector_flow.attach_sector_metrics([
            {'name': '電子零組件類指數', 'changePct': 2.1},
            {'name': '電腦及週邊設備類指數', 'changePct': 1.5},
            {'name': '電子類指數', 'changePct': 1.8},
        ], industry_turnover_yi={'電子零組件業': 320, '電腦及週邊設備業': 280})
        out = sector_flow.build_sector_flow(rows, total_turnover_yi=600)
        self.assertTrue(out['flowEligible'])
        self.assertEqual(out['turnoverCoveragePct'], 100.0)
        self.assertEqual(out['turnoverScope'], 'TWSE_COMMON_STOCKS_BY_INDUSTRY')
        self.assertEqual(out['rows'][0]['marketSharePct'], 53.333)
        self.assertIsNone(out['rows'][2]['marketSharePct'])

    def test_price_only_rows_are_not_mislabeled_as_fund_flow(self):
        out = sector_flow.build_sector_flow([
            {'name': '半導體', 'changePct': 2.0},
            {'name': '金融', 'changePct': -1.0},
        ], source='TWSE MI_INDEX IND')
        self.assertEqual(out['mode'], 'participation_proxy')
        self.assertFalse(out['flowEligible'])
        self.assertIsNone(out['rows'][0]['marketSharePct'])
        self.assertEqual(out['participationPct'], 50.0)

    def test_turnover_share_hhi_and_rs20(self):
        out = sector_flow.build_sector_flow([
            {'name': 'A', 'changePct': 1, 'turnoverYi': 60, 'return20Pct': 8},
            {'name': 'B', 'changePct': 2, 'turnoverYi': 40, 'return20Pct': 3},
        ], total_turnover_yi=100, benchmark_return20_pct=2)
        self.assertTrue(out['flowEligible'])
        self.assertEqual(out['top3SharePct'], 100.0)
        self.assertEqual(out['hhi'], 5200.0)
        self.assertEqual(out['rows'][0]['rs20VsBenchmarkPct'], 6.0)

    def test_partial_or_proxy_turnover_is_not_called_fund_flow(self):
        partial = sector_flow.build_sector_flow([
            {'name': 'A', 'changePct': 1, 'turnoverYi': 60},
            {'name': 'B', 'changePct': -1},
        ], total_turnover_yi=100)
        proxy = sector_flow.build_sector_flow([
            {'name': 'A', 'changePct': 1, 'turnoverYi': 100},
        ], total_turnover_yi=100, proxy_basket=True)
        self.assertEqual(partial['mode'], 'partial_turnover')
        self.assertFalse(partial['flowEligible'])
        self.assertIsNone(partial['hhi'])
        self.assertFalse(proxy['flowEligible'])


if __name__ == '__main__':
    unittest.main()
