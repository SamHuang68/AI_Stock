"""策略 HTTP 與急停並行定向驗收：只操作暫存副本及動態本機埠。"""
from __future__ import annotations

import http.client
import hashlib
import importlib
import json
import socket
import shutil
import tempfile
from pathlib import Path
import sys
import threading
import unittest
from datetime import datetime
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from wavedeck.tests import test_策略訊號整合 as _策略fixture

原始連線 = socket.socket.connect


class 策略HTTP測試(unittest.TestCase):
    def setUp(self):
        self.fixture = _策略fixture.策略訊號整合測試(methodName="test_規則執行不呼叫AI且紙上成交標示模擬")
        self.fixture.setUp()
        shutil.copyfile(_策略fixture.ROOT / "VERSION", self.fixture.home / "VERSION")
        self.addCleanup(self.fixture.doCleanups)
        self.engine = self.fixture.engine
        self.runtime = self.fixture.runtime
        self.denied = []
        self.allowed_port = None

        def guarded(sock, address):
            if isinstance(address, tuple) and address == ("127.0.0.1", self.allowed_port) and self.allowed_port is not None:
                return 原始連線(sock, address)
            self.denied.append(address)
            raise AssertionError("隔離測試禁止非測試埠連線")

        guard = patch.object(socket.socket, "connect", new=guarded)
        guard.start()
        self.addCleanup(guard.stop)
        aliases = {"server" + name[len(self.fixture.package):]: module
                   for name, module in list(sys.modules.items())
                   if name == self.fixture.package or name.startswith(self.fixture.package + ".")}
        prior_path = list(sys.path)
        try:
            with patch.dict(sys.modules, aliases):
                self.server_module = importlib.import_module(self.fixture.package + ".server")
        finally:
            sys.path[:] = prior_path
        # 只建立正式 Handler，不呼叫 main，因此不啟動 review／風控／ST 連線背景工作。
        base = self.server_module.Handler

        class 安靜路由(base):
            def log_message(self, fmt, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), 安靜路由)
        self.allowed_port = self.httpd.server_address[1]
        self.assertNotEqual(self.allowed_port, 18433)
        self.http_thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.http_thread.start()
        self.addCleanup(self.stop_http)

    def stop_http(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.http_thread.join(timeout=3)
        self.assertFalse(self.http_thread.is_alive())

    def tearDown(self):
        self.fixture.infer.assert_not_called()
        self.assertEqual(self.denied, [])

    def request(self, endpoint, body=None, raw=None, length=None):
        payload = raw if raw is not None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Content-Length": str(len(payload) if length is None else length)}
        conn = http.client.HTTPConnection("127.0.0.1", self.allowed_port, timeout=3)
        try:
            conn.request("POST", endpoint, body=payload, headers=headers)
            response = conn.getresponse()
            self.assertIn("application/json", response.getheader("Content-Type"))
            return response.status, json.loads(response.read().decode("utf-8"))
        finally:
            conn.close()

    def test_四個策略端點使用真實引擎及JSON回覆(self):
        status, result = self.request("/api/strategy/register", {"manifest": self.fixture.manifest})
        self.assertEqual(status, 200)
        self.assertTrue(result["ok"])
        self.assertEqual(result["manifest"]["version"], self.fixture.manifest["version"])
        identity = {key: self.fixture.manifest[key] for key in ("strategy_id", "version")}
        status, result = self.request("/api/strategy/activate", identity)
        self.assertEqual(status, 200)
        self.assertEqual(result["state"]["strategy_execution"]["mode"], "rules")
        self.assertEqual(result["state"]["strategy_execution"]["version"], identity["version"])
        status, result = self.request("/api/strategy/mode", {"mode": "discretionary"})
        self.assertEqual(status, 200)
        self.assertEqual(result["state"]["strategy_execution"]["mode"], "discretionary")
        status, result = self.request("/api/no_overnight", {"enabled": True, "force_flat_time": "13:45", "block_new_before_close_min": 12})
        self.assertEqual(status, 200)
        self.assertEqual(result["state"]["no_overnight"]["force_flat_time"], "13:45")
        self.assertTrue(self.runtime.snapshot()["no_overnight"]["enabled"])

    def test_錯誤及過大JSON回傳400且不觸發AI(self):
        before = self.runtime.snapshot()["strategy_execution"]
        for endpoint in ("/api/strategy/register", "/api/strategy/activate", "/api/strategy/mode", "/api/no_overnight"):
            for raw, length in ((b"{", None), (b"[]", None), (b"{}", 262145)):
                with self.subTest(端點=endpoint,內容=raw,宣告長度=length):
                    status, result = self.request(endpoint, raw=raw, length=length)
                    self.assertEqual(status, 400)
                    self.assertFalse(result["ok"])
                    self.assertIsInstance(result["error"], str)
        self.assertEqual(self.runtime.snapshot()["strategy_execution"], before)

    def test_規則敘事即使自動模式也不呼叫Ollama(self):
        module = importlib.import_module(self.fixture.package + ".exec_md")
        decision = {"provider": "rules", "action": "ENTER_LONG", "action_label": "進場做多"}
        metrics = module.build_metrics(self.runtime.snapshot(), decision, {"allow": True, "gate": "ALLOW"})
        with patch.object(module, "_ollama_narrative", side_effect=AssertionError("規則模式禁止敘事模型")) as ollama:
            narrative = module.resolve_narrative(metrics, decision, {"mode": "auto", "llm_timeout_sec": 5})
        ollama.assert_not_called()
        self.assertEqual(narrative["narrative_source"], "template")

    def test_敘事阻塞時截止監控仍可平倉且舊敘事不覆寫部位(self):
        module = importlib.import_module(self.fixture.package + ".exec_md")
        narrative_entered, release_narrative = threading.Event(), threading.Event()
        watchdog_done = threading.Event()
        failures, results = [], {}

        def blocked_narrative(**kwargs):
            narrative_entered.set()
            if not release_narrative.wait(timeout=5):
                raise AssertionError("敘事未收到釋放事件")
            return {"ai_fields": {"narrative_source": "template", "reason_short": "較早的敘事完成"}}

        def signal():
            try:
                results["signal"] = self.engine.handle_signal(self.fixture.signal())
            except BaseException as error:
                failures.append(error)

        def watchdog():
            try:
                self.engine.set_no_overnight({"enabled": True, "force_flat_time": "13:40", "block_new_before_close_min": 15})
                results["watchdog"] = self.engine.enforce_no_overnight(datetime(2026, 10, 12, 13, 40, tzinfo=self.fixture.state.TZ8))
            except BaseException as error:
                failures.append(error)
            finally:
                watchdog_done.set()

        normal = threading.Thread(target=signal, daemon=True)
        monitor = threading.Thread(target=watchdog, daemon=True)
        flat_order_id = None
        with patch.object(module, "enrich_and_maybe_write", side_effect=blocked_narrative):
            try:
                normal.start()
                self.assertTrue(narrative_entered.wait(timeout=3), "一般委託尚未到達敘事階段")
                self.assertEqual(self.runtime.snapshot()["positions"]["account"], 2)
                monitor.start()
                self.assertTrue(watchdog_done.wait(timeout=3), "敘事阻塞了不留倉監控")
                flat = self.runtime.snapshot()
                self.assertEqual(flat["positions"]["account"], 0)
                self.assertEqual(flat["execution"]["action"], "EXIT")
                self.assertEqual(flat["execution"]["target"], 0)
                flat_order_id = flat["execution"]["order_id"]
            finally:
                release_narrative.set()
                normal.join(timeout=5)
                if monitor.ident is not None:
                    monitor.join(timeout=5)
            self.assertFalse(normal.is_alive())
            self.assertFalse(monitor.is_alive())
        self.assertEqual(failures, [])
        self.assertTrue(results["signal"]["ok"])
        final = self.runtime.snapshot()
        self.assertEqual(final["positions"]["account"], 0)
        self.assertEqual(final["positions"]["txt_target"], 0)
        self.assertEqual(final["execution"]["action"], "EXIT")
        self.assertEqual(final["execution"]["order_id"], flat_order_id)

    def test_一般委託持鎖時急停等待且最後平倉並鎖定(self):
        broker = importlib.import_module(self.fixture.package + ".broker")
        original_apply = broker.PaperBroker.apply_intent
        original_lock = self.engine._ORDER_LOCK
        order_entered, release_order = threading.Event(), threading.Event()
        panic_attempted, panic_acquired = threading.Event(), threading.Event()
        failures, results = [], {}

        class 觀測鎖:
            def __enter__(inner):
                is_panic = threading.current_thread().name == "測試急停"
                if is_panic:
                    panic_attempted.set()
                original_lock.acquire()
                if is_panic:
                    panic_acquired.set()
                return inner

            def __exit__(inner, *_):
                original_lock.release()

        def blocked_apply(instance, state, decision, lots):
            if decision["action"] == "ENTER_LONG":
                order_entered.set()
                if not release_order.wait(timeout=5):
                    raise AssertionError("一般委託未收到釋放事件")
            return original_apply(instance, state, decision, lots)

        def execute(name, action):
            try:
                results[name] = action()
            except BaseException as error:
                failures.append(error)

        normal = threading.Thread(target=execute, args=("一般委託", lambda: self.engine.handle_signal(self.fixture.signal())), daemon=True)
        panic = threading.Thread(target=execute, args=("急停", self.engine.panic), name="測試急停", daemon=True)
        with patch.object(self.engine, "_ORDER_LOCK", 觀測鎖()), patch.object(broker.PaperBroker, "apply_intent", blocked_apply):
            try:
                normal.start()
                self.assertTrue(order_entered.wait(timeout=3), "一般委託未進入真實 broker")
                panic.start()
                self.assertTrue(panic_attempted.wait(timeout=3), "急停未嘗試取得共用鎖")
                self.assertFalse(panic_acquired.is_set(), "一般委託尚未釋放時急停已穿越共用鎖")
            finally:
                release_order.set()
                normal.join(timeout=5)
                if panic.ident is not None:
                    panic.join(timeout=5)
            self.assertFalse(normal.is_alive())
            self.assertFalse(panic.is_alive())
        self.assertEqual(failures, [])
        self.assertTrue(results["一般委託"]["ok"])
        self.assertTrue(results["急停"]["ok"])
        self.assertTrue(panic_acquired.is_set())
        final = self.runtime.snapshot()
        self.assertEqual(final["positions"]["txt_target"], 0)
        self.assertEqual(final["positions"]["account"], 0)
        self.assertEqual(final["execution"]["action"], "EXIT")
        self.assertEqual(final["execution"]["target"], 0)
        self.assertTrue(final["kill_switch"])
        self.assertEqual(final["fsm"], "Halted")


class 發布身分測試(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="wd_release_identity_")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        source = _策略fixture.ROOT / "server" / "版本身分.py"
        spec = importlib.util.spec_from_file_location("_測試發布身分", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.read_identity = module.read_release_identity

    def test_缺少收據不宣稱版本已驗證(self):
        result = self.read_identity(self.root)
        self.assertFalse(result["releaseVerified"])
        self.assertIsNone(result["runtimeCommit"])
        self.assertEqual(result["releaseError"], "尚未建立發布收據")

    def test_有效收據通過且程式變更後拒絕(self):
        content = {"VERSION": "0.1.21", "run.py": "# 測試入口\n",
                   "web/index.html": "<!doctype html><title>測試</title>",
                   "web/js/deck.js": "// 測試腳本\n", "web/css/deck.css": "/* 測試樣式 */",
                   "server/固定.py": "# 測試模組\n"}
        hashes = {}
        for relative, text in content.items():
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            hashes[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
        receipt = self.root / "data" / "程式版本.json"
        receipt.parent.mkdir()
        commit = "a" * 40
        receipt.write_text(json.dumps({"commit": commit, "files": hashes}), encoding="utf-8")
        valid = self.read_identity(self.root)
        self.assertTrue(valid["releaseVerified"])
        self.assertEqual(valid["runtimeCommit"], commit)
        self.assertIsNone(valid["releaseError"])
        (self.root / "server/固定.py").write_text("# 變更後的模組\n", encoding="utf-8")
        modified = self.read_identity(self.root)
        self.assertFalse(modified["releaseVerified"])
        self.assertIsNone(modified["runtimeCommit"])
        self.assertEqual(modified["releaseError"], "程式檔案與發布收據不符")


if __name__ == "__main__":
    unittest.main()
