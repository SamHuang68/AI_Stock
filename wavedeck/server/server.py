#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaveDeck stdlib HTTP server — bind 127.0.0.1:18433 by default."""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
sys.path.insert(0, str(ROOT))

from server import audit  # noqa: E402
from server.engine import apply_st_bridge, handle_signal  # noqa: E402
from server.state import RUNTIME, now_iso  # noqa: E402

HOST = os.environ.get("WAVEDECK_HOST", "127.0.0.1")
PORT = int(os.environ.get("WAVEDECK_PORT", "18433"))
SECRET = os.environ.get("WAVEDECK_SECRET", "")


def _json(handler: BaseHTTPRequestHandler, code: int, obj: Any) -> None:
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(raw)


def _read_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    n = int(handler.headers.get("Content-Length") or 0)
    if n <= 0:
        return {}
    try:
        return json.loads(handler.rfile.read(n).decode("utf-8"))
    except Exception:
        return {}


def _check_secret(handler: BaseHTTPRequestHandler) -> bool:
    if not SECRET:
        return True
    got = handler.headers.get("X-WaveDeck-Secret") or ""
    return got == SECRET


class Handler(BaseHTTPRequestHandler):
    server_version = "WaveDeck/0.1"

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("[wavedeck] " + (fmt % args) + "\n")

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type,X-WaveDeck-Secret")
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"

        if path == "/health":
            return _json(
                self,
                200,
                {
                    "ok": True,
                    "service": "WaveDeck",
                    "version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
                    "ts": now_iso(),
                    "fsm": RUNTIME.snapshot().get("fsm"),
                },
            )
        if path == "/api/state":
            return _json(self, 200, {"ok": True, "state": RUNTIME.snapshot()})
        if path == "/api/audit":
            q = parse_qs(u.query)
            lim = int((q.get("limit") or ["40"])[0])
            return _json(self, 200, {"ok": True, "items": audit.recent(lim)})

        # static
        rel = "index.html" if path == "/" else path.lstrip("/")
        fp = (WEB / rel).resolve()
        if not str(fp).startswith(str(WEB.resolve())) or not fp.is_file():
            return _json(self, 404, {"ok": False, "error": "not found"})
        data = fp.read_bytes()
        ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:  # noqa: N802
        u = urlparse(self.path)
        path = u.path.rstrip("/") or "/"
        if not _check_secret(self) and path.startswith("/webhook"):
            return _json(self, 401, {"ok": False, "error": "bad secret"})

        body = _read_json(self)

        if path in ("/webhook", "/webhook/tradingview"):
            return _json(self, 200, handle_signal(body))

        if path == "/bridge/st":
            return _json(self, 200, {"ok": True, "state": apply_st_bridge(body)})

        if path == "/api/signal":
            return _json(self, 200, handle_signal(body))

        if path == "/api/style":
            try:
                style = int(body.get("style", 50))
            except Exception:
                style = 50
            style = max(1, min(99, style))
            return _json(self, 200, {"ok": True, "state": RUNTIME.patch(style=style)})

        if path == "/api/kill":
            on = bool(body.get("on"))
            return _json(self, 200, {"ok": True, "state": RUNTIME.set_kill(on)})

        if path == "/api/control":
            cmd = str(body.get("cmd") or "")
            st = RUNTIME.snapshot()
            if cmd == "start":
                if st.get("fsm") == "Halted" and not st.get("kill_switch"):
                    RUNTIME.set_fsm("Idle")
                RUNTIME.patch(lights={"system": "run"})
            elif cmd == "stop":
                RUNTIME.patch(lights={"system": "stop"})
            elif cmd == "restart":
                RUNTIME.set_kill(False)
                RUNTIME.set_fsm("Idle")
                RUNTIME.patch(lights={"system": "run"})
            elif cmd == "refresh":
                pass
            else:
                return _json(self, 400, {"ok": False, "error": "unknown cmd"})
            audit.write("control", {"cmd": cmd})
            return _json(self, 200, {"ok": True, "state": RUNTIME.snapshot()})

        if path == "/api/demo_tick":
            # Convenience: run a timed market review for UI demos
            return _json(
                self,
                200,
                handle_signal(
                    {
                        "source": "demo",
                        "event": "TIMED_MARKET_REVIEW",
                        "symbol": RUNTIME.snapshot().get("symbol") or "TXF",
                    }
                ),
            )

        return _json(self, 404, {"ok": False, "error": "not found"})


def main() -> None:
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print("=" * 52)
    print(f" WaveDeck · 浪潮執行台  http://{HOST}:{PORT}/")
    print(f" Health                 http://{HOST}:{PORT}/health")
    print(f" Stock Terminal bridge  POST /bridge/st")
    print("=" * 52)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[wavedeck] bye")
        httpd.server_close()


if __name__ == "__main__":
    main()
