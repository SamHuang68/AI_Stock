#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Authenticated loopback gateway for the private Web edition of ST.

The Stock Terminal backend intentionally remains bound to loopback.  This
gateway is the only component intended to sit behind Tailscale Serve (or a
similarly private HTTPS reverse proxy).  It provides:

* owner/read-only tokens (signed browser sessions, Bearer for API clients),
* an explicit route policy that excludes credentials, notifications, refresh
  jobs, WaveDeck and all trading-adjacent controls,
* same-origin checks for browser writes,
* request-size and per-client rate limits, and
* an append-only, body-free audit trail for writes and rejected requests.

It uses only the Python standard library and does not modify the ST backend.
"""
from __future__ import annotations

import base64
import errno
import hashlib
import hmac
import html
import http.client
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import CookieError, SimpleCookie
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, quote, urlsplit

from private_web_access import (
    AccessRequestStore,
    AccessValidationError,
    render_admin_page,
    render_help_page,
    render_request_page,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "data" / "private_web.json"
DEFAULT_OWNER_TOKEN = ROOT / "data" / "private_web_owner.token"
DEFAULT_READ_TOKEN = ROOT / "data" / "private_web_read.token"
DEFAULT_ACCESS_REQUESTS = ROOT / "data" / "private_web_access_requests.json"
STARTUP_TRACE = ROOT / "logs" / "private_web_gateway_startup.jsonl"
CLIENT_TRACE = ROOT / "logs" / "private_web_client.jsonl"
SESSION_COOKIE = "st_private_session"
# Browser sessions are intentionally persistent.  The signed payload has no
# clock expiry; rotating either access token changes the signing key and
# invalidates every existing session without storing a server-side session DB.
PERSISTENT_SESSION_MAX_AGE_SECONDS = 10 * 365 * 24 * 60 * 60
LOGIN_CSRF_TTL_SECONDS = 15 * 60

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

PRIVATE_PROFILE_BOOT = r'''<script id="st-private-web-profile">
window.ST_PRIVATE_WEB_PROFILE={profile:"personal-market",wavedeck:false,remoteTrading:false};
window.SERVER=(window.location&&window.location.origin&&window.location.origin!=="null")?window.location.origin:"http://localhost:18432";
(function(){
  "use strict";
  var cid="private-web-boot-"+Date.now().toString(36)+"-"+Math.random().toString(36).slice(2,9);
  var errorCount=0;
  function clipped(value,limit){return String(value==null?"":value).slice(0,limit||240);}
  function rect(id){
    var node=document.getElementById(id),box=node&&node.getBoundingClientRect();
    return box?{w:Math.round(box.width),h:Math.round(box.height),x:Math.round(box.x),y:Math.round(box.y)}:null;
  }
  function snapshot(){
    return {
      href:clipped(location.pathname+location.hash,160),
      viewport:{w:window.innerWidth||0,h:window.innerHeight||0,dpr:window.devicePixelRatio||1},
      ready:document.readyState,
      booted:document.documentElement.classList.contains("st5-booted"),
      route:document.documentElement.getAttribute("data-st5-route")||"",
      app:rect("app"),topbar:rect("topbar"),body:rect("body"),views:rect("shell-views"),
      pulse:rect("view-pulse"),mount:rect("mount-pulse"),root:rect("pl-root")
    };
  }
  function send(event,detail){
    try{
      fetch("/gateway/client-log",{
        method:"POST",credentials:"same-origin",keepalive:true,
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({event:event,correlationId:cid,detail:detail||snapshot()})
      }).catch(function(){});
    }catch(ignore){}
  }
  window.addEventListener("error",function(ev){
    errorCount+=1;
    if(errorCount>24){
      if(errorCount===25){send("client_error_suppressed",{count:errorCount,state:snapshot()});}
      return;
    }
    var target=ev&&ev.target;
    var resource=target&&(target.currentSrc||target.src||target.href)||"";
    send("client_error",{
      message:clipped(ev&&ev.message,300),source:clipped(ev&&ev.filename,180),
      resource:clipped(resource,240),tag:clipped(target&&target.tagName,24),
      stack:clipped(ev&&ev.error&&ev.error.stack,600),
      line:ev&&ev.lineno||0,column:ev&&ev.colno||0,state:snapshot()
    });
  },true);
  window.addEventListener("unhandledrejection",function(ev){
    var reason=ev&&ev.reason;
    send("client_rejection",{message:clipped(reason&&reason.message||reason,300),state:snapshot()});
  });
  document.addEventListener("DOMContentLoaded",function(){
    send("dom_ready",snapshot());
    setTimeout(function(){send("boot_probe_1s",snapshot());},1000);
    setTimeout(function(){
      var state=snapshot();
      send("boot_probe_5s",state);
      if(state.booted){return;}
      try{
        if(window.ShellV5&&typeof window.ShellV5.go==="function"){
          window.ShellV5.go("pulse");
        }
      }catch(ignore){}
      if(document.documentElement.classList.contains("st5-booted")){return;}
      document.documentElement.classList.add("st5-booted");
      document.documentElement.setAttribute("data-st5-route","chart");
      var body=document.getElementById("body"),topbar=document.getElementById("topbar");
      var views=document.getElementById("shell-views");
      if(body){body.classList.remove("shell-hidden");}
      if(topbar){topbar.classList.remove("shell-hidden");}
      if(views){views.classList.remove("show");}
      var app=document.getElementById("app");
      if(app&&!document.getElementById("st-private-web-recovery")){
        var note=document.createElement("button");
        note.id="st-private-web-recovery";
        note.type="button";
        note.textContent="完整介面載入失敗 · 目前顯示基本圖表 · 點此重試";
        note.setAttribute("style","position:fixed;z-index:20050;left:10px;right:10px;bottom:max(10px,env(safe-area-inset-bottom));padding:10px 12px;border:1px solid #536b88;border-radius:10px;background:#101c30;color:#dbeafe;font:700 12px -apple-system,sans-serif;box-shadow:0 8px 26px rgba(0,0,0,.5)");
        note.onclick=function(){location.reload();};
        app.appendChild(note);
      }
      send("boot_recovered",snapshot());
    },5000);
  });
})();
</script>'''.encode("utf-8")


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _session_key(settings: "Settings") -> bytes:
    material = (settings.owner_token + "\0" + settings.read_token).encode("utf-8")
    return hashlib.sha256(b"st-private-web-session-v1\0" + material).digest()


def _make_session(settings: "Settings", role: str) -> str:
    payload = {
        "v": 2,
        "r": role,
        "n": uuid.uuid4().hex[:16],
    }
    encoded = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = _b64url_encode(
        hmac.new(_session_key(settings), encoded.encode("ascii"), hashlib.sha256).digest()
    )
    return encoded + "." + signature


def _read_session(settings: "Settings", value: str) -> str | None:
    try:
        encoded, signature = value.split(".", 1)
        expected = _b64url_encode(
            hmac.new(_session_key(settings), encoded.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(_b64url_decode(encoded).decode("utf-8"))
        role = str(payload.get("r") or "")
        version = payload.get("v")
        if role not in {"owner", "reader"}:
            return None
        if version == 1:
            # Accept still-valid legacy sessions during the rollout.  The next
            # successful form login always creates the persistent v2 contract.
            expires = int(payload.get("e") or 0)
            if expires <= int(time.time()):
                return None
        elif version != 2:
            return None
        return role
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def _make_login_csrf(settings: "Settings", request_host: str) -> str:
    payload = {
        "v": 1,
        "h": request_host.strip().lower()[:200],
        "e": int(time.time()) + LOGIN_CSRF_TTL_SECONDS,
        "n": uuid.uuid4().hex[:20],
    }
    encoded = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = _b64url_encode(
        hmac.new(
            _session_key(settings),
            ("login-csrf\0" + encoded).encode("ascii"),
            hashlib.sha256,
        ).digest()
    )
    return encoded + "." + signature


def _valid_login_csrf(settings: "Settings", value: str, request_host: str) -> bool:
    if not value or len(value) > 2048:
        return False
    try:
        encoded, signature = value.split(".", 1)
        expected = _b64url_encode(
            hmac.new(
                _session_key(settings),
                ("login-csrf\0" + encoded).encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        if not hmac.compare_digest(signature, expected):
            return False
        payload = json.loads(_b64url_decode(encoded).decode("utf-8"))
        return (
            payload.get("v") == 1
            and int(payload.get("e") or 0) > int(time.time())
            and str(payload.get("h") or "") == request_host.strip().lower()[:200]
        )
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return False


def _make_form_csrf(settings: "Settings", request_host: str, purpose: str) -> str:
    clean_purpose = re.sub(r"[^a-z0-9_-]", "", purpose.lower())[:40]
    payload = {
        "v": 1,
        "p": clean_purpose,
        "h": request_host.strip().lower()[:200],
        "e": int(time.time()) + LOGIN_CSRF_TTL_SECONDS,
        "n": uuid.uuid4().hex[:20],
    }
    encoded = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signature = _b64url_encode(
        hmac.new(
            _session_key(settings),
            ("form-csrf\0" + clean_purpose + "\0" + encoded).encode("ascii"),
            hashlib.sha256,
        ).digest()
    )
    return encoded + "." + signature


def _valid_form_csrf(
    settings: "Settings", value: str, request_host: str, purpose: str
) -> bool:
    if not value or len(value) > 2048:
        return False
    clean_purpose = re.sub(r"[^a-z0-9_-]", "", purpose.lower())[:40]
    try:
        encoded, signature = value.split(".", 1)
        expected = _b64url_encode(
            hmac.new(
                _session_key(settings),
                ("form-csrf\0" + clean_purpose + "\0" + encoded).encode("ascii"),
                hashlib.sha256,
            ).digest()
        )
        if not hmac.compare_digest(signature, expected):
            return False
        payload = json.loads(_b64url_decode(encoded).decode("utf-8"))
        return (
            payload.get("v") == 1
            and payload.get("p") == clean_purpose
            and int(payload.get("e") or 0) > int(time.time())
            and str(payload.get("h") or "") == request_host.strip().lower()[:200]
        )
    except (ValueError, TypeError, UnicodeDecodeError, json.JSONDecodeError):
        return False

# Static files required by the generated ST UI.  Arbitrary filesystem paths
# never pass through the gateway.
STATIC_EXACT = {
    "/",
    "/index.html",
    "/stock_terminal.html",
    "/stock_terminal_v2.html",
    "/favicon.ico",
}
STATIC_PREFIXES = ("/assets/", "/src/")

# Read-only market/research API.  Prefix matching is segment-aware below.
READ_GET_EXACT = {
    "/health",
    "/health/live",
    "/etf-delta",
    "/etf-catalog",
    "/etf-tracker/status",
    "/quote-batch",
    "/bars",
    "/universe",
    "/datasources",
    "/marketflow",
    "/breadth",
    "/pulse",
    "/pulse/history",
    "/decision/context",
    "/decision/history",
    "/signals/active",
    "/signals/history",
    "/research/overnight-intraday",
    "/options/txo/structure",
    "/options/txo/history",
    "/key-levels",
    "/sync/status",
    "/movers",
    "/inst-rank",
    "/events",
    "/flash",
    "/sectors",
    "/ai/local/status",
    "/screener",
    "/focus",
    "/alert/status",
    "/watch/status",
    "/txf",
    "/stockfut",
    "/twindex",
    "/market/snapshot",
    "/margin_ratio",
    "/search",
    "/ai-key/status",
    "/ai-model",
    "/twquote-batch",
    "/twquote",
    "/selftest",
    "/macro",
}
READ_GET_PREFIXES = (
    "/yf/",
    "/quote/",
    "/chip/",
    "/holders/",
    "/keystats/",
    "/fundamental/",
    "/valuation/",
    "/macro/",
)

# Personal state is visible only with the owner token.
OWNER_GET_EXACT = {
    "/alert/rules",
    "/alert/config",  # ST masks stored transport credentials in its response.
    "/api/override-alpha",
    "/api/llm-gate",
}
OWNER_GET_PREFIXES = ("/draw/",)

# Deliberately narrow write surface for a long-horizon market/research user.
CONTROL_POST_EXACT = {
    "/diagnostics/ui-route",
    "/screener",
    "/screen3",
    "/portfolio",
    "/decision/context",
    "/research/overnight-intraday/refresh",
    "/options/txo/refresh",
    "/chain-momentum",
    "/ai/local",
    "/ai/deep",
    "/ai-report",
    "/etf-reason",
    "/ai-note",
    "/watch/rules",
    "/watch/config",
    "/alert/rules",
}
CONTROL_POST_PREFIXES = ("/draw/",)

# These backend endpoints are intentionally not remotely reachable, even with
# the owner token.  They are listed here for status/documentation responses.
BLOCKED_REMOTE_PATHS = {
    "POST /ai-key",
    "POST /ai-proxy",
    "POST /etf-catalog",
    "POST /etf-tracker/run",
    "GET/POST /bridge/wavedeck",
    "GET /bridge/wavedeck/stream",
    "GET/POST /api/cost-meter",
    "POST /api/override-alpha",
    "POST /api/override-alpha/review",
    "POST /api/llm-gate",
    "POST /notify",
    "POST /universe/refresh",
    "POST /datasource/refresh",
    "POST /macro/refresh",
    "POST /margin_ratio/backfill",
    "POST /alert/config",
    "POST /alert/test",
    "POST /etf-report/email",
    "POST /report-email",
    "GET/POST /sync",
}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _read_secret(path: Path, env_name: str) -> str:
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _tcp_port_snapshot(port: int) -> list[dict[str, object]]:
    """Capture sanitized Windows TCP ownership at a failed bind boundary."""
    try:
        result = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    rows: list[dict[str, object]] = []
    suffix = f":{port}"
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local, remote, state, pid_text = parts[1:5]
        if not (local.endswith(suffix) or remote.endswith(suffix)):
            continue
        try:
            pid = int(pid_text)
        except ValueError:
            pid = -1
        rows.append(
            {"local": local, "remote": remote, "state": state, "pid": pid}
        )
    return rows[:50]


def _startup_event(event: str, **details: object) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "component": "private_web_gateway",
        "event": event,
        **details,
    }
    try:
        STARTUP_TRACE.parent.mkdir(parents=True, exist_ok=True)
        with STARTUP_TRACE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass


def _string_list(value: object, default: Iterable[str] = ()) -> tuple[str, ...]:
    if not isinstance(value, list):
        return tuple(default)
    return tuple(str(item).strip().lower() for item in value if str(item).strip())


def _normalized_extra_paths(value: object) -> tuple[str, ...]:
    paths = _string_list(value)
    return tuple(path for path in paths if path.startswith("/") and ".." not in path)


@dataclass(frozen=True)
class Settings:
    listen_host: str
    listen_port: int
    upstream_host: str
    upstream_port: int
    owner_token: str
    read_token: str
    allowed_hosts: tuple[str, ...]
    allowed_host_suffixes: tuple[str, ...]
    max_body_bytes: int
    read_rate_per_minute: int
    write_rate_per_minute: int
    upstream_timeout_seconds: int
    audit_path: Path
    access_request_path: Path
    client_trace_path: Path = CLIENT_TRACE
    ai_upstream_timeout_seconds: int = 1200
    extra_read_paths: tuple[str, ...] = ()
    extra_control_paths: tuple[str, ...] = ()
    dev_bypass: bool = False
    instance_id: str = ""
    mode: str = "dev-linked"

    @classmethod
    def load(cls, config_path: Path | None = None) -> "Settings":
        path = config_path or Path(os.environ.get("ST_WEB_CONFIG", str(DEFAULT_CONFIG)))
        cfg = _read_json(path)
        upstream = os.environ.get("ST_WEB_UPSTREAM", str(cfg.get("upstream") or "http://127.0.0.1:18432"))
        parsed = urlsplit(upstream)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("private web upstream must be an http loopback address")
        upstream_port = parsed.port or 80

        owner_path = Path(os.environ.get("ST_WEB_OWNER_TOKEN_FILE", str(DEFAULT_OWNER_TOKEN)))
        read_path = Path(os.environ.get("ST_WEB_READ_TOKEN_FILE", str(DEFAULT_READ_TOKEN)))
        owner = _read_secret(owner_path, "ST_WEB_OWNER_TOKEN")
        reader = _read_secret(read_path, "ST_WEB_READ_TOKEN")
        dev_bypass = os.environ.get("ST_WEB_DEV_BYPASS", "").lower() in {"1", "true", "yes"}
        if not owner and not dev_bypass:
            raise ValueError(
                f"owner token missing; run scripts/setup_private_web.py (expected {owner_path})"
            )

        listen_host = os.environ.get("ST_WEB_LISTEN_HOST", str(cfg.get("listen_host") or "127.0.0.1"))
        if listen_host not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("gateway must remain loopback; publish it through a private HTTPS proxy")
        listen_port = _env_int(
            "ST_WEB_LISTEN_PORT", int(cfg.get("listen_port") or 18434), minimum=1024, maximum=65535
        )
        audit_value = os.environ.get("ST_WEB_AUDIT_PATH", str(cfg.get("audit_path") or "logs/private_web_audit.jsonl"))
        audit_path = Path(audit_value)
        if not audit_path.is_absolute():
            audit_path = ROOT / audit_path
        client_trace_value = os.environ.get(
            "ST_WEB_CLIENT_TRACE_PATH",
            str(cfg.get("client_trace_path") or "logs/private_web_client.jsonl"),
        )
        client_trace_path = Path(client_trace_value)
        if not client_trace_path.is_absolute():
            client_trace_path = ROOT / client_trace_path
        access_request_value = os.environ.get(
            "ST_WEB_ACCESS_REQUEST_PATH",
            str(cfg.get("access_request_path") or DEFAULT_ACCESS_REQUESTS),
        )
        access_request_path = Path(access_request_value)
        if not access_request_path.is_absolute():
            access_request_path = ROOT / access_request_path
        instance_id = re.sub(
            r"[^A-Za-z0-9._-]", "", os.environ.get("ST_WEB_INSTANCE_ID", "")
        )[:96]
        mode = os.environ.get("ST_WEB_MODE", "dev-linked").strip().lower()
        if mode not in {"dev-linked", "isolated-host"}:
            mode = "dev-linked"

        return cls(
            listen_host=listen_host,
            listen_port=listen_port,
            upstream_host=parsed.hostname or "127.0.0.1",
            upstream_port=upstream_port,
            owner_token=owner,
            read_token=reader,
            allowed_hosts=_string_list(cfg.get("allowed_hosts"), ("localhost", "127.0.0.1", "::1")),
            allowed_host_suffixes=_string_list(cfg.get("allowed_host_suffixes"), (".ts.net",)),
            max_body_bytes=_env_int(
                "ST_WEB_MAX_BODY_BYTES", int(cfg.get("max_body_bytes") or 1_048_576),
                minimum=1024, maximum=8_388_608,
            ),
            read_rate_per_minute=_env_int(
                "ST_WEB_READ_RATE", int(cfg.get("read_rate_per_minute") or 240),
                minimum=10, maximum=5000,
            ),
            write_rate_per_minute=_env_int(
                "ST_WEB_WRITE_RATE", int(cfg.get("write_rate_per_minute") or 30),
                minimum=1, maximum=600,
            ),
            upstream_timeout_seconds=_env_int(
                "ST_WEB_UPSTREAM_TIMEOUT", int(cfg.get("upstream_timeout_seconds") or 120),
                minimum=5, maximum=1800,
            ),
            audit_path=audit_path,
            access_request_path=access_request_path,
            client_trace_path=client_trace_path,
            ai_upstream_timeout_seconds=_env_int(
                "ST_WEB_AI_UPSTREAM_TIMEOUT",
                int(cfg.get("ai_upstream_timeout_seconds") or 1200),
                minimum=60,
                maximum=1800,
            ),
            extra_read_paths=_normalized_extra_paths(cfg.get("extra_read_paths")),
            extra_control_paths=_normalized_extra_paths(cfg.get("extra_control_paths")),
            dev_bypass=dev_bypass,
            instance_id=instance_id,
            mode=mode,
        )


class WindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, client: str, bucket: str, limit: int) -> bool:
        now = time.monotonic()
        cutoff = now - 60.0
        key = (client, bucket)
        with self._lock:
            events = self._events[key]
            while events and events[0] < cutoff:
                events.popleft()
            if len(events) >= limit:
                return False
            events.append(now)
            return True


class PrivateWebServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False
    # Tailscale Serve terminates browser HTTP/2 and can fan one dashboard load
    # out into dozens of simultaneous loopback requests.  The stdlib default
    # backlog is only 5, so excess asset connections are rejected by the OS
    # before Handler/_audit ever sees them and Tailscale surfaces random 502s.
    request_queue_size = 128

    def server_bind(self) -> None:
        # Windows SO_REUSEADDR can allow multiple listeners on the same tuple,
        # which would randomly route authenticated requests between versions.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(
                socket.SOL_SOCKET,
                socket.SO_EXCLUSIVEADDRUSE,
                1,
            )
        super().server_bind()

    def __init__(self, address: tuple[str, int], handler, settings: Settings):
        super().__init__(address, handler)
        self.settings = settings
        self.rate_limiter = WindowRateLimiter()
        self.audit_lock = threading.Lock()
        self.access_store = AccessRequestStore(settings.access_request_path)


def _path_matches(path: str, exact: set[str], prefixes: tuple[str, ...]) -> bool:
    if path in exact:
        return True
    return any(path.startswith(prefix) for prefix in prefixes)


def route_permission(method: str, path: str, role: str, settings: Settings) -> bool:
    if method in {"GET", "HEAD"}:
        if path in STATIC_EXACT or path.startswith(STATIC_PREFIXES):
            return True
        if _path_matches(path, READ_GET_EXACT, READ_GET_PREFIXES):
            return True
        if path in settings.extra_read_paths:
            return True
        if role == "owner" and _path_matches(path, OWNER_GET_EXACT, OWNER_GET_PREFIXES):
            return True
        return False
    if method == "POST" and role == "owner":
        if _path_matches(path, CONTROL_POST_EXACT, CONTROL_POST_PREFIXES):
            return True
        return path in settings.extra_control_paths
    return False


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "STPrivateWeb/1.0"

    @property
    def settings(self) -> Settings:
        return self.server.settings  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: object) -> None:
        # Access details are captured by the structured audit trail without
        # leaking Authorization headers or request bodies.
        return

    def _json(self, status: int, payload: dict, *, challenge: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'")
        if challenge:
            self.send_header("WWW-Authenticate", 'Basic realm="Private Web ST", charset="UTF-8"')
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_html(
        self,
        status: int,
        body: str,
        *,
        location: str = "",
        cookie: str = "",
    ) -> None:
        raw = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; "
            "base-uri 'none'; frame-ancestors 'none'",
        )
        if location:
            self.send_header("Location", location)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(raw)

    def _request_is_https(self) -> bool:
        forwarded = (self.headers.get("X-Forwarded-Proto") or "").split(",", 1)[0].strip().lower()
        if forwarded == "https":
            return True
        host = (self.headers.get("Host") or "").split(":", 1)[0].strip().lower()
        return host.endswith(".ts.net")

    def _cookie_value(self, role: str) -> str:
        parts = [
            f"{SESSION_COOKIE}={_make_session(self.settings, role)}",
            "Path=/",
            "HttpOnly",
            "SameSite=Strict",
            f"Max-Age={PERSISTENT_SESSION_MAX_AGE_SECONDS}",
        ]
        if self._request_is_https():
            parts.append("Secure")
        return "; ".join(parts)

    def _clear_cookie_value(self) -> str:
        parts = [
            f"{SESSION_COOKIE}=",
            "Path=/",
            "HttpOnly",
            "SameSite=Strict",
            "Max-Age=0",
        ]
        if self._request_is_https():
            parts.append("Secure")
        return "; ".join(parts)

    @staticmethod
    def _safe_next(value: object) -> str:
        path = str(value or "/")[:512]
        if not path.startswith("/") or path.startswith("//") or "\\" in path:
            return "/"
        if "\r" in path or "\n" in path or path.startswith("/gateway/login"):
            return "/"
        return path

    def _login_page(self, *, status: int = 200, error: str = "", next_path: str = "/") -> None:
        safe_next = html.escape(self._safe_next(next_path), quote=True)
        csrf = html.escape(
            _make_login_csrf(self.settings, self.headers.get("Host") or ""),
            quote=True,
        )
        error_html = (
            '<div class="error" role="alert">' + html.escape(error) + "</div>"
            if error else ""
        )
        page = f'''<!doctype html>
<html lang="zh-TW"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>登入 Stock Terminal</title>
<style>
:root{{--bg:#060a12;--panel:#0d1727;--line:#253851;--text:#dbe7f5;--muted:#8ea1b8;--gold:#f5c518;--cyan:#67e8f9}}
*{{box-sizing:border-box}}html,body{{min-height:100%;margin:0;background:radial-gradient(circle at 18% 4%,#142641 0,transparent 38%),var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Noto Sans TC",sans-serif}}
body{{display:grid;place-items:center;padding:max(22px,env(safe-area-inset-top)) 18px max(22px,env(safe-area-inset-bottom))}}
.card{{width:min(440px,100%);padding:26px 24px 22px;border:1px solid var(--line);border-radius:18px;background:rgba(13,23,39,.94);box-shadow:0 24px 70px rgba(0,0,0,.48),inset 0 1px rgba(255,255,255,.05)}}
.brand{{display:flex;align-items:center;gap:12px;margin-bottom:20px}}.mark{{display:grid;place-items:center;width:42px;height:42px;border-radius:12px;border:1px solid rgba(245,197,24,.42);background:#101c30;color:var(--gold);font:800 16px monospace;box-shadow:0 0 24px rgba(245,197,24,.12)}}
h1{{font-size:22px;margin:0}}.sub{{margin:4px 0 0;color:var(--muted);font-size:13px;line-height:1.5}}
label.title{{display:block;margin:15px 0 7px;color:#b8c8da;font-size:13px;font-weight:700}}
select,input[type=password]{{width:100%;min-height:46px;border:1px solid #314963;border-radius:10px;background:#07111f;color:#f4f8fc;padding:10px 12px;font-size:16px;outline:none}}
select:focus,input:focus{{border-color:var(--cyan);box-shadow:0 0 0 3px rgba(103,232,249,.1)}}
.session-note{{margin:16px 0;color:#aebed0;font-size:12px;line-height:1.6}}
button{{width:100%;min-height:48px;border:0;border-radius:11px;background:linear-gradient(135deg,#facc15,#e5a70a);color:#09101b;font-size:16px;font-weight:900;cursor:pointer}}
.error{{margin:0 0 13px;padding:10px 12px;border:1px solid rgba(248,113,113,.5);border-radius:9px;background:rgba(127,29,29,.18);color:#fecaca;font-size:13px}}
.help{{margin-top:18px;padding-top:15px;border-top:1px solid #203149;color:var(--muted);font-size:12px;line-height:1.65}}.help b{{color:#dce8f5}}.help a{{color:var(--cyan);font-weight:800;text-underline-offset:3px}}
</style></head><body><main class="card">
<div class="brand"><div class="mark">ST</div><div><h1>Stock Terminal</h1><p class="sub">Tailscale 私有市場研究站</p></div></div>
{error_html}
<form method="post" action="/gateway/login" autocomplete="on">
<input type="hidden" name="next" value="{safe_next}">
<input type="hidden" name="csrf" value="{csrf}">
<label class="title" for="role">登入身分</label>
<select id="role" name="role"><option value="owner">Owner（完整研究權限）</option><option value="reader">Reader（唯讀）</option></select>
<label class="title" for="token">ST 存取密碼</label>
<input id="token" name="token" type="password" required autocomplete="current-password" autocapitalize="none" spellcheck="false">
<p class="session-note">登入狀態會持續保留；只有清除本站資料或管理者更換存取密碼後才需要重新登入。</p>
<button type="submit">安全登入</button>
</form>
<div class="help"><b>第一次使用？</b><br>先接受管理者提供的 Tailscale 主機分享，再送出 Reader 使用權申請。申請不會自動開通。<br><a href="/gateway/request-access">申請使用權</a>　·　<a href="/gateway/help">查看手機／Windows 圖文教學</a>　·　<a href="/gateway/admin">Owner 後台</a></div>
</main></body></html>'''
        self._send_html(status, page)

    def _login_help_page(self) -> None:
        host = (self.headers.get("Host") or "localhost").strip()
        scheme = "https" if self._request_is_https() else "http"
        self._send_html(200, render_help_page(service_url=f"{scheme}://{host}/"))

    def _read_form(self, *, maximum: int = 16_384) -> dict[str, str]:
        if self.headers.get("Transfer-Encoding"):
            raise AccessValidationError("請求格式不支援。")
        try:
            content_length = int(self.headers.get("Content-Length") or "0")
        except ValueError as exc:
            raise AccessValidationError("表單格式不正確。") from exc
        if content_length < 1 or content_length > maximum:
            raise AccessValidationError("表單內容大小不正確。")
        try:
            parsed = parse_qs(
                self.rfile.read(content_length).decode("utf-8"),
                keep_blank_values=True,
                max_num_fields=24,
            )
        except (UnicodeDecodeError, ValueError) as exc:
            raise AccessValidationError("表單格式不正確。") from exc
        return {key: values[0] if values else "" for key, values in parsed.items()}

    def _form_origin_allowed(self) -> bool:
        origin = (self.headers.get("Origin") or "").strip()
        if not origin or origin.lower() == "null":
            return True
        try:
            return urlsplit(origin).netloc.lower() == (
                self.headers.get("Host") or ""
            ).strip().lower()
        except ValueError:
            return False

    def _access_request_page(
        self,
        *,
        status: int = 200,
        values: dict[str, object] | None = None,
        error: str = "",
        receipt: str = "",
        duplicate: bool = False,
    ) -> None:
        csrf = _make_form_csrf(
            self.settings,
            self.headers.get("Host") or "",
            "access-request",
        )
        self._send_html(
            status,
            render_request_page(
                csrf=csrf,
                values=values,
                error=error,
                receipt=receipt,
                duplicate=duplicate,
            ),
        )

    def _access_request_post(self) -> None:
        try:
            form = self._read_form()
        except AccessValidationError as exc:
            self._access_request_page(status=400, error=str(exc))
            return
        request_host = (self.headers.get("Host") or "").strip().lower()
        if not _valid_form_csrf(
            self.settings,
            form.get("csrf", ""),
            request_host,
            "access-request",
        ):
            self._audit("access_request_csrf_rejected", 403)
            self._access_request_page(status=403, values=form, error="申請頁已過期，請重新整理後再試。")
            return
        if not self._form_origin_allowed():
            self._audit("access_request_origin_rejected", 403)
            self._access_request_page(status=403, error="申請來源驗證失敗，請重新開啟本站。")
            return
        if form.get("consent") != "yes":
            self._access_request_page(status=400, values=form, error="請先確認申請與安全聲明。")
            return
        try:
            row, created = self.server.access_store.create(  # type: ignore[attr-defined]
                display_name=form.get("display_name"),
                contact_email=form.get("contact_email"),
                tailscale_email=form.get("tailscale_email"),
                platform=form.get("platform"),
                note=form.get("note"),
            )
        except AccessValidationError as exc:
            self._access_request_page(status=400, values=form, error=str(exc))
            return
        except (OSError, RuntimeError):
            self._audit("access_request_store_failed", 503)
            self._access_request_page(status=503, error="申請資料暫時無法保存，請稍後再試。")
            return
        request_id = str(row.get("id") or "")
        self._audit(
            "access_request_submitted" if created else "access_request_duplicate",
            201 if created else 200,
            requestIdRef=request_id,
        )
        self._access_request_page(
            status=201 if created else 200,
            receipt=request_id,
            duplicate=not created,
        )

    def _admin_page(self, *, status: int = 200, error: str = "") -> None:
        try:
            requests = self.server.access_store.list_requests()  # type: ignore[attr-defined]
        except (OSError, RuntimeError):
            requests = []
            status = 503
            error = "申請資料暫時無法讀取，請檢查本機資料檔與備份。"
            self._audit("access_request_store_failed", 503, "owner")
        query = parse_qs(urlsplit(self.path).query)
        notice = "申請狀態已更新。" if (query.get("updated") or [""])[0] == "1" else ""
        csrf = _make_form_csrf(
            self.settings,
            self.headers.get("Host") or "",
            "access-admin",
        )
        self._send_html(
            status,
            render_admin_page(
                requests=requests,
                csrf=csrf,
                mode=self.settings.mode,
                instance_id=self.settings.instance_id,
                notice=notice,
                error=error,
            ),
        )

    def _admin_post(self, auth_kind: str) -> None:
        try:
            form = self._read_form()
        except AccessValidationError as exc:
            self._admin_page(status=400, error=str(exc))
            return
        request_host = (self.headers.get("Host") or "").strip().lower()
        if not _valid_form_csrf(
            self.settings,
            form.get("csrf", ""),
            request_host,
            "access-admin",
        ):
            self._audit("access_admin_csrf_rejected", 403, "owner")
            self._admin_page(status=403, error="管理頁已過期，請重新整理後再試。")
            return
        if not self._origin_ok(auth_kind):
            self._audit("access_admin_origin_rejected", 403, "owner")
            self._admin_page(status=403, error="管理操作來源驗證失敗。")
            return
        try:
            row = self.server.access_store.update_status(  # type: ignore[attr-defined]
                form.get("request_id"),
                status=form.get("status"),
                admin_note=form.get("admin_note"),
            )
        except AccessValidationError as exc:
            self._admin_page(status=400, error=str(exc))
            return
        except (OSError, RuntimeError):
            self._audit("access_request_store_failed", 503, "owner")
            self._admin_page(status=503, error="申請資料暫時無法更新。")
            return
        self._audit(
            "access_request_status_changed",
            303,
            "owner",
            requestIdRef=str(row.get("id") or ""),
            newStatus=str(row.get("status") or ""),
        )
        self._send_html(
            303,
            "<!doctype html><title>狀態已更新</title>",
            location="/gateway/admin?updated=1",
        )

    def _login_post(self) -> None:
        if self.headers.get("Transfer-Encoding"):
            self._json(411, {"error": "Content-Length required"})
            return
        try:
            content_length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            content_length = -1
        if content_length < 1 or content_length > 8192:
            self._login_page(status=400, error="登入資料格式不正確。")
            return
        try:
            form = parse_qs(self.rfile.read(content_length).decode("utf-8"), keep_blank_values=True)
        except UnicodeDecodeError:
            self._login_page(status=400, error="登入資料格式不正確。")
            return
        role = (form.get("role") or [""])[0].strip().lower()
        token = (form.get("token") or [""])[0].strip()
        next_path = self._safe_next((form.get("next") or ["/"])[0])
        request_host = (self.headers.get("Host") or "").strip().lower()
        csrf = (form.get("csrf") or [""])[0]
        if not _valid_login_csrf(self.settings, csrf, request_host):
            self._audit("login_csrf_rejected", 403)
            self._login_page(status=403, error="登入頁已過期，請重新整理後再試。")
            return
        origin = (self.headers.get("Origin") or "").strip()
        if origin and origin.lower() != "null":
            try:
                origin_host = urlsplit(origin).netloc.lower()
                if origin_host != request_host:
                    self._audit(
                        "login_origin_rejected",
                        403,
                        originHost=origin_host[:200],
                        requestHost=request_host[:200],
                    )
                    self._login_page(status=403, error="登入來源驗證失敗，請重新開啟本站。")
                    return
            except ValueError:
                self._login_page(status=403, error="登入來源驗證失敗。")
                return
        expected = self.settings.owner_token if role == "owner" else self.settings.read_token if role == "reader" else ""
        if not expected or not token or not hmac.compare_digest(token, expected):
            self._audit("login_failed", 401, role if role in {"owner", "reader"} else "none")
            self._login_page(status=401, error="身分或存取密碼不正確。", next_path=next_path)
            return
        self._audit("login_succeeded", 303, role, persistent=True)
        self._send_html(
            303,
            "<!doctype html><title>登入完成</title>",
            location=next_path,
            cookie=self._cookie_value(role),
        )

    def _logout(self) -> None:
        self._audit("logout", 303)
        self._send_html(
            303,
            "<!doctype html><title>已登出</title>",
            location="/gateway/login",
            cookie=self._clear_cookie_value(),
        )

    def _request_id(self) -> str:
        value = getattr(self, "_rid", "")
        if not value:
            value = uuid.uuid4().hex
            self._rid = value
        return value

    def _client_identity(self) -> str:
        peer = self.client_address[0]
        if peer in {"127.0.0.1", "::1"}:
            forwarded = (self.headers.get("X-Forwarded-For") or "").split(",", 1)[0].strip()
            login = (self.headers.get("Tailscale-User-Login") or "").strip()
            candidate = login or forwarded
            if candidate and re.fullmatch(r"[A-Za-z0-9_.:@+-]{1,160}", candidate):
                return candidate
        return peer

    def _audit(self, event: str, status: int, role: str = "none", **details: object) -> None:
        client = self._client_identity()
        if event.startswith("access_"):
            # Access-application events must remain correlatable without
            # persisting a Tailscale login email or forwarded client identity.
            client = "anon-" + hashlib.sha256(
                ("private-web-access-audit\0" + client).encode("utf-8")
            ).hexdigest()[:16]
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": "private_web_gateway",
            "event": event,
            "requestId": self._request_id(),
            "method": self.command,
            "path": urlsplit(self.path).path,
            "status": status,
            "role": role,
            "client": client,
            **details,
        }
        try:
            self.settings.audit_path.parent.mkdir(parents=True, exist_ok=True)
            lock = self.server.audit_lock  # type: ignore[attr-defined]
            with lock, self.settings.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError:
            pass

    @staticmethod
    def _sanitize_client_detail(value: object, *, depth: int = 0) -> object:
        if depth > 3:
            return "[depth-limit]"
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return value[:320]
        if isinstance(value, list):
            return [Handler._sanitize_client_detail(item, depth=depth + 1) for item in value[:24]]
        if isinstance(value, dict):
            safe: dict[str, object] = {}
            for key, item in list(value.items())[:48]:
                clean_key = re.sub(r"[^A-Za-z0-9_.-]", "", str(key))[:64]
                if clean_key:
                    safe[clean_key] = Handler._sanitize_client_detail(item, depth=depth + 1)
            return safe
        return str(type(value).__name__)[:64]

    def _client_log(self, role: str) -> None:
        allowed_events = {
            "dom_ready", "boot_probe_1s", "boot_probe_5s",
            "client_error", "client_rejection", "boot_recovered",
        }
        if self.headers.get("Transfer-Encoding"):
            self._json(411, {"error": "Content-Length required"})
            return
        try:
            content_length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            content_length = -1
        if content_length < 2 or content_length > 16_384:
            self._json(413, {"error": "client trace body invalid"})
            return
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self._json(400, {"error": "client trace JSON invalid"})
            return
        if not isinstance(payload, dict):
            self._json(400, {"error": "client trace object required"})
            return
        event = str(payload.get("event") or "")[:64]
        if event not in allowed_events:
            self._json(400, {"error": "client trace event invalid"})
            return
        correlation_id = re.sub(
            r"[^A-Za-z0-9._-]", "", str(payload.get("correlationId") or "")
        )[:96]
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "component": "private_web_client",
            "event": event,
            "correlationId": correlation_id,
            "requestId": self._request_id(),
            "role": role,
            "client": self._client_identity(),
            "userAgent": (self.headers.get("User-Agent") or "")[:240],
            "detail": self._sanitize_client_detail(payload.get("detail")),
        }
        try:
            self.settings.client_trace_path.parent.mkdir(parents=True, exist_ok=True)
            lock = self.server.audit_lock  # type: ignore[attr-defined]
            with lock, self.settings.client_trace_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError:
            self._json(503, {"error": "client trace unavailable"})
            return
        self._json(202, {"ok": True, "requestId": self._request_id()})

    def _host_allowed(self) -> bool:
        raw = (self.headers.get("Host") or "").strip().lower()
        if not raw:
            return False
        try:
            hostname = urlsplit("//" + raw).hostname or ""
        except ValueError:
            return False
        if hostname in self.settings.allowed_hosts:
            return True
        return any(hostname.endswith(suffix) for suffix in self.settings.allowed_host_suffixes)

    def _auth(self) -> tuple[str, str]:
        if self.settings.dev_bypass and self.client_address[0] in {"127.0.0.1", "::1"}:
            return "owner", "dev-bypass"
        header = (self.headers.get("Authorization") or "").strip()
        scheme, _, credential = header.partition(" ")
        token = ""
        auth_kind = scheme.lower()
        if auth_kind == "bearer":
            token = credential.strip()
        elif auth_kind == "basic":
            try:
                decoded = base64.b64decode(credential.strip(), validate=True).decode("utf-8")
                _, token = decoded.split(":", 1)
            except (ValueError, UnicodeDecodeError):
                token = ""
        if token and self.settings.owner_token and hmac.compare_digest(token, self.settings.owner_token):
            return "owner", auth_kind
        if token and self.settings.read_token and hmac.compare_digest(token, self.settings.read_token):
            return "reader", auth_kind
        try:
            cookies = SimpleCookie()
            cookies.load(self.headers.get("Cookie") or "")
            morsel = cookies.get(SESSION_COOKIE)
            session_value = morsel.value if morsel and len(morsel.value) <= 2048 else ""
            session_role = _read_session(self.settings, session_value) if session_value else None
            if session_role:
                return session_role, "session"
        except (CookieError, ValueError):
            pass
        return "none", auth_kind or "none"

    def _origin_ok(self, auth_kind: str) -> bool:
        # Bearer requests are non-browser API calls.  Cookie/Basic browser
        # writes must be same-origin to prevent CSRF.
        if auth_kind == "bearer" or auth_kind == "dev-bypass":
            return True
        origin = (self.headers.get("Origin") or "").strip()
        if not origin:
            return False
        try:
            parsed = urlsplit(origin)
            origin_host = parsed.netloc.lower()
        except ValueError:
            return False
        request_host = (self.headers.get("Host") or "").strip().lower()
        return parsed.scheme in {"http", "https"} and origin_host == request_host

    def _gateway_health(self) -> None:
        upstream_ok = False
        try:
            conn = http.client.HTTPConnection(
                self.settings.upstream_host,
                self.settings.upstream_port,
                timeout=2,
            )
            conn.request("GET", "/health/live", headers={"Connection": "close"})
            response = conn.getresponse()
            response.read(4096)
            upstream_ok = response.status == 200
            conn.close()
        except OSError:
            pass
        payload = {
            "ok": True,
            "gateway": "private-web",
            "upstream": upstream_ok,
            "mode": self.settings.mode,
        }
        if self.settings.instance_id:
            payload["instance"] = self.settings.instance_id
        self._json(200, payload)

    def _gateway_routes(self, role: str) -> None:
        if role != "owner":
            self._audit("route_denied", 403, role)
            self._json(403, {"error": "owner role required"})
            return
        self._json(
            200,
            {
                "profile": "personal-market",
                "roles": ["reader", "owner"],
                "remoteTrading": False,
                "wavedeck": False,
                "controlPost": sorted(CONTROL_POST_EXACT | set(self.settings.extra_control_paths)),
                "blockedRemote": sorted(BLOCKED_REMOTE_PATHS),
            },
        )

    def _proxy(self, role: str) -> None:
        started = time.monotonic()
        path_only = urlsplit(self.path).path
        ai_request = path_only in {"/ai/local", "/ai/deep"}
        response_started = False
        upstream_status = 0
        bytes_forwarded = 0
        conn: http.client.HTTPConnection | None = None
        content_length_raw = self.headers.get("Content-Length") or "0"
        if self.headers.get("Transfer-Encoding"):
            self._audit("request_rejected", 411, role, reason="chunked_request")
            self._json(411, {"error": "Content-Length required"})
            return
        try:
            content_length = int(content_length_raw)
        except ValueError:
            content_length = -1
        if content_length < 0 or content_length > self.settings.max_body_bytes:
            self._audit("request_rejected", 413, role, reason="body_too_large")
            self._json(413, {"error": "request body too large"})
            return
        body = self.rfile.read(content_length) if content_length else None

        outbound_headers: dict[str, str] = {}
        blocked = HOP_BY_HOP | {
            "authorization",
            "cookie",
            "host",
            "origin",
            "referer",
            "forwarded",
            "x-forwarded-for",
            "x-forwarded-host",
            "x-forwarded-proto",
        }
        for key, value in self.headers.items():
            if key.lower() not in blocked:
                outbound_headers[key] = value
        outbound_headers["Host"] = f"{self.settings.upstream_host}:{self.settings.upstream_port}"
        outbound_headers["Connection"] = "close"
        outbound_headers["X-ST-Gateway-Role"] = role
        try:
            conn = http.client.HTTPConnection(
                self.settings.upstream_host,
                self.settings.upstream_port,
                timeout=(
                    self.settings.ai_upstream_timeout_seconds
                    if ai_request else self.settings.upstream_timeout_seconds
                ),
            )
            conn.request(self.command, self.path, body=body, headers=outbound_headers)
            response = conn.getresponse()
            upstream_status = response.status
            response_headers = response.getheaders()
            content_type = next(
                (value for key, value in response_headers if key.lower() == "content-type"),
                "",
            ).lower()
            inject_profile = (
                self.command == "GET"
                and response.status == 200
                and "text/html" in content_type
            )
            injected_body = None
            if inject_profile:
                injected_body = response.read()
                marker = b"<head>"
                if marker in injected_body:
                    injected_body = injected_body.replace(
                        marker, marker + PRIVATE_PROFILE_BOOT, 1
                    )
                else:
                    injected_body = PRIVATE_PROFILE_BOOT + injected_body
            self.send_response(response.status, response.reason)
            for key, value in response_headers:
                lower = key.lower()
                if lower not in HOP_BY_HOP and lower not in {
                    "server", "date", "access-control-allow-origin",
                } and not (inject_profile and lower == "content-length"):
                    self.send_header(key, value)
            if injected_body is not None:
                self.send_header("Content-Length", str(len(injected_body)))
            self.send_header("Cache-Control", "no-store" if self.command == "POST" else "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "same-origin")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Connection", "close")
            self.end_headers()
            response_started = True
            if self.command != "HEAD":
                if injected_body is not None:
                    self.wfile.write(injected_body)
                    bytes_forwarded += len(injected_body)
                else:
                    while True:
                        # read1 returns an available HTTP/socket chunk instead
                        # of waiting to fill a large 64 KiB buffer. This is
                        # essential for token streams from local AI runtimes.
                        reader = getattr(response, "read1", response.read)
                        chunk = reader(8 * 1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        bytes_forwarded += len(chunk)
            if self.command == "POST":
                self._audit(
                    "write_forwarded", response.status, role,
                    elapsedMs=round((time.monotonic() - started) * 1000),
                    bytesForwarded=bytes_forwarded,
                    streaming=ai_request,
                )
        except (OSError, http.client.HTTPException) as exc:
            event = "upstream_stream_aborted" if response_started else "upstream_error"
            self._audit(
                event, 502, role,
                errorType=type(exc).__name__,
                upstreamStatus=upstream_status or None,
                responseStarted=response_started,
                elapsedMs=round((time.monotonic() - started) * 1000),
                bytesForwarded=bytes_forwarded,
                streaming=ai_request,
            )
            # Once response headers reached the browser a second HTTP status
            # would become visible body text. Close the stream instead.
            if not response_started and not self.wfile.closed:
                try:
                    self._json(502, {"error": "ST backend unavailable"})
                except (OSError, ValueError):
                    pass
        finally:
            if conn is not None:
                try:
                    conn.close()
                except OSError:
                    pass

    def _handle(self) -> None:
        path = urlsplit(self.path).path
        if path == "/gateway/health" and self.command in {"GET", "HEAD"}:
            self._gateway_health()
            return
        if not self._host_allowed():
            self._audit("host_rejected", 421)
            self._json(421, {"error": "unrecognized Host header"})
            return
        if path == "/favicon.ico" and self.command in {"GET", "HEAD"}:
            self.send_response(204)
            self.send_header("Cache-Control", "public, max-age=86400")
            self.send_header("Content-Length", "0")
            self.send_header("Connection", "close")
            self.end_headers()
            return
        if path == "/gateway/help" and self.command in {"GET", "HEAD"}:
            self._login_help_page()
            return
        if path == "/gateway/request-access":
            if self.command in {"GET", "HEAD"}:
                self._access_request_page()
                return
            if self.command == "POST":
                if not self.server.rate_limiter.allow(  # type: ignore[attr-defined]
                    self._client_identity(), "access-request", 4
                ):
                    self._audit("access_request_rate_limited", 429)
                    self._access_request_page(
                        status=429,
                        error="申請送出過於頻繁，請稍後再試。",
                    )
                    return
                self._access_request_post()
                return
            self._json(405, {"error": "GET or POST required"})
            return
        if path == "/gateway/login":
            if self.command in {"GET", "HEAD"}:
                next_path = (parse_qs(urlsplit(self.path).query).get("next") or ["/"])[0]
                self._login_page(next_path=next_path)
                return
            if self.command == "POST":
                if not self.server.rate_limiter.allow(self._client_identity(), "login", 10):  # type: ignore[attr-defined]
                    self._audit("login_rate_limited", 429)
                    self._login_page(status=429, error="登入嘗試過多，請稍後再試。")
                    return
                self._login_post()
                return
            self._json(405, {"error": "GET or POST required"})
            return
        if path == "/gateway/logout" and self.command == "POST":
            self._logout()
            return
        role, auth_kind = self._auth()
        if role == "none":
            self._audit("authentication_failed", 401)
            accepts_html = "text/html" in (self.headers.get("Accept") or "").lower()
            if (
                self.command in {"GET", "HEAD"}
                and accepts_html
                and (path in STATIC_EXACT or path == "/gateway/admin")
            ):
                target = path or "/"
                if urlsplit(self.path).query:
                    target += "?" + urlsplit(self.path).query
                self._send_html(
                    303,
                    "<!doctype html><title>前往登入</title>",
                    location="/gateway/login?next=" + quote(target, safe="/?:=&%#"),
                )
            else:
                self._json(401, {"error": "authentication required"})
            return
        bucket = "write" if self.command == "POST" else "read"
        limit = self.settings.write_rate_per_minute if bucket == "write" else self.settings.read_rate_per_minute
        if not self.server.rate_limiter.allow(self._client_identity(), bucket, limit):  # type: ignore[attr-defined]
            self._audit("rate_limited", 429, role)
            self._json(429, {"error": "rate limit exceeded"})
            return
        if path in {"/gateway/admin", "/gateway/admin/action"}:
            if role != "owner":
                self._audit("access_admin_denied", 403, role)
                self._json(403, {"error": "owner role required"})
                return
            if path == "/gateway/admin" and self.command in {"GET", "HEAD"}:
                self._admin_page()
                return
            if path == "/gateway/admin/action" and self.command == "POST":
                self._admin_post(auth_kind)
                return
            self._json(405, {"error": "unsupported admin method"})
            return
        if path == "/gateway/client-log":
            if self.command != "POST":
                self._json(405, {"error": "POST required"})
                return
            if not self._origin_ok(auth_kind):
                self._audit("origin_rejected", 403, role, reason="client_trace")
                self._json(403, {"error": "same-origin browser request required"})
                return
            self._client_log(role)
            return
        if path == "/gateway/routes" and self.command in {"GET", "HEAD"}:
            self._gateway_routes(role)
            return
        if path == "/gateway/whoami" and self.command in {"GET", "HEAD"}:
            self._json(200, {"role": role, "profile": "personal-market"})
            return
        if self.command in {"GET", "HEAD"} and path == "/margin_ratio":
            action = (parse_qs(urlsplit(self.path).query).get("action") or [""])[0].lower()
            if action == "backfill":
                self._audit("route_denied", 403, role, reason="remote_backfill")
                self._json(403, {"error": "remote backfill is disabled"})
                return
        if not route_permission(self.command, path, role, self.settings):
            self._audit("route_denied", 403, role)
            self._json(403, {"error": "route is not enabled for private Web ST"})
            return
        if self.command == "POST" and not self._origin_ok(auth_kind):
            self._audit("origin_rejected", 403, role)
            self._json(403, {"error": "same-origin browser request or Bearer token required"})
            return
        self._proxy(role)

    def do_GET(self) -> None:
        self._handle()

    def do_HEAD(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_OPTIONS(self) -> None:
        # Private Web ST is intentionally same-origin; no wildcard CORS.
        self._json(405, {"error": "cross-origin requests are not enabled"})


def create_server(settings: Settings | None = None) -> PrivateWebServer:
    active = settings or Settings.load()
    return PrivateWebServer((active.listen_host, active.listen_port), Handler, active)


def main() -> None:
    settings = Settings.load()
    startup_id = settings.instance_id or uuid.uuid4().hex
    bind_started = time.monotonic()
    _startup_event(
        "bind_start",
        startupId=startup_id,
        mode=settings.mode,
        host=settings.listen_host,
        port=settings.listen_port,
    )
    try:
        server = create_server(settings)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 10048 or exc.errno == errno.EADDRINUSE:
            _startup_event(
                "bind_failed",
                startupId=startup_id,
                mode=settings.mode,
                host=settings.listen_host,
                port=settings.listen_port,
                winerror=getattr(exc, "winerror", None),
                errno=exc.errno,
                elapsedMs=round((time.monotonic() - bind_started) * 1000),
                tcp=_tcp_port_snapshot(settings.listen_port),
            )
            print(
                f"[FAIL] {settings.listen_host}:{settings.listen_port} is already in use. "
                "If Private Web ST is already open, use that instance; run "
                "STOP_PRIVATE_WEB.cmd before switching modes.",
                file=sys.stderr,
            )
            raise SystemExit(3) from None
        raise
    _startup_event(
        "bind_success",
        startupId=startup_id,
        mode=settings.mode,
        host=settings.listen_host,
        port=settings.listen_port,
        pid=os.getpid(),
        elapsedMs=round((time.monotonic() - bind_started) * 1000),
    )
    pid_value = os.environ.get(
        "ST_WEB_PID_PATH",
        str(ROOT / "data" / "private_web_gateway.pid"),
    )
    pid_path = Path(pid_value)
    if not pid_path.is_absolute():
        pid_path = ROOT / pid_path
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()) + "\n", encoding="ascii")
    print(
        f"Private Web ST gateway: http://{settings.listen_host}:{settings.listen_port}/\n"
        f"Upstream ST: http://{settings.upstream_host}:{settings.upstream_port}\n"
        "Profile: personal-market (access review enabled; trading and credential routes disabled)"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        pid_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
