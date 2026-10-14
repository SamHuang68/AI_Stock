"""WaveDeck 控制面的請求防護驗收：Host 白名單、跨來源寫入、CORS 與 webhook 密鑰。

只操作暫存副本與動態本機埠；用正式 Handler 驗證，不啟動背景工作。
"""
from __future__ import annotations

import http.client
import importlib
import json
import shutil
import socket
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from wavedeck.server import request_guard as guard
from wavedeck.tests import test_策略訊號整合 as _fixture

# 在任何 fixture 以隔離補丁蓋掉 connect 之前取得真正的連線函式。
_REAL_CONNECT = socket.socket.connect
ST_ORIGIN = "http://127.0.0.1:18432"
FOREIGN = "http://evil.example"
CONTROL_POSTS = (
    "/api/mode", "/api/broker", "/api/kill", "/api/panic", "/api/control", "/api/style", "/api/provider",
    "/api/sync_txt", "/api/demo_tick", "/api/signal", "/api/strategy/register", "/api/strategy/activate",
    "/api/strategy/mode", "/api/no_overnight", "/bridge/st",
)


class RequestGuardUnitTests(unittest.TestCase):
    def test_host_allowlist_accepts_only_loopback_on_the_serving_port(self):
        for host in ("127.0.0.1:18433", "localhost:18433", "LOCALHOST:18433", "[::1]:18433", "127.0.0.1"):
            with self.subTest(host=host):
                self.assertTrue(guard.host_allowed(host, 18433))
        for host in ("", None, "evil.example:18433", "127.0.0.1.evil.example:18433", "127.0.0.1@evil.example:18433",
                     "127.0.0.1:9999", "0.0.0.0:18433", "evil.example"):
            with self.subTest(host=host):
                self.assertFalse(guard.host_allowed(host, 18433))
        self.assertTrue(guard.host_allowed("wd.lan:18433", 18433, frozenset({"wd.lan"})))

    def test_st_origins_follow_the_configured_port(self):
        self.assertEqual(guard.st_origins("http://127.0.0.1:18432"),
                         frozenset({"http://127.0.0.1:18432", "http://localhost:18432", "http://[::1]:18432"}))
        self.assertEqual(guard.st_origins("http://localhost"), frozenset())
        self.assertEqual(guard.st_origins("not a url"), frozenset())

    def test_referer_is_only_a_post_fallback(self):
        self.assertEqual(guard.request_origin(None, "http://evil.example/p?q=1", method="POST"), "http://evil.example")
        self.assertIsNone(guard.request_origin(None, "http://evil.example/p", method="GET"))
        self.assertEqual(guard.request_origin("HTTP://Evil.Example", None, method="GET"), "http://evil.example")
        self.assertEqual(guard.request_origin(None, "garbage", method="POST"), "invalid")

    def test_decision_matrix(self):
        st = guard.st_origins(ST_ORIGIN)

        def check(method, path, origin, host="127.0.0.1:18433", fetch=None):
            return guard.check_request(method=method, path=path, host=host, origin=origin, sec_fetch_site=fetch,
                                       server_port=18433, st_allowed=st)[0]
        self.assertTrue(check("POST", "/api/mode", None))
        self.assertTrue(check("POST", "/api/mode", "http://127.0.0.1:18433"))
        self.assertTrue(check("POST", "/api/mode", "http://localhost:18433"))
        self.assertFalse(check("POST", "/api/mode", FOREIGN))
        self.assertFalse(check("POST", "/api/mode", "null"))
        self.assertFalse(check("POST", "/api/mode", None, fetch="cross-site"))
        self.assertTrue(check("POST", "/api/mode", None, fetch="same-origin"))
        self.assertFalse(check("POST", "/api/mode", "http://127.0.0.1:18433", host="evil.example:18433"))
        self.assertTrue(check("POST", "/bridge/st", ST_ORIGIN))
        self.assertFalse(check("POST", "/api/mode", ST_ORIGIN))
        self.assertTrue(check("GET", "/api/state", ST_ORIGIN))
        self.assertFalse(check("GET", "/api/config", ST_ORIGIN))
        self.assertTrue(check("OPTIONS", "/bridge/st", ST_ORIGIN))
        self.assertFalse(check("OPTIONS", "/api/mode", ST_ORIGIN))
        self.assertFalse(check("OPTIONS", "/bridge/st", FOREIGN))
        self.assertTrue(check("POST", "/webhook/tradingview", FOREIGN, host="tunnel.example"))
        # 明示允許的主機：它上面的控制臺是自己的來源，但同一個網域名稱換埠或換主機仍不是。
        lan = frozenset({"wd.lan"})

        def lan_check(origin, host):
            return guard.check_request(method="POST", path="/api/mode", host=host, origin=origin, sec_fetch_site=None,
                                       server_port=18433, st_allowed=st, allowed_hosts=lan)[0]
        self.assertTrue(lan_check("http://wd.lan:18433", "wd.lan:18433"))
        self.assertFalse(lan_check("http://wd.lan:9999", "wd.lan:18433"))
        self.assertFalse(lan_check("http://other.lan:18433", "other.lan:18433"))
        self.assertIsNone(guard.cors_origin(FOREIGN, st))
        self.assertEqual(guard.cors_origin(ST_ORIGIN, st), ST_ORIGIN)


class RequestGuardHttpTests(unittest.TestCase):
    def setUp(self):
        self.fixture = _fixture.策略訊號整合測試(methodName="test_規則執行不呼叫AI且紙上成交標示模擬")
        self.fixture.setUp()
        shutil.copyfile(_fixture.ROOT / "VERSION", self.fixture.home / "VERSION")
        self.addCleanup(self.fixture.doCleanups)
        self.runtime = self.fixture.runtime
        self.allowed_port = None
        self.denied = []

        def guarded(sock, address):
            if isinstance(address, tuple) and address == ("127.0.0.1", self.allowed_port) and self.allowed_port is not None:
                return _REAL_CONNECT(sock, address)
            self.denied.append(address)
            raise AssertionError("隔離測試禁止非測試埠連線")
        stop = patch.object(socket.socket, "connect", new=guarded)
        stop.start()
        self.addCleanup(stop.stop)
        aliases = {"server" + name[len(self.fixture.package):]: module
                   for name, module in list(sys.modules.items())
                   if name == self.fixture.package or name.startswith(self.fixture.package + ".")}
        prior_path = list(sys.path)
        try:
            with patch.dict(sys.modules, aliases):
                self.server_module = importlib.import_module(self.fixture.package + ".server")
        finally:
            sys.path[:] = prior_path
        # 副本的 server 模組以自己的 request_guard／ST_ORIGINS 取得 ST 來源；固定為測試用的 ST 位址。
        self.addCleanup(setattr, self.server_module, "ST_ORIGINS", getattr(self.server_module, "ST_ORIGINS", frozenset()))
        self.server_module.ST_ORIGINS = guard.st_origins(ST_ORIGIN)
        base = self.server_module.Handler

        class Quiet(base):
            def log_message(self, fmt, *args):
                pass
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
        self.allowed_port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_http)

    def stop_http(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=3)

    def tearDown(self):
        self.fixture.infer.assert_not_called()
        self.assertEqual(self.denied, [])

    def request(self, method, path, *, body=None, headers=None, host=None, content_type="application/json"):
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        conn = http.client.HTTPConnection("127.0.0.1", self.allowed_port, timeout=3)
        try:
            conn.putrequest(method, path, skip_host=host is not None)
            if host is not None:
                conn.putheader("Host", host)
            if method == "POST":
                conn.putheader("Content-Type", content_type)
                conn.putheader("Content-Length", str(len(payload)))
            for key, value in (headers or {}).items():
                conn.putheader(key, value)
            conn.endheaders(payload if method == "POST" else None)
            response = conn.getresponse()
            raw = response.read()
            try:
                parsed = json.loads(raw.decode("utf-8")) if raw else None
            except ValueError:
                parsed = None
            return response.status, parsed, response
        finally:
            conn.close()

    def state(self):
        snap = self.runtime.snapshot()
        return {key: snap.get(key) for key in ("mode", "kill_switch", "style", "positions", "fsm", "lights")}

    def test_foreign_site_cannot_use_any_control_endpoint(self):
        before = self.state()
        for path in CONTROL_POSTS:
            for content_type in ("application/json", "text/plain"):  # text/plain 是不需預檢的簡單請求
                with self.subTest(path=path, content_type=content_type):
                    status, body, response = self.request(
                        "POST", path, body={"mode": "live", "on": False, "style": 99, "cmd": "restart", "kind": "txt_master"},
                        headers={"Origin": FOREIGN}, content_type=content_type)
                    self.assertEqual(status, 403, (path, body))
                    self.assertFalse(body["ok"])
                    self.assertIsNone(response.getheader("Access-Control-Allow-Origin"))
        self.assertEqual(self.state(), before)

    def test_rejected_post_with_a_large_body_still_returns_403_instead_of_resetting_the_connection(self):
        # 防護拒絕時若尚未讀完請求本體就關閉連線，Windows 會送出 RST，客戶端可能讀不到 403。
        # 本體越大越容易重現，因此以接近上限的本體重複多次，任何一次連線被中止都算失敗。
        body = {"pad": "x" * 200000}
        failures = []
        for attempt in range(25):
            try:
                status, parsed, _ = self.request("POST", "/api/style", body=body, headers={"Origin": FOREIGN})
            except OSError as exc:
                failures.append((attempt, type(exc).__name__, getattr(exc, "winerror", None)))
                continue
            if status != 403 or not parsed or parsed.get("ok") is not False:
                failures.append((attempt, status, parsed))
        self.assertEqual(failures, [])

    def test_referer_only_and_fetch_metadata_cannot_bypass_the_origin_check(self):
        before = self.state()
        status, _, _ = self.request("POST", "/api/style", body={"style": 99}, headers={"Referer": FOREIGN + "/attack"})
        self.assertEqual(status, 403)
        status, _, _ = self.request("POST", "/api/style", body={"style": 99}, headers={"Sec-Fetch-Site": "cross-site"})
        self.assertEqual(status, 403)
        self.assertEqual(self.state(), before)

    def test_local_console_and_command_line_still_work(self):
        origin = f"http://127.0.0.1:{self.allowed_port}"
        for headers in ({}, {"Origin": origin}, {"Origin": f"http://localhost:{self.allowed_port}"},
                        {"Sec-Fetch-Site": "same-origin", "Origin": origin}):
            with self.subTest(headers=headers):
                status, body, _ = self.request("POST", "/api/style", body={"style": 41}, headers=headers)
                self.assertEqual(status, 200, body)
        self.assertEqual(self.runtime.snapshot()["style"], 41)

    def test_stock_terminal_origin_may_only_read_state_and_push_the_overlay(self):
        headers = {"Origin": ST_ORIGIN}
        with patch.object(self.server_module, "apply_st_bridge", return_value={"ok": True}) as bridge:
            status, body, response = self.request("POST", "/bridge/st", body={"style": 60}, headers=headers)
        self.assertEqual(status, 200, body)
        bridge.assert_called_once()
        self.assertEqual(response.getheader("Access-Control-Allow-Origin"), ST_ORIGIN)
        for path in ("/health", "/api/state"):
            with self.subTest(path=path):
                status, _, response = self.request("GET", path, headers=headers)
                self.assertEqual(status, 200)
                self.assertEqual(response.getheader("Access-Control-Allow-Origin"), ST_ORIGIN)
                self.assertEqual(response.getheader("Vary"), "Origin")
        before = self.state()
        for path in CONTROL_POSTS:
            if path == "/bridge/st":
                continue
            with self.subTest(post=path):
                status, _, _ = self.request("POST", path, body={"mode": "live", "on": False}, headers=headers)
                self.assertEqual(status, 403)
        for path in ("/api/config", "/api/audit", "/api/st_link", "/api/exec_md/latest"):
            with self.subTest(get=path):
                status, _, _ = self.request("GET", path, headers=headers)
                self.assertEqual(status, 403)
        self.assertEqual(self.state(), before)

    def test_preflight_is_granted_only_for_the_stock_terminal_calls(self):
        ask = {"Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
        status, _, response = self.request("OPTIONS", "/bridge/st", headers={"Origin": ST_ORIGIN, **ask})
        self.assertEqual(status, 204)
        self.assertEqual(response.getheader("Access-Control-Allow-Origin"), ST_ORIGIN)
        self.assertIn("Content-Type", response.getheader("Access-Control-Allow-Headers"))
        for path, origin in (("/bridge/st", FOREIGN), ("/api/mode", ST_ORIGIN), ("/api/mode", FOREIGN)):
            with self.subTest(path=path, origin=origin):
                status, _, response = self.request("OPTIONS", path, headers={"Origin": origin, **ask})
                self.assertEqual(status, 403)  # 預檢非 2xx，瀏覽器不會送出實際請求
                self.assertIsNone(response.getheader("Access-Control-Allow-Methods"))
                if origin == FOREIGN:
                    self.assertIsNone(response.getheader("Access-Control-Allow-Origin"))

    def test_there_is_no_wildcard_cors_anywhere(self):
        status, _, response = self.request("GET", "/health")
        self.assertEqual(status, 200)
        self.assertIsNone(response.getheader("Access-Control-Allow-Origin"))
        status, _, response = self.request("GET", "/health", headers={"Origin": FOREIGN})
        self.assertEqual(status, 403)
        self.assertIsNone(response.getheader("Access-Control-Allow-Origin"))

    def test_host_header_must_be_loopback_so_dns_rebinding_fails(self):
        evil = f"attacker.example:{self.allowed_port}"
        for method, path in (("GET", "/health"), ("GET", "/api/state"), ("POST", "/api/style")):
            with self.subTest(method=method, path=path):
                status, body, _ = self.request(method, path, body={"style": 99}, host=evil)
                self.assertEqual(status, 403)
                self.assertFalse(body["ok"])
        # 重綁定時瀏覽器的 Origin 會等於攻擊者的 Host，只比對兩者相等是不夠的。
        status, _, _ = self.request("POST", "/api/style", body={"style": 99}, host=evil,
                                    headers={"Origin": "http://" + evil})
        self.assertEqual(status, 403)
        for host in (f"localhost:{self.allowed_port}", "127.0.0.1"):
            self.assertEqual(self.request("GET", "/health", host=host)[0], 200)
        with patch.dict("os.environ", {"WAVEDECK_ALLOWED_HOSTS": "wd.lan"}):
            lan = f"wd.lan:{self.allowed_port}"
            self.assertEqual(self.request("GET", "/health", host=lan)[0], 200)
            self.assertEqual(self.request("POST", "/api/style", body={"style": 42}, host=lan,
                                          headers={"Origin": "http://" + lan})[0], 200)
            self.assertEqual(self.request("POST", "/api/style", body={"style": 99}, host=lan,
                                          headers={"Origin": FOREIGN})[0], 403)

    def test_opening_the_console_from_another_page_is_still_a_harmless_navigation(self):
        status, _, _ = self.request("GET", "/", headers={"Referer": FOREIGN + "/link"})
        self.assertNotEqual(status, 403)

    def test_webhook_is_guarded_by_the_secret_and_may_arrive_through_the_tunnel_host(self):
        tunnel = {"host": "tunnel.example"}
        with patch.object(self.server_module, "SECRET", "s3cret"), \
                patch.object(self.server_module, "handle_signal", return_value={"ok": True}) as signal:
            for path in ("/webhook", "/webhook/tradingview"):
                with self.subTest(path=path):
                    status, _, _ = self.request("POST", path, body={}, **tunnel)
                    self.assertEqual(status, 401)
                    status, _, _ = self.request("POST", path, body={}, headers={"X-WaveDeck-Secret": "wrong"}, **tunnel)
                    self.assertEqual(status, 401)
                    status, body, _ = self.request("POST", path, body={}, headers={"X-WaveDeck-Secret": "s3cret"}, **tunnel)
                    self.assertEqual(status, 200, body)
            self.assertEqual(signal.call_count, 2)
            # 隧道主機不能用來打控制端點。
            status, _, _ = self.request("POST", "/api/style", body={"style": 99},
                                        headers={"X-WaveDeck-Secret": "s3cret"}, **tunnel)
            self.assertEqual(status, 403)

    def test_webhook_with_a_wrong_secret_and_a_large_body_still_returns_401(self):
        # 密鑰檢查也在讀取本體之前回應；與防護拒絕相同，不可讓連線被重設。
        failures = []
        with patch.object(self.server_module, "SECRET", "s3cret"), \
                patch.object(self.server_module, "handle_signal", return_value={"ok": True}) as signal:
            for attempt in range(25):
                try:
                    status, _, _ = self.request("POST", "/webhook", body={"pad": "x" * 200000},
                                                headers={"X-WaveDeck-Secret": "wrong"}, host="tunnel.example")
                except OSError as exc:
                    failures.append((attempt, type(exc).__name__, getattr(exc, "winerror", None)))
                    continue
                if status != 401:
                    failures.append((attempt, status))
            signal.assert_not_called()
        self.assertEqual(failures, [])


if __name__ == "__main__":
    unittest.main()
