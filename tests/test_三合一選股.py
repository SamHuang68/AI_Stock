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


class CanonicalWriterTests(unittest.TestCase):
    def test_concurrent_owner_prevents_read_modify_write(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'chip_history'
            target.mkdir()
            path = target / '20260911.json'
            original = json.dumps({'5347': {'trust': 10}})
            path.write_text(original, encoding='utf-8')
            handle = tracker.acquire_daemon_lock('chip-2026-09-11', lock_dir=Path(directory) / 'runtime_locks')
            self.assertIsNotNone(handle)
            try:
                with self.assertRaisesRegex(RuntimeError, '本次保留原檔未寫入'):
                    tracker.record_rows(DAYS[-1], {'2330': {'sourceDate': DAYS[-1], 'trust': 1}}, directory=target)
                self.assertEqual(path.read_text(encoding='utf-8'), original)
            finally:
                tracker.release_daemon_lock(handle)

    def test_merge_uses_source_day_preserves_other_rows_and_keeps_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '20260911.json'
            path.write_text(json.dumps({'5347': {'trust': 10}}), encoding='utf-8')
            row = {'sourceDate': DAYS[-1], 'trust': 0, 'foreign': -5, 'source': 'TWSE T86'}
            self.assertEqual(tracker.record_rows(DAYS[-1], {'2330': row}, directory=directory), 1)
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved['5347'], {'trust': 10})
            self.assertEqual(saved['2330']['sourceDate'], DAYS[-1])
            self.assertEqual(tracker.record_rows(DAYS[-1], {'2330': row}, directory=directory), 0)
            self.assertEqual(tracker.record_rows(DAYS[-2], {'2330': row}, directory=directory), 0)
            self.assertFalse((Path(directory) / '20260910.json').exists())

    def test_t86_mismatched_date_is_not_accepted(self):
        chip_api._SNAP.clear()
        data = {'stat': 'OK', 'date': '20260910', 'fields': ['證券代號'], 'data': [['2330']]}
        with mock.patch.object(chip_api, '_fetch_json', return_value=data):
            self.assertIsNone(chip_api.snap_t86('20260911'))

    def test_tpex_preserves_its_own_date_and_legitimate_zero(self):
        chip_api._SNAP.clear()
        data = [{'Date': '1150910', 'SecuritiesCompanyCode': '5347',
                 'ForeignInvestors-Difference': '-5', 'SecuritiesInvestmentTrustCompanies-Difference': '0',
                 'Dealers-Difference': '-2', 'TotalDifference': '-7'}]
        with mock.patch.object(chip_api, '_src_fetch_json', None), mock.patch.object(chip_api, '_fetch_json', return_value=data):
            row = chip_api._tpex_inst('5347')
        self.assertEqual(row['sourceDate'], '2026-09-10')
        self.assertEqual(row['trust'], 0)
        self.assertEqual(row['foreign'], -5)


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
