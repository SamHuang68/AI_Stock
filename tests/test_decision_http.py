# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import importlib.util
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from datetime import datetime, timezone
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

import decision_context as dc  # noqa: E402
import options_exposure as ox  # noqa: E402
import overnight_intraday as oi  # noqa: E402

# Load Stock Terminal's single-file HTTP server under a collision-free name.
# The optional WaveDeck project deliberately owns the top-level ``server``
# package, so importing server/server.py as ``server`` makes full-suite test
# discovery order-dependent.
_SERVER_SPEC = importlib.util.spec_from_file_location(
    'stock_terminal_http_server_test', ROOT / 'server' / 'server.py'
)
if _SERVER_SPEC is None or _SERVER_SPEC.loader is None:  # pragma: no cover
    raise RuntimeError('Unable to load Stock Terminal HTTP server for tests')
st_server = importlib.util.module_from_spec(_SERVER_SPEC)
sys.modules[_SERVER_SPEC.name] = st_server
_SERVER_SPEC.loader.exec_module(st_server)


def _pulse() -> dict:
    as_of = datetime.now(timezone.utc).isoformat()
    twii = {'price': 23000, 'changePct': 1.0,
            'market': {'displayChangePct': 1.0, 'source': 'twse-mis', 'session': 'regular',
                       'referenceType': 'previous_close', 'asOf': as_of}}
    txf = {'price': 23020, 'changePct': 0.8,
           'market': {'displayChangePct': 0.8, 'source': 'taifex-mis', 'session': 'night',
                      'referenceType': 'previous_close', 'asOf': as_of}}
    return {
        'ok': True, 'updatedAt': as_of, 'date': as_of[:10],
        'marketSnapshot': {'quotes': {'^TWII': twii, '__TXF__': txf}},
        'stocks': {'up': 700, 'down': 300, 'advRatio': 0.7, 'limitDown': 1},
        'snapshot': {'stocks': {'up': 700, 'down': 300, 'advRatio': 0.7, 'limitDown': 1},
                     'inst': {'totalYi': 160}},
        'healthScore': 75, 'riskScore': 25, 'dataCompleteness': 90,
        'breadthScope': 'TWSE_STOCKS', 'breadthSource': 'TWSE MI_INDEX MS',
        'overview': {'strip': {'volumeScore': 70, 't00Trend': {'momScore': 70}}},
        'global': [], 'sectors': [], 'flash': [],
    }


class DecisionHttpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_options_history = ox.HISTORY_PATH
        ox.HISTORY_PATH = str(Path(self.tmp.name) / 'options-history.json')
        with oi._CACHE_LOCK:
            oi._CACHE.clear()
        levels = {'levels': {'r1': 23100, 'pivot': 22950, 's1': 22800},
                  'atr': {'pct': 1.5}, 'quality': {'complete': True, 'stale': False}}
        p = _pulse()
        ctx = dc.build_decision_context(p, key_levels=levels)
        dc.publish_context(ctx, pulse=p, build_kwargs={'key_levels': levels},
                           db_path=str(Path(self.tmp.name) / 'decision.db'),
                           trace_path=str(Path(self.tmp.name) / 'decision.jsonl'))
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), st_server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.httpd.server_port}'

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        ox.HISTORY_PATH = self.old_options_history
        self.tmp.cleanup()

    def test_get_context_returns_canonical_contract(self):
        with urllib.request.urlopen(self.base + '/decision/context', timeout=5) as resp:
            body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertEqual(body['contractVersion'], 2)
        self.assertEqual(body['regime']['id'], 'BROAD_RISK_ON')
        self.assertTrue(body['evidence'])
        self.assertTrue(body['earlyWarnings']['shadowOnly'])
        self.assertEqual(body['consensusAttention']['authority'], 'attention_only')
        self.assertLessEqual(len(body['consensusAttention']['items']), 5)
        self.assertTrue(any(row.get('id') == 'signal.prospective_validation'
                            for row in body['evidence']))

    def test_signal_routes_expose_shadow_state_and_transition_history(self):
        with urllib.request.urlopen(self.base + '/signals/active', timeout=5) as resp:
            active = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertTrue(active['shadowOnly'])
        self.assertTrue(active['signals'])
        with urllib.request.urlopen(self.base + '/signals/history?limit=10', timeout=5) as resp:
            history = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertTrue(history['shadowOnly'])
        self.assertLessEqual(len(history['events']), 10)
        with urllib.request.urlopen(self.base + '/signals/performance?limit=10', timeout=5) as resp:
            performance = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertTrue(performance['shadowOnly'])
        self.assertEqual(performance['actionAuthority'], 'none')
        self.assertIn('horizons', performance)

    def test_options_refresh_publishes_back_into_canonical_context(self):
        fixture = {
            'ok': True, 'contractVersion': 1, 'model': 'st-options-structure/v1',
            'status': 'ready', 'shadowMode': True, 'decisionUse': 'research_only',
            'observed': {'expiry': '2026-08-19', 'tradeDate': datetime.now(timezone.utc).date().isoformat(),
                         'rowCount': 2, 'callOpenInterest': 10, 'putOpenInterest': 12,
                         'oiPutCallRatio': 1.2, 'profile': []},
            'derived': {'ivOiCoveragePct': 100.0},
            'modeled': {'eligible': False, 'scenarios': []},
            'quality': {'warnings': []},
        }
        original = ox.refresh
        ox.refresh = lambda **_kwargs: fixture
        try:
            req = urllib.request.Request(
                self.base + '/options/txo/refresh', data=b'{"force":true}',
                headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read())
            self.assertEqual(resp.status, 200)
            self.assertEqual(body['optionsStructure']['observed']['expiry'], '2026-08-19')
            with urllib.request.urlopen(self.base + '/decision/context', timeout=5) as resp:
                after = json.loads(resp.read())
            self.assertEqual(after['optionsStructure']['status'], 'ready')
        finally:
            ox.refresh = original

    def test_options_history_is_bounded_read_only_and_validated(self):
        ox._write_history_rows([
            {'tradeDate': '2026-08-14', 'expiry': '2026-08-19', 'ivOiCoveragePct': 100.0},
            {'tradeDate': '2026-08-15', 'expiry': '2026-08-19', 'ivOiCoveragePct': 100.0},
        ])
        with urllib.request.urlopen(
                self.base + '/options/txo/history?expiry=20260819&limit=1', timeout=5) as resp:
            body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertEqual(body['count'], 1)
        self.assertEqual(body['total'], 2)
        self.assertEqual(body['rows'][0]['tradeDate'], '2026-08-15')
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.base + '/options/txo/history?limit=999', timeout=5)
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()

    def test_overnight_get_is_cache_only_and_refresh_is_bounded_shadow(self):
        called = []
        original = oi.get_snapshot
        with urllib.request.urlopen(self.base + '/research/overnight-intraday?market=US', timeout=5) as resp:
            cached = json.loads(resp.read())
        self.assertFalse(cached['ok'])
        self.assertEqual(cached['quality']['warnings'], ['NOT_REFRESHED'])
        fixture = {
            'ok': True, 'contractVersion': 1, 'model': 'st-overnight-intraday/v1',
            'shadowOnly': True, 'decisionUse': 'research_only', 'actionAuthority': 'none',
            'markets': [], 'evidence': [], 'quality': {'status': 'good'},
        }

        def fake_snapshot(market='all', force=False, fetcher=None):
            called.append((market, force))
            return fixture

        oi.get_snapshot = fake_snapshot
        try:
            before = dc.latest_context()
            request = urllib.request.Request(
                self.base + '/research/overnight-intraday/refresh', data=b'{"market":"all","force":true}',
                headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(request, timeout=5) as resp:
                refreshed = json.loads(resp.read())
            self.assertTrue(refreshed['shadowOnly'])
            self.assertEqual(called, [('all', True)])
            after = dc.latest_context()
            for key in ('regime', 'actionEnvelope', 'keyLevels', 'scenario', 'confirmation', 'invalidation'):
                self.assertEqual(before[key], after[key], key)
            bad = urllib.request.Request(
                self.base + '/research/overnight-intraday/refresh', data=b'{"symbols":["ANY"]}',
                headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(bad, timeout=5)
            self.assertEqual(caught.exception.code, 400)
            caught.exception.close()
            wrong_type = urllib.request.Request(
                self.base + '/research/overnight-intraday/refresh', data=b'{"market":"all","force":"false"}',
                headers={'Content-Type': 'application/json'}, method='POST')
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(wrong_type, timeout=5)
            self.assertEqual(caught.exception.code, 400)
            caught.exception.close()
        finally:
            oi.get_snapshot = original

    def test_post_profile_recomputes_without_mutating_deterministic_regime(self):
        profile = {
            'baseGrossExposure': 70, 'maxGrossExposure': 90, 'maxLeverage': 1,
            'maxSingleNameWeight': 20, 'maxSectorWeight': 40,
            'maxPortfolioBeta': 1.1, 'maxDailyVaR': 2, 'investmentHorizon': 'swing',
        }
        data = json.dumps({'riskProfile': profile}).encode()
        req = urllib.request.Request(self.base + '/decision/context', data=data,
                                     headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())
        self.assertEqual(body['regime']['id'], 'BROAD_RISK_ON')
        self.assertIsNotNone(body['actionEnvelope']['positionRange'])

    def test_post_rejects_invalid_json_and_unbounded_holdings(self):
        bad_json = urllib.request.Request(self.base + '/decision/context', data=b'{', method='POST')
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(bad_json, timeout=5)
        self.assertEqual(caught.exception.code, 415)
        caught.exception.close()
        oversized = json.dumps({'holdings': [{'sym': '2330', 'weight': 1}] * 81}).encode()
        req = urllib.request.Request(self.base + '/decision/context', data=oversized,
                                     headers={'Content-Type': 'application/json'}, method='POST')
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()


if __name__ == '__main__':
    unittest.main()
