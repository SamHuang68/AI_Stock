"""隔離測試每日截止、減倉閘門及獨立風控排程；不載入真實券商。"""
from __future__ import annotations

import importlib
import shutil
import sys
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


class 不留倉測試(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="wd-deadline-")
        package_dir = Path(cls.temp.name) / "server"
        package_dir.mkdir()
        cls.package = "_wd_deadline_test"
        module = types.ModuleType(cls.package)
        module.__path__ = [str(package_dir)]
        sys.modules[cls.package] = module
        source = Path(__file__).resolve().parents[1] / "server"
        for name in ("state.py", "risk.py", "review_loop.py", "不留倉.py"):
            shutil.copyfile(source / name, package_dir / name)
        cls.clock = importlib.import_module(cls.package + ".不留倉")
        cls.risk = importlib.import_module(cls.package + ".risk")
        cls.loop = importlib.import_module(cls.package + ".review_loop")
        cls.state_module = importlib.import_module(cls.package + ".state")

    @classmethod
    def tearDownClass(cls):
        for name in list(sys.modules):
            if name == cls.package or name.startswith(cls.package + "."):
                sys.modules.pop(name)
        cls.temp.cleanup()

    def setUp(self):
        self.state = {
            "no_overnight": {"enabled": True, "force_flat_time": "13:40", "block_new_before_close_min": 15},
            "positions": {"account": 2},
            "exec": {"lots": 2},
            "style": 30,
        }

    def now(self, hour=13, minute=40, second=0, day=10):
        return datetime(2026, 10, day, hour, minute, second, tzinfo=self.state_module.TZ8)

    def test_截止前十五分鐘邊界(self):
        before = self.clock.deadline_status(self.state, self.now(13, 24, 59))
        boundary = self.clock.deadline_status(self.state, self.now(13, 25))
        self.assertFalse(before["blocked_new"])
        self.assertTrue(boundary["blocked_new"])
        self.assertFalse(boundary["due"])

    def test_截止時刻邊界(self):
        self.assertFalse(self.clock.deadline_status(self.state, self.now(13, 39, 59))["due"])
        self.assertTrue(self.clock.deadline_status(self.state, self.now())["due"])

    def test_截止後持續到午夜(self):
        self.assertTrue(self.clock.deadline_status(self.state, self.now(23, 59, 59))["due"])
        following = self.clock.deadline_status(self.state, self.now(0, 0, day=11))
        self.assertFalse(following["due"])
        self.assertFalse(following["blocked_new"])
        self.assertEqual(following["date"], "2026-10-11")

    def test_跨午夜的提前時窗(self):
        self.state["no_overnight"]["force_flat_time"] = "00:05"
        self.assertTrue(self.clock.deadline_status(self.state, self.now(0, 0))["blocked_new"])

    def test_明確轉換時區(self):
        utc = datetime(2026, 10, 10, 5, 40, tzinfo=timezone.utc)
        self.assertTrue(self.clock.deadline_status(self.state, utc)["due"])

    def test_無時區時鐘拒絕(self):
        with self.assertRaisesRegex(ValueError, "時區"):
            self.clock.deadline_status(self.state, datetime(2026, 10, 10, 13, 40))

    def test_可停用與零分鐘(self):
        self.state["no_overnight"]["enabled"] = False
        self.assertFalse(self.clock.deadline_status(self.state, self.now())["blocked_new"])
        self.state["no_overnight"].update(enabled=True, block_new_before_close_min=0)
        self.assertFalse(self.clock.deadline_status(self.state, self.now(13, 39, 59))["blocked_new"])
        self.assertTrue(self.clock.deadline_status(self.state, self.now())["blocked_new"])

    def test_設定錯誤明確阻擋新單(self):
        for field, value in (("force_flat_time", "25:00"), ("force_flat_time", "13:40:30"),
                             ("block_new_before_close_min", -1), ("block_new_before_close_min", 1.5)):
            with self.subTest(field=field, value=value):
                state = {"no_overnight": dict(self.state["no_overnight"], **{field: value})}
                status = self.clock.deadline_status(state, self.now())
                self.assertTrue(status["blocked_new"])
                self.assertFalse(status["due"])
                self.assertTrue(status["error"])

    def test_多空新單使用同一提前時窗(self):
        for action in ("ENTER_LONG", "ENTER_SHORT"):
            self.assertTrue(self.risk.evaluate_gate(self.state, {"action": action}, now=self.now(13, 24, 59))["allow"])
            self.assertFalse(self.risk.evaluate_gate(self.state, {"action": action}, now=self.now(13, 25))["allow"])

    def test_減倉不被信心回撤追價截止阻擋(self):
        self.state.update(account={"yesterday_balance": 100, "equity": 50}, st_overlay={"spillover_prob": 0.1})
        for action in ("EXIT", "REDUCE"):
            decision = {"action": action, "confidence": 0.01, "process": {"chase_risk": "high"}}
            self.assertTrue(self.risk.evaluate_gate(self.state, decision, now=self.now())["allow"])

    def test_減倉仍尊重緊急停止(self):
        for patch in ({"kill_switch": True}, {"fsm": "Halted"}):
            state = dict(self.state, **patch)
            self.assertFalse(self.risk.evaluate_gate(state, {"action": "EXIT"}, now=self.now())["allow"])

    def test_追價仍阻擋新單(self):
        decision = {"action": "ENTER_LONG", "process": {"chase_risk": "high"}}
        self.assertFalse(self.risk.evaluate_gate(self.state, decision, now=self.now(12))["allow"])

    def test_規則模式不呼叫模型(self):
        engine = types.ModuleType(self.package + ".engine")
        engine.handle_signal = mock.Mock()
        self.state["strategy_execution"] = {"mode": "rules"}
        with mock.patch.object(self.loop.RUNTIME, "snapshot", return_value=self.state), mock.patch.dict(sys.modules, {engine.__name__: engine}):
            self.loop._tick()
        engine.handle_signal.assert_not_called()

    def test_一般模式保留原檢視(self):
        engine = types.ModuleType(self.package + ".engine")
        engine.handle_signal = mock.Mock()
        with mock.patch.object(self.loop.RUNTIME, "snapshot", return_value=self.state), mock.patch.dict(sys.modules, {engine.__name__: engine}):
            self.loop._tick()
        self.assertEqual(engine.handle_signal.call_args.args[0]["event"], "TIMED_MARKET_REVIEW")

    def test_風控使用注入時鐘(self):
        engine = types.ModuleType(self.package + ".engine")
        engine.enforce_no_overnight = mock.Mock()
        current = self.now()
        with mock.patch.dict(sys.modules, {engine.__name__: engine}):
            self.loop._risk_tick(current)
        engine.enforce_no_overnight.assert_called_once_with(current)

    def test_風控每秒喚醒且不執行檢視(self):
        event = mock.Mock()
        event.is_set.return_value = False
        event.wait.side_effect = [False, False, True]
        with mock.patch.object(self.loop, "_stop", event), mock.patch.object(self.loop, "_risk_tick") as tick, mock.patch.object(self.loop, "_tick") as review:
            self.loop._risk_loop()
        self.assertEqual(tick.call_count, 3)
        self.assertEqual(event.wait.call_args_list, [mock.call(1.0)] * 3)
        review.assert_not_called()

    def test_風控失敗有記錄且持續監控(self):
        event = mock.Mock()
        event.is_set.return_value = False
        event.wait.side_effect = [False, True]
        with mock.patch.object(self.loop, "_stop", event), mock.patch.object(self.loop, "_risk_tick", side_effect=[RuntimeError("隔離測試失敗"), None]) as tick, mock.patch.object(self.loop, "_logger") as logger:
            self.loop._risk_loop()
        self.assertEqual(tick.call_count, 2)
        logger.exception.assert_called_once()

    def test_關閉檢視仍啟動風控(self):
        with mock.patch.dict(self.loop.os.environ, {"WD_REVIEW_LOOP": "off", "WD_RISK_WATCHDOG": "1"}), mock.patch.object(self.loop, "_thread", None), mock.patch.object(self.loop, "_risk_thread", None), mock.patch.object(self.loop, "_stop", threading_event := mock.Mock()), mock.patch.object(self.loop.threading, "Thread") as thread:
            threading_event.is_set.return_value = False
            self.loop.start()
            self.assertEqual(thread.call_count, 1)
            self.assertIs(thread.call_args.kwargs["target"], self.loop._risk_loop)
            self.loop.start()
            self.assertEqual(thread.call_count, 1)

    def test_一般檢視節奏保留(self):
        self.assertEqual(self.loop._interval_sec(self.state), max(30, self.loop.INPOS_SEC))
        self.state["costs"] = {"provider": "openai"}
        self.assertEqual(self.loop._interval_sec(self.state), max(30, self.loop.INPOS_LLM_SEC))
        self.state["positions"] = {"account": 0}
        self.assertEqual(self.loop._interval_sec(self.state), max(60, self.loop.IDLE_SEC))


if __name__ == "__main__":
    unittest.main()
