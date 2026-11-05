# -*- coding: utf-8 -*-
"""紙上委託與成交收據（WD P0 第 4 片）：純模組、紙上券商、引擎整合三層。不連網、不寫正式資料。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import importlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import broker, paper_orders  # noqa: E402

CREATED = "2026-10-03T01:00:00+00:00"
FILLED = "2026-10-03T01:01:00+00:00"
PV = 200


def fixture(position=0, price=45020, **extra):
    state = {"symbol": "TXF", "exec": {"price": price}, "execution": {},
             "positions": {"ai_suggested": position, "txt_target": position, "strategy": position, "account": position},
             "paper_book": {"order": None, "receipts": {}, "intents": {}}}
    state.update(extra)
    return state


def submit(state, action="ENTER_LONG", target=3, signal_id="intent-1", strategy_id=None):
    decision = {"action": action, "signal_id": signal_id}
    if strategy_id is not None:
        decision["strategy_id"] = strategy_id
    with mock.patch("server.paper_orders._now", return_value=CREATED):
        return paper_orders.submit(state, decision, target)


def merged(state, out):
    return {**deepcopy(state), "positions": out["positions"], "paper_book": out["paper_book"]}


def receipt(state, quantity=1, receipt_id="fill-1", price=100, **extra):
    return {"receipt_id": receipt_id, "order_id": state["paper_book"]["order"]["order_id"], "symbol": "TXF",
            "quantity": quantity, "price": price, "filled_at": FILLED, "source": "paper", **extra}


def filled(state, **kwargs):
    return merged(state, paper_orders.confirm_fill(state, receipt(state, **kwargs)))


class 紙上委託純模組測試(unittest.TestCase):
    def test_受理意圖只建立待成交委託_不改輸入也不動帳戶部位(self):
        initial = fixture()
        before = deepcopy(initial)
        out = submit(initial)
        self.assertEqual(initial, before)
        self.assertTrue(out["accepted"])
        self.assertEqual(out["positions"], {"ai_suggested": 3, "txt_target": 3, "strategy": 0, "account": 0})
        order = out["paper_book"]["order"]
        self.assertEqual((order["status"], order["side"], order["quantity"], order["remaining_quantity"]), ("pending", "BUY", 3, 3))

    def test_部分與最終收據只改已成交數量_平均價加權(self):
        state = merged(fixture(), submit(fixture()))
        partial = filled(state, quantity=1, price=100)
        self.assertEqual((partial["positions"]["account"], partial["positions"]["strategy"], partial["positions"]["txt_target"]), (1, 1, 3))
        self.assertEqual(partial["paper_book"]["order"]["status"], "partial")
        final = filled(partial, quantity=2, receipt_id="fill-2", price=106)
        self.assertEqual(final["positions"]["account"], 3)
        self.assertEqual(final["paper_book"]["order"]["average_fill_price"], 104)
        self.assertEqual(final["paper_book"]["order"]["status"], "confirmed")
        self.assertEqual(final["paper_book"]["order"]["remaining_quantity"], 0)

    def test_收據經狀態檔重啟後重放不重複套用(self):
        state = merged(fixture(), submit(fixture()))
        fill = receipt(state)
        applied = merged(state, paper_orders.confirm_fill(state, fill))
        restarted = json.loads(json.dumps(applied))
        again = paper_orders.confirm_fill(restarted, fill)
        self.assertEqual(again["positions"]["account"], 1)
        self.assertEqual(len(again["paper_book"]["receipts"]), 1)
        self.assertEqual(again["paper_book"], applied["paper_book"])

    def test_舊收據重放不覆蓋新委託與最新部位(self):
        opening = merged(fixture(), submit(fixture(), target=2))
        old_fill = receipt(opening, quantity=2)
        held = merged(opening, paper_orders.confirm_fill(opening, old_fill))
        closing = merged(held, submit(held, action="EXIT", target=0, signal_id="intent-exit"))
        out = paper_orders.confirm_fill(closing, old_fill)
        self.assertEqual(out["paper_book"]["order"], closing["paper_book"]["order"])
        self.assertEqual(out["positions"], closing["positions"])

    def test_同收據識別碼內容不同被拒(self):
        state = merged(fixture(), submit(fixture()))
        fill = receipt(state)
        partial = merged(state, paper_orders.confirm_fill(state, fill))
        with self.assertRaises(ValueError):
            paper_orders.confirm_fill(partial, {**fill, "price": 101})

    def test_無效收據都被拒且不改輸入(self):
        state = merged(fixture(), submit(fixture()))
        changes = [
            {"order_id": "wrong"}, {"symbol": "MTX"}, {"quantity": 4}, {"quantity": 0}, {"quantity": -1},
            {"quantity": True}, {"quantity": 1.5}, {"quantity": float("nan")}, {"quantity": float("inf")},
            {"price": True}, {"price": 0}, {"price": -1}, {"price": float("nan")}, {"price": float("inf")},
            {"price": "100"}, {"price": None}, {"receipt_id": ""}, {"source": "live"},
            {"filled_at": "2026-10-03T01:01:00"}, {"filled_at": "2026-10-03T00:59:00+00:00"},
            {"price_basis": " "}, {"price_unknown": True},   # 未知價格的收據不可同時帶價格
        ]
        for change in changes:
            with self.subTest(change=change):
                before = deepcopy(state)
                with self.assertRaises(ValueError):
                    paper_orders.confirm_fill(state, {**receipt(state), **change})
                self.assertEqual(state, before)

    def test_延遲與亂序的部分收據可接受(self):
        state = merged(fixture(), submit(fixture()))
        later = receipt(state, filled_at="2026-10-04T01:00:00+00:00")
        partial = merged(state, paper_orders.confirm_fill(state, later))
        out = paper_orders.confirm_fill(partial, receipt(partial, receipt_id="fill-delayed"))
        self.assertEqual(out["positions"]["account"], 2)
        self.assertEqual(out["paper_book"]["order"]["updated_at"], later["filled_at"])

    def test_重複意圖不重開委託_內容不同被拒_成交後重放仍被忽略(self):
        pending = merged(fixture(), submit(fixture()))
        same = submit(pending)
        self.assertTrue(same["accepted"] and same["duplicate"])
        self.assertEqual(same["paper_book"], pending["paper_book"])
        self.assertEqual(same["positions"], pending["positions"])
        held = filled(pending, quantity=3)
        replay = submit(held)
        self.assertTrue(replay["duplicate"])
        self.assertEqual(replay["positions"]["account"], 3)
        conflict = submit(pending, target=2)
        self.assertFalse(conflict["accepted"])
        self.assertEqual(conflict["paper_book"], pending["paper_book"])

    def test_不同策略使用同一個_signal_id_互不視為重複(self):
        # 策略契約.claim 的去重範圍是 (strategy_id, signal_id)；啟用別的策略不會清掉 paper_book。
        a_enter = merged(fixture(), submit(fixture(), target=2, signal_id="entry-1", strategy_id="A"))
        a_held = filled(a_enter, quantity=2)
        a_exit = merged(a_held, submit(a_held, action="EXIT", target=0, signal_id="exit-1", strategy_id="A"))
        flat = filled(a_exit, quantity=2, receipt_id="exit-fill")
        self.assertEqual(flat["positions"]["account"], 0)
        b_enter = submit(flat, target=2, signal_id="entry-1", strategy_id="B")
        self.assertTrue(b_enter["accepted"])
        self.assertFalse(b_enter["duplicate"])
        self.assertEqual((b_enter["order"]["action"], b_enter["order"]["quantity"]), ("ENTER_LONG", 2))
        # 同一個策略重送同一個 signal_id 仍是重複；沒有策略識別的意圖維持原本以 signal_id 為準。
        self.assertTrue(submit(flat, target=2, signal_id="entry-1", strategy_id="A")["duplicate"])
        self.assertTrue(submit(flat, target=2, signal_id="entry-1", strategy_id="A")["accepted"])
        no_strategy = filled(merged(fixture(), submit(fixture(), target=2, signal_id="x")), quantity=2)
        self.assertTrue(submit(no_strategy, target=2, signal_id="x")["duplicate"])
        self.assertFalse(submit(no_strategy, target=2, signal_id="x", strategy_id="A")["duplicate"])

    def test_進行中的委託擋下進場與減碼_平倉意圖取消它再平倉(self):
        partial = filled(merged(fixture(), submit(fixture())), quantity=1)     # 目標 3、已成交 1、餘量 2
        for action, target in (("ENTER_SHORT", -2), ("REDUCE", 0)):
            with self.subTest(action=action):
                blocked = submit(partial, action=action, target=target, signal_id="other")
                self.assertFalse(blocked["accepted"])
                self.assertEqual(blocked["paper_book"], partial["paper_book"])
                self.assertEqual(blocked["positions"], partial["positions"])
        exit_out = submit(partial, action="EXIT", target=0, signal_id="exit")
        self.assertTrue(exit_out["accepted"])
        cancelled = exit_out["paper_book"]["order"]
        self.assertEqual(exit_out["order"]["action"], "EXIT")
        self.assertEqual((exit_out["order"]["quantity"], exit_out["order"]["side"]), (1, "SELL"))
        self.assertEqual(exit_out["positions"]["account"], 1)       # 平倉也要等成交收據才改部位
        self.assertEqual(cancelled["order_id"], exit_out["order"]["order_id"])
        # 被取消的舊委託：餘量全數取消、已成交的部位不受影響。
        old = paper_orders.cancel_order(partial, "測試取消")
        self.assertEqual((old["order"]["status"], old["order"]["cancelled_quantity"], old["order"]["remaining_quantity"]), ("cancelled", 2, 0))
        self.assertEqual((old["positions"]["account"], old["positions"]["txt_target"]), (1, 1))
        with self.assertRaises(ValueError):
            paper_orders.confirm_fill(merged(partial, old), receipt(partial, receipt_id="late"))

    def test_已有部位時加碼與反手由絕對目標決定(self):
        add = submit(fixture(1), target=3)
        self.assertEqual((add["order"]["side"], add["order"]["quantity"]), ("BUY", 2))
        flip = submit(fixture(1), action="ENTER_SHORT", target=-2)
        self.assertEqual((flip["order"]["side"], flip["order"]["quantity"]), ("SELL", 3))
        flipped = filled(merged(fixture(1), flip), quantity=3)
        self.assertEqual(flipped["positions"]["account"], -2)

    def test_減碼與平倉雙向(self):
        for position in (3, -3):
            with self.subTest(position=position):
                target = 2 if position > 0 else -2
                reduced = merged(fixture(position), submit(fixture(position), action="REDUCE", target=target))
                self.assertEqual(reduced["positions"]["account"], position)
                reduced = filled(reduced)
                self.assertEqual(reduced["positions"]["account"], target)
                exited = merged(reduced, submit(reduced, action="EXIT", target=0, signal_id="exit"))
                self.assertEqual(filled(exited, quantity=2, receipt_id="exit-fill")["positions"]["account"], 0)

    def test_已是目標部位不建立委託但對齊部位(self):
        state = fixture(1)
        state["positions"].update(txt_target=5, ai_suggested=5, strategy=7)      # 漂移：紙上以帳戶為準
        out = submit(state, target=1)
        self.assertTrue(out["accepted"])
        self.assertIsNone(out["order"])
        self.assertEqual(out["positions"], {"ai_suggested": 1, "txt_target": 1, "strategy": 1, "account": 1})
        self.assertIsNone(out["paper_book"]["order"])

    def test_價格未知的收據部位照記_平均價未知且不被後來的已知價洗掉(self):
        state = merged(fixture(), submit(fixture()))
        unknown = filled(state, quantity=1, price=None, price_unknown=True)
        self.assertEqual(unknown["positions"]["account"], 1)
        order = unknown["paper_book"]["order"]
        self.assertTrue(order["price_unknown"])
        self.assertIsNone(order["average_fill_price"])
        self.assertIsNone(unknown["paper_book"]["receipts"]["fill-1"]["price"])
        later = filled(unknown, quantity=2, receipt_id="fill-2", price=110)
        self.assertIsNone(later["paper_book"]["order"]["average_fill_price"])
        self.assertEqual(later["paper_book"]["order"]["status"], "confirmed")

    def test_部位漂移與超額成交被拒(self):
        pending = merged(fixture(), submit(fixture()))
        drifted = deepcopy(pending)
        drifted["positions"]["account"] = 9
        with self.assertRaises(ValueError):
            paper_orders.confirm_fill(drifted, receipt(drifted))
        completed = filled(pending, quantity=3)
        with self.assertRaisesRegex(ValueError, "不在可成交狀態"):
            paper_orders.confirm_fill(completed, receipt(completed, receipt_id="extra"))
        cancelled = merged(pending, paper_orders.cancel_order(pending, "測試取消"))
        with self.assertRaisesRegex(ValueError, "不在可成交狀態"):
            paper_orders.confirm_fill(cancelled, receipt(pending, receipt_id="late"))

    def test_帳簿只留最近的收據與意圖(self):
        state = fixture()
        for index in range(paper_orders.MAX_HISTORY + 7):
            out = submit(state, action="ENTER_LONG", target=1, signal_id=f"id-{index}")
            state = merged(state, out)
            if out["order"]:
                state = filled(state, quantity=1, receipt_id=f"r-{index}")
                state["positions"].update(account=0, strategy=0)        # 讓下一圈再進場
        book = state["paper_book"]
        self.assertEqual(len(book["intents"]), paper_orders.MAX_HISTORY)
        self.assertEqual(len(book["receipts"]), paper_orders.MAX_HISTORY)
        self.assertIn(paper_orders.intent_key({"signal_id": f"id-{paper_orders.MAX_HISTORY + 6}"}), book["intents"])
        self.assertNotIn(paper_orders.intent_key({"signal_id": "id-0"}), book["intents"])

    def test_帳簿格式不明時拒絕而不丟例外(self):
        bad = fixture(paper_book={"order": None, "receipts": [], "intents": {}})
        out = submit(bad)
        self.assertFalse(out["accepted"])
        with self.assertRaises(ValueError):
            paper_orders.confirm_fill(bad, {"source": "paper"})


class 紙上券商測試(unittest.TestCase):
    def setUp(self):
        cfg = mock.patch.object(broker, "load_config", return_value={"paper_account": {"starting_equity": 1_000_000, "point_value": PV}})
        cfg.start()
        self.addCleanup(cfg.stop)

    def apply(self, state, action="ENTER_LONG", lots=2, **decision):
        return broker.PaperBroker().apply_intent(state, {"action": action, **decision}, lots)

    def after(self, state, out):
        return {**deepcopy(state), **{k: v for k, v in out.items() if k in ("positions", "execution", "paper_book", "paper_ledger")}}

    def test_進場即時成交_收據與帳本同源(self):
        out = self.apply(fixture(), signal_id="s-1")
        self.assertEqual(out["positions"], {"ai_suggested": 2, "txt_target": 2, "strategy": 2, "account": 2})
        execution = out["execution"]
        self.assertEqual((execution["status"], execution["evidence_kind"], execution["position_confirmed"], execution["target"]),
                         ("filled", "simulated", True, 2))
        self.assertEqual((execution["confirmed_account"], execution["signal_id"], execution["before_account"]), (2, "s-1", 0))
        order = out["paper_book"]["order"]
        self.assertEqual((order["status"], order["filled_quantity"], order["average_fill_price"]), ("confirmed", 2, 45020.0))
        self.assertEqual(execution["order_id"], order["order_id"])
        saved = out["paper_book"]["receipts"][order["receipt_ids"][0]]
        self.assertEqual((saved["source"], saved["quantity"], saved["price"]), ("paper", 2, 45020.0))
        self.assertEqual((out["paper_ledger"]["position"], out["paper_ledger"]["avgPrice"]), (2, 45020.0))
        self.assertEqual(out["order_action"], "紙上模擬成交")
        self.assertFalse(broker.execution_pending(execution))

    def test_成交價出處標示是否與新鮮行情一致(self):
        now = datetime.now(timezone.utc)
        quote = {"symbol": "TXF", "price": 45020, "as_of": now.isoformat(), "source": "offline-fixture"}
        cases = {
            "新鮮行情且價格一致": (quote, "quote"),
            "行情已過期": ({**quote, "as_of": (now - timedelta(minutes=10)).isoformat()}, "signal_price"),
            "行情價格與成交價不同": ({**quote, "price": 45030}, "signal_price"),
            "舊式只帶價格的行情": ({**quote, "legacy_price_only": True}, "signal_price"),
            "沒有行情": (None, "signal_price"),
        }
        for name, (value, basis) in cases.items():
            with self.subTest(name):
                out = self.apply(fixture(quote=value))
                saved = next(iter(out["paper_book"]["receipts"].values()))
                self.assertEqual(saved["price_basis"], basis)
                self.assertEqual("quote_as_of" in saved, basis == "quote")
                if basis == "quote":
                    self.assertEqual(saved["quote_source"], "offline-fixture")

    def test_減碼實現損益_收據數量是口數差(self):
        state = fixture(3, price=45100, paper_ledger={"position": 3, "avgPrice": 45000.0, "realized": 0.0, "priceUnknown": False})
        out = self.apply(state, "REDUCE", 2, requested_lots=1, signal_id="r-1")
        self.assertEqual(out["positions"]["account"], 2)
        self.assertEqual(next(iter(out["paper_book"]["receipts"].values()))["quantity"], 1)
        self.assertEqual(out["paper_ledger"]["realized"], (45100 - 45000) * 1 * PV)
        self.assertEqual(out["paper_ledger"]["position"], 2)

    def test_反手只開一張委託_帳本先實現再開反向(self):
        state = fixture(1, price=45100, paper_ledger={"position": 1, "avgPrice": 45000.0, "realized": 0.0, "priceUnknown": False})
        out = self.apply(state, "ENTER_SHORT", 2, signal_id="f-1")
        order = out["paper_book"]["order"]
        self.assertEqual((order["side"], order["quantity"], order["target_position"]), ("SELL", 3, -2))
        self.assertEqual(out["positions"]["account"], -2)
        self.assertEqual((out["paper_ledger"]["position"], out["paper_ledger"]["avgPrice"]), (-2, 45100.0))
        self.assertEqual(out["paper_ledger"]["realized"], (45100 - 45000) * 1 * PV)

    def test_換策略後同一個_signal_id_的進場照常成交(self):
        state = fixture()
        enter_a = self.apply(state, signal_id="entry-1", strategy_id="A")
        held = self.after(state, enter_a)
        exit_a = self.apply(held, "EXIT", 0, signal_id="exit-1", strategy_id="A")
        flat = self.after(held, exit_a)
        self.assertEqual(flat["positions"]["account"], 0)
        enter_b = self.apply(flat, signal_id="entry-1", strategy_id="B")               # 與 A 同名的 signal_id
        self.assertNotIn("blocked", enter_b)
        self.assertEqual(enter_b["positions"]["account"], 2)
        self.assertEqual(enter_b["order_action"], "紙上模擬成交")
        replay = self.apply(self.after(flat, enter_b), signal_id="entry-1", strategy_id="B")
        self.assertEqual(replay["order_action"], "紙上重複意圖已忽略，維持原委託與部位")

    def test_同_signal_id_重送不重複成交_內容不同被擋(self):
        state = fixture()
        first = self.apply(state, signal_id="same")
        held = self.after(state, first)
        again = self.apply(held, signal_id="same")
        self.assertNotIn("blocked", again)
        self.assertEqual(again["positions"], first["positions"])
        self.assertEqual(again["execution"], first["execution"])
        self.assertNotIn("paper_ledger", again)
        self.assertNotIn("paper_book", again)
        self.assertEqual(again["order_action"], "紙上重複意圖已忽略，維持原委託與部位")
        conflict = self.apply(held, "ENTER_SHORT", 2, signal_id="same")
        self.assertTrue(conflict["blocked"])
        self.assertIn("已用於不同委託", conflict["reason"])

    def test_價格未知仍成交_帳本標未知而非推估(self):
        out = self.apply(fixture(price=None), signal_id="u-1")
        self.assertEqual(out["positions"]["account"], 2)
        saved = next(iter(out["paper_book"]["receipts"].values()))
        self.assertTrue(saved["price_unknown"])
        self.assertIsNone(saved["price"])
        self.assertTrue(out["execution"]["price_unknown"])
        self.assertIsNone(out["execution"]["average_fill_price"])
        self.assertTrue(out["paper_ledger"]["priceUnknown"])

    def test_非有限或非正的訊號價一律視為價格未知(self):
        for bad in (0, -5, float("nan"), float("inf"), "abc", True, None):
            with self.subTest(price=bad):
                out = self.apply(fixture(price=bad), signal_id="bad-price")
                self.assertEqual(out["positions"]["account"], 2)                  # 部位照記，不是卡在待成交
                self.assertEqual(out["paper_book"]["order"]["status"], "confirmed")
                self.assertTrue(out["execution"]["price_unknown"])
                self.assertTrue(out["paper_ledger"]["priceUnknown"])

    def test_執行紀錄遺失時同步仍補回進行中委託的狀態(self):
        with mock.patch.object(paper_orders, "confirm_fill", side_effect=ValueError("測試拒絕")):
            stuck = self.after(fixture(), self.apply(fixture(), signal_id="p-1"))
        stuck["execution"] = {}
        synced = broker.PaperBroker().sync_positions(stuck)
        self.assertEqual((synced["execution"]["status"], synced["execution"]["position_confirmed"]), ("filled", True))
        self.assertEqual(synced["execution"]["order_id"], stuck["paper_book"]["order"]["order_id"])

    def test_策略啟用後的閒置紀錄不被舊的已成交委託復活(self):
        done = self.after(fixture(), self.apply(fixture(), signal_id="old"))
        idle = {"order_id": None, "status": "idle", "position_confirmed": False}
        out = self.apply({**done, "execution": idle}, lots=2, signal_id="same-target")        # 已是目標部位
        self.assertEqual(out["execution"], idle)
        self.assertIn("已是目標部位", out["order_action"])

    def test_已是目標部位的意圖不改寫舊成交的核對時間(self):
        with mock.patch.object(broker, "now_line", return_value="2026-11-05 09:00:00"):
            done = self.after(fixture(), self.apply(fixture(), signal_id="old"))
        self.assertEqual(done["execution"]["confirmed_at"], "2026-11-05 09:00:00")
        with mock.patch.object(broker, "now_line", return_value="2026-11-05 13:00:00"):
            again = self.apply(done, lots=2, signal_id="same-target")                      # 已是目標部位
        self.assertIn("已是目標部位", again["order_action"])
        self.assertEqual(again["execution"], done["execution"])

    def test_未核對的新委託不殘留上一筆成交的核對結果(self):
        # 狀態補丁逐層合併：新的待成交委託若沒有明確清掉 confirmed_*，上一筆的核對結果會留在 execution 裡。
        first = self.apply(fixture(), signal_id="first")
        self.assertEqual(first["execution"]["confirmed_account"], 2)
        held = self.after(fixture(), first)
        with mock.patch.object(paper_orders, "confirm_fill", side_effect=ValueError("測試拒絕")):
            stuck = self.apply(held, "EXIT", 0, signal_id="exit-1")
        merged_execution = {**first["execution"], **stuck["execution"]}              # 與 RUNTIME.patch 相同的一層合併
        self.assertEqual(merged_execution["status"], "pending")
        self.assertIsNone(merged_execution["confirmed_account"])
        self.assertIsNone(merged_execution["confirmed_at"])

    def test_已是目標部位時不捏造委託_帳本仍與部位對齊(self):
        phantom = fixture(1)                                    # 預設示範部位：有部位但帳本是空的
        out = self.apply(phantom, lots=1, signal_id="n-1")
        self.assertIsNone(out["paper_book"]["order"])
        self.assertEqual(out["execution"], {})
        self.assertEqual((out["paper_ledger"]["position"], out["paper_ledger"]["avgPrice"]), (1, 45020.0))
        self.assertIn("已是目標部位", out["order_action"])

    def test_收據被拒時維持待成交_同步重試後成交(self):
        with mock.patch.object(paper_orders, "confirm_fill", side_effect=ValueError("測試拒絕")):
            out = self.apply(fixture(), signal_id="p-1")
        self.assertEqual(out["positions"]["account"], 0)
        self.assertEqual(out["positions"]["txt_target"], 2)
        self.assertEqual((out["execution"]["status"], out["execution"]["position_confirmed"]), ("pending", False))
        self.assertTrue(broker.execution_pending(out["execution"]))
        self.assertIn("測試拒絕", out["order_action"])
        self.assertNotIn("paper_ledger", out)
        pending = self.after(fixture(), out)
        synced = broker.PaperBroker().sync_positions(pending)
        self.assertEqual(synced["positions"]["account"], 2)
        self.assertEqual((synced["execution"]["status"], synced["execution"]["position_confirmed"]), ("filled", True))
        self.assertEqual(synced["execution"]["order_id"], out["execution"]["order_id"])
        self.assertEqual(synced["paper_ledger"]["position"], 2)
        self.assertEqual(synced["paper_book"]["order"]["status"], "confirmed")
        # 已成交後再同步不會重複成交。
        done = broker.PaperBroker().sync_positions(self.after(pending, synced))
        self.assertNotIn("paper_book", done)

    def test_進行中的入場被擋_急停取消它_平倉意圖取消後平倉(self):
        with mock.patch.object(paper_orders, "confirm_fill", side_effect=ValueError("測試拒絕")):
            stuck = self.after(fixture(), self.apply(fixture(), signal_id="p-1"))
        blocked = self.apply(stuck, "ENTER_SHORT", 1, signal_id="p-2")
        self.assertTrue(blocked["blocked"])
        self.assertIn("待成交", blocked["reason"])
        killed = broker.PaperBroker().sync_positions({**stuck, "kill_switch": True})
        self.assertEqual(killed["execution"]["status"], "cancelled")
        self.assertFalse(broker.execution_pending(killed["execution"]))
        self.assertEqual((killed["positions"]["account"], killed["positions"]["txt_target"]), (0, 0))
        self.assertEqual(killed["paper_book"]["order"]["cancelled_quantity"], 2)
        halted = broker.PaperBroker().sync_positions({**stuck, "fsm": "Halted"})
        self.assertEqual(halted["execution"]["status"], "cancelled")
        out = self.apply(stuck, "EXIT", 0, signal_id="p-exit")           # 已是平倉目標：取消舊委託、execution 不再待成交
        self.assertEqual(out["paper_book"]["order"]["status"], "cancelled")
        self.assertFalse(broker.execution_pending(out["execution"]))
        self.assertEqual(out["positions"]["txt_target"], 0)

    def test_部分成交後的急停平倉取消餘量並平掉已成交部位(self):
        partial = filled(merged(fixture(), submit(fixture(), target=3)), quantity=1, price=45000)
        with mock.patch.object(broker, "get_broker", return_value=broker.PaperBroker()), \
                mock.patch.object(broker, "_txt_dir", side_effect=AssertionError("紙上不可存取 TXT")):
            out = broker.panic_flatten(partial)
        self.assertEqual((out["positions"]["account"], out["positions"]["txt_target"]), (0, 0))
        self.assertEqual(out["paper_book"]["order"]["action"], "EXIT")
        self.assertEqual(out["paper_book"]["order"]["status"], "confirmed")
        self.assertTrue(out["execution"]["position_confirmed"])
        self.assertEqual(out["execution"]["target"], 0)

    def test_整份結果可存成狀態檔_重啟後重送同意圖仍被忽略(self):
        state = fixture()
        out = self.apply(state, signal_id="persist-1")
        restarted = json.loads(json.dumps(self.after(state, out)))
        again = self.apply(restarted, signal_id="persist-1")
        self.assertEqual(again["positions"]["account"], 2)
        self.assertEqual(again["order_action"], "紙上重複意圖已忽略，維持原委託與部位")

    def test_沒有進行中委託時同步不動帳簿_持有不動作(self):
        out = broker.PaperBroker().sync_positions(fixture(2))
        self.assertEqual(out["positions"]["account"], 2)
        self.assertNotIn("paper_book", out)
        hold = self.apply(fixture(2), "HOLD")
        self.assertNotIn("paper_book", hold)
        self.assertEqual(hold["positions"]["account"], 2)


_spec = importlib.util.spec_from_file_location("_紙上委託隔離基礎", Path(__file__).with_name("test_策略訊號整合.py"))
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
_base = _fixture.策略訊號整合測試


class 紙上委託引擎整合測試(unittest.TestCase):
    setUp = _base.setUp
    tearDown = _base.tearDown
    clear_modules = _base.clear_modules
    signal = _base.signal

    def modules(self):
        return (importlib.import_module(self.package + ".paper_orders"),
                importlib.import_module(self.package + ".broker"))

    def test_規則訊號經引擎成交_委託與收據隨狀態檔保留(self):
        self.engine.system_control("start")
        self.assertTrue(self.engine.handle_signal(self.signal())["ok"])
        state = self.runtime.snapshot()
        self.assertEqual((state["fsm"], state["positions"]["account"], state["execution"]["status"]), ("InPosition", 2, "filled"))
        book = state["paper_book"]
        self.assertEqual(book["order"]["status"], "confirmed")
        self.assertEqual(len(book["receipts"]), 1)
        orders, broker_module = self.modules()
        decision = {"action": "ENTER_LONG", "strategy_id": self.manifest["strategy_id"], "signal_id": "signal-001"}
        self.assertEqual(book["intents"][orders.intent_key(decision)]["order_id"], book["order"]["order_id"])
        # 真的重新載入狀態檔（同一個資料目錄），帳簿與冪等識別都還在。
        reloaded = self.state.Runtime().snapshot()
        self.assertEqual(reloaded["paper_book"], book)
        again = broker_module.PaperBroker().apply_intent(reloaded, decision, 2)
        self.assertEqual(again["order_action"], "紙上重複意圖已忽略，維持原委託與部位")
        self.assertEqual(again["positions"]["account"], 2)

    def test_收據被拒時引擎為待成交_下一次同步後成交(self):
        self.engine.system_control("start")
        orders, _ = self.modules()
        with mock.patch.object(orders, "confirm_fill", side_effect=ValueError("測試拒絕")):
            self.engine.handle_signal(self.signal())
        stuck = self.runtime.snapshot()
        self.assertEqual((stuck["fsm"], stuck["positions"]["account"], stuck["positions"]["txt_target"]), ("Arming", 0, 2))
        self.assertEqual(stuck["execution"]["status"], "pending")
        synced = self.engine.sync_broker_positions()["state"]
        self.assertEqual((synced["fsm"], synced["positions"]["account"], synced["execution"]["status"]), ("InPosition", 2, "filled"))
        self.assertEqual(synced["paper_ledger"]["position"], 2)
        self.assertEqual(synced["paper_book"]["order"]["status"], "confirmed")

    def test_待成交時急停取消入場並鎖定(self):
        self.engine.system_control("start")
        orders, _ = self.modules()
        with mock.patch.object(orders, "confirm_fill", side_effect=ValueError("測試拒絕")):
            self.engine.handle_signal(self.signal())
        result = self.engine.panic()
        state = result["state"]
        self.assertTrue(state["kill_switch"])
        self.assertEqual((state["fsm"], state["positions"]["account"], state["positions"]["txt_target"]), ("Halted", 0, 0))
        self.assertEqual(state["paper_book"]["order"]["status"], "cancelled")
        self.assertFalse(self.modules()[1].execution_pending(state["execution"]))


# 借用既有整合測試的 setUp 之後，把基底類別從模組命名空間拿掉：否則載入器會把它自己的測試在這個模組再跑一遍。
del _base


if __name__ == "__main__":
    unittest.main()
