# -*- coding: utf-8 -*-
"""ST heartbeat + graceful degradation (fail-safe) for WaveDeck."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from . import audit
from .state import RUNTIME, now_iso
from .st_push import push_async

ST_URL = os.environ.get("ST_URL", "http://127.0.0.1:18432").rstrip("/")
PING_SEC = float(os.environ.get("WD_ST_HEARTBEAT_SEC", "5"))
# Overlay older than this without bridge update → fail-safe
OVERLAY_STALE_SEC = float(os.environ.get("WD_ST_OVERLAY_STALE_SEC", "90"))
# Consecutive ping failures before fail-safe
FAIL_AFTER = int(os.environ.get("WD_ST_FAIL_AFTER", "2"))

_stop = threading.Event()
_thread: Optional[threading.Thread] = None
_fail_count = 0
_lock = threading.Lock()


def _default_link() -> dict[str, Any]:
    return {
        "status": "unknown",  # ok | warn | down
        "last_ok_at": None,
        "last_ping_at": None,
        "fail_count": 0,
        "overlay_at": None,
        "fail_safe": False,
        "fail_safe_reason": "",
        "st_port": ST_URL,
    }


def touch_overlay() -> None:
    """Call when POST /bridge/st succeeds."""
    link = dict(RUNTIME.snapshot().get("st_link") or _default_link())
    link["overlay_at"] = now_iso()
    link["overlay_epoch"] = time.time()
    link["status"] = "ok"
    link["fail_safe"] = False
    link["fail_safe_reason"] = ""
    # clear fail_safe flag on overlay when ST resumes commanding
    ov = dict(RUNTIME.snapshot().get("st_overlay") or {})
    if ov.get("fail_safe"):
        ov["fail_safe"] = False
        ov["fail_safe_reason"] = None
        RUNTIME.patch(st_link=link, st_overlay=ov, lights={"st_bridge": "ok", "risk_watchdog": "ok"})
    else:
        RUNTIME.patch(st_link=link, lights={"st_bridge": "ok"})


def _ping_st() -> bool:
    try:
        req = urllib.request.Request(ST_URL + "/health", method="GET")
        with urllib.request.urlopen(req, timeout=1.2) as resp:
            raw = resp.read().decode("utf-8", "replace")
        j = json.loads(raw)
        return bool(j.get("status") == "ok" or j.get("ok") is True)
    except Exception:
        return False


def _overlay_age_sec(link: dict[str, Any]) -> Optional[float]:
    ep = link.get("overlay_epoch")
    if ep is None:
        return None
    try:
        return max(0.0, time.time() - float(ep))
    except Exception:
        return None


def apply_fail_safe(reason: str) -> dict[str, Any]:
    """Conservative style + delever + tighten invalidation toward market."""
    st = RUNTIME.snapshot()
    link = dict(st.get("st_link") or _default_link())
    if link.get("fail_safe") and link.get("fail_safe_reason") == reason:
        # already in this fail-safe — avoid spam
        return st

    ai = dict(st.get("ai") or {})
    price = float((st.get("exec") or {}).get("price") or 0)
    inv = dict(ai.get("invalidation") or {})
    side = str(inv.get("side") or "below")
    try:
        inv_price = float(inv.get("price")) if inv.get("price") is not None else None
    except Exception:
        inv_price = None
    if price > 0 and inv_price is not None:
        if side == "below" and inv_price < price:
            # Long stop: raise toward price (tighter trailing)
            inv["price"] = round(inv_price + (price - inv_price) * 0.40, 0)
        elif side == "above" and inv_price > price:
            inv["price"] = round(inv_price - (inv_price - price) * 0.40, 0)
    ai["invalidation"] = inv
    prev_sum = str(ai.get("summary") or "")
    if "Fail-safe" not in prev_sum:
        ai["summary"] = f"〔Fail-safe：{reason}〕風格→保守、降載、收緊失效。 " + prev_sum[:500]

    link.update(
        {
            "status": "down" if "心跳" in reason or "斷線" in reason else "warn",
            "fail_safe": True,
            "fail_safe_reason": reason,
        }
    )
    ov = dict(st.get("st_overlay") or {})
    ov.update(
        {
            "aggressiveness": 35,
            "delever": True,
            "note": f"Fail-safe · {reason}",
            "fail_safe": True,
            "fail_safe_reason": reason,
        }
    )
    snap = RUNTIME.patch(
        style=35,
        ai=ai,
        st_overlay=ov,
        st_link=link,
        lights={"st_bridge": "warn", "risk_watchdog": "warn"},
    )
    audit.write("fail_safe", {"reason": reason})
    push_async(snap, reason="fail_safe", force=True)
    return snap


def _tick() -> None:
    global _fail_count
    ok = _ping_st()
    link = dict(RUNTIME.snapshot().get("st_link") or _default_link())
    link["last_ping_at"] = now_iso()
    with _lock:
        if ok:
            _fail_count = 0
            link["fail_count"] = 0
            link["last_ok_at"] = now_iso()
            if not link.get("fail_safe"):
                link["status"] = "ok"
            RUNTIME.patch(st_link=link, lights={"st_bridge": "ok" if not link.get("fail_safe") else "warn"})
        else:
            _fail_count += 1
            link["fail_count"] = _fail_count
            link["status"] = "down" if _fail_count >= FAIL_AFTER else "warn"
            RUNTIME.patch(st_link=link, lights={"st_bridge": "warn" if _fail_count < FAIL_AFTER else "bad"})

    # Fail-safe triggers
    if not ok and _fail_count >= FAIL_AFTER:
        apply_fail_safe("ST 心跳中斷")
        return
    age = _overlay_age_sec(link)
    # Only stale-check after we've received at least one overlay
    if age is not None and age > OVERLAY_STALE_SEC and not link.get("fail_safe"):
        apply_fail_safe(f"宏觀覆寫過期 {int(age)}s")


def _loop() -> None:
    # seed link struct
    if not RUNTIME.snapshot().get("st_link"):
        RUNTIME.patch(st_link=_default_link())
    while not _stop.wait(PING_SEC):
        try:
            _tick()
        except Exception as exc:
            try:
                import sys

                sys.stderr.write(f"[wavedeck] st_link tick: {exc}\n")
            except Exception:
                pass


def start() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="wd-st-heartbeat", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()


def snapshot_link() -> dict[str, Any]:
    return dict(RUNTIME.snapshot().get("st_link") or _default_link())
