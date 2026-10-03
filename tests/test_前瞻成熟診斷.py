"""固定真實交易日期與手算結果驗收；僅使用暫存帳本，禁止網路與留存寫入。"""
import hashlib
import json
import sqlite3
import sys
import tempfile
import unittest
import zlib
from contextlib import closing
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import stock_signals as ss
import 每日個股留存 as daily
import 個股前瞻對照 as comparison
import 前瞻成熟診斷 as diagnosis
import 證據限制回報 as reports
from 個股訊號研究 import digest


class ForwardDiagnosticsTests(unittest.TestCase):
    origin = '2026-09-29'
    following = ['2026-09-30', '2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06', '2026-10-07']
    now = datetime(2026, 10, 7, 18, tzinfo=ss._TZ['TW'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / '前瞻.sqlite3'
        daily.enable(self.path, datetime(2026, 9, 27, 18, tzinfo=ss._TZ['TW']))
        self.version = daily.engine_digest()

    def bar(self, day):
        return {'date': day, 'open': 100, 'high': 112, 'low': 90,
                'close': 110 if day == '2026-10-07' else 100, 'volume': 1000}

    def seed(self, symbol='2330', prices=None, *, version=None, invalid=None, outcome=False, input_time=True):
        version = version or self.version
        signal = 'mom_rsi_rebound'
        iid = digest([version, symbol, self.origin])
        eid = digest([iid, signal])
        stamp = self.origin + 'T18:31:02+08:00'
        frozen = {'engineDigest': '不相符' if invalid == 'version' else version,
                  'bars': [self.bar(self.origin)], 'benchmark': [self.bar(self.origin)]}
        if input_time:
            frozen['observedAt'] = stamp
        ev = {'signalId': signal, 'date': self.origin, 'provisional': invalid == 'event'}
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('INSERT INTO daily_inputs VALUES(?,?,?,?,?)',
                         (iid, symbol, self.origin, version, zlib.compress(json.dumps(frozen).encode())))
            conn.execute('INSERT INTO daily_events VALUES(?,?,?,?,?,?,?)',
                         (eid, iid, symbol, self.origin, signal, stamp, json.dumps(ev)))
            for day in self.following if prices is None else prices:
                value = self.bar(day)
                if invalid == 'price' and day == '2026-10-01':
                    value['close'] = 0
                conn.execute('INSERT INTO daily_prices VALUES(?,?,?,?)',
                             (symbol, day, day + 'T18:32:01+08:00', json.dumps(value)))
            if outcome:
                values = [self.bar(day) for day in self.following]
                payload = {'horizon': 5, 'entryDate': '2026-09-30', 'endDate': '2026-10-07',
                           'expectedSessions': self.following, 'prices': values, 'pricesDigest': digest(values),
                           'ret': .5 if invalid == 'outcome' else .1, 'adverse': -.1}
                conn.execute('INSERT INTO daily_outcomes VALUES(?,?,?,?)',
                             (eid, 5, '2026-10-07T18:32:01+08:00', json.dumps(payload)))
        return eid

    def read(self, sessions=None, **kwargs):
        return diagnosis.read_diagnostics(self.path, self.following if sessions is None else sessions,
                                          now=kwargs.pop('now', self.now), **kwargs)

    def test_five_days_need_six_actual_closes_twenty_days_need_twenty_one(self):
        self.seed(prices=self.following[:3])
        result = self.read(self.following[:3], now=self.now.replace(day=2))
        for h in ('5', '20'):
            self.assertEqual(result['byHorizon'][h], {'awaiting_observed_sessions': 1})
        sample = result['samples'][0]
        self.assertEqual(sample['expectedSessions'], ['2026-09-30', '2026-10-01', '2026-10-02'])
        self.assertEqual(sample['observedFollowingSessions'], 3)
        self.assertEqual(result['horizons'][0]['requiredFollowingSessions'], 6)
        self.assertEqual(result['horizons'][1]['requiredFollowingSessions'], 21)
        report = comparison.read_report(self.path, sessions=self.following[:3], now=self.now.replace(day=2))
        signal = next(r for r in report['groups'][0]['signals'] if r['signalId'] == 'mom_rsi_rebound')
        self.assertIsNone(signal['horizons'][0]['forward']['medianRet'])

    def test_ready_unrecorded_is_distinct_from_mature_and_read_never_settles(self):
        self.seed()
        old_receipt = {'reason': '原留存收據，未提供成熟進度', 'sessionDate': self.origin}
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('INSERT INTO daily_runs VALUES(?,?)', (self.origin, json.dumps(old_receipt)))
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with patch('socket.create_connection', side_effect=AssertionError('不得連網')), \
                patch.object(daily, 'capture', side_effect=AssertionError('不得留存')):
            result = self.read()
            report = comparison.read_report(self.path, sessions=self.following, now=self.now)
        self.assertEqual(result['byHorizon']['5'], {'ready_unrecorded': 1})
        self.assertEqual(result['horizons'][0]['mature'], 0)
        self.assertEqual(result['horizons'][0]['due'], 1)
        self.assertEqual(result['lastRun'], old_receipt)
        self.assertEqual(report['diagnostics']['byHorizon'], result['byHorizon'])
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)
        self.assertFalse(result['candidatePromotion'])

    def test_benchmark_gap_stock_gap_and_invalid_price_have_separate_evidence(self):
        self.seed(prices=self.following[1:])
        result = self.read()
        self.assertEqual(result['byHorizon']['5'], {'missing_stock_sessions': 1})
        self.assertEqual(result['samples'][0]['missingPriceDates'], ['2026-09-30'])
        # 即使個股與基準都漏第一日，後來日期也不能順延湊成六日。
        gap = self.read(self.following[1:])
        self.assertEqual(gap['byHorizon']['5'], {'missing_benchmark_sessions': 1})
        self.assertEqual(gap['samples'][0]['missingBenchmarkDates'], ['2026-09-30'])
        self.seed('0050', invalid='price')
        result = self.read()
        bad = next(s for s in result['samples'] if s['symbol'] == '0050')
        self.assertEqual(bad['invalidPriceDates'], ['2026-10-01'])

    def test_bad_versions_events_and_results_do_not_count_as_mature(self):
        self.seed('2330', invalid='version', outcome=True)
        self.seed('0050', invalid='event', outcome=True)
        self.seed('2317', invalid='outcome', outcome=True)
        result = self.read()
        self.assertEqual(result['byHorizon']['5'], {'invalid_evidence': 2, 'invalid_version': 1})
        self.assertEqual(result['horizons'][0]['mature'], 0)
        self.assertEqual(result['horizons'][0]['unverified'], 3)
        self.assertEqual(result['storedResults'], 3)
        report = comparison.read_report(self.path, sessions=self.following, now=self.now)
        signal = next(r for r in report['groups'][0]['signals'] if r['signalId'] == 'mom_rsi_rebound')
        self.assertEqual(signal['horizons'][0]['unverified'], 3)
        self.assertEqual(signal['horizons'][0]['forward']['n'], 0)

    def test_previous_rules_are_separate_but_valid_and_hand_calculated_return_is_reproducible(self):
        self.seed('2330', outcome=True)
        self.seed('0050', version='已留存舊規則', outcome=True)
        result = self.read()
        self.assertEqual(result['byHorizon']['5'], {'mature': 2})
        report = comparison.read_report(self.path, sessions=self.following, now=self.now)
        self.assertEqual({r['currentRules'] for r in report['groups']}, {True, False})
        for group in report['groups']:
            signal = next(r for r in group['signals'] if r['signalId'] == 'mom_rsi_rebound')
            self.assertEqual(signal['horizons'][0]['forward']['n'], 1)
            self.assertIsNone(signal['horizons'][0]['forward']['medianRet'])
        with closing(sqlite3.connect(self.path)) as conn:
            value = diagnosis.validate_outcome(conn.execute('SELECT payload FROM daily_outcomes LIMIT 1').fetchone()[0], 5, self.origin)
        self.assertAlmostEqual(value['ret'], 110 / 100 - 1)
        self.assertAlmostEqual(value['adverse'], 90 / 100 - 1)

    def test_future_and_intraday_rows_cannot_count_as_observed(self):
        self.seed()
        result = self.read(now=datetime(2026, 10, 2, 13, 59, tzinfo=ss._TZ['TW']))
        self.assertEqual(result['benchmarkAsOf'], '2026-10-01')
        self.assertEqual(result['samples'][0]['expectedSessions'], self.following[:2])
        self.assertEqual(result['byHorizon']['5'], {'awaiting_observed_sessions': 1})
        self.assertNotIn('2026-10-02', result['samples'][0]['observedPriceDates'])

    def test_real_market_snapshot_filters_incomplete_and_future_rows_without_writes(self):
        self.seed()
        market = self.path.parent / 'market.db'
        with closing(sqlite3.connect(market)) as conn, conn:
            conn.execute('CREATE TABLE bars(market TEXT,symbol TEXT,ts INTEGER,open REAL,high REAL,low REAL,close REAL,volume REAL)')
            for day in self.following:
                stamp = int(datetime.fromisoformat(day + 'T09:00:00+08:00').timestamp())
                conn.execute('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)',
                             ('TW', '^TWII', stamp, 100, 112, 90, None if day == '2026-10-01' else 100, 1000))
        before = market.read_bytes()
        result = diagnosis.read_diagnostics(self.path, now=self.now.replace(day=2))
        self.assertEqual(result['benchmarkAsOf'], '2026-10-02')
        self.assertEqual(result['samples'][0]['expectedSessions'], ['2026-09-30', '2026-10-02'])
        self.assertEqual(result['samples'][0]['missingBenchmarkDates'], ['2026-10-01'])
        self.assertEqual(result['byHorizon']['5'], {'missing_benchmark_sessions': 1})
        self.assertEqual(market.read_bytes(), before)

    def test_result_with_invalid_frozen_ohlcv_is_not_verified_even_if_return_matches(self):
        self.seed(outcome=True)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            row = conn.execute('SELECT event_id,payload FROM daily_outcomes').fetchone()
            value = json.loads(row[1])
            value['prices'][1]['volume'] = None
            value['pricesDigest'] = digest(value['prices'])
            conn.execute('UPDATE daily_outcomes SET payload=? WHERE event_id=?', (json.dumps(value), row[0]))
        self.assertEqual(self.read()['byHorizon']['5'], {'invalid_evidence': 1})

    def test_stored_result_cannot_shift_missing_day_even_when_its_arithmetic_matches(self):
        self.seed(outcome=True)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            row = conn.execute('SELECT event_id,payload FROM daily_outcomes').fetchone()
            value = json.loads(row[1])
            value['expectedSessions'] = self.following[1:] + ['2026-10-08']
            value['prices'] = [self.bar(day) for day in value['expectedSessions']]
            value.update(entryDate='2026-10-01', endDate='2026-10-08', ret=0,
                         pricesDigest=digest(value['prices']))
            conn.execute('UPDATE daily_outcomes SET payload=? WHERE event_id=?', (json.dumps(value), row[0]))
        result = self.read(self.following + ['2026-10-08'], now=self.now.replace(day=8))
        self.assertEqual(result['byHorizon']['5'], {'invalid_evidence': 1})

    def test_dates_do_not_come_from_old_frozen_input_and_missing_db_is_not_created(self):
        self.seed(prices=[])
        result = diagnosis.read_diagnostics(self.path, now=self.now)
        self.assertIsNone(result['benchmarkAsOf'])
        self.assertEqual(result['byHorizon']['5'], {'missing_benchmark_sessions': 1})
        self.assertFalse((self.path.parent / 'market.db').exists())
        absent = self.path.parent / '不存在.sqlite3'
        self.assertFalse(diagnosis.read_diagnostics(absent, now=self.now)['enabled'])
        self.assertFalse(absent.exists())

    def test_trace_is_bounded_and_missing_timestamp_is_not_invented(self):
        self.seed(input_time=False)
        for i in range(20):
            self.seed(str(2400 + i))
        result = self.read(sample_limit=4)
        self.assertEqual(len(result['samples']), 4)
        self.assertEqual(result['totalEventHorizons'], 42)
        # 另以固定樣本上限取得該原始欄位；缺欄位必須維持缺值。
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("DELETE FROM daily_events WHERE symbol!='2330'")
        first = self.read()['samples'][0]
        self.assertIsNone(first['inputFirstRecordedAt'])
        self.assertEqual(first['eventFirstRecordedAt'], '2026-09-29T18:31:02+08:00')
        self.assertEqual(first['priceFirstRecordedAt'][0], {'date': '2026-09-30', 'observedAt': '2026-09-30T18:32:01+08:00'})
        self.assertEqual(first['rulesDigest'], self.version)
        self.assertEqual(len(first['inputPayloadDigest']), 64)
        self.assertEqual(len(first['eventPayloadDigest']), 64)

    def test_rechecking_time_alone_does_not_duplicate_evidence_report(self):
        self.seed()
        from tests.test_證據限制回報 import build
        first = build(observations=self.read())
        later = build(observations=self.read(now=self.now.replace(minute=1)))
        path = self.path.parent / '證據回報.sqlite3'
        self.assertEqual(reports.save_report(path, first), reports.save_report(path, later))


if __name__ == '__main__':
    unittest.main()
