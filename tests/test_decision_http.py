# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import copy
import importlib.util
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

import decision_context as dc  # noqa: E402
import early_warning as ew  # noqa: E402
import options_exposure as ox  # noqa: E402
import overnight_intraday as oi  # noqa: E402
import job_queue as jq  # noqa: E402
import 更新路由 as updates  # noqa: E402
from pulse_updates import PulseUpdates  # noqa: E402

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
    observed = datetime.now(dc.TW_TZ)
    if observed.weekday() >= 5 or not 540 <= observed.hour * 60 + observed.minute < 815:
        if observed.hour * 60 + observed.minute < 815:
            observed -= timedelta(days=1)
        while observed.weekday() >= 5:
            observed -= timedelta(days=1)
        observed = observed.replace(hour=13, minute=33, second=0, microsecond=0)
    source_as_of = observed.isoformat()
    twii = {'price': 23000, 'changePct': 1.0,
            'market': {'displayChangePct': 1.0, 'source': 'twse-mis', 'session': 'regular',
                       'referenceType': 'previous_close', 'asOf': source_as_of}}
    txf = {'price': 23020, 'changePct': 0.8,
           'market': {'displayChangePct': 0.8, 'source': 'taifex-mis', 'session': 'night',
                      'referenceType': 'previous_close', 'asOf': source_as_of}}
    return {
        'ok': True, 'updatedAt': as_of, 'date': observed.date().isoformat(),
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
        (ROOT / 'scratch').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='決策HTTP-', dir=ROOT / 'scratch')
        self.signal_db_path = str(Path(self.tmp.name) / 'market_signals.db')
        # 訊號讀取函式的預設路徑在定義時已綁定；只改 DB_PATH 不會隔離 HTTP 查詢。
        # 保留真實查詢與序列化流程，讓讀取端與下方發布端共用本次測試資料庫。
        for name in ('active', 'history', 'performance'):
            replacement = patch.object(ew, name, partial(getattr(ew, name), path=self.signal_db_path))
            replacement.start()
            self.addCleanup(replacement.stop)
        for replacement in (patch.object(dc, '_latest_context', None), patch.object(dc, '_latest_inputs', None)):
            replacement.start()
            self.addCleanup(replacement.stop)
        publish = dc.publish_context
        def isolated_publish(context, **kwargs):
            kwargs.update(db_path=str(Path(self.tmp.name) / 'decision.db'),
                          trace_path=str(Path(self.tmp.name) / 'decision.jsonl'))
            return publish(context, **kwargs)
        publication = patch.object(dc, 'publish_context', side_effect=isolated_publish)
        publication.start()
        self.addCleanup(publication.stop)
        self.old_options_history = ox.HISTORY_PATH
        ox.HISTORY_PATH = str(Path(self.tmp.name) / 'options-history.json')
        with oi._CACHE_LOCK:
            oi._CACHE.clear()
        levels = {'levels': {'r1': 23100, 'pivot': 22950, 's1': 22800},
                  'atr': {'pct': 1.5}, 'quality': {'complete': True, 'stale': False}}
        self.levels = levels
        p = _pulse()
        ctx = dc.build_decision_context(p, key_levels=levels)
        dc.publish_context(ctx, pulse=p, build_kwargs={'key_levels': levels},
                           db_path=str(Path(self.tmp.name) / 'decision.db'),
                           trace_path=str(Path(self.tmp.name) / 'decision.jsonl'))
        self.pulse_updates = PulseUpdates(Path(self.tmp.name) / 'updates.db',
                                          Path(self.tmp.name) / 'updates.jsonl', interval_seconds=3600)
        self.queue = jq.DurableJobQueue(self.pulse_updates.db_path, retain=10, capacity=2)
        self.coordinator = updates.UpdateCoordinator(self.pulse_updates, self.queue)
        for replacement in (patch.object(updates, '_service', self.coordinator),
                            patch.object(st_server, '_pulse_updates', self.pulse_updates)):
            replacement.start()
            self.addCleanup(replacement.stop)
        self.httpd = ThreadingHTTPServer(('127.0.0.1', 0), st_server.Handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.httpd.server_port}'

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
        self.assertTrue(self.queue.stop())
        self.assertTrue(self.pulse_updates.stop())
        ox.HISTORY_PATH = self.old_options_history
        self.tmp.cleanup()

    def wait_for(self, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = predicate()
            if result:
                return result
            time.sleep(0.01)
        self.fail('隔離更新工作未於時限內完成')

    @staticmethod
    def committed_context():
        # latest_context 會依讀取當下重算 freshness 秒數；原提交內容才是不可變檢查標的。
        return copy.deepcopy(dc._latest_context)

    def publish_queued_market(self, market_job_id, **build_kwargs):
        calls = []
        def builder(job_id, guard):
            calls.append((job_id, threading.current_thread().name))
            pulse = _pulse()
            pulse['updateJobId'] = job_id
            dc.build_and_publish(pulse, key_levels=self.levels, publication_guard=guard, **build_kwargs)
            return dc.latest_pulse()
        self.assertTrue(self.pulse_updates.start(builder, dc.latest_pulse))
        job_id = market_job_id.removeprefix('p-')
        self.wait_for(lambda: self.pulse_updates.status(job_id)['job']['status'] not in ('queued', 'running'))
        job = self.pulse_updates.status(job_id)['job']
        self.assertEqual(job['status'], 'succeeded', job)
        self.assertEqual(calls, [(job_id, 'st-pulse-updates')])
        self.assertEqual(dc.latest_pulse()['updateJobId'], job_id)
        self.assertEqual(job['result']['snapshotId'], dc.latest_context()['snapshotId'])
        self.assertEqual(dc.latest_context()['persistence'], 'committed')
        return dc.latest_context()

    def test_get_context_returns_canonical_contract(self):
        with urllib.request.urlopen(self.base + '/decision/context', timeout=5) as resp:
            body = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertEqual(body['contractVersion'], 2)
        self.assertEqual(body['regime']['id'], 'BROAD_RISK_ON')
        self.assertTrue(body['evidence'])
        self.assertTrue(body['earlyWarnings']['shadowOnly'])
        self.assertIn('temporalContext', body['earlyWarnings'])
        self.assertEqual(body['earlyWarnings']['thresholds']['watchStrength'], 55)
        self.assertEqual(body['consensusAttention']['authority'], 'attention_only')
        self.assertLessEqual(len(body['consensusAttention']['items']), 5)
        self.assertTrue(any(row.get('id') == 'signal.prospective_validation'
                            for row in body['evidence']))
        family_evidence = next(
            row for row in body['evidence']
            if str(row.get('id') or '').startswith('signal.family.')
        )
        self.assertIn('temporal', family_evidence['value'])
        compact = dc.compact_context(body)
        self.assertIn('temporalContext', compact['earlyWarnings'])
        self.assertFalse(compact['earlyWarnings']['strengthIsProbability'])

    def test_signal_routes_expose_shadow_state_and_transition_history(self):
        with urllib.request.urlopen(self.base + '/signals/active', timeout=5) as resp:
            active = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertTrue(active['shadowOnly'])
        self.assertTrue(active['signals'])
        expected = (dc.latest_context() or {}).get('earlyWarnings', {}).get('signals', [])
        self.assertTrue(expected)
        self.assertEqual(
            {(row['signalId'], row['observationKey'], row['lastSeenAt']) for row in active['signals']},
            {(row['signalId'], row['observationKey'], row['lastSeenAt']) for row in expected},
        )
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

    def test_options_refresh_queues_then_publishes_through_shared_pulse_writer(self):
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
        with patch.object(ox, 'refresh', return_value=fixture) as source:
            before = self.committed_context()
            req = urllib.request.Request(
                self.base + '/options/txo/refresh', data=b'{"force":true}',
                headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(req, timeout=5) as resp:
                body = json.loads(resp.read())
            self.assertEqual(resp.status, 202)
            self.assertEqual(body['job']['status'], 'queued')
            self.assertEqual(body['job']['type'], 'options')
            source.assert_not_called()
            self.assertEqual(self.committed_context(), before, 'HTTP 排隊不可同步改寫正式決策')
            self.queue.start()
            job_id = body['job']['jobId'].removeprefix('r-')
            self.wait_for(lambda: self.queue.get(job_id)['status'] not in ('queued', 'running'))
            job = self.queue.get(job_id)
            self.assertEqual(job['status'], 'succeeded', job)
            source.assert_called_once()
            self.assertTrue(callable(source.call_args.kwargs['commit_guard']))
            self.assertTrue(source.call_args.kwargs['force'])
            self.assertEqual(self.committed_context(), before, '來源工作只能提交 Pulse 工作，不可自己發布')
            after = self.publish_queued_market(job['result']['marketJobId'], options_structure=fixture)
            self.assertEqual(after['optionsStructure']['status'], 'ready')
            self.assertEqual(after['optionsStructure']['observed']['expiry'], '2026-08-19')
            self.assertGreater(after['revision'], before['revision'])

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

        def fake_snapshot(market='all', force=False, fetcher=None, commit_guard=None):
            self.assertTrue(callable(commit_guard))
            commit_guard()
            called.append((market, force))
            return fixture

        oi.get_snapshot = fake_snapshot
        try:
            before = self.committed_context()
            request = urllib.request.Request(
                self.base + '/research/overnight-intraday/refresh', data=b'{"market":"all","force":true}',
                headers={'Content-Type': 'application/json'}, method='POST')
            with urllib.request.urlopen(request, timeout=5) as resp:
                refreshed = json.loads(resp.read())
            self.assertEqual(resp.status, 202)
            self.assertEqual(refreshed['job']['status'], 'queued')
            self.assertEqual(refreshed['job']['type'], 'research')
            self.assertEqual(called, [], 'HTTP 排隊時不可同步執行研究來源')
            self.assertEqual(self.committed_context(), before)
            self.queue.start()
            job_id = refreshed['job']['jobId'].removeprefix('r-')
            self.wait_for(lambda: self.queue.get(job_id)['status'] not in ('queued', 'running'))
            job = self.queue.get(job_id)
            self.assertEqual(job['status'], 'succeeded', job)
            self.assertEqual(called, [('all', True)])
            self.assertEqual(self.committed_context(), before, '來源完成後仍須等待原 Pulse writer 發布')
            with patch.object(oi, 'latest_cached', return_value=fixture) as cached_source:
                after = self.publish_queued_market(job['result']['marketJobId'])
                cached_source.assert_called_with('all')
            self.assertGreater(after['revision'], before['revision'])
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

    def test_post_profile_without_holdings_has_no_position_range_or_canonical_write(self):
        profile = {
            'baseGrossExposure': 70, 'maxGrossExposure': 90, 'maxLeverage': 1,
            'maxSingleNameWeight': 20, 'maxSectorWeight': 40,
            'maxPortfolioBeta': 1.1, 'maxDailyVaR': 2, 'investmentHorizon': 'swing',
        }
        before = self.committed_context()
        before_pulse = copy.deepcopy(dc._latest_inputs['pulse'])
        data = json.dumps({'riskProfile': profile, 'holdings': [], 'portfolioKind': 'actual',
                           'portfolioInputStatus': 'empty'}).encode()
        req = urllib.request.Request(self.base + '/decision/context', data=data,
                                     headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req, timeout=5) as resp:
            body = json.loads(resp.read())
        self.assertEqual(body['regime']['id'], 'BROAD_RISK_ON')
        self.assertIsNone(body['actionEnvelope']['positionRange'])
        self.assertIn('portfolio_input_empty', body['actionEnvelope']['constraints'])
        self.assertEqual(self.committed_context(), before)
        self.assertEqual(dc._latest_inputs['pulse'], before_pulse)

    def test_updates_keep_old_active_jobs_and_export_all_history_beyond_retention(self):
        # 高優先工作連續完成，較早等待的工作仍須可見；歷史不可隨即時清單裁切。
        fixed_time = time.time()
        self.queue.clock = lambda: fixed_time
        self.queue.register('驗收低優先', lambda *_: {}, priority=80)
        self.queue.register('驗收高優先', lambda *_: {}, priority=10)
        old = self.queue.submit_registered('驗收低優先')['job']
        completed = []
        for index in range(self.queue.retain + self.queue.capacity + 8):
            job = self.queue.submit_registered('驗收高優先', {'index': index})['job']
            claimed = self.queue._claim()
            self.assertEqual(claimed['jobId'], job['jobId'])
            self.queue._finish(claimed, 'succeeded', {'index': index}, None)
            completed.append(job['jobId'])
        with urllib.request.urlopen(self.base + '/updates', timeout=5) as resp:
            status = json.loads(resp.read())
        visible = {job['jobId']: job for job in status['jobs']}
        self.assertEqual(visible['r-' + old['jobId']]['status'], 'queued')
        self.assertEqual(len(status['jobs']), self.queue.retain + 1)
        self.assertEqual(status['researchTotalJobs'], len(completed) + 1)
        with patch.object(jq, '_durable_default', self.queue):
            self.assertTrue(jq.is_busy())
        with urllib.request.urlopen(self.base + '/updates/archive', timeout=5) as resp:
            archive = json.loads(resp.read())
        self.assertEqual(resp.status, 200)
        self.assertEqual({job['jobId'] for job in archive['research']},
                         {'r-' + value for value in [old['jobId'], *completed]})
        self.assertEqual(len(archive['research']), len(completed) + 1)
        self.assertEqual(self.queue.get(old['jobId'])['status'], 'queued')

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
