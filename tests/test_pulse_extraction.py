#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'server'
sys.path.insert(0, str(SERVER))

from pulse_layout import pulse_layout_probe  # noqa: E402
import breadth_build as bb  # noqa: E402
import pulse_orchestration as po  # noqa: E402


class PulseLayoutTests(unittest.TestCase):
    def test_probe_reports_missing_js(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = pulse_layout_probe(tmp)
        self.assertFalse(out['pulseJsExists'])
        self.assertIn('pulseJsPath', out)

    def test_probe_reads_contract_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            ui = Path(tmp) / 'src' / 'ui'
            ui.mkdir(parents=True)
            (ui / 'pulse_v5.js').write_text(
                'PULSE_LAYOUT_ANCHOR_3cab212 repeat(5,minmax(0,1fr)) 5col-2zone 4col-priority',
                encoding='utf-8',
            )
            out = pulse_layout_probe(tmp)
        self.assertTrue(out['pulseJsExists'])
        self.assertEqual(out['layoutAnchor'], 'PULSE_LAYOUT_ANCHOR_3cab212')
        self.assertEqual(out['layoutContract'], '5col-2zone')
        self.assertTrue(out['hasFiveCol'])
        self.assertTrue(out['hasFourColPriority'])


class BreadthBuildTests(unittest.TestCase):
    def test_cache_hit_skips_network(self):
        cache = MagicMock()
        payload = {'ok': True, 'date': '2026-08-11', 'stocks': {'up': 100}}
        cache.get.return_value = b'{"ok": true, "date": "2026-08-11", "stocks": {"up": 100}}'
        with tempfile.TemporaryDirectory() as tmp:
            out = bb.build_breadth_payload(
                cache,
                base_dir=tmp,
                yf_headers={},
                twse_mis_index=lambda *_a, **_k: {},
                build_tw_market_fundamental=lambda *_a, **_k: {},
            )
        self.assertTrue(out['ok'])
        cache.set.assert_not_called()


class PulseOrchestrationTests(unittest.TestCase):
    def test_cache_hit_returns_bytes_without_build(self):
        cached = b'{"ok":true,"updatedAt":"2026-08-11T00:00:00Z"}'
        mock_cache = MagicMock()
        mock_cache.get.return_value = cached
        handler = MagicMock()
        original = po._deps.cache
        po._deps.cache = mock_cache
        try:
            body = po.build_pulse_payload(handler, '/pulse')
        finally:
            po._deps.cache = original
        self.assertEqual(body, cached)
        handler._txf_mis_session.assert_not_called()


class BreadthCacheKeyContractTests(unittest.TestCase):
    def test_reader_and_writer_share_one_key(self):
        # 寫入端改成 breadth:source-date-v1 後，Pulse 讀取端仍寫死舊的 breadth:v1，
        # 永遠 miss → 每次 Pulse 重建都多一次廣度建置。兩端現在都由 breadth_cache_key 產生。
        from datetime import date
        from exchange_source_dates import breadth_cache_key
        self.assertEqual(breadth_cache_key(date(2026, 10, 1)), 'breadth:source-date-v1:20261001')
        for name in ('pulse_orchestration.py', 'breadth_build.py'):
            text = (SERVER / name).read_text(encoding='utf-8')
            self.assertIn('breadth_cache_key(', text, name)
            self.assertNotIn('breadth:v1', text, name)


if __name__ == '__main__':
    unittest.main()
