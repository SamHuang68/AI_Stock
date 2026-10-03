"""投組工程核心：以獨立手算數字驗證現金、時序與未知值。"""
import copy
import importlib
import math
import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
p = importlib.import_module('突破組合研究')

DAYS = ['2026-03-02', '2026-03-03', '2026-03-04', '2026-03-05', '2026-03-06']


def dataset(closes, opens=None, symbol='2330', days=None):
    opens = opens or closes
    days = days or DAYS
    rows = [{'date': day, 'open': op, 'high': max(op, close) + 1,
             'low': min(op, close) - 1, 'close': close, 'volume': 1000,
             'source': 'TWSE', 'priceBasis': 'unadjusted', 'issues': []}
            for day, op, close in zip(days, opens, closes)]
    return {'rows': rows, 'calendar_years': [2026], 'action_days': [],
            'action_coverage': [days[0], days[-1], 'TWSE'],
            'action_coverage_kind': 'etf' if symbol == '0050' else 'stock'}


def observations(closes, signals=None, vidyas=None):
    signals = signals if signals is not None else [True] + [False] * (len(closes) - 1)
    vidyas = vidyas if vidyas is not None else [1] * len(closes)
    return [{'date': d, 'close': close, 'entrySignal': signal, 'vidya': vidya, 'reason': None}
            for d, close, signal, vidya in zip(DAYS, closes, signals, vidyas)]


def run_case(closes, opens=None, signals=None, vidyas=None, cost=.01, config=None):
    return p.simulate_portfolio({'2330': dataset(closes, opens)}, DAYS[:len(closes)],
                               {'2330': observations(closes, signals, vidyas)}, side_cost=cost,
                               config={'initialCapital': 1000, 'allocationFraction': 1, **(config or {})})


class PortfolioHandCalculationTests(unittest.TestCase):
    def test_both_side_cost_cash_and_close_stop_next_open(self):
        result = run_case([100, 110, 90, 100], [100, 100, 100, 105])
        # 1000 / 101 可買 9 股。買入 909，現金 91；收盤 90 觸發 8% 停損。
        # 下日開盤賣出 9×105×0.99=935.55，總現金 1026.55。
        self.assertEqual(result['closedTrades'], 1)
        trade = result['trades'][0]
        self.assertEqual((trade['signalDate'], trade['entryDate'], trade['exitDate']), (DAYS[0], DAYS[1], DAYS[3]))
        self.assertEqual(trade['shares'], 9)
        self.assertAlmostEqual(trade['entryCost'], 9)
        self.assertAlmostEqual(trade['exitCost'], 9.45)
        self.assertAlmostEqual(trade['netPnl'], 26.55)
        self.assertAlmostEqual(result['finalEquity'], 1026.55)
        self.assertEqual(trade['entryPrice'], 100)
        self.assertEqual(trade['exitPrice'], 105)

    def test_daily_mark_to_market_drawdown_not_closed_trade_curve(self):
        result = run_case([100, 110, 90, 100], [100, 100, 100, 105])
        self.assertEqual([r['equity'] for r in result['curve'][:3]], [1000, 1081, 901])
        self.assertAlmostEqual(result['maxDrawdownPct'], 180 / 1081 * 100)
        self.assertAlmostEqual(result['curve'][2]['dailyReturn'], 901 / 1081 - 1)

    def test_cash_competition_sorted_by_symbol_not_input_order_or_today_close(self):
        data = {'2222': dataset([100, 10000]), '1111': dataset([100, 100])}
        obs = {s: observations([100, 100]) for s in data}
        result = p.simulate_portfolio(data, DAYS[:2], obs, side_cost=0,
                                     config={'initialCapital': 100, 'allocationFraction': 1})
        self.assertEqual(result['openPositions'][0]['symbol'], '1111')
        self.assertEqual(result['curve'][1]['cash'], 0)
        self.assertEqual(result['rejected'][0]['symbol'], '2222')

    def test_lot_floor_keeps_cash_nonnegative(self):
        result = run_case([30, 30], cost=.01, config={'lotSize': 10})
        self.assertEqual(result['openPositions'][0]['shares'], 30)
        self.assertAlmostEqual(result['curve'][1]['cash'], 91)

    def test_no_same_bar_exit_and_no_intraday_stop_guess(self):
        data = dataset([100, 100, 100])
        data['rows'][1]['low'] = 50
        result = p.simulate_portfolio({'2330': data}, DAYS[:3], {'2330': observations([100, 100, 100])},
                                     side_cost=0, config={'initialCapital': 1000, 'allocationFraction': 1})
        self.assertEqual(result['closedTrades'], 0)
        self.assertEqual(len(result['openPositions']), 1)
        self.assertFalse(result['pending'])

    def test_vidya_exit_uses_next_open_and_final_signal_stays_pending(self):
        result = run_case([100, 100, 99], vidyas=[90, 90, 100], cost=0)
        self.assertEqual(result['closedTrades'], 0)
        self.assertEqual(result['pending'][0]['kind'], 'exit')
        self.assertEqual(result['pending'][0]['signalDate'], DAYS[2])
        self.assertEqual(result['finalEquity'], 990)

    def test_missing_next_bar_does_not_fill_from_later_bar(self):
        data = dataset([100, 100, 100])
        del data['rows'][1]
        result = p.simulate_portfolio({'2330': data}, DAYS[:3], {'2330': observations([100, 100, 100])},
                                     side_cost=0, config={'initialCapital': 1000})
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['closedTrades'], 0)
        self.assertEqual(result['openPositions'], [])
        self.assertIsNone(result['totalReturnPct'])
        self.assertEqual(result['curve'][2]['cash'], 1000)

    def test_held_missing_close_is_null_no_previous_price_fill(self):
        data = dataset([100, 100, 100, 101])
        data['rows'][2]['close'] = None
        result = p.simulate_portfolio({'2330': data}, DAYS[:4], {'2330': observations([100, 100, 100, 101])},
                                     side_cost=0, config={'initialCapital': 1000, 'allocationFraction': 1})
        self.assertIsNone(result['curve'][2]['equity'])
        self.assertIsNone(result['curve'][3]['dailyReturn'])
        self.assertIsNone(result['maxDrawdownPct'])
        self.assertEqual(result['finalEquity'], 1010)
        self.assertEqual(result['status'], 'unknown')

    def test_company_action_unknown_rights_never_becomes_fictitious_gain(self):
        data = dataset([100, 100, 50, 51])
        data['action_days'] = [DAYS[2]]
        result = p.simulate_portfolio({'2330': data}, DAYS[:4], {'2330': observations([100, 100, 50, 51])},
                                     side_cost=0, config={'initialCapital': 1000, 'allocationFraction': 1})
        self.assertIsNone(result['curve'][2]['equity'])
        self.assertIsNone(result['finalEquity'])
        self.assertIn('股數', result['openPositions'][0]['accountingUnknown'])

    def test_zero_net_zero_no_trades_and_unknown_are_distinct(self):
        empty = run_case([100, 100], signals=[False, False], cost=0)
        self.assertEqual(empty['tradeStatus'], 'no_trades')
        self.assertEqual(empty['totalReturnPct'], 0)
        self.assertIsNone(empty['winRatePct'])
        # 出場價格 100×1.01/.99 恰好抵銷兩邊 1% 成本。
        flat = run_case([100, 90, 100], [100, 100, 100 * 1.01 / .99], cost=.01)
        self.assertEqual(flat['closedTrades'], 1)
        self.assertEqual(flat['netZeroTrades'], 1)
        self.assertAlmostEqual(flat['trades'][0]['netPnl'], 0)
        self.assertGreater(flat['trades'][0]['grossPnl'], 0)
        self.assertEqual(flat['winRatePct'], 0)
        unknown = run_case([100, 100], vidyas=[None, None])
        self.assertIsNone(unknown['totalReturnPct'])
        self.assertEqual(unknown['status'], 'unknown')

    def test_sale_proceeds_can_fund_next_sorted_entry_same_open(self):
        data = {'1111': dataset([100, 90, 100], [100, 100, 100]), '2222': dataset([100, 100, 100])}
        obs = {'1111': observations([100, 90, 100]), '2222': observations([100, 100, 100], [False, True, False])}
        result = p.simulate_portfolio(data, DAYS[:3], obs, side_cost=0,
                                     config={'initialCapital': 1000, 'allocationFraction': 1, 'maxPositions': 1})
        self.assertEqual(result['closedTrades'], 1)
        self.assertEqual(result['openPositions'][0]['symbol'], '2222')
        self.assertEqual(result['openPositions'][0]['entryDate'], DAYS[2])

    def test_prior_equity_sizing_does_not_use_current_close(self):
        data = {'1111': dataset([100, 110, 1000], [100, 100, 100]), '2222': dataset([100, 100, 100])}
        obs = {'1111': observations([100, 110, 1000]), '2222': observations([100, 100, 100], [False, True, False])}
        result = p.simulate_portfolio(data, DAYS[:3], obs, side_cost=0,
                                     config={'initialCapital': 1000, 'allocationFraction': .5, 'capitalBasis': 'previous_close_equity'})
        second = next(row for row in result['openPositions'] if row['symbol'] == '2222')
        self.assertEqual(second['sizingEquity'], 1050)
        self.assertEqual(second['shares'], 5)

    def test_partial_allocation_three_share_lot_and_losing_costs(self):
        result = run_case([47, 50, 43, 45], [47, 47, 45, 45], cost=.0025,
                          config={'initialCapital': 5000, 'allocationFraction': .4, 'lotSize': 3})
        trade = result['trades'][0]
        # 2000 元預算、每三股一單位：42 股原價 1974，買費 4.935。
        # 45 元賣出，原價 1890、賣費 4.725，淨損 84+9.66=93.66。
        self.assertEqual(trade['shares'], 42)
        self.assertAlmostEqual(trade['entryCash'], 1978.935)
        self.assertAlmostEqual(trade['exitCash'], 1885.275)
        self.assertAlmostEqual(trade['netPnl'], -93.66)
        self.assertAlmostEqual(result['finalEquity'], 4906.34)
        self.assertAlmostEqual(result['totalReturnPct'], -1.8732)
        self.assertAlmostEqual(result['maxDrawdownPct'], 294 / 5121.065 * 100)

    def test_one_price_entry_is_unconfirmed_not_a_zero_cost_fill(self):
        data = dataset([100, 100, 110])
        data['rows'][1].update(open=100, high=100, low=100, close=100)
        result = p.simulate_portfolio({'2330': data}, DAYS[:3], {'2330': observations([100, 100, 110])},
                                     side_cost=0, config={'initialCapital': 1000, 'allocationFraction': 1})
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(result['openPositions'], [])
        self.assertEqual(result['finalEquity'], 1000)
        self.assertIsNone(result['totalReturnPct'])
        self.assertIn('一價棒', result['rejected'][0]['reason'])

    def test_one_price_exit_retains_pending_until_verified_open(self):
        data = dataset([100, 90, 80, 85], [100, 100, 80, 85])
        data['rows'][2].update(high=80, low=80)
        result = p.simulate_portfolio({'2330': data}, DAYS[:4], {'2330': observations([100, 90, 80, 85])},
                                     side_cost=0, config={'initialCapital': 1000, 'allocationFraction': 1})
        self.assertEqual(result['trades'][0]['exitDate'], DAYS[3])
        self.assertEqual(result['trades'][0]['netPnl'], -150)
        self.assertEqual(result['curve'][2]['equity'], 800)
        self.assertEqual(result['status'], 'unknown')
        self.assertIsNone(result['maxDrawdownPct'])

    def test_zero_volume_never_confirms_an_open_fill(self):
        data = dataset([100, 100, 100])
        data['rows'][1]['volume'] = 0
        result = p.simulate_portfolio({'2330': data}, DAYS[:3], {'2330': observations([100, 100, 100])})
        self.assertEqual(result['openPositions'], [])
        self.assertIn('無成交', result['rejected'][0]['reason'])
        self.assertEqual(result['status'], 'unknown')

    def test_no_price_at_tail_keeps_position_unvalued_and_does_not_sell(self):
        data = dataset([100, 100])
        result = p.simulate_portfolio({'2330': data}, DAYS[:3], {'2330': observations([100, 100, 100])},
                                     side_cost=.0025, config={'initialCapital': 1000, 'allocationFraction': 1})
        self.assertEqual(result['closedTrades'], 0)
        self.assertEqual(len(result['openPositions']), 1)
        self.assertIsNone(result['finalEquity'])
        self.assertIsNone(result['curve'][-1]['equity'])
        self.assertEqual(result['curve'][-1]['cash'], 97.75)


class FormulaAndQualityTests(unittest.TestCase):
    def test_twenty_sma_nine_change_cmo_hand_calculation(self):
        # 前二十棒 SMA=10，最後一棒+2且最近九個變化全為上漲：alpha=2/21。
        self.assertEqual(p.vidya_value([10] * 20), 10)
        self.assertAlmostEqual(p.vidya_value([10] * 20 + [12]), 10 + 4 / 21)
        self.assertEqual(p.vidya_value([10] * 25), 10)
        # 接著 -1：九期 CMO 的絕對值為 1/3，遞迴後為 13516/1323。
        self.assertAlmostEqual(p.vidya_value([10] * 20 + [12, 11]), 13516 / 1323)

    def test_information_ratio_uses_aligned_daily_returns(self):
        result = p.daily_information_ratio([{'date': d, 'dailyReturn': r} for d, r in zip(DAYS, [None, 0, .02, -.01])],
                                      [{'date': d, 'dailyReturn': r} for d, r in zip(DAYS, [None, 0, .01, -.01])])
        # 超額日報酬 [0,.01,0]，平均 .01/3，樣本變異 .0001/3。
        self.assertAlmostEqual(result['value'], (.01 / 3) / math.sqrt(.0001 / 3) * math.sqrt(252))
        self.assertEqual(result['n'], 3)
        zero = p.daily_information_ratio([{'date': d, 'dailyReturn': 0} for d in DAYS],
                                    [{'date': d, 'dailyReturn': 0} for d in DAYS])
        self.assertIsNone(zero['value'])

    def test_information_ratio_negative_and_positive_independent_oracle(self):
        curve = [{'date': d, 'dailyReturn': r} for d, r in zip(DAYS, [None, -.01, 0, .03])]
        benchmark = [{'date': d, 'dailyReturn': r} for d, r in zip(DAYS, [None, 0, 0, .01])]
        # 超額 [-.01,0,.02] 的樣本變異為 7/30000，年化比率=2×sqrt(3)。
        result = p.daily_information_ratio(curve, benchmark)
        self.assertAlmostEqual(result['value'], 2 * math.sqrt(3))
        curve[1]['dailyReturn'] = float('nan')
        self.assertIsNone(p.daily_information_ratio(curve, benchmark)['value'])

    def test_risk_free_sharpe_uses_compounded_daily_rate_and_sample_deviation(self):
        curve = [{'date': d, 'dailyReturn': r} for d, r in zip(DAYS, [None, 0, .02, .04])]
        # 年率 .04060401、每年四期，單期利率恰為 .01。
        # 超額 [-.01,.01,.03] 平均 .01、樣本標準差 .02，年化夏普為 1。
        result = p.daily_sharpe(curve, annual_risk_free_rate=.04060401, periods_per_year=4)
        self.assertAlmostEqual(result['dailyRiskFreeRate'], .01)
        self.assertAlmostEqual(result['meanDailyExcessReturn'], .01)
        self.assertAlmostEqual(result['sampleStandardDeviation'], .02)
        self.assertAlmostEqual(result['value'], 1)
        self.assertEqual(result['n'], 3)
        self.assertEqual(result['periodsPerYear'], 4)
        self.assertEqual(result['baselineDate'], DAYS[0])
        self.assertIsNone(result['reason'])

    def test_default_sharpe_is_distinct_from_0050_information_ratio(self):
        curve = [{'date': d, 'dailyReturn': r} for d, r in zip(DAYS, [None, -.01, 0, .03])]
        benchmark = [{'date': d, 'dailyReturn': r} for d, r in zip(DAYS, [None, 0, 0, .01])]
        # 投組平均 1/150、樣本變異 13/30000；零利率夏普=sqrt(336/13)。
        self.assertAlmostEqual(p.daily_sharpe(curve)['value'], math.sqrt(336 / 13))
        self.assertAlmostEqual(p.daily_information_ratio(curve, benchmark)['value'], 2 * math.sqrt(3))

    def test_full_cash_curve_matches_backtest_daily_sample_fixture(self):
        # 與既有 backtest_v3.runLS 實際交叉驗算同一組四根日線。
        # 第一根只作基準，其後每日報酬 [0,.02,.04]，不是四個樣本。
        result = run_case([100, 100, 102, 106.08], [100, 100, 100, 100], cost=0,
                          config={'annualRiskFreeRate': .04060401, 'periodsPerYear': 4})
        self.assertEqual(len(result['curve']), 4)
        self.assertEqual(result['sharpeEvidence']['n'], 3)
        self.assertAlmostEqual(result['dailySharpe'], 1)
        self.assertEqual(result['sharpeEvidence']['baselineDate'], DAYS[0])

    def test_risk_free_sharpe_no_trade_constant_missing_and_short_samples_are_null(self):
        for returns, had_entry, code in [([0, 0, 0], False, 'no_trades'),
                                         ([.01, .01, .01], True, 'zero_variance'),
                                         ([0, None, .01], True, 'missing_daily_return'),
                                         ([.01], True, 'insufficient_samples')]:
            with self.subTest(code=code):
                curve = [{'date': d, 'dailyReturn': r} for d, r in zip(DAYS, [None] + returns)]
                result = p.daily_sharpe(curve, annual_risk_free_rate=.05, had_entry=had_entry)
                self.assertIsNone(result['value'])
                self.assertEqual(result['reasonCode'], code)
        no_trade = run_case([100, 100, 100], signals=[False, False, False], cost=0,
                            config={'annualRiskFreeRate': .05})
        self.assertIsNone(no_trade['dailySharpe'])
        self.assertEqual(no_trade['sharpeEvidence']['reasonCode'], 'no_trades')

    def test_sharpe_of_open_position_does_not_require_closed_trade_or_0050(self):
        days = DAYS + ['2026-03-09']
        data = dataset([10, 10, 10, 12, 13, 13], [10, 10, 10, 12, 12, 13], days=days)
        report = p.build_portfolio({'2330': data}, days, sample_start=3,
                                   config={'vidyaLength': 2, 'cmoLength': 1, 'warmupBars': 3})
        result = report['rules'][0]['scenarios']['gross']
        # 首根收盤僅基準；其後兩日報酬 [r,0]，夏普=sqrt(126)。
        self.assertAlmostEqual(result['dailySharpe'], math.sqrt(126))
        self.assertEqual(result['sharpeEvidence']['n'], 2)
        self.assertEqual(result['closedTrades'], 0)
        self.assertEqual(result['tradeStatus'], 'open_only')
        self.assertIsNone(result['informationRatio'])
        self.assertIn('0050', result['benchmarkEvidence']['reason'])
        self.assertNotIn('dailyExcessSharpe', result)

    def test_unknown_price_gap_cannot_produce_sharpe_from_partial_days(self):
        data = dataset([100, 100, 100, 101])
        data['rows'][2]['close'] = None
        result = p.simulate_portfolio({'2330': data}, DAYS[:4], {'2330': observations([100, 100, 100, 101])},
                                     side_cost=0, config={'initialCapital': 1000, 'allocationFraction': 1})
        self.assertIsNone(result['dailySharpe'])
        self.assertEqual(result['sharpeEvidence']['reasonCode'], 'missing_daily_return')
        self.assertEqual(result['sharpeEvidence']['n'], 0)

    def test_report_keeps_risk_free_sharpe_and_benchmark_ratio_separate(self):
        days = DAYS + ['2026-03-09']
        data = {symbol: dataset([10, 10, 10, 12, 13, 13], [10, 10, 10, 12, 12, 13], symbol=symbol, days=days)
                for symbol in ('2330', '0050')}
        report = p.build_portfolio(data, days, sample_start=3,
                                   config={'vidyaLength': 2, 'cmoLength': 1, 'warmupBars': 3})
        result = report['rules'][0]['scenarios']['gross']
        # 兩檔各買 41666 股，共 83332 股；基準單買 83333 股。
        # 首根收盤僅基準；投組兩日報酬 [.083332,0]，相對差 [-.000001,0]。
        self.assertAlmostEqual(result['dailySharpe'], math.sqrt(126))
        self.assertAlmostEqual(result['informationRatio'], -math.sqrt(126))
        self.assertEqual(result['sharpeEvidence']['annualRiskFreeRate'], 0)
        self.assertEqual(result['benchmarkEvidence']['benchmarkSymbol'], '0050')
        self.assertEqual(result['benchmarkEvidence']['n'], 2)

    def test_etf_source_date_suspension_and_basis_do_not_default_valid(self):
        for field, value, text in [('priceBasis', None, '原始'), ('sourceDate', '2026-03-01', '來源日期'),
                                    ('suspended', True, '停止交易')]:
            data = dataset([100, 100])
            data['rows'][0][field] = value
            self.assertIn(text, p._quality('2330', data, 0))
        data = dataset([100], symbol='0050')
        del data['action_coverage_kind']
        self.assertIn('ETF', p._quality('0050', data, 0))

    def test_bounded_configuration_and_duplicates(self):
        for config in ({'maxPositions': 21}, {'warmupBars': 9999}, {'initialCapital': float('nan')},
                       {'lotSize': True}, {'surprise': 1}, {'annualRiskFreeRate': -.01},
                       {'annualRiskFreeRate': 1.01}, {'annualRiskFreeRate': float('nan')},
                       {'annualRiskFreeRate': True}, {'periodsPerYear': 0},
                       {'periodsPerYear': 367}, {'periodsPerYear': 2.5}):
            with self.assertRaises(ValueError):
                p._config(config)
        data = dataset([100])
        data['rows'] *= 2
        with self.assertRaises(ValueError):
            p.build_portfolio({'2330': data}, DAYS[:1])

    def test_prefix_invariance_and_fixed_split_not_optimized(self):
        data = dataset([10, 10, 10, 12, 20])
        settings = {'vidyaLength': 2, 'cmoLength': 1, 'warmupBars': 3, 'testStart': DAYS[4]}
        prefix = p.build_portfolio({'2330': data}, DAYS, sample_start=3, as_of=DAYS[3], config=settings)
        changed = copy.deepcopy(data)
        changed['rows'][-1].update(open=10000, high=10001, low=9999, close=10000)
        changed['action_days'] = [DAYS[4]]
        changed['calendar_years'].append(2027)
        changed['action_coverage'][1] = '2027-12-31'
        repeated = p.build_portfolio({'2330': changed}, DAYS, sample_start=3, as_of=DAYS[3], config=settings)
        self.assertEqual(prefix, repeated)
        full = p.build_portfolio({'2330': data}, DAYS, sample_start=3, config=settings)
        self.assertFalse(full['evaluation']['optimized'])
        self.assertEqual(full['evaluation']['testStart'], DAYS[4])
        training = full['evaluation']['training']['rules'][0]['scenarios']['gross']
        self.assertEqual(training['curve'], prefix['rules'][0]['scenarios']['gross']['curve'])

    def test_actual_cross_uses_previous_close_and_vidya(self):
        data = dataset([10, 10, 10, 12, 13], [10, 10, 10, 12, 12])
        report = p.build_portfolio({'2330': data}, DAYS, sample_start=3,
                                   config={'vidyaLength': 2, 'cmoLength': 1, 'warmupBars': 3})
        obs = report['assets'][0]['rows']
        self.assertTrue(obs[0]['entrySignal'])
        self.assertFalse(obs[1]['entrySignal'])
        position = report['rules'][0]['scenarios']['gross']['openPositions'][0]
        self.assertEqual(position['signalDate'], DAYS[3])
        self.assertEqual(position['entryDate'], DAYS[4])

    def test_benchmark_without_next_bar_is_not_zero_return(self):
        data = dataset([100], symbol='0050')
        result = p.simulate_portfolio({'0050': data}, DAYS[:1], {'0050': observations([100])},
                                     benchmark_symbol='0050')
        self.assertEqual(result['status'], 'insufficient')
        self.assertIsNone(result['totalReturnPct'])
        self.assertEqual(result['pending'][0]['kind'], 'entry')


class SavedAdapterTests(unittest.TestCase):
    def test_missing_db_never_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '不存在.sqlite'
            result = p.build_saved_portfolio(path)
            self.assertEqual(result['status'], 'unavailable')
            self.assertFalse(path.exists())

    def test_adapter_readonly_snapshot_and_shared_loader(self):
        # 此 stub 只替代兄弟模組載入；真實 SQLite 連線必須禁止寫入。
        called = []
        def loader(conn, symbol, cutoff):
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute('CREATE TABLE 不得建立(x)')
            called.append((symbol, cutoff))
            return {**dataset([100] * 5, symbol=symbol), 'session_dates': DAYS}
        events = types.ModuleType('K線事件')
        events.freshness = lambda conn, symbol, clock: {'expectedSession': DAYS[-1]}
        events.range_start = lambda period, cutoff, start: datetime(2021, 3, 6).date()
        breakout = types.ModuleType('突破觀察')
        breakout.load_dataset = loader
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '快取.sqlite'
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute('CREATE TABLE market_sessions(session_date TEXT,source TEXT)')
                conn.executemany('INSERT INTO market_sessions VALUES(?,?)', [(d, 'TWSE') for d in DAYS])
            before = path.read_bytes()
            with patch.dict(sys.modules, {'K線事件': events, '突破觀察': breakout}):
                result = p.build_saved_portfolio(path, now=datetime(2026, 3, 6, 20, tzinfo=p.TZ),
                                                 config={'vidyaLength': 2, 'cmoLength': 1, 'warmupBars': 3})
            self.assertNotEqual(result['status'], 'unavailable', result)
            self.assertEqual(called, [('0050', DAYS[-1]), ('2330', DAYS[-1])])
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
