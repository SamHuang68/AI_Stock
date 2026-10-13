"""只驗曝險評估的品質、區間與既有保守約束；不讀寫市場資料。"""
import copy
import os
import sys
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
import consensus_attention
import exposure_lab
import margin_cycle
from tests.test_exposure_lab import benchmark_contract


class PressureAssessmentTest(unittest.TestCase):
    def setUp(self):
        self.margin = margin_cycle.margin_balance_state([
            {'date': (date(2026, 8, 13) + timedelta(days=i)).isoformat(), 'margin_amt_k': 1000 + i}
            for i in range(38)])
        self.volatility = {
            'status': 'ready', 'stateDownside20AnnualPct': {'asOf': '2026-10-12'},
            'horizonForecastAnnualPct': {'asOf': '2026-10-12', 'confidence': 'medium'},
            'periods': {'stateStart': '2026-09-14', 'forecastStart': '2025-10-13'},
        }
        self.assumptions = {'asOf': '2026-10-01', 'frozenUntil': '2026-11-01'}
        self.weekly = {'stateToForecastRatio': 0.30, 'marginPercentile52w': 100}
        self.benchmarks = {'FTSE_TAIWAN_50': {'status': 'INDETERMINATE', 'volatility': self.volatility}}

    def assess(self, symbols=None, look=None):
        symbols = symbols or set()
        temp = exposure_lab._exposure_temperature(self.weekly, self.benchmarks, look, symbols, 'FTSE_TAIWAN_50')
        legacy = copy.deepcopy(temp)
        exposure_lab._pressure_assessment(
            temp, margin_state=self.margin, volatility=self.volatility,
            assumptions=self.assumptions, benchmark_rows=list(self.benchmarks.values()),
            actual_symbols=symbols, as_of='2026-10-13T02:00:00Z')
        for key in ('score', 'tone', 'state'):
            self.assertEqual(temp[key], legacy[key], '不得藉資料說明降低既有保守約束')
        return temp

    def sufficient_margin(self):
        self.margin = margin_cycle.margin_balance_state([
            {'date': (date(2025, 10, 13) + timedelta(days=i)).isoformat(), 'margin_amt_k': 1000 + i}
            for i in range(365)])

    def test_short_history_preserves_constraint_without_claiming_complete_score(self):
        temp = self.assess()
        self.assertEqual(temp['score'], 85)
        self.assertEqual(temp['rawWeightedScore'], 48.6)
        self.assertIsNone(temp['compositeScore'])
        self.assertEqual(temp['compositeState'], '資料不足')
        self.assertEqual(temp['quality'], 'incomplete')
        constraint = temp['conservativeConstraint']
        self.assertTrue(constraint['active'])
        self.assertEqual(constraint['floor'], 85)
        self.assertEqual(constraint['drivers'][0]['key'], 'margin')
        self.assertEqual(constraint['drivers'][0]['quality'], 'partial')
        margin = temp['components'][1]
        self.assertIn('38筆', margin['periodLabel'])
        self.assertIn('2026-08-13', margin['periodLabel'])
        self.assertNotIn('52週 100', margin['detail'])

    def test_sufficient_current_inputs_show_mean_separately_from_constraint(self):
        self.sufficient_margin()
        temp = self.assess()
        self.assertEqual(temp['quality'], 'ready')
        self.assertEqual(temp['compositeScore'], 48.6)
        self.assertEqual(temp['conservativeConstraint']['score'], 85)
        self.assertIn('非盤中即時', temp['cadence'])
        self.assertIn('2026-09-14', temp['components'][0]['periodLabel'])

    def test_overdue_monthly_model_is_explicit_and_withholds_composite(self):
        self.sufficient_margin()
        self.assumptions = {'asOf': '2026-08-13', 'frozenUntil': '2026-09-01'}
        temp = self.assess()
        self.assertIsNone(temp['compositeScore'])
        self.assertEqual(temp['components'][2]['quality'], 'review_due')
        self.assertIn('2026-09-01', temp['components'][2]['periodLabel'])

    def test_stale_or_unknown_volatility_keeps_dates_and_blocks_composite(self):
        self.sufficient_margin()
        self.volatility['stateDownside20AnnualPct']['stale'] = True
        temp = self.assess()
        self.assertIsNone(temp['compositeScore'])
        self.assertEqual(temp['components'][0]['quality'], 'partial')
        self.assertIn('2026-10-12', temp['components'][0]['periodLabel'])

    def test_missing_period_cannot_claim_full_year(self):
        self.margin = {'available': True, 'percentile52w': 100, 'samples52w': 220,
                       'asOf': '2026-10-12', 'confidence': 'medium'}
        self.assertIsNone(self.assess()['compositeScore'])

    def test_future_source_date_cannot_be_current_assessment(self):
        self.sufficient_margin()
        self.margin['asOf'] = '2026-10-14'
        temp = self.assess()
        self.assertIsNone(temp['compositeScore'])
        self.assertIn('晚於', temp['components'][1]['qualityNote'])

    def test_portfolio_missing_does_not_claim_personal_exposure(self):
        temp = self.assess()
        self.assertIn('未含實際持倉', temp['scopeLabel'])
        self.assertIsNone(temp['components'][3]['score'])

    def test_radar_keeps_warning_and_labels_constraint_with_quality(self):
        temp = self.assess({'00631L'}, {'effectiveGrossExposurePct': 200})
        result = consensus_attention._owner_exposure_item({
            'portfolioOverlay': {'kind': 'actual', 'available': True},
            'exposureLab': {'temperature': temp}, 'dataQuality': {'completeness': 1}})
        self.assertEqual(result['severity'], 'warning')
        self.assertEqual(result['strength'], 85)
        self.assertIn('約束', result['title'])
        self.assertIn('資料不足', result['insight'])
        self.assertIn('periodLabel', result['components'][1])

    def test_minimum_samples_and_coverage_are_both_required(self):
        for rows in (
            [{'date': (date(2025, 10, 13) + timedelta(days=i*5)).isoformat(), 'margin_amt_k': 100+i}
             for i in range(73)],
            [{'date': (date(2026, 3, 27) + timedelta(days=i)).isoformat(), 'margin_amt_k': 100+i}
             for i in range(200)],
        ):
            state = margin_cycle.margin_balance_state(rows)
            self.assertEqual(state['windowQuality'], 'partial')
            self.assertEqual(state['confidence'], 'low')
        self.sufficient_margin()
        self.assertEqual(self.margin['windowQuality'], 'sufficient')

    def test_real_build_propagates_stale_source_quality(self):
        for marker in ({'quality': 'stale'}, {'quality': 'ready', 'stale': True}):
            contract = benchmark_contract()
            contract.update(marker)
            lab = exposure_lab.build_exposure_lab(
                benchmark_data={'FTSE_TAIWAN_50': contract}, margin_state=self.margin,
                as_of='2026-10-13')
            self.assertTrue(lab['volatility']['stateDownside20AnnualPct']['stale'])
            self.assertEqual(lab['temperature']['components'][0]['quality'], 'partial')
            self.assertIsNone(lab['temperature']['compositeScore'])

    def test_short_volatility_history_uses_actual_window(self):
        for days, count in ((10, 9), (30, 29), (300, 252)):
            lab = exposure_lab.build_exposure_lab(
                benchmark_data={'FTSE_TAIWAN_50': benchmark_contract(days=days)}, as_of='2026-10-13')
            period = lab['temperature']['components'][0]['periodLabel']
            self.assertIn(f'現有{count}筆日報酬', period)
            self.assertNotIn('並參考滾動3年', period)
            self.assertIn(f'短期近{min(20, count)}交易日', period)


if __name__ == '__main__':
    unittest.main()
