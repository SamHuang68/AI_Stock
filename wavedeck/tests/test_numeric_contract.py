#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""數值契約（WD P0 第 2a 片）：下單閘門遇到非有限值要失敗關閉，有效值與 None 的行為不變；完全離線。

NaN 的任何比較都是 False，`max(0.0, nan)` 是 0.0：沒有這層契約時，NaN 信心度會跳過門檻、
NaN 權益會讓單日回撤鎖看起來「量過、0%」卻永不觸發。"""
from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from server import risk  # noqa: E402
from server.data_contract import finite_number  # noqa: E402
from server.state import TZ8  # noqa: E402

NAN, INF = float("nan"), float("inf")
NOON = datetime(2026, 11, 4, 11, 0, tzinfo=TZ8)          # 不留倉時窗之前；規則另被關閉，不靠這個時間


def base_state(**overrides):
    state = {"kill_switch": False, "fsm": "Idle", "account": {"yesterday_balance": 100.0, "equity": 100.0},
             "no_overnight": {"enabled": False}, "st_overlay": {}, "style": 50, "exec": {"lots": 1, "price": 45000.0}}
    state.update(overrides)
    return state


def decision(action="ENTER_LONG", **fields):
    return {"action": action, "confidence": 0.9, "process": {}, **fields}


def gate(state=None, dec=None):
    return risk.evaluate_gate(state if state is not None else base_state(), dec if dec is not None else decision(), now=NOON)


class FiniteNumberTests(unittest.TestCase):
    def test_valid_numbers_and_numeric_strings(self):
        for value, expected in ((1, 1.0), (0, 0.0), (-2.5, -2.5), ("1.5", 1.5), (" 7 ", 7.0), (10 ** 20, 1e20)):
            with self.subTest(value=value):
                self.assertEqual(finite_number(value), expected)

    def test_everything_else_is_unknown_not_zero(self):
        for value in (None, True, False, NAN, INF, -INF, "nan", "inf", "abc", "", [], {}, 10 ** 400):
            with self.subTest(value=repr(value)[:20]):
                self.assertIsNone(finite_number(value))


class AccountTests(unittest.TestCase):
    def test_valid_account_is_unchanged(self):
        state = base_state(account={"yesterday_balance": 100.0, "equity": 90.0})
        self.assertTrue(risk.daily_dd_known(state))
        self.assertFalse(risk.daily_dd_invalid(state))
        self.assertAlmostEqual(risk.daily_dd_ratio(state), 0.10)

    def test_missing_values_are_unknown_not_invalid(self):
        for account in ({"equity": None, "yesterday_balance": 100.0}, {"equity": 90.0}, {}):
            with self.subTest(account=account):
                state = base_state(account=account)
                self.assertFalse(risk.daily_dd_known(state))
                self.assertFalse(risk.daily_dd_invalid(state))

    def test_non_finite_values_are_neither_known_nor_zero_drawdown(self):
        for bad in (NAN, INF, -INF, True, "abc"):
            for key in ("equity", "yesterday_balance"):
                with self.subTest(bad=repr(bad), key=key):
                    state = base_state(account={"yesterday_balance": 100.0, "equity": 90.0, key: bad})
                    self.assertFalse(risk.daily_dd_known(state))     # 不能是「已量測」
                    self.assertTrue(risk.daily_dd_invalid(state))
                    self.assertEqual(risk.daily_dd_ratio(state), 0.0)  # 不丟例外

    def test_reference_accounts_are_never_invalid(self):
        for account in ({"reference": True, "equity": NAN, "yesterday_balance": 100.0},
                        {"source": "wave_ai_ref", "equity": NAN, "yesterday_balance": 100.0}):
            with self.subTest(account=account):
                state = base_state(account=account)
                self.assertFalse(risk.daily_dd_known(state))
                self.assertFalse(risk.daily_dd_invalid(state))


class GateTests(unittest.TestCase):
    def test_baseline_entry_is_allowed(self):
        result = gate()
        self.assertTrue(result["allow"], result)
        self.assertEqual(result["lots_effective"], 1)

    def test_invalid_equity_blocks_new_risk_but_never_exits(self):
        state = base_state(account={"yesterday_balance": 100.0, "equity": NAN})
        for action in ("ENTER_LONG", "ENTER_SHORT"):
            result = gate(state, decision(action))
            self.assertFalse(result["allow"], action)
            self.assertIn("權益資料無效", " ".join(result["reasons"]))
            self.assertNotIn("回撤未知", " ".join(result["reasons"]))     # 不和「未知」的說法互相矛盾
        for action in ("EXIT", "REDUCE", "HOLD"):
            self.assertTrue(gate(state, decision(action))["allow"], action)

    def test_unknown_equity_keeps_the_existing_warn_only_behavior(self):
        result = gate(base_state(account={"yesterday_balance": 100.0, "equity": None}))
        self.assertTrue(result["allow"], result)
        self.assertIn("單日回撤未知", " ".join(result["reasons"]))

    def test_real_drawdown_lock_still_works(self):
        result = gate(base_state(account={"yesterday_balance": 100.0, "equity": 90.0}))
        self.assertFalse(result["allow"])
        self.assertIn("單日回撤", " ".join(result["reasons"]))

    def test_non_finite_confidence_no_longer_skips_the_floor(self):
        for bad in (NAN, INF, True, "abc"):
            with self.subTest(bad=repr(bad)):
                result = gate(dec=decision(confidence=bad))
                self.assertFalse(result["allow"], result)
                self.assertIn("信心度無效", " ".join(result["reasons"]))
        self.assertTrue(gate(dec=decision("EXIT", confidence=NAN))["allow"])      # 平倉不被擋

    def test_confidence_floor_semantics_for_valid_and_missing_values_are_unchanged(self):
        self.assertTrue(gate(dec=decision(confidence=None))["allow"])             # 沒給：略過門檻（既有行為）
        self.assertTrue(gate(dec=decision(confidence=0.8))["allow"])
        self.assertTrue(gate(dec=decision(confidence="0.8"))["allow"])            # 數字字串向來可用
        low = gate(dec=decision(confidence=0.5))
        self.assertFalse(low["allow"])
        self.assertIn("信心度 50%", " ".join(low["reasons"]))

    def test_disabled_floor_is_respected(self):
        with mock.patch.object(risk, "MIN_ENTRY_CONFIDENCE", 0.0):
            self.assertTrue(gate(dec=decision(confidence=NAN))["allow"])

    def test_non_finite_overlay_numbers_do_not_crash_or_trigger_rules(self):
        for bad in (NAN, INF, "abc"):
            with self.subTest(bad=repr(bad)):
                result = gate(base_state(st_overlay={"spillover_prob": bad}))
                self.assertTrue(result["allow"], result)                           # 當未知：不觸發外溢規則
        blocked = gate(base_state(st_overlay={"spillover_prob": 0.1}))
        self.assertFalse(blocked["allow"])                                         # 有效的低外溢照舊擋

    def test_non_finite_lots_and_style_fall_back_to_defaults(self):
        for bad in (NAN, INF, -INF, "abc", True):
            with self.subTest(bad=repr(bad)):
                result = gate(base_state(exec={"lots": bad}, style=bad))
                self.assertEqual(result["lots_effective"], 1)
        self.assertEqual(gate(base_state(exec={"lots": 4}))["lots_effective"], 4)
        # style 預設 50 (<55)：追價風險高時照舊被擋；NaN 與預設同義
        high_chase = decision(process={"chase_risk": "high"})
        self.assertFalse(gate(base_state(style=NAN), high_chase)["allow"])
        self.assertFalse(gate(base_state(style=50), high_chase)["allow"])
        self.assertTrue(gate(base_state(style=70), high_chase)["allow"])

    def test_gate_does_not_modify_its_input(self):
        state = base_state(account={"yesterday_balance": 100.0, "equity": NAN}, st_overlay={"spillover_prob": NAN})
        snapshot = copy.deepcopy(state)
        gate(state)
        self.assertEqual(repr(state), repr(snapshot))                              # NaN != NaN，所以比 repr


class EngineDrawdownStatusTests(unittest.TestCase):
    """引擎端：壞資料不會被標成『已量測 0%』，也不會誤觸發鎖；狀態標籤能和『示範帳戶』區分。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        home = Path(self.temp.name)
        for target, value in (("server.state.DATA", home), ("server.state.STATE_PATH", home / "runtime_state.json"),
                              ("server.audit.DATA", home)):
            patcher = mock.patch(target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        from server import engine
        from server.state import RUNTIME, _default_state
        patcher = mock.patch.object(RUNTIME, "_state", _default_state())
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in ("push_async", "notify_override_alpha"):
            patcher = mock.patch.object(engine, name)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.engine, self.runtime = engine, RUNTIME

    def enforce(self, account):
        state = self.runtime.snapshot()
        state["account"] = account
        with mock.patch.object(self.engine, "refresh_account", return_value=state):
            return self.engine.enforce_daily_drawdown(flatten=False, already_locked=False)

    def test_corrupt_equity_is_reported_as_invalid_and_does_not_lock(self):
        locked = self.enforce({"source": "broker", "yesterday_balance": 100.0, "equity": NAN})
        snapshot = self.runtime.snapshot()
        self.assertFalse(locked)
        self.assertFalse(snapshot["kill_switch"])
        self.assertEqual(snapshot["account"]["daily_dd_status"], "unknown_invalid")
        self.assertIsNone(snapshot["account"]["daily_dd_pct"])
        self.assertEqual(snapshot["lights"]["risk_watchdog"], "warn")

    def test_reference_account_keeps_its_own_label(self):
        self.enforce({"source": "wave_ai_ref", "yesterday_balance": 100.0, "equity": NAN})
        self.assertEqual(self.runtime.snapshot()["account"]["daily_dd_status"], "unknown_reference")

    def test_valid_drawdown_is_still_measured_and_still_locks(self):
        self.assertTrue(self.enforce({"source": "broker", "yesterday_balance": 100.0, "equity": 90.0}))
        snapshot = self.runtime.snapshot()
        self.assertTrue(snapshot["kill_switch"])
        self.assertEqual(snapshot["account"]["daily_dd_status"], "measured")


if __name__ == "__main__":
    unittest.main()
