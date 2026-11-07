"""共用成交解析與四個正式 HTTP 路徑的回歸案例。"""
import importlib.util
import json
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
from market_routes import twse_mis_stock_quote, quote_observation, guard_tw_quote

NOW = datetime.fromisoformat('2026-09-17T09:20:00+08:00')


def row(code='2330', **values):
    return dict({'c': code, 'd': '20260917', 't': '09:19:40',
                 'tlong': int(datetime.fromisoformat('2026-09-17T09:19:40+08:00').timestamp() * 1000),
                 'z': '-', 'y': '2380', 'v': '4843', 'o': '2405', 'h': '2440', 'l': '2400',
                 'a': '2435_', 'b': '2430_', 'trade': {'t': '09:19:30', 'z': '2430'}}, **values)


class MisQuoteTests(unittest.TestCase):
    def test_nested_trade_keeps_trade_and_volume_timestamps_separate(self):
        q = twse_mis_stock_quote(row(), NOW)
        self.assertEqual(q['price'], 2430)
        self.assertEqual(q['priceField'], 'trade.z')
        self.assertAlmostEqual(q['changePct'], 50 / 2380 * 100)
        self.assertEqual(q['time'], '09:19:30')
        self.assertEqual(q['volumeShares'], 4843000)
        self.assertEqual(q['volumeTimestampMs'] - q['timestampMs'], 10000)

    def test_legacy_trade_wins_and_order_book_never_becomes_trade(self):
        self.assertEqual(twse_mis_stock_quote(row(z='2425'), NOW)['price'], 2425)
        for trade in [None, {}, {'z': 'NaN', 't': '09:19:30'}, {'z': '0', 't': '09:19:30'},
                      {'z': '2430', 't': '09:30:00'}, {'z': '2430'}, {'z': 'inf', 't': '09:19:30'}]:
            with self.subTest(trade=trade):
                self.assertIsNone(twse_mis_stock_quote(row(trade=trade), NOW))

    def test_stale_backup_is_not_a_current_price_during_session(self):
        old = int(datetime.fromisoformat('2026-09-16T13:30:10+08:00').timestamp() * 1000)
        guarded = guard_tw_quote({'ok': True, 'price': 2380, 'changePct': -0.21, 'timestampMs': old}, NOW)
        self.assertFalse(guarded['ok'])
        self.assertIsNone(guarded['price'])
        self.assertIsNone(guarded['changePct'])
        self.assertEqual(guarded['lastKnownPrice'], 2380)
        self.assertTrue(guard_tw_quote({'price': 2380}, NOW)['stale'])

    def test_stock_etf_and_otc_share_the_same_trade_parser(self):
        for code in ['2330', '2308', '2885', '2883', '5347', '00631L', '00981A']:
            with self.subTest(code=code):
                self.assertEqual(twse_mis_stock_quote(row(code), NOW)['code'], code)


class QuoteRouteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location(
            'st_server_realtime_quote_test', ROOT / 'server/server.py')
        cls.server = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.server)
        cls.addClassCleanup(cls.server._pool.shutdown)

    def setUp(self):
        self.pool = ThreadPoolExecutor(4)
        self.addCleanup(self.pool.shutdown)
        self.fetch = Mock(return_value={'msgArray': [row(), row('5347'), row('00631L')]})
        self.yahoo = Mock(return_value=('2330.TW', json.dumps({'chart': {'result': [{'meta': {
            'regularMarketPrice': 2380, 'regularMarketTime': int(NOW.timestamp()) - 86400,
            'chartPreviousClose': 2385}}]}}), False))
        # Keep the real module namespace, including _trusted_prev_close and
        # log_once. Only replace external data, wall-clock inputs and the pool.
        # patch.object defaults to create=False: a removed production dependency
        # must fail setup rather than silently acquiring a test-only stand-in.
        for name, value in {
            '_src_fetch_json': self.fetch,
            'fetch_one': self.yahoo,
            'twse_mis_stock_quote': lambda r: twse_mis_stock_quote(r, NOW),
            'quote_observation': lambda t: quote_observation(t, NOW),
            'guard_tw_quote': lambda r: guard_tw_quote(r, NOW),
            '_pool': self.pool,
        }.items():
            dependency = patch.object(self.server, name, value)
            dependency.start()
            self.addCleanup(dependency.stop)

    def call(self, method, path, *args):
        handler = self.server.Handler.__new__(self.server.Handler)
        handler.path = path
        handler._ok = lambda b: setattr(handler, 'result', json.loads(b))
        getattr(handler, method)(*args)
        return handler.result

    def test_all_four_routes_prefer_official_nested_trade(self):
        single = self.call('_handle_twquote', '/twquote?code=2330')
        alias = self.call('_handle_quote', '/quote/2330.TW', '2330.TW')
        batch = self.call('_handle_twquote_batch', '/twquote-batch?codes=2330,5347,00631L')
        mixed = self.call('_handle_quote_batch', '/quote-batch?syms=2330.TW,5347.TWO,00631L.TW')
        for q in [single, alias, *batch.values(), *mixed.values()]:
            self.assertEqual(q['price'], 2430)
            self.assertEqual(q['source'], 'twse-mis')
            self.assertIn('asOf', q)
        self.yahoo.assert_not_called()
        self.assertEqual(alias['volume'], 4843000)
        self.assertEqual(single['volume'], 4843)

    def test_no_official_trade_and_yesterday_yahoo_do_not_look_current(self):
        self.fetch.return_value = {'msgArray': [row(trade={})]}
        single = self.call('_handle_twquote', '/twquote?code=2330')
        batch = self.call('_handle_quote_batch', '/quote-batch?syms=2330.TW')
        for q in [single, batch['2330.TW']]:
            self.assertFalse(q['ok'])
            self.assertIsNone(q['price'])
            self.assertEqual(q['quoteStatus'], 'stale')
        self.assertEqual(single['volumeShares'], 4843000)
        self.assertEqual(single['volumeSource'], 'twse-mis')

    def test_non_tw_quotes_keep_their_own_session(self):
        q = self.call('_handle_quote_batch', '/quote-batch?syms=NVDA')['NVDA']
        self.assertEqual(q['price'], 2380)
        self.assertFalse(q['stale'])
        self.fetch.assert_not_called()


if __name__ == '__main__':
    unittest.main()
