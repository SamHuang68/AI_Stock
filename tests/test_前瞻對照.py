"""前瞻對照的樣本、版本、唯讀與批次網路邊界驗收。"""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import stock_signals as ss
import stock_signals_routes as routes
import 每日個股留存 as daily
import 個股訊號研究 as research
import 個股前瞻對照 as comparison
from tests.test_stock_signals import make_bars


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / '前瞻驗收.sqlite3'
        daily.enable(self.path, datetime(2024, 1, 1, 15, tzinfo=ss._TZ['TW']))
        self.bars = make_bars([100 + i / 10 for i in range(340)])
        self.version = daily.engine_digest()
        self.signal = 'mom_rsi_rebound'

    def seed(self, number, version=None, horizon=5, corrupted=False):
        version = version or self.version
        symbol, origin = str(2300 + number), self.bars[300]['date']
        input_id = research.digest([version, symbol, origin])
        event_id = research.digest([input_id, self.signal])
        frozen = {'bars': self.bars[:301], 'benchmark': self.bars[:301], 'engineDigest': version}
        event = {'signalId': self.signal, 'date': origin, 'provisional': False}
        prices = self.bars[301:302 + horizon]
        dates = [b['date'] for b in prices]
        outcome = {'horizon': horizon, 'entryDate': dates[0], 'endDate': dates[-1], 'prices': prices,
                   'expectedSessions': dates, 'pricesDigest': research.digest(prices),
                   'ret': prices[-1]['close'] / prices[0]['close'] - 1,
                   'adverse': min(b['low'] for b in prices[1:]) / prices[0]['close'] - 1}
        if corrupted:
            outcome['ret'] += .5
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('INSERT INTO daily_inputs VALUES(?,?,?,?,?)',
                         (input_id, symbol, origin, version, zlib.compress(json.dumps(frozen).encode())))
            conn.execute('INSERT INTO daily_events VALUES(?,?,?,?,?,?,?)',
                         (event_id, input_id, symbol, origin, self.signal, origin + 'T15:00:00+08:00', json.dumps(event)))
            conn.execute('INSERT INTO daily_outcomes VALUES(?,?,?,?)',
                         (event_id, horizon, dates[-1] + 'T15:00:00+08:00', json.dumps(outcome)))

    def row(self, report, horizon=5, version=None):
        group = next(g for g in report['groups'] if g['rulesDigest'] == (version or self.version))
        signal = next(s for s in group['signals'] if s['signalId'] == self.signal)
        return next(h for h in signal['horizons'] if h['horizon'] == horizon)

    def history(self):
        return {'generatedAt': '2026-09-30', 'research': {
            'rulesDigest': self.version, 'methodDigest': comparison.method_digest(),
            'policyDigest': research.digest(research.POLICY),
            'signals': [{'signalId': self.signal, 'horizons': [{'horizon': 5, 'all': {
                'n': 20, 'upRatio': .6, 'medianRet': .02, 'medianAdverse': -.03,
                'meanControlRet': .01, 'meanDeltaRet': .01}}]}]}}

    def test_nineteen_hidden_twenty_visible_costs_and_twenty_day_waits(self):
        for i in range(19):
            self.seed(i)
        report = comparison.read_report(self.path)
        self.assertIsNone(self.row(report)['forward']['medianRet'])
        self.seed(19)
        report = comparison.read_report(self.path)
        self.assertEqual(self.row(report)['forward']['gate'], 'ok')
        scenarios = self.row(report)['forward']['costScenarios']
        self.assertEqual([s['roundTripBps'] for s in scenarios], [0, 20, 50, 100])
        self.assertGreater(scenarios[0]['medianRet'], scenarios[-1]['medianRet'])
        self.assertEqual(self.row(report, 20)['waiting'], 20)
        self.assertEqual(self.row(report, 20)['mature'], 0)

    def test_versions_not_pooled_and_corrupt_result_explicitly_counted(self):
        for i in range(19):
            self.seed(i)
        self.seed(19, version='舊規則')
        self.seed(20, corrupted=True)
        report = comparison.read_report(self.path, self.history())
        self.assertEqual(self.row(report)['mature'], 19)
        self.assertEqual(self.row(report)['unverified'], 1)
        self.assertEqual(self.row(report)['forward']['gate'], 'insufficient')
        self.assertEqual(self.row(report, version='舊規則')['mature'], 1)
        self.assertEqual(self.row(report, version='舊規則')['historical']['gate'], 'unverified_version')

    def test_history_needs_both_fingerprints_and_reading_never_writes_or_calls_network(self):
        self.seed(0)
        before = hashlib.sha256(self.path.read_bytes()).hexdigest()
        with patch('socket.create_connection', side_effect=AssertionError('不得對外連線')):
            history = self.history()
            result = comparison.read_report(self.path, history)
            self.assertTrue(result['historicalVerified'])
            self.assertEqual(self.row(result)['historical']['upRatio'], .6)
            history['research']['methodDigest'] = '過期方法'
            result = comparison.read_report(self.path, history)
            self.assertFalse(result['historicalVerified'])
            self.assertIsNone(self.row(result)['historical']['upRatio'])
        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), before)

    def test_reference_uses_frozen_past_and_rejects_future_benchmark(self):
        frozen = {'bars': self.bars[:301], 'benchmark': self.bars[:301]}
        control = comparison._reference(frozen, 5)
        self.assertIsNotNone(control)
        self.assertLess(control['lastOutcomeIndex'], 300)
        with self.assertRaisesRegex(ValueError, '事件日之後'):
            comparison._reference({**frozen, 'benchmark': self.bars}, 5)

    def test_missing_ledger_is_not_created(self):
        path = self.path.parent / '尚未啟用.sqlite3'
        report = comparison.read_report(path)
        self.assertFalse(report['enabled'])
        self.assertFalse(path.exists())
        self.assertFalse(report['candidatePromotion'])


class BatchTests(unittest.TestCase):
    def test_cache_only_and_invalidated_event_evidence_preserved(self):
        class Handler(routes.StockSignalsRoutesMixin):
            def _stock_signals_query(self):
                return {'syms': [','.join(str(2300 + i) for i in range(87))], 'cacheOnly': ['1']}

            def _ok(self, value):
                self.payload = json.loads(value)

        event = {'signalId': 'mom_rsi_rebound', 'status': 'invalidated', 'statusDate': '2026-09-30',
                 'rule': '驗收規則', 'invalidation': {'text': '驗收失效條件'}, 'audit': {'evaluatedThrough': '2026-09-30'}}
        handler = Handler()
        def analyze(code, market, **options):
            self.assertFalse(options['allow_network'])
            self.assertFalse(options['use_cache'])
            return {'symbol': code, 'market': market, 'ok': False, 'events': [event], 'dataQuality': {'status': 'attention'}}
        with patch.object(routes, 'analyze_symbol', side_effect=analyze) as called:
            handler._handle_stock_signals_batch()
        self.assertEqual(called.call_count, 40)
        row = handler.payload['items'][0]
        self.assertEqual(row['eventReview'][0]['status'], 'invalidated')
        self.assertEqual(row['eventReview'][0]['invalidation']['text'], '驗收失效條件')
        self.assertEqual(row['dataQuality']['status'], 'attention')


if __name__ == '__main__':
    unittest.main()
