# -*- coding: utf-8 -*-
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import decision_context as dc  # noqa: E402


def pulse(change=1.0, adv=0.70, risk=25, health=75, inst=180, volume=70, completeness=90, updated='2026-08-11T08:45:00'):
    twii = {
        'price': 23000, 'prevClose': 22770, 'changePct': change,
        'source': 'twse-mis', 'session': 'regular', 'asOf': updated,
        'market': {'displayChangePct': change, 'source': 'twse-mis', 'session': 'regular',
                   'referenceType': 'previous_close', 'asOf': updated},
    }
    txf = {
        'price': 23020, 'prevClose': 22790, 'changePct': change * 0.9,
        'market': {'displayChangePct': change * 0.9, 'source': 'taifex-mis', 'session': 'night',
                   'referenceType': 'previous_close', 'asOf': updated},
    }
    up = int(1000 * adv)
    down = 1000 - up
    return {
        'ok': True, 'updatedAt': updated, 'date': '2026-08-11',
        'marketSnapshot': {'quotes': {'^TWII': twii, '__TXF__': txf}},
        'snapshot': {
            't00': {'price': 23000, 'changePct': change},
            'txf': {'price': 23020, 'changePct': change * 0.9},
            'stocks': {'up': up, 'down': down, 'advRatio': adv, 'limitDown': 1},
            'inst': {'totalYi': inst},
        },
        'stocks': {'up': up, 'down': down, 'advRatio': adv, 'limitDown': 1},
        'riskScore': risk, 'healthScore': health, 'dataCompleteness': completeness,
        'breadthSource': 'TWSE MI_INDEX MS', 'breadthScope': 'TWSE_STOCKS',
        'overview': {'strip': {
            'volumeScore': volume, 'turnoverVsMa5Pct': 2.0, 'basisPct': 0.08,
            't00Trend': {'momScore': 70},
        }, 'institutional': {'totalYi': inst, 'date': '2026-08-11'}},
        'global': [{'symbol': '^SOX', 'changePct': 0.8}, {'symbol': '^IXIC', 'changePct': 0.4}],
        'sectors': [{'name': '半導體', 'changePct': 1.2}, {'name': '金融', 'changePct': 0.3}],
        'flash': [],
    }


KEYS = {
    'symbol': '^TWII', 'levels': {'r2': 23300, 'r1': 23150, 'pivot': 22950, 's1': 22800, 's2': 22600},
    'atr': {'pct': 1.5}, 'volatility': {'realized20AnnualPct': 18, 'expectedOneDayPct': 1.5},
    'quality': {'complete': True, 'stale': False},
}
FIXED_NOW = datetime(2026, 8, 11, 1, 0, tzinfo=timezone.utc)


def build(p, **kwargs):
    kwargs.setdefault('now', FIXED_NOW)
    return dc.build_decision_context(p, **kwargs)


class DecisionContextTest(unittest.TestCase):
    def test_options_structure_is_layered_and_evidenced_without_changing_regime(self):
        options = {
            'status': 'ready', 'contractVersion': 2, 'shadowMode': True, 'decisionUse': 'research_only',
            'observed': {
                'expiry': '2026-08-19', 'tradeDate': '2026-08-11', 'rowCount': 20,
                'callOpenInterest': 1200, 'putOpenInterest': 1500, 'oiPutCallRatio': 1.25,
                'callWall': {'strike': 23500, 'openInterest': 400},
                'putWall': {'strike': 22500, 'openInterest': 500},
            },
            'derived': {
                'totalOiGamma1PctNtd': 123400000, 'totalOiGammaYi': 1.234,
                'totalOiVega1VolPointNtd': 4560000, 'totalOiVegaWan': 456.0,
                'vegaOiCoveragePct': 92.0,
                'ivOiCoveragePct': 92.0, 'atmIvPct': 21.5, 'ivSkew25dPctPoint': 3.2,
            },
            'modeled': {
                'eligible': True, 'directionConsensus': 'DIRECTION_AMBIGUOUS',
                'coefficientVersion': 'txo-public-oi-scenarios/v1',
                'flipBand': {'status': 'ready', 'low': 22800, 'high': 23100},
                'scenarios': [{'id': 'balanced_proxy', 'signedGexYi': 1.1,
                               'scenarioVexYi': -0.03, 'primaryFlip': 22900}],
            },
            'history': {
                'status': 'ready', 'expiry': '2026-08-19', 'currentTradeDate': '2026-08-11',
                'baselineTradeDate': '2026-08-10', 'sameExpiry': True,
                'changes': {'callOpenInterestPct': 2.0, 'putOpenInterestPct': -1.0,
                            'atmIvPctPoint': 0.5, 'totalOiGammaPct': 4.0,
                            'totalOiVegaPct': 3.0},
            },
            'quality': {'chainAsOf': '2026-08-11', 'isHybridTimestamp': False},
        }
        baseline = build(pulse(), key_levels=KEYS)
        out = build(pulse(), key_levels=KEYS, options_structure=options)
        self.assertEqual(out['regime']['id'], baseline['regime']['id'])
        self.assertEqual(out['optionsStructure']['observed']['expiry'], '2026-08-19')
        ids = {row['id'] for row in out['evidence']}
        self.assertTrue({'options.chain', 'options.gamma_density', 'options.vega_density',
                         'options.iv_structure', 'options.gex_scenario',
                         'options.same_expiry_change'}.issubset(ids))
        self.assertNotIn('optionsStructure', dc.compact_context(out))

    def test_regime_matrix_covers_primary_states(self):
        broad = build(pulse(), key_levels=KEYS)
        narrow = build(pulse(1.0, 0.38, inst=0, volume=50), key_levels=KEYS)
        defensive_pulse = pulse(-1.3, 0.25, risk=75, inst=-200, volume=35)
        defensive_pulse['overview']['strip']['t00Trend']['momScore'] = 20
        defensive = build(defensive_pulse, key_levels=KEYS)
        cap_pulse = pulse(-4.0, 0.15, risk=90, inst=-300, volume=90)
        cap_pulse['stocks']['limitDown'] = 30
        cap_pulse['snapshot']['stocks']['limitDown'] = 30
        cap = build(cap_pulse, key_levels=KEYS)
        missing = pulse()
        missing['stocks'] = {}
        missing['snapshot']['stocks'] = {}
        insufficient = build(missing, key_levels=KEYS)
        self.assertEqual(broad['regime']['id'], 'BROAD_RISK_ON')
        self.assertEqual(narrow['regime']['id'], 'NARROW_RALLY')
        self.assertEqual(defensive['regime']['id'], 'DEFENSIVE_RISK_OFF')
        self.assertEqual(cap['regime']['id'], 'CAPITULATION')
        self.assertEqual(insufficient['regime']['id'], 'INSUFFICIENT_DATA')

    def test_recovery_requires_breadth_lead(self):
        p = pulse(-0.02, 0.60, risk=30, inst=0, volume=50)
        hist = [{'advRatio': 0.60}, {'advRatio': 0.45}, {'advRatio': 0.44}, {'advRatio': 0.43}]
        out = build(p, key_levels=KEYS, breadth_history=hist)
        self.assertEqual(out['regime']['id'], 'RECOVERY_ATTEMPT')
        self.assertEqual(len(out['breadthTrend']['rows']), 4)
        self.assertGreater(out['breadthTrend']['changeVs3'], 0)

    def test_divergence_and_evidence_are_auditable(self):
        out = build(pulse(1.0, 0.35, inst=-100, volume=40), key_levels=KEYS)
        ids = {x['id'] for x in out['divergences']}
        self.assertIn('INDEX_UP_BREADTH_DOWN', ids)
        self.assertIn('FLOW_PRICE_CONFLICT', ids)
        for ev in out['evidence']:
            self.assertTrue(ev['source'])
            self.assertTrue(ev['reference'])
            self.assertIn('asOf', ev)
        self.assertEqual(out['actionEnvelope']['positionRange'], None)

    def test_multi_day_index_streak_catches_rounded_45pct_breadth_divergence(self):
        p = pulse(0.35, 0.45, inst=80, volume=58)
        p['stocks'].update({'up': 442, 'down': 541, 'advRatio': 0.45})
        p['snapshot']['stocks'].update({'up': 442, 'down': 541, 'advRatio': 0.45})
        p['overview']['strip']['t00Trend']['streak'] = 4
        out = build(p, key_levels=KEYS)
        row = next(x for x in out['divergences'] if x['id'] == 'INDEX_UP_BREADTH_DOWN')
        self.assertEqual(row['severity'], 'watch')
        self.assertEqual(row['observed']['indexStreak'], 4)
        self.assertEqual(row['observed']['advancers'], 442)
        self.assertEqual(row['observed']['decliners'], 541)
        self.assertAlmostEqual(row['observed']['longShortRatio'], 0.817, places=3)
        compact = dc.compact_context(out)
        self.assertEqual(compact['divergenceDetails'][0]['observed']['breadthGapPct'], 5.0)

    def test_divergence_intensity_velocity_and_action_lock_are_auditable(self):
        p = pulse(1.11, 0.45, inst=80, volume=58)
        p['stocks'].update({'up': 450, 'down': 470, 'unchanged': 80})
        p['snapshot']['stocks'].update({'up': 450, 'down': 470, 'unchanged': 80})
        p['overview']['strip']['t00Trend']['streak'] = 4
        breadth = [
            {'date': '2026-08-11', 'advRatio': 0.45, 'up': 450, 'down': 470, 'flat': 80},
            {'date': '2026-08-10', 'advRatio': 0.52}, {'date': '2026-08-09', 'advRatio': 0.56},
            {'date': '2026-08-08', 'advRatio': 0.58}, {'date': '2026-08-07', 'advRatio': 0.60},
        ]
        index = [
            {'date': '2026-08-11', 'close': 23000, 'changePct': 1.11},
            {'date': '2026-08-10', 'close': 22800}, {'date': '2026-08-09', 'close': 22600},
            {'date': '2026-08-08', 'close': 22400}, {'date': '2026-08-07', 'close': 22200},
        ]
        out = build(p, key_levels=KEYS, breadth_history=breadth, index_history=index)
        row = next(x for x in out['divergences'] if x['id'] == 'INDEX_UP_BREADTH_DOWN')
        self.assertAlmostEqual(row['observed']['divergenceIntensityRaw'], 5.55, places=2)
        self.assertLess(row['observed']['breadthVelocity5'], 0)
        self.assertEqual(row['visual']['type'], 'index_breadth_overlay')
        self.assertTrue(any(x['id'] == 'LIMIT_NEW_LEVERAGE' for x in out['actionEnvelope']['mandatoryControls']))
        self.assertIn('CHASE_GAP_UP', out['actionEnvelope']['prohibited'])
        self.assertIn('breadth_divergence_risk_lock', out['actionEnvelope']['constraints'])

    def test_nominal_night_gap_has_day_basis_z_but_needs_oi_or_adjustment_to_conflict(self):
        index = []
        futures = []
        for i in range(60):
            day = f'202601{i + 1:02d}'
            spot = 20000 + i * 10
            basis = 20 if i < 59 else 400
            index.append({'date': day, 'close': spot})
            futures.append({'date': day, 'close': spot + basis})
        plain = build(pulse(1.0, 0.70), key_levels=KEYS, index_history=index, futures_history=futures)
        self.assertEqual(plain['basisContext']['mode'], 'cross_session_nominal_gap')
        self.assertGreater(abs(plain['basisContext']['basisZ20']), 2)
        self.assertNotIn('SPOT_FUTURES_CONFLICT', {x['id'] for x in plain['divergences']})

        p = pulse(1.11, 0.70)
        p['marketSnapshot']['quotes']['__TXF__']['market']['displayChangePct'] = 1.08
        p['extras'] = {'txOi': {
            'contract': '202608', 'date': '2026-08-11', 'prevDate': '2026-08-10',
            'oi': 90000, 'oiChgPct': -2.87, 'priceChgPct': 1.08,
            'source': 'FinMind TaiwanFuturesDaily TX',
        }}
        out = build(p, key_levels=KEYS, index_history=index, futures_history=futures)
        row = next(x for x in out['divergences'] if x['id'] == 'SPOT_FUTURES_CONFLICT')
        self.assertTrue(row['observed']['shortCoveringRisk'])
        self.assertFalse(row['observed']['sessionComparable'])
        self.assertIn('短空回補', row['insight'])

    def test_same_contract_oi_enters_flow_and_evidence_without_cross_roll_guess(self):
        p = pulse()
        p['extras'] = {'txOi': {
            'contract': '202608', 'date': '2026-08-11', 'prevDate': '2026-08-10',
            'oi': 120000, 'oiChgPct': 2.5, 'priceChgPct': 0.8,
            'source': 'FinMind TaiwanFuturesDaily TX',
        }}
        out = build(p, key_levels=KEYS)
        self.assertGreater(out['scenario']['flow']['raw']['txOiSignal'], 0)
        self.assertIn('flow.tx_oi', {x['id'] for x in out['evidence']})

    def test_position_range_requires_complete_risk_profile_and_applies_caps(self):
        profile = {
            'baseGrossExposure': 70, 'maxGrossExposure': 90, 'maxLeverage': 1,
            'maxSingleNameWeight': 20, 'maxSectorWeight': 40,
            'maxPortfolioBeta': 1.1, 'maxDailyVaR': 2.0, 'investmentHorizon': 'swing',
        }
        overlay = {
            'stocks': {'2330': {'weight': 100, 'beta': 1.4}},
            'portfolio': {'vol': 25, 'var95': 3.0, 'days': 200},
            'corr': {}, 'sector': {'半導體': 100}, 'skipped': [],
        }
        out = build(pulse(), key_levels=KEYS, risk_profile=profile, portfolio_overlay=overlay)
        rng = out['actionEnvelope']['positionRange']
        self.assertIsNotNone(rng)
        self.assertLess(rng['capPct'], 90)
        self.assertIn('portfolio_beta_cap', out['actionEnvelope']['constraints'])
        self.assertIn('portfolio_var_cap', out['actionEnvelope']['constraints'])
        self.assertIn('lookthrough_tsmc_over_limit', out['actionEnvelope']['constraints'])
        self.assertGreater(out['portfolioOverlay']['lookThrough']['tsmcEconomicExposurePct'], 99)
        # Beta 1.4/1.1 與 VaR 3/2 共線時取最嚴約束，不連乘。
        self.assertAlmostEqual(rng['capPct'], round(90 * min(1.1 / 1.4, 2.0 / 3.0), 1), places=1)

    def test_beta_and_var_caps_take_min_not_product(self):
        profile = {
            'baseGrossExposure': 70, 'maxGrossExposure': 90, 'maxLeverage': 1,
            'maxSingleNameWeight': 20, 'maxSectorWeight': 40,
            'maxPortfolioBeta': 1.1, 'maxDailyVaR': 2.0, 'investmentHorizon': 'swing',
        }
        portfolio = {
            'kind': 'actual', 'available': True,
            'portfolioBeta': 1.4, 'var95DailyPct': 3.0,
        }
        rng, constraints = dc._position_range(
            'BROAD_RISK_ON', 1.0, KEYS, profile, portfolio, None)
        self.assertIsNotNone(rng)
        product = 90 * (1.1 / 1.4) * (2.0 / 3.0)
        tightest = 90 * min(1.1 / 1.4, 2.0 / 3.0)
        self.assertAlmostEqual(rng['capPct'], round(tightest, 1), places=1)
        self.assertGreater(rng['capPct'], product)
        self.assertIn('portfolio_beta_cap', constraints)
        self.assertIn('portfolio_var_cap', constraints)

    def test_decision_history_enables_wal(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'decision_history.db')
            conn = dc._connect(path)
            try:
                mode = conn.execute('PRAGMA journal_mode').fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(str(mode).lower(), 'wal')

    def test_exposure_lab_keeps_00685l_thesis_separate_from_diversification(self):
        overlay = {
            'stocks': {
                '00631L': {'weight': 60, 'beta': 1.9},
                '00685L': {'weight': 25, 'beta': 1.9},
                '2330': {'weight': 15, 'beta': 1.2},
            },
            'portfolio': {'vol': 35, 'var95': 4.0, 'days': 200},
            'corr': {'00631L|00685L': 0.98}, 'sector': {'ETF': 85, '半導體': 15}, 'skipped': [],
        }
        out = build(pulse(), key_levels=KEYS, portfolio_overlay=overlay)
        look = out['exposureLab']['portfolioLookThrough']
        self.assertTrue(look['leveragedOverlap'])
        self.assertFalse(look['diversificationCredit'])
        self.assertEqual(out['exposureLab']['hypotheses'][0]['status'], 'UNVERIFIED')
        self.assertEqual(out['exposureLab']['hypotheses'][0]['scope'], 'actual_portfolio_only')
        self.assertIsNone(out['actionEnvelope']['positionRange'])

    def test_unavailable_portfolio_blocks_position_range(self):
        profile = {
            'baseGrossExposure': 70, 'maxGrossExposure': 90, 'maxLeverage': 1,
            'maxSingleNameWeight': 20, 'maxSectorWeight': 40,
            'maxPortfolioBeta': 1.1, 'maxDailyVaR': 2.0, 'investmentHorizon': 'swing',
        }
        out = build(
            pulse(), key_levels=KEYS, risk_profile=profile,
            portfolio_overlay={'error': 'price history unavailable'},
        )
        self.assertIsNone(out['actionEnvelope']['positionRange'])
        self.assertIn('portfolio_overlay_unavailable', out['actionEnvelope']['constraints'])

    def test_observation_pool_never_caps_risk_profile_as_actual_portfolio(self):
        profile = {
            'baseGrossExposure': 70, 'maxGrossExposure': 90, 'maxLeverage': 1,
            'maxSingleNameWeight': 20, 'maxSectorWeight': 40,
            'maxPortfolioBeta': 1.1, 'maxDailyVaR': 2.0, 'investmentHorizon': 'swing',
        }
        overlay = {
            'stocks': {'2330': {'weight': 100, 'beta': 2.0}},
            'portfolio': {'vol': 50, 'var95': 8.0, 'days': 200},
            'corr': {}, 'sector': {'半導體': 100}, 'skipped': [],
        }
        out = build(pulse(), key_levels=KEYS, risk_profile=profile,
                    portfolio_overlay=overlay, portfolio_kind='observation_pool')
        self.assertEqual(out['actionEnvelope']['positionRange']['capPct'], 90.0)
        self.assertIn('observation_pool_not_risk_overlay', out['actionEnvelope']['constraints'])
        self.assertNotIn('portfolio_beta_cap', out['actionEnvelope']['constraints'])

    def test_observation_pool_never_exposes_holding_specific_hypothesis(self):
        overlay = {
            'stocks': {'00685L': {'weight': 100, 'beta': 1.9}},
            'portfolio': {'vol': 35, 'var95': 4.0, 'days': 200},
            'corr': {}, 'sector': {'ETF': 100}, 'skipped': [],
        }
        out = build(pulse(), key_levels=KEYS, portfolio_overlay=overlay,
                    portfolio_kind='observation_pool')
        self.assertEqual(out['exposureLab']['hypotheses'], [])

    def test_invalid_complete_risk_profile_never_publishes_range(self):
        invalid = {
            'baseGrossExposure': 70, 'maxGrossExposure': 90, 'maxLeverage': 1,
            'maxSingleNameWeight': 20, 'maxSectorWeight': 40,
            'maxPortfolioBeta': 0, 'maxDailyVaR': 2.0, 'investmentHorizon': 'swing',
        }
        out = build(pulse(), key_levels=KEYS, risk_profile=invalid)
        self.assertIsNone(out['actionEnvelope']['positionRange'])
        self.assertIn('risk_profile_invalid_exposure', out['actionEnvelope']['constraints'])

    def test_insufficient_data_never_turns_into_zero_percent_position_signal(self):
        p = pulse()
        p['stocks'] = {}
        p['snapshot']['stocks'] = {}
        profile = {
            'baseGrossExposure': 100, 'maxGrossExposure': 200, 'maxLeverage': 2,
            'maxSingleNameWeight': 70, 'maxSectorWeight': 95,
            'maxPortfolioBeta': 2.5, 'maxDailyVaR': 8, 'investmentHorizon': 'long_term',
        }
        out = build(p, key_levels=KEYS, risk_profile=profile)
        self.assertEqual(out['regime']['id'], 'INSUFFICIENT_DATA')
        self.assertIsNone(out['actionEnvelope']['positionRange'])
        self.assertIn('insufficient_data_no_position_range', out['actionEnvelope']['constraints'])

    def test_publish_history_trace_and_replay(self):
        with tempfile.TemporaryDirectory() as td:
            db = str(Path(td) / 'decision.db')
            trace = str(Path(td) / 'decision.jsonl')
            p1 = pulse(updated='2026-08-11T08:45:00')
            c1 = build(p1, key_levels=KEYS)
            dc.publish_context(c1, pulse=p1, build_kwargs={'key_levels': KEYS}, db_path=db, trace_path=trace, elapsed_ms=5)
            self.assertEqual(dc.history(10, path=db)['rows'][0]['regime'], 'BROAD_RISK_ON')
            row = json.loads(Path(trace).read_text(encoding='utf-8').splitlines()[0])
            self.assertEqual(row['regime'], 'BROAD_RISK_ON')
            p2 = pulse(1.0, 0.38, inst=0, volume=50, updated='2026-08-11T08:46:00')
            replay = dc.replay([p1, p2], key_levels=KEYS)
            self.assertEqual(replay['transitions'][0]['to'], 'NARROW_RALLY')

    def test_checked_in_replay_fixtures(self):
        fixture = Path(__file__).with_name('fixtures') / 'decision_replay.json'
        cases = json.loads(fixture.read_text(encoding='utf-8'))
        replay = dc.replay([x['pulse'] for x in cases])
        actual = [(x.get('regime') or {}).get('id') for x in replay['contexts']]
        self.assertEqual(actual, [x['expectedRegime'] for x in cases])

    def test_naive_local_timestamp_is_checked_for_freshness(self):
        stale_now = datetime(2026, 8, 12, 1, 0, tzinfo=timezone.utc)
        out = dc.build_decision_context(pulse(), key_levels=KEYS, now=stale_now)
        self.assertEqual(out['dataQuality']['freshness'], 0.2)
        self.assertEqual(out['regime']['id'], 'INSUFFICIENT_DATA')

    def test_stale_key_levels_are_not_published_as_action_triggers(self):
        stale = json.loads(json.dumps(KEYS))
        stale['quality']['stale'] = True
        stale['referenceDate'] = '2026-06-22'
        profile = {
            'baseGrossExposure': 70, 'maxGrossExposure': 90, 'maxLeverage': 1,
            'maxSingleNameWeight': 20, 'maxSectorWeight': 40,
            'maxPortfolioBeta': 1.1, 'maxDailyVaR': 2.0, 'investmentHorizon': 'swing',
        }
        out = build(pulse(), key_levels=stale, risk_profile=profile)
        joined = ' '.join(out['confirmation'] + out['invalidation'])
        self.assertNotIn('R1', joined)
        self.assertNotIn('S1', joined)
        self.assertIn('key_levels_stale', out['actionEnvelope']['constraints'])
        compact = dc.compact_context(out)
        self.assertTrue(compact['keyLevelMeta']['quality']['stale'])
        self.assertEqual(compact['keyLevelMeta']['referenceDate'], '2026-06-22')
        self.assertIn('expectedOneDayPct', compact['volatility'])

    def test_unselected_incomplete_benchmark_does_not_lock_selected_benchmark(self):
        exposure = {
            'selectedBenchmarkId': 'FTSE_TAIWAN_50',
            'benchmarks': {
                'FTSE_TAIWAN_50': {'status': 'EDGE_POSITIVE_RESEARCH'},
                'TAIEX': {'status': 'RESEARCH_DATA_INCOMPLETE'},
            },
            'weeklyHealth': {'flags': []},
        }
        envelope = dc._action_envelope(
            'BROAD_RISK_ON', [], KEYS, 0.8, None, None, exposure)
        self.assertNotIn('ADD_LEVERAGE', envelope['restricted'])

        exposure['selectedBenchmarkId'] = 'TAIEX'
        envelope = dc._action_envelope(
            'BROAD_RISK_ON', [], KEYS, 0.8, None, None, exposure)
        self.assertIn('ADD_LEVERAGE', envelope['restricted'])

    def test_short_horizon_volatility_is_monitor_only_for_position_range(self):
        profile = {
            'baseGrossExposure': 80, 'maxGrossExposure': 150, 'maxLeverage': 1.5,
            'maxSingleNameWeight': 60, 'maxSectorWeight': 90,
            'maxPortfolioBeta': 2.0, 'maxDailyVaR': 6.0,
            'investmentHorizon': 'long_term',
        }
        calm = json.loads(json.dumps(KEYS))
        calm['volatility'].update({
            'stateToForecastRatio': 0.7, 'realized20AnnualPct': 12.0})
        stressed = json.loads(json.dumps(KEYS))
        stressed['volatility'].update({
            'stateToForecastRatio': 1.8, 'realized20AnnualPct': 45.0})
        left = build(pulse(), key_levels=calm, risk_profile=profile)
        right = build(pulse(), key_levels=stressed, risk_profile=profile)
        self.assertEqual(left['actionEnvelope']['positionRange']['targetPct'],
                         right['actionEnvelope']['positionRange']['targetPct'])
        multipliers = right['actionEnvelope']['positionRange']['multipliers']
        self.assertFalse(multipliers['stateVolatilityApplied'])
        self.assertEqual(multipliers['stateVolatility'], 1.0)


if __name__ == '__main__':
    unittest.main()
