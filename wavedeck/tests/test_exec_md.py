#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaveDeck exec_md (Wave AI–style Markdown) unit tests."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import exec_md  # noqa: E402


class ExecMdTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.dir = Path(self._td.name)
        self._audit_patch = mock.patch.object(exec_md, "audit")
        self._patchers = [
            mock.patch.object(exec_md, "DATA", self.dir),
            mock.patch.object(exec_md, "_last_write_mono", 0.0),
            mock.patch.object(exec_md, "_last_timed_mono", 0.0),
            mock.patch.object(exec_md, "_last_inv_price", None),
            mock.patch.object(exec_md, "_last_action", None),
            self._audit_patch,
        ]
        for p in self._patchers:
            p.start()
        self.audit = self._audit_patch.get_original()[0]  # unused; writes mocked

    def tearDown(self) -> None:
        for p in self._patchers:
            p.stop()
        self._td.cleanup()

    def _decision(self, action="HOLD", inv=45019.0):
        return {
            "action": action,
            "action_label": "維持續抱" if action == "HOLD" else action,
            "confidence": 0.62,
            "bias_long": 0.60,
            "bias_short": 0.40,
            "event": "TIMED_MARKET_REVIEW",
            "summary": "短摘要",
            "invalidation": {"price": inv, "side": "below"},
            "next_watch": ["失守短線結構再評估"],
            "process": {"route": "heuristic→gate", "chase_risk": "medium", "gate": "ALLOW"},
            "provider": "heuristic",
        }

    def test_template_has_wave_ai_sections(self):
        snap = {
            "symbol": "TXF",
            "fsm": "InPosition",
            "mode": "paper",
            "style": 80,
            "exec": {"price": 45033},
            "st_overlay": {"spillover_prob": 0.55, "hot_stage": "先進封裝"},
        }
        d = self._decision()
        m = exec_md.build_metrics(snap, d, {"allow": True, "gate": "ALLOW", "lots_effective": 1})
        n = exec_md.narrative_template(m, d)
        self.assertTrue("結構" in n["market_status"] or "策略" in n["reasoning"])
        md = exec_md.render_markdown(
            symbol="TXF",
            ts="2026-08-10 08:00:00",
            decision=d,
            metrics=m,
            narrative=n,
            gate={"allow": True, "gate": "ALLOW", "lots_effective": 1, "reasons": []},
            event="TIMED_MARKET_REVIEW",
            source="test",
            fsm_before="InPosition",
            fsm_after="InPosition",
            trigger="timed_review:first",
        )
        self.assertIn("# 執行細節紀錄：TXF", md)
        self.assertIn("## 🎯 AI 最新判斷摘要", md)
        self.assertIn("## 📊 市場狀態與判斷理由", md)
        self.assertIn("## 🔍 觀察與失效條件", md)
        self.assertIn("## ⚙️ 本事件三層處理結果", md)
        self.assertIn("heuristic→gate", md)

    def test_should_emit_entry_and_throttle_timed(self):
        cfg = dict(exec_md._DEFAULT_EXEC_MD)
        d = self._decision("ENTER_LONG")
        ok, why = exec_md.should_emit(
            decision=d,
            event="WEBHOOK",
            fsm_before="Idle",
            fsm_after="InPosition",
            prev_ai={"action": "HOLD"},
            cfg=cfg,
        )
        self.assertTrue(ok)
        self.assertTrue(why.startswith("state:") or why.startswith("fsm:"))

        hold = self._decision("HOLD")
        ok2, why2 = exec_md.should_emit(
            decision=hold,
            event="TIMED_MARKET_REVIEW",
            fsm_before="InPosition",
            fsm_after="InPosition",
            prev_ai=hold,
            cfg=cfg,
        )
        self.assertTrue(ok2)  # first timed
        exec_md._last_timed_mono = 1e12  # far future → throttle
        ok3, why3 = exec_md.should_emit(
            decision=hold,
            event="TIMED_MARKET_REVIEW",
            fsm_before="InPosition",
            fsm_after="InPosition",
            prev_ai=hold,
            cfg=cfg,
        )
        self.assertFalse(ok3)
        self.assertEqual(why3, "skip")

    def test_enrich_writes_file_and_ai_fields(self):
        with mock.patch.object(exec_md, "_cfg", return_value=dict(exec_md._DEFAULT_EXEC_MD, mode="template")):
            with mock.patch.object(exec_md, "_ollama_narrative", return_value=None):
                snap = {
                    "symbol": "TXF",
                    "fsm": "InPosition",
                    "mode": "paper",
                    "style": 50,
                    "exec": {"price": 45020},
                    "st_overlay": {},
                }
                d = self._decision("EXIT")
                meta = exec_md.enrich_and_maybe_write(
                    snap=snap,
                    decision=d,
                    gate={"allow": True, "gate": "ALLOW", "lots_effective": 0, "reasons": []},
                    event="STOP",
                    source="test",
                    fsm_before="InPosition",
                    fsm_after="Flat",
                    prev_ai={"action": "HOLD", "invalidation": {"price": 44900, "side": "below"}},
                )
        self.assertTrue(meta.get("written"))
        self.assertIn("market_status", meta["ai_fields"])
        self.assertIn("reasoning", meta["ai_fields"])
        latest = exec_md.read_latest()
        self.assertIsNotNone(latest)
        self.assertIn("執行細節紀錄", latest["markdown"])
        items = exec_md.list_recent(5)
        self.assertGreaterEqual(len(items), 1)

    def test_inv_trail_force(self):
        with mock.patch.object(exec_md, "_cfg", return_value=dict(exec_md._DEFAULT_EXEC_MD, mode="template")):
            snap = {
                "symbol": "TXF",
                "fsm": "InPosition",
                "mode": "paper",
                "style": 35,
                "exec": {"price": 45020},
                "ai": self._decision("HOLD", inv=44900),
                "st_overlay": {"fail_safe": True},
            }
            meta = exec_md.on_invalidation_trail(
                snap,
                reason="heartbeat",
                prev_inv={"price": 44900, "side": "below"},
                new_inv={"price": 45010, "side": "below"},
            )
        self.assertTrue(meta and meta.get("written"))


if __name__ == "__main__":
    unittest.main()
