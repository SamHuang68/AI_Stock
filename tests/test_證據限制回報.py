"""三項限制的判定、前瞻成熟、失敗留存、去重與排程回報契約。"""
import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, nullcontext
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import stock_signals as ss
import 個股研究維護 as maintenance
import 每日個股留存 as daily
import 證據限制回報 as reports
import stock_signals_routes as routes

NOW = datetime(2026, 9, 29, 6, tzinfo=ss._TZ['TW'])


def cached():
    return {'window': {'to': '2026-09-24'}, 'generatedAt': NOW.isoformat(), 'statisticsVersion': 3,
            'research': {'policy': copy.deepcopy(reports.POLICY), 'selection': {'status': 'no_candidate'},
                         'rsiRebound': {'policy': copy.deepcopy(reports.RSI_POLICY), 'selection': {'status': 'no_candidate'}}},
            'priceSensitivity': {'coveredSymbols': 1054, 'totalSymbols': 1083,
                                 'partial': {'coveredSymbols': 26, 'coveredBars': 28056}, 'missingSymbols': ['2330']}}


def build(**kwargs):
    return reports.build_report(kwargs.pop('cached', cached()), {'benchmarkAsOf': '2026-09-24', 'missingPrices': [],
             'missingSessions': []}, kwargs.pop('observations', {'enabled': True, 'events': 0, 'orphans': 0, 'horizons': []}),
             kwargs.pop('sources', {}), {}, now=kwargs.pop('now', NOW), **kwargs)


class ReportTests(unittest.TestCase):
    def test_completed_checks_do_not_promote_no_candidate_or_historical_pass(self):
        for state in ('no_candidate', 'forward_only', 'temporal_check_failed'):
            value = cached()
            value['research']['selection']['status'] = state
            result = build(cached=value)
            self.assertEqual(result['execution'], 'completed')
            self.assertEqual(result['constraints'][0]['state'], 'unproven')
            self.assertFalse(result['candidatePromotion'])
            self.assertEqual(result['metrics']['mainSelection'], state)

    def test_changed_policy_is_failure_and_newer_sources_need_recalculation(self):
        value = cached()
        value['research']['policy']['minEvents'] = 1
        result = build(cached=value, sources={'updatedAt': (NOW + timedelta(minutes=5)).isoformat()})
        self.assertEqual(result['execution'], 'failed')
        checks = {r['id']: r['state'] for r in result['checks']}
        self.assertEqual(checks['policy'], 'failed')
        self.assertEqual(checks['research_source_time'], 'waiting')

    def test_missing_history_is_waiting_not_zero_evidence_pass(self):
        result = build(cached={}, observations={'enabled': False})
        checks = {r['id']: r['state'] for r in result['checks']}
        for key in ('policy', 'selection', 'research_freshness', 'ledger', 'observation_run', 'daily_sources', 'research_source_time'):
            self.assertEqual(checks[key], 'waiting')
        self.assertFalse(result['candidatePromotion'])
        value = cached()
        value['research']['selection']['status'] = 'candidate'
        self.assertEqual(build(cached=value)['execution'], 'failed')

    def test_forward_maturity_counts_real_sessions_and_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '前瞻.sqlite3'
            daily.enable(path, NOW)
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute('INSERT INTO daily_events VALUES(?,?,?,?,?,?,?)', ('one', 'input', '2330', '2026-09-01',
                             'mom_rsi_rebound', NOW.isoformat(), '{}'))
            five = ['2026-09-02', '2026-09-03', '2026-09-04', '2026-09-07', '2026-09-08']
            original = path.read_bytes()
            first = reports.forward_status(path, five)
            self.assertEqual({k: first['horizons'][0][k] for k in ('horizon', 'mature', 'pending', 'due', 'waiting')},
                             {'horizon': 5, 'mature': 0, 'pending': 1, 'due': 0, 'waiting': 1})
            self.assertEqual(first['horizons'][0]['reasons'], {'invalid_version': 1})
            second = reports.forward_status(path, five + ['2026-09-09'])
            self.assertEqual(second['horizons'][0]['due'], 1)
            self.assertEqual(second['horizons'][1]['waiting'], 1)
            self.assertEqual(path.read_bytes(), original)
            with closing(sqlite3.connect(path)) as conn, conn:
                conn.execute('INSERT INTO daily_outcomes VALUES(?,?,?,?)', ('one', 5, NOW.isoformat(), '{}'))
                conn.execute('INSERT INTO daily_outcomes VALUES(?,?,?,?)', ('unknown', 20, NOW.isoformat(), '{}'))
            final = reports.forward_status(path, five + ['2026-09-09'])
            self.assertEqual(final['horizons'][0]['mature'], 0)  # 空白結果與不存在的輸入不能算成熟。
            self.assertEqual(final['horizons'][0]['pending'], 1)
            self.assertEqual(final['horizons'][0]['unverified'], 1)
            self.assertEqual(final['orphans'], 1)
            self.assertEqual(build(observations=final)['execution'], 'failed')

    def test_same_result_dedupes_but_return_to_earlier_state_is_new_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '報告.sqlite3'
            first = build()
            a = reports.save_report(path, first)
            self.assertEqual(reports.save_report(path, {**first, 'checkedAt': (NOW + timedelta(minutes=1)).isoformat()}), a)
            second = copy.deepcopy(first)
            second['metrics']['events'] = 3
            b = reports.save_report(path, second)
            c = reports.save_report(path, first)
            self.assertLess(a, b)
            self.assertLess(b, c)
            data = reports.read_reports(path)
            self.assertEqual(data['total'], 3)
            self.assertEqual(data['latest']['metrics']['events'], 0)
            self.assertEqual(next(r for r in data['latest']['changes'] if r['label'] == '前瞻事件數')['before'], 3)

    def test_pagination_keeps_all_history_and_failed_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '報告.sqlite3'
            for i in range(25):
                result = build(now=NOW + timedelta(days=i), errors=['本機測試失敗'] if i == 23 else None)
                reports.save_report(path, result)
            original = path.read_bytes()
            first = reports.read_reports(path)
            second = reports.read_reports(path, first['nextBefore'])
            self.assertEqual(len(first['history']), 20)
            self.assertEqual(len(second['history']), 5)
            self.assertEqual(len({r['id'] for r in first['history'] + second['history']}), 25)
            self.assertIsNone(second['nextBefore'])
            self.assertEqual(first['latest']['execution'], 'completed')
            old_failure = first['history'][1]
            self.assertEqual(old_failure['execution'], 'failed')
            self.assertIn('本機測試失敗', str(old_failure['checks']))
            self.assertIn('coverage', old_failure)
            self.assertEqual(path.read_bytes(), original)

    def test_refresh_failure_is_saved_and_report_job_fails(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(maintenance.datastore, 'DB_PATH', str(Path(tmp) / 'market.db')), \
                patch.object(maintenance.pool, 'refresh', side_effect=RuntimeError('失敗')), \
                patch.object(maintenance.pool, 'load_cached', return_value=cached()), \
                patch.object(maintenance.datastore, 'read_snapshot', return_value=nullcontext(None)), \
                patch.object(reports, 'collect_inventory', return_value=({'benchmarkAsOf': '2026-09-24'}, [])), \
                patch.object(maintenance.datastore, 'source_revision_status', return_value={}):
            with self.assertRaises(RuntimeError):
                maintenance.check_evidence(recalculate=True, now=NOW)
            result = reports.read_reports(maintenance.report_path())['latest']
            self.assertEqual(result['execution'], 'failed')
            self.assertTrue(any(r['id'] == 'execution_error' for r in result['checks']))

    def test_source_failure_is_saved_even_when_old_receipts_are_successful(self):
        import 個股每日資料 as sources
        with tempfile.TemporaryDirectory() as tmp, patch.object(maintenance.datastore, 'DB_PATH', str(Path(tmp) / 'market.db')), \
                patch.object(maintenance, 'schedule_status', return_value={'enabled': True, 'lastSources': {'status': 'completed'}}), \
                patch.object(sources, 'run', side_effect=ValueError('來源失敗')), \
                patch.object(maintenance.pool, 'refresh'), \
                patch.object(maintenance.pool, 'load_cached', return_value=cached()), \
                patch.object(maintenance.datastore, 'read_snapshot', return_value=nullcontext(None)), \
                patch.object(reports, 'collect_inventory', return_value=({'benchmarkAsOf': '2026-09-24'}, [])), \
                patch.object(maintenance.datastore, 'source_revision_status', return_value={}):
            with self.assertRaises(ValueError):
                maintenance.scheduled_update('2026-09-29')
            result = reports.read_reports(maintenance.report_path())['latest']
            self.assertEqual(result['execution'], 'failed')
            self.assertIn('每日來源更新或留存失敗：ValueError', str(result['checks']))

    def test_nightly_report_runs_on_closed_days_and_restarts_do_not_duplicate(self):
        when = NOW.replace(day=26, hour=20, minute=40)
        with tempfile.TemporaryDirectory() as tmp, patch.object(maintenance, 'report_path', return_value=Path(tmp) / '報告.sqlite3'), \
                patch.object(maintenance.job_queue, 'submit', return_value={'queued': True}) as submit:
            self.assertFalse(maintenance.report_tick(when.replace(minute=39)))
            self.assertTrue(maintenance.report_tick(when))
            submit.assert_called_once()
            reports.save_report(maintenance.report_path(), build(now=when), nightly_day=when.date().isoformat())
            self.assertFalse(maintenance.report_tick(when + timedelta(minutes=10)))

    def test_changed_observation_gaps_are_preserved_even_when_counts_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / '報告.sqlite3'
            first = build(observations={'enabled': True, 'lastRun': {'missingChipInputs': ['2330']}})
            second = build(observations={'enabled': True, 'lastRun': {'missingChipInputs': ['2317']}})
            self.assertNotEqual(reports.save_report(path, first), reports.save_report(path, second))
            self.assertEqual(reports.read_reports(path)['latest']['observations']['lastRun']['missingChipInputs'], ['2317'])

    def test_queued_nightly_crossing_midnight_does_not_skip_next_evening(self):
        when = NOW.replace(hour=23, minute=50)
        with tempfile.TemporaryDirectory() as tmp, patch.object(maintenance, 'report_path', return_value=Path(tmp) / '報告.sqlite3'), \
                patch.object(maintenance.job_queue, 'submit', return_value={'queued': True}) as submit:
            self.assertTrue(maintenance.report_tick(when))
            callback = submit.call_args.args[1]
            with patch.object(maintenance, 'check_evidence') as check:
                callback()
                check.assert_called_once_with(nightly_day='2026-09-29')
            delayed = build(now=when + timedelta(minutes=15))
            reports.save_report(maintenance.report_path(), delayed, nightly_day='2026-09-29')
            self.assertEqual(reports.read_reports(maintenance.report_path())['latest']['sessionDate'], '2026-09-30')
            self.assertTrue(maintenance.report_tick((when + timedelta(days=1)).replace(hour=20, minute=40)))

    def test_check_route_is_explicit_and_cannot_enable_sources(self):
        from types import SimpleNamespace
        handler = SimpleNamespace(_err=lambda msg, code: setattr(handler, 'code', code),
                                  _ok=lambda body: setattr(handler, 'body', body))
        for body in ({'checkEvidence': False}, {'checkEvidence': True, 'downloadSources': True}):
            with patch.object(routes, 'read_json_body', return_value=body), patch.object(maintenance, 'submit_evidence') as submit:
                routes.StockSignalsRoutesMixin._handle_stock_research_refresh(handler)
                self.assertEqual(handler.code, 400)
                submit.assert_not_called()
        with patch.object(routes, 'read_json_body', return_value={'checkEvidence': True}), \
                patch.object(maintenance, 'submit_evidence', return_value={'queued': True}):
            routes.StockSignalsRoutesMixin._handle_stock_research_refresh(handler)
            self.assertEqual(json.loads(handler.body), {'queued': True})


if __name__ == '__main__':
    unittest.main()
