# -*- coding: utf-8 -*-
"""以現有純介面驗證市場尾碼只從代號結尾移除一次。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))

import exposure_lab
import tdcc_holders
import wavedeck_bus


class MarketSuffixConsistencyTest(unittest.TestCase):
    CASES = (
        ('2330.TW', '2330'),
        ('6488.TWO', '6488'),
        ('5274.two', '5274'),
        ('AAPL', 'AAPL'),
        ('^TWOII', '^TWOII'),
        ('TXF', 'TXF'),
        ('ABC.TW.EXTRA', 'ABC.TW.EXTRA'),
        ('ABC.TWO.EXTRA', 'ABC.TWO.EXTRA'),
        ('ABC.TW.TWO', 'ABC.TW'),
    )

    def test_holders_chart_id_preserves_symbol_content(self):
        for raw, expected in self.CASES:
            with self.subTest(symbol=raw):
                self.assertEqual(tdcc_holders.holders_chart_id(raw),
                                 f'__HOLDERS_{expected}__')
        self.assertEqual(tdcc_holders.holders_chart_id(' 6488.two '),
                         '__HOLDERS_6488__')
        self.assertEqual(tdcc_holders._norm_code(None), '')

    def test_portfolio_lookthrough_keeps_weights_and_normalizes_only_suffix(self):
        for raw, expected in self.CASES:
            with self.subTest(symbol=raw):
                look = exposure_lab.portfolio_lookthrough({raw: {'weight': 12.5}})
                self.assertEqual(look['rows'][0]['symbol'], expected)
                self.assertEqual(look['rows'][0]['surfaceWeightPct'], 12.5)
                self.assertEqual(look['effectiveGrossExposurePct'], 12.5)
        canonical = exposure_lab.portfolio_lookthrough({'00685L': {'weight': 20}})
        for suffix in ('.TW', '.TWO'):
            self.assertEqual(
                exposure_lab.portfolio_lookthrough({'00685L' + suffix: {'weight': 20}}),
                canonical)

    def test_actual_holding_symbols_keeps_existing_eligibility(self):
        for raw, expected in self.CASES:
            with self.subTest(symbol=raw):
                portfolio = {'kind': 'actual', 'stocks': {raw: {'weight': 10},
                                                        'ZERO.TWO': {'weight': 0}}}
                self.assertEqual(exposure_lab._actual_holding_symbols(portfolio),
                                 {expected})
                self.assertEqual(exposure_lab._actual_holding_symbols(
                    {**portfolio, 'available': False}), set())
                self.assertEqual(exposure_lab._actual_holding_symbols(
                    {**portfolio, 'kind': 'model'}), set())

    def test_wavedeck_chip_preserves_symbol_and_position(self):
        for raw, expected in self.CASES:
            with self.subTest(symbol=raw):
                chip = wavedeck_bus.chip_from_report({
                    'symbol': raw, 'positions': {'account': -2}, 'mode': 'paper'})
                self.assertEqual(chip['symbol'], expected)
                self.assertEqual(chip['position_size'], 2)
                self.assertEqual(chip['direction'], 'SHORT')
                if expected.isdigit():
                    self.assertEqual(chip['market'], 'TW')
        self.assertEqual(wavedeck_bus._norm_sym(' 6488.two '), '6488')
        for raw in ('', '   ', None):
            self.assertEqual(wavedeck_bus._norm_sym(raw), 'TXF')


if __name__ == '__main__':
    unittest.main()
