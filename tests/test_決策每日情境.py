"""decision_history 是「最近 500 筆」的滾動緩衝；研究要用的逐日情境標籤另存 decision_regime_daily。"""
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import conditional_expectation as ce
import decision_store as store


def context(n, as_of, regime='BROAD_RISK_ON'):
    return {'snapshotId': f'snap-{n}', 'inputHash': f'hash-{n}', 'asOf': as_of, 'market': 'TW',
            'regime': {'id': regime, 'confidence': 0.6}, 'dataQuality': {'completeness': 0.9}}


class DailyRegimeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.db = str(Path(folder.name) / 'decision.db')

    def commit(self, n, as_of, regime='BROAD_RISK_ON'):
        store.commit(self.db, context(n, as_of, regime), {'pulse': {}}, '2026-10-01T00:00:00Z')

    def daily(self):
        with closing(sqlite3.connect(self.db)) as conn:
            return conn.execute('SELECT day,as_of,regime FROM decision_regime_daily ORDER BY day').fetchall()

    def history_count(self):
        with closing(sqlite3.connect(self.db)) as conn:
            return conn.execute('SELECT count(*) FROM decision_history').fetchone()[0]

    def test_daily_regime_survives_the_500_row_history_buffer(self):
        self.commit(0, '2026-10-01T05:00:00Z', 'DEFENSIVE_RISK_OFF')
        self.commit(1, '2026-10-02T05:00:00Z', 'NARROW_RALLY')
        for n in range(2, 505):
            self.commit(n, '2026-10-05T05:%02d:00Z' % (n % 60), 'CONFLICT')
        self.assertEqual(self.history_count(), 500)
        with closing(sqlite3.connect(self.db)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM decision_history WHERE as_of<'2026-10-05'").fetchone()[0], 0)
        self.assertEqual([row[0] for row in self.daily()], ['2026-10-01', '2026-10-02', '2026-10-05'])
        self.assertEqual(ce.regime_at_date(date(2026, 10, 1), decision_db_path=self.db), 'DEFENSIVE_RISK_OFF')
        self.assertEqual(ce.regime_at_date(date(2026, 10, 2), decision_db_path=self.db), 'NARROW_RALLY')
        self.assertEqual(ce.regime_at_date(date(2026, 10, 5), decision_db_path=self.db), 'CONFLICT')

    def test_day_is_taipei_date_not_utc_date(self):
        self.commit(1, '2026-10-01T17:30:00Z', 'NARROW_RALLY')       # 台北 10-02 01:30
        self.commit(2, '2026-10-01T08:00:00Z', 'DEFENSIVE_RISK_OFF')  # 台北 10-01 16:00
        self.assertEqual([(d, r) for d, _, r in self.daily()],
                         [('2026-10-01', 'DEFENSIVE_RISK_OFF'), ('2026-10-02', 'NARROW_RALLY')])
        self.assertEqual(ce.regime_at_date(date(2026, 10, 1), decision_db_path=self.db), 'DEFENSIVE_RISK_OFF')

    def test_last_pulse_of_the_day_wins_even_when_it_arrives_out_of_order(self):
        self.commit(1, '2026-10-01T03:00:00Z', 'A')
        self.commit(2, '2026-10-01T05:00:00Z', 'B')
        self.commit(3, '2026-10-01T04:00:00Z', 'C')                   # 較舊的紀錄後到，不得覆蓋
        self.assertEqual([r for _, _, r in self.daily()], ['B'])

    def test_offset_and_z_timestamps_compare_correctly(self):
        self.commit(1, '2026-10-01T10:00:00+08:00', 'EARLY')          # = 02:00Z
        self.commit(2, '2026-10-01T03:00:00Z', 'LATE')
        self.assertEqual([(d, a, r) for d, a, r in self.daily()], [('2026-10-01', '2026-10-01T03:00:00Z', 'LATE')])

    def test_existing_history_is_backfilled_once_when_the_table_is_empty(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('CREATE TABLE decision_history(id INTEGER PRIMARY KEY AUTOINCREMENT,as_of TEXT,created_at INTEGER,'
                         'market TEXT,input_hash TEXT UNIQUE,regime TEXT,confidence REAL,completeness REAL,context_json TEXT)')
            for as_of, regime in (('2026-09-30T05:00:00Z', 'OLD'), ('2026-09-30T06:00:00Z', 'OLD_LAST'),
                                  ('2026-10-01T05:00:00Z', 'NEWER')):
                conn.execute('INSERT INTO decision_history(as_of,created_at,market,input_hash,regime) VALUES(?,?,?,?,?)',
                             (as_of, 0, 'TW', as_of, regime))
        self.commit(1, '2026-10-02T05:00:00Z', 'NOW')
        self.assertEqual([(d, r) for d, _, r in self.daily()],
                         [('2026-09-30', 'OLD_LAST'), ('2026-10-01', 'NEWER'), ('2026-10-02', 'NOW')])

    def test_unparseable_as_of_does_not_break_the_commit(self):
        with patch.object(store, 'log_once') as logged:
            self.commit(1, 'not-a-timestamp')
            self.commit(2, None)
        self.assertEqual(self.history_count(), 2)
        self.assertEqual(self.daily(), [])
        self.assertTrue(logged.called)   # 每日表仍空時回補會再看一次舊列，所以不固定次數；log_once 自己限頻

    def test_regime_before_coverage_is_unknown_and_never_future(self):
        self.commit(1, '2026-10-05T05:00:00Z', 'CONFLICT')
        self.assertEqual(ce.regime_at_date(date(2026, 10, 4), decision_db_path=self.db), 'UNKNOWN')
        self.assertEqual(ce.regime_at_date(date(2026, 10, 6), decision_db_path=self.db), 'CONFLICT')

    def test_legacy_database_without_the_daily_table_still_answers_from_history(self):
        with closing(sqlite3.connect(self.db)) as conn, conn:
            conn.execute('CREATE TABLE decision_history(id INTEGER PRIMARY KEY AUTOINCREMENT,as_of TEXT,regime TEXT)')
            conn.execute("INSERT INTO decision_history(as_of,regime) VALUES('2026-10-01T05:00:00Z','LEGACY')")
        self.assertEqual(ce.regime_at_date(date(2026, 10, 1), decision_db_path=self.db), 'LEGACY')
        self.assertEqual(ce.regime_at_date(date(2026, 9, 1), decision_db_path=self.db), 'UNKNOWN')

    def test_missing_database_is_unknown(self):
        self.assertEqual(ce.regime_at_date(date(2026, 10, 1), decision_db_path=self.db + '.absent'), 'UNKNOWN')


if __name__ == '__main__':
    unittest.main()
