"""F01 至 F04 局部回歸；沿用隔離套件，不連線或載入正式資料。"""
import importlib
import importlib.util
import subprocess
import sys
import threading
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

_spec = importlib.util.spec_from_file_location("_執行隔離基礎", Path(__file__).with_name("test_策略訊號整合.py"))
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
_base = _fixture.策略訊號整合測試


class 執行修正測試(unittest.TestCase):
    setUp = _base.setUp
    tearDown = _base.tearDown
    clear_modules = _base.clear_modules
    signal = _base.signal

    def test_停止阻擋新倉但保留減碼退出與恢復(self):
        self.engine.system_control("start")
        self.assertTrue(self.engine.handle_signal(self.signal())["gate"]["allow"])
        self.engine.system_control("stop")
        for index, action in enumerate(("ENTER_LONG", "ENTER_SHORT", "REDUCE", "EXIT")):
            with self.subTest(動作=action):
                result = self.engine.handle_signal(self.signal(signal_id=f"停止訊號{index}", action=action))
                self.assertEqual(result["gate"]["allow"], action in {"REDUCE", "EXIT"})
        self.assertEqual(self.runtime.snapshot()["positions"]["account"], 0)
        self.engine.system_control("start")
        self.assertTrue(self.engine.handle_signal(self.signal(signal_id="恢復訊號"))["gate"]["allow"])

    def test_推論途中停止後不得新增部位(self):
        self.engine.set_strategy_mode("discretionary")
        self.engine.system_control("start")
        def infer(*args):
            self.engine.system_control("stop")
            return {"action": "ENTER_LONG", "action_label": "做多", "confidence": 1, "process": {}}, None
        with patch.object(self.engine, "infer_with_fallback", side_effect=infer):
            result = self.engine.handle_signal({"event": "人工檢視", "price": 45020})
        self.assertFalse(result["gate"]["allow"])
        self.assertEqual(self.runtime.snapshot()["positions"]["account"], 0)

    def test_停止仍執行截止平倉(self):
        self.engine.system_control("start")
        self.engine.handle_signal(self.signal())
        self.engine.system_control("stop")
        self.engine.set_no_overnight({"enabled": True, "force_flat_time": "13:40", "block_new_before_close_min": 15})
        result = self.engine.enforce_no_overnight(datetime(2026, 10, 13, 13, 40, tzinfo=self.state.TZ8))
        self.assertTrue(result["ok"])
        self.assertEqual(result["state"]["positions"]["account"], 0)
        self.assertEqual(result["state"]["overnight_enforcement"]["status"], "confirmed")

    def test_送單途中回撤等待同鎖且最後維持急停平倉(self):
        self.engine.system_control("start")
        broker_module = importlib.import_module(self.package + ".broker")
        link = importlib.import_module(self.package + ".st_link")
        broker = broker_module.PaperBroker()
        entered, release, watchdog_started, flattened = [threading.Event() for _ in range(4)]
        failures = []
        original = broker.apply_intent
        def apply(state, decision, lots):
            if decision["action"] == "ENTER_LONG":
                entered.set()
                if not release.wait(3):
                    raise AssertionError("隔離送單未收到釋放通知")
            else:
                flattened.set()
            return original(state, decision, lots)
        def entry():
            try:
                self.engine.handle_signal(self.signal())
            except BaseException as exc:
                failures.append(exc)
        def watchdog():
            try:
                watchdog_started.set()
                link._enforce_daily_dd()
                self.assertTrue(link._dd_locked)
            except BaseException as exc:
                failures.append(exc)
        with patch.object(self.engine, "get_broker", return_value=broker), patch.object(broker_module, "get_broker", return_value=broker), patch.object(broker, "apply_intent", side_effect=apply), patch.object(link, "DD_FLATTEN", True), patch.object(link, "_dd_locked", False):
            first = threading.Thread(target=entry)
            second = threading.Thread(target=watchdog)
            first.start()
            try:
                self.assertTrue(entered.wait(3), "進場未到達隔離券商")
                self.runtime.patch(account={"equity": 80000})
                second.start()
                self.assertTrue(watchdog_started.wait(3))
                self.assertFalse(flattened.wait(0.15), "進場尚未結束就平倉")
            finally:
                release.set()
                first.join(4)
                if second.ident is not None:
                    second.join(4)
            self.assertFalse(first.is_alive() or second.is_alive(), "隔離執行緒未結束")
        self.assertEqual(failures, [])
        self.assertTrue(flattened.is_set())
        state = self.runtime.snapshot()
        self.assertTrue(state["kill_switch"])
        self.assertEqual(state["positions"]["account"], 0)
        self.assertEqual(state["execution"]["action"], "EXIT")
        self.assertEqual(state["fsm"], "Halted")

    def test_券商與模式兩入口來回同步設定狀態推播(self):
        for method, value, mode, kind in (("set_broker", "txt_master", "live", "txt_master"), ("set_broker", "paper", "paper", "paper"), ("set_exec_mode", "live", "live", "txt_master"), ("set_exec_mode", "paper", "paper", "paper")):
            with self.subTest(入口=method, 值=value):
                self.engine.push_async.reset_mock()
                result = getattr(self.engine, method)(value)
                config = self.config.load_config()
                state = self.runtime.snapshot()
                self.assertEqual((config["mode"], config["broker"]["kind"]), (mode, kind))
                self.assertEqual((result["mode"], result["broker"]), (mode, kind))
                self.assertEqual((state["mode"], state["account"]["broker_api"]), (mode, kind))
                self.assertEqual(state["lights"]["order_signal_file"], "ok" if kind == "txt_master" else "idle")
                self.engine.push_async.assert_called_once()
                self.assertEqual(self.engine.push_async.call_args.args[0]["mode"], mode)

    def test_跨程序拒絕相同目錄且退出後可重新取得(self):
        module = importlib.import_module(self.package + ".程序單例")
        directory = self.home / "單例資料"
        child = "import importlib.util,sys; from pathlib import Path; s=importlib.util.spec_from_file_location('lock',sys.argv[1]); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); h=m.acquire(Path(sys.argv[2]))"
        command = [sys.executable, "-B", "-c", child, module.__file__, str(directory)]
        handle = module.acquire(directory)
        try:
            blocked = subprocess.run(command, capture_output=True, timeout=5)
            self.assertNotEqual(blocked.returncode, 0)
            self.assertIn("RuntimeError", blocked.stderr.decode("utf-8", "replace"))
        finally:
            handle.close()
        accepted = subprocess.run(command, capture_output=True, timeout=5)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        with module.acquire(directory):
            self.assertTrue((directory / "wavedeck.instance.lock").is_file())


del _base

if __name__ == "__main__":
    unittest.main()
