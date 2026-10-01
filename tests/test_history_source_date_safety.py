import os
import sys
import sqlite3
from contextlib import closing
import tempfile
import unittest
from datetime import date
from unittest.mock import patch
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'server'))
import margin_ratio as mr
import pulse_history as ph

class HistorySafetyTests(unittest.TestCase):
    def test_seed_whole_file_rejection(self):
        with tempfile.TemporaryDirectory() as td, patch.object(mr, '_taipei_today', return_value=date(2026, 10, 1)):
            p = os.path.join(td, 'seed.csv')
            for bad in ('2026-10-02,150', '2026-09-30,inf', '2026-09-30,nan', '2026-09-29,150', '2026-09-30,150'):
                with open(p, 'w') as f:
                    f.write('date,ratio\n2026-09-30,145\n' + bad + '\n')
                self.assertEqual(mr.load_seed_csv(p), [])
    def test_writer_preserves_previous_on_rejection_and_backup(self):
        with tempfile.TemporaryDirectory() as td, patch.object(mr, '_taipei_today', return_value=date(2026, 10, 1)):
            p = os.path.join(td, 'seed.csv')
            with open(p, 'w') as f: f.write('date,ratio\n2026-09-29,145\n')
            for rows in ([], [(mr._date_to_ts(date(2026, 10, 2)), 150)], [(mr._date_to_ts(date(2026, 9, 30)), float('inf'))]):
                with self.assertRaises(ValueError): mr.save_seed_csv(rows, p)
                with open(p) as f: self.assertEqual(f.read(), 'date,ratio\n2026-09-29,145\n')
            mr.save_seed_csv([(mr._date_to_ts(date(2026, 9, 30)), 150)], p)
            with open(p + '.bak') as f: self.assertEqual(f.read(), 'date,ratio\n2026-09-29,145\n')
    def test_rejected_seed_cannot_be_rebuilt_silently(self):
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, 'seed.csv')
            with open(p, 'w') as f: f.write('corrupt original')
            with self.assertRaises(ValueError): mr.save_seed_csv([(mr._date_to_ts(date(2026, 9, 30)), 150)], p)
            with open(p) as f: self.assertEqual(f.read(), 'corrupt original')

    def test_sync_preserves_legacy_on_failure_and_archives_on_success(self):
        with tempfile.TemporaryDirectory() as td, patch.object(ph, 'DB_PATH', os.path.join(td, 'history.db')), patch.object(ph, '_taipei_today', return_value=date(2026, 10, 1)), patch.object(ph, 'fetch_breadth_day', return_value=None), patch.object(ph, 'fetch_inst_day', return_value=None):
            ph.init_db()
            with closing(ph._conn()) as conn, conn:
                conn.execute("INSERT INTO index_daily(symbol,d,source) VALUES('^TWOII','2026-09-29','yahoo')")
            with patch.object(ph, 'fetch_index_series', return_value=([], ph.TWOII_SOURCE)):
                ph.sync(days=0)
            with closing(ph._conn()) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM index_daily').fetchone()[0], 1)
            official = [('2026-09-30', 100., 101., 99., 100., None, 10.)]
            with patch.object(ph, 'fetch_index_series', side_effect=lambda sym, rng: (official if sym == '^TWOII' else [], ph.TWOII_SOURCE)):
                ph.sync(days=0)
            with closing(ph._conn()) as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM index_daily_legacy').fetchone()[0], 1)
                self.assertEqual(conn.execute('SELECT source FROM index_daily').fetchone()[0], ph.TWOII_SOURCE)
            self.assertTrue(ph.history('twoii')['ok'])

    def test_twoii_has_no_yahoo_fallback(self):
        with patch('tw_index_charts.recent_rows', return_value=[]), patch.object(ph, 'fetch_index_yahoo') as yahoo:
            self.assertEqual(ph.fetch_index_series('^TWOII'), ([], ph.TWOII_SOURCE))
            yahoo.assert_not_called()
    def test_archive_is_transactional(self):
        conn = sqlite3.connect(':memory:'); conn.executescript(ph.SCHEMA)
        conn.execute("INSERT INTO index_daily(symbol,d,source) VALUES('^TWOII','2026-09-30','yahoo')"); conn.commit()
        conn.execute('SAVEPOINT migration'); ph._archive_legacy_twoii(conn)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM index_daily').fetchone()[0], 0)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM index_daily_legacy').fetchone()[0], 1)
        conn.execute('ROLLBACK TO migration')
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM index_daily').fetchone()[0], 1)
        conn.close()
    def test_legacy_only_query_unavailable(self):
        with tempfile.TemporaryDirectory() as td, patch.object(ph, 'DB_PATH', os.path.join(td, 'history.db')):
            ph.init_db()
            with closing(ph._conn()) as conn, conn:
                conn.execute("INSERT INTO index_daily(symbol,d,source) VALUES('^TWOII','2026-09-30','yahoo')")
            result = ph.history('twoii')
            self.assertFalse(result['ok']); self.assertEqual(result['status'], 'unavailable'); self.assertEqual(result['rows'], [])
    def test_institutional_missing_mismatched_future_date_rejected(self):
        with patch.object(ph, '_taipei_today', return_value=date(2026, 10, 1)):
            for payload in ({'stat': 'OK'}, {'stat': 'OK', 'date': '20260929'}, {'stat': 'OK', 'date': '20261002'}):
                with patch.object(ph, '_http_json', return_value=payload):
                    self.assertIsNone(ph.fetch_inst_day('20260930'))

    def test_institutional_waits_for_official_day(self):
        self.assertEqual(ph._institutional_meta('2026-09-29', '2026-09-30', 1)[0], '等待當日發布')

    def test_breadth_day_rejects_response_that_states_another_day(self):
        # fetch_inst_day 已核對回應日；廣度之前直接把請求日當成資料日存起來。
        body = {'stat': 'OK', 'date': '20260930', 'tables': [{'title': '漲跌證券數合計', 'data': [
            ['上漲(漲停)', '1,000(10)', '800(9)'], ['下跌(跌停)', '500(2)', '400(1)'], ['持平', '100', '90']]}]}
        with patch.object(ph, '_taipei_today', return_value=date(2026, 10, 1)), \
                patch.object(ph, '_http_json', return_value=body):
            self.assertIsNone(ph.fetch_breadth_day('20261001'))
            got = ph.fetch_breadth_day('20260930')
        self.assertEqual((got['d'], got['up'], got['down'], got['limit_up']), ('2026-09-30', 800, 400, 9))

    def test_breadth_day_without_a_date_field_is_still_accepted(self):
        body = {'stat': 'OK', 'tables': [{'title': '漲跌證券數合計', 'data': [
            ['上漲(漲停)', '1,000(10)', '800(9)'], ['下跌(跌停)', '500(2)', '400(1)']]}]}
        with patch.object(ph, '_taipei_today', return_value=date(2026, 10, 1)), \
                patch.object(ph, '_http_json', return_value=body):
            self.assertEqual(ph.fetch_breadth_day('20260930')['up'], 800)

if __name__ == '__main__': unittest.main()
