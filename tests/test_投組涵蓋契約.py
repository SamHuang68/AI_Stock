import inspect
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import portfolio
from tests.已核對資料 import 價格資料, 交易日
from 台股日線 import stamp


def load_tests(loader, tests, pattern):
    # 裸函式須包成 FunctionTestCase，unittest 與驗證計畫才會收集（審查 TQ-02）。
    suite = unittest.TestSuite()
    module = sys.modules[__name__]
    for name, fn in inspect.getmembers(module, inspect.isfunction):
        if name.startswith('test_'):
            suite.addTest(unittest.FunctionTestCase(fn, description=name))
    return suite


def bars(returns, start=0, price=100):
    # 以合成日曆的交易日（週一至週五）排列；start 是交易日位移。
    values = [price]
    for value in returns:
        values.append(values[-1] * (1 + value))
    days = 交易日('2026-01-05', start + len(values))[start:]
    return [(stamp(day), x, x, x, x, 1000) for day, x in zip(days, values)]


def compute(holdings, data):
    # 2026-10-13 起 compute 必須以資料庫核對交易日曆與價格品質（b3bdcf7）；
    # 舊版只 patch get_bars_bulk、沒有日曆，結果一律為空。改用共用的已核對資料夾具，斷言不變。
    with 價格資料(data):
        return portfolio.compute(holdings, sectors_map={'2330': '半導體', '6488': '半導體'})


def test_partial_history_keeps_complete_denominator_and_unknown_portfolio():
    data = {'2330': bars([.01, -.01] * 40), '^TWII': bars([.01, -.01] * 40)}
    result = compute([{'sym': '2330.TW', 'weight': 80}, {'sym': '6488.TWO', 'weight': 20}], data)
    assert result['stocks']['2330']['weight'] == 80
    assert result['sector']['半導體'] == 80
    assert result['skipped'] == ['6488']
    assert result['quality']['holdingCoveragePct'] == 80
    assert result['quality']['betaCoveragePct'] == 80
    assert result['portfolio']['vol'] is None
    assert result['portfolio']['var95'] is None


def test_all_missing_preserves_quality_and_does_not_become_zero():
    result = compute([{'sym': '2330', 'weight': 1}], {})
    assert result['quality']['holdingCoveragePct'] == 0
    assert not result['quality']['available']
    assert result['portfolio'] == {'vol': None, 'var95': None, 'days': 0}
    assert result['skipped'] == ['2330']


def test_alternating_returns_have_independent_expected_sample_risk():
    values = [.01, -.01] * 40
    result = compute([{'sym': '2330'}], {'2330': bars(values), '^TWII': bars(values)})
    sample_sd = .01 * math.sqrt(80 / 79)
    assert result['portfolio']['vol'] == round(sample_sd * math.sqrt(252) * 100, 1)
    assert result['portfolio']['var95'] == round(1.645 * sample_sd * 100, 2)
    assert result['stocks']['2330']['beta'] == 1


def test_equal_opposite_returns_cancel_without_zero_correlation_assumption():
    returns = [.01, -.01] * 40
    result = compute([{'sym': '2330'}, {'sym': '6488.TWO'}], {
        '2330': bars(returns), '6488': bars([-v for v in returns]), '^TWII': bars(returns)})
    assert result['corr']['2330|6488'] == -1
    assert result['portfolio']['vol'] == 0
    assert result['portfolio']['var95'] == 0


def test_constant_prices_have_zero_vol_but_undefined_correlation():
    data = {code: bars([0] * 80) for code in ['2330', '6488', '^TWII']}
    result = compute([{'sym': '2330'}, {'sym': '6488'}], data)
    assert result['portfolio']['vol'] == 0
    assert result['portfolio']['var95'] == 0
    assert result['corr']['2330|6488'] is None
    assert result['quality']['betaCoveragePct'] == 0


def test_short_common_window_is_not_zero_risk():
    result = compute([{'sym': '2330'}, {'sym': '6488'}], {
        '2330': bars([.01, -.01] * 35), '6488': bars([.01, -.01] * 35, start=60)})
    assert result['portfolio']['days'] == 10
    assert result['portfolio']['vol'] is None
    assert result['portfolio']['var95'] is None
    assert result['corr']['2330|6488'] is None


def test_invalid_weight_rejects_whole_unknown_denominator_before_fetch():
    for weight in (None, True, False, -1, 'bad', float('nan'), float('inf'), 10 ** 1000):
        with patch.object(portfolio.datastore, 'get_bars_bulk') as fetch:
            result = portfolio.compute([{'sym': '2330', 'weight': 1}, {'sym': '6488', 'weight': weight}])
            assert result['error']
            assert result['portfolio']['vol'] is None
            assert result['quality']['holdingCoveragePct'] is None
            fetch.assert_not_called()


def test_zero_weight_is_excluded_and_duplicate_suffixes_merge():
    result = compute([{'sym': '2330', 'weight': 0}, {'sym': '6488.TWO', 'weight': 20},
                      {'sym': ' 6488.two ', 'weight': 30}], {'6488': bars([.01, -.01] * 40)})
    assert set(result['stocks']) == {'6488'}
    assert result['stocks']['6488']['weight'] == 100
    assert result['skipped'] == []


def test_missing_price_never_bridges_two_day_return():
    assert portfolio._dated_rets({'1': 100, '2': None, '3': 121, '4': 133.1}, ['1', '2', '3', '4']) == {'4': 133.1 / 121 - 1}
