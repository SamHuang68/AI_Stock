"""投組正式產業分類查找須正確處理上市／上櫃代號尾碼。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import portfolio


def bars(multiplier=1):
    return [(day, 0, 0, 0, multiplier * (100 + day * 0.2 + day % 5 * 0.03), 1000)
            for day in range(80)]


class PortfolioMarketSymbolTests(unittest.TestCase):
    def test_listed_and_otc_positions_use_actual_sector_and_name_maps(self):
        data = {'2330': bars(), '6488': bars(2), '^TWII': bars(3)}
        with patch.object(portfolio.datastore, 'get_bars_bulk', return_value=data) as read:
            result = portfolio.compute(
                [{'sym': '2330.TW', 'weight': 70}, {'sym': '6488.TWO', 'weight': 30}],
                sectors_map={'2330': '半導體業', '6488': '其他電子業'},
                names_map={'2330': '上市測試公司', '6488': '上櫃測試公司'},
            )
        read.assert_called_once_with(['2330', '6488', '^TWII'])
        self.assertEqual(result['sector'], {'半導體業': 70.0, '其他電子業': 30.0})
        self.assertEqual(result['stocks']['6488']['name'], '上櫃測試公司')
        self.assertEqual(result['skipped'], [])
        self.assertEqual(result['quality']['holdingCoveragePct'], 100.0)

    def test_bare_and_otc_forms_merge_without_losing_portfolio_weight(self):
        data = {'6488': bars(), '^TWII': bars(2)}
        with patch.object(portfolio.datastore, 'get_bars_bulk', return_value=data) as read:
            result = portfolio.compute(
                [{'sym': '6488.TWO', 'weight': 3}, {'sym': '6488', 'weight': 1}],
                sectors_map={'6488': '其他電子業'},
            )
        read.assert_called_once_with(['6488', '^TWII'])
        self.assertEqual(set(result['stocks']), {'6488'})
        self.assertEqual(result['stocks']['6488']['weight'], 100.0)
        self.assertEqual(result['sector'], {'其他電子業': 100.0})

    def test_market_letters_inside_symbol_are_not_removed(self):
        with patch.object(portfolio.datastore, 'get_bars_bulk', return_value={}) as read:
            result = portfolio.compute([{'sym': 'ABC.TWOX', 'weight': 1}])
        read.assert_called_once_with(['ABC.TWOX', '^TWII'])
        self.assertIn('error', result)


if __name__ == '__main__':
    unittest.main()
