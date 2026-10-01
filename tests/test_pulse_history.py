# -*- coding: utf-8 -*-
"""pulse_history: schema + merge upsert + history API shape."""
import os
import sys
import tempfile
import unittest

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

    def test_index_resync_keeps_change_pct_of_row_that_becomes_window_start(self):
        # 視窗最舊的一列 pct=None（沒有前一日收盤）。先前同步已算好的 change_pct 不可被洗成 NULL。
        import sqlite3
        from contextlib import closing
        first = [('2026-09-01', 100, 101, 99, 100.0, None, 0.0),
                 ('2026-09-02', 100, 103, 99, 102.0, 2.0, 0.0),
                 ('2026-09-03', 102, 104, 101, 101.0, -0.98, 0.0)]
        second = [('2026-09-02', 100, 103, 99, 102.0, None, 0.0),   # 視窗滑動：09-02 變成最舊
                  ('2026-09-03', 102, 104, 101, 101.0, -0.98, 0.0),
                  ('2026-09-04', 101, 106, 100, 105.0, 3.96, 0.0)]
        with closing(sqlite3.connect(self.ph.DB_PATH)) as conn:
            self.assertEqual(self.ph._upsert_index_rows(conn, '^TWOII', first, 'src', 1), 3)
            self.assertEqual(self.ph._upsert_index_rows(conn, '^TWOII', second, 'src', 2), 3)
            conn.commit()
            got = dict(conn.execute("SELECT d, change_pct FROM index_daily WHERE symbol='^TWOII'").fetchall())
        self.assertEqual(got['2026-09-02'], 2.0)
        self.assertIsNone(got['2026-09-01'])          # 真的沒有前值的第一列維持空
        self.assertAlmostEqual(got['2026-09-04'], 3.96)

    def test_index_resync_still_corrects_changed_values(self):
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.ph.DB_PATH)) as conn:
            self.ph._upsert_index_rows(conn, '^TWII', [('2026-09-02', 1, 2, 0.5, 1.5, 1.0, 0.0)], 'a', 1)
            self.ph._upsert_index_rows(conn, '^TWII', [('2026-09-02', 1, 2, 0.5, 1.8, 2.0, 0.0)], 'b', 2)
            row = conn.execute("SELECT close, change_pct, source FROM index_daily WHERE d='2026-09-02'").fetchone()
        self.assertEqual(row, (1.8, 2.0, 'b'))

    def test_twoii_history_flags_derived_ohlc_but_twii_does_not(self):
        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(self.ph.DB_PATH)) as conn:
            self.ph._upsert_index_rows(conn, '^TWOII', [('2026-09-30', 100, 101, 99, 100.5, 0.5, 0.0)], self.ph.TWOII_SOURCE, 1)
            self.ph._upsert_index_rows(conn, '^TWII', [('2026-09-30', 1, 2, 0.5, 1.5, 1.0, 9.0)], 'yahoo', 1)
            conn.commit()
        otc = self.ph.history('twoii', n=5)
        self.assertTrue(otc['ohlcDerived'])
        self.assertIn('官方', otc['ohlcNote'])
        self.assertEqual(otc['rows'][0]['close'], 100.5)          # 欄位與數值照舊，向後相容
        self.assertNotIn('ohlcDerived', self.ph.history('twii', n=5))


if __name__ == '__main__':
    unittest.main()
