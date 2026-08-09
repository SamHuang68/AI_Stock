#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llm_gate + override_alpha unit tests (stdlib)."""
from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))


class LlmGateTests(unittest.TestCase):
    def test_wd_preempts_st(self):
        import llm_gate as lg

        with tempfile.TemporaryDirectory() as td:
            gate = Path(td) / "llm_gate.json"
            with mock.patch.object(lg, "GATE_PATH", gate):
                self.assertTrue(lg.acquire("st", ttl_sec=30))
                self.assertTrue(lg.wd_busy() is False)
                self.assertTrue(lg.acquire("wd", ttl_sec=30))  # preempt
                self.assertTrue(lg.wd_busy())
                self.assertFalse(lg.acquire("st", ttl_sec=30))  # cannot steal
                lg.release("wd")
                self.assertFalse(lg.wd_busy())
                self.assertTrue(lg.acquire("st", ttl_sec=30))

    def test_wait_or_defer_times_out(self):
        import llm_gate as lg

        with tempfile.TemporaryDirectory() as td:
            gate = Path(td) / "llm_gate.json"
            with mock.patch.object(lg, "GATE_PATH", gate):
                self.assertTrue(lg.acquire("wd", ttl_sec=60))
                t0 = time.time()
                ok = lg.wait_or_defer("st", wait_sec=0.35, ttl_sec=30)
                self.assertFalse(ok)
                self.assertLess(time.time() - t0, 1.2)


class OverrideAlphaTests(unittest.TestCase):
    def test_log_and_summary(self):
        import override_alpha as oa

        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "override_alpha.db"
            with mock.patch.object(oa, "DATA", Path(td)), mock.patch.object(oa, "DB", db):
                oa.init_db()
                r = oa.log_event(
                    {
                        "style": 35,
                        "delever": True,
                        "score": 28,
                        "spillover_prob": 0.22,
                        "twii": 22000.5,
                        "wd_equity": 1_000_000,
                        "wd_equity_chg": -1200,
                        "wd_fsm": "InPosition",
                        "note": "unit risk-off",
                        "source": "unit",
                        "meta": {"hot_stage": "先進封裝"},
                    }
                )
                self.assertTrue(r["ok"])
                items = oa.recent(10)
                self.assertEqual(len(items), 1)
                self.assertTrue(items[0]["delever"])
                self.assertAlmostEqual(float(items[0]["twii"]), 22000.5)
                text = oa.summary_for_review(10)
                self.assertIn("Override Alpha", text)
                self.assertIn("unit risk-off", text)


class BusChipFieldsTests(unittest.TestCase):
    def test_accept_report_keeps_invalidation_and_fail_safe(self):
        import wavedeck_bus as wdb

        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / "wavedeck_bus.json"
            with mock.patch.object(wdb, "DATA", Path(td)), mock.patch.object(wdb, "STORE", store):
                with wdb._lock:
                    wdb._state["report"] = None
                snap = wdb.accept_report(
                    {
                        "fsm": "InPosition",
                        "ai": {
                            "action": "HOLD",
                            "invalidation": {"side": "below", "price": 44800},
                        },
                        "st_overlay": {
                            "fail_safe": True,
                            "fail_safe_reason": "ST 心跳中斷",
                            "delever": True,
                        },
                        "st_link": {"status": "down", "fail_safe": True},
                        "push_reason": "fail_safe",
                    }
                )
                self.assertTrue(snap["ok"])
                rep = snap.get("report") or {}
                self.assertEqual((rep.get("ai") or {}).get("invalidation", {}).get("price"), 44800)
                self.assertTrue((rep.get("st_overlay") or {}).get("fail_safe"))
                self.assertEqual(rep.get("push_reason"), "fail_safe")


if __name__ == "__main__":
    unittest.main()
