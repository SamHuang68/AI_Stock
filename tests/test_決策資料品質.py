"""來源時效、投組涵蓋率、發布順序與決策修訂的回歸測試。"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
import threading
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'server'), str(ROOT / 'tests')]
import decision_context as dc
import portfolio
from test_decision_context import FIXED_NOW, KEYS, pulse


PROFILE = {'baseGrossExposure': 70, 'maxGrossExposure': 90, 'maxLeverage': 1,
           'maxSingleNameWeight': 100, 'maxSectorWeight': 100, 'maxPortfolioBeta': 10,
           'maxDailyVaR': 0.1, 'investmentHorizon': 'swing'}


def observed_pulse(observed: str, generated: str | None = None) -> dict:
    out = pulse(updated=observed)
    out['date'] = observed[:10]
    out['updatedAt'] = generated or observed
    return out


class SourceQualityTest(unittest.TestCase):
    def test_old_sources_cannot_be_refreshed_by_generation_time(self):
        p = observed_pulse('2026-08-04T13:33:00+08:00', '2026-08-12T09:00:00+08:00')
        for quote in p['marketSnapshot']['quotes'].values():
            quote['market']['stale'] = True
        out = dc.build_decision_context(p, now=datetime.fromisoformat(p['updatedAt']), risk_profile=PROFILE)
        self.assertEqual(out['regime']['id'], 'INSUFFICIENT_DATA')
        self.assertLess(out['dataQuality']['freshness'], 0.25)
        self.assertIn('twii', out['dataQuality']['staleFields'])
        self.assertIn('breadth', out['dataQuality']['staleFields'])
        self.assertIsNone(out['actionEnvelope']['positionRange'])

    def test_unknown_and_future_quote_timestamps_fail_closed(self):
        for observed in (None, '2026-08-11T12:00:00+08:00'):
            with self.subTest(observed=observed):
                p = pulse()
                quote = p['marketSnapshot']['quotes']['^TWII']
                quote['asOf'] = quote['market']['asOf'] = observed
                out = dc.build_decision_context(p, now=FIXED_NOW)
                self.assertEqual(out['regime']['id'], 'INSUFFICIENT_DATA')

    def test_weekend_and_preopen_keep_last_completed_session(self):
        p = observed_pulse('2026-09-18T13:33:00+08:00')
        p['marketSnapshot']['quotes']['^TWII']['market']['stale'] = True
        for now in ('2026-09-19T18:00:00+08:00', '2026-09-21T08:00:00+08:00'):
            with self.subTest(now=now):
                out = dc.build_decision_context(p, now=datetime.fromisoformat(now))
                self.assertEqual(out['regime']['id'], 'BROAD_RISK_ON')
                self.assertEqual(out['dataQuality']['sourceQuality']['twii']['status'], 'completed_session')
                self.assertEqual(out['dataQuality']['freshness'], 1.0)

    def test_weekend_does_not_accept_an_unfinished_friday_quote(self):
        p = observed_pulse('2026-09-18T10:00:00+08:00')
        out = dc.build_decision_context(p, now=datetime.fromisoformat('2026-09-19T18:00:00+08:00'))
        self.assertEqual(out['regime']['id'], 'INSUFFICIENT_DATA')

    def test_market_open_invalidates_previous_session_quote(self):
        p = observed_pulse('2026-09-18T13:33:00+08:00', '2026-09-21T10:00:00+08:00')
        out = dc.build_decision_context(p, now=datetime.fromisoformat(p['updatedAt']))
        self.assertEqual(out['regime']['id'], 'INSUFFICIENT_DATA')

    def test_stored_exchange_calendar_preserves_a_closed_monday(self):
        p = observed_pulse('2026-09-18T13:33:00+08:00')
        calendar = {'coveredYears': [2026], 'sessions': ['2026-09-18', '2026-09-22']}
        out = dc.build_decision_context(p, now=datetime.fromisoformat('2026-09-21T18:00:00+08:00'), session_calendar=calendar)
        self.assertEqual(out['regime']['id'], 'BROAD_RISK_ON')
        self.assertEqual(out['dataQuality']['calendarSource'], 'stored_exchange_calendar')

    def test_old_breadth_is_not_rescued_by_a_fresh_index(self):
        p = pulse()
        p['date'] = '2026-08-04'
        out = dc.build_decision_context(p, now=FIXED_NOW)
        self.assertEqual(out['regime']['id'], 'INSUFFICIENT_DATA')
        self.assertIn('breadth', out['dataQuality']['staleFields'])

    def test_previous_completed_breadth_remains_eligible_during_session(self):
        p = pulse()
        p['date'] = '2026-08-10'
        out = dc.build_decision_context(p, now=FIXED_NOW)
        self.assertEqual(out['regime']['id'], 'BROAD_RISK_ON')

    def test_cached_context_expires_without_publishing_or_losing_evidence(self):
        p = observed_pulse('2026-09-18T13:33:00+08:00')
        context = dc.build_decision_context(p, now=datetime.fromisoformat('2026-09-19T18:00:00+08:00'))
        with patch.object(dc, '_latest_context', context), patch.object(dc, '_latest_inputs', {'pulse': p}), patch.object(dc, '_save_history') as save:
            out = dc.latest_context(now=datetime.fromisoformat('2026-09-21T10:00:00+08:00'))
            self.assertEqual(out['regime']['id'], 'INSUFFICIENT_DATA')
            self.assertEqual(out['lastObservedRegime']['id'], 'BROAD_RISK_ON')
            self.assertEqual(out['evidence'], context['evidence'])
            self.assertEqual(dc._latest_context['regime']['id'], 'BROAD_RISK_ON')
            save.assert_not_called()

    def test_live_futures_after_friday_midnight_keep_the_start_session(self):
        p = observed_pulse('2026-09-18T13:33:00+08:00')
        p['marketSnapshot']['quotes']['__TXF__']['market']['asOf'] = '2026-09-19T02:00:00+08:00'
        out = dc.build_decision_context(p, now=datetime.fromisoformat('2026-09-19T02:00:10+08:00'))
        self.assertEqual(out['dataQuality']['sourceQuality']['txf']['freshness'], 1.0)
        self.assertEqual(out['regime']['id'], 'BROAD_RISK_ON')

    def test_read_view_and_build_use_the_same_legacy_snapshot_fallback(self):
        p = pulse()
        p['snapshot']['t00'] = copy.deepcopy(p['marketSnapshot']['quotes']['^TWII'])
        p['snapshot']['txf'] = copy.deepcopy(p['marketSnapshot']['quotes']['__TXF__'])
        p.pop('marketSnapshot')
        context = dc.build_decision_context(p, now=FIXED_NOW)
        with patch.object(dc, '_latest_context', context), patch.object(dc, '_latest_inputs', {'pulse': p}):
            view = dc.latest_context(now=FIXED_NOW)
        self.assertEqual(view['dataQuality']['sourceQuality'], context['dataQuality']['sourceQuality'])
        self.assertEqual(view['regime']['id'], 'BROAD_RISK_ON')

    def test_live_post_does_not_reuse_a_frozen_replay_clock(self):
        p = observed_pulse('2020-01-06T09:00:00+08:00')
        frozen = datetime.fromisoformat(p['updatedAt'])
        context = dc.build_decision_context(p, now=frozen)
        self.assertEqual(context['regime']['id'], 'BROAD_RISK_ON')
        with patch.object(dc, '_latest_context', context), patch.object(dc, '_latest_inputs', {'pulse': p, 'now': frozen}):
            view = dc.rebuild_latest(risk_profile=PROFILE)
        self.assertEqual(view['regime']['id'], 'INSUFFICIENT_DATA')
        self.assertIsNone(view['actionEnvelope']['positionRange'])


class PortfolioCoverageTest(unittest.TestCase):
    @staticmethod
    def bars(start, end):
        return [(i, 100, 105, 95, 100 + i % 5, 1000) for i in range(start, end)]

    def build(self, data, holdings, *, kind='actual'):
        with patch.object(portfolio.datastore, 'get_bars_bulk', return_value=data):
            overlay = portfolio.compute(holdings)
        context = dc.build_decision_context(pulse(), now=FIXED_NOW, key_levels=KEYS,
            risk_profile=PROFILE, portfolio_overlay=overlay, portfolio_kind=kind)
        return overlay, context

    def test_no_common_sample_is_unknown_instead_of_zero_risk(self):
        data = {'A': self.bars(1, 81), 'B': self.bars(81, 161), '^TWII': self.bars(1, 161)}
        overlay, context = self.build(data, [{'sym': 'A', 'weight': 50}, {'sym': 'B', 'weight': 50}])
        self.assertEqual(overlay['portfolio']['days'], 0)
        self.assertIsNone(overlay['portfolio']['vol'])
        self.assertIsNone(overlay['portfolio']['var95'])
        self.assertFalse(context['portfolioOverlay']['available'])
        self.assertIsNone(context['actionEnvelope']['positionRange'])
        self.assertEqual(len(context['portfolioOverlay']['stocks']), 2)

    def test_missing_majority_keeps_original_weights_and_blocks_range(self):
        data = {'A': self.bars(1, 81), 'B': self.bars(1, 20), '^TWII': self.bars(1, 81)}
        overlay, context = self.build(data, [{'sym': 'A', 'weight': 10}, {'sym': 'B', 'weight': 90}])
        self.assertEqual(overlay['stocks']['A']['weight'], 10)
        self.assertEqual(overlay['quality']['holdingCoveragePct'], 10)
        self.assertEqual(overlay['skipped'], ['B'])
        self.assertIsNone(context['actionEnvelope']['positionRange'])

    def test_complete_portfolio_still_applies_the_var_cap(self):
        rows = self.bars(1, 81)
        overlay, context = self.build({'A': rows, '^TWII': rows}, [{'sym': 'A', 'weight': 100}])
        self.assertTrue(overlay['quality']['available'])
        self.assertTrue(context['portfolioOverlay']['available'])
        self.assertIn('portfolio_var_cap', context['actionEnvelope']['constraints'])
        self.assertLess(context['actionEnvelope']['positionRange']['capPct'], PROFILE['maxGrossExposure'])

    def test_missing_benchmark_blocks_actual_portfolio_but_not_observation_pool(self):
        data = {'A': self.bars(1, 81)}
        _, actual = self.build(data, [{'sym': 'A', 'weight': 100}])
        _, observed = self.build(data, [{'sym': 'A', 'weight': 100}], kind='observation_pool')
        self.assertIsNone(actual['actionEnvelope']['positionRange'])
        self.assertIsNotNone(observed['actionEnvelope']['positionRange'])
        self.assertIn('observation_pool_not_risk_overlay', observed['actionEnvelope']['constraints'])


class PublicationTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.options = {'db_path': str(Path(self.folder.name) / 'decision.db'),
                        'trace_path': str(Path(self.folder.name) / 'trace.jsonl')}
        self.warning = Mock(return_value={})
        self.delivery = Mock()
        replacements = {'early_warning': types.SimpleNamespace(DB_PATH='unused', process_context=self.warning),
                        'overnight_intraday': types.SimpleNamespace(latest_cached=lambda *args: None),
                        'alert_daemon': types.SimpleNamespace(deliver_signal_events=self.delivery)}
        for replacement in (patch.dict(sys.modules, replacements), patch.object(dc, '_latest_context', None), patch.object(dc, '_latest_inputs', None)):
            replacement.start()
            self.addCleanup(replacement.stop)

    def publish(self, observed, **build_inputs):
        p = observed_pulse(observed)
        build_inputs.setdefault('now', datetime.fromisoformat(observed))
        context = dc.build_decision_context(p, **build_inputs)
        return dc.publish_context(context, pulse=p, build_kwargs=build_inputs, **self.options)

    def test_late_old_thread_is_rejected_before_warning_or_history(self):
        old_ready = threading.Event()
        release_old = threading.Event()
        def old_worker():
            old_ready.set()
            if not release_old.wait(2):
                raise AssertionError('舊工作未收到解除等待訊號')
            return self.publish('2026-08-11T09:00:00+08:00')
        with ThreadPoolExecutor(max_workers=1) as pool:
            older = pool.submit(old_worker)
            self.assertTrue(old_ready.wait(2))
            current = self.publish('2026-08-11T09:01:00+08:00')
            release_old.set()
            rejected = older.result(timeout=2)
        self.assertEqual(rejected['publicationStatus'], 'superseded')
        self.assertEqual(dc._latest_context['asOf'], current['asOf'])
        self.assertEqual(self.warning.call_count, 1)
        self.assertEqual(self.delivery.call_count, 1)
        self.assertEqual(len(dc.history(path=self.options['db_path'])['rows']), 1)

    def test_request_start_prevents_slow_build_from_appearing_newer(self):
        self.publish('2026-08-11T09:01:00+08:00')
        p = observed_pulse('2026-08-11T09:02:00+08:00')
        p['updateStartedAt'] = '2026-08-11T09:00:00+08:00'
        result = dc.publish_context(dc.build_decision_context(p, now=FIXED_NOW), pulse=p, **self.options)
        self.assertEqual(result['publicationStatus'], 'superseded')
        self.assertEqual(self.warning.call_count, 1)

    def test_accepted_side_effects_cannot_interleave(self):
        entered = threading.Event()
        release = threading.Event()
        seen = []
        def warning(context, *args, **kwargs):
            seen.append(context['asOf'])
            if len(seen) == 1:
                entered.set()
                if not release.wait(2):
                    raise AssertionError('第一筆預警未收到解除等待訊號')
            return {}
        self.warning.side_effect = warning
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.publish, '2026-08-11T09:00:00+08:00')
            self.assertTrue(entered.wait(2))
            second = pool.submit(self.publish, '2026-08-11T09:01:00+08:00')
            release.set()
            first.result(timeout=2)
            second.result(timeout=2)
        self.assertEqual(seen, ['2026-08-11T09:00:00+08:00', '2026-08-11T09:01:00+08:00'])
        self.assertEqual(dc.history(path=self.options['db_path'])['rows'][0]['asOf'], seen[-1])

    def test_options_refresh_persists_a_distinct_revision(self):
        initial = self.publish('2026-08-11T09:00:00+08:00')
        publish = dc.publish_context
        def isolated(context, **kwargs):
            return publish(context, **kwargs, **self.options)
        with patch.object(dc, 'publish_context', side_effect=isolated):
            refreshed = dc.update_options_structure({'status': 'ready', 'observed': {'expiry': '2026-08-19', 'tradeDate': '2026-08-11', 'rowCount': 10}})
        rows = dc.history(path=self.options['db_path'])['rows']
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(initial['inputHash'], refreshed['inputHash'])
        self.assertEqual(rows[0]['context']['optionsStructure']['status'], 'ready')
        self.assertEqual(rows[1]['context']['optionsStructure']['status'], 'insufficient')

    def test_input_and_rules_changes_are_preserved_but_identical_replay_is_deduplicated(self):
        first = self.publish('2026-08-11T09:00:00+08:00', sector_flow={'participationPct': 25})
        second = self.publish('2026-08-11T09:00:00+08:00', sector_flow={'participationPct': 75})
        self.assertNotEqual(first['inputHash'], second['inputHash'])
        duplicate = self.publish('2026-08-11T09:00:00+08:00', sector_flow={'participationPct': 75})
        self.assertEqual(second['inputHash'], duplicate['inputHash'])
        with patch.object(dc, 'RULES_VERSION', '回歸測試規則版本'):
            changed = self.publish('2026-08-11T09:00:00+08:00', sector_flow={'participationPct': 75})
        self.assertNotEqual(changed['rulesDigest'], second['rulesDigest'])
        self.assertEqual(len(dc.history(path=self.options['db_path'])['rows']), 3)

    def test_published_inputs_are_not_mutated_by_request_response_decoration(self):
        p = observed_pulse('2026-08-11T09:00:00+08:00')
        context = dc.build_decision_context(p, now=FIXED_NOW)
        dc.publish_context(context, pulse=p, **self.options)
        p['decisionSummary'] = {'unexpected': True}
        p['stocks']['advRatio'] = 0
        self.assertNotIn('decisionSummary', dc._latest_inputs['pulse'])
        self.assertEqual(dc._latest_inputs['pulse']['stocks']['advRatio'], 0.7)


if __name__ == '__main__':
    unittest.main()
