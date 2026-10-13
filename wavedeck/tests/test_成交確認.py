"""隔離暫存目錄的送單與成交證據契約。"""
import json
import os
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from server import broker


class 成交確認測試(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        self.cfg = {"broker": {"txt_dir": self.tmp.name, "confirmation_timeout_sec": 30}}
        self.patch = patch.object(broker, "load_config", return_value=self.cfg)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.state = {"symbol": "TXF", "positions": {"account": 0, "strategy": 0, "txt_target": 0}, "exec": {"price": 100}}
        self.bridge = broker.TxtMasterBroker()
        self.write("account_position.txt", "TXF 0")
        self.write("strategy_position.txt", "TXF 0")
        self.decision = {"action": "ENTER_LONG", "strategy_id": "測試策略", "strategy_version": "1", "signal_id": "訊號一"}

    def write(self, name, text):
        path = self.path / name
        path.write_text(text, encoding="utf-8")
        return path

    def submit(self, lots=2):
        return self.bridge.apply_intent(self.state, self.decision, lots)

    def account(self, lots, execution):
        path = self.write("account_position.txt", f"TXF {lots}")
        stamp = max(time.time_ns(), execution["requested_ns"] + 1000000)
        os.utime(path, ns=(stamp, stamp))

    def ack(self, execution, status):
        data = {key: execution[key] for key in ("order_id", "symbol", "target")}
        data.update(status=status, updated_at=datetime.now(timezone.utc).isoformat())
        self.write("成交回報.json", json.dumps(data))

    def test_送出不等於成交且不覆寫外部帳戶(self):
        result = self.submit()
        self.assertEqual(result["execution"]["status"], "sent")
        self.assertFalse(result["execution"]["position_confirmed"])
        self.assertEqual((self.path / "account_position.txt").read_text(), "TXF 0")
        self.assertEqual(result["execution"]["strategy_id"], "測試策略")
        self.assertEqual((self.path / "target_position.txt").read_text(), "TXF 2\n")

    def test_新部位部分至完成僅證明倉位(self):
        result = self.submit()
        self.account(1, result["execution"])
        partial = self.bridge.sync_positions(self.state)
        self.assertEqual(partial["execution"]["status"], "partial")
        self.account(2, result["execution"])
        complete = self.bridge.sync_positions(self.state)
        self.assertTrue(complete["execution"]["position_confirmed"])
        self.assertNotEqual(complete["execution"]["status"], "filled")
        self.assertFalse(broker.execution_pending(complete["execution"]))

    def test_對應回報部分至成交(self):
        execution = self.submit()["execution"]
        self.ack(execution, "partial")
        self.assertEqual(self.bridge.sync_positions(self.state)["execution"]["status"], "partial")
        self.ack(execution, "filled")
        self.assertEqual(self.bridge.sync_positions(self.state)["execution"]["status"], "filled")

    def test_缺檔舊檔與拒單(self):
        execution = self.submit()["execution"]
        self.cfg["broker"]["confirmation_timeout_sec"] = -1
        self.assertEqual(self.bridge.sync_positions(self.state)["execution"]["status"], "stale")
        (self.path / "account_position.txt").unlink()
        self.assertEqual(self.bridge.sync_positions(self.state)["execution"]["status"], "unknown")
        self.assertFalse((self.path / "account_position.txt").exists())
        self.ack(execution, "rejected")
        self.assertEqual(self.bridge.sync_positions(self.state)["execution"]["status"], "rejected")

    def test_重複訊號與同目標不重送(self):
        first = self.submit()
        self.submit()
        self.decision["signal_id"] = "訊號二"
        second = self.submit()
        self.assertEqual(first["execution"]["order_id"], second["execution"]["order_id"])
        self.assertEqual(len((self.path / "order_signal.txt").read_text().splitlines()), 1)

    def test_反向先平倉且重播不開反向(self):
        self.write("account_position.txt", "TXF 2")
        self.decision.update(action="ENTER_SHORT")
        first = self.submit()
        self.assertEqual(first["execution"]["target"], 0)
        self.assertTrue(first["execution"]["requires_new_signal"])
        self.account(0, first["execution"])
        second = self.submit()
        self.assertEqual(second["execution"]["order_id"], first["execution"]["order_id"])

    def test_商品比對不可取其他商品(self):
        self.assertIsNone(broker._parse_lots("MTXF 3\n2330 8", "TXF"))
        self.assertEqual(broker._parse_lots("TXF=2\nMTXF 3", "TXF"), 2)
        self.assertEqual(broker._parse_lots("2330=3", "2330"), 3)

    def test_紙上明確模擬且同步不捏造(self):
        result = broker.PaperBroker().apply_intent(self.state, self.decision, 2)
        self.assertEqual(result["execution"]["status"], "filled")
        self.assertEqual(result["execution"]["evidence_kind"], "simulated")
        self.state["positions"]["txt_target"] = 3
        self.assertEqual(broker.PaperBroker().sync_positions(self.state)["positions"]["account"], 0)

    def test_示範檔不可當真實部位(self):
        (self.path / "account_position.txt").unlink()
        broker.ensure_master_seeds()
        self.assertIsNone(broker.read_txt_positions()["account"])

    def test_純讀取不建立資料夾(self):
        self.cfg["broker"]["txt_dir"] = str(self.path / "尚未建立")
        got = broker.read_txt_positions()
        self.assertFalse(got["ok"])
        self.assertFalse((self.path / "尚未建立").exists())

    def test_部分回報不受缺少部位檔誤覆寫(self):
        execution = self.submit()["execution"]
        self.ack(execution, "partial")
        (self.path / "account_position.txt").unlink()
        self.assertEqual(self.bridge.sync_positions(self.state)["execution"]["status"], "partial")

    def test_正式版本欄位保留(self):
        self.decision["version"] = "固定版本雜湊"
        execution = self.submit()["execution"]
        self.assertEqual(execution["version"], "固定版本雜湊")
        self.assertEqual(execution["strategy_version"], "固定版本雜湊")

    def test_成交回報先到仍等倉位並且之後允許新交易(self):
        first = self.submit()["execution"]
        self.ack(first, "filled")
        waiting = self.bridge.sync_positions(self.state)["execution"]
        self.assertEqual(waiting["status"], "filled")
        self.assertFalse(waiting["position_confirmed"])
        self.decision["signal_id"] = "訊號二"
        self.assertEqual(self.submit()["execution"]["order_id"], first["order_id"])
        self.account(2, first)
        confirmed = self.bridge.sync_positions(self.state)["execution"]
        self.assertTrue(confirmed["position_confirmed"])
        self.assertEqual(confirmed["evidence_kind"], "order_ack")
        self.account(0, first)
        self.decision["signal_id"] = "訊號三"
        self.assertNotEqual(self.submit()["execution"]["order_id"], first["order_id"])

    def test_純倉位核對後外部平倉可再進場(self):
        first = self.submit()["execution"]
        self.account(2, first)
        self.bridge.sync_positions(self.state)
        self.account(0, first)
        self.decision["signal_id"] = "訊號二"
        self.assertNotEqual(self.submit()["execution"]["order_id"], first["order_id"])

    def test_ACK已成交但帳戶未核對反向與異口數先平倉(self):
        for action, lots in (("ENTER_SHORT", 2), ("ENTER_LONG", 3)):
            with self.subTest(動作=action, 口數=lots):
                for filename in ("委託追蹤_TXF.json", "成交回報.json", "order_signal.txt"):
                    path = self.path / filename
                    if path.exists():
                        path.unlink()
                self.decision.update(action="ENTER_LONG", signal_id="原始訊號")
                first = self.submit()["execution"]
                self.ack(first, "filled")
                waiting = self.bridge.sync_positions(self.state)["execution"]
                self.assertTrue(broker.execution_pending(waiting))
                self.decision.update(action=action, signal_id="後續訊號")
                result = self.submit(lots)["execution"]
                self.assertEqual(result["target"], 0)
                self.assertEqual(result["action"], "EXIT")
                self.assertTrue(result["requires_new_signal"])
                self.assertEqual(result["before_account"], 0)
                lines = (self.path / "order_signal.txt").read_text().splitlines()
                self.assertEqual(len(lines), 2)
                self.assertIn("EXIT", lines[-1])
                self.submit(lots)
                self.assertEqual(len((self.path / "order_signal.txt").read_text().splitlines()), 2)

    def test_無有效帳戶讀回拒絕新進場且保留外部檔案與舊追蹤(self):
        first = self.submit()["execution"]
        self.ack(first, "filled")
        self.account(2, first)
        self.bridge.sync_positions(self.state)
        self.decision.update(action="ENTER_SHORT", signal_id="新的反向訊號")
        protected = [self.path / name for name in ("target_position.txt", "order_signal.txt", "委託追蹤_TXF.json")]
        before = {path: path.read_bytes() for path in protected}
        for content in (None, "MTXF 5", "# 示範資料，非真實帳戶\nTXF 2"):
            with self.subTest(帳戶內容=content):
                account = self.path / "account_position.txt"
                if content is None:
                    account.unlink()
                else:
                    account.write_text(content, encoding="utf-8")
                result = self.submit()
                self.assertTrue(result["blocked"])
                self.assertIn("帳戶部位無有效讀回", result["reason"])
                self.assertEqual(result["execution"]["order_id"], first["order_id"])
                self.assertIsNone(result["broker_meta"]["account"])
                for path in protected:
                    self.assertEqual(path.read_bytes(), before[path])

    def test_缺少帳戶仍允許明確急停平倉(self):
        (self.path / "account_position.txt").unlink()
        self.decision.update(action="EXIT")
        result = self.submit()
        self.assertFalse(result.get("blocked", False))
        self.assertEqual(result["execution"]["target"], 0)
        self.assertEqual(result["execution"]["status"], "sent")
        self.assertIn("EXIT", (self.path / "order_signal.txt").read_text())

    def test_舊回報和其他委託回報不可成交(self):
        execution = self.submit()["execution"]
        data = {key: execution[key] for key in ("order_id", "symbol", "target")}
        data.update(status="filled", updated_at="2020-01-01T00:00:00+00:00")
        self.write("成交回報.json", json.dumps(data))
        self.assertNotEqual(self.bridge.sync_positions(self.state)["execution"]["status"], "filled")
        data.update(order_id="其他委託", updated_at=datetime.now(timezone.utc).isoformat())
        self.write("成交回報.json", json.dumps(data))
        self.assertNotEqual(self.bridge.sync_positions(self.state)["execution"]["status"], "filled")

if __name__ == "__main__":
    unittest.main()
