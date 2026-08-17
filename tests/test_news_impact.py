# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import news_impact  # noqa: E402


class NewsImpactTest(unittest.TestCase):
    def test_material_disclosure_is_high_priority_without_direction(self):
        tag = news_impact.tag_item({
            'title': '公司發布財報與最新財測', 'cat': 'SEC 8-K',
            'code': 'NVDA', 'mkt': 'US', 'source': 'SEC',
        })
        self.assertEqual(tag['tier'], 'HIGH')
        self.assertIn('TW_AI_SPILLOVER', tag['scope'])
        self.assertEqual(tag['direction'], 'unknown')
        self.assertEqual(tag['source'], 'SEC')

    def test_generic_item_stays_low(self):
        tag = news_impact.tag_item({'title': 'Market chatter', 'mkt': 'US'})
        self.assertEqual(tag['tier'], 'LOW')


if __name__ == '__main__':
    unittest.main()
