#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外部訊號與 ST 橋接資料的輸入檢查（WD P0 第 1 片）；完全離線，只用暫存狀態。"""
from __future__ import annotations

import copy
import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.signal_input import MAX_BODY_BYTES, bounded_object, check_bridge, check_signal  # noqa: E402


class BoundedObjectTests(unittest.TestCase):
    def test_accepts_plain_object_and_rejects_everything_else(self):
        body = {"event": "BREAKOUT", "price": 45000.5}
        self.assertIs(bounded_object(body), body)
        for bad in ([], "x", 3, None):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "JSON 物件"):
                bounded_object(bad)

    def test_non_finite_numbers_are_rejected_wherever_they_hide(self):
        # Python 的 json.loads 預設放行 NaN／Infinity；寫進狀態後瀏覽器端 JSON.parse 會失敗。
        for bad in ({"price": float("nan")}, {"meta": {"score": float("inf")}}, {"a": [{"b": float("-inf")}]}):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "非有限"):
                bounded_object(bad)
        parsed = json.loads('{"price": NaN}')           # 這就是 HTTP 層實際會交進來的東西
        with self.assertRaises(ValueError):
            bounded_object(parsed)

    def test_size_limit_counts_encoded_bytes(self):
        bounded_object({"note": "a" * (MAX_BODY_BYTES - 20)})
        with self.assertRaisesRegex(ValueError, "16 KiB"):
            bounded_object({"note": "a" * MAX_BODY_BYTES})
        with self.assertRaisesRegex(ValueError, "16 KiB"):
            bounded_object({"note": "測" * (MAX_BODY_BYTES // 3 + 10)})      # 中文每字 3 位元組

    def test_deeply_nested_input_is_a_clean_rejection_not_a_crash(self):
        deep = cur = {}
        for _ in range(5000):
            cur["x"] = {}
            cur = cur["x"]
        with self.assertRaises(ValueError):
            bounded_object(deep)


class CheckSignalTests(unittest.TestCase):
    def test_typical_signals_pass_and_are_not_modified(self):
        for body in ({}, {"symbol": "TXF", "event": "BREAKOUT", "source": "tradingview", "price": 45010},
                     {"symbol": "txf", "provider": "OpenAI", "signal_id": "sig:2026-11-04_01", "timeframe": "5"},
                     {"strategy_id": "ma-cross", "version": "1", "signal_id": "abc.123", "levels": [1, 2, 3]}):
            with self.subTest(body=body):
                snapshot = copy.deepcopy(body)
                self.assertIsNone(check_signal(body))
                self.assertEqual(body, snapshot)         # 策略契約用 body 做冪等指紋：不可補欄位、不可改值

    def test_missing_none_or_empty_values_mean_use_default_like_main(self):
        for field in ("symbol", "event", "source", "provider", "signal_id"):
            for empty in (None, ""):
                with self.subTest(field=field, empty=empty):
                    check_signal({field: empty})

    def test_symbol_must_be_a_short_plain_token(self):
        for bad in ("TX F", "TXF<script>", "A" * 33, 123, ["TXF"], "TXF\n"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "商品代碼"):
                check_signal({"symbol": bad})

    def test_event_and_source_reject_control_characters_and_long_text(self):
        for field in ("event", "source"):
            for bad in ("a\x00b", "line\nbreak", "x" * 129, "   ", 5, ["x"]):
                with self.subTest(field=field, bad=bad), self.assertRaises(ValueError):
                    check_signal({field: bad})
        check_signal({"event": "突破 · 5分K", "source": "x" * 128})

    def test_provider_is_limited_to_the_names_providers_py_knows(self):
        for good in ("heuristic", "ollama", "openai", "OpenAI", "OLLAMA"):
            check_signal({"provider": good})
        for bad in ("gpt-5", "anthropic", 7, ["openai"]):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "決策來源"):
                check_signal({"provider": bad})

    def test_signal_id_must_be_a_plain_token(self):
        for bad in ("has space", "x" * 81, "a/b", 12, "id\n"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "識別碼"):
                check_signal({"signal_id": bad})


class CheckBridgeTests(unittest.TestCase):
    ST_PAYLOAD = {"style": 47, "delever": False, "note": "風格→47",
                  "meta": {"rotation": "narrow", "spillover_prob": 0.22, "leaders": ["半導體", "AI 伺服器"],
                           "hot_stage": "上游", "source": "st-macro", "score": 61.5, "advRatio": 0.42}}

    def test_what_stock_terminal_actually_sends_passes(self):
        check_bridge(copy.deepcopy(self.ST_PAYLOAD))
        check_bridge({"style": 20.0})                       # JSON 的 20.0 與 20 同義
        check_bridge({"style": 90, "delever": True, "leaders": ["a"] * 6})

    def test_absent_or_null_fields_keep_main_semantics(self):
        check_bridge({})
        check_bridge({"style": None, "delever": None, "meta": None, "leaders": None})

    def test_style_must_be_a_real_integer_in_range(self):
        for bad in (0, 100, -1, 47.5, "47", True, False, [], {}, 10 ** 400):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "風格"):
                check_bridge({"style": bad})

    def test_delever_must_be_boolean_because_string_false_is_truthy(self):
        for bad in ("false", "0", 0, 1, "true"):
            with self.subTest(bad=bad), self.assertRaisesRegex(ValueError, "降載"):
                check_bridge({"delever": bad})

    def test_meta_and_leaders_shapes(self):
        with self.assertRaisesRegex(ValueError, "meta"):
            check_bridge({"meta": ["x"]})
        for container in ({"leaders": "半導體"}, {"leaders": ["x"] * 7}, {"leaders": ["x" * 41]}, {"leaders": [1]},
                          {"meta": {"leaders": ["x"] * 7}}, {"meta": {"leaders": [None]}}):
            with self.subTest(container=container), self.assertRaisesRegex(ValueError, "領先名單"):
                check_bridge(container)

    def test_non_finite_and_oversized_bridge_bodies_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "非有限"):
            check_bridge({"style": 50, "meta": {"score": float("nan")}})
        with self.assertRaisesRegex(ValueError, "16 KiB"):
            check_bridge({"note": "x" * MAX_BODY_BYTES})


class EngineIntegrationTests(unittest.TestCase):
    """進入點真的有接上檢查：無效輸入不改狀態、不進稽核（只記原因），有效輸入行為與先前相同。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        home = Path(self.temp.name)
        for target, value in (("server.state.DATA", home), ("server.state.STATE_PATH", home / "runtime_state.json"),
                              ("server.audit.DATA", home)):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target in ("server.engine.notify_override_alpha", "server.engine.push_async"):
            patcher = mock.patch(target)
            patcher.start()
            self.addCleanup(patcher.stop)
        from server import engine
        from server.state import RUNTIME, _default_state
        # RUNTIME 是行程內單例：前面的測試（例如回撤鎖）可能已把急停開起來。換上全新狀態，清理時還原，
        # 測試才不依賴執行順序。
        patcher = mock.patch.object(RUNTIME, "_state", _default_state())
        patcher.start()
        self.addCleanup(patcher.stop)
        self.engine, self.runtime, self.home = engine, RUNTIME, home

    def audit_rows(self):
        db = self.home / "wavedeck_audit.db"
        if not db.exists():
            return []
        with closing(sqlite3.connect(db)) as conn:
            return conn.execute("SELECT kind, payload FROM audit").fetchall()

    def test_invalid_signals_are_blocked_without_touching_state_or_storing_the_body(self):
        before = self.runtime.snapshot()
        for body in ({"symbol": "TX F"}, {"price": float("nan"), "event": "X"}, {"provider": "gpt-5"},
                     {"event": "a\x00b"}, {"note": "x" * (MAX_BODY_BYTES + 1)}):
            with self.subTest(body=str(body)[:40]):
                result = self.engine.handle_signal(body)
                self.assertFalse(result["ok"])
                self.assertTrue(result["blocked"])
                self.assertIn("訊號內容無效", result["reason"])
        self.assertEqual(self.runtime.snapshot(), before)
        rows = self.audit_rows()
        self.assertEqual([kind for kind, _ in rows], ["signal_blocked"] * 5)
        for _, payload in rows:
            stored = json.loads(payload)
            self.assertEqual(stored["body"], {})                  # 不存無效內容本身
            self.assertNotIn("NaN", payload)

    def test_non_object_signal_keeps_its_existing_block_reason(self):
        self.assertEqual(self.engine.handle_signal([1, 2])["reason"], "訊號內容須為 JSON 物件")

    def test_valid_signal_still_goes_through_the_same_path(self):
        # 啟發式提供者是離線的純函式；大小寫不同的 provider 名稱（main 會轉小寫）也要照常通過。
        # 不留倉規則在台北時間 13:25 之後會擋新單，用的是真實時鐘；關掉它，測試才不隨時間變紅。
        self.runtime.patch(no_overnight={"enabled": False})
        result = self.engine.handle_signal({"symbol": "TXF", "event": "TIMED_MARKET_REVIEW", "provider": "Heuristic"})
        self.assertNotIn("訊號內容無效", str(result.get("reason") or ""))
        self.assertFalse(result.get("blocked"), result)
        self.assertEqual([kind for kind, _ in self.audit_rows() if kind == "signal_blocked"], [])

    def test_invalid_bridge_raises_before_any_overlay_write(self):
        before = self.runtime.snapshot().get("st_overlay")
        for body in ({"style": 500}, {"delever": "no"}, {"meta": 3}, [], {"meta": {"score": float("inf")}}):
            with self.subTest(body=str(body)[:40]), self.assertRaises(ValueError):
                self.engine.apply_st_bridge(body)
        self.assertEqual(self.runtime.snapshot().get("st_overlay"), before)
        self.engine.push_async.assert_not_called()
        self.engine.notify_override_alpha.assert_not_called()

    def test_valid_bridge_is_applied_as_before(self):
        snap = self.engine.apply_st_bridge(copy.deepcopy(CheckBridgeTests.ST_PAYLOAD))
        self.assertEqual(snap.get("style"), 47)
        self.assertEqual((snap.get("st_overlay") or {}).get("rotation"), "narrow")


if __name__ == "__main__":
    unittest.main()
