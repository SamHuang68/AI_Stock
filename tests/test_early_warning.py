# -*- coding: utf-8 -*-
from __future__ import annotations

import copy
import os
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))

import early_warning as ew  # noqa: E402


def memory(regime='OVERNIGHT_CONFIRMED'):
    return {
        'ok': True,
        'markets': [
            {'market': market, 'status': 'ready', 'quality': {'status': 'good'},
             'summary': {'regime': {'id': regime}, 'overnightRepricing20Pct': 4.2,
                         'cashSessionAcceptance20Pct': 2.1, 'basketBreadthPct': 80,
                         'asOf': '2026-08-25'}}
            for market in ('TW', 'US')
        ],
    }


def fixture(direction=1, as_of='2026-08-26T01:10:00+00:00', include_weight=True):
    sign = 1 if direction >= 0 else -1
    scenario = {
        'breadth': {'value': 0.85 * sign, 'raw': {'advRatio': 0.72 if sign > 0 else 0.25,
                                                  'velocity3': 0.05 * sign, 'velocity5': 0.04 * sign}},
        'sector': {'value': 0.75 * sign, 'raw': {}},
        'flow': {'value': 0.85 * sign, 'raw': {'institutionalNetYi': 260 * sign,
                                               'txOiChangePct': 2.5 * sign}},
    }
    benchmark = ({'FTSE_TAIWAN_50': {'tsmcWeightPct': 58.35, 'weightQuality': 'external_research'}}
                 if include_weight else {})
    context = {
        'ok': True, 'asOf': as_of, 'scenario': scenario,
        'exposureLab': {'benchmarks': benchmark},
        'dataQuality': {'completeness': 0.95, 'freshness': 1.0},
        'evidence': [], 'regime': {'id': 'BROAD_RISK_ON'}, 'actionEnvelope': {},
    }
    change = 2.0 * sign
    twii = {'price': 100.0, 'changePct': change,
            'market': {'displayChangePct': change, 'session': 'regular',
                       'source': 'test-canonical-pulse', 'asOf': as_of}}
    txf = {'changePct': 1.8 * sign, 'market': {'displayChangePct': 1.8 * sign, 'session': 'night'}}
    pulse = {
        'ok': True, 'updatedAt': as_of,
        'marketSnapshot': {'quotes': {'^TWII': twii, '__TXF__': txf}},
        'global': [
            {'symbol': '^SOX', 'changePct': 2.4 * sign}, {'symbol': '^IXIC', 'changePct': 1.8 * sign},
            {'symbol': 'NVDA', 'changePct': 2.8 * sign}, {'symbol': 'AVGO', 'changePct': 2.6 * sign},
            {'symbol': 'TSM', 'changePct': 2.1 * sign},
        ],
        'signalQuotes': [
            {'symbol': '2330.TW', 'changePct': 2.2 * sign},
            {'symbol': '0050.TW', 'changePct': 2.0 * sign},
        ],
    }
    return context, pulse


class EarlyWarningTest(unittest.TestCase):
    def test_upside_and_downside_are_directional_and_not_probabilities(self):
        up_ctx, up_pulse = fixture(1)
        up = ew.evaluate_context(up_ctx, up_pulse, memory_snapshot=memory())
        down_ctx, down_pulse = fixture(-1)
        down = ew.evaluate_context(down_ctx, down_pulse, memory_snapshot=memory('BROAD_CORRECTION'))
        self.assertGreater(up['upside']['strength'], 80)
        self.assertLess(up['downside']['strength'], 20)
        self.assertGreater(down['downside']['strength'], 80)
        self.assertLess(down['upside']['strength'], 20)
        self.assertFalse(up['dataQuality']['strengthIsProbability'])
        self.assertEqual(len(up['familyScores']), 5)

    def test_0050_is_residualized_or_does_not_double_count(self):
        context, pulse = fixture(1, include_weight=True)
        result = ew.evaluate_context(context, pulse, memory_snapshot=memory())
        anchor = next(row for row in result['familyScores'] if row['id'] == 'anchor')
        self.assertEqual(anchor['observed']['doubleCountGuard'], '0050_ex_2330_residual')
        self.assertIsNotNone(anchor['observed']['0050Ex2330ChangePct'])

        context, pulse = fixture(1, include_weight=False)
        result = ew.evaluate_context(context, pulse, memory_snapshot=memory())
        anchor = next(row for row in result['familyScores'] if row['id'] == 'anchor')
        self.assertEqual(anchor['observed']['doubleCountGuard'], 'residual_unavailable')
        self.assertIsNone(anchor['observed']['0050Ex2330ChangePct'])
        self.assertTrue(any('不重複計票' in row for row in anchor['reasons']))

    def test_missing_memory_fails_closed_without_blocking_other_domains(self):
        context, pulse = fixture(1)
        result = ew.evaluate_context(context, pulse, memory_snapshot={})
        memory_row = next(row for row in result['familyScores'] if row['id'] == 'memoryCycle')
        self.assertFalse(memory_row['available'])
        self.assertIn('memoryCycle', result['dataQuality']['missingDomains'])
        self.assertGreater(result['upside']['strength'], 55)

    def test_lifecycle_requires_repetition_and_deduplicates_same_observation(self):
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / 'signals.db')
            start = datetime(2026, 8, 26, 1, 10, tzinfo=timezone.utc)
            states = []
            event_counts = []
            for index in range(5):
                as_of = (start + timedelta(minutes=index)).isoformat()
                context, pulse = fixture(1, as_of=as_of)
                result = ew.process_context(context, pulse, memory_snapshot=memory(), db_path=db,
                                            now=start + timedelta(minutes=index))
                signal = next(row for row in result['signals'] if row['signalId'] == 'TW_ATTACK_BUILDUP')
                states.append(signal['state'])
                event_counts.append(len(result['newEvents']))
            self.assertEqual(states, ['WATCH', 'ARMED', 'CONFIRMED', 'ACTIVE', 'ACTIVE'])
            context, pulse = fixture(1, as_of=(start + timedelta(minutes=4)).isoformat())
            duplicate = ew.process_context(context, pulse, memory_snapshot=memory(), db_path=db,
                                           now=start + timedelta(minutes=5))
            signal = next(row for row in duplicate['signals'] if row['signalId'] == 'TW_ATTACK_BUILDUP')
            self.assertEqual(signal['state'], 'ACTIVE')
            self.assertEqual(duplicate['newEvents'], [])
            history = ew.history(100, db)
            attack_events = [row for row in history['events'] if row['signalId'] == 'TW_ATTACK_BUILDUP']
            self.assertEqual([row['toState'] for row in reversed(attack_events)],
                             ['WATCH', 'ARMED', 'CONFIRMED', 'ACTIVE'])

    def test_component_conflict_is_explicit(self):
        context, pulse = fixture(1)
        pulse['global'] = [
            {'symbol': '^SOX', 'changePct': -2.5}, {'symbol': '^IXIC', 'changePct': -2.0},
            {'symbol': 'NVDA', 'changePct': -3.0}, {'symbol': 'AVGO', 'changePct': -3.0},
            {'symbol': 'TSM', 'changePct': -2.0},
        ]
        result = ew.evaluate_context(context, pulse, memory_snapshot=memory())
        signal = next(row for row in result['signals'] if row['signalId'] == 'AI_WAFER_DOUBLE_ARROW')
        self.assertEqual(signal['direction'], 'mixed')
        self.assertLessEqual(signal['strength'], 54)

    def test_active_hysteresis_requires_three_subthreshold_observations(self):
        previous = {
            'direction': 'upside', 'state': 'ACTIVE',
            'consecutive_hits': 4, 'miss_count': 0,
        }
        moderate = {'direction': 'upside', 'strength': 60, 'independentDomains': 2,
                    'cashConfirmation': False}
        state, hits, misses = ew._target_state(moderate, previous, False)
        self.assertEqual((state, misses), ('ACTIVE', 0))
        weak = {'direction': 'upside', 'strength': 40, 'independentDomains': 1,
                'cashConfirmation': False}
        for expected in ('ACTIVE', 'ACTIVE', 'RECOVERY'):
            previous.update(state=state, consecutive_hits=hits, miss_count=misses)
            state, hits, misses = ew._target_state(weak, previous, False)
            self.assertEqual(state, expected)

    def test_prospective_ledger_enrolls_once_and_resolves_immutable_horizons(self):
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / 'signals.db')
            start = datetime(2026, 8, 20, 1, 10, tzinfo=timezone.utc)
            context, pulse = fixture(1, as_of=start.isoformat())
            first = ew.process_context(
                context, pulse, memory_snapshot=memory(), market_history=[],
                db_path=db, now=start,
            )
            self.assertEqual(first['prospectiveValidation']['status'], 'building')

            history = []
            closes = [101.0, 102.5, 103.0, 104.0, 105.0]
            for offset, close in enumerate(closes, start=1):
                observed = start + timedelta(days=offset)
                history.append({
                    'date': observed.date().isoformat(), 'close': close,
                    'source': 'test-finalized-twii', 'asOf': observed.isoformat(),
                })
                context, pulse = fixture(1, as_of=observed.isoformat())
                pulse['marketSnapshot']['quotes']['^TWII']['price'] = close
                ew.process_context(
                    context, pulse, memory_snapshot=memory(), market_history=history,
                    db_path=db, now=observed,
                )

            result = ew.performance(20, db, signal_id='TW_ATTACK_BUILDUP')
            self.assertEqual(result['totalTrials'], 1)
            self.assertEqual([row['sessions'] for row in result['horizons']], [1, 3, 5])
            self.assertEqual([row['resolvedCount'] for row in result['horizons']], [1, 1, 1])
            self.assertTrue(all(not row['ratesAvailable'] for row in result['horizons']))
            self.assertTrue(all(row['directionHitRatePct'] is None for row in result['horizons']))
            self.assertEqual(
                [row['horizonSessions'] for row in result['trials'][0]['outcomes']],
                [1, 3, 5],
            )
            first_outcome = result['trials'][0]['outcomes'][0]
            self.assertEqual(first_outcome['rawReturnPct'], 1.0)
            self.assertFalse(first_outcome['predictiveProbability'])

            corrected = list(history)
            corrected[0] = {**corrected[0], 'close': 90.0}
            context, pulse = fixture(1, as_of=(start + timedelta(days=6)).isoformat())
            ew.process_context(
                context, pulse, memory_snapshot=memory(), market_history=corrected,
                db_path=db, now=start + timedelta(days=6),
            )
            unchanged = ew.performance(20, db, signal_id='TW_ATTACK_BUILDUP')
            self.assertEqual(unchanged['trials'][0]['outcomes'][0]['rawReturnPct'], 1.0)

    def test_prospective_rates_are_withheld_until_twenty_resolved_trials(self):
        with tempfile.TemporaryDirectory() as folder:
            db = str(Path(folder) / 'signals.db')
            ew._init_db(db)
            with closing(sqlite3.connect(db)) as conn:
                with conn:
                    for index in range(20):
                        trial_id = f'trial-{index:02d}'
                        conn.execute(
                            'INSERT INTO signal_trials('
                            'trial_id,signal_id,direction,origin_session,entry_price,trial_json) '
                            'VALUES(?,?,?,?,?,?)',
                            (trial_id, 'TW_ATTACK_BUILDUP', 'upside', f'2026-07-{index + 1:02d}',
                             100.0, '{}'),
                        )
                        for horizon in ew.OUTCOME_HORIZONS:
                            direction_hit = int(index < 15)
                            material_hit = int(index < 10)
                            conn.execute(
                                'INSERT INTO signal_outcomes('
                                'trial_id,horizon_sessions,directional_return_pct,max_favorable_pct,'
                                'max_adverse_pct,direction_hit,material_hit,lead_sessions,outcome_json) '
                                'VALUES(?,?,?,?,?,?,?,?,?)',
                                (trial_id, horizon, 1.0 if direction_hit else -1.0,
                                 2.5 if material_hit else 1.0, 0.8, direction_hit,
                                 material_hit, horizon if material_hit else None, '{}'),
                            )
            result = ew.performance(5, db)
            self.assertEqual(result['scope'], 'headline_precursors')
            self.assertEqual(result['status'], 'ready')
            self.assertTrue(all(row['ratesAvailable'] for row in result['horizons']))
            self.assertTrue(all(row['directionHitRatePct'] == 75.0 for row in result['horizons']))
            self.assertTrue(all(row['materialMoveHitRatePct'] == 50.0 for row in result['horizons']))


if __name__ == '__main__':
    unittest.main()
