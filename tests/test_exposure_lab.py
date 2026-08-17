# -*- coding: utf-8 -*-
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))

import exposure_lab  # noqa: E402


def benchmark_contract(days=820, up=0.006, down=-0.004):
    level = 10000.0
    rows = []
    start = date(2023, 1, 2)
    for index in range(days):
        level *= 1.0 + (down if index % 3 == 0 else up)
        rows.append({
            'date': (start + timedelta(days=index)).isoformat(),
            'priceIndex': round(level * 0.45, 4),
            'totalReturnIndex': round(level, 4),
        })
    return {
        'rows': rows, 'source': 'official-fixture', 'asOf': rows[-1]['date'],
        'quality': 'ready', 'pointInTimeAudited': True,
    }


class ExposureLabTest(unittest.TestCase):
    def setUp(self):
        self.levels = {
            'referenceDate': '2026-08-11', 'source': 'fixture',
            'quality': {'stale': False},
            'volatility': {
                'stateDownside20AnnualPct': 18.0,
                'horizonForecastAnnualPct': 24.0,
                'stateToForecastRatio': 0.75,
            },
        }
        self.benchmarks = {'FTSE_TAIWAN_50': benchmark_contract()}

    def test_contract_separates_monthly_core_from_weekly_monitor(self):
        lab = exposure_lab.build_exposure_lab(
            key_levels=self.levels, benchmark_data=self.benchmarks,
            risk_profile={'maxLeverage': 2.0}, as_of='2026-08-16')
        self.assertEqual(lab['contractVersion'], 3)
        self.assertEqual(lab['model'], 'st-exposure-lab/v3')
        self.assertFalse(lab['coreResearch']['weeklyMutationAllowed'])
        self.assertEqual(lab['weeklyHealth']['actionAuthority'], 'monitor_only')
        self.assertFalse(lab['weeklyHealth']['mayIncreaseExposure'])
        self.assertEqual(lab['actionAuthority'], 'research_only')

    def test_guidance_history_is_observed_not_future_certainty(self):
        score = exposure_lab.tsmc_guidance_reliability()
        self.assertEqual(score['observations'], 9)
        self.assertEqual(score['atOrAboveHighCount'], 7)
        self.assertEqual(score['upperHalfCount'], 9)
        self.assertIn('不把', score['interpretation'])

    def test_eps_path_keeps_actual_guidance_and_model_layers_distinct(self):
        eps = exposure_lab.tsmc_eps_evidence()
        self.assertEqual(eps['actualQuarters'], 2)
        self.assertEqual(eps['guidanceDerivedQuarters'], 1)
        self.assertEqual(eps['modelQuarters'], 1)
        self.assertAlmostEqual(eps['epsBase'], 107.60, places=2)
        self.assertIsNone(eps['epsLow'])
        self.assertIsNone(eps['epsHigh'])

    def test_two_leveraged_etfs_are_concentration_not_diversification(self):
        look = exposure_lab.portfolio_lookthrough({
            '00631L': {'weight': 59.8},
            '00685L': {'weight': 24.8},
            '2330': {'weight': 15.4},
        })
        self.assertTrue(look['leveragedOverlap'])
        self.assertFalse(look['diversificationCredit'])
        self.assertGreater(look['effectiveGrossExposurePct'], 180)
        self.assertGreater(look['tsmcEconomicExposurePct'], 100)
        self.assertIn('集中', look['overlapNote'])

    def test_shareable_default_hides_holding_specific_hypotheses(self):
        lab = exposure_lab.build_exposure_lab(
            key_levels=self.levels, benchmark_data=self.benchmarks, as_of='2026-08-11')
        self.assertEqual(lab['hypotheses'], [])
        self.assertNotIn('00685L', lab['products'])
        self.assertNotIn('00685L', ' '.join(lab['warnings']))
        self.assertIsNone(lab['selectedResearchCeilingPct'])
        self.assertIsNotNone(lab['temperature']['score'])
        self.assertEqual(
            [row['key'] for row in lab['temperature']['components']],
            ['volatility', 'margin', 'leverage', 'portfolio'])
        self.assertEqual(lab['temperature']['components'][-1]['tone'], 'unknown')

    def test_exposure_pressure_uses_professional_market_terms(self):
        self.assertEqual(exposure_lab._temperature_band(20), ('cool', '偏低'))
        self.assertEqual(exposure_lab._temperature_band(45), ('steady', '中性'))
        self.assertEqual(exposure_lab._temperature_band(70), ('watch', '偏高'))
        self.assertEqual(exposure_lab._temperature_band(85), ('hot', '過熱'))

    def test_actual_00685l_holding_enables_unverified_thesis_without_credit(self):
        lab = exposure_lab.build_exposure_lab(
            key_levels=self.levels, benchmark_data=self.benchmarks, as_of='2026-08-11',
            portfolio={
                'kind': 'actual', 'available': True,
                'stocks': {'00685L': {'weight': 100}},
            })
        hypothesis = lab['hypotheses'][0]
        self.assertEqual(hypothesis['symbol'], '00685L')
        self.assertEqual(hypothesis['status'], 'UNVERIFIED')
        self.assertEqual(hypothesis['scope'], 'actual_portfolio_only')
        self.assertFalse(hypothesis['diversificationCredit'])
        self.assertIn('成交值', hypothesis['confirmationRule'])
        self.assertIn('00685L', lab['products'])

    def test_observation_pool_does_not_enable_personal_hypothesis(self):
        lab = exposure_lab.build_exposure_lab(
            key_levels=self.levels, benchmark_data=self.benchmarks,
            portfolio={
                'kind': 'observation_pool', 'available': True,
                'stocks': {'00685L': {'weight': 100}},
            })
        self.assertEqual(lab['hypotheses'], [])
        self.assertNotIn('00685L', lab['products'])

    def test_margin_and_anchor_health_can_only_add_review_not_mutate_core(self):
        profile = {'maxLeverage': 2.0}
        normal = exposure_lab.build_exposure_lab(
            key_levels=self.levels, benchmark_data=self.benchmarks, risk_profile=profile,
            margin_state={'available': True, 'percentile52w': 40, 'direction': 'flat'},
            research_inputs={'currentTsmcPrice': 2395})
        stressed = exposure_lab.build_exposure_lab(
            key_levels=self.levels, benchmark_data=self.benchmarks, risk_profile=profile,
            margin_state={'available': True, 'percentile52w': 95, 'direction': 'rising'},
            research_inputs={'currentTsmcPrice': 3000})
        self.assertEqual(normal['riskMode'], 'aggressive')
        self.assertEqual(stressed['selectedResearchCeilingPct'], normal['selectedResearchCeilingPct'])
        self.assertEqual(stressed['coreResearch']['assumptionFingerprint'],
                         normal['coreResearch']['assumptionFingerprint'])
        self.assertTrue(stressed['weeklyHealth']['reviewRequired'])
        self.assertIn('margin_elevated_and_rising', stressed['weeklyHealth']['flags'])
        self.assertIn('core_anchor_move', stressed['weeklyHealth']['flags'])

    def test_selected_taiwan50_never_borrows_taiex_volatility(self):
        low_taiex = {**self.levels, 'volatility': {
            'stateDownside20AnnualPct': 4.0, 'horizonForecastAnnualPct': 6.0}}
        high_taiex = {**self.levels, 'volatility': {
            'stateDownside20AnnualPct': 80.0, 'horizonForecastAnnualPct': 90.0}}
        left = exposure_lab.build_exposure_lab(
            key_levels=low_taiex, benchmark_data=self.benchmarks,
            risk_profile={'maxLeverage': 2.0})
        right = exposure_lab.build_exposure_lab(
            key_levels=high_taiex, benchmark_data=self.benchmarks,
            risk_profile={'maxLeverage': 2.0})
        self.assertEqual(left['selectedBenchmarkId'], 'FTSE_TAIWAN_50')
        self.assertEqual(left['selectedResearchCeilingPct'], right['selectedResearchCeilingPct'])
        self.assertEqual(left['volatility']['benchmarkId'], 'FTSE_TAIWAN_50')

    def test_missing_taiwan50_fails_closed_instead_of_using_taiex(self):
        lab = exposure_lab.build_exposure_lab(
            key_levels=self.levels, benchmark_data={}, risk_profile={'maxLeverage': 2.0})
        self.assertEqual(lab['selectedBenchmarkId'], 'FTSE_TAIWAN_50')
        self.assertEqual(lab['benchmarks']['FTSE_TAIWAN_50']['status'], 'RESEARCH_DATA_INCOMPLETE')
        self.assertIsNone(lab['selectedResearchCeilingPct'])
        self.assertIsNone((lab['volatility']['horizonForecastAnnualPct'] or {}).get('value'))

    def test_mixed_underlyings_do_not_publish_a_fake_blended_volatility(self):
        lab = exposure_lab.build_exposure_lab(
            key_levels=self.levels, benchmark_data=self.benchmarks,
            risk_profile={'maxLeverage': 2.0},
            portfolio={
                'kind': 'actual', 'available': True,
                'stocks': {'00631L': {'weight': 60}, '00685L': {'weight': 40}},
            })
        self.assertEqual(lab['selectedBenchmarkId'], 'MIXED')
        self.assertEqual(lab['volatility']['benchmarkId'], 'MIXED')
        self.assertEqual(lab['volatility']['status'], 'mixed_no_aggregate')
        self.assertIsNone(lab['volatility']['horizonForecastAnnualPct']['value'])
        self.assertIsNotNone(lab['volatility']['stateToForecastRatio'])

    def test_cost_adjusted_kelly_formula_does_not_double_count_risk_free_rate(self):
        rows = exposure_lab._mode_ceilings(20.0, 25.0, 2.3, False)
        expected_lambda_pct = (0.5 + (0.20 - 0.023) / (0.25 ** 2)) * 100.0
        self.assertAlmostEqual(rows['aggressive']['costAdjustedKellyPct'], expected_lambda_pct, places=1)
        self.assertIn('g-c_incremental', rows['aggressive']['formula'])
        self.assertTrue(all(not row['weeklyHealthApplied'] for row in rows.values()))

    def test_unadjusted_product_history_never_claims_empirical_cost_gap(self):
        underlying = benchmark_contract(days=150)
        product_rows = []
        product_level = 100.0
        for index, row in enumerate(underlying['rows']):
            if index:
                prev = underlying['rows'][index - 1]['totalReturnIndex']
                ret = row['totalReturnIndex'] / prev - 1.0
                product_level *= 1.0 + 2.0 * ret - 0.0001
            product_rows.append({'date': row['date'], 'close': product_level})
        metrics = exposure_lab._daily_leverage_metrics(
            {'rows': product_rows, 'returnBasis': 'price_close_unadjusted'},
            underlying, 2.0)
        self.assertIsNotNone(metrics['rollingBeta'])
        self.assertIsNotNone(metrics['trackingResidualAnnualPct'])
        self.assertIsNone(metrics['empiricalCostGapAnnualPct'])
        self.assertEqual(metrics['quality'], 'tracking_only_unadjusted_product')


if __name__ == '__main__':
    unittest.main()
