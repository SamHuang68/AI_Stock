# -*- coding: utf-8 -*-
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import key_levels  # noqa: E402


class KeyLevelsTest(unittest.TestCase):
    def _bars(self, n=35):
        start = date(2026, 6, 1)
        rows = []
        for i in range(n):
            close = 100.0 + i * 0.5 + (1 if i % 5 == 0 else 0)
            rows.append({
                'date': (start + timedelta(days=i)).isoformat(),
                'open': close - 0.5, 'high': close + 2.0,
                'low': close - 3.0, 'close': close, 'volume': 1000 + i,
            })
        return rows

    def test_classic_pivot_and_volatility_are_reproducible(self):
        rows = self._bars()
        out = key_levels.calculate_key_levels(rows, today=date(2026, 7, 5))
        ref = rows[-1]
        pivot = (ref['high'] + ref['low'] + ref['close']) / 3
        self.assertTrue(out['quality']['complete'])
        self.assertAlmostEqual(out['levels']['pivot'], pivot, places=2)
        self.assertAlmostEqual(out['levels']['r1'], 2 * pivot - ref['low'], places=2)
        self.assertAlmostEqual(out['levels']['s1'], 2 * pivot - ref['high'], places=2)
        self.assertIsNotNone(out['atr']['value'])
        self.assertIsNotNone(out['volatility']['realized20AnnualPct'])
        self.assertIsNotNone(out['volatility']['stateDownside20AnnualPct'])
        self.assertIsNotNone(out['volatility']['horizonForecastAnnualPct'])

    def test_missing_ohlc_does_not_publish_levels(self):
        out = key_levels.calculate_key_levels([{'date': '2026-08-01', 'close': 100}])
        self.assertFalse(out['quality']['complete'])
        self.assertIsNone(out['levels']['pivot'])

    def test_volatility_contract_includes_60d_gap_tail_and_normal_ranges(self):
        rows = self._bars(90)
        out = key_levels.calculate_key_levels(rows, today=date(2026, 9, 15))
        vol = out['volatility']
        self.assertIsNotNone(vol['realized60AnnualPct'])
        self.assertIsNotNone(vol['normal68Range'])
        self.assertIsNotNone(vol['normal95Range'])
        self.assertEqual(vol['gap60']['samples'], 60)
        self.assertEqual(vol['tail60']['samples'], 60)
        self.assertIn('not guarantees', vol['modelLimitations'])
        self.assertIsNotNone(vol['stateToForecastRatio'])
        self.assertEqual(vol['stateVolRole'], 'risk_brake_only')
        self.assertIn('long-run 20%', vol['horizonForecastMethod'])


if __name__ == '__main__':
    unittest.main()
