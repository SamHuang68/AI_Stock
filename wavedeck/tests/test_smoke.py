#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaveDeck smoke tests (stdlib unittest)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.broker import PaperBroker, TxtMasterBroker, _parse_lots  # noqa: E402
from server.config import set_broker_kind, set_mode, set_provider  # noqa: E402
from server.decision import HeuristicProvider  # noqa: E402
from server.engine import apply_st_bridge  # noqa: E402
from server.providers import infer_with_fallback  # noqa: E402
from server.risk import evaluate_gate  # noqa: E402
from server.spillover import (  # noqa: E402
    blend_spillover,
    spillover_from_chain_stages,
    spillover_from_rotation,
)


class WaveDeckSmoke(unittest.TestCase):
    def test_heuristic_hold_shape(self):
        d = HeuristicProvider().infer(
            {"style": 50, "event": "TIMED_MARKET_REVIEW", "positions": {"account": 1}, "price": 45020}
        )
        self.assertIn(d["action"], {"HOLD", "ENTER_LONG", "REDUCE", "EXIT", "ENTER_SHORT"})
        self.assertIn("invalidation", d)
        self.assertGreaterEqual(d["confidence"], 0.1)

    def test_kill_switch_blocks(self):
        st = {
            "kill_switch": True,
            "fsm": "Halted",
            "account": {"yesterday_balance": 100, "equity": 100},
            "no_overnight": {"enabled": False},
            "st_overlay": {},
            "style": 50,
            "exec": {"lots": 1},
        }
        g = evaluate_gate(st, {"action": "ENTER_LONG", "process": {"chase_risk": "low"}})
        self.assertFalse(g["allow"])
        self.assertEqual(g["gate"], "BLOCK")

    def test_architecture_doc_exists(self):
        p = ROOT / "docs" / "ARCHITECTURE.md"
        self.assertTrue(p.is_file())
        text = p.read_text(encoding="utf-8")
        self.assertIn("WaveDeck", text)
        self.assertIn("執行閘門", text)
        self.assertIn("v1.5", text)

    def test_parse_lots(self):
        self.assertEqual(_parse_lots("TXF 2\n", "TXF"), 2)
        self.assertEqual(_parse_lots("2330=3", "2330"), 3)
        self.assertEqual(_parse_lots("7"), 7)

    def test_paper_broker_enter(self):
        st = {"positions": {"ai_suggested": 0, "txt_target": 0, "strategy": 0, "account": 0}, "exec": {"price": 1}}
        out = PaperBroker().apply_intent(st, {"action": "ENTER_LONG", "action_label": "偏多進場"}, 2)
        self.assertEqual(out["positions"]["txt_target"], 2)
        self.assertEqual(out["positions"]["account"], 2)

    def test_txt_master_roundtrip(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = {
                "provider": "heuristic",
                "mode": "live",
                "broker": {
                    "kind": "txt_master",
                    "txt_dir": td,
                    "target_file": "target_position.txt",
                    "account_file": "account_position.txt",
                    "strategy_file": "strategy_position.txt",
                    "signal_file": "order_signal.txt",
                },
            }
            with mock.patch("server.broker.load_config", return_value=cfg):
                Path(td, "account_position.txt").write_text("TXF 0\n", encoding="utf-8")
                Path(td, "strategy_position.txt").write_text("TXF 0\n", encoding="utf-8")
                br = TxtMasterBroker()
                st = {
                    "symbol": "TXF",
                    "positions": {"ai_suggested": 0, "txt_target": 0, "strategy": 0, "account": 0},
                    "exec": {"price": 45020},
                }
                applied = br.apply_intent(st, {"action": "ENTER_LONG", "action_label": "偏多"}, 1)
                self.assertEqual(applied["positions"]["txt_target"], 1)
                target = Path(td, "target_position.txt").read_text(encoding="utf-8")
                self.assertIn("TXF", target)
                self.assertIn("1", target)
                signal = Path(td, "order_signal.txt").read_text(encoding="utf-8")
                self.assertIn("ENTER_LONG", signal)

    def test_infer_fallback_on_provider_error(self):
        class Boom:
            name = "ollama"

            def infer(self, ctx):
                raise RuntimeError("down")

        with mock.patch("server.providers.resolve_provider", return_value=Boom()):
            d, err = infer_with_fallback(
                {"style": 50, "event": "X", "positions": {"account": 1}, "price": 1},
                "ollama",
            )
        self.assertIsNotNone(err)
        self.assertEqual(d["provider"], "heuristic")
        self.assertIn("heuristic", d["process"]["route"])

    def test_config_helpers_validate(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = Path(td) / "wavedeck_config.json"
            with mock.patch("server.config.CONFIG_PATH", cfg_path), mock.patch(
                "server.config.DATA", Path(td)
            ):
                cfg_path.write_text("{}", encoding="utf-8")
                c = set_provider("ollama")
                self.assertEqual(c["provider"], "ollama")
                c = set_mode("live")
                self.assertEqual(c["mode"], "live")
                self.assertEqual(c["broker"]["kind"], "txt_master")
                c = set_broker_kind("paper")
                self.assertEqual(c["broker"]["kind"], "paper")
                with self.assertRaises(ValueError):
                    set_provider("nope")

    def test_st_bridge_spillover_forces_delever(self):
        with tempfile.TemporaryDirectory() as td:
            with mock.patch("server.state.DATA", Path(td)), mock.patch(
                "server.state.STATE_PATH", Path(td) / "runtime_state.json"
            ), mock.patch("server.audit.DATA", Path(td)):
                snap = apply_st_bridge(
                    {
                        "style": 55,
                        "delever": False,
                        "note": "test",
                        "meta": {
                            "rotation": "narrow",
                            "spillover_prob": 0.22,
                            "leaders": ["半導體"],
                            "source": "unit",
                        },
                    }
                )
                ov = snap.get("st_overlay") or {}
                self.assertTrue(ov.get("delever"))
                self.assertEqual(ov.get("rotation"), "narrow")
                self.assertAlmostEqual(float(ov.get("spillover_prob")), 0.22)
                self.assertEqual(snap.get("style"), 55)

    def test_soft_spillover_gate_halves_lots(self):
        st = {
            "kill_switch": False,
            "fsm": "Idle",
            "account": {"yesterday_balance": 100, "equity": 100},
            "no_overnight": {"enabled": False},
            "st_overlay": {"delever": False, "spillover_prob": 0.25},
            "style": 50,
            "exec": {"lots": 4},
        }
        g = evaluate_gate(st, {"action": "ENTER_LONG", "process": {"chase_risk": "low"}})
        self.assertTrue(g["allow"])
        self.assertEqual(g["lots_effective"], 2)
        self.assertTrue(any("外溢" in r for r in g["reasons"]))

    def test_chain_spillover_contiguous_high(self):
        stages = [
            {"stage": "A", "n": 3, "mom5": 2.0, "mom20": 1.0},
            {"stage": "B", "n": 3, "mom5": 1.5, "mom20": 0.5},
            {"stage": "C", "n": 3, "mom5": 1.0, "mom20": 0.2},
        ]
        out = spillover_from_chain_stages(stages)
        self.assertGreaterEqual(out["prob"], 0.70)
        self.assertEqual(out["contig"], 1.0)
        self.assertEqual(out["hot_stage"], "A")

    def test_chain_spillover_isolated_low(self):
        stages = [
            {"stage": "A", "n": 3, "mom5": 3.0, "mom20": 2.0},
            {"stage": "B", "n": 3, "mom5": -1.0, "mom20": -0.5},
            {"stage": "C", "n": 3, "mom5": -0.5, "mom20": 0.0},
        ]
        out = spillover_from_chain_stages(stages)
        self.assertLessEqual(out["prob"], 0.40)
        self.assertEqual(out["contig"], 0.0)

    def test_blend_and_sector_spillover(self):
        self.assertGreater(spillover_from_rotation("broad", 5, 1), 0.6)
        self.assertLess(spillover_from_rotation("narrow", 1, 5), 0.45)
        self.assertAlmostEqual(blend_spillover(0.5, 0.8), 0.68)

    def test_heuristic_respects_low_spillover(self):
        d = HeuristicProvider().infer(
            {
                "style": 65,
                "event": "TIMED_MARKET_REVIEW",
                "positions": {"account": 0},
                "price": 45020,
                "st_spillover_prob": 0.22,
                "st_hot_stage": "先進封裝",
                "st_delever": False,
            }
        )
        self.assertEqual(d["action"], "HOLD")
        self.assertIn("外溢", d["action_label"])
        self.assertEqual(d["process"]["chase_risk"], "high")
        self.assertTrue(any("先進封裝" in w for w in d["next_watch"]))

    def test_gate_blocks_extreme_low_spillover(self):
        st = {
            "kill_switch": False,
            "fsm": "Idle",
            "account": {"yesterday_balance": 100, "equity": 100},
            "no_overnight": {"enabled": False},
            "st_overlay": {"delever": False, "spillover_prob": 0.15},
            "style": 65,
            "exec": {"lots": 2},
        }
        g = evaluate_gate(st, {"action": "ENTER_LONG", "process": {"chase_risk": "medium"}})
        self.assertFalse(g["allow"])
        self.assertTrue(any("極低" in r for r in g["reasons"]))

    def test_fail_safe_blocks_new_entries(self):
        st = {
            "kill_switch": False,
            "fsm": "Idle",
            "account": {"yesterday_balance": 100, "equity": 100},
            "no_overnight": {"enabled": False},
            "st_overlay": {"fail_safe": True, "delever": True},
            "st_link": {"fail_safe": True, "status": "down"},
            "style": 35,
            "exec": {"lots": 2},
        }
        g = evaluate_gate(st, {"action": "ENTER_LONG", "process": {"chase_risk": "low"}})
        self.assertFalse(g["allow"])
        self.assertTrue(any("Fail-safe" in r for r in g["reasons"]))

    def test_apply_fail_safe_tightens_style(self):
        from server.st_link import apply_fail_safe
        from server.state import RUNTIME

        with tempfile.TemporaryDirectory() as td:
            with mock.patch("server.state.DATA", Path(td)), mock.patch(
                "server.state.STATE_PATH", Path(td) / "runtime_state.json"
            ), mock.patch("server.audit.DATA", Path(td)), mock.patch(
                "server.st_link.push_async"
            ):
                RUNTIME.patch(
                    style=70,
                    exec={"price": 45000},
                    ai={"invalidation": {"side": "below", "price": 44000}, "summary": "ok"},
                    st_overlay={},
                    st_link={},
                )
                snap = apply_fail_safe("ST 心跳中斷")
                self.assertEqual(snap.get("style"), 35)
                self.assertTrue((snap.get("st_overlay") or {}).get("fail_safe"))
                self.assertTrue((snap.get("st_link") or {}).get("fail_safe"))
                inv = ((snap.get("ai") or {}).get("invalidation") or {})
                self.assertGreater(float(inv.get("price")), 44000)

    def test_st_push_chip_lightweight(self):
        from server.st_push import build_report, _chip_from_snap

        snap = {
            "fsm": "InPosition",
            "mode": "paper",
            "style": 55,
            "symbol": "TXF",
            "kill_switch": False,
            "ai": {
                "action": "HOLD",
                "action_label": "維持續抱",
                "confidence": 0.7,
                "invalidation": {"side": "below", "price": 44800},
            },
            "positions": {"account": 2, "txt_target": 2},
            "costs": {},
            "account": {},
            "st_overlay": {"delever": False, "spillover_prob": 0.5},
            "st_link": {"status": "ok"},
        }
        chip = _chip_from_snap(snap)
        self.assertEqual(chip["direction"], "LONG")
        self.assertEqual(chip["position_size"], 2)
        self.assertEqual(chip["wd_mode"], "PAPER")
        self.assertNotIn("candles", chip)
        rep = build_report(snap, reason="unit")
        self.assertEqual(rep["event_type"], "POSITION_STATE_CHANGE")
        self.assertEqual(rep["chip"]["invalidation_price"], 44800)


if __name__ == "__main__":
    unittest.main()
