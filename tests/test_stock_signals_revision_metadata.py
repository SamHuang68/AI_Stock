"""修訂中繼資料故障的真 SQLite 回歸；只使用合成行情與離線來源。"""
import hashlib
import io
import json
import os
import socket
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname
import nturl2path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import datastore as ds
import stock_signals_routes as routes
from 台股交易參考 import session

TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 8, 8, 0, tzinfo=TZ)
TEST_TEMP_ROOT = None
OBSERVATIONS = []


def database_path_for_guard(database, decoder=None):
    """保留本機平台的絕對路徑根；URI 只解碼一次。"""
    target = os.fspath(database)
    if target.startswith('file:'):
        target = (decoder or url2pathname)(urlsplit(target).path)
    return target


class SqliteGuardPathTests(unittest.TestCase):
    def test_uri_conversion_preserves_posix_and_windows_roots(self):
        cases = (
            ('file:///tmp/guard%252F/market%20data.db?mode=ro', unquote,
             '/tmp/guard%2F/market data.db'),
            ('file:///C:/fixture/guard%252F/market%20data.db?mode=ro',
             nturl2path.url2pathname, 'C:\\fixture\\guard%2F\\market data.db'),
        )
        for uri, decoder, expected in cases:
            with self.subTest(uri=uri):
                self.assertEqual(database_path_for_guard(uri, decoder), expected)

    def test_plain_database_path_is_not_uri_decoded(self):
        target = Path(tempfile.gettempdir()) / 'guard%2F' / 'market.db'
        decoder = mock.Mock(side_effect=AssertionError('一般路徑不應作 URI 解碼'))
        self.assertEqual(database_path_for_guard(target, decoder), os.fspath(target))
        decoder.assert_not_called()


def bar(day, opening, high, low, close):
    timestamp = int(datetime.fromisoformat(day).replace(hour=12, tzinfo=TZ).timestamp())
    return (timestamp, float(opening), float(high), float(low), float(close), 100.0)


OLD = bar('2026-10-06', 10, 11, 9, 10.5)
REVISION = bar('2026-10-06', 20, 22, 18, 21)
NEW = bar('2026-10-07', 11, 12, 10, 11.5)
LIVE = bar('2026-10-08', 12, 13, 11, 12.5)


def full_completed_rows():
    """真交易日曆中的 131 個完成日；含一筆已存原價的來源衝突。"""
    cursor, rows = date(2026, 10, 7), []
    while len(rows) < 131:
        state = session(cursor)
        if state['status'] == 'unknown':
            raise AssertionError('合成案例越出已涵蓋的年度日曆')
        if state['status'] == 'scheduled':
            rows.append(REVISION if cursor.isoformat() == '2026-10-06'
                        else bar(cursor.isoformat(), 11, 12, 10, 11.5))
        cursor -= timedelta(days=1)
    return list(reversed(rows))


class StockSignalsRevisionMetadataTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix='revision-metadata-', dir=TEST_TEMP_ROOT)
        self.addCleanup(self.directory.cleanup)
        self.db_path = Path(self.directory.name) / 'market.db'
        original_connect = sqlite3.connect

        def connect_only_temp(database, *arguments, **kwargs):
            target = database_path_for_guard(database)
            self.assertTrue(Path(target).resolve().is_relative_to(Path(self.directory.name).resolve()),
                            '測試拒絕開啟合成案例以外的資料庫')
            return original_connect(database, *arguments, **kwargs)

        for patcher in (
            mock.patch('sqlite3.connect', side_effect=connect_only_temp),
            mock.patch.object(ds, 'DB_PATH', str(self.db_path)),
            mock.patch('urllib.request.urlopen', side_effect=AssertionError('禁止測試連網')),
            mock.patch('socket.create_connection', side_effect=AssertionError('禁止測試連網')),
            mock.patch('socket.getaddrinfo', side_effect=AssertionError('禁止測試連網')),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        routes.clear_cache()
        self.addCleanup(routes.clear_cache)
        with redirect_stdout(io.StringIO()):
            ds.init_db()
        ds.upsert_bars('DEMO', 'TW', [OLD], source='Yahoo Finance')
        self.clock = [100.0]
        clock_patcher = mock.patch.object(routes.time, 'time', side_effect=lambda: self.clock[0])
        clock_patcher.start()
        self.addCleanup(clock_patcher.stop)
        self.fetches = []

    def remote(self, payload):
        def fetch(*arguments, **options):
            # _fetch_remote 另有可選的 receipt_out；替身不產生原始回應，收據維持空值（視為未附證據）。
            self.fetches.append(arguments)
            return list(payload)
        return mock.patch.object(routes, '_fetch_remote', side_effect=fetch)

    def metadata_failure(self):
        return mock.patch.object(ds, 'source_revision_status',
                                 side_effect=sqlite3.OperationalError('修訂中繼資料測試故障'))

    def summary(self, result):
        with ds.read_snapshot() as connection:
            prices = connection.execute('SELECT ts,close FROM bars ORDER BY ts').fetchall()
            revisions = connection.execute('SELECT id,payload FROM bar_source_revisions ORDER BY id').fetchall()
            integrity = connection.execute('PRAGMA integrity_check').fetchone()[0]
        self.assertEqual(dict(prices)[OLD[0]], OLD[4])
        self.assertEqual(integrity, 'ok')
        state = {'databaseBars': len(prices), 'returnedBars': len(result['bars']),
                 'originalPricePreserved': True, 'revisionCount': len(revisions),
                 'revisionEvidenceSha256': hashlib.sha256(json.dumps(revisions).encode()).hexdigest(),
                 'source': result['source'], 'warning': result.get('error'), 'retrySoon': result['retrySoon'],
                 'sourceRevisionStatusUnknown': result.get('sourceRevisionStatusUnknown'),
                 'integrity': integrity, 'remoteFetches': len(self.fetches)}
        OBSERVATIONS.append({'case': self.id().rsplit('.', 1)[-1], **state})
        return state

    def test_first_response_preserves_real_persisted_readback_and_original_price(self):
        with self.remote([REVISION, NEW]), self.metadata_failure():
            result = routes.load_bars('DEMO', 'TW', now=NOW)
        state = self.summary(result)
        self.assertEqual(state['databaseBars'], 2)
        self.assertEqual(state['revisionCount'], 1)
        self.assertEqual(len(result['bars']), 2)
        self.assertEqual(result['source'], 'local-db+yahoo')
        self.assertIn('來源修訂狀態待確認', result['error'])
        self.assertTrue(result['retrySoon'])
        self.assertIs(result.get('sourceRevisionStatusUnknown'), True)

    def test_metadata_failure_never_adds_intraday_live_extra(self):
        with self.remote([REVISION, NEW, LIVE]), self.metadata_failure():
            result = routes.load_bars('DEMO', 'TW', now=NOW.replace(hour=11))
        state = self.summary(result)
        self.assertEqual(state['databaseBars'], 2)
        self.assertEqual(len(result['bars']), 2)
        self.assertFalse(any(item['date'] == '2026-10-08' for item in result['bars']))
        self.assertIs(result.get('sourceRevisionStatusUnknown'), True)

    def test_unknown_quality_and_short_cache_survive_negative_cache_then_recover(self):
        with self.remote([REVISION, NEW]):
            with self.metadata_failure():
                first = routes.load_bars('DEMO', 'TW', now=NOW)
            first_state = self.summary(first)
            self.clock[0] = 101
            second = routes.load_bars('DEMO', 'TW', now=NOW)
            cache_only = routes.load_bars('DEMO', 'TW', allow_network=False, now=NOW)
            result = routes.analyze_symbol('DEMO', 'TW', with_stats=False, now=NOW)
            self.assertEqual(len(self.fetches), 1)
            self.assertIs(second.get('sourceRevisionStatusUnknown'), True)
            self.assertIs(cache_only.get('sourceRevisionStatusUnknown'), True)
            self.assertIn('來源修訂狀態待確認', cache_only['error'])
            self.assertEqual(result['dataQuality']['status'], 'unknown')
            self.assertIn('來源修訂狀態待確認', result['dataWarning'])
            self.assertEqual(routes._cache[('DEMO', 'TW', False)][0], 161)
            self.clock[0] = 161
            recovered = routes.load_bars('DEMO', 'TW', allow_network=False, now=NOW)
            recovered_state = self.summary(recovered)
            self.assertEqual(len(self.fetches), 1)
            self.assertFalse(recovered.get('sourceRevisionStatusUnknown'))
            self.assertFalse(recovered['retrySoon'])
            self.assertIn('歷史修訂', recovered['error'])
            self.assertEqual(first_state['revisionEvidenceSha256'], recovered_state['revisionEvidenceSha256'])

    def test_only_live_rows_do_not_claim_persisted_yahoo_source(self):
        with self.remote([LIVE]), self.metadata_failure():
            result = routes.load_bars('DEMO', 'TW', now=NOW.replace(hour=11))
        state = self.summary(result)
        self.assertEqual(state['databaseBars'], 1)
        self.assertEqual(len(result['bars']), 1)
        self.assertEqual(result['source'], 'local-db')
        self.assertIs(result.get('sourceRevisionStatusUnknown'), True)

    def test_success_keeps_historical_revision_warning_and_no_original_overwrite(self):
        with self.remote([REVISION, NEW]):
            result = routes.load_bars('DEMO', 'TW', now=NOW)
        state = self.summary(result)
        self.assertEqual(state['databaseBars'], 2)
        self.assertEqual(state['revisionCount'], 1)
        self.assertEqual(len(result['bars']), 2)
        self.assertIn('歷史修訂', result['error'])
        self.assertFalse(result.get('sourceRevisionStatusUnknown'))

    def test_persisted_revision_warning_survives_local_reads_and_cache_clear(self):
        with self.remote(full_completed_rows()):
            initial = routes.load_bars('DEMO', 'TW', now=NOW)
        baseline = self.summary(initial)
        with mock.patch.object(routes, '_fetch_remote', side_effect=AssertionError('本機讀取不得重抓')), \
             mock.patch.object(ds, 'upsert_bars', side_effect=AssertionError('本機讀取不得寫行情')):
            for clear_memory in (False, True):
                with self.subTest(clear_memory=clear_memory):
                    if clear_memory:
                        routes.clear_cache()
                    result = routes.load_bars('DEMO', 'TW', allow_network=False, now=NOW)
                    state = self.summary(result)
                    self.assertIn('歷史修訂', result['error'])
                    self.assertFalse(result['sourceRevisionStatusUnknown'])
                    self.assertFalse(result['retrySoon'])
                    self.assertEqual(state['revisionEvidenceSha256'], baseline['revisionEvidenceSha256'])

    def test_first_local_metadata_failure_is_unknown_and_obeys_backoff(self):
        with self.metadata_failure() as status:
            first = routes.load_bars('DEMO', 'TW', allow_network=False, now=NOW)
            self.clock[0] = 101
            repeated = routes.load_bars('DEMO', 'TW', allow_network=False, now=NOW)
            status.assert_called_once_with('DEMO', 'TW')
        self.assertTrue(first['sourceRevisionStatusUnknown'])
        self.assertTrue(first['retrySoon'])
        self.assertEqual(repeated['error'], first['error'])
        self.clock[0] = 161
        recovered = routes.load_bars('DEMO', 'TW', allow_network=False, now=NOW)
        self.assertFalse(recovered['sourceRevisionStatusUnknown'])
        self.assertFalse(recovered['retrySoon'])

    def analyze_stored_rows(self, symbol, market, rows):
        # Legacy stored rows can include provider prices during a suspension;
        # health must check tradability independently of the newer ingest filter.
        ds.upsert_bars(symbol, market, rows)
        # Only isolate the unrelated pooled-result cache; calendar, loader,
        # normalization, health analysis and quality assessment remain production.
        with mock.patch('signal_stats_pool.load_cached', return_value=None):
            return routes.analyze_symbol(symbol, market, with_stats=False,
                                         allow_network=False, use_cache=False,
                                         chip_dir=self.directory.name, now=NOW)

    def test_health_missing_whole_tw_session_restarts_warmup(self):
        rows = full_completed_rows()
        result = self.analyze_stored_rows('2330', 'TW', rows[:-10] + rows[-9:])
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'INSUFFICIENT_BARS')
        self.assertEqual(result['bars'], 9)
        self.assertEqual(result['dataQuality']['continuousBars'], 9)
        quality = result['dataQuality']
        self.assertEqual(quality['rawInputBars'], 130)
        self.assertEqual(quality['inputBars'], 131, '日曆對齊後包含缺日邊界列')
        self.assertEqual(quality['excludedBeforeLastGap'], 122)
        self.assertEqual(quality['inputBars'], quality['continuousBars'] + quality['excludedBeforeLastGap'])

    def test_health_calendar_failure_is_explicit_and_preserves_source_warning(self):
        ds.upsert_bars('DEMO', 'TW', full_completed_rows(), source='Yahoo Finance')
        for failure in ('malformed_json', 'query_failure'):
            with self.subTest(failure=failure):
                with closing(ds.get_conn()) as connection, connection:
                    if failure == 'malformed_json':
                        connection.execute('INSERT OR REPLACE INTO calendar_years VALUES(?,?,?,?)',
                                           (2026, 'invalid-json', '[]', 'fixture'))
                    else:
                        connection.execute('ALTER TABLE calendar_years RENAME COLUMN closed TO fixture_closed')
                with mock.patch('signal_stats_pool.load_cached', return_value=None), \
                     mock.patch.object(routes.ss, 'build_frame', side_effect=AssertionError('日曆失敗不得計算指標')) as frame:
                    result = routes.analyze_symbol('DEMO', 'TW', with_stats=False, allow_network=False,
                                                   use_cache=False, chip_dir=self.directory.name, now=NOW)
                    frame.assert_not_called()
                self.assertFalse(result['ok'])
                self.assertEqual(result['reason'], 'CALENDAR_UNAVAILABLE')
                self.assertIn('日曆無法核對', result['message'])
                self.assertNotIn('日線不足', result['message'])
                self.assertIn('日曆無法核對', result['dataWarning'])
                self.assertIn('歷史修訂', result['dataWarning'])
                self.assertEqual(result['dataQuality']['status'], 'unknown')
                self.assertEqual(result['dataQuality']['rawInputBars'], 131)
                self.assertEqual(result['dataQuality']['inputBars'], 0)
                self.assertEqual(len(ds.get_bars('DEMO', market='TW')), 131)

    def test_health_closed_only_history_is_empty_not_calendar_failure(self):
        rows = [bar('2026-10-03', 10, 11, 9, 10), bar('2026-10-04', 10, 11, 9, 10)]
        result = self.analyze_stored_rows('2330', 'TW', rows)
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'], 'INSUFFICIENT_BARS')
        self.assertEqual(result['dataQuality']['rawInputBars'], 2)
        self.assertEqual(result['dataQuality']['inputBars'], 0)
        self.assertNotIn('日曆無法核對', result.get('dataWarning', ''))

    def test_health_official_holidays_do_not_reset_complete_tw_history(self):
        result = self.analyze_stored_rows('2330', 'TW', full_completed_rows())
        self.assertTrue(result['ok'])
        self.assertEqual(result['bars'], 131)
        self.assertEqual(result['dataQuality']['continuousBars'], 131)

    def test_health_known_suspension_resets_warmup_even_if_provider_has_prices(self):
        result = self.analyze_stored_rows('1441', 'TW', full_completed_rows())
        self.assertFalse(result['ok'])
        # Official resumption 2026-09-29 through 2026-10-07: seven sessions.
        self.assertEqual(result['bars'], 7)
        self.assertEqual(result['dataQuality']['continuousBars'], 7)
        self.assertEqual(result['dataQuality']['inputBars'], 131)

    def test_health_missing_whole_us_session_restarts_warmup(self):
        from us_equity_calendar import session as us_session, TZ as us_tz
        cursor, rows = date(2026, 10, 7), []
        while len(rows) < 131:
            if us_session(cursor)['status'] == 'scheduled':
                timestamp = int(datetime.combine(cursor, datetime.min.time(), tzinfo=us_tz)
                                .replace(hour=16).timestamp())
                rows.append((timestamp, 100.0, 101.0, 99.0, 100.0, 1000.0))
            cursor -= timedelta(days=1)
        rows.reverse()
        result = self.analyze_stored_rows('AAPL', 'US', rows[:-10] + rows[-9:])
        self.assertFalse(result['ok'])
        self.assertEqual(result['bars'], 9)
        self.assertEqual(result['dataQuality']['continuousBars'], 9)

    def test_full_closed_snapshot_recovers_metadata_without_network_or_writes(self):
        with self.remote(full_completed_rows()), self.metadata_failure():
            first = routes.load_bars('DEMO', 'TW', now=NOW)
        first_state = self.summary(first)
        self.assertGreaterEqual(first_state['databaseBars'], 130)
        self.assertFalse(first['session']['sessionOpen'])
        self.assertEqual(first['bars'][-1]['date'], first['session']['expectedLastDate'])
        self.assertIs(first.get('sourceRevisionStatusUnknown'), True)
        self.clock[0] = 161
        with mock.patch.object(routes, '_fetch_remote', side_effect=AssertionError('完整快照不得重抓')) as fetch, \
             mock.patch.object(ds, 'upsert_bars', side_effect=AssertionError('metadata 重試不得寫行情')) as write, \
             mock.patch.object(ds, 'source_revision_status', wraps=ds.source_revision_status) as status:
            recovered = routes.load_bars('DEMO', 'TW', allow_network=False, now=NOW)
            fetch.assert_not_called()
            write.assert_not_called()
            status.assert_called_once_with('DEMO', 'TW')
        state = self.summary(recovered)
        self.assertFalse(recovered.get('sourceRevisionStatusUnknown'))
        self.assertFalse(recovered['retrySoon'])
        self.assertIn('歷史修訂', recovered['error'])
        self.assertEqual(state['revisionCount'], 1)
        self.assertEqual(state['revisionEvidenceSha256'], first_state['revisionEvidenceSha256'])
        again = routes.load_bars('DEMO', 'TW', allow_network=False, now=NOW)
        self.assertIn('歷史修訂', again['error'])

    def test_full_closed_metadata_retry_failure_keeps_reason_until_readonly_recovery(self):
        with self.remote(full_completed_rows()), self.metadata_failure():
            first = routes.load_bars('DEMO', 'TW', now=NOW)
        initial_state = self.summary(first)
        self.clock[0] = 161
        with mock.patch.object(routes, '_fetch_remote', side_effect=AssertionError('完整快照不得重抓')) as fetch, \
             mock.patch.object(ds, 'upsert_bars', side_effect=AssertionError('metadata 重試不得寫行情')) as write:
            with self.metadata_failure() as status:
                repeated = routes.load_bars('DEMO', 'TW', allow_network=False, now=NOW)
                self.assertIs(repeated.get('sourceRevisionStatusUnknown'), True)
                self.assertTrue(repeated['retrySoon'])
                self.assertIn('修訂中繼資料測試故障', repeated['error'])
                self.assertEqual(routes._remote_fail[('DEMO', 'TW')], 221)
                self.clock[0] = 162
                within_backoff = routes.load_bars('DEMO', 'TW', now=NOW)
                status.assert_called_once_with('DEMO', 'TW')
                self.assertEqual(within_backoff['error'], repeated['error'])
                self.assertIs(within_backoff.get('sourceRevisionStatusUnknown'), True)
            self.clock[0] = 221
            with mock.patch.object(ds, 'source_revision_status', wraps=ds.source_revision_status) as status:
                recovered = routes.load_bars('DEMO', 'TW', now=NOW)
                status.assert_called_once_with('DEMO', 'TW')
            fetch.assert_not_called()
            write.assert_not_called()
        state = self.summary(recovered)
        self.assertFalse(recovered.get('sourceRevisionStatusUnknown'))
        self.assertIn('歷史修訂', recovered['error'])
        self.assertEqual(state['revisionEvidenceSha256'], initial_state['revisionEvidenceSha256'])
        self.assertNotIn(('DEMO', 'TW'), routes._remote_fail)

    def test_zero_revisions_metadata_recovery_preserves_unknown_calendar_warning(self):
        with self.remote([OLD, NEW]), self.metadata_failure():
            routes.load_bars('DEMO', 'TW', now=NOW)
        self.clock[0] = 161
        with mock.patch.object(routes, '_fetch_remote', side_effect=AssertionError('禁止測試連網')) as fetch:
            recovered = routes.load_bars('DEMO', 'TW', allow_network=False, now=NOW.replace(year=2027))
            fetch.assert_not_called()
        state = self.summary(recovered)
        self.assertFalse(recovered.get('sourceRevisionStatusUnknown'))
        self.assertEqual(state['revisionCount'], 0)
        self.assertIn('尚無該年度官方交易日曆', recovered['error'])
        self.assertIsNone(recovered['session']['expectedLastDate'])


if __name__ == '__main__':
    unittest.main()
