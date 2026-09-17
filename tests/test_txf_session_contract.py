"""台指期場次、日期與共同主報價的回歸測試。"""
import ast
import json
from pathlib import Path
import sys
import time
import types
import unittest
from datetime import datetime
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'server'))
from market_routes import taifex_mis_observation, select_txf_quote, synchronous_basis
from market_contract import attach_quote_contract


class TestTxfSessionContract(unittest.TestCase):
    def quote(self, session, day, clock, price=100):
        return {'price': price, 'session': session, 'prevClose': 99, 'changePct': 1,
                **taifex_mis_observation({'CDate': day, 'CTime': clock, 'SymbolID': 'TXFJ6-M'}, session)}

    def test_official_cross_midnight_fixture(self):
        # 官方 2026/09/17 盤後日報：9/16 15:00 至次日05:00；OHLC同MIS。
        q = self.quote('night', '20260916', '045958', 46382)
        self.assertEqual(q['asOf'], '2026-09-17T04:59:58+08:00')
        self.assertEqual(q['sessionDate'], '2026-09-16')
        self.assertIsNone(q['tradeDate'])
        self.assertEqual(self.quote('night', '20260918', '045958')['asOf'], '2026-09-19T04:59:58+08:00')
        self.assertEqual(self.quote('night', '20260918', '150000')['asOf'], '2026-09-18T15:00:00+08:00')
        self.assertEqual(self.quote('night', '20260918', '050000')['asOf'], '2026-09-19T05:00:00+08:00')

    def test_equal_prices_do_not_select_last_night_during_day(self):
        day = self.quote('day', '20260917', '090000')
        night = self.quote('night', '20260916', '045958')
        q = select_txf_quote(day, night, datetime.fromisoformat('2026-09-17T09:00:05+08:00'))
        self.assertEqual(q['session'], 'day')
        self.assertFalse(q['stale'])
        q = select_txf_quote(day, self.quote('night', '20260917', '150100'),
                             datetime.fromisoformat('2026-09-17T15:01:05+08:00'))
        self.assertEqual(q['session'], 'night')

    def test_invalid_future_and_stale_quotes(self):
        for day, clock in (('', ''), ('20260230', '090000'), ('20260917', '120000'), ('2026091', '045958'), ('20260917', '45958')):
            self.assertIsNone(self.quote('night', day, clock)['asOf'])
        future = self.quote('day', '20260918', '090000')
        self.assertIsNone(select_txf_quote(future, None, datetime.fromisoformat('2026-09-17T09:00:00+08:00')))
        old = self.quote('night', '20260918', '045958')
        self.assertTrue(select_txf_quote(None, old, datetime.fromisoformat('2026-09-21T09:00:00+08:00'))['stale'])

    def test_basis_rejects_different_sessions_and_times(self):
        spot = {'price': 100, 'asOf': '2026-09-17T09:00:00+08:00'}
        day = self.quote('day', '20260917', '090000', 101)
        self.assertEqual(synchronous_basis(spot, day), (1, 1))
        self.assertEqual(synchronous_basis(spot, self.quote('night', '20260916', '045958')), (None, None))
        self.assertEqual(synchronous_basis(spot, {**day, 'asOf': '2026-09-17T08:50:00+08:00'}), (None, None))

    def test_http_payload_uses_shared_builder_and_preserves_contract(self):
        tree = ast.parse((ROOT / 'server/server.py').read_text(encoding='utf-8'))
        handler = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Handler')
        names = {'_txf_payload', '_handle_txf'}
        body = [n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name in names]
        namespace = {'json': json, 'time': time, '_cache': Mock(get=Mock(return_value=None)),
                     'select_txf_quote': lambda day, night: select_txf_quote(day, night, datetime.fromisoformat('2026-09-17T09:00:05+08:00')),
                     'attach_quote_contract': attach_quote_contract}
        exec(compile(ast.Module(body=body, type_ignores=[]), '<實際HTTP方法>', 'exec'), namespace)
        obj = types.SimpleNamespace(_ok=Mock())
        day = self.quote('day', '20260917', '090000')
        night = self.quote('night', '20260916', '045958')
        obj._txf_mis_session = lambda market: day if market == 0 else night
        obj._txf_payload = types.MethodType(namespace['_txf_payload'], obj)
        namespace['_handle_txf'](obj)
        value = json.loads(obj._ok.call_args.args[0])
        self.assertEqual(value['session'], 'day')
        self.assertEqual(value['market']['tradeDate'], '2026-09-17')
        self.assertEqual(value['night']['asOf'], night['asOf'])
        pulse = next(n for n in handler.body if isinstance(n, ast.FunctionDef) and n.name == '_handle_pulse')
        calls = [n for n in ast.walk(pulse) if isinstance(n, ast.Call)]
        self.assertTrue(any(isinstance(n.func, ast.Attribute) and n.func.attr == '_txf_payload' for n in calls))


if __name__ == '__main__':
    unittest.main()
