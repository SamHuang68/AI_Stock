"""前瞻留存入口的限定離線契約；只操作暫存帳本，不新增歷史事件。"""
import json
import sqlite3
import sys
import tempfile
import unittest
import zlib
from contextlib import closing, nullcontext
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import stock_signals as ss
import 每日個股留存 as daily
import 個股研究維護 as maintenance
from 個股訊號研究 import digest


class ForwardCapturePipelineTests(unittest.TestCase):
    origin = '2026-09-29'
    following = ['2026-09-30', '2026-10-01', '2026-10-02', '2026-10-05', '2026-10-06', '2026-10-07']
    now = datetime(2026, 10, 7, 18, tzinfo=ss._TZ['TW'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'stock_daily_observations.sqlite3'
        daily.enable(self.path, datetime(2026, 9, 27, 18, tzinfo=ss._TZ['TW']))
        version = daily.engine_digest()
        self.input_id = digest([version, '2330', self.origin])
        self.event_id = digest([self.input_id, 'mom_rsi_rebound'])
        self.event_stamp = self.origin + 'T18:31:02+08:00'
        frozen = {'engineDigest': version, 'bars': [self.bar(self.origin)],
                  'benchmark': [self.bar(self.origin)], 'observedAt': self.event_stamp}
        event = {'signalId': 'mom_rsi_rebound', 'date': self.origin, 'provisional': False}
        self.input_payload = zlib.compress(json.dumps(frozen).encode())
        self.event_payload = json.dumps(event)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute('INSERT INTO daily_inputs VALUES(?,?,?,?,?)',
                         (self.input_id, '2330', self.origin, version, self.input_payload))
            conn.execute('INSERT INTO daily_events VALUES(?,?,?,?,?,?,?)',
                         (self.event_id, self.input_id, '2330', self.origin,
                          'mom_rsi_rebound', self.event_stamp, self.event_payload))
        self.bars = [self.bar(day) for day in self.following]
        self.benchmark = [self.bar(day) for day in self.following]
        self.addCleanup(patch.stopall)
        patch('urllib.request.urlopen', side_effect=AssertionError('禁止網路呼叫')).start()
        patch.object(ss, 'analyze', side_effect=AssertionError('短歷史不得新增訊號')).start()
        patch.object(maintenance.datastore, 'DB_PATH', str(Path(self.temp.name) / 'market.db')).start()
        patch.object(maintenance.datastore, 'read_snapshot', side_effect=lambda: nullcontext(object())).start()
        # 目前只有六根行情，現行七十根新增訊號篩選不會回傳此待結算個股。
        self.list_symbols = patch.object(maintenance.datastore, 'list_symbols', return_value=[]).start()
        patch.object(maintenance.datastore, 'get_bars_bulk',
                     side_effect=lambda symbols, **kwargs: {'^TWII': self.benchmark}).start()
        patch.object(maintenance.pool, '_load_all_chips', return_value={}).start()
        self.iterate = patch.object(maintenance.pool, 'iter_datastore',
            side_effect=lambda market, symbols, **kwargs: ((symbol, self.bars) for symbol in symbols)).start()

    def bar(self, day):
        return {'date': day, 'open': 100, 'high': 112, 'low': 90,
                'close': 110 if day == self.following[-1] else 100, 'volume': 1000}

    def test_pending_event_with_six_current_bars_matures_without_new_event(self):
        result = maintenance.capture(self.now)
        self.assertEqual(result['eventsAdded'], 0)
        self.assertEqual(result['outcomesAdded'], 1)
        self.assertEqual(result['outcomeProgress']['byHorizon']['20'], {'awaiting_observed_sessions': 1})
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM daily_events').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT observed_at,payload FROM daily_events WHERE id=?',
                                         (self.event_id,)).fetchone(), (self.event_stamp, self.event_payload))
            self.assertEqual(conn.execute('SELECT payload FROM daily_inputs WHERE id=?',
                                         (self.input_id,)).fetchone()[0], self.input_payload)
            value = json.loads(conn.execute('SELECT payload FROM daily_outcomes WHERE horizon=5').fetchone()[0])
        self.assertEqual(value['entryDate'], '2026-09-30')
        self.assertEqual(value['endDate'], '2026-10-07')
        self.assertAlmostEqual(value['ret'], .1)
        self.assertEqual(self.iterate.call_args.kwargs['symbols'], ['2330'])

    def test_incomplete_benchmark_cannot_supply_a_maturity_session(self):
        self.benchmark[1]['volume'] = None
        result = maintenance.capture(self.now)
        self.assertEqual(result['eventsAdded'], 0)
        self.assertEqual(result['outcomesAdded'], 0)
        self.assertEqual(result['outcomeProgress']['byHorizon']['5'], {'missing_benchmark_sessions': 1})
        sample = result['outcomeProgress']['samples'][0]
        self.assertEqual(sample['missingBenchmarkDates'], ['2026-10-01'])
        with closing(sqlite3.connect(self.path)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM daily_outcomes').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
