"""研究公開邊界：拒絕模糊查詢、保持唯讀與個人資料權限。"""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import 研究整合路由 as routes
import private_web_gateway as gateway


class Handler(routes.ResearchIntegrationRoutesMixin):
    _BASE = str(Path(__file__).resolve().parents[1])
    def __init__(self, path=''):
        self.path = path
        self.status = None
        self.body = None
    def _ok(self, value):
        self.status, self.body = 200, json.loads(value)
    def _err(self, value, status):
        self.status, self.body = status, value
    def _research_runtime(self):
        return {'official': {}, 'names': {}, 'sectors': {}, 'technologySectors': set(), 'chipHistory': ''}
    def _calc_ind(self, *args):
        raise AssertionError('不應觸發技術計算')
    def _screen3_tech(self, *args):
        raise AssertionError('不應觸發技術篩選')


class ResearchBoundaryTests(unittest.TestCase):
    def test_ambiguous_queries_and_dates_are_rejected(self):
        for query in ('?sym=2330&sym=2454', '?sym=', '?refresh=true'):
            with self.subTest(query=query), self.assertRaises(ValueError):
                routes.query_values('/breakout-research' + query, {'sym'})
        for values in ({'sym':'../secret'}, {'asOf':'2026-02-30'}, {'range':'custom'},
                       {'start':'2026-10-02','asOf':'2026-10-01'}, {'refresh':True}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                routes.breakout_options(values)

    def test_query_keeps_exact_dates_and_tw_identity(self):
        symbol, options = routes.breakout_options({'sym':'2330','asOf':'2026-10-02',
                                                  'range':'custom','start':'2026-01-01'})
        self.assertEqual(symbol, '2330')
        self.assertEqual(options, {'as_of':'2026-10-02','period':'custom','start_date':'2026-01-01'})
        self.assertEqual(routes.stock_code('00631L.TW'), '00631L')

    def test_gateway_market_reads_and_personal_research(self):
        settings = SimpleNamespace(extra_read_paths=(), extra_control_paths=())
        for path in ('/breakout-research','/valuation-research/2330','/research/portfolio'):
            self.assertTrue(gateway.route_permission('GET',path,'reader',settings),path)
        for path in ('/research/workflow','/research/subject','/research/validation','/breakout-shadow'):
            self.assertFalse(gateway.route_permission('GET',path,'reader',settings),path)
            self.assertTrue(gateway.route_permission('GET',path,'owner',settings),path)
        self.assertFalse(gateway.route_permission('POST','/breakout-shadow','reader',settings))
        self.assertTrue(gateway.route_permission('POST','/breakout-shadow','owner',settings))
        for path in ('/research/portfolio/refresh','/breakout-shadow/admin','/valuation-research-admin'):
            self.assertFalse(gateway.route_permission('GET',path,'owner',settings),path)

    def test_research_screen_does_not_download_or_invent_sector(self):
        import 估值趨勢
        handler = Handler()
        payload = {'research': {'enabled':True}, 'symbols':['2330.TW','2454','2330'], 'sector':''}
        with patch.object(估值趨勢,'run_screen',return_value={'results':[]}) as calculation:
            handler._handle_research_screen(payload)
        self.assertEqual(handler.status,200)
        self.assertEqual(calculation.call_args.kwargs['symbols'],['2330','2330.TW','2454'])
        self.assertIsNone(calculation.call_args.kwargs['lookup'](['missing'],'2330'))
        payload['sector'] = '半導體業'
        with patch.object(估值趨勢,'run_screen') as calculation:
            handler._handle_research_screen(payload)
        self.assertEqual(handler.status,503)
        calculation.assert_not_called()

    def test_invalid_shapes_stop_before_calculation(self):
        import 估值趨勢
        for payload in ({'research':{'enabled':'true'},'symbols':['2330']},
                        {'research':{'enabled':True},'symbols':[]},
                        {'research':{'enabled':True},'symbols':['2330'],'tech':[]}):
            handler = Handler()
            with patch.object(估值趨勢,'run_screen') as calculation:
                handler._handle_research_screen(payload)
            self.assertEqual(handler.status,400)
            calculation.assert_not_called()

    def test_valuation_preserves_explicit_exchange_identity(self):
        import 估值趨勢
        handler = Handler('/valuation-research/2330.TWO?peMax=40&excludeIp=true')
        with patch.object(估值趨勢, 'get_research', return_value={'row':{}}) as calculation:
            handler._handle_valuation_research()
        self.assertEqual(handler.status,200)
        self.assertEqual(calculation.call_args.args, ('2330.TWO',))
        self.assertEqual(calculation.call_args.kwargs['settings'], {'peMax':40.0,'excludeIp':True})
        with self.assertRaises(ValueError):
            routes.breakout_options({'sym':'2330.TWO'})


if __name__ == '__main__':
    unittest.main()
