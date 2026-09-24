"""工程版組合研究：固定合成官方證據、原始價格與隔離 SQLite，禁止連外。"""
from __future__ import annotations

import copy
import json
import socket
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from tests import test_公司行動比較 as comparison_tests
from tests.test_突破成交研究 import datastore, daily
import 突破組合研究 as portfolio

YEAR = 'breakout_252'


def scenario(result, cost='gross'):
    return next(rule for rule in result['rules'] if rule['key'] == YEAR)['scenarios'][cost]


class BreakoutPortfolioTest(unittest.TestCase):
    def setUp(self):
        fixture = comparison_tests.官方比較測試(methodName='runTest')
        fixture.setUp()
        self.fixture = fixture
        self.datasets = {}
        for symbol in portfolio.SYMBOLS:
            adjustments = copy.deepcopy(fixture.adjustments)
            adjustments['symbol'] = symbol
            self.datasets[symbol] = {'rows': copy.deepcopy(fixture.rows), 'calendar_years': {2025, 2026},
                                     'action_days': set(), 'action_coverage': ('2025-01-01', '2026-12-31', 'TWSE'),
                                     'adjustments': adjustments}
        self.dates = [row['date'] for row in fixture.rows]
        network = patch.object(socket, 'create_connection', side_effect=AssertionError('測試禁止連外'))
        network.start()
        self.addCleanup(network.stop)

    def price(self, index, opening, close, symbols=portfolio.SYMBOLS):
        for symbol in symbols:
            self.datasets[symbol]['rows'][index].update(open=opening, close=close,
                high=max(opening, close) + 1, low=min(opening, close) - 1)

    def signal(self):
        self.price(270, 100, 102)
        self.price(271, 110, 111)

    def run_research(self, **kwargs):
        return portfolio.build_portfolio(self.datasets, self.dates, sample_start=253, **kwargs)

    def test_vidya_formula_flat_and_trend_have_hand_calculated_values(self):
        self.assertEqual(portfolio.vidya_value([100] * 5, length=2, cmo_length=1), 100)
        # SMA(1,2)=1.5；CMO=1，所以第3棒為2.5，第4棒為3.5。
        self.assertAlmostEqual(portfolio.vidya_value([1, 2, 3, 4], length=2, cmo_length=1), 3.5)
        with self.assertRaises(ValueError):
            portfolio.vidya_value([1, 2, 3, 4], length=2, cmo_length=3)

    def test_next_open_entry_shared_cash_priority_and_integer_lots(self):
        self.signal()
        self.price(272, 111, 100)
        self.price(273, 90, 95)
        result = scenario(self.run_research(config={'maxPositions': 1, 'lotSize': 100}))
        self.assertEqual(result['trades'][0]['symbol'], '0050')
        self.assertEqual(result['trades'][0]['entryDate'], self.dates[271])
        self.assertEqual(result['trades'][0]['entryPrice'], 110)
        self.assertEqual(result['trades'][0]['shares'], 4500)
        self.assertTrue(any(row['symbol'] == '2330' and '上限' in row['reason'] for row in result['rejected']))
        self.assertTrue(all(row['cash'] >= 0 and row['positions'] <= 1 for row in result['curve']))

    def test_close_stop_next_open_gap_and_costs_use_actual_cash(self):
        self.signal()
        self.price(272, 111, 100)
        self.price(273, 90, 95)
        result = scenario(self.run_research(), 'baseNet')
        self.assertEqual(len(result['trades']), 2)
        trade = result['trades'][0]
        self.assertEqual(trade['exitSignalDate'], self.dates[272])
        self.assertEqual(trade['exitDate'], self.dates[273])
        self.assertEqual(trade['exitPrice'], 90)
        self.assertAlmostEqual(trade['netReturnPct'], (90 * .9975 / (110 * 1.0025) - 1) * 100)
        self.assertGreater(result['maxDrawdownPct'], 10)

    def test_future_prices_and_future_events_do_not_change_prefix_or_digest(self):
        self.signal()
        cutoff = self.dates[271]
        before = self.run_research(as_of=cutoff)
        self.price(299, 1000, 1000)
        for data in self.datasets.values():
            data['adjustments']['events'].append({'date': self.dates[299], 'status': 'unsupported'})
            data['action_days'].add(self.dates[299])
        after = self.run_research(as_of=cutoff)
        self.assertEqual(before, after)

    def test_vidya_exit_can_trigger_without_cost_stop_and_cash_cannot_be_borrowed(self):
        self.signal()
        self.price(271, 102, 102)
        self.price(272, 102, 100)
        self.price(273, 99, 100)
        result = scenario(self.run_research(config={'allocationFraction': 1}))
        self.assertEqual(len(result['trades']), 1)
        self.assertEqual(result['trades'][0]['exitReason'], 'vidya_close')
        self.assertEqual(result['trades'][0]['exitDate'], self.dates[273])
        self.assertTrue(any(row['symbol'] == '2330' and '現金不足' in row['reason'] for row in result['rejected']))
        self.assertTrue(all(row['cash'] >= 0 for row in result['curve']))

    def test_end_open_position_and_pending_entry_are_not_fabricated_closes(self):
        self.signal()
        opened = scenario(self.run_research(as_of=self.dates[271]))
        self.assertEqual(opened['closedTrades'], 0)
        self.assertEqual(len(opened['openPositions']), 2)
        self.assertTrue(all(position['markPrice'] == 111 for position in opened['openPositions']))
        pending = scenario(self.run_research(as_of=self.dates[270]))
        self.assertEqual(pending['openPositions'], [])
        self.assertEqual(set(pending['pending']), set(portfolio.SYMBOLS))

    def test_missing_entry_is_cancelled_without_skipping_market_day(self):
        self.signal()
        self.datasets['0050']['rows'][271]['volume'] = 0
        result = scenario(self.run_research(as_of=self.dates[272]))
        self.assertTrue(any(row['symbol'] == '0050' and row['kind'] == 'entry' for row in result['rejected']))
        self.assertTrue(all(row['symbol'] != '0050' for row in result['openPositions']))
        self.assertEqual(result['status'], 'unknown')
        self.assertIsNone(result['totalReturnPct'])

    def test_unfillable_exit_stays_open_and_retries_at_next_actual_open(self):
        self.signal()
        self.price(272, 111, 100)
        for symbol in portfolio.SYMBOLS:
            self.datasets[symbol]['rows'][273].update(open=100, high=100, low=100, close=100)
        result = scenario(self.run_research())
        self.assertTrue(all(trade['exitDate'] == self.dates[274] for trade in result['trades']))
        self.assertTrue(any(row['kind'] == 'exit' and '一價' in row['reason'] for row in result['rejected']))

    def test_daily_close_after_scheduled_open_exit_cannot_retroactively_block_fill(self):
        self.signal()
        self.price(272, 111, 100)
        self.price(273, 99, 50)
        result = scenario(self.run_research())
        self.assertEqual(len(result['trades']), 2)
        self.assertTrue(all(trade['exitPrice'] == 99 for trade in result['trades']))

    def test_known_action_during_hold_is_unknown_without_avoiding_earlier_entry(self):
        self.signal()
        for symbol in portfolio.SYMBOLS:
            self.datasets[symbol]['action_days'].add(self.dates[272])
        result = scenario(self.run_research(as_of=self.dates[273]))
        self.assertEqual(len(result['openPositions']), 2)
        self.assertTrue(all(position['entryDate'] == self.dates[271] for position in result['openPositions']))
        self.assertEqual(result['status'], 'unknown')
        self.assertIsNone(result['totalReturnPct'])
        self.assertIsNone(result['maxDrawdownPct'])

    def test_benchmark_action_or_missing_price_never_becomes_zero_or_excess(self):
        self.signal()
        self.datasets['0050']['action_days'].add(self.dates[260])
        result = self.run_research()
        baseline = result['benchmark']['scenarios']['baseNet']
        self.assertEqual(baseline['status'], 'unknown')
        self.assertIsNone(baseline['totalReturnPct'])
        self.assertTrue(all(rule['scenarios']['baseNet']['excessReturnPctPoints'] is None for rule in result['rules']))
        self.datasets['0050']['action_days'].clear()
        self.datasets['0050']['rows'][254]['volume'] = 0
        missing = self.run_research()['benchmark']['scenarios']['baseNet']
        self.assertEqual(missing['status'], 'unknown')
        self.assertIsNone(missing['totalReturnPct'])

    def test_indicator_asof_comparison_adjusts_past_without_changing_raw_rows(self):
        self.fixture.apply_event(index=275, after=25, split=True)
        data = self.datasets['2330']
        data.update(rows=copy.deepcopy(self.fixture.rows), adjustments=copy.deepcopy(self.fixture.adjustments))
        before = copy.deepcopy(self.datasets)
        report = self.run_research()
        rows = next(asset for asset in report['assets'] if asset['symbol'] == '2330')['rows']
        self.assertEqual(next(row for row in rows if row['date'] == self.dates[274])['vidya'], 100)
        self.assertEqual(next(row for row in rows if row['date'] == self.dates[275])['vidya'], 25)
        self.assertEqual(self.datasets, before)

    def test_unknown_sources_coverage_and_initial_warmup_do_not_become_zero_performance(self):
        self.datasets['2330']['adjustments']['coverage'] = None
        report = self.run_research()
        self.assertEqual(scenario(report)['status'], 'unknown')
        self.assertIsNone(scenario(report)['totalReturnPct'])
        empty = portfolio.build_portfolio(self.datasets, [], sample_start=0)
        self.assertEqual(scenario(empty)['status'], 'insufficient')
        self.assertIsNone(scenario(empty)['totalReturnPct'])
        self.assertEqual(scenario(report)['curve'][0]['date'], self.dates[253])

    def test_digest_changes_with_quality_basis_but_not_future_calendar_extension(self):
        self.signal()
        before = self.run_research()
        self.datasets['2330']['calendar_years'].clear()
        changed = self.run_research()
        self.assertNotEqual(before['inputDigest'], changed['inputDigest'])
        self.datasets['2330']['calendar_years'] = {2025, 2026, 2027}
        self.assertEqual(before['inputDigest'], self.run_research()['inputDigest'])
        self.datasets['2330']['action_coverage'] = ('2025-01-01', self.dates[270], 'TWSE')
        self.assertNotEqual(before['inputDigest'], self.run_research()['inputDigest'])

    def test_compounding_uses_previous_close_equity_and_not_entry_day_future_close(self):
        self.signal()
        # 首波完成獲利後再形成突破，第二筆配置才應隨已實現盈虧改變。
        self.price(271, 102, 104)
        self.price(272, 104, 108)
        self.price(273, 108, 105)
        self.price(274, 105, 100)
        self.price(275, 108, 108)
        self.price(280, 110, 112)
        self.price(281, 114, 114)
        fixed = scenario(self.run_research(as_of=self.dates[281]))
        compounded = scenario(self.run_research(as_of=self.dates[281], config={'capitalBasis': 'previous_close_equity'}))
        self.assertTrue(fixed['trades'])
        self.assertTrue(compounded['openPositions'])
        second = compounded['openPositions'][0]
        prior = next(row for row in compounded['curve'] if row['date'] == self.dates[280])
        self.assertAlmostEqual(second['sizingEquity'], prior['equity'])
        self.assertGreater(second['shares'], fixed['openPositions'][0]['shares'])
        shares = second['shares']
        self.price(281, 114, 115)
        after = scenario(self.run_research(as_of=self.dates[281], config={'capitalBasis': 'previous_close_equity'}))
        self.assertEqual(after['openPositions'][0]['shares'], shares)
        self.price(275, 99, 99)
        loss_fixed = scenario(self.run_research(as_of=self.dates[281]))
        loss_compound = scenario(self.run_research(as_of=self.dates[281], config={'capitalBasis': 'previous_close_equity'}))
        self.assertLess(loss_compound['openPositions'][0]['shares'], loss_fixed['openPositions'][0]['shares'])

    def test_unknown_previous_equity_cannot_size_a_new_position(self):
        self.price(270, 100, 102, symbols=('0050',))
        self.price(271, 102, 102, symbols=('0050',))
        self.datasets['0050']['rows'][272]['close'] = None
        self.price(272, 100, 102, symbols=('2330',))
        self.price(273, 102, 103, symbols=('2330',))
        result = scenario(self.run_research(as_of=self.dates[273], config={'capitalBasis': 'previous_close_equity'}))
        self.assertIsNone(next(row for row in result['curve'] if row['date'] == self.dates[272])['equity'])
        self.assertTrue(any(row['symbol'] == '2330' and '前一日收盤權益未知' in row['reason'] for row in result['rejected']))
        self.assertTrue(all(position['symbol'] != '2330' for position in result['openPositions']))

    def test_dataset_scope_config_and_duplicate_dates_are_rejected(self):
        with self.assertRaises(ValueError):
            portfolio.build_portfolio({'2330': self.datasets['2330']}, self.dates)
        with self.assertRaises(ValueError):
            self.run_research(config={'initialCapital': float('nan')})
        with self.assertRaises(ValueError):
            self.run_research(config={'cmoLength': 30})
        with self.assertRaises(ValueError):
            portfolio.build_portfolio(self.datasets, self.dates + [self.dates[-1]])
        self.datasets['2330']['adjustments']['symbol'] = '0050'
        with self.assertRaisesRegex(ValueError, '標的不一致'):
            self.run_research()

    def test_saved_reader_is_read_only_and_uses_same_sqlite_snapshot(self):
        with tempfile.TemporaryDirectory(prefix='組合讀端-') as folder:
            db = Path(folder) / 'market.db'
            self.assertEqual(portfolio.build_saved_portfolio(db)['status'], 'unavailable')
            self.assertFalse(db.exists())
            with patch.object(datastore, 'DB_PATH', str(db)):
                datastore.init_db()
                for year in (2025, 2026):
                    daily.save_calendar(db, year, set(), set())
                for symbol, data in self.datasets.items():
                    datastore.upsert_bars(symbol, 'TW', [(daily.stamp(datetime.fromisoformat(row['date']).date()),
                        row['open'], row['high'], row['low'], row['close'], row['volume']) for row in data['rows']], source='TWSE')
                    with closing(sqlite3.connect(db)) as conn, conn:
                        conn.execute('INSERT INTO action_coverage VALUES(?,?,?,?,?)', ('TW', symbol, '2025-01-01', '2026-12-31', 'TWSE'))
                        coverage = data['adjustments']['coverage']
                        conn.execute('INSERT INTO action_price_coverage VALUES(?,?,?,?,?,?)', ('TW', symbol, coverage['start'], coverage['end'], coverage['version'], json.dumps(coverage['sources'])))
                with closing(sqlite3.connect(db)) as conn:
                    before = list(conn.iterdump())
                original = portfolio.events._read_bars
                writes = []
                def read(conn, symbol, cutoff):
                    value = original(conn, symbol, cutoff)
                    if symbol == '0050' and not writes:
                        with closing(sqlite3.connect(db)) as writer, writer:
                            writer.execute("UPDATE bars SET close=close+1 WHERE symbol='2330' AND ts=?", (daily.stamp(datetime.fromisoformat(self.dates[-1]).date()),))
                        writes.append(True)
                    return value
                at = datetime.fromisoformat(self.dates[-1] + 'T18:00:00+08:00')
                with patch.object(portfolio.events, '_read_bars', side_effect=read):
                    result = portfolio.build_saved_portfolio(db, self.dates[-1], now=at)
                self.assertNotEqual(result['status'], 'unavailable', result.get('reason'))
                stock = next(asset for asset in result['assets'] if asset['symbol'] == '2330')
                self.assertEqual(stock['rows'][-1]['close'], 100)
                again = portfolio.build_saved_portfolio(db, self.dates[-1], now=at)
                stock = next(asset for asset in again['assets'] if asset['symbol'] == '2330')
                self.assertEqual(stock['rows'][-1]['close'], 101)
                # 只有測試所控制的外部 writer 改價；正式 reader 不建立表或改其他資料。
                with closing(sqlite3.connect(db)) as conn, conn:
                    conn.execute("UPDATE bars SET close=100 WHERE symbol='2330' AND ts=?", (daily.stamp(datetime.fromisoformat(self.dates[-1]).date()),))
                with closing(sqlite3.connect(db)) as conn:
                    self.assertEqual(list(conn.iterdump()), before)


if __name__ == '__main__':
    unittest.main()
