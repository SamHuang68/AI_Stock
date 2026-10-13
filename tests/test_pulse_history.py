# -*- coding: utf-8 -*-
"""pulse_history: schema + merge upsert + history API shape."""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))


class PulseHistoryTests(unittest.TestCase):
    def test_sync_blocked_fetch_does_not_block_a_real_score_write(self):
        import threading
        from unittest import mock

        ph = self.ph
        entered, release, written = threading.Event(), threading.Event(), threading.Event()
        errors, results = [], []

        def source(*args):
            entered.set()
            if not release.wait(3):
                raise TimeoutError('合成來源未釋放')
            return [], '離線測試'

        def synchronize():
            try:
                results.append(ph.sync(days=0))
            except BaseException as error:
                errors.append(error)

        def write_score():
            try:
                ph.save_pulse_score({'date': '20261008', 'healthScore': 61,
                                     'riskScore': 39, 'totalScore': 67,
                                     'dataCompleteness': 93, 'statusText': '測試', 'tone': 'up'})
            except BaseException as error:
                errors.append(error)
            finally:
                written.set()

        with mock.patch.object(ph, 'fetch_index_series', side_effect=source), \
                mock.patch.object(ph, 'fetch_breadth_day', return_value=None), \
                mock.patch.object(ph, 'fetch_inst_day', return_value=None), \
                mock.patch.object(ph.time, 'sleep', return_value=None), \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('離線測試不得連外')):
            worker = threading.Thread(target=synchronize, name='history-sync-proof')
            writer = threading.Thread(target=write_score, name='history-write-proof')
            worker.start()
            try:
                self.assertTrue(entered.wait(1))
                writer.start()
                # fetch 必須仍阻塞；這是同一資料庫與 _lock 上的真正寫入，並非唯讀查詢。
                self.assertTrue(written.wait(1), '同步來源阻塞時資料庫寫入也被鎖住')
                self.assertFalse(release.is_set())
                self.assertTrue(worker.is_alive())
                self.assertFalse(errors, errors)
                saved = ph.history('pulse')['rows']
                self.assertEqual(len(saved), 1)
                self.assertEqual(saved[0]['date'], '2026-10-08')
                self.assertEqual(saved[0]['total'], 67)
            finally:
                release.set()
                worker.join(3)
                if writer.ident is not None:
                    writer.join(3)
            self.assertFalse(worker.is_alive())
            self.assertFalse(writer.is_alive())
            self.assertFalse(errors, errors)
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0]['ok'], results)

    def test_sync_merges_real_rows_from_each_dataset_start_and_records_metadata(self):
        import sqlite3
        from contextlib import closing
        from datetime import date
        from unittest import mock

        ph = self.ph
        with closing(sqlite3.connect(ph.DB_PATH)) as connection, connection:
            connection.execute('INSERT INTO breadth_daily(d,up,down,flat,limit_up,limit_down,adv_ratio,net,source,updated_at) '
                               'VALUES(?,?,?,?,?,?,?,?,?,?)',
                               ('2026-10-06', 31, 19, 2, 3, 1, .62, 12, '種子廣度', 1))
            connection.execute('INSERT INTO inst_daily(d,foreign_net,trust_net,dealer_net,total_net,source,updated_at) '
                               'VALUES(?,?,?,?,?,?,?)',
                               ('2026-10-07', 11, 22, 33, 66, '種子法人', 1))
        breadth_rows = {
            '20261007': {'d': '2026-10-07', 'up': 80, 'down': 20, 'flat': 4, 'limit_up': 8,
                         'limit_down': 2, 'adv_ratio': .8, 'net': 60, 'source': '合成廣度'},
            '20261008': {'d': '2026-10-08', 'up': 60, 'down': 40, 'flat': 7, 'limit_up': 6,
                         'limit_down': 4, 'adv_ratio': .6, 'net': 20, 'source': '合成廣度'},
        }
        inst_rows = {
            '20261008': {'d': '2026-10-08', 'foreign_net': 101, 'trust_net': 202,
                         'dealer_net': 303, 'total_net': 606, 'source': '合成法人'},
        }

        def index_rows(symbol, range_name):
            self.assertEqual(range_name, '3mo')
            return ([('2026-10-08', 100, 110, 90, 105, 5, 42)],
                    ph.TWOII_SOURCE if symbol == '^TWOII' else 'yahoo')

        with mock.patch.object(ph, '_taipei_today', return_value=date(2026, 10, 8)), \
                mock.patch.object(ph, 'fetch_index_series', side_effect=index_rows) as index, \
                mock.patch.object(ph, 'fetch_breadth_day', side_effect=breadth_rows.get) as breadth, \
                mock.patch.object(ph, 'fetch_inst_day', side_effect=inst_rows.get) as inst, \
                mock.patch.object(ph.time, 'sleep', return_value=None), \
                mock.patch('urllib.request.urlopen', side_effect=AssertionError('離線測試不得連外')):
            result = ph.sync(days=3)
            self.assertTrue(result['ok'], result)
            self.assertEqual((result['breadth'], result['inst'], result['index'], result['skipped']), (2, 1, 2, 0))
            self.assertEqual(result['mode'], 'merge')
            self.assertEqual(breadth.call_args_list, [mock.call('20261007'), mock.call('20261008')])
            self.assertEqual(inst.call_args_list, [mock.call('20261008')])
            self.assertEqual(index.call_args_list, [mock.call('^TWII', '3mo'), mock.call('^TWOII', '3mo')])
            with closing(sqlite3.connect(ph.DB_PATH)) as connection:
                row = connection.execute('SELECT up,down,flat,limit_up,limit_down,adv_ratio,net,source '
                                         'FROM breadth_daily WHERE d=?', ('2026-10-08',)).fetchone()
                self.assertEqual(row, (60, 40, 7, 6, 4, .6, 20, '合成廣度'))
                row = connection.execute('SELECT foreign_net,trust_net,dealer_net,total_net,source '
                                         'FROM inst_daily WHERE d=?', ('2026-10-08',)).fetchone()
                self.assertEqual(row, (101, 202, 303, 606, '合成法人'))
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM breadth_daily').fetchone()[0], 3)
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM inst_daily').fetchone()[0], 2)
                self.assertEqual(connection.execute('SELECT COUNT(*) FROM index_daily').fetchone()[0], 2)
            metadata = {row['dataset']: row for row in ph.status()['datasets']}
            for dataset, count in [('breadth', 2), ('institutional', 1), ('index:^TWII', 1), ('index:^TWOII', 1)]:
                self.assertEqual(metadata[dataset]['dataDate'], '2026-10-08')
                self.assertEqual(metadata[dataset]['status'], '同步完成')
                self.assertEqual(metadata[dataset]['rows'], count)
                self.assertIsNotNone(metadata[dataset]['lastSuccess'])
            self.assertEqual(metadata['breadth']['note'], 'merged 2 days')
            self.assertEqual(metadata['institutional']['note'], 'merged 1 days')
            self.assertEqual({r['dataset']: r for r in result['datasets']}, metadata)

            # 兩個日資料集已到當日；第二次 merge 不重抓，指數仍沿用原有每次同步契約。
            breadth.reset_mock(); inst.reset_mock(); index.reset_mock()
            again = ph.sync(days=3)
            self.assertTrue(again['ok'], again)
            self.assertEqual((again['breadth'], again['inst'], again['index'], again['skipped']), (0, 0, 2, 1))
            breadth.assert_not_called(); inst.assert_not_called()
            self.assertEqual(index.call_count, 2)
            metadata = {row['dataset']: row for row in ph.status()['datasets']}
            self.assertEqual(metadata['breadth']['rows'], 0)
            self.assertEqual(metadata['institutional']['rows'], 0)
            self.assertEqual(ph.status()['counts'], {'breadth': 3, 'institutional': 2, 'index': 2, 'pulseScore': 0})

            # force_full 僅改起點；對當日真資料 upsert，不能新增重複列。
            breadth_rows['20261008']['up'] = 61
            breadth_rows['20261008']['net'] = 21
            full = ph.sync(days=0, force_full=True)
            self.assertTrue(full['ok'], full)
            self.assertEqual(full['mode'], 'full')
            self.assertEqual((full['breadth'], full['inst'], full['index'], full['skipped']), (1, 1, 2, 0))
            self.assertEqual(ph.history('breadth', n=1)['rows'][0]['up'], 61)
            self.assertEqual(ph.status()['counts'], {'breadth': 3, 'institutional': 2, 'index': 2, 'pulseScore': 0})


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
