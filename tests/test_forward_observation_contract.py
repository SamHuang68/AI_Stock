"""前瞻成熟日期與缺日契約；預期值獨立指定，無網路或正式帳本寫入。"""
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import 每日個股留存 as daily
import stock_signals as ss


class ForwardObservationTests(unittest.TestCase):
    origin = '2026-09-29'
    following = ['2026-09-30', '2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06', '2026-10-07']

    def test_five_day_return_requires_entry_plus_five_actual_sessions(self):
        value = daily.maturity_progress(self.origin, self.following[:5], self.following[:5], 5)
        self.assertEqual(value['status'], 'awaiting_observed_sessions')
        self.assertEqual(value['requiredFollowingSessions'], 6)
        self.assertEqual(value['observedFollowingSessions'], 5)
        self.assertEqual(daily.maturity_progress(self.origin, self.following, self.following, 5)['status'], 'ready')

    def test_stock_missing_day_and_benchmark_missing_day_are_distinct(self):
        missing = daily.maturity_progress(self.origin, self.following, self.following[1:], 5)
        self.assertEqual(missing['status'], 'missing_stock_sessions')
        self.assertEqual(missing['missingPriceDates'], ['2026-09-30'])
        benchmark = self.following[1:] + ['2026-10-08']
        missing = daily.maturity_progress(self.origin, benchmark, self.following + ['2026-10-08'], 5)
        self.assertEqual(missing['status'], 'missing_benchmark_sessions')
        self.assertEqual(missing['missingBenchmarkDates'], ['2026-09-30'])

    def test_twenty_day_observation_does_not_use_calendar_day_arithmetic(self):
        value = daily.maturity_progress(self.origin, self.following, self.following, 20)
        self.assertEqual(value['status'], 'awaiting_observed_sessions')
        self.assertEqual(value['requiredFollowingSessions'], 21)

    def test_absent_or_lagging_benchmark_is_not_only_waiting_for_time(self):
        for sessions in ([], self.following[:1]):
            value = daily.maturity_progress(self.origin, sessions, self.following[:2], 5)
            self.assertEqual(value['status'], 'missing_benchmark_sessions')
            self.assertIn('2026-10-01', value['missingBenchmarkDates'])

    def test_later_prices_do_not_change_a_complete_frozen_horizon(self):
        value = daily.maturity_progress(self.origin, self.following, self.following + ['2026-10-08'], 5)
        self.assertEqual(value['status'], 'ready')

    def test_both_sources_missing_a_scheduled_day_cannot_shift_the_horizon(self):
        both = self.following[1:] + ['2026-10-08']
        value = daily.maturity_progress(self.origin, both, both, 5)
        self.assertEqual(value['status'], 'missing_benchmark_sessions')
        self.assertEqual(value['missingBenchmarkDates'], ['2026-09-30'])

    def test_existing_event_can_mature_with_short_current_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'observations.sqlite3'
            daily.enable(path, datetime(2026, 9, 27, 20, tzinfo=ss._TZ['TW']))
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute('INSERT INTO daily_events VALUES(?,?,?,?,?,?,?)',
                             ('event', 'input', '2330', self.origin, 'mom_rsi_rebound', self.origin, '{}'))
            bars = [{'date': day, 'open': 100, 'high': 112, 'low': 90,
                     'close': 110 if day == self.following[-1] else 100, 'volume': 1000}
                    for day in self.following]
            now = datetime(2026, 10, 7, 18, tzinfo=ss._TZ['TW'])
            with patch.object(ss, 'analyze', side_effect=AssertionError('短歷史不得新增訊號')):
                result = daily.capture(path, [('2330', bars)], bars, now=now)
            self.assertEqual(result['eventsAdded'], 0)
            self.assertEqual(result['outcomesAdded'], 1)
            self.assertEqual(result['priceExclusions'][0]['reason'], 'insufficient_history')
            self.assertEqual(result['outcomeProgress']['byHorizon']['20'], {'awaiting_observed_sessions': 1})
            with closing(sqlite3.connect(path)) as conn:
                stored = conn.execute('SELECT payload FROM daily_outcomes WHERE horizon=5').fetchone()[0]
                out = json.loads(stored)
            self.assertEqual(out['entryDate'], '2026-09-30')
            self.assertEqual(out['endDate'], '2026-10-07')
            self.assertAlmostEqual(out['ret'], .1)
            self.assertAlmostEqual(out['adverse'], -.1)
            before = path.read_bytes()
            status = daily.status(path)
            self.assertEqual(status['forward']['horizons'][0]['pending'], 0)
            self.assertEqual(status['forward']['horizons'][1]['pending'], 1)
            self.assertEqual(path.read_bytes(), before)
            bars[-1]['close'] = 200
            daily.capture(path, [('2330', bars)], bars, now=now)
            with closing(sqlite3.connect(path)) as conn:
                self.assertEqual(conn.execute('SELECT payload FROM daily_outcomes WHERE horizon=5').fetchone()[0], stored)

    def test_event_without_current_symbol_input_is_not_silently_lost(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'observations.sqlite3'
            daily.enable(path, datetime(2026, 9, 27, 20, tzinfo=ss._TZ['TW']))
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute('INSERT INTO daily_events VALUES(?,?,?,?,?,?,?)',
                             ('event', 'input', '2330', self.origin, 'mom_rsi_rebound', self.origin, '{}'))
            result = daily.capture(path, [], [], now=datetime(2026, 10, 2, 18, tzinfo=ss._TZ['TW']))
            for h in ('5', '20'):
                self.assertEqual(result['outcomeProgress']['byHorizon'][h], {'not_evaluated_current_input': 1})

    def test_incomplete_prices_cannot_mature_or_overwrite_older_bad_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'observations.sqlite3'
            daily.enable(path, datetime(2026, 9, 27, 20, tzinfo=ss._TZ['TW']))
            bars = [{'date': day, 'open': 100, 'high': 110, 'low': 90, 'close': 100, 'volume': 1000}
                    for day in self.following]
            bad = {**bars[0], 'close': 0}
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute('INSERT INTO daily_events VALUES(?,?,?,?,?,?,?)',
                             ('event', 'input', '2330', self.origin, 'mom_rsi_rebound', self.origin, '{}'))
                conn.execute('INSERT INTO daily_prices VALUES(?,?,?,?)',
                             ('2330', bad['date'], self.origin, json.dumps(bad)))
            benchmark = [dict(b) for b in bars]  # 此案例單獨驗證股票缺口；基準維持完整。
            bars[1]['volume'] = None
            result = daily.capture(path, [('2330', bars)], benchmark,
                                   now=datetime(2026, 10, 7, 18, tzinfo=ss._TZ['TW']))
            self.assertEqual(result['outcomesAdded'], 0)
            sample = result['outcomeProgress']['samples'][0]
            self.assertEqual(sample['status'], 'missing_stock_sessions')
            self.assertEqual(sample['invalidPriceDates'], self.following[:2])
            with closing(sqlite3.connect(path)) as conn:
                self.assertEqual(json.loads(conn.execute('SELECT payload FROM daily_prices WHERE session_date=?',
                                                        (bad['date'],)).fetchone()[0]), bad)

    def test_empty_ledger_is_zero_events_not_successful_performance(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'observations.sqlite3'
            daily.enable(path, datetime(2026, 9, 27, 20, tzinfo=ss._TZ['TW']))
            result = daily.status(path)
            self.assertEqual(result['forward']['eventRange'], {'first': None, 'last': None})
            self.assertEqual(result['events'], 0)
            self.assertFalse(result['candidatePromotion'])


if __name__ == '__main__':
    unittest.main()
