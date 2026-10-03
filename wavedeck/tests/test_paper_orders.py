# -*- coding: utf-8 -*-
"""紙上委託／成交對帳的隔離測試，不使用真實資料或券商。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# 避免初次匯入全域 Runtime 讀到工作樹內的實際資料。
with mock.patch.object(Path, "is_file", return_value=False):
    from server.broker import PaperBroker, panic_flatten
from server.paper_orders import apply_paper_intent, confirm_fill


CREATED = "2026-10-03T01:00:00+00:00"
FILLED = "2026-10-03T01:01:00+00:00"


def fixture(position=0):
    return {
        "mode": "paper", "symbol": "TXF", "kill_switch": False,
        "positions": {"ai_suggested": position, "txt_target": position, "strategy": position, "account": position},
        "account": {"equity": None}, "exec": {"price": 99999},
        "paper_order": None, "execution": {"status": "idle", "receipts": {}, "intents": {}},
    }


def submit(state, action="ENTER_LONG", lots=3, intent_id="intent-1"):
    with mock.patch("server.paper_orders._now", return_value=CREATED):
        out = apply_paper_intent(state, {"action": action, "intent_id": intent_id}, lots)
    return {**deepcopy(state), **out}


def receipt(state, quantity=1, receipt_id="fill-1", price=100):
    return {"receipt_id": receipt_id, "order_id": state["paper_order"]["order_id"],
            "symbol": "TXF", "quantity": quantity, "price": price,
            "filled_at": FILLED, "source": "paper"}


def filled_state(state, **kwargs):
    return {**deepcopy(state), **confirm_fill(state, receipt(state, **kwargs))}


class PaperOrderTests(unittest.TestCase):
    def test_intent_is_pending_and_input_is_unchanged(self):
        initial = fixture()
        before = deepcopy(initial)
        state = submit(initial)
        self.assertEqual(initial, before)
        self.assertEqual(state["positions"], {"ai_suggested": 3, "txt_target": 3, "strategy": 0, "account": 0})
        self.assertEqual(state["execution"]["status"], "pending")
        self.assertEqual(state["paper_order"]["remaining_quantity"], 3)
        self.assertIsNone(state["account"]["equity"])

    def test_partial_and_final_receipts_update_only_filled_quantity(self):
        state = submit(fixture())
        partial = filled_state(state, quantity=1, price=100)
        self.assertEqual(partial["positions"]["account"], 1)
        self.assertEqual(partial["positions"]["strategy"], 1)
        self.assertEqual(partial["positions"]["txt_target"], 3)
        self.assertEqual(partial["execution"]["status"], "partial")
        final = filled_state(partial, quantity=2, receipt_id="fill-2", price=106)
        self.assertEqual(final["positions"]["account"], 3)
        self.assertEqual(final["paper_order"]["average_fill_price"], 104)
        self.assertEqual(final["execution"]["status"], "confirmed")
        self.assertEqual(final["paper_order"]["remaining_quantity"], 0)

    def test_receipt_replay_survives_restart_and_does_not_reapply(self):
        state = submit(fixture())
        fill = receipt(state)
        applied = {**state, **confirm_fill(state, fill)}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "paper-state.json"
            path.write_text(json.dumps(applied), encoding="utf-8")
            restarted = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(confirm_fill(restarted, fill), confirm_fill(applied, fill))
        self.assertEqual(confirm_fill(restarted, fill)["positions"]["account"], 1)
        self.assertEqual(len(confirm_fill(restarted, fill)["execution"]["receipts"]), 1)

    def test_old_duplicate_does_not_replace_new_order_or_latest_account(self):
        opening = submit(fixture(), lots=2)
        old_fill = receipt(opening, quantity=2)
        held = {**opening, **confirm_fill(opening, old_fill)}
        closing = submit(held, action="EXIT", lots=0, intent_id="intent-exit")
        closing["account"]["equity"] = 123456
        out = confirm_fill(closing, old_fill)
        self.assertEqual(out["paper_order"], closing["paper_order"])
        self.assertEqual(out["positions"], closing["positions"])
        self.assertEqual(out["account"]["equity"], 123456)

    def test_reused_receipt_id_with_conflicting_payload_is_rejected(self):
        state = submit(fixture())
        fill = receipt(state)
        partial = {**state, **confirm_fill(state, fill)}
        with self.assertRaises(ValueError):
            confirm_fill(partial, {**fill, "price": 101})

    def test_invalid_receipts_leave_input_untouched(self):
        state = submit(fixture())
        changes = [
            {"order_id": "wrong"}, {"symbol": "MTX"}, {"quantity": 4},
            {"quantity": 0}, {"quantity": -1}, {"quantity": True}, {"quantity": 1.5},
            {"quantity": float("nan")}, {"quantity": float("inf")},
            {"price": True}, {"price": 0}, {"price": -1},
            {"price": float("nan")}, {"price": float("inf")}, {"price": "100"},
            {"receipt_id": ""}, {"source": "live"}, {"filled_at": "2026-10-03T01:01:00"},
            {"filled_at": "2026-10-03T00:59:00+00:00"},
        ]
        for change in changes:
            with self.subTest(change=change):
                before = deepcopy(state)
                with self.assertRaises(ValueError):
                    confirm_fill(state, {**receipt(state), **change})
                self.assertEqual(state, before)

    def test_delayed_and_out_of_order_partial_receipts_are_accepted(self):
        state = submit(fixture())
        later = {**receipt(state), "filled_at": "2026-10-04T01:00:00+00:00"}
        partial = {**state, **confirm_fill(state, later)}
        earlier = receipt(partial, receipt_id="fill-delayed")
        out = confirm_fill(partial, earlier)
        self.assertEqual(out["positions"]["account"], 2)
        self.assertEqual(out["paper_order"]["updated_at"], later["filled_at"])

    def test_replayed_intent_survives_confirmed_fill(self):
        pending = submit(fixture())
        same = submit(pending)
        self.assertTrue(same["accepted"])
        self.assertEqual(same["paper_order"], pending["paper_order"])
        held = filled_state(pending, quantity=3)
        replay = submit(held)
        self.assertEqual(replay["paper_order"], held["paper_order"])
        self.assertEqual(replay["positions"]["account"], 3)
        conflict = submit(pending, lots=2)
        self.assertFalse(conflict["accepted"])
        self.assertEqual(conflict["paper_order"], pending["paper_order"])

    def test_pending_and_open_position_cannot_be_overwritten(self):
        pending = submit(fixture())
        blocked = submit(pending, action="ENTER_SHORT", intent_id="intent-2")
        self.assertFalse(blocked["accepted"])
        self.assertEqual(blocked["paper_order"], pending["paper_order"])
        self.assertEqual(blocked["positions"], pending["positions"])
        for position in (3, -3):
            with self.subTest(position=position):
                held = fixture(position)
                out = submit(held, intent_id="new-entry")
                self.assertFalse(out["accepted"])
                self.assertEqual(out["positions"], held["positions"])

    def test_reduce_and_exit_for_both_directions(self):
        for position in (3, -3):
            with self.subTest(position=position):
                reduced = submit(fixture(position), action="REDUCE", lots=1)
                self.assertEqual(reduced["positions"]["account"], position)
                self.assertEqual(abs(reduced["positions"]["txt_target"]), 2)
                reduced = filled_state(reduced)
                self.assertEqual(abs(reduced["positions"]["account"]), 2)
                exited = submit(reduced, action="EXIT", lots=0, intent_id="exit")
                self.assertEqual(exited["positions"]["txt_target"], 0)
                self.assertEqual(abs(exited["positions"]["account"]), 2)
                exited = filled_state(exited, quantity=2, receipt_id="exit-fill")
                self.assertEqual(exited["positions"]["account"], 0)

    def test_reduce_over_position_and_invalid_lots_are_rejected(self):
        self.assertFalse(submit(fixture(2), action="REDUCE", lots=3)["accepted"])
        for value in (0, -1, True, 1.5, float("nan"), float("inf")):
            with self.subTest(value=value):
                self.assertFalse(submit(fixture(), lots=value)["accepted"])

    def test_missing_order_never_copies_target_into_confirmed_positions(self):
        state = fixture()
        state["positions"].update(ai_suggested=7, txt_target=7)
        out = PaperBroker().sync_positions(state)
        self.assertEqual(out["positions"], state["positions"])
        self.assertEqual(out["account"]["position_sync"], "drift")

    def test_sync_waits_for_valid_quote_and_ignores_exec_price(self):
        state = submit(fixture())
        now = datetime.now(timezone.utc)
        valid = {"symbol": "TXF", "price": 100, "as_of": (now - timedelta(seconds=1)).isoformat(), "source": "offline-fixture", "demo": True}
        bad = [None, {**valid, "source": "unknown"}, {**valid, "symbol": "MTX"},
               {**valid, "price": float("nan")}, {**valid, "price": True},
               {**valid, "as_of": (now - timedelta(minutes=10)).isoformat()},
               {**valid, "as_of": (now + timedelta(minutes=10)).isoformat()},
               {"quality": "fresh", "entry_allowed": True, "price": 100}]
        for quote in bad:
            with self.subTest(quote=quote):
                out = PaperBroker().sync_positions({**state, "quote": quote})
                self.assertEqual(out["execution"]["status"], "pending")
                self.assertEqual(out["positions"]["account"], 0)
                self.assertFalse(out["execution"]["receipts"])
        out = PaperBroker().sync_positions({**state, "quote": valid})
        self.assertEqual(out["execution"]["status"], "confirmed")
        self.assertEqual(out["positions"]["account"], 3)
        saved = next(iter(out["execution"]["receipts"].values()))
        self.assertEqual(saved["price"], 100)
        self.assertEqual(saved["source"], "paper")
        self.assertEqual(saved["quote_source"], "offline-fixture")

    def test_state_drift_and_completed_overfill_are_rejected(self):
        pending = submit(fixture())
        drifted = deepcopy(pending)
        drifted["positions"]["account"] = 9
        with self.assertRaises(ValueError):
            confirm_fill(drifted, receipt(drifted))
        completed = filled_state(pending, quantity=3)
        with self.assertRaises(ValueError):
            confirm_fill(completed, receipt(completed, receipt_id="extra"))

    def test_panic_cancels_pending_entry_and_never_accesses_txt(self):
        pending = submit(fixture())
        with mock.patch("server.broker._txt_dir", side_effect=AssertionError("紙上不可存取 TXT")), mock.patch("server.broker.load_config", side_effect=AssertionError("紙上不可讀取實盤設定")):
            out = panic_flatten(pending)
        self.assertEqual(out["positions"]["account"], 0)
        self.assertEqual(out["paper_order"]["status"], "cancelled")
        self.assertEqual(out["paper_order"]["cancelled_quantity"], 3)
        self.assertIn(pending["paper_order"]["order_id"], out["execution"]["cancelled_orders"])
        with self.assertRaises(ValueError):
            confirm_fill({**pending, **out}, receipt(pending))

    def test_panic_preserves_partial_position_and_queues_exit(self):
        partial = filled_state(submit(fixture()))
        out = panic_flatten(partial)
        self.assertEqual(out["positions"]["account"], 1)
        self.assertEqual(out["positions"]["strategy"], 1)
        self.assertEqual(out["positions"]["txt_target"], 0)
        self.assertEqual(out["paper_order"]["action"], "EXIT")
        self.assertEqual(out["execution"]["status"], "pending")
        self.assertEqual(out["paper_order"]["quantity"], 1)
        self.assertEqual(out["execution"]["cancelled_orders"][partial["paper_order"]["order_id"]]["cancelled_quantity"], 2)

    def test_kill_or_halt_cancels_restarted_pending_entry(self):
        for changes in ({"kill_switch": True}, {"fsm": "Halted"}):
            with self.subTest(changes=changes):
                state = {**submit(fixture()), **changes}
                out = PaperBroker().sync_positions(state)
                self.assertEqual(out["execution"]["status"], "cancelled")
                self.assertEqual(out["positions"]["account"], 0)

    def test_receipts_cannot_be_applied_in_live_mode(self):
        state = {**submit(fixture()), "mode": "live"}
        with self.assertRaises(ValueError):
            confirm_fill(state, receipt(state))
        self.assertFalse(apply_paper_intent(state, {"action": "EXIT"}, 0)["accepted"])


if __name__ == "__main__":
    unittest.main()
