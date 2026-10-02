"""驗證未設篩選仍回傳觀察值，以及籌碼日期、缺值與零值的差別。"""
import ast
import json
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import 三合一選股 as fields
import chip_api
import chip_history_tracker as tracker

DAYS = [f'2026-09-{n:02d}' for n in (1, 2, 3, 4, 7, 8, 9, 10, 11)]


def snapshots(values, days=DAYS):
    return {day: {'2330': {'sourceDate': day, 'trust': value, 'foreign': value}}
            for day, value in zip(days, values)}


class ObservationTests(unittest.TestCase):
    def test_invalid_or_conflicting_valuation_dates_fail_closed(self):
        for dates in ({'Date':'not-a-date'}, {'Date':'1150911','日期':'1150910'}, {'Date':'1150911','日期':'錯誤'}):
            with self.subTest(dates=dates):
                row = fields.parse_valuation({**dates,'PEratio':'15','DividendYield':'5'}, fields.PE_DATASETS[0])
                self.assertIsNone(row['per'])
                self.assertIsNone(row['yield'])
                self.assertFalse(fields.matches(row, {'perMax':20,'yieldMin':3}, {}))
        self.assertEqual(fields.parse_valuation({'PEratio':'15'}, fields.PE_DATASETS[0])['per'], 15)

    def enrich(self, code='5347', *, per='18.5', yoy='0', yield_value='0'):
        def lookup(datasets, code):
            if datasets[0] == fields.PE_DATASETS[1]:
                return {'PriceEarningRatio': per, 'YieldRatio': yield_value, 'Date': '1150911'}
            if fields.REVENUE_DATASETS[1] in datasets:
                return {'營業收入-去年同月增減(%)': yoy, '資料年月': '11508'}
        return fields.enrich({'sym': code}, lookup=lookup, monthly_revenue=lambda *_: None,
                             sessions=DAYS, snapshots={})

    def test_default_results_have_all_fields_and_preserve_legitimate_zero(self):
        row = self.enrich()
        self.assertTrue(all(key in row for key in fields.FIELDS))
        self.assertEqual((row['revYoy'], row['per'], row['yield']), (0, 18.5, 0))
        self.assertEqual(row['valuationDate'], '2026-09-11')
        self.assertEqual(row['revenuePeriod'], '11508')
        self.assertTrue(fields.matches(row, {}, {}))
        self.assertTrue(fields.matches(row, {'revYoyMin': 0, 'yieldMin': 0}, {}))
        self.assertFalse(fields.matches(row, {}, {'trustBuyDays': 0}))

    def test_missing_data_is_retained_without_filters_but_fails_selected_filter(self):
        row = self.enrich(per='NaN', yoy='', yield_value='Infinity')
        self.assertTrue(fields.matches(row, {}, {}))
        self.assertFalse(fields.matches(row, {'perMax': 30}, {}))
        self.assertIsNone(row['revYoy'])
        self.assertIsNone(row['yield'])
        json.dumps(row, allow_nan=False)
        self.assertIsNone(self.enrich(per='-1')['per'])

    def test_etf_remains_a_technical_result_without_company_valuation(self):
        lookup = mock.Mock(side_effect=AssertionError('ETF 不查公司基本面'))
        row = fields.enrich({'sym': '00631L'}, lookup=lookup, monthly_revenue=lookup,
                            sessions=DAYS, snapshots={})
        self.assertTrue(fields.matches(row, {}, {}))
        self.assertIn('不適用', row['fieldStatus']['revYoy'])

    def test_mops_fallback_uses_existing_otc_pipeline(self):
        fallback = mock.Mock(return_value={'yoyPct': 12.3, 'period': '11508'})
        def lookup(datasets, _):
            return {'PriceEarningRatio': 15} if datasets == [fields.PE_DATASETS[1]] else None
        row = fields.enrich({'sym': '5347'}, lookup=lookup, monthly_revenue=fallback,
                            sessions=DAYS, snapshots={})
        self.assertEqual(row['revYoy'], 12.3)
        fallback.assert_called_once_with('otc', '5347')


class ChipDaysTests(unittest.TestCase):
    def test_seven_day_streak_is_not_capped_at_five(self):
        result = fields.chip_fields('2330', DAYS, snapshots([-1, -1, 1, 1, 1, 1, 1, 1, 1]))
        self.assertEqual(result['trustStreak'], 7)
        self.assertTrue(result['trustStreakComplete'])

    def test_missing_day_stops_count_and_marks_lower_bound(self):
        data = snapshots([1] * 9)
        del data[DAYS[-3]]
        result = fields.chip_fields('2330', DAYS, data)
        self.assertEqual(result['trustStreak'], 2)
        self.assertFalse(result['trustStreakComplete'])

    def test_negative_lower_bound_cannot_prove_minimum_filter(self):
        row = fields.chip_fields('2330', DAYS, snapshots([None] * 7 + [-1, -1]))
        self.assertEqual(row['trustStreak'], -2)
        self.assertFalse(fields.matches(row, {}, {'trustBuyDays': -3}))
        row['trustStreakComplete'] = True
        self.assertTrue(fields.matches(row, {}, {'trustBuyDays': -3}))

    def test_weekend_copies_do_not_add_days(self):
        data = snapshots([-1] * 8 + [1])
        data['2026-09-12'] = data[DAYS[-1]]
        data['2026-09-13'] = data[DAYS[-1]]
        self.assertEqual(fields.chip_fields('2330', DAYS, data)['trustStreak'], 1)

    def test_stale_undated_conflicting_and_zero_are_distinct(self):
        data = snapshots([1] * 8)
        row = fields.chip_fields('2330', DAYS, data)
        self.assertIsNone(row['trustStreak'])
        self.assertEqual(row['chipAsOf'], DAYS[-2])
        undated = {DAYS[-1]: {'2330': {'trust': 1, 'foreign': 1}}}
        self.assertIn('未保存來源交易日', fields.chip_fields('2330', DAYS, undated)['fieldStatus']['trustStreak'])
        data[DAYS[-1]] = {'2330': {'sourceDate': DAYS[-1], 'trust': 0, 'foreign': 0}}
        self.assertEqual(fields.chip_fields('2330', DAYS, data)['trustStreak'], 0)
        data['2026-09-12'] = {'2330': {'sourceDate': DAYS[-1], 'trust': 99, 'foreign': 99}}
        self.assertIsNone(fields.chip_fields('2330', DAYS, data)['trustStreak'])


class SnapshotReaderTests(unittest.TestCase):
    def test_reader_keeps_source_day_separate_from_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '20260912.json'
            path.write_text(json.dumps({'2330': {'sourceDate': DAYS[-1], 'trust': 0}}), encoding='utf-8')
            (Path(directory) / '20260913.json').write_text('{broken', encoding='utf-8')
            (Path(directory) / 'unknown.json').write_text('{}', encoding='utf-8')
            rows = fields.load_chip_snapshots(directory)
            self.assertEqual(len(rows), 1)
            output = fields.chip_fields('2330', DAYS, rows)
            self.assertEqual(output['chipAsOf'], DAYS[-1])
            self.assertEqual(output['trustStreak'], 0)
            self.assertIsNone(output['foreignStreak'])

    def test_conflicting_invalid_date_is_not_ignored(self):
        rows = snapshots([1] * 9)
        rows[DAYS[-1]]['2330']['tradeDate'] = 'not-a-date'
        self.assertIsNone(fields.chip_fields('2330', DAYS, rows)['trustStreak'])

    def test_enrichment_reads_existing_snapshots_without_refreshing_market(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(fields, 'market_sessions', return_value=DAYS), mock.patch.object(tracker, 'parse_and_save') as fetch:
            output = fields.enrich_results([{'sym':'00631L'}], {}, {}, lookup=mock.Mock(), monthly_revenue=mock.Mock(), database='unused', chip_history_path=directory, trace_path=Path(directory)/'trace.jsonl', trace_id='fixture')
            fetch.assert_not_called()
            self.assertEqual(len(output), 1)
            self.assertIsNone(output[0]['trustStreak'])


class HandlerTests(unittest.TestCase):
    def test_no_filters_reaches_enrichment_and_does_not_use_chart_period_start(self):
        tree = ast.parse((ROOT / 'server/server.py').read_text(encoding='utf-8'))
        method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == '_handle_screen3')
        quote = {'chart': {'result': [{'timestamp': list(range(70)), 'meta': {},
                                      'indicators': {'quote': [{'close': [100] * 70}]}}]}}
        with ThreadPoolExecutor(max_workers=1) as pool:
            previous = mock.Mock(return_value=None)
            namespace = {'read_json_body': lambda *_a, **_k: {'symbols': ['2330']}, 'json': json,
                         '_get_tw_universe': lambda: [], '_get_tw_names': lambda: {'2330': '台積電'},
                         '_pool': pool, 'as_completed': as_completed,
                         'fetch_one': lambda *_: ('2330.TW', json.dumps(quote), False), '_yf_prevclose': previous,
                         '_openapi_lookup': mock.Mock(), '_mops_monthly_revenue': mock.Mock(),
                         'CHIP_HISTORY_PATH': '', '_BASE': str(ROOT), 'os': __import__('os')}
            exec(compile(ast.Module(body=[method], type_ignores=[]), '<三合一端點>', 'exec'), namespace)
            instance = mock.Mock()
            instance._calc_ind.return_value = {'close': 100, 'changePct': 0, 'rsi14': 50, 'volRatio': 1}
            with mock.patch.object(fields, 'enrich_results', side_effect=lambda rows, *_a, **_k: [{**r, **dict.fromkeys(fields.FIELDS)} for r in rows]) as enrich:
                namespace['_handle_screen3'](instance)
            output = json.loads(instance._ok.call_args.args[0])
            self.assertEqual(output['matched'], 1)
            self.assertTrue(all(key in output['results'][0] for key in fields.FIELDS))
            self.assertEqual(enrich.call_args.args[1:3], ({}, {}))
            previous.assert_called_once_with({}, allow_chart_prev=False)


if __name__ == '__main__':
    unittest.main()
