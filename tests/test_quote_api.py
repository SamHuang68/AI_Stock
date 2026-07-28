# -*- coding: utf-8 -*-
"""quote_api：macro id 解析與 jobs_snapshot 煙霧。"""
import unittest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'server'))
import quote_api as qa  # noqa: E402


class TestQuoteApi(unittest.TestCase):
    def test_resolve_macro_exact(self):
        self.assertEqual(qa._resolve_macro_id('__TW_MARGIN_MIX__'), '__TW_MARGIN_MIX__')
        self.assertEqual(qa._resolve_macro_id('__TW_MARGIN_CYCLE__'), '__TW_MARGIN_CYCLE__')

    def test_resolve_no_false_prefix(self):
        # 不可把 MIX 誤解析成 RATES
        self.assertNotEqual(qa._resolve_macro_id('__TW_MARGIN_MIX__'), '__TW_RATES__')

    def test_jobs_snapshot_keys(self):
        snap = qa.jobs_snapshot()
        self.assertIn('macro_track', snap)
        self.assertIn('margin_cycle', snap)
        self.assertIn('tdcc_holders', snap)
        self.assertIn('margin_ratio', snap)


if __name__ == '__main__':
    unittest.main()
