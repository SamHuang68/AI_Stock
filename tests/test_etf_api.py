# -*- coding: utf-8 -*-
"""etf_api / ai_api 抽出後的煙霧測試（H2 續）"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SERVER = os.path.join(_ROOT, 'server')
if _SERVER not in sys.path:
    sys.path.insert(0, _SERVER)


class TestAiApi(unittest.TestCase):
    def test_resolve_model_fallback_without_key(self):
        import ai_api
        m = ai_api.resolve_model(None)
        self.assertTrue(isinstance(m, str) and len(m) > 0)
        self.assertIn('claude', m.lower())

    def test_load_ai_key_missing_ok(self):
        import ai_api
        # 不應因缺檔拋例外
        k = ai_api.load_ai_key()
        self.assertIsInstance(k, str)


class TestEtfApi(unittest.TestCase):
    def test_parse_and_delta(self):
        import etf_api

        def holdings(rows):
            return {'00992A': [
                {'code': c, 'name': n, 'weight': w, 'shares': s, 'rank': r}
                for r, (c, n, w, s) in enumerate(rows, 1)
            ]}

        prev = holdings([
            ('2330', '台積電', 20.0, 1000),
            ('2317', '鴻海', 10.0, 500),
        ])
        curr = holdings([
            ('2330', '台積電', 21.0, 1200),  # 加碼
            ('2454', '聯發科', 8.0, 300),   # 新進
        ])
        with tempfile.TemporaryDirectory() as td:
            f0 = os.path.join(td, 'top10_active_etf_holdings_20260101.json')
            f1 = os.path.join(td, 'top10_active_etf_holdings_20260102.json')
            with open(f0, 'w', encoding='utf-8') as f:
                json.dump(prev, f)
            with open(f1, 'w', encoding='utf-8') as f:
                json.dump(curr, f)
            # 暫時關閉 catalog 過濾
            old = etf_api.ETF_CATALOG_FILE
            etf_api.ETF_CATALOG_FILE = os.path.join(td, 'no_catalog.json')
            try:
                out = etf_api.compute_etf_delta([f0, f1])
            finally:
                etf_api.ETF_CATALOG_FILE = old
        self.assertIsNotNone(out)
        self.assertEqual(out['date'], '20260102')
        self.assertEqual(out['prev_date'], '20260101')
        self.assertEqual(len(out['etfs']), 1)
        etf = out['etfs'][0]
        self.assertEqual(etf['code'], '00992A')
        self.assertEqual(len(etf['new']), 1)
        self.assertEqual(etf['new'][0]['code'], '2454')
        self.assertEqual(len(etf['removed']), 1)
        self.assertEqual(etf['removed'][0]['code'], '2317')
        self.assertTrue(any(c['code'] == '2330' for c in etf['changed']))

    def test_handler_mixin_methods(self):
        import ai_routes
        import etf_routes
        for name in (
            '_handle_ai_key_status', '_handle_ai_proxy', '_handle_ai_report',
            '_handle_ai_note', '_handle_ai_local',
        ):
            self.assertTrue(hasattr(ai_routes.AiRoutesMixin, name), name)
        for name in (
            '_handle_etf_catalog_get', '_handle_etf_delta',
            '_handle_tracker_run', '_handle_tracker_status',
        ):
            self.assertTrue(hasattr(etf_routes.EtfRoutesMixin, name), name)


if __name__ == '__main__':
    unittest.main()
