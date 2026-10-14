# -*- coding: utf-8 -*-
"""WaveDeck 控制面的請求防護：Host 白名單、Origin 判定與 CORS 回應來源。

威脅：WaveDeck 綁 127.0.0.1，但瀏覽器中的任何網頁都能對它發請求（CORS 簡單請求不需預檢，
DNS 重綁定還能讓攻擊者網域指向 127.0.0.1）。控制端點包含切換實盤、解除急停、送單訊號，
因此不能只靠「只綁本機」。這裡只做判定，不碰 HTTP；伺服器負責回應。
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]")

# Stock Terminal 的瀏覽器畫面跨來源呼叫 WaveDeck 的唯一合法用途：
# 讀取狀態、探測 /health，以及把巨集覆寫推送到 /bridge/st。其他控制端點一律不開放給 ST 來源。
ST_READ_PATHS = frozenset({"/health", "/api/state"})
ST_WRITE_PATHS = frozenset({"/bridge/st"})
# 電視警報走公開隧道：不檢查 Host／Origin，改由共享密鑰把關。
WEBHOOK_PREFIX = "/webhook"


def loopback_origins(port: int) -> frozenset[str]:
    return frozenset(f"http://{host}:{port}" for host in LOOPBACK_HOSTS)


def st_origins(st_url: str) -> frozenset[str]:
    """由 ST_URL 的埠推導 ST 畫面的來源（127.0.0.1 與 localhost 兩種寫法）。"""
    try:
        port = urlsplit(st_url).port
    except ValueError:
        port = None
    return loopback_origins(port) if port else frozenset()


def extra_hosts() -> frozenset[str]:
    """明示加入的主機名稱（例如區網名稱）；預設只有本機。"""
    raw = os.environ.get("WAVEDECK_ALLOWED_HOSTS", "")
    return frozenset(item.strip().lower() for item in raw.split(",") if item.strip())


def host_allowed(host_header: str | None, server_port: int, allowed: frozenset[str] = frozenset()) -> bool:
    value = (host_header or "").strip().lower()
    if not value:
        return False
    try:
        parts = urlsplit("//" + value)
        hostname, port = parts.hostname or "", parts.port
    except ValueError:
        return False
    if port is not None and port != server_port:
        return False
    bracketed = f"[{hostname}]" if ":" in hostname else hostname
    return bracketed in LOOPBACK_HOSTS or hostname in allowed


def request_origin(origin_header: str | None, referer_header: str | None, *, method: str = "POST") -> str | None:
    """瀏覽器的跨來源請求會帶 Origin。寫入（POST）在沒有 Origin 時退回 Referer 的來源；
    GET／OPTIONS 不看 Referer：使用者從別的網頁或 ST 按鈕開啟 WaveDeck 畫面是無害的導覽。
    都沒有則回 None（命令列、PowerShell、伺服器對伺服器）。"""
    origin = (origin_header or "").strip()
    if origin:
        return origin.lower()
    if method != "POST":
        return None
    referer = (referer_header or "").strip()
    if not referer:
        return None
    try:
        parts = urlsplit(referer)
    except ValueError:
        return "invalid"
    if not parts.scheme or not parts.netloc:
        return "invalid"
    return f"{parts.scheme}://{parts.netloc}".lower()


def check_request(*, method: str, path: str, host: str | None, origin: str | None, sec_fetch_site: str | None,
                  server_port: int, st_allowed: frozenset[str], allowed_hosts: frozenset[str] = frozenset()) -> tuple[bool, str]:
    """回傳 (放行, 拒絕原因)。method 為 GET／POST／OPTIONS。"""
    if path.startswith(WEBHOOK_PREFIX):
        return True, ""
    if not host_allowed(host, server_port, allowed_hosts):
        return False, "主機名稱不在允許清單；WaveDeck 只接受本機位址"
    if origin is None:
        # 沒有 Origin：命令列、PowerShell、伺服器對伺服器。瀏覽器的跨站寫入一定帶 Origin，
        # 但再用 Sec-Fetch-Site 補一道，避免省略 Origin 的跨站請求。
        if method == "POST" and (sec_fetch_site or "").lower() == "cross-site":
            return False, "跨站請求被拒絕"
        return True, ""
    # 明示允許的主機（例如區網名稱）上的控制臺，其來源同樣是「自己」。
    own = loopback_origins(server_port) | frozenset(f"http://{name}:{server_port}" for name in allowed_hosts)
    if origin in own:
        return True, ""
    if origin in st_allowed:
        if method == "GET" and path in ST_READ_PATHS:
            return True, ""
        if method == "POST" and path in ST_WRITE_PATHS:
            return True, ""
        if method == "OPTIONS" and (path in ST_READ_PATHS or path in ST_WRITE_PATHS):
            return True, ""
        return False, "Stock Terminal 畫面只可讀取狀態或推送巨集覆寫，不可操作控制端點"
    return False, "設定與控制操作須由本機控制臺發起"


def cors_origin(origin: str | None, st_allowed: frozenset[str]) -> str | None:
    """只有已知的 ST 畫面來源才回 Access-Control-Allow-Origin；永不使用 *。"""
    return origin if origin and origin in st_allowed else None
