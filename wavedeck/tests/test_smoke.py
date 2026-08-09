#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaveDeck smoke tests (stdlib unittest)."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server.decision import HeuristicProvider  # noqa: E402
from server.risk import evaluate_gate  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
