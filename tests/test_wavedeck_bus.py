#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ST wavedeck_bus reverse bus + cost meter smoke tests."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import wavedeck_bus as wdb  # noqa: E402


class WaveDeckBusSmoke(unittest.TestCase):
    def test_origin_allows_wd_ports(self):
        self.assertTrue(wdb.is_wavedeck_origin("http://127.0.0.1:18433/"))
        self.assertTrue(wdb.is_wavedeck_origin("http://localhost:18765"))
        self.assertFalse(wdb.is_wavedeck_origin("http://127.0.0.1:18432/"))
        self.assertFalse(wdb.is_wavedeck_origin("https://evil.example/"))

    def test_accept_report_and_costs(self):
        with tempfile.TemporaryDirectory() as td:
            store = Path(td) / "wavedeck_bus.json"
            with mock.patch.object(wdb, "DATA", Path(td)), mock.patch.object(wdb, "STORE", store):
                with wdb._lock:
                    wdb._state["report"] = None
                    wdb._state["costs"] = {
                        "st_local_calls": 0,
                        "st_cloud_calls": 0,
                        "st_cloud_usd_est": 0.0,
                        "wd_session_usd": 0.0,
                        "wd_day_usd": 0.0,
                        "wd_month_usd": 0.0,
                        "wd_provider": None,
                        "updated_at": None,
                    }
                snap = wdb.accept_report(
                    {
                        "fsm": "InPosition",
                        "mode": "paper",
                        "style": 55,
                        "symbol": "TXF",
                        "ai": {"action": "HOLD", "action_label": "維持續抱", "confidence": 0.6},
                        "positions": {"account": 1},
                        "costs": {"session_usd": 0.2, "day_usd": 1.5, "provider": "heuristic"},
                        "st_overlay": {"aggressiveness": 55, "delever": False, "spillover_prob": 0.5},
                        "source": "unit",
                    }
                )
                self.assertTrue(snap["ok"])
                self.assertEqual(snap["report"]["fsm"], "InPosition")
                self.assertEqual(snap["costs"]["wd_day_usd"], 1.5)
                wdb.record_st_local(2)
                wdb.record_st_cloud(0.03, 1)
                snap2 = wdb.snapshot()
                self.assertEqual(snap2["costs"]["st_local_calls"], 2)
                self.assertEqual(snap2["costs"]["st_cloud_calls"], 1)
                self.assertAlmostEqual(snap2["costs"]["combined_usd_est"], 1.53)


if __name__ == "__main__":
    unittest.main()
