# -*- coding: utf-8 -*-
"""ST heartbeat + graceful degradation (fail-safe) for WaveDeck.

Root cause (fixed): fail-safe used to set style=35 once, then any later
`/api/style` or bridge noise could raise style back (e.g. 60) while the
Fail-safe banner stayed — looking like 「降載失效」. While fail-safe is
active we now RE-ENFORCE style/delever/lights every heartbeat tick.
"""
from __future__ import annotations

import json
import os
import threading
import time
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
FAIL_SAFE_STYLE = int(os.environ.get("WD_FAIL_SAFE_STYLE", "35"))

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
        "fail_safe_kind": "",  # stale_overlay | heartbeat
        "st_port": ST_URL,
    }


def _kind_of(reason: str) -> str:
    r = str(reason or "")
    if "心跳" in r or "斷線" in r:
        return "heartbeat"
    if "過期" in r or "覆寫" in r:
        return "stale_overlay"
    return "other"


def touch_overlay() -> None:
    """Call when POST /bridge/st succeeds — ST resumed commanding; clear fail-safe."""
    link = dict(RUNTIME.snapshot().get("st_link") or _default_link())
    link["overlay_at"] = now_iso()
    link["overlay_epoch"] = time.time()
    link["status"] = "ok"
    link["fail_safe"] = False
    link["fail_safe_reason"] = ""
    link["fail_safe_kind"] = ""
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


def _tighten_invalidation(ai: dict[str, Any], price: float) -> dict[str, Any]:
    inv = dict(ai.get("invalidation") or {})
    side = str(inv.get("side") or "below")
    try:
        inv_price = float(inv.get("price")) if inv.get("price") is not None else None
    except Exception:
        inv_price = None
    if price > 0 and inv_price is not None:
        if side == "below" and inv_price < price:
            inv["price"] = round(inv_price + (price - inv_price) * 0.40, 0)
        elif side == "above" and inv_price > price:
            inv["price"] = round(inv_price - (inv_price - price) * 0.40, 0)
    ai["invalidation"] = inv
    return ai


def _write_inv_txt(ai: dict[str, Any], symbol: str = "TXF") -> None:
    """Soft-sync invalidation for 下單大師 side-file (non-fatal)."""
    try:
        from .broker import write_invalidation_txt

        inv = ai.get("invalidation") if isinstance(ai.get("invalidation"), dict) else {}
        if inv.get("price") is not None:
            write_invalidation_txt(
                float(inv["price"]),
                str(inv.get("side") or "below"),
                symbol=symbol,
            )
    except Exception:
        pass


def enforce_fail_safe(reason: str | None = None, *, tighten: bool = False) -> dict[str, Any]:
    """Keep fail-safe sticky: style cap + delever + warn lamps (every tick)."""
    st = RUNTIME.snapshot()
    link = dict(st.get("st_link") or _default_link())
    ov = dict(st.get("st_overlay") or {})
    reason = str(reason or link.get("fail_safe_reason") or ov.get("fail_safe_reason") or "Fail-safe")
    kind = _kind_of(reason)
    ai = dict(st.get("ai") or {})
    price = float((st.get("exec") or {}).get("price") or 0)
    if tighten:
        ai = _tighten_invalidation(ai, price)
    prev_sum = str(ai.get("summary") or "")
    banner = f"〔Fail-safe：{reason}〕風格→保守、降載、收緊失效。"
    if "Fail-safe" not in prev_sum:
        ai["summary"] = banner + " " + prev_sum[:500]
    else:
        # Refresh age/reason text in summary without stacking duplicates
        if prev_sum.startswith("〔Fail-safe"):
            rest = prev_sum.split("〕", 1)
            tail = rest[1] if len(rest) > 1 else ""
            # strip leading "風格→…" clause if present
            ai["summary"] = banner + (tail if tail.startswith(" ") else (" " + tail.lstrip()[:500]))

    link.update(
        {
            "status": "down" if kind == "heartbeat" else "warn",
            "fail_safe": True,
            "fail_safe_reason": reason,
            "fail_safe_kind": kind,
        }
    )
    ov.update(
        {
            "aggressiveness": FAIL_SAFE_STYLE,
            "delever": True,
            "note": f"Fail-safe · {reason}",
            "fail_safe": True,
            "fail_safe_reason": reason,
        }
    )
    try:
        cur_style = int(st.get("style") or 50)
    except Exception:
        cur_style = 50
    style = min(cur_style, FAIL_SAFE_STYLE)

    snap = RUNTIME.patch(
        style=style,
        ai=ai,
        st_overlay=ov,
        st_link=link,
        lights={"st_bridge": "warn" if kind != "heartbeat" else "bad", "risk_watchdog": "warn"},
    )
    _write_inv_txt(ai, str(st.get("symbol") or "TXF"))
    return snap


def apply_fail_safe(reason: str) -> dict[str, Any]:
    """Enter or refresh fail-safe (tighten invalidation on first entry / kind change)."""
    st = RUNTIME.snapshot()
    link = dict(st.get("st_link") or _default_link())
    kind = _kind_of(reason)
    already = bool(link.get("fail_safe") or (st.get("st_overlay") or {}).get("fail_safe"))
    same_kind = str(link.get("fail_safe_kind") or "") == kind
    # First entry or kind change → tighten stop once; every call re-enforces caps
    snap = enforce_fail_safe(reason, tighten=(not already or not same_kind))
    if not already:
        audit.write("fail_safe", {"reason": reason, "kind": kind})
        push_async(snap, reason="fail_safe", force=True)
    elif not same_kind:
        audit.write("fail_safe", {"reason": reason, "kind": kind, "upgrade": True})
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
            # Never paint st_bridge green while fail-safe is sticky
            lamp = "warn" if link.get("fail_safe") else "ok"
            RUNTIME.patch(st_link=link, lights={"st_bridge": lamp})
        else:
            _fail_count += 1
            link["fail_count"] = _fail_count
            link["status"] = "down" if _fail_count >= FAIL_AFTER else "warn"
            RUNTIME.patch(
                st_link=link,
                lights={"st_bridge": "warn" if _fail_count < FAIL_AFTER else "bad"},
            )

    # Fail-safe triggers
    if not ok and _fail_count >= FAIL_AFTER:
        apply_fail_safe("ST 心跳中斷")
        return

    # Refresh link after ping patch
    link = dict(RUNTIME.snapshot().get("st_link") or _default_link())
    age = _overlay_age_sec(link)
    if age is not None and age > OVERLAY_STALE_SEC:
        apply_fail_safe(f"宏觀覆寫過期 {int(age)}s")
        return

    # Sticky re-enforce every tick while flagged (style drift / lamp green / delever cleared)
    if fail_safe_active():
        enforce_fail_safe(tighten=False)


def _loop() -> None:
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


def fail_safe_active(state: dict[str, Any] | None = None) -> bool:
    st = state or RUNTIME.snapshot()
    return bool((st.get("st_link") or {}).get("fail_safe") or (st.get("st_overlay") or {}).get("fail_safe"))
