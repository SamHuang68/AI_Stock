# -*- coding: utf-8 -*-
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import industry_revenue  # noqa: E402
import sector_flow  # noqa: E402


FIXTURE = os.path.join(os.path.dirname(__file__), 'fixtures', 'industry_revenue_sample.json')


class IndustryRevenueTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(FIXTURE, 'r', encoding='utf-8') as f:
            cls.sample = json.load(f)

    def test_aggregate_market_and_industry_metrics(self):
        agg = industry_revenue.build_from_openapi_rows(self.sample)
        self.assertTrue(agg['ok'])
        self.assertEqual(agg['periodLabel'], '2026-08')
        mkt = agg['market']
        self.assertEqual(mkt['monthRevThousand'], 170000.0)
        self.assertAlmostEqual(mkt['monthRevYi'], 1.7, places=2)
        self.assertEqual(mkt['growCount'], 2)
        self.assertEqual(mkt['declineCount'], 1)
        semi_key = sector_flow.normalize_sector_name('半導體業')
        semi = agg['byIndustryKey'][semi_key]
        self.assertEqual(semi['stockCount'], 2)
        self.assertEqual(semi['growCount'], 1)
        self.assertEqual(semi['declineCount'], 1)
        self.assertAlmostEqual(semi['sharePct'], 120000.0 / 170000.0 * 100.0, places=2)
        self.assertEqual(semi['leader']['code'], '2330')

    def test_attach_sector_revenue_uses_same_normalize_key(self):
        agg = industry_revenue.build_from_openapi_rows(self.sample)
        rows = industry_revenue.attach_sector_revenue([
            {'name': '半導體', 'changePct': 1.2},
            {'name': '金融保險', 'changePct': -0.5},
        ], agg)
        self.assertIsNotNone(rows[0].get('revenueYoyPct'))
        self.assertIsNotNone(rows[0].get('revenueSharePct'))
        self.assertEqual(rows[0]['revenueGrowCount'], 1)
        self.assertEqual(rows[0]['revenueDeclineCount'], 1)
        self.assertIsNotNone(rows[1].get('revenueYoyPct'))

    def test_flash_title_mentions_period_and_no_scraper(self):
        agg = industry_revenue.build_from_openapi_rows(self.sample)
        title = industry_revenue.market_flash_title(agg)
        self.assertIn('2026-08', title or '')
        self.assertIn('OpenAPI', title or '')
        item = industry_revenue.market_flash_item(agg)
        self.assertEqual(item['source'], 'industry_revenue_openapi')


if __name__ == '__main__':
    unittest.main()
