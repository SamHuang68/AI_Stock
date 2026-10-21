"""審查 QB-05：Yahoo 報價的異常門檻只對台股指數套用台股漲跌停門檻；海外標的的大波動不再被標為可疑。不連網。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import server  # noqa: E402


class QuoteAnomalyNonTwTest(unittest.TestCase):
    def test_foreign_large_moves_are_not_suspect(self):
        for price, prev, chg in ((130, 100, 30.0), (70, 100, -30.0), (115, 100, 15.0)):
            with self.subTest(chg=chg):
                self.assertEqual(server._anom_quote(price, prev, chg, 'foreign'), (False, None))

    def test_foreign_keeps_data_sanity_checks(self):
        self.assertTrue(server._anom_quote(0, 100, -100, 'foreign')[0])
        self.assertTrue(server._anom_quote(None, 100, None, 'foreign')[0])
        self.assertTrue(server._anom_quote(300, 100, 200, 'foreign')[0])      # 比值 3.0
        self.assertTrue(server._anom_quote(40, 100, -60, 'foreign')[0])       # 比值 0.4

    def test_tw_rules_unchanged(self):
        self.assertTrue(server._anom_quote(419, 267, 56.9, 'index')[0])
        self.assertTrue(server._anom_quote(114, 100, 14.0, 'index')[0])
        self.assertFalse(server._anom_quote(430, 429, 0.2, 'index')[0])
        self.assertTrue(server._anom_quote(130, 100, 30, 'stock')[0])
        self.assertFalse(server._anom_quote(110, 100, 10, 'stock')[0])

    def test_kind_by_symbol(self):
        self.assertEqual(server._anom_quote_kind('^TWII'), 'index')
        self.assertEqual(server._anom_quote_kind('^twoii'), 'index')
        for sym in ('^VIX', '^SOX', 'AAPL', 'BTC-USD', 'GC=F', 'TWD=X', ''):
            with self.subTest(sym=sym):
                self.assertEqual(server._anom_quote_kind(sym), 'foreign')


if __name__ == '__main__':
    unittest.main()
