# -*- coding: utf-8 -*-
"""H0：chart_registry primaryKey 不得選到右軸指數。"""
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
import chart_registry as cr  # noqa: E402


class TestChartRegistry(unittest.TestCase):
    def test_prefer_yoy_not_twii(self):
        series = [
            {'key': 'yoy', 'scale': 'left', 'points': [{'date': '2026-01-01', 'value': 3.68}]},
            {'key': 'twii', 'scale': 'right', 'points': [{'date': '2026-01-01', 'value': 43654.8}]},
        ]
        p = cr.pick_primary_series(series, '__TW_MARGIN_MIX__')
        self.assertIsNotNone(p)
        self.assertEqual(p['key'], 'yoy')
        self.assertNotEqual(p['points'][-1]['value'], 43654.8)

    def test_never_fallback_right_axis(self):
        series = [
            {'key': 'twii', 'scale': 'right', 'points': [{'date': '2026-01-01', 'value': 43654.8}]},
        ]
        p = cr.pick_primary_series(series, '__TW_MARGIN_MIX__')
        self.assertIsNone(p)

    def test_margin_cycle_primary(self):
        series = [
            {'key': 'margin_ratio', 'scale': 'left', 'points': [{'date': '2026-01-01', 'value': 167.3}]},
            {'key': 'twii', 'scale': 'right', 'points': [{'date': '2026-01-01', 'value': 20000}]},
        ]
        p = cr.pick_primary_series(series, '__TW_MARGIN_CYCLE__')
        self.assertEqual(p['key'], 'margin_ratio')

    def test_holders_primary(self):
        self.assertEqual(cr.primary_key_for('__HOLDERS_2330__'), 'major_pct')
        series = [
            {'key': 'holders', 'scale': 'left', 'points': [{'date': '2026-01-01', 'value': 900000}]},
            {'key': 'major_pct', 'scale': 'right', 'points': [{'date': '2026-01-01', 'value': 42.5}]},
        ]
        # holders primary is major_pct even if right scale
        p = cr.pick_primary_series(series, '__HOLDERS_2330__')
        self.assertEqual(p['key'], 'major_pct')


if __name__ == '__main__':
    unittest.main()
