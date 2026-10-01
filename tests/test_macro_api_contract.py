"""Exercise the real macro API functions without starting the HTTP server."""
import ast
import json
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import macro_track as mt


def api_namespace():
    tree = ast.parse((ROOT / 'server/server.py').read_text(encoding='utf-8'))
    names = {'MACRO_SERIES', 'MACRO_ECONOMY_KEYS', '_macro_resolve_points',
             '_macro_payload', '_macro_economy_snapshot', '_macro_latest', '_macro_today',
             '_macro_cache', '_macro_cache_invalidate'}
    nodes = [node for node in tree.body if
             isinstance(node, ast.FunctionDef) and node.name in names or
             isinstance(node, ast.Assign) and any(
                 isinstance(target, ast.Name) and target.id in names for target in node.targets)]
    namespace = {}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'server/server.py', 'exec'), namespace)
    return namespace


class TestMacroApiContract(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.seed_patch = mock.patch.object(mt, 'SEED_DIR', self.temp.name)
        self.seed_patch.start()
        self.api = api_namespace()

    def tearDown(self):
        self.seed_patch.stop()
        self.temp.cleanup()

    def test_every_api_seed_has_a_canonical_provider(self):
        for key, spec in self.api['MACRO_SERIES'].items():
            if spec.get('seed'):
                with self.subTest(key=key):
                    self.assertIn(spec.get('canonical'),
                                  {'fred', 'nyfed_effr', 'bls_cpi_yoy', 'bls_unrate', 'yahoo', 'yahoo_adj'})

    def test_shared_chart_seeds_have_identical_provider_and_symbol(self):
        api_specs = {s['seed']: s for s in self.api['MACRO_SERIES'].values() if s.get('seed')}
        for chart in mt.CHARTS.values():
            for spec in chart['series']:
                if spec.get('seed') in api_specs:
                    api_spec = api_specs[spec['seed']]
                    self.assertEqual(mt._seed_identity(spec), mt._seed_identity({
                        **api_spec, 'fred': api_spec.get('id')}))

    def test_api_never_retries_unadjusted_yahoo_after_canonical_failure(self):
        with mock.patch.object(mt, '_yahoo_closes', return_value=[]) as yahoo, \
                mock.patch.object(mt, '_fred_points') as fred:
            points, source = self.api['_macro_resolve_points']('baml_hy', force_live=True)
        self.assertEqual(points, [])
        self.assertIn('canonical:yahoo_adj', source)
        yahoo.assert_called_once_with('HYG', years=10, adj=True)
        fred.assert_not_called()

    def test_recent_unverified_seed_is_not_publishable(self):
        points = [{'date': '2026-08-28', 'value': 80}]
        mt._save_seed_csv('baml_hy.csv', points)
        with mock.patch.object(mt, '_taipei_today', return_value=date(2026, 8, 28)), \
                mock.patch.object(mt, '_nyfed_effr', return_value=[]), \
                mock.patch.object(mt, '_yahoo_closes', return_value=[]):
            payload = self.api['_macro_payload']('baml_hy')
            self.assertEqual(payload['freshness'], 'unknown')
            self.assertIn('unverified', payload['source'])
            chart = mt.get_chart('__US_RATES_CREDIT__')
        self.assertFalse(chart['publishable'])

    def test_stale_verified_api_seed_keeps_date_and_reports_stale(self):
        spec = self.api['MACRO_SERIES']['baml_hy']
        mt._save_seed_csv(spec['seed'], [{'date': '2026-08-28', 'value': 80}])
        mt._save_seed_source(spec)
        with mock.patch.object(mt, '_taipei_today', return_value=date(2026, 9, 2)):
            payload = self.api['_macro_payload']('baml_hy')
        self.assertEqual(payload['lastDate'], '2026-08-28')
        self.assertEqual(payload['freshness'], 'stale')

    def test_provider_change_invalidates_existing_provenance(self):
        spec = {'seed': 'bond.csv', 'canonical': 'yahoo_adj', 'symbol': 'HYG'}
        mt._save_seed_csv(spec['seed'], [{'date': '2026-08-28', 'value': 80}])
        mt._save_seed_source(spec)
        self.assertFalse(mt._seed_verified({**spec, 'symbol': 'LQD'}))
        self.assertFalse(mt._seed_verified({**spec, 'canonical': 'yahoo'}))

    def test_handler_cache_recalculates_freshness_at_taipei_midnight(self):
        tree = ast.parse((ROOT / 'server/server.py').read_text(encoding='utf-8'))
        handler = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == '_handle_macro')
        ns = {**self.api, 'json': json, 'parse_qs': parse_qs, 'urlparse': urlparse, '_macro_cache': {}}
        ns['_macro_resolve_points'] = lambda *a, **k: ([{'date': '2026-08-28', 'value': 80}], 'Yahoo HYG adj')
        # Functions must share the same globals as the real handler.
        ns['_macro_payload'] = type(self.api['_macro_payload'])(self.api['_macro_payload'].__code__, ns)
        exec(compile(ast.Module(body=[handler], type_ignores=[]), 'server/server.py', 'exec'), ns)
        responses = []
        request = SimpleNamespace(path='/macro/baml_hy?years=10', _ok=lambda body: responses.append(json.loads(body)))
        with mock.patch.object(mt, '_taipei_today', return_value=date(2026, 9, 1)):
            ns['_handle_macro'](request, 'baml_hy')
        with mock.patch.object(mt, '_taipei_today', return_value=date(2026, 9, 2)):
            ns['_handle_macro'](request, 'baml_hy')
        self.assertEqual([r['freshness'] for r in responses], ['fresh', 'stale'])
        self.assertEqual(set(ns['_macro_cache']), {'baml_hy:10:20260901', 'baml_hy:10:20260902'})

    def test_snapshot_reports_failed_refresh_even_with_recent_points(self):
        import time
        ns = {**self.api, 'time': time, 'MACRO_ECONOMY_KEYS': ['baml_hy']}
        ns['_macro_resolve_points'] = lambda *a, **k: (
            [{'date': '2026-09-30', 'value': 80}], 'refresh-save-failed:OSError')
        for name in ('_macro_payload', '_macro_economy_snapshot'):
            fn = self.api[name]
            ns[name] = type(fn)(fn.__code__, ns, argdefs=fn.__defaults__)
        with mock.patch.object(mt, '_taipei_today', return_value=date(2026, 10, 1)):
            result = ns['_macro_economy_snapshot'](force_live=True)
        self.assertFalse(result['ok'])
        self.assertEqual(result['counts']['ok'], 0)
        self.assertFalse(result['items'][0]['ok'])
        self.assertIn('OSError', result['items'][0]['refreshError'])
        self.assertEqual(len(result['refreshErrors']), 1)

    def test_latest_reader_uses_the_same_taipei_date_key(self):
        points = [{'date': '2026-08-28', 'value': 80}]
        ns = {**self.api, 'json': json, '_macro_cache': {
            'baml_hy:10:20260902': json.dumps({'points': points}).encode()}}
        latest = type(self.api['_macro_latest'])(self.api['_macro_latest'].__code__, ns,
                                                argdefs=self.api['_macro_latest'].__defaults__)
        with mock.patch.object(mt, '_taipei_today', return_value=date(2026, 9, 2)):
            self.assertEqual(latest('baml_hy', allow_fetch=False)['value'], 80)


if __name__ == '__main__':
    unittest.main()
