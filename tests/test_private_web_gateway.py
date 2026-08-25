#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import base64
import http.client
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from dataclasses import replace
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlencode, urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server"))

import private_web_gateway as gateway  # noqa: E402


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UpstreamHandler(BaseHTTPRequestHandler):
    seen: list[dict] = []
    ai_stream_mode = "normal"
    ai_stream_release = threading.Event()

    def log_message(self, fmt, *args):
        return

    def _send(self, body: dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def do_GET(self):
        self.__class__.seen.append(
            {"method": "GET", "path": self.path, "headers": dict(self.headers)}
        )
        if self.path == "/":
            raw = b"<html><head></head><body>ST</body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            return
        self._send({"ok": True, "path": self.path})

    def do_HEAD(self):
        self._send({"ok": True})

    def do_POST(self):
        size = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(size)
        self.__class__.seen.append(
            {
                "method": "POST",
                "path": self.path,
                "headers": dict(self.headers),
                "body": raw.decode("utf-8"),
            }
        )
        if self.path == "/ai/local":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("X-ST-AI-Host", "EVO-T1")
            self.end_headers()
            self.close_connection = True
            self.wfile.write(b"A")
            self.wfile.flush()
            if self.__class__.ai_stream_mode == "gated":
                self.__class__.ai_stream_release.wait(3)
            elif self.__class__.ai_stream_mode == "timeout":
                time.sleep(1.4)
            try:
                self.wfile.write(b"B")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
            return
        self._send({"ok": True})


def _request(url: str, *, method: str = "GET", token: str | None = None,
             basic: bool = False, origin: str | None = None, body: dict | None = None):
    headers = {}
    if token:
        if basic:
            credential = base64.b64encode(f"owner:{token}".encode()).decode()
            headers["Authorization"] = "Basic " + credential
        else:
            headers["Authorization"] = "Bearer " + token
    if origin:
        headers["Origin"] = origin
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            raw = response.read()
            return response.status, json.loads(raw or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode("utf-8"))
        finally:
            exc.close()


class PrivateWebGatewayTests(unittest.TestCase):
    def test_gateway_backlog_covers_dashboard_asset_fanout(self):
        self.assertGreaterEqual(gateway.PrivateWebServer.request_queue_size, 128)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        UpstreamHandler.seen = []
        UpstreamHandler.ai_stream_mode = "normal"
        UpstreamHandler.ai_stream_release = threading.Event()
        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), UpstreamHandler)
        self.upstream_thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.upstream_thread.start()
        upstream_port = self.upstream.server_address[1]
        settings = gateway.Settings(
            listen_host="127.0.0.1",
            listen_port=0,
            upstream_host="127.0.0.1",
            upstream_port=upstream_port,
            owner_token="owner-secret",
            read_token="reader-secret",
            allowed_hosts=("127.0.0.1", "localhost"),
            allowed_host_suffixes=(".ts.net",),
            max_body_bytes=1024,
            read_rate_per_minute=100,
            write_rate_per_minute=100,
            upstream_timeout_seconds=5,
            audit_path=Path(self.temp.name) / "audit.jsonl",
            access_request_path=Path(self.temp.name) / "access_requests.json",
            client_trace_path=Path(self.temp.name) / "client.jsonl",
        )
        self.gateway = gateway.PrivateWebServer(("127.0.0.1", 0), gateway.Handler, settings)
        self.gateway_thread = threading.Thread(target=self.gateway.serve_forever, daemon=True)
        self.gateway_thread.start()
        self.port = self.gateway.server_address[1]
        self.base = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        UpstreamHandler.ai_stream_release.set()
        self.gateway.shutdown()
        self.gateway.server_close()
        self.upstream.shutdown()
        self.upstream.server_close()
        self.temp.cleanup()

    def test_health_is_minimal_and_does_not_require_authentication(self):
        status, payload = _request(self.base + "/gateway/health")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["upstream"])
        self.assertEqual(payload["mode"], "dev-linked")
        self.assertEqual(UpstreamHandler.seen[-1]["path"], "/health/live")

    def test_health_exposes_non_secret_instance_identity_when_configured(self):
        self.gateway.settings = gateway.Settings(
            **{
                **self.gateway.settings.__dict__,
                "instance_id": "host-run-1",
                "mode": "isolated-host",
            }
        )
        status, payload = _request(self.base + "/gateway/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload["instance"], "host-run-1")
        self.assertEqual(payload["mode"], "isolated-host")

    def test_market_get_accepts_read_only_bearer(self):
        status, payload = _request(
            self.base + "/market/snapshot", token="reader-secret"
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["path"], "/market/snapshot")

    def test_signal_ledger_is_read_only_for_shared_viewers(self):
        for path in ("/signals/active", "/signals/history?limit=20"):
            status, payload = _request(self.base + path, token="reader-secret")
            self.assertEqual(status, 200)
            self.assertEqual(payload["path"], path)

    def test_html_receives_private_market_profile_before_ui_boot(self):
        credential = base64.b64encode(b"owner:owner-secret").decode()
        req = urllib.request.Request(
            self.base + "/",
            headers={"Authorization": "Basic " + credential},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode("utf-8")
            self.assertEqual(int(response.headers["Content-Length"]), len(html.encode("utf-8")))
        self.assertIn("ST_PRIVATE_WEB_PROFILE", html)
        self.assertIn("wavedeck:false", html)
        self.assertIn("window.SERVER=", html)
        self.assertIn("window.location.origin", html)
        self.assertIn("private-web-boot-", html)
        self.assertNotIn("mobile-boot-", html)
        self.assertIn("完整介面載入失敗", html)
        self.assertNotIn("已切換手機相容圖表", html)
        self.assertLess(html.index("ST_PRIVATE_WEB_PROFILE"), html.index("<body>"))

    def test_missing_authentication_is_challenged(self):
        status, payload = _request(self.base + "/pulse")
        self.assertEqual(status, 401)
        self.assertIn("authentication", payload["error"])

    def test_browser_login_page_creates_persistent_cookie_session(self):
        req = urllib.request.Request(
            self.base + "/",
            headers={"Accept": "text/html"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            page = response.read().decode("utf-8")
            final_url = response.geturl()
            response_headers = dict(response.headers)
        self.assertEqual(final_url, self.base + "/gateway/login?next=/")
        self.assertIn("登入狀態會持續保留", page)
        self.assertNotIn('name="remember"', page)
        self.assertIn('name="csrf"', page)
        self.assertIn('/gateway/help', page)
        self.assertNotIn("WWW-Authenticate", response_headers)

        form = urlencode({
            "role": "reader",
            "token": "reader-secret",
            "next": "/",
            "csrf": gateway._make_login_csrf(self.gateway.settings, urlsplit(self.base).netloc),
        }).encode("utf-8")
        login = urllib.request.Request(
            self.base + "/gateway/login",
            data=form,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": self.base,
                "Tailscale-User-Login": "applicant@example.com",
            },
        )
        opener = urllib.request.build_opener(NoRedirect)
        with self.assertRaises(urllib.error.HTTPError) as raised:
            opener.open(login, timeout=5)
        login_response = raised.exception
        self.assertEqual(login_response.code, 303)
        set_cookie = login_response.headers["Set-Cookie"]
        login_response.close()
        self.assertIn(gateway.SESSION_COOKIE + "=", set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)
        self.assertIn(
            f"Max-Age={gateway.PERSISTENT_SESSION_MAX_AGE_SECONDS}",
            set_cookie,
        )
        cookie = set_cookie.split(";", 1)[0]
        session_value = cookie.split("=", 1)[1]
        far_future = time.time() + 100 * 365 * 24 * 60 * 60
        with mock.patch.object(gateway.time, "time", return_value=far_future):
            self.assertEqual(gateway._read_session(self.gateway.settings, session_value), "reader")

        root = urllib.request.Request(self.base + "/", headers={"Cookie": cookie})
        with urllib.request.urlopen(root, timeout=5) as response:
            html_body = response.read().decode("utf-8")
        self.assertIn("ST_PRIVATE_WEB_PROFILE", html_body)

    def test_login_help_is_available_before_authentication(self):
        req = urllib.request.Request(self.base + "/gateway/help", headers={"Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=5) as response:
            page = response.read().decode("utf-8")
        self.assertIn("手機與 Windows 外部連線圖文教學", page)
        self.assertIn("Tailscale", page)
        self.assertIn("iPhone Chrome", page)
        self.assertIn("Windows Chrome", page)
        self.assertIn("/gateway/request-access", page)
        self.assertNotIn("30 天", page)

    def test_access_request_form_is_public_but_never_auto_grants_access(self):
        with urllib.request.urlopen(self.base + "/gateway/request-access", timeout=5) as response:
            page = response.read().decode("utf-8")
        self.assertIn("申請 Stock Terminal Reader 使用權", page)
        self.assertIn('name="csrf"', page)
        self.assertIn("申請不等於自動開通", page)

        form = urlencode({
            "display_name": "Test Reader",
            "contact_email": "reader@example.com",
            "tailscale_email": "tail@example.com",
            "platform": "iphone",
            "note": "Chrome",
            "consent": "yes",
            "csrf": gateway._make_form_csrf(
                self.gateway.settings,
                urlsplit(self.base).netloc,
                "access-request",
            ),
        }).encode("utf-8")
        req = urllib.request.Request(
            self.base + "/gateway/request-access",
            data=form,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": self.base,
            },
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            result_page = response.read().decode("utf-8")
            self.assertEqual(response.status, 201)
        self.assertIn("申請已安全送出", result_page)
        rows = self.gateway.access_store.list_requests()
        self.assertEqual(rows[0]["status"], "pending")
        audit = self.gateway.settings.audit_path.read_text(encoding="utf-8")
        self.assertIn("access_request_submitted", audit)
        self.assertNotIn("reader@example.com", audit)
        self.assertNotIn("Test Reader", audit)
        self.assertNotIn("applicant@example.com", audit)
        self.assertIn("anon-", audit)

    def test_access_request_rejects_cross_origin_submission(self):
        form = urlencode({
            "display_name": "Test Reader",
            "contact_email": "reader@example.com",
            "tailscale_email": "tail@example.com",
            "platform": "windows",
            "consent": "yes",
            "csrf": gateway._make_form_csrf(
                self.gateway.settings,
                urlsplit(self.base).netloc,
                "access-request",
            ),
        }).encode("utf-8")
        req = urllib.request.Request(
            self.base + "/gateway/request-access",
            data=form,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://evil.example",
            },
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(req, timeout=5)
        self.assertEqual(raised.exception.code, 403)
        raised.exception.close()
        self.assertEqual(self.gateway.access_store.list_requests(), [])

    def test_admin_panel_is_owner_only_and_updates_without_logging_pii(self):
        row, _ = self.gateway.access_store.create(
            display_name="Private Reader",
            contact_email="private@example.com",
            tailscale_email="tail-private@example.com",
            platform="both",
        )
        status, payload = _request(
            self.base + "/gateway/admin", token="reader-secret"
        )
        self.assertEqual(status, 403)
        self.assertIn("owner", payload["error"])

        credential = base64.b64encode(b"owner:owner-secret").decode()
        req = urllib.request.Request(
            self.base + "/gateway/admin",
            headers={"Authorization": "Basic " + credential, "Accept": "text/html"},
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            page = response.read().decode("utf-8")
        self.assertIn("Private Web 存取管理", page)
        self.assertIn("private@example.com", page)
        self.assertNotIn("owner-secret", page)
        self.assertNotIn("reader-secret", page)

        form = urlencode({
            "request_id": row["id"],
            "status": "active",
            "admin_note": "Identity checked",
            "csrf": gateway._make_form_csrf(
                self.gateway.settings,
                urlsplit(self.base).netloc,
                "access-admin",
            ),
        }).encode("utf-8")
        update = urllib.request.Request(
            self.base + "/gateway/admin/action",
            data=form,
            method="POST",
            headers={
                "Authorization": "Basic " + credential,
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": self.base,
            },
        )
        opener = urllib.request.build_opener(NoRedirect)
        with self.assertRaises(urllib.error.HTTPError) as raised:
            opener.open(update, timeout=5)
        self.assertEqual(raised.exception.code, 303)
        raised.exception.close()
        self.assertEqual(self.gateway.access_store.list_requests()[0]["status"], "active")
        audit = self.gateway.settings.audit_path.read_text(encoding="utf-8")
        self.assertIn("access_request_status_changed", audit)
        self.assertNotIn("private@example.com", audit)
        self.assertNotIn("Private Reader", audit)

    def test_login_failure_never_persists_token(self):
        form = urlencode({
            "role": "owner",
            "token": "wrong-secret",
            "csrf": gateway._make_login_csrf(self.gateway.settings, urlsplit(self.base).netloc),
        }).encode("utf-8")
        req = urllib.request.Request(
            self.base + "/gateway/login",
            data=form,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": self.base,
            },
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            urllib.request.urlopen(req, timeout=5)
        failed_response = raised.exception
        self.assertEqual(failed_response.code, 401)
        self.assertIn("不正確", failed_response.read().decode("utf-8"))
        failed_response.close()
        audit = self.gateway.settings.audit_path.read_text(encoding="utf-8")
        self.assertIn("login_failed", audit)
        self.assertNotIn("wrong-secret", audit)

    def test_authenticated_browser_trace_is_sanitized_and_persisted(self):
        status, payload = _request(
            self.base + "/gateway/client-log",
            method="POST",
            token="owner-secret",
            basic=True,
            origin=self.base,
            body={
                "event": "boot_probe_1s",
                "correlationId": "mobile-boot-test",
                "detail": {"viewport": {"w": 390, "h": 844}, "token": "not-a-secret"},
            },
        )
        self.assertEqual(status, 202)
        self.assertTrue(payload["ok"])
        rows = [
            json.loads(line)
            for line in self.gateway.settings.client_trace_path.read_text(encoding="utf-8").splitlines()
        ]
        self.assertEqual(rows[-1]["event"], "boot_probe_1s")
        self.assertEqual(rows[-1]["correlationId"], "mobile-boot-test")
        self.assertEqual(rows[-1]["detail"]["viewport"]["w"], 390)
        self.assertNotIn("owner-secret", json.dumps(rows[-1]))

    def test_second_gateway_cannot_share_the_same_listener(self):
        with self.assertRaises(OSError):
            gateway.PrivateWebServer(
                ("127.0.0.1", self.port),
                gateway.Handler,
                self.gateway.settings,
            )

    def test_reader_cannot_write(self):
        status, _ = _request(
            self.base + "/portfolio",
            method="POST",
            token="reader-secret",
            body={"symbols": ["2330"]},
        )
        self.assertEqual(status, 403)
        self.assertEqual(UpstreamHandler.seen, [])

    def test_basic_browser_write_requires_same_origin(self):
        status, _ = _request(
            self.base + "/portfolio",
            method="POST",
            token="owner-secret",
            basic=True,
            body={"symbols": ["2330"]},
        )
        self.assertEqual(status, 403)

        status, _ = _request(
            self.base + "/portfolio",
            method="POST",
            token="owner-secret",
            basic=True,
            origin=self.base,
            body={"symbols": ["2330"]},
        )
        self.assertEqual(status, 200)
        seen = UpstreamHandler.seen[-1]
        lowered = {key.lower() for key in seen["headers"]}
        self.assertNotIn("authorization", lowered)
        self.assertNotIn("origin", lowered)

    def test_owner_bearer_can_write_but_admin_and_wavedeck_stay_blocked(self):
        status, _ = _request(
            self.base + "/decision/context",
            method="POST",
            token="owner-secret",
            body={},
        )
        self.assertEqual(status, 200)
        status, _ = _request(
            self.base + "/ai/deep",
            method="POST",
            token="owner-secret",
            body={"prompt": "test"},
        )
        self.assertEqual(status, 200)
        status, _ = _request(
            self.base + "/options/txo/refresh",
            method="POST",
            token="owner-secret",
            body={"force": False},
        )
        self.assertEqual(status, 200)
        status, _ = _request(
            self.base + "/research/overnight-intraday/refresh",
            method="POST",
            token="owner-secret",
            body={"market": "all", "force": False},
        )
        self.assertEqual(status, 200)
        for path in ("/ai-key", "/bridge/wavedeck", "/notify", "/universe/refresh"):
            status, _ = _request(
                self.base + path,
                method="POST",
                token="owner-secret",
                body={},
            )
            self.assertEqual(status, 403, path)

    def test_ai_proxy_forwards_first_small_chunk_without_large_buffer_wait(self):
        UpstreamHandler.ai_stream_mode = "gated"
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        started = time.monotonic()
        try:
            connection.request(
                "POST", "/ai/local", body=b'{"prompt":"test"}',
                headers={
                    "Authorization": "Bearer owner-secret",
                    "Content-Type": "application/json",
                    "Content-Length": "17",
                },
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            self.assertEqual(response.read(1), b"A")
            self.assertLess(time.monotonic() - started, 0.9)
            UpstreamHandler.ai_stream_release.set()
            self.assertEqual(response.read(), b"B")
        finally:
            UpstreamHandler.ai_stream_release.set()
            connection.close()

    def test_ai_timeout_after_headers_never_injects_second_http_response(self):
        UpstreamHandler.ai_stream_mode = "timeout"
        self.gateway.settings = replace(
            self.gateway.settings, ai_upstream_timeout_seconds=1,
        )
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(
                "POST", "/ai/local", body=b'{"prompt":"test"}',
                headers={
                    "Authorization": "Bearer owner-secret",
                    "Content-Type": "application/json",
                    "Content-Length": "17",
                },
            )
            response = connection.getresponse()
            self.assertEqual(response.status, 200)
            body = response.read()
            self.assertEqual(body, b"A")
            self.assertNotIn(b"HTTP/1.1", body)
            self.assertNotIn(b"ST backend unavailable", body)
        finally:
            connection.close()
        audit = self.gateway.settings.audit_path.read_text(encoding="utf-8")
        self.assertIn("upstream_stream_aborted", audit)

    def test_legacy_get_backfill_query_is_blocked(self):
        status, _ = _request(
            self.base + "/margin_ratio?action=backfill&full=1",
            token="owner-secret",
        )
        self.assertEqual(status, 403)
        self.assertFalse(
            any(item["path"].startswith("/margin_ratio") for item in UpstreamHandler.seen)
        )

    def test_write_audit_contains_no_body_or_token(self):
        _request(
            self.base + "/portfolio",
            method="POST",
            token="owner-secret",
            body={"private": "do-not-log"},
        )
        audit_path = Path(self.temp.name) / "audit.jsonl"
        audit = ""
        for _ in range(100):
            if audit_path.exists():
                audit = audit_path.read_text(encoding="utf-8")
            if "write_forwarded" in audit:
                break
            time.sleep(0.01)
        self.assertIn("write_forwarded", audit)
        self.assertNotIn("do-not-log", audit)
        self.assertNotIn("owner-secret", audit)


if __name__ == "__main__":
    unittest.main()
