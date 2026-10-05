#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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


class TxfSnapshotSelectionTests(unittest.TestCase):
    """決策中心用的 __TXF__ 報價：夜盤區塊與日盤主報價中，已核實時間較新的那一筆。"""

    TW = timezone(timedelta(hours=8))

    def q(self, session, hh, mm, day=(2026, 10, 6), price=50000.0, verified=True):
        at = datetime(*day, hh, mm, tzinfo=self.TW)
        return {'ok': True, 'session': session, 'price': price,
                'asOf': at.isoformat() if verified else None, 'timeUnverified': not verified}

    def pick(self, now_hm, night, day, now_day=(2026, 10, 6)):
        now = datetime(*now_day, *now_hm, tzinfo=self.TW)
        return po.txf_for_snapshot(day, night, now=now)

    def test_day_session_uses_the_day_quote_not_last_nights(self):
        # 10:00：夜盤最後一筆 05:00、日盤 10:00 → 用日盤（過去一律用夜盤 → 被判過期而排除）
        night = self.q('night', 5, 0)
        day = self.q('day', 10, 0)
        self.assertEqual(self.pick((10, 0), night, day)['session'], 'day')

    def test_before_the_open_the_fresher_night_close_beats_yesterdays_day_session(self):
        # 06:00：/txf 主報價是「前一個日盤」（昨天 13:45），比剛收的夜盤（05:00）舊 15 小時
        night = self.q('night', 5, 0)
        day = self.q('day', 13, 45, day=(2026, 10, 5))
        self.assertEqual(self.pick((6, 0), night, day)['session'], 'night')

    def test_after_the_day_close_and_at_night(self):
        night_old = self.q('night', 5, 0)
        day_close = self.q('day', 13, 45)
        self.assertEqual(self.pick((14, 20), night_old, day_close)['session'], 'day')       # 13:45 收盤後、夜盤開始前
        night_new = self.q('night', 20, 0)
        self.assertEqual(self.pick((20, 1), night_new, day_close)['session'], 'night')      # 夜盤開始後

    def test_unverified_night_stays_in_charge_during_night_hours_only(self):
        night = self.q('night', 20, 0, verified=False)          # 價格在、時間未核實
        day_close = self.q('day', 13, 45)
        self.assertIs(self.pick((20, 5), night, day_close), night)
        # 白天則改用已核實的日盤
        morning_day = self.q('day', 10, 0)
        self.assertEqual(self.pick((10, 5), night, morning_day)['session'], 'day')

    def test_without_a_day_quote_behaviour_is_unchanged(self):
        night = self.q('night', 20, 0)
        self.assertIs(po.txf_for_snapshot(None, night), night)
        self.assertIs(po.txf_for_snapshot({'ok': False}, night), night)
        self.assertIs(po.txf_for_snapshot({'ok': True, 'session': 'night', 'price': 1.0}, night), night)
        day = self.q('day', 10, 0)
        self.assertEqual(po.txf_for_snapshot(day, None)['session'], 'day')

    def test_the_night_block_and_debug_keys_are_not_carried_into_the_day_quote(self):
        day = {**self.q('day', 10, 0), 'night': {'price': 1.0}, 'debug': {'x': 1}}
        picked = self.pick((10, 0), self.q('night', 5, 0), day)
        self.assertNotIn('night', picked)
        self.assertNotIn('debug', picked)

    def test_unverified_quote_is_excluded_from_pulse_scoring_only(self):
        unverified = self.q('night', 20, 0, verified=False)
        self.assertIsNone(po.txf_for_scoring(unverified))
        verified = self.q('night', 20, 0)
        self.assertIs(po.txf_for_scoring(verified), verified)
        self.assertIsNone(po.txf_for_scoring(None))


if __name__ == '__main__':
    unittest.main()
