"""策略訊號與執行層整合：暫存副本、真實稽核資料庫、禁止對外連線。"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import shutil
import socket
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT.parent / "tests" / "fixtures" / "固定策略版本.json"


class 策略訊號整合測試(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="wd_strategy_")
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        shutil.copytree(ROOT / "server", self.home / "server", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        self.package = "_wd_strategy_" + uuid.uuid4().hex
        spec = importlib.util.spec_from_file_location(self.package, self.home / "server" / "__init__.py", submodule_search_locations=[str(self.home / "server")])
        module = importlib.util.module_from_spec(spec)
        sys.modules[self.package] = module
        spec.loader.exec_module(module)
        self.addCleanup(self.clear_modules)
        self.env = patch.dict(os.environ, {"WD_EXEC_MD_ENABLED": "0"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.connection = patch.object(socket.socket, "connect", side_effect=AssertionError("隔離測試禁止網路連線"))
        self.network = self.connection.start()
        self.addCleanup(self.connection.stop)
        self.engine = importlib.import_module(self.package + ".engine")
        self.state = importlib.import_module(self.package + ".state")
        self.config = importlib.import_module(self.package + ".config")
        self.contracts = importlib.import_module(self.package + ".策略契約")
        self.runtime = self.state.RUNTIME
        cfg = self.config.load_config()
        cfg.update(mode="paper")
        cfg["broker"].update(kind="paper", txt_dir=str(self.home / "master"))
        cfg["exec_md"].update(enabled=False, mode="template")
        self.config.save_config(cfg)
        for name in ("push_async", "notify_override_alpha"):
            active = patch.object(self.engine, name)
            active.start()
            self.addCleanup(active.stop)
        active = patch.object(self.engine, "infer_with_fallback", side_effect=AssertionError("規則模式不可呼叫 AI"))
        self.infer = active.start()
        self.addCleanup(active.stop)
        self.runtime.patch(fsm="Flat", mode="paper", kill_switch=False,
                           positions={"account": 0, "strategy": 0, "txt_target": 0, "ai_suggested": 0},
                           account={"equity": 100000, "yesterday_balance": 100000, "reference": False},
                           exec={"price": 45020, "lots": 2},
                           st_link={"status": "up", "fail_safe": False},
                           st_overlay={"fail_safe": False, "delever": False, "spillover_prob": 0.8},
                           no_overnight={"enabled": False})
        self.manifest = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.contracts.register(self.manifest)
        self.engine.activate_strategy({"strategy_id": self.manifest["strategy_id"], "version": self.manifest["version"]})

    def clear_modules(self):
        for name in list(sys.modules):
            if name == self.package or name.startswith(self.package + "."):
                del sys.modules[name]

    def tearDown(self):
        self.network.assert_not_called()
        self.infer.assert_not_called()

    def signal(self, **overrides):
        payload = {"strategy_id": self.manifest["strategy_id"], "version": self.manifest["version"],
                   "symbol": self.manifest["context"]["symbol"], "timeframe": self.manifest["execution"]["timeframe"],
                   "signal_id": "signal-001", "action": "ENTER_LONG", "lots": 2, "price": 45020,
                   "bar_close_time": datetime.now(timezone.utc).isoformat(), "source": "固定策略測試"}
        payload.update(overrides)
        return payload

    def txt(self, account=0):
        self.engine.set_broker("txt_master")
        path = self.home / "master"
        path.mkdir(parents=True, exist_ok=True)
        symbol = self.manifest["context"]["symbol"]
        for name in ("account_position.txt", "strategy_position.txt", "target_position.txt"):
            (path / name).write_text(f"{symbol} {account}\n", encoding="utf-8")
        self.runtime.patch(positions={"account": account, "strategy": account, "txt_target": account, "ai_suggested": account})
        return path

    def sent(self):
        path = self.home / "master" / "order_signal.txt"
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def rejected(self, body):
        try:
            result = self.engine.handle_signal(body)
        except ValueError:
            return
        self.assertTrue(result.get("blocked") or result.get("ok") is False, result)

    def test_規則執行不呼叫AI且紙上成交標示模擬(self):
        result = self.engine.handle_signal(self.signal())
        self.assertTrue(result["ok"])
        self.assertEqual(result["decision"]["action"], "ENTER_LONG")
        state = self.runtime.snapshot()
        self.assertEqual(state["fsm"], "InPosition")
        self.assertEqual(state["execution"]["status"], "filled")
        self.assertEqual(state["execution"]["evidence_kind"], "simulated")
        self.assertEqual(state["execution"]["version"], self.manifest["version"])
        self.assertEqual(state["positions"]["account"], 2)

    def test_版本商品週期不符與過期訊號拒絕送單(self):
        self.txt()
        for key, value in (("version", "0" * 64), ("symbol", "WRONG"), ("timeframe", "999m"),
                           ("bar_close_time", (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat())):
            with self.subTest(欄位=key):
                self.rejected(self.signal(**{key: value}))
                self.assertEqual(self.sent(), [])
                self.assertEqual(self.runtime.snapshot()["positions"]["account"], 0)

    def test_相同訊號重播不重送且修改內容拒絕(self):
        self.txt()
        payload = self.signal()
        first = self.engine.handle_signal(payload)
        first_id = self.runtime.snapshot()["execution"]["order_id"]
        second = self.engine.handle_signal(payload)
        self.assertEqual(self.runtime.snapshot()["execution"]["order_id"], first_id)
        self.assertEqual(len(self.sent()), 1)
        self.rejected({**payload, "action": "ENTER_SHORT"})
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(first["decision"]["action"], "ENTER_LONG")
        self.assertEqual(second["decision"]["action"], "ENTER_LONG")

    def test_風險阻擋保留原動作且不送單(self):
        self.txt()
        self.runtime.patch(account={"equity": 80000})
        result = self.engine.handle_signal(self.signal())
        self.assertEqual(result["decision"]["action"], "ENTER_LONG")
        self.assertFalse(result["gate"]["allow"])
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.runtime.snapshot()["positions"]["account"], 0)

    def test_TXT待成交維持Arming且回讀後才持倉(self):
        path = self.txt()
        self.engine.handle_signal(self.signal())
        state = self.runtime.snapshot()
        self.assertEqual(state["fsm"], "Arming")
        self.assertEqual(state["execution"]["status"], "sent")
        self.assertEqual(state["positions"]["account"], 0)
        account = path / "account_position.txt"
        account.write_text(f'{state["symbol"]} 2\n', encoding="utf-8")
        stamp = state["execution"]["requested_ns"] + 1000000
        os.utime(account, ns=(stamp, stamp))
        self.engine.sync_broker_positions()
        updated = self.runtime.snapshot()
        self.assertEqual(updated["fsm"], "InPosition")
        self.assertTrue(updated["execution"]["position_confirmed"])
        self.assertNotEqual(updated["execution"]["status"], "filled")

    def test_ACK先到帳戶未更新仍維持Arming(self):
        path = self.txt()
        self.engine.handle_signal(self.signal())
        receipt = self.runtime.snapshot()["execution"]
        ack = {key: receipt[key] for key in ("order_id", "symbol", "target")}
        ack.update(status="filled", updated_at=datetime.now(timezone.utc).isoformat())
        (path / "成交回報.json").write_text(json.dumps(ack), encoding="utf-8")
        self.engine.sync_broker_positions()
        state = self.runtime.snapshot()
        self.assertEqual(state["execution"]["status"], "filled")
        self.assertEqual(state["positions"]["account"], 0)
        self.assertEqual(state["fsm"], "Arming")

    def test_不留倉截止送平倉一次且跨日保存待確認(self):
        self.txt(account=2)
        self.engine.set_no_overnight({"enabled": True, "force_flat_time": "13:40", "block_new_before_close_min": 15})
        now = datetime(2026, 10, 12, 13, 40, tzinfo=self.state.TZ8)
        self.engine.enforce_no_overnight(now)
        state = self.runtime.snapshot()
        self.assertEqual(state["execution"]["action"], "EXIT")
        self.assertEqual(state["fsm"], "Reducing")
        self.assertEqual(state["positions"]["account"], 2)
        self.assertEqual(len(self.sent()), 1)
        order_id = state["execution"]["order_id"]
        self.engine.enforce_no_overnight(now + timedelta(minutes=1))
        self.engine.enforce_no_overnight(now + timedelta(days=1))
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(self.runtime.snapshot()["execution"]["order_id"], order_id)
        self.assertEqual(self.runtime.snapshot()["positions"]["account"], 2)

    def test_急停時不留倉不自動送單(self):
        self.txt(account=2)
        self.runtime.set_kill(True)
        self.engine.set_no_overnight({"enabled": True, "force_flat_time": "13:40"})
        self.engine.enforce_no_overnight(datetime(2026, 10, 12, 13, 40, tzinfo=self.state.TZ8))
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.runtime.snapshot()["fsm"], "Halted")

    def test_相同收K不同識別碼與逆序舊K拒絕(self):
        self.txt()
        payload = self.signal(bar_close_time=(datetime.now(timezone.utc) - timedelta(seconds=20)).isoformat())
        self.engine.handle_signal(payload)
        order_id = self.runtime.snapshot()["execution"]["order_id"]
        self.rejected({**payload, "signal_id": "same-bar-new-id", "action": "EXIT"})
        self.rejected({**payload, "signal_id": "older-bar-new-id", "action": "EXIT",
                       "bar_close_time": (datetime.fromisoformat(payload["bar_close_time"]) - timedelta(seconds=10)).isoformat()})
        self.assertEqual(len(self.sent()), 1)
        self.assertEqual(self.runtime.snapshot()["execution"]["order_id"], order_id)

    def test_前日三次後完成不阻擋翌日重新平倉(self):
        path = self.txt(account=2)
        self.engine.set_no_overnight({"enabled": True, "force_flat_time": "13:40"})
        now = datetime(2026, 10, 12, 13, 40, tzinfo=self.state.TZ8)
        self.engine.enforce_no_overnight(now)
        for attempt in (1, 2):
            receipt = self.runtime.snapshot()["execution"]
            report = {key: receipt[key] for key in ("order_id", "symbol", "target")}
            report.update(status="rejected", updated_at=datetime.now(timezone.utc).isoformat())
            (path / "成交回報.json").write_text(json.dumps(report), encoding="utf-8")
            self.engine.enforce_no_overnight(now + timedelta(seconds=31 * attempt))
        self.assertEqual(len(self.sent()), 3)
        receipt = self.runtime.snapshot()["execution"]
        account = path / "account_position.txt"
        account.write_text(f'{receipt["symbol"]} 0\n', encoding="utf-8")
        stamp = receipt["requested_ns"] + 1000000
        os.utime(account, ns=(stamp, stamp))
        self.engine.enforce_no_overnight(now + timedelta(seconds=63))
        completed = self.runtime.snapshot()["overnight_enforcement"]
        self.assertEqual(completed["status"], "confirmed")
        self.assertEqual(completed["attempts"], 3)
        account.write_text(f'{receipt["symbol"]} 2\n', encoding="utf-8")
        self.engine.enforce_no_overnight(now + timedelta(days=1))
        next_day = self.runtime.snapshot()["overnight_enforcement"]
        self.assertEqual(next_day["attempts"], 1)
        self.assertEqual(next_day["status"], "pending")
        self.assertEqual(next_day["date"], "2026-10-13")
        self.assertEqual(len(self.sent()), 4)

    def test_券商缺少帳戶拒絕須傳遞且不得用舊快照宣告成交(self):
        path = self.txt(account=2)
        before = self.runtime.snapshot()
        (path / "account_position.txt").unlink()
        result = self.engine.handle_signal(self.signal(action="ENTER_SHORT"))
        self.assertTrue(result["blocked"])
        self.assertFalse(result["gate"]["allow"])
        self.assertEqual(result["decision"]["action"], "ENTER_SHORT")
        self.assertIn("帳戶部位無有效讀回", "；".join(result["gate"]["reasons"]))
        self.assertEqual(self.sent(), [])
        self.assertEqual(self.runtime.snapshot()["fsm"], before["fsm"])
        self.assertEqual(self.runtime.snapshot()["positions"], before["positions"])
        self.assertFalse((path / "委託追蹤_TXF.json").exists())

    def test_不留倉設定重啟仍保留(self):
        self.engine.set_no_overnight({"enabled": True, "force_flat_time": "14:05", "block_new_before_close_min": 23})
        restored = self.state.Runtime().snapshot()["no_overnight"]
        self.assertEqual(restored["force_flat_time"], "14:05")
        self.assertEqual(restored["block_new_before_close_min"], 23)


if __name__ == "__main__":
    unittest.main()
