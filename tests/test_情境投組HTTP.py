"""手動情境沿真實 HTTP 與投組計算，保持公開快照及保存行情不變。"""
from __future__ import annotations

import copy
import json
import socket
import sqlite3
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from contextlib import closing
from unittest.mock import patch

from tests import test_decision_http as decision_fixture
import datastore
import portfolio
import private_web_gateway as gateway

dc = decision_fixture.dc
st_server = decision_fixture.st_server


PROFILE = {
    'baseGrossExposure': 70, 'maxGrossExposure': 90, 'maxLeverage': 1,
    'maxSingleNameWeight': 20, 'maxSectorWeight': 40, 'maxPortfolioBeta': 1.1,
    'maxDailyVaR': 2, 'investmentHorizon': 'swing',
}


class SimulationHttpTest(unittest.TestCase):
    tearDown = decision_fixture.DecisionHttpTest.tearDown

    def setUp(self):
        decision_fixture.DecisionHttpTest.setUp(self)
        path = Path(self.tmp.name) / 'market.db'
        with closing(sqlite3.connect(path)) as conn:
            conn.executescript(datastore.SCHEMA)
            for symbol, multiplier in (('2330', 1), ('0050', 2), ('^TWII', 3)):
                conn.executemany('INSERT INTO bars VALUES(?,?,?,?,?,?,?,?)', [
                    (symbol, 'TW', day, price, price, price, price, 1000)
                    for day in range(80)
                    for price in [multiplier * (100 + day * .2 + day % 5 * .03)]
                ])
            conn.commit()
        self.market_path = path
        self.blocked = []
        for replacement in (
            patch.object(datastore, 'DB_PATH', str(path)),
            patch.object(st_server, '_TW_SECTORS', {'map': {'2330': '半導體業', '0050': '基金'}}),
            patch.object(st_server, '_TW_NAMES', {'map': {'2330': '測試公司', '0050': '測試基金'}}),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)
        for module, name in ((datastore, 'fetch_yahoo_daily'), (datastore, 'upsert_bars'),
                             (st_server, '_get_tw_sectors'), (st_server, '_get_tw_names')):
            replacement = patch.object(module, name, side_effect=AssertionError('情境不得回補或更新來源'))
            self.blocked.append(replacement.start())
            self.addCleanup(replacement.stop)
        original_connection = socket.create_connection

        def local_only(address, *args, **kwargs):
            if address[0] not in ('127.0.0.1', 'localhost', '::1'):
                raise AssertionError('本測試只允許隔離 loopback HTTP')
            return original_connection(address, *args, **kwargs)

        replacement = patch.object(socket, 'create_connection', side_effect=local_only)
        replacement.start()
        self.addCleanup(replacement.stop)

    def post(self, path, body, base=None, token=None):
        headers = {'Content-Type': 'application/json'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        request = urllib.request.Request((base or self.base) + path,
                                         data=json.dumps(body).encode(), headers=headers, method='POST')
        with urllib.request.urlopen(request, timeout=5) as response:
            return json.loads(response.read())

    def unchanged_state(self):
        dumps = {}
        for path in (self.market_path, Path(self.tmp.name) / 'decision.db', Path(self.signal_db_path)):
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as conn:
                dumps[path.name] = '\n'.join(conn.iterdump())
        return copy.deepcopy(dc._latest_context), copy.deepcopy(dc._latest_inputs), dumps

    def assert_sources_untouched(self):
        for blocked in self.blocked:
            blocked.assert_not_called()

    def test_complete_simulation_has_private_identity_and_keeps_all_public_evidence(self):
        before = self.unchanged_state()
        body = self.post('/decision/context', {
            'portfolioKind': 'simulation', 'portfolioInputStatus': 'complete',
            'riskProfile': PROFILE, 'holdings': [{'sym': '2330', 'weight': 40}, {'sym': '0050', 'weight': 60}],
        })
        overlay = body['portfolioOverlay']
        self.assertEqual(overlay['kind'], 'simulation')
        self.assertIn('手動權重', overlay['label'])
        self.assertTrue(overlay['available'])
        self.assertEqual(overlay['stocks']['2330']['weight'], 40)
        self.assertEqual(body['viewScope'], 'personal')
        self.assertEqual(body['persistence'], 'ephemeral')
        self.assertEqual(body['parentSnapshotId'], before[0]['snapshotId'])
        self.assertIsNotNone(body['actionEnvelope']['positionRange'])
        self.assertEqual(body['actionEnvelope']['positionRange'], body['exposureLab']['finalEligibleRange'])
        self.assertEqual(self.unchanged_state(), before)
        with urllib.request.urlopen(self.base + '/decision/context', timeout=5) as response:
            public = json.loads(response.read())
        self.assertIsNone(public['portfolioOverlay'])
        self.assertIsNone(public['actionEnvelope']['positionRange'])
        self.assertEqual(public['evidence'], before[0]['evidence'])
        self.assert_sources_untouched()

    def test_empty_incomplete_and_missing_history_never_produce_position_limits(self):
        before = self.unchanged_state()
        for status, holdings in (('empty', []), ('incomplete', []),
                                 ('complete', [{'sym': '9999', 'weight': 100}])):
            with self.subTest(status=status):
                body = self.post('/decision/context', {
                    'portfolioKind': 'simulation', 'portfolioInputStatus': status,
                    'riskProfile': PROFILE, 'holdings': holdings,
                })
                self.assertEqual(body['portfolioOverlay']['kind'], 'simulation')
                self.assertFalse(body['portfolioOverlay']['available'])
                self.assertIsNone(body['actionEnvelope']['positionRange'])
                self.assertIsNone(body['exposureLab']['finalEligibleRange'])
                self.assertEqual(body['portfolioInputStatus'], status)
        self.assertEqual(self.unchanged_state(), before)
        self.assert_sources_untouched()

    def test_portfolio_retains_simulation_kind_and_rejects_unknown_mode(self):
        before = self.unchanged_state()
        for symbol in ('2330', '9999'):
            body = self.post('/portfolio', {'portfolioKind': 'simulation',
                                          'holdings': [{'sym': symbol, 'weight': 100}]})
            self.assertEqual(body['kind'], 'simulation')
            self.assertIn('非實際持倉', body['label'])
            self.assertEqual(body['viewScope'], 'personal')
            if symbol == '9999':
                self.assertIn('error', body)
            else:
                self.assertEqual(body['stocks']['2330']['name'], '測試公司')
        for route in ('/portfolio', '/decision/context'):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.post(route, {'portfolioKind': 'unknown', 'holdings': [{'sym': '2330', 'weight': 100}]})
            self.assertEqual(caught.exception.code, 400)
            caught.exception.close()
        self.assertEqual(self.unchanged_state(), before)
        self.assert_sources_untouched()

    def test_reader_is_denied_by_real_gateway_before_any_simulation_compute(self):
        settings = gateway.Settings(
            listen_host='127.0.0.1', listen_port=0, upstream_host='127.0.0.1',
            upstream_port=self.httpd.server_port, owner_token='test-owner', read_token='test-reader',
            allowed_hosts=('127.0.0.1',), allowed_host_suffixes=(), max_body_bytes=4096,
            read_rate_per_minute=100, write_rate_per_minute=100, upstream_timeout_seconds=5,
            audit_path=Path(self.tmp.name) / 'gateway.jsonl',
            access_request_path=Path(self.tmp.name) / 'access.json',
            client_trace_path=Path(self.tmp.name) / 'client.jsonl',
        )
        service = gateway.PrivateWebServer(('127.0.0.1', 0), gateway.Handler, settings)
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{service.server_port}'
        before = self.unchanged_state()
        payload = {'portfolioKind': 'simulation', 'holdings': [{'sym': '2330', 'weight': 100}]}
        try:
            with patch.object(portfolio, 'compute', wraps=portfolio.compute) as compute:
                for route in ('/portfolio', '/decision/context'):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        self.post(route, payload, base=base, token='test-reader')
                    self.assertEqual(caught.exception.code, 403)
                    caught.exception.close()
                compute.assert_not_called()
                owner = self.post('/decision/context', payload, base=base, token='test-owner')
                self.assertEqual(owner['portfolioOverlay']['kind'], 'simulation')
                self.assertEqual(compute.call_count, 1)
            self.assertEqual(self.unchanged_state(), before)
            self.assert_sources_untouched()
        finally:
            service.shutdown()
            service.server_close()
            thread.join(timeout=2)

    def test_simulation_requires_explicit_weights_and_distinct_normalized_symbols(self):
        before = self.unchanged_state()
        invalid = [
            [{'sym': '2330'}], [{'sym': '2330', 'weight': True}],
            [{'sym': '2330', 'weight': 20}, {'sym': '2330.TW', 'weight': 80}],
            [{'sym': '2330', 'weight': 'NaN'}], [{'sym': '2330', 'weight': 'Infinity'}],
            [{'sym': '2330', 'weight': 0}], [{'sym': '2330', 'weight': -1}],
        ]
        with patch.object(portfolio, 'compute', wraps=portfolio.compute) as compute:
            for route in ('/portfolio', '/decision/context'):
                for holdings in invalid:
                    with self.subTest(route=route, holdings=holdings):
                        with self.assertRaises(urllib.error.HTTPError) as caught:
                            self.post(route, {'portfolioKind': 'simulation', 'holdings': holdings})
                        self.assertEqual(caught.exception.code, 400)
                        caught.exception.close()
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.post('/portfolio', {'portfolioKind': 'simulation', 'symbols': ['2330', '0050']})
            self.assertEqual(caught.exception.code, 400)
            caught.exception.close()
            compute.assert_not_called()
        self.assertEqual(self.unchanged_state(), before)
        self.assert_sources_untouched()

    def test_simulation_market_and_currency_cannot_be_discarded_or_invented(self):
        before = self.unchanged_state()
        invalid = [
            {'sym': '2330', 'weight': 100, 'market': 'HK', 'currency': 'HKD'},
            {'sym': '2330', 'weight': 100, 'market': 'TW', 'currency': 'USD'},
            {'sym': 'AAPL', 'weight': 100},
            {'sym': 'AAPL', 'weight': 100, 'market': 'US', 'currency': 'USD'},
            {'sym': 'AAPL', 'weight': 100, 'market': 'TW', 'currency': 'TWD'},
        ]
        with patch.object(portfolio, 'compute', wraps=portfolio.compute) as compute:
            for route in ('/portfolio', '/decision/context'):
                for row in invalid:
                    with self.subTest(route=route, row=row):
                        with self.assertRaises(urllib.error.HTTPError) as caught:
                            self.post(route, {'portfolioKind': 'simulation', 'holdings': [row]})
                        self.assertEqual(caught.exception.code, 400)
                        self.assertIn('TW／TWD', json.loads(caught.exception.read())['error'])
                        caught.exception.close()
            compute.assert_not_called()
        valid = self.post('/portfolio', {'portfolioKind': 'simulation',
                                        'holdings': [{'sym': '2330.tw', 'weight': 100}]})
        self.assertEqual(valid['stocks']['2330']['weight'], 100)
        self.assertEqual(self.unchanged_state(), before)
        self.assert_sources_untouched()


if __name__ == '__main__':
    unittest.main()
