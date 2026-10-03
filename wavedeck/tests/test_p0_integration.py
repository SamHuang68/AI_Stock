# -*- coding: utf-8 -*-
"""P0 紙上訊號、成交與重啟的限定整合驗收。"""
from __future__ import annotations

from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# 全域 Runtime 初次匯入不得讀取實際資料；每一例另用 temp Runtime。
with mock.patch.object(Path, "is_file", return_value=False):
    from server import engine
    from server.state import Runtime


def fresh_quote():
    return {"symbol": "TXF", "price": 45000,
            "as_of": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
            "source": "offline-fixture", "demo": False}


def decision(action="ENTER_LONG", cost_usd=0.0):
    return {"action": action, "action_label": "離線整合驗收", "provider": "heuristic",
            "confidence": None, "bias_long": None, "bias_short": None, "demo": True,
            "summary": "隔離紙上訊號", "invalidation": {"price": None, "side": None},
            "process": {"route": "fixture", "chase_risk": "low"}, "next_watch": [],
            "cost_usd": cost_usd, "local_calls": 0, "cloud_calls": 0}


class P0IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "runtime.json"
        self.runtime = Runtime(self.path)
        self.runtime.patch(mode="paper", no_overnight={"enabled": False}, exec={"lots": 2},
                           st_link={"status": "ok", "fail_safe": False}, st_overlay={"fail_safe": False})
        self.config = {"provider": "heuristic", "mode": "paper", "broker": {"kind": "paper"}}
        self.next_decision = decision()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name in ("server.engine.RUNTIME", "server.state.RUNTIME", "server.st_link.RUNTIME"):
            self.stack.enter_context(mock.patch(name, self.runtime))
        for name in ("server.engine.load_config", "server.broker.load_config"):
            self.stack.enter_context(mock.patch(name, side_effect=lambda: deepcopy(self.config)))
        self.infer = self.stack.enter_context(mock.patch("server.engine.infer_with_fallback", side_effect=lambda *args, **kwargs: (deepcopy(self.next_decision), None)))
        for name in ("server.audit.write", "server.engine.push_async", "server.st_link.push_async",
                     "server.engine.notify_override_alpha", "server.exec_md.on_invalidation_trail"):
            self.stack.enter_context(mock.patch(name))
        self.stack.enter_context(mock.patch("server.exec_md.enrich_and_maybe_write", return_value={}))
        self.network = self.stack.enter_context(mock.patch("urllib.request.urlopen", side_effect=AssertionError("整合驗收禁止網路")))
        self.txt_calls = [self.stack.enter_context(mock.patch(name, side_effect=AssertionError("紙上不可存取 TXT")))
                          for name in ("server.broker._txt_dir", "server.broker.write_txt_target",
                                       "server.broker.write_order_signal", "server.broker.write_invalidation_txt")]

    def tearDown(self):
        self.network.assert_not_called()
        for call in self.txt_calls:
            call.assert_not_called()

    def send(self, signal_id, action="ENTER_LONG", lots=2, cost_usd=0.0):
        self.next_decision = decision(action, cost_usd)
        self.runtime.patch(exec={"lots": lots})
        return engine.handle_signal({"signal_id": signal_id, "symbol": "TXF", "quote": fresh_quote()})

    def test_hold_without_order_returns_to_idle(self):
        result = self.send("hold-no-order", "HOLD")
        self.assertTrue(result["gate"]["allow"])
        self.assertEqual(result["state"]["fsm"], "Idle")
        self.assertEqual(result["state"]["execution"]["status"], "idle")
        self.assertEqual(result["state"]["positions"]["account"], 0)
        self.assertIsNone(result["state"]["paper_order"])

    def test_signal_pending_sync_confirmed_and_restart_retains_receipts(self):
        pending = self.send("integration-entry")
        self.assertTrue(pending["ok"])
        self.assertTrue(pending["gate"]["allow"])
        state = pending["state"]
        self.assertEqual(state["fsm"], "AwaitingFill")
        self.assertEqual(state["execution"]["status"], "pending")
        self.assertEqual(state["positions"]["account"], 0)
        self.assertEqual(state["positions"]["strategy"], 0)
        self.assertEqual(state["positions"]["txt_target"], 2)
        pending_restart = Runtime(self.path).snapshot()
        self.assertEqual(pending_restart["paper_order"], state["paper_order"])
        confirmed = engine.sync_broker_positions()["state"]
        self.assertEqual(confirmed["positions"]["account"], 2)
        self.assertEqual(confirmed["positions"]["strategy"], 2)
        self.assertEqual(confirmed["execution"]["status"], "confirmed")
        self.assertEqual(confirmed["fsm"], "InPosition")
        restarted = Runtime(self.path).snapshot()
        for key in ("positions", "paper_order", "execution"):
            self.assertEqual(restarted[key], confirmed[key])
        self.assertEqual(len(restarted["execution"]["receipts"]), 1)

    def test_duplicate_signal_skips_model_and_preserves_order(self):
        original = self.send("duplicate-entry")["state"]
        replay = engine.handle_signal({"signal_id": "duplicate-entry", "symbol": "TXF"})
        self.assertTrue(replay["duplicate"])
        self.assertEqual(replay["state"]["paper_order"], original["paper_order"])
        self.assertEqual(replay["state"]["positions"], original["positions"])
        self.infer.assert_called_once()

    def test_reduce_and_exit_need_confirmation_before_changing_positions(self):
        self.send("open-for-reduce")
        engine.sync_broker_positions()
        reduced = self.send("reduce-one", "REDUCE", lots=1)["state"]
        self.assertEqual(reduced["positions"]["account"], 2)
        self.assertEqual(reduced["positions"]["txt_target"], 1)
        self.assertEqual(reduced["fsm"], "AwaitingFill")
        reduced = engine.sync_broker_positions()["state"]
        self.assertEqual(reduced["positions"]["account"], 1)
        closing = self.send("close-final", "EXIT", lots=1)["state"]
        self.assertEqual(closing["positions"]["account"], 1)
        self.assertEqual(closing["positions"]["txt_target"], 0)
        self.assertEqual(closing["fsm"], "AwaitingFill")
        closed = engine.sync_broker_positions()["state"]
        self.assertEqual(closed["positions"]["account"], 0)
        self.assertEqual(closed["execution"]["status"], "confirmed")
        self.assertEqual(closed["fsm"], "Flat")
        self.assertEqual(len(closed["execution"]["receipts"]), 3)

    def test_invalid_inputs_and_provider_lists_stop_before_model(self):
        before = self.runtime.snapshot()
        for body in ([], {"provider": []}, {"provider": {}}, {"provider": "unsupported"},
                     {"quote": {"price": float("nan")}}, {"symbol": "TXF/../"}):
            with self.subTest(body=body):
                out = engine.handle_signal(body)
                self.assertFalse(out["ok"])
                self.assertEqual(out["code"], "INVALID_SIGNAL")
                self.assertEqual(self.runtime.snapshot(), before)
        self.infer.assert_not_called()

    def test_mode_broker_mismatch_stops_before_model(self):
        for mode, kind in (("paper", "txt_master"), ("live", "paper")):
            with self.subTest(mode=mode, kind=kind):
                self.runtime.patch(mode=mode)
                self.config["broker"]["kind"] = kind
                before = self.runtime.snapshot()
                out = engine.handle_signal({"signal_id": "mode-mismatch"})
                self.assertFalse(out["ok"])
                self.assertEqual(out["code"], "MODE_MISMATCH")
                self.assertEqual(self.runtime.snapshot(), before)
                synced = engine.sync_broker_positions()
                self.assertEqual(synced["code"], "MODE_MISMATCH")
                self.assertEqual(self.runtime.snapshot(), before)
                panic = engine.panic_positions()
                self.assertEqual(panic["code"], "MODE_MISMATCH")
                self.assertTrue(panic["state"]["kill_switch"])
                self.assertEqual(panic["state"]["positions"], before["positions"])
        self.infer.assert_not_called()

    def test_unknown_cost_stays_unknown_across_following_decision(self):
        self.runtime.patch(costs={"session_usd": None, "day_usd": None, "month_usd": None})
        unknown = self.send("unknown-cost", "HOLD", cost_usd=None)["state"]
        for key in ("session_usd", "day_usd", "month_usd"):
            self.assertIsNone(unknown["costs"][key])
        following = self.send("known-following-cost", "HOLD", cost_usd=0.25)["state"]
        for key in ("session_usd", "day_usd", "month_usd"):
            self.assertIsNone(following["costs"][key])
        self.assertIsNone(Runtime(self.path).snapshot()["costs"]["session_usd"])

    def test_panic_serialized_entry_cancellation_survives_restart(self):
        pending = self.send("panic-entry")["state"]
        result = engine.panic_positions()
        state = result["state"]
        self.assertTrue(state["kill_switch"])
        self.assertEqual(state["fsm"], "Halted")
        self.assertEqual(state["positions"]["account"], 0)
        self.assertEqual(state["execution"]["status"], "cancelled")
        self.assertIn(pending["paper_order"]["order_id"], state["execution"]["cancelled_orders"])
        after_sync = engine.sync_broker_positions()["state"]
        self.assertEqual(after_sync["positions"]["account"], 0)
        self.assertFalse(after_sync["execution"]["receipts"])
        self.assertEqual(Runtime(self.path).snapshot()["execution"], after_sync["execution"])


if __name__ == "__main__":
    unittest.main()
