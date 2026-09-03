# -*- coding: utf-8 -*-
"""pulse_history: schema + merge upsert + history API shape."""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))


class PulseHistoryTests(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        import pulse_history as ph
        self.ph = ph
        self._orig = ph.DB_PATH
        ph.DB_PATH = os.path.join(self._tmpdir.name, 'pulse_history.db')
        ph.init_db()

    def tearDown(self):
        self.ph.DB_PATH = self._orig
        self._tmpdir.cleanup()

    def test_init_and_status(self):
        st = self.ph.status()
        self.assertTrue(st['ok'])
        self.assertEqual(st['version'], '5.0')
        self.assertEqual(st['counts']['breadth'], 0)

    def test_save_pulse_score_and_history(self):
        self.ph.save_pulse_score({
            'date': '20260731',
            'healthScore': 66.4,
            'riskScore': 33.6,
            'totalScore': 75.0,
            'dataCompleteness': 70.0,
            'statusText': '偏強',
            'tone': 'up',
        })
        h = self.ph.history('pulse', n=5)
        self.assertTrue(h['ok'])
        self.assertEqual(len(h['rows']), 1)
        self.assertEqual(h['rows'][0]['date'], '2026-07-31')
        self.assertAlmostEqual(h['rows'][0]['total'], 75.0)

    def test_index_upsert_merge(self):
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.ph.DB_PATH)) as conn:
            conn.execute(
                'INSERT OR REPLACE INTO index_daily(symbol,d,open,high,low,close,change_pct,volume,source,updated_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?)',
                ('^TWII', '2026-07-30', 1, 2, 0.5, 1.5, 1.0, 0, 'test', 1))
            conn.commit()
        # replace same day with new close — merge
        with closing(sqlite3.connect(self.ph.DB_PATH)) as conn:
            conn.execute(
                'INSERT OR REPLACE INTO index_daily(symbol,d,open,high,low,close,change_pct,volume,source,updated_at) '
                'VALUES(?,?,?,?,?,?,?,?,?,?)',
                ('^TWII', '2026-07-30', 1, 2, 0.5, 1.8, 2.0, 0, 'test', 2))
            conn.commit()
        h = self.ph.history('index', n=5)
        self.assertEqual(len(h['rows']), 1)
        self.assertAlmostEqual(h['rows'][0]['close'], 1.8)

    def test_twoii_uses_official_canonical_rows(self):
        rows = [
            {'date': '2026-09-02', 'open': 410.77, 'high': 410.77,
             'low': 406.96, 'close': 406.96, 'volume': 0},
            {'date': '2026-09-03', 'open': 406.96, 'high': 406.96,
             'low': 395.25, 'close': 395.25, 'volume': 0},
        ]
        with mock.patch('tw_index_charts.recent_rows', return_value=rows) as recent:
            points, source = self.ph.fetch_index_series('^TWOII')
        recent.assert_called_once_with('^TWOII', n=120, allow_network=True)
        self.assertEqual(source, 'TPEx st41 / TWSE MIS')
        self.assertEqual(points[-1][0], '2026-09-03')
        self.assertAlmostEqual(points[-1][4], 395.25)

    def test_institutional_meta_waits_for_official_release(self):
        status, note = self.ph._institutional_meta('2026-09-02', '2026-09-03', 0)
        self.assertEqual(status, '等待當日發布')
        self.assertIn('2026-09-02', note)
        self.assertIn('2026-09-03', note)
        self.assertEqual(
            self.ph._institutional_meta('2026-09-03', '2026-09-03', 1)[0],
            '同步完成',
        )


if __name__ == '__main__':
    unittest.main()
