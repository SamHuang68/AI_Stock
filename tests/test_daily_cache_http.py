"""真實 HTTP 邊界：市場隔離、唯讀 GET、研究查詢、選定更新與 gateway 權限。"""
import json
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from tests.test_server_http_security import ST
import datastore
import private_web_gateway as gateway
import daily_cache_jobs as jobs


class DailyHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = ThreadingHTTPServer(('127.0.0.1', 0), ST.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True); cls.thread.start()
        cls.base = 'http://127.0.0.1:' + str(cls.httpd.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown(); cls.httpd.server_close(); cls.thread.join()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patcher = patch.object(datastore, 'DB_PATH', str(Path(self.temp.name) / 'market.db'))
        self.patcher.start(); datastore.init_db()

    def tearDown(self):
        self.patcher.stop(); self.temp.cleanup()

    def get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=3) as response: return json.load(response)

    def test_bars_separates_markets_and_never_fetches_when_empty(self):
        datastore.upsert_bars('SAME', 'TW', [(100, 1, 2, 1, 2, 3)])
        datastore.upsert_bars('SAME', 'US', [(100, 10, 20, 10, 20, 30)])
        with patch.object(datastore, 'fetch_yahoo_daily') as network:
            self.assertEqual(self.get('/bars?sym=SAME&market=US')['candles'][0]['close'], 20)
            self.assertEqual(self.get('/bars?sym=SAME&market=TW')['candles'][0]['close'], 2)
            empty = self.get('/bars?sym=EMPTY&market=US')
        self.assertTrue(empty['cacheOnly']); self.assertEqual(empty['missing'], ['daily_bars']); network.assert_not_called()

    def test_empty_research_is_not_successful_evidence(self):
        result = self.get('/kline-events?sym=2330&range=all')
        self.assertEqual(result['eligibleDays'], 0); self.assertEqual(result['events'], [])
        self.assertIsNone(result['companyActionCoverage'])
        self.assertTrue(all(row['horizons']['1']['raw']['mean'] is None for row in result['stats']))

    def test_invalid_range_is_400(self):
        with self.assertRaises(urllib.error.HTTPError) as caught: self.get('/kline-events?sym=2330&range=invalid')
        self.assertEqual(caught.exception.code, 400); caught.exception.close()

    def test_selected_update_post_only_and_body_reaches_validated_worker(self):
        body = {'symbols': [{'symbol': '2330', 'market': 'TW'}], 'range': '1y'}
        req = urllib.request.Request(self.base + '/daily-cache/refresh', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        with patch.object(jobs, 'submit', return_value={'ok': True, 'status': 'queued'}) as submit:
            with urllib.request.urlopen(req, timeout=3) as response: self.assertTrue(json.load(response)['ok'])
            submit.assert_called_once_with(body)
        with self.assertRaises(urllib.error.HTTPError) as caught: self.get('/daily-cache/refresh')
        self.assertEqual(caught.exception.code, 405); caught.exception.close()

    def test_gateway_does_not_grant_reader_updates_or_private_job_status(self):
        settings = SimpleNamespace(extra_control_paths=set(), extra_read_paths=set())
        for endpoint in ('/daily-cache/refresh', '/daily-cache/cancel'):
            self.assertFalse(gateway.route_permission('POST', endpoint, 'reader', settings))
            self.assertTrue(gateway.route_permission('POST', endpoint, 'owner', settings))
        self.assertFalse(gateway.route_permission('GET', '/daily-cache/status', 'reader', settings))
        self.assertTrue(gateway.route_permission('GET', '/kline-events', 'reader', settings))

    def test_rejected_queue_returns_503(self):
        body = {'symbols': [{'symbol': '2330', 'market': 'TW'}], 'range': '1y'}
        req = urllib.request.Request(self.base + '/daily-cache/refresh', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
        with patch.object(jobs, 'submit', return_value={'ok': False, 'reason': 'queue_full', 'error': '佇列已滿'}):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req, timeout=3)
            self.assertEqual(caught.exception.code, 503)
            caught.exception.close()

    def test_datasource_invalid_symbols_are_bad_request(self):
        req = urllib.request.Request(self.base + '/datasource/refresh',
                data=json.dumps({'id': 'db', 'symbols': 'invalid'}).encode(),
                headers={'Content-Type': 'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=3)
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()


    def test_busy_job_returns_409_with_readable_message(self):
        req = urllib.request.Request(self.base + '/daily-cache/refresh',
                data=json.dumps({'symbols': [{'symbol': '2330', 'market': 'TW'}], 'range': '1y'}).encode(),
                headers={'Content-Type': 'application/json'})
        with patch.object(jobs, 'submit', return_value={'ok': False, 'reason': 'busy'}):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req, timeout=3)
            with caught.exception as error:
                self.assertEqual(error.code, 409)
                self.assertIn('更新進行中', json.load(error)['error'])


if __name__ == '__main__': unittest.main()
