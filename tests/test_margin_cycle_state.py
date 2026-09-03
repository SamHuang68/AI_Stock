# -*- coding: utf-8 -*-
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import margin_cycle  # noqa: E402


class MarginCycleStateTest(unittest.TestCase):
    def test_margin_balance_state_reports_percentile_and_four_week_direction(self):
        start = date(2025, 8, 1)
        rows = [
            {'date': (start + timedelta(days=i)).isoformat(), 'margin_amt_k': 1000 + i * 5}
            for i in range(370)
        ]
        state = margin_cycle.margin_balance_state(rows)
        self.assertTrue(state['available'])
        self.assertGreater(state['percentile52w'], 95)
        self.assertGreater(state['change4wPct'], 2)
        self.assertEqual(state['direction'], 'rising')
        self.assertEqual(state['role'], 'risk_brake_only')

    def test_missing_history_is_explicit(self):
        state = margin_cycle.margin_balance_state([])
        self.assertFalse(state['available'])
        self.assertEqual(state['reason'], 'local_margin_history_unavailable')


if __name__ == '__main__':
    unittest.main()
