# -*- coding: utf-8 -*-
"""NHNL 正式來源流程回歸；網路替身與 SQLite fixture 僅使用隔離工作樹 scratch。"""
import contextlib
from datetime import date, datetime, timedelta, timezone
import io
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import pulse_extras as px
from deadline import BoundedExecutor, Deadline


def timestamps(count=250):
    end = date(2026, 9, 18)
    days = [end - timedelta(days=i) for i in range(count * 2 + 10)]
    days = sorted(day for day in days if day.weekday() < 5)[-count:]
    return [int(datetime(day.year, day.month, day.day, 1, tzinfo=timezone.utc).timestamp()) for day in days]


def chart(symbol, values=None):
    values = values if values is not None else [100.0] * 249 + [120.0]
    return {'chart': {'result': [{'meta': {'symbol': symbol}, 'timestamp': timestamps(len(values)),
                                'indicators': {'quote': [{'close': values}]}}], 'error': None}}


def symbol_from(url):
    return urlparse(url).path.rsplit('/', 1)[-1]


def http_error(url, status):
    return urllib.error.HTTPError(url, status, '測試來源失敗', {}, io.BytesIO(b'{}'))


class NHNLSourceTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / 'scratch'
        scratch.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='NHNL測試-', dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.executor = BoundedExecutor(6, 36, prefix='nhnl-test')
        self.addCleanup(self.executor.shutdown)
        self.patches = contextlib.ExitStack()
        self.addCleanup(self.patches.close)
        self.patches.enter_context(patch.object(px, '_BASE', str(self.base)))
        self.patches.enter_context(patch.object(px, '_NHNL_EXECUTOR', self.executor))
        self.patches.enter_context(patch.object(px, '_mem', {}))
        self.log = io.StringIO()
        self.patches.enter_context(contextlib.redirect_stdout(self.log))

    def database(self, symbols):
        directory = self.base / 'data'
        directory.mkdir(exist_ok=True)
        with contextlib.closing(sqlite3.connect(directory / 'market.db')) as conn:
            conn.execute('CREATE TABLE bars(symbol TEXT,market TEXT,ts INTEGER,close REAL)')
            conn.executemany('INSERT INTO bars VALUES(?,?,?,?)',
                             [(symbol, 'TW', ts, 100.0 + i) for symbol in symbols for i, ts in enumerate(timestamps())])
            conn.commit()

    def test_listed_uses_tw_without_extra_network(self):
        calls = []
        def fetch(url, timeout):
            calls.append((url, timeout))
            return chart(symbol_from(url))
        with patch.object(px, '_http_json', side_effect=fetch):
            code, closes, detail = px._nhnl_yahoo_closes('2330', Deadline(7))
        self.assertEqual(code, '2330')
        self.assertEqual(len(closes), 250)
        self.assertEqual(detail['symbol'], '2330.TW')
        self.assertEqual(detail['sessionDate'], '2026-09-18')
        self.assertEqual(len(calls), 1)
        self.assertIn('query1.finance.yahoo.com', calls[0][0])
        self.assertGreater(calls[0][1], 0)
        self.assertLessEqual(calls[0][1], 6)

    def test_otc_404_switches_suffix_and_remembers_verified_route(self):
        for code in ('5274', '6488'):
            calls = []
            def fetch(url, timeout):
                symbol = symbol_from(url)
                calls.append(symbol)
                if symbol.endswith('.TW'):
                    raise http_error(url, 404)
                return chart(symbol)
            with patch.object(px, '_http_json', side_effect=fetch):
                _, closes, detail = px._nhnl_yahoo_closes(code, Deadline(7))
                self.assertEqual(len(closes), 250)
                self.assertEqual(calls, [code + '.TW', code + '.TWO'])
                self.assertEqual(detail['attempts'][0]['httpStatus'], 404)
                self.assertEqual(detail['attempts'][1]['httpStatus'], 200)
                px._nhnl_yahoo_closes(code, Deadline(7))
                self.assertEqual(calls[-1], code + '.TWO')
                self.assertEqual(len(calls), 3)

    def test_host_failure_retries_same_symbol_on_query2(self):
        calls = []
        def fetch(url, timeout):
            calls.append(url)
            if 'query1.' in url:
                raise http_error(url, 503)
            return chart(symbol_from(url))
        with patch.object(px, '_http_json', side_effect=fetch):
            _, closes, detail = px._nhnl_yahoo_closes('2330.TW', Deadline(7))
        self.assertEqual(len(closes), 250)
        self.assertEqual([symbol_from(url) for url in calls], ['2330.TW', '2330.TW'])
        self.assertEqual(detail['attempts'][0]['httpStatus'], 503)
        self.assertEqual(detail['attempts'][1]['host'], 'query2')

    def test_invalid_prices_and_duplicate_dates_cannot_fill_250_days(self):
        for bad in (None, math.nan, math.inf, -math.inf, 0, -1, True, '非數字'):
            with patch.object(px, '_http_json', return_value=chart('2330.TW', [100.0] * 249 + [bad])):
                _, closes, detail = px._nhnl_yahoo_closes('2330', Deadline(7))
            self.assertIsNone(closes)
            self.assertEqual(detail['status'], 'insufficient_history')
            self.assertEqual(detail['validBars'], 249)
        duplicate = chart('2330.TW')
        duplicate['chart']['result'][0]['timestamp'] = [timestamps(1)[0]] * 250
        with patch.object(px, '_http_json', return_value=duplicate):
            self.assertIsNone(px._nhnl_yahoo_closes('2330', Deadline(7))[1])
        missing_dates = chart('2330.TW')
        missing_dates['chart']['result'][0]['timestamp'] = []
        with patch.object(px, '_http_json', return_value=missing_dates):
            self.assertIsNone(px._nhnl_yahoo_closes('2330', Deadline(7))[1])
        self.assertIsNone(px.count_nhnl({str(i): [100.0] * 249 + [math.inf] for i in range(12)}))
        flat = px.count_nhnl({str(i): [100.0] * 250 for i in range(12)})
        self.assertEqual((flat['newHighs'], flat['newLows']), (0, 0))
        self.assertIsNone(flat['date'], '純計算不可用今日冒充來源交易日')

    def test_daily_series_sorted_with_one_value_per_day(self):
        ts = timestamps(250)
        payload = chart('2330.TW')
        payload['chart']['result'][0]['timestamp'] = list(reversed(ts)) + [ts[-1]]
        payload['chart']['result'][0]['indicators']['quote'][0]['close'] = list(range(349, 99, -1)) + [500]
        with patch.object(px, '_http_json', return_value=payload):
            _, closes, detail = px._nhnl_yahoo_closes('2330', Deadline(7))
        self.assertEqual(len(closes), 250)
        self.assertEqual(closes[-1], 500)
        self.assertEqual(detail['sessionDate'], '2026-09-18')

    def test_point_after_yahoo_declared_session_is_not_a_new_daily_bar(self):
        payload = chart('5274.TWO')
        row = payload['chart']['result'][0]
        row['meta']['currentTradingPeriod'] = {'regular': {'start': timestamps(1)[0]}}
        row['timestamp'].append(int(datetime(2026, 9, 20, 3, tzinfo=timezone.utc).timestamp()))
        row['indicators']['quote'][0]['close'].append(99999.0)
        with patch.object(px, '_http_json', return_value=payload):
            _, closes, detail = px._nhnl_yahoo_closes('5274.TWO', Deadline(7))
        self.assertEqual(len(closes), 250)
        self.assertEqual(closes[-1], 120)
        self.assertEqual(detail['sessionDate'], '2026-09-18')
        self.assertEqual(detail['ignoredAfterSessionN'], 1)

    def test_wrong_identity_or_chart_errors_never_count_as_closes(self):
        for payload in (chart('其他股票.TW'), {'chart': {'result': None, 'error': {'code': 'Not Found'}}}, {'chart': {'result': []}}):
            with patch.object(px, '_http_json', return_value=payload):
                _, closes, detail = px._nhnl_yahoo_closes('2330', Deadline(7))
            self.assertIsNone(closes)
            self.assertEqual(detail['status'], 'source_error')
            self.assertTrue(detail['attempts'])

    def test_db_keeps_tw_market_for_otc_and_avoids_yahoo(self):
        symbols = ['5274', '6488'] + [str(1000 + i) for i in range(10)]
        self.database(symbols)
        with patch.object(px, '_NHNL_UNIVERSE', symbols), patch.object(px, '_http_json', side_effect=AssertionError('完整 DB 不應抓 Yahoo')) as fetch:
            result = px.fetch_nhnl_sample()
        self.assertFalse(fetch.called)
        self.assertEqual(result['sampleN'], 12)
        self.assertEqual(result['source'], 'market.db')
        self.assertEqual(result['date'], '2026-09-18')
        self.assertFalse(result['freshnessVerified'])
        self.assertIn('來源效期未驗證', result['note'])
        self.assertEqual(result['sourceDetails']['missingSymbols'], [])

    def test_partial_source_failure_is_visible_without_faking_full_coverage(self):
        symbols = [str(1000 + i) for i in range(12)]
        self.database(symbols)
        universe = symbols + ['5274', '6488']
        with patch.object(px, '_NHNL_UNIVERSE', universe), patch.object(px, '_http_json', side_effect=lambda url, timeout: (_ for _ in ()).throw(http_error(url, 429))):
            result = px.fetch_nhnl_sample()
        self.assertEqual(result['sampleN'], 12)
        self.assertEqual(result['universeN'], 14)
        self.assertEqual(result['source'], 'market.db', '未貢獻資料的 Yahoo 不能列為行情來源')
        self.assertEqual(result['sourceDetails']['yahooN'], 0)
        self.assertEqual(result['sourceDetails']['missingSymbols'], ['5274', '6488'])
        self.assertEqual(result['sourceDetails']['yahoo']['5274']['status'], 'source_error')
        self.assertIn('429', self.log.getvalue())

    def test_total_failure_remains_pending_not_zero(self):
        with patch.object(px, '_NHNL_UNIVERSE', [str(1000 + i) for i in range(12)]), patch.object(px, '_http_json', side_effect=lambda url, timeout: (_ for _ in ()).throw(http_error(url, 404))):
            result = px.fetch_nhnl_sample()
        self.assertIsNone(result)
        self.assertIn('nhnl unavailable', self.log.getvalue())
        self.assertNotIn('nhnl:' + date.today().isoformat(), px._mem)

    def test_cap_and_thresholds_unchanged_and_unattempted_exposed(self):
        self.assertEqual((px.NHNL_MIN_BARS, px.NHNL_MIN_SAMPLE, px.NHNL_YAHOO_WORKERS, px.NHNL_YAHOO_BUDGET), (250, 12, 6, 7.0))
        universe = [str(1000 + i) for i in range(50)]
        with patch.object(px, '_NHNL_UNIVERSE', universe), patch.object(px, '_http_json', side_effect=lambda url, timeout: chart(symbol_from(url))):
            result = px.fetch_nhnl_sample()
        self.assertEqual(result['sampleN'], 36)
        self.assertEqual(result['sourceDetails']['notAttempted'], universe[36:])
        self.assertEqual(result['sourceDetails']['missingSymbols'], universe[36:])
        self.assertIn('36/50', result['note'])

    def test_deadline_stays_bounded_and_late_response_cannot_publish(self):
        with patch.object(px, '_http_json', side_effect=AssertionError('到期不應啟動請求')) as fetch:
            self.assertEqual(px._nhnl_yahoo_closes('2330', Deadline(0))[2]['status'], 'timeout')
        self.assertFalse(fetch.called)
        release = threading.Event()
        def fetch(url, timeout):
            release.wait(1)
            return chart(symbol_from(url))
        with patch.object(px, '_NHNL_UNIVERSE', [str(1000 + i) for i in range(12)]), patch.object(px, 'NHNL_YAHOO_BUDGET', 0.03), patch.object(px, '_http_json', side_effect=fetch):
            started = time.monotonic()
            try:
                result = px.fetch_nhnl_sample()
                self.assertLess(time.monotonic() - started, 0.5)
                self.assertIsNone(result)
            finally:
                release.set()
                self.executor.shutdown()
        self.assertEqual(px._mem, {}, '逾時的晚回應不得發布結果或改寫已驗證路由快取')


if __name__ == '__main__':
    unittest.main()
