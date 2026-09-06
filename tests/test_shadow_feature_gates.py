#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shadow feature flags must short-circuit backend computation when OFF."""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / 'server'
sys.path.insert(0, str(SERVER_DIR))

import decision_context as dc  # noqa: E402
from feature_settings import disabled_consensus_attention, disabled_early_warning  # noqa: E402

_SHADOW_ENV_KEYS = (
    'ST_ENABLE_SHADOW_RESEARCH',
    'ST_SHADOW_OVERNIGHT_INTRADAY',
    'ST_SHADOW_EARLY_WARNING',
    'ST_SHADOW_CONSENSUS_ATTENTION',
)


def _pulse() -> dict:
    return {
        'ok': True,
        'updatedAt': '2026-08-11T08:45:00',
        'date': '2026-08-11',
        'marketSnapshot': {
            'quotes': {
                '^TWII': {
                    'price': 23000,
                    'changePct': 1.0,
                    'market': {
                        'displayChangePct': 1.0,
                        'source': 'twse-mis',
                        'session': 'regular',
                        'referenceType': 'previous_close',
                        'asOf': '2026-08-11T08:45:00',
                    },
                },
            },
        },
        'stocks': {'up': 700, 'down': 300, 'advRatio': 0.7, 'limitDown': 1},
        'snapshot': {'stocks': {'up': 700, 'down': 300, 'advRatio': 0.7, 'limitDown': 1}},
        'healthScore': 75,
        'riskScore': 25,
        'dataCompleteness': 90,
        'breadthScope': 'TWSE_STOCKS',
        'breadthSource': 'TWSE MI_INDEX MS',
        'overview': {'strip': {'volumeScore': 70, 't00Trend': {'momScore': 70}}},
        'global': [],
        'sectors': [],
        'flash': [],
    }


def _levels() -> dict:
    return {
        'levels': {'r1': 23100, 'pivot': 22950, 's1': 22800},
        'atr': {'pct': 1.5},
        'quality': {'complete': True, 'stale': False},
    }


def _load_server():
    spec = importlib.util.spec_from_file_location('st_shadow_gate_http', SERVER_DIR / 'server.py')
    if spec is None or spec.loader is None:
        raise RuntimeError('unable to load server')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ShadowFeatureGateTests(unittest.TestCase):
    def setUp(self):
        self._saved = {key: os.environ.get(key) for key in _SHADOW_ENV_KEYS}
        for key in _SHADOW_ENV_KEYS:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_publish_context_skips_shadow_engines_when_off(self):
        pulse = _pulse()
        levels = _levels()
        context = dc.build_decision_context(pulse, key_levels=levels)
        with patch('early_warning.process_context') as proc, \
                patch('overnight_intraday.latest_cached') as latest, \
                patch('consensus_attention.build_consensus_attention') as consensus:
            out = dc.publish_context(context, pulse=pulse, build_kwargs={'key_levels': levels})
        proc.assert_not_called()
        latest.assert_not_called()
        consensus.assert_not_called()
        self.assertFalse(out['earlyWarnings']['enabled'])
        self.assertEqual(out['earlyWarnings']['status'], 'DISABLED')
        self.assertFalse(out['consensusAttention']['enabled'])
        self.assertEqual(out['consensusAttention']['items'], [])

    def test_publish_context_runs_shadow_engines_when_on(self):
        os.environ['ST_ENABLE_SHADOW_RESEARCH'] = '1'
        pulse = _pulse()
        levels = _levels()
        context = dc.build_decision_context(pulse, key_levels=levels)
        fake_warning = disabled_early_warning('TEST')
        fake_warning['enabled'] = True
        fake_warning['status'] = 'OK'
        fake_consensus = disabled_consensus_attention('TEST')
        fake_consensus['enabled'] = True
        with patch('early_warning.process_context', return_value=fake_warning) as proc, \
                patch('overnight_intraday.latest_cached', return_value={'markets': []}) as latest, \
                patch('consensus_attention.build_consensus_attention', return_value=fake_consensus) as consensus:
            out = dc.publish_context(context, pulse=pulse, build_kwargs={'key_levels': levels})
        proc.assert_called_once()
        latest.assert_called_once()
        consensus.assert_called_once()
        self.assertTrue(out['earlyWarnings']['enabled'])
        self.assertTrue(out['consensusAttention']['enabled'])

    def test_build_decision_context_skips_consensus_when_off(self):
        with patch('consensus_attention.build_consensus_attention') as consensus:
            out = dc.build_decision_context(_pulse(), key_levels=_levels())
        consensus.assert_not_called()
        self.assertFalse(out['consensusAttention']['enabled'])

    def test_disabled_http_routes_return_200_not_403(self):
        st_server = _load_server()
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), st_server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{httpd.server_port}'
        try:
            with urllib.request.urlopen(base + '/research/overnight-intraday', timeout=3) as resp:
                body = json.load(resp)
            self.assertEqual(resp.status, 200)
            self.assertFalse(body['enabled'])
            self.assertFalse(body['ok'])

            req = urllib.request.Request(
                base + '/research/overnight-intraday/refresh',
                data=b'{"market":"all","force":false}',
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            with urllib.request.urlopen(req, timeout=3) as resp:
                refreshed = json.load(resp)
            self.assertEqual(resp.status, 200)
            self.assertFalse(refreshed['enabled'])
            self.assertIn('SHADOW_DISABLED', refreshed.get('reason', ''))

            with urllib.request.urlopen(base + '/signals/active', timeout=3) as resp:
                active = json.load(resp)
            self.assertEqual(resp.status, 200)
            self.assertFalse(active['enabled'])
            self.assertEqual(active['signals'], [])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)

    def test_refresh_does_not_call_snapshot_when_flag_off(self):
        st_server = _load_server()
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), st_server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{httpd.server_port}'
        try:
            import overnight_intraday as oi

            called = []
            original = oi.get_snapshot
            oi.get_snapshot = lambda **kwargs: called.append(kwargs) or original(**kwargs)
            try:
                req = urllib.request.Request(
                    base + '/research/overnight-intraday/refresh',
                    data=b'{"market":"all","force":true}',
                    headers={'Content-Type': 'application/json'},
                    method='POST',
                )
                with urllib.request.urlopen(req, timeout=3) as resp:
                    body = json.load(resp)
                self.assertEqual(resp.status, 200)
                self.assertFalse(body['enabled'])
                self.assertEqual(called, [])
            finally:
                oi.get_snapshot = original
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()
