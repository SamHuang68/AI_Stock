"""官方來源路由、故障恢復與上市分類涵蓋率回歸。"""
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from email.message import Message
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
import sector_flow
import 類股成員 as members
from 台股基本面 import REVENUE_DATASETS, dataset_url

SPEC = importlib.util.spec_from_file_location('st_官方來源測試', ROOT / 'server/server.py')
ST = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ST)


def response(payload, mime='application/json'):
    stream = io.BytesIO(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
    stream.status = 200
    stream.headers = Message()
    stream.headers['Content-Type'] = mime
    return stream


LISTED = [{'公司代號': '2330', '公司名稱': '上市新名稱', '產業別': '半導體業'}]
OTC = [{'公司代號': '6488', '公司名稱': '上櫃新名稱', '產業別': '半導體業'}]


class 官方對照來源測試(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        for attr, value in (('_BASE', folder.name), ('_TW_NAMES', {'date': None, 'map': {}}),
                            ('_TW_SECTORS', {'date': None, 'map': {}})):
            patcher = mock.patch.object(ST, attr, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def reference(self, req, timeout=None):
        if req.full_url == dataset_url(REVENUE_DATASETS[0]):
            return response(LISTED)
        if req.full_url == dataset_url(REVENUE_DATASETS[1]):
            return response(OTC)
        if 'STOCK_DAY_ALL' in req.full_url:
            return response([{'Code': '2330', 'Name': '上市正式簡稱'}])
        if 'tpex_mainboard' in req.full_url:
            return response([{'SecuritiesCompanyCode': '6488', 'CompanyName': '上櫃正式簡稱'}])
        self.fail('不得請求未知或已失效的來源路徑')

    def test_名稱與產業共用既有上市上櫃來源契約(self):
        with mock.patch.object(ST.urllib.request, 'urlopen', side_effect=self.reference) as fetch:
            names = ST._get_tw_names()
            sectors = ST._get_tw_sectors()
        self.assertEqual(names, {'2330': '上市正式簡稱', '6488': '上櫃正式簡稱'})
        self.assertEqual(sectors, {'2330': '半導體業', '6488': '半導體業'})
        urls = [call.args[0].full_url for call in fetch.call_args_list]
        self.assertEqual(urls.count(dataset_url(REVENUE_DATASETS[1])), 2)
        self.assertNotIn('https://openapi.twse.com.tw/v1/opendata/t187ap05_O', urls)
        events = [json.loads(line) for line in (self.root / 'logs/fundamental_trace.jsonl').read_text(encoding='utf-8').splitlines()]
        done = [row for row in events if row['event'] == '對照來源完成']
        self.assertEqual(len(done), 6)
        self.assertTrue(all(row['httpStatus'] == 200 and row['sampleCount'] for row in done))
        self.assertEqual(len({row['correlationId'] for row in done}), 6)

    def test_成功名稱可更新舊同代號但不刪備份其他代號(self):
        (self.root / 'data').mkdir()
        backup = self.root / 'data/tw_names_backup.json'
        backup.write_text(json.dumps({'6488': '過去名稱', '9999': '保留名稱'}), encoding='utf-8')
        with mock.patch.object(ST.urllib.request, 'urlopen', side_effect=self.reference):
            names = ST._get_tw_names()
        self.assertEqual(names['6488'], '上櫃正式簡稱')
        self.assertEqual(names['9999'], '保留名稱')
        self.assertEqual(json.loads(backup.read_text(encoding='utf-8')), names)

    def test_任一市場失敗不能快取整天且同日恢復(self):
        for failed_source in REVENUE_DATASETS:
            with self.subTest(source=failed_source):
                ST._TW_SECTORS = {'date': None, 'map': {'9999': '保留分類'}}
                def partial(req, timeout=None):
                    if req.full_url == dataset_url(failed_source):
                        raise TimeoutError('受控來源逾時')
                    return self.reference(req, timeout)
                with mock.patch.object(ST.time, 'monotonic', return_value=100), mock.patch.object(
                        ST.urllib.request, 'urlopen', side_effect=partial) as fetch:
                    first = ST._get_tw_sectors()
                    self.assertIsNone(ST._TW_SECTORS['date'])
                    self.assertEqual(ST._get_tw_sectors(), first)
                    self.assertEqual(fetch.call_count, 2)
                with mock.patch.object(ST.time, 'monotonic', return_value=161), mock.patch.object(
                        ST.urllib.request, 'urlopen', side_effect=self.reference):
                    recovered = ST._get_tw_sectors()
                self.assertEqual(set(recovered), {'2330', '6488', '9999'})
                self.assertIsNotNone(ST._TW_SECTORS['date'])

    def test_所有名稱來源失敗仍保留備份且可重試(self):
        (self.root / 'data').mkdir()
        (self.root / 'data/tw_names_backup.json').write_text('{"6488":"保留名稱"}', encoding='utf-8')
        with mock.patch.object(ST.time, 'monotonic', return_value=100), mock.patch.object(
                ST.urllib.request, 'urlopen', side_effect=TimeoutError):
            self.assertEqual(ST._get_tw_names(), {'6488': '保留名稱'})
            self.assertIsNone(ST._TW_NAMES['date'])
        with mock.patch.object(ST.time, 'monotonic', return_value=161), mock.patch.object(
                ST.urllib.request, 'urlopen', side_effect=self.reference):
            self.assertEqual(ST._get_tw_names()['6488'], '上櫃正式簡稱')

    def test_名稱來源失敗首輪仍保留記憶體且拒收錯誤備份型別(self):
        (self.root / 'data').mkdir()
        backup = self.root / 'data/tw_names_backup.json'
        for payload in (None, ['錯誤陣列'], {'6488': '磁碟舊名稱', '2330': 123, '2885': '有效備份'}):
            with self.subTest(payload=payload):
                ST._TW_NAMES = {'date': None, 'map': {'6488': '記憶體名稱'}}
                if payload is None:
                    backup.unlink(missing_ok=True)
                else:
                    backup.write_text(json.dumps(payload), encoding='utf-8')
                with mock.patch.object(ST.urllib.request, 'urlopen', side_effect=TimeoutError):
                    result = ST._get_tw_names()
                self.assertEqual(result['6488'], '記憶體名稱')
                self.assertNotIn('2330', result)
                self.assertIsNone(ST._TW_NAMES['date'])

    def test_HTTP成功但HTML或錯誤JSON不算來源成功(self):
        for payload, mime in (('<html>錯誤</html>'.encode(), 'text/html'), ({'error': '失敗'}, 'application/json'),
                              ([], 'application/json'), ([None], 'application/json')):
            with self.subTest(mime=mime, payload=payload), mock.patch.object(
                    ST.urllib.request, 'urlopen', return_value=response(payload, mime)), mock.patch.object(ST, '_fundamental_trace') as trace:
                with self.assertRaises(ValueError):
                    ST._fetch_tw_reference_rows(dataset_url(REVENUE_DATASETS[0]), '名稱')
                self.assertEqual(trace.call_args.args[0], '對照來源失敗')
                self.assertEqual(trace.call_args.kwargs['stateAfter'], 'unavailable')


class 上市分類涵蓋測試(unittest.TestCase):
    def snapshot(self, industries, *, missing_change=False, include_rows=True, include_tdr=False):
        listed = [
            {'Code': '2330', 'Name': '上市甲', 'ClosingPrice': '100', 'Change': '1', 'Date': '1150918', 'TradeValue': '600000000'},
            {'Code': '2885', 'Name': '上市乙', 'ClosingPrice': '100', 'Change': '1', 'Date': '1150918', 'TradeValue': '400000000'},
        ]
        if missing_change:
            listed[1]['Change'] = None
        if include_tdr:
            listed.extend({'Code': code, 'Name': name, 'ClosingPrice': '100', 'Change': '1',
                           'Date': '1150918', 'TradeValue': '100000000'}
                          for code, name in (('9103', '美德醫療-DR'), ('9110', '越南控-DR'), ('9136', '巨騰-DR')))
        def fetch(req, timeout=None):
            return response(listed if 'STOCK_DAY_ALL' in req.full_url else [])
        with mock.patch.object(ST.urllib.request, 'urlopen', side_effect=fetch), mock.patch.object(
                ST, '_get_tw_sectors', return_value=industries):
            return ST._fetch_day_movers(include_rows=include_rows)

    def test_缺漲跌的普通股仍計入分類及成交分母(self):
        for include_rows in (True, False):
            with self.subTest(include_rows=include_rows):
                out = self.snapshot({'2330': '半導體業'}, missing_change=True, include_rows=include_rows)
                self.assertEqual(out['classificationTotal'], 2)
                self.assertEqual(out['classificationCoveragePct'], 50)
                self.assertFalse(out['classificationComplete'])
                self.assertEqual(out['industryTurnoverTotalYi'], 10)
                self.assertEqual('rows' in out, include_rows)

    def test_上櫃分類不能冒充上市涵蓋(self):
        out = self.snapshot({'6488': '半導體業'})
        self.assertEqual((out['classificationCount'], out['classificationTotal']), (0, 2))
        self.assertEqual(out['classificationCoveragePct'], 0)
        self.assertFalse(members.build_tw_members(out, '半導體')['ok'])

    def test_缺分類仍保留成交分母且不判定完整資金流(self):
        out = self.snapshot({'2330': '半導體業', '6488': '半導體業'})
        self.assertEqual((out['classificationCount'], out['classificationTotal']), (1, 2))
        self.assertEqual(out['industryTurnoverTotalYi'], 10)
        rows = sector_flow.attach_sector_metrics([{'name': '半導體'}, {'name': '金融保險'}, {'name': '電子'}],
                                                 industry_turnover_yi=out['industryTurnoverYi'])
        flow = sector_flow.build_sector_flow(rows, total_turnover_yi=out['industryTurnoverTotalYi'],
                   classification_coverage_pct=out['classificationCoveragePct'], classification_complete=out['classificationComplete'])
        self.assertEqual(flow['rows'][0]['marketSharePct'], 60)
        self.assertEqual(flow['turnoverCoveragePct'], 50)
        self.assertFalse(flow['flowEligible'])
        self.assertIsNone(flow['hhi'])
        view = members.build_tw_members(out, '半導體')
        self.assertEqual(view['count'], 1)
        self.assertIn('分類未完整', view['scopeLabel'])

    def test_完整分類維持總類不重複計算(self):
        out = self.snapshot({'2330': '半導體業', '2885': '金融保險業'})
        rows = sector_flow.attach_sector_metrics([{'name': '半導體'}, {'name': '金融保險'}, {'name': '電子'}],
                                                 industry_turnover_yi=out['industryTurnoverYi'])
        flow = sector_flow.build_sector_flow(rows, total_turnover_yi=out['industryTurnoverTotalYi'],
                   classification_coverage_pct=out['classificationCoveragePct'], classification_complete=out['classificationComplete'])
        self.assertTrue(flow['flowEligible'])
        self.assertEqual(flow['turnoverCoveragePct'], 100)
        self.assertEqual(flow['hhi'], 5200)

    def test_未分類存託憑證保留母體與成交分母且不偽稱完整(self):
        out = self.snapshot({'2330': '半導體業', '2885': '金融保險業'}, include_tdr=True)
        self.assertEqual({row['code'] for row in out['rows']}, {'2330', '2885', '9103', '9110', '9136'})
        self.assertEqual((out['classificationCount'], out['classificationTotal']), (2, 5))
        self.assertEqual(out['classificationCoveragePct'], 40)
        self.assertFalse(out['classificationComplete'])
        self.assertEqual(out['industryTurnoverTotalYi'], 13)
        self.assertEqual(sum(out['industryTurnoverYi'].values()), 10)
        self.assertIn('四碼證券（含存託憑證）', out['limitNote'])
        rows = sector_flow.attach_sector_metrics([{'name': '半導體'}, {'name': '金融保險'}, {'name': '電子'}],
                                                 industry_turnover_yi=out['industryTurnoverYi'])
        flow = sector_flow.build_sector_flow(rows, total_turnover_yi=out['industryTurnoverTotalYi'],
                   classification_coverage_pct=out['classificationCoveragePct'], classification_complete=out['classificationComplete'])
        self.assertEqual(flow['turnoverScope'], 'TWSE_FOUR_DIGIT_SECURITIES_BY_INDUSTRY')
        self.assertEqual(flow['turnoverCoveragePct'], 40)
        self.assertEqual(flow['rows'][0]['marketSharePct'], round(6 / 13 * 100, 3))
        self.assertFalse(flow['flowEligible'])
        self.assertIsNone(flow['hhi'])
        self.assertIsNone(flow['top3SharePct'])
        view = members.build_tw_members(out, '半導體')
        self.assertEqual([row['code'] for row in view['rows']], ['2330'])
        self.assertIn('分類母體為上市四碼證券，含存託憑證', view['scopeLabel'])
        self.assertIn('分類未完整', view['scopeLabel'])


class 選股交易所尾碼測試(unittest.TestCase):
    def test_兩個正式選股入口保留Yahoo上櫃尾碼且資料庫查裸代號(self):
        import datastore

        class 同步執行器:
            def submit(self, fn, *args, **kwargs):
                future = Future()
                try:
                    future.set_result(fn(*args, **kwargs))
                except Exception as error:
                    future.set_exception(error)
                return future

        for method in ('_handle_screener_post', '_handle_screen3'):
            with self.subTest(method=method):
                handler = SimpleNamespace(_ok=mock.Mock(), _TW_TOP200=[], _err=mock.Mock())
                body = {'symbols': ['6488.TWO', '6488', '2330.TW'], 'sector': '半導體業'}
                with mock.patch.object(ST, 'read_json_body', return_value=body), mock.patch.object(
                        ST, '_get_tw_universe', return_value=[]), mock.patch.object(
                        ST, '_get_tw_sectors', return_value={'6488': '半導體業', '2330': '半導體業'}), mock.patch.object(
                        ST, '_pool', 同步執行器()), mock.patch.object(
                        ST, 'fetch_one', side_effect=lambda symbol, **kwargs: (symbol, None, False)) as fetch, mock.patch.object(
                        datastore, 'get_bars_bulk', return_value={}) as read, mock.patch.object(
                        ST.urllib.request, 'urlopen', side_effect=AssertionError('不得連線至正式來源')):
                    getattr(ST.Handler, method)(handler)
                self.assertEqual(sorted(call.args[0] for call in fetch.call_args_list), ['2330.TW', '6488.TW', '6488.TWO'])
                if method == '_handle_screener_post':
                    self.assertEqual(sorted(read.call_args.args[0]), ['2330', '6488', '6488'])
                handler._err.assert_not_called()
                handler._ok.assert_called_once()


class 籌碼市場快取測試(unittest.TestCase):
    def capture(self, first_symbol):
        import chip_api
        import tdcc_holders

        store, outputs, lookups = {}, [], []
        cache = SimpleNamespace(get=store.get, set=lambda key, value, **kwargs: store.__setitem__(key, value))
        handler = SimpleNamespace(_ok=lambda value: outputs.append(json.loads(value)))

        def otc(code):
            lookups.append(code)
            return {'foreignNet': 123, '_chipSource': 'TPEx'} if code == '6488' else None

        with ExitStack() as stack:
            stack.enter_context(mock.patch.object(ST, '_cache', cache))
            stack.enter_context(mock.patch.object(chip_api, 'resolve_t86_date', return_value=('20260918', {})))
            stack.enter_context(mock.patch.object(chip_api, '_tpex_inst', side_effect=otc))
            for name in ('snap_margn', 'snap_twt72u', 'snap_twtb4u'):
                stack.enter_context(mock.patch.object(chip_api, name, return_value={}))
            for name in ('_chip_streak', '_chip_history_record'):
                stack.enter_context(mock.patch.object(chip_api, name, None))
            stack.enter_context(mock.patch.object(tdcc_holders, 'stock_snapshot', return_value={}))
            stack.enter_context(mock.patch.object(ST.urllib.request, 'urlopen', side_effect=AssertionError('不得連線至正式來源')))
            ST.Handler._handle_chip(handler, first_symbol)
            ST.Handler._handle_chip(handler, '6488')
        return store, outputs, lookups

    def test_上櫃與裸碼共用正確來源及快取(self):
        store, outputs, lookups = self.capture('6488.TWO')
        self.assertEqual(lookups, ['6488'])
        self.assertEqual(len(store), 1)
        self.assertTrue(next(iter(store)).startswith('chip:6488:'))
        self.assertEqual(len(outputs), 2)
        self.assertTrue(all(row['inst']['foreignNet'] == 123 for row in outputs))

    def test_重複尾碼不污染合法裸碼快取(self):
        store, outputs, lookups = self.capture('6488.TW.TWO')
        self.assertEqual(lookups, ['6488'])
        self.assertEqual(len(store), 2)
        self.assertIsNone(outputs[0]['inst'])
        self.assertEqual(outputs[1]['inst']['foreignNet'], 123)


if __name__ == '__main__':
    unittest.main()
