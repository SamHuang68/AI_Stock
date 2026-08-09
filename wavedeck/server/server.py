#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WaveDeck stdlib HTTP server — bind 127.0.0.1:18433 by default."""
from __future__ import annotations

import json
import mimetypes
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
# Avoid shadowing: `python server/server.py` puts this directory on sys.path[0],
# so `import server` would load this file instead of the package.
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
sys.path = [str(ROOT)] + [p for p in sys.path if p not in ("", ".", _SCRIPT_DIR)]

from server import audit  # noqa: E402
from server.engine import (  # noqa: E402
    apply_st_bridge,
    get_runtime_config,
    handle_signal,
    set_broker,
    set_decision_provider,
    set_exec_mode,
    sync_broker_positions,
)
from server.config import load_config  # noqa: E402
from server.state import RUNTIME, now_iso  # noqa: E402

HOST = os.environ.get("WAVEDECK_HOST", "127.0.0.1")
PORT = int(os.environ.get("WAVEDECK_PORT", "18433"))
SECRET = os.environ.get("WAVEDECK_SECRET", "")
# Windows 常把某些埠段列為 excluded（WinError 10013），預設失敗時改試這些埠
PORT_FALLBACKS = [
    PORT,
    18434,
    18765,
    28765,
    38433,
    8765,
]
PORT_FILE = ROOT / "data" / "wavedeck.port"


def _boot_sync_config() -> None:
    """Align runtime mode/provider lights with local config on start."""
    try:
        cfg = load_config()
        kind = ((cfg.get("broker") or {}).get("kind") or "paper")
        RUNTIME.patch(
            mode=str(cfg.get("mode") or "paper"),
            costs={"provider": str(cfg.get("provider") or "heuristic")},
            account={"broker_api": kind},
        )
    except Exception as exc:
        sys.stderr.write(f"[wavedeck] boot config sync skipped: {exc}\n")


def _json(handler: BaseHTTPRequestHandler, code: int, obj: Any) -> None:
    raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    handler.send_response(code)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(raw)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Access-Control-Allow-Origin", "*")
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
    server_version = "WaveDeck/0.1.14"

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
            snap = RUNTIME.snapshot()
            return _json(
                self,
                200,
                {
                    "ok": True,
                    "service": "WaveDeck",
                    "version": (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
                    "ts": now_iso(),
                    "fsm": snap.get("fsm"),
                    "mode": snap.get("mode"),
                    "provider": (snap.get("costs") or {}).get("provider"),
                    "st_link": snap.get("st_link") or {},
                    "fail_safe": bool((snap.get("st_overlay") or {}).get("fail_safe")),
                },
            )
        if path == "/api/st_link":
            snap = RUNTIME.snapshot()
            return _json(
                self,
                200,
                {
                    "ok": True,
                    "st_link": snap.get("st_link") or {},
                    "fail_safe": bool((snap.get("st_overlay") or {}).get("fail_safe")),
                    "style": snap.get("style"),
                },
            )
        if path == "/api/llm_busy":
            try:
                import sys
                from pathlib import Path as _P

                _root = _P(__file__).resolve().parents[2]
                if str(_root / "server") not in sys.path:
                    sys.path.insert(0, str(_root / "server"))
                import llm_gate as lg  # type: ignore

                return _json(self, 200, lg.status())
            except Exception as exc:
                return _json(self, 200, {"ok": True, "held": False, "error": str(exc)})
        if path == "/api/state":
            return _json(self, 200, {"ok": True, "state": RUNTIME.snapshot()})
        if path == "/api/config":
            return _json(self, 200, get_runtime_config())
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

        if path == "/api/provider":
            try:
                return _json(self, 200, set_decision_provider(str(body.get("provider") or "heuristic")))
            except ValueError as exc:
                return _json(self, 400, {"ok": False, "error": str(exc)})

        if path == "/api/mode":
            try:
                return _json(self, 200, set_exec_mode(str(body.get("mode") or "paper")))
            except ValueError as exc:
                return _json(self, 400, {"ok": False, "error": str(exc)})

        if path == "/api/broker":
            try:
                return _json(self, 200, set_broker(str(body.get("kind") or body.get("broker") or "paper")))
            except ValueError as exc:
                return _json(self, 400, {"ok": False, "error": str(exc)})

        if path == "/api/sync_txt":
            return _json(self, 200, sync_broker_positions())

        if path == "/api/kill":
            on = bool(body.get("on"))
            snap = RUNTIME.set_kill(on)
            try:
                from server.st_push import push_async

                push_async(snap, reason="kill", force=True)
            except Exception:
                pass
            return _json(self, 200, {"ok": True, "state": snap})

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
                sync_broker_positions()
            else:
                return _json(self, 400, {"ok": False, "error": "unknown cmd"})
            audit.write("control", {"cmd": cmd})
            return _json(self, 200, {"ok": True, "state": RUNTIME.snapshot()})

        if path == "/api/demo_tick":
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


def _candidate_ports() -> list[int]:
    seen: set[int] = set()
    out: list[int] = []
    for p in PORT_FALLBACKS:
        try:
            n = int(p)
        except Exception:
            continue
        if n <= 0 or n in seen:
            continue
        seen.add(n)
        out.append(n)
    return out


def _bind_server() -> tuple[ThreadingHTTPServer, int]:
    """Bind loopback; on Windows PermissionError(10013) try next ports."""
    errors: list[str] = []
    for port in _candidate_ports():
        try:
            httpd = ThreadingHTTPServer((HOST, port), Handler)
            return httpd, port
        except OSError as exc:
            # WinError 10013 = excluded/forbidden; 10048 = in use
            errors.append(f"{HOST}:{port} → {exc}")
            continue
    msg = "無法綁定任何埠。嘗試過：\n  - " + "\n  - ".join(errors)
    msg += (
        "\n\nWindows 若出現 WinError 10013：該埠可能在 excluded port range。\n"
        "可改埠：set WAVEDECK_PORT=28765\n"
        "或查看：netsh interface ipv4 show excludedportrange protocol=tcp"
    )
    raise OSError(msg)


def _write_port_file(port: int) -> None:
    try:
        PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
        PORT_FILE.write_text(str(port), encoding="utf-8")
    except Exception as exc:
        sys.stderr.write(f"[wavedeck] port file skip: {exc}\n")


def main() -> None:
    _boot_sync_config()
    httpd, port = _bind_server()
    _write_port_file(port)
    try:
        RUNTIME.patch(transport={"domain": f"{HOST}:{port}", "webhook": "ready"})
    except Exception:
        pass
    try:
        from server.st_link import start as start_st_link

        start_st_link()
    except Exception as exc:
        sys.stderr.write(f"[wavedeck] st_link heartbeat skip: {exc}\n")
    if port != PORT:
        print(f"[wavedeck] 預設埠 {PORT} 不可用，已改用 {port}")
    print("=" * 52)
    print(f" WaveDeck · 浪潮執行台  http://{HOST}:{port}/")
    print(f" Health                 http://{HOST}:{port}/health")
    print(f" Stock Terminal bridge  POST /bridge/st")
    print(f" ST heartbeat           every {os.environ.get('WD_ST_HEARTBEAT_SEC', '5')}s → fail-safe")
    print("=" * 52)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[wavedeck] bye")
        try:
            from server.st_link import stop as stop_st_link

            stop_st_link()
        except Exception:
            pass
        httpd.server_close()


if __name__ == "__main__":
    main()
