"""估值範圍、資料日期、區間與稀疏籌碼的行為驗證。"""
from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import 估值趨勢 as research


def daily_bars(count=110):
    day = datetime(2026, 9, 9, 13, 30, tzinfo=research.TZ_TPE)
    dates = []
    while len(dates) < count:
        if day.weekday() < 5:
            dates.append(day)
        day -= timedelta(days=1)
    return [{'date': day.date().isoformat(), 'close': 99.0, 'high': 100.0, 'low': 90.0, 'volume': 1000.0}
            for day in reversed(dates)]


def quote_payload(code, bars=None):
    bars = daily_bars() if bars is None else bars
    return json.dumps({'chart': {'result': [{
        'meta': {'symbol': code},
        'timestamp': [datetime.fromisoformat(bar['date']).replace(tzinfo=research.TZ_TPE).timestamp() for bar in bars],
        'indicators': {'quote': [{key: [bar.get(key) for bar in bars] for key in ('close', 'high', 'low', 'volume')}]},
    }]}}).encode()


class ScopeTests(unittest.TestCase):
    def test_positive_pe_has_no_twenty_lower_bound(self):
        settings = research.validate_settings({})
        self.assertIsNone(research.scope_reason('2330', 10, settings))
        self.assertIsNone(research.scope_reason('2330', 30, settings))
        self.assertEqual(research.scope_reason('2330', 30.01, settings), 'excludedPeAbove')

    def test_invalid_or_nonpositive_pe_is_not_eligible(self):
        for raw in (None, '', '-', 0, -1, 'NaN', 'Infinity', True):
            with self.subTest(raw=raw):
                self.assertEqual(research.scope_reason('2330', research.number(raw), research.validate_settings({})),
                                 'excludedPeInvalid')

    def test_user_settings_are_finite_and_bounded(self):
        for value in (None, 0, -1, 201, 'NaN', 'Infinity', True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                research.validate_settings({'peMax': value})
        self.assertEqual(research.validate_settings({'peMax': 40})['peMax'], 40)
        self.assertIsNone(research.scope_reason('2330', 0.2, research.validate_settings({'peMax': 0.5})))

    def test_only_explicit_ip_examples_are_excluded(self):
        for code in ('3529', '6643'):
            self.assertEqual(research.scope_reason(code, 25, research.validate_settings({})), 'excludedIp')
            self.assertIsNone(research.scope_reason(code, 25, research.validate_settings({'excludeIp': False})))
        self.assertIsNone(research.scope_reason('6669', 25, research.validate_settings({})))
        self.assertEqual(research.scope_reason('00631L', 20, research.validate_settings({})), 'excludedNonStock')

    def test_tpex_alias_and_missing_date_are_preserved(self):
        row = research.parse_valuation({'PriceEarningRatio': '24.5', 'Yield': '0'}, research.PE_DATASETS[1])
        self.assertEqual(row['per'], 24.5)
        self.assertEqual(row['yield'], 0)
        self.assertEqual(row['valuationSource'], 'TPEx peratio')
        self.assertIsNone(row['valuationDate'])
        self.assertNotIn('epsTtm', row)

    def test_source_dates_support_roc_without_inventing_today(self):
        for raw in ('1150909', '20260909', '115/09/09', '2026-09-09'):
            self.assertEqual(research.source_date(raw), '2026-09-09')
        for raw in ('', None, '20260231', '202609'):
            self.assertIsNone(research.source_date(raw))

    def test_latest_revenue_retains_single_month_basis(self):
        row = research.parse_revenue({'資料年月': '11508', '營業收入-去年同月增減(%)': '5.6',
                                     '營業收入-上月比較增減(%)': '-3', '累計營業收入-前期比較增減(%)': '1'})
        self.assertEqual(row, {'revenuePeriod': '11508', 'revYoy': 5.6, 'revenueMom': -3, 'revenueCumYoy': 1})


class PriceTests(unittest.TestCase):
    def test_range_excludes_current_candle(self):
        bars = daily_bars()
        bars[-1].update(close=105, high=110, low=89, volume=1600)
        result = research.price_observation(bars)
        self.assertEqual((result['rangeTop'], result['rangeBottom']), (100, 90))
        self.assertEqual(result['rangePosition'], '帶量越過')
        self.assertEqual(result['distanceToTopPct'], -5)
        self.assertEqual(result['breakoutVolumeRatio'], 1.6)

    def test_missing_volume_does_not_confirm_breakout(self):
        bars = daily_bars()
        bars[-1]['close'] = 105
        bars[-1]['volume'] = None
        self.assertEqual(research.price_observation(bars)['rangePosition'], '越過但量未確認')

    def test_high_five_day_volume_does_not_confirm_low_volume_breakout(self):
        bars = daily_bars()
        for bar in bars[-5:-1]:
            bar['volume'] = 10000
        bars[-1].update(close=105, volume=500)
        legacy_ratio = (sum(bar['volume'] for bar in bars[-5:]) / 5) / (sum(bar['volume'] for bar in bars[-20:]) / 20)
        self.assertGreater(legacy_ratio, 1.5)
        result = research.price_observation(bars)
        self.assertLess(result['breakoutVolumeRatio'], 1)
        self.assertEqual(result['rangePosition'], '越過但量未確認')

    def test_short_history_has_no_hundred_session_claim(self):
        result = research.price_observation(daily_bars(99))
        self.assertIsNone(result['drawdown100'])
        self.assertEqual(result['rangePosition'], '接近上緣')

    def test_missing_high_does_not_synthesize_range(self):
        bars = daily_bars()
        bars[-2]['high'] = None
        self.assertIsNone(research.price_observation(bars)['rangeTop'])

    def test_current_unfinished_session_is_excluded(self):
        bars = daily_bars()
        payload = json.loads(quote_payload('2330.TW', bars))
        observed, _ = research.completed_bars(payload, datetime(2026, 9, 9, 12, 0, tzinfo=research.TZ_TPE))
        self.assertEqual(observed[-1]['date'], '2026-09-08')


class ChipTests(unittest.TestCase):
    def setUp(self):
        self.days = [bar['date'] for bar in daily_bars(5)]

    def test_missing_middle_day_is_unknown_not_continuous_buy(self):
        snapshots = {day: {'2330': {'trust': 100, 'tradingDate': day}} for day in self.days}
        snapshots[self.days[2]] = {'6669': {'trust': 100, 'tradingDate': self.days[2]}}
        result = research.chip_observation('2330', self.days, snapshots)
        self.assertEqual(result['trustObservedDays'], 4)
        self.assertIsNone(result['trustStreak'])
        self.assertIsNone(result['trustNet5d'])
        self.assertEqual(result['trustLatestShares'], 100)

    def test_zero_is_valid_and_stops_streak(self):
        snapshots = {day: {'2330': {'trust': 100, 'tradingDate': day}} for day in self.days}
        snapshots[self.days[-1]]['2330']['trust'] = 0
        result = research.chip_observation('2330', self.days, snapshots)
        self.assertEqual(result['trustObservedDays'], 5)
        self.assertEqual(result['trustNet5d'], 400)
        self.assertEqual(result['trustStreak'], 0)

    def test_older_observation_keeps_its_actual_date(self):
        old = '2026-08-01'
        result = research.chip_observation('2330', self.days, {old: {'2330': {'trust': 50, 'sourceDate': old}}})
        self.assertEqual(result['trustAsOf'], old)
        self.assertEqual(result['trustObservedDays'], 0)
        self.assertIsNone(result['trustNet5d'])

    def test_five_undated_snapshots_are_not_five_trading_days(self):
        snapshots = {day: {'2330': {'trust': 100, 'foreign': 200}} for day in self.days}
        result = research.chip_observation('2330', self.days, snapshots)
        self.assertEqual(result['trustObservedDays'], 0)
        self.assertIsNone(result['trustLatestShares'])
        self.assertIsNone(result['trustAsOf'])
        self.assertIsNone(result['trustNet5d'])
        self.assertIsNone(result['trustStreak'])
        self.assertIsNone(result['foreignStreak'])
        self.assertEqual(result['chipDateIssue'], '既有籌碼快照未保存來源交易日')

    def test_repeated_trade_date_does_not_become_five_days(self):
        snapshots = {day: {'2330': {'trust': 100, 'tradingDate': self.days[0]}} for day in self.days}
        result = research.chip_observation('2330', self.days, snapshots)
        self.assertEqual(result['trustObservedDays'], 1)
        self.assertEqual(result['trustAsOf'], self.days[0])
        self.assertIsNone(result['trustNet5d'])
        self.assertIsNone(result['trustStreak'])

    def test_conflicting_source_dates_are_rejected(self):
        snapshots = {day: {'2330': {'trust': 100, 'tradingDate': day, 'sourceDate': '2026-01-01'}}
                     for day in self.days}
        result = research.chip_observation('2330', self.days, snapshots)
        self.assertEqual(result['trustObservedDays'], 0)
        self.assertIsNone(result['trustLatestShares'])
        self.assertEqual(result['chipDateIssue'], '籌碼快照來源交易日不一致')


class IntegrationTests(unittest.TestCase):
    def run_fixture(self, symbols, values, *, detail=False, quote_failure=False):
        fetched = []
        def lookup(datasets, code):
            if datasets[0] == research.PE_DATASETS[0]:
                return {'PEratio': values.get(code), 'Date': '20260909'}
            if datasets[0] == research.REVENUE_DATASETS[0]:
                return {'資料年月': '11508', '去年同月增減': 3}
            return None
        def fetch(code, **kwargs):
            fetched.append(code)
            if quote_failure:
                raise RuntimeError('測試價格來源暫時無資料')
            return code, quote_payload(code), False
        with tempfile.TemporaryDirectory() as directory, ThreadPoolExecutor(max_workers=2) as pool:
            result = research.run_screen(
                {}, settings=research.validate_settings({}), symbols=symbols, universe_source='測試清單',
                lookup=lookup, monthly_revenue=lambda *_: None, names={}, fetch_quote=fetch,
                calc_ind=lambda c, h, l, v: {'close': c[-1], 'changePct': 0, 'volRatio': 1, 'rsi14': 50},
                tech_match=lambda *_: True, pool=pool, chip_history_path=directory,
                now=datetime(2026, 9, 10, tzinfo=research.TZ_TPE), detail=detail,
            )
        return result, fetched

    def test_valuation_prescreen_prevents_out_of_scope_quote_fetch(self):
        result, fetched = self.run_fixture(['2330', '3529', '6669', '00631L', '2408'],
                                           {'2330': 10, '3529': 25, '6669': 60, '2408': -2})
        self.assertEqual(fetched, ['2330.TW'])
        self.assertEqual(result['matched'], 1)
        self.assertEqual(result['researchMeta']['excludedIp'], 1)
        self.assertEqual(result['researchMeta']['excludedPeAbove'], 1)
        self.assertEqual(result['researchMeta']['excludedPeInvalid'], 1)
        self.assertEqual(result['researchMeta']['excludedNonStock'], 1)
        self.assertIsNone(result['results'][0]['trustStreak'])

    def test_detail_keeps_excluded_ip_and_partial_fundamental(self):
        result, _ = self.run_fixture(['3529'], {'3529': 110}, detail=True, quote_failure=True)
        row = result['results'][0]
        self.assertIsNone(row['close'])
        self.assertEqual(row['per'], 110)
        self.assertEqual(row['revYoy'], 3)
        self.assertFalse(row['research']['scopeEligible'])
        self.assertEqual(row['research']['valuationModel'], '另案估值')
        self.assertEqual(result['researchMeta']['valuationPassed'], 0)
        self.assertEqual(result['techPass'], 0)

    def test_result_cap_retains_exact_match_count(self):
        symbols = [str(code) for code in range(2000, 2085)]
        result, fetched = self.run_fixture(symbols, {code: 15 for code in symbols})
        self.assertEqual(len(fetched), 85)
        self.assertEqual(result['matched'], 85)
        self.assertEqual(len(result['results']), 80)
        self.assertTrue(result['researchMeta']['truncated'])

    def test_disabled_mode_dispatch_keeps_existing_contract(self):
        tree = ast.parse((ROOT / 'server' / 'server.py').read_text(encoding='utf-8'))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == '_handle_screen3')
        namespace = {'read_json_body': lambda *_args, **_kwargs: {'research': {'enabled': False}},
                     'json': json, '_get_tw_universe': lambda: [], 'as_completed': lambda _: []}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<選股端點>', 'exec'), namespace)
        instance = mock.Mock(_TW_TOP200=[])
        namespace['_handle_screen3'](instance)
        instance._handle_screen3_research.assert_not_called()
        output = json.loads(instance._ok.call_args.args[0])
        self.assertEqual(output, {'results': [], 'scanned': 0, 'techPass': 0, 'matched': 0})


if __name__ == '__main__':
    unittest.main()
