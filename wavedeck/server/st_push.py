# -*- coding: utf-8 -*-
"""Async WD → ST reverse bus push (state-machine / overlay changes)."""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from .state import RUNTIME

ST_URL = os.environ.get("ST_URL", "http://127.0.0.1:18432").rstrip("/")
_push_lock = threading.Lock()
_last_sig = ""


def _signature(snap: dict[str, Any]) -> str:
    ai = snap.get("ai") or {}
    pos = snap.get("positions") or {}
    ov = snap.get("st_overlay") or {}
    return "|".join(
        [
            str(snap.get("fsm")),
            str(snap.get("mode")),
            str(snap.get("style")),
            str(snap.get("kill_switch")),
            str(ai.get("action")),
            str(ai.get("invalidation")),
            str(pos.get("account")),
            str(ov.get("delever")),
            str(ov.get("spillover_prob")),
            str(ov.get("fail_safe")),
        ]
    )


def _chip_from_snap(s: dict[str, Any]) -> dict[str, Any]:
    """Lightweight POSITION_STATE chip (aligned with ST wavedeck_bus.chip_from_report)."""
    ai = s.get("ai") or {}
    pos = s.get("positions") or {}
    inv = ai.get("invalidation") if isinstance(ai.get("invalidation"), dict) else {}
    ov = s.get("st_overlay") or {}
    qty_raw = pos.get("account")
    if qty_raw is None:
        qty_raw = pos.get("txt_target")
    try:
        qty_i = int(qty_raw) if qty_raw is not None else 0
    except Exception:
        qty_i = 0
    if qty_i > 0:
        direction = "LONG"
    elif qty_i < 0:
        direction = "SHORT"
    else:
        direction = "EMPTY"
    sym = str(s.get("symbol") or "TXF").upper().replace(".TW", "").replace(".TWO", "")
    mode = str(s.get("mode") or "paper").lower()
    try:
        inv_px = float(inv["price"]) if inv.get("price") is not None else None
    except Exception:
        inv_px = None
    try:
        conf = float(ai["confidence"]) if ai.get("confidence") is not None else None
    except Exception:
        conf = None
    market = "TW" if sym in {"TXF", "TX", "TWII", "^TWII", "MXF"} or (sym.isdigit() and len(sym) <= 6) else "US"
    return {
        "symbol": sym,
        "market": market,
        "direction": direction,
        "position_size": abs(qty_i),
        "invalidation_price": inv_px,
        "invalidation_side": str(inv.get("side") or "below")[:12],
        "wd_mode": "REAL" if mode == "live" else "PAPER",
        "ai_confidence": conf,
        "action": ai.get("action"),
        "action_label": ai.get("action_label"),
        "fsm": s.get("fsm"),
        "style": s.get("style"),
        "fail_safe": bool(ov.get("fail_safe")),
        "spillover_prob": ov.get("spillover_prob"),
        "macro_style": ov.get("aggressiveness"),
        "rotation": ov.get("rotation"),
        "hot_stage": ov.get("hot_stage"),
    }


def build_report(snap: Optional[dict[str, Any]] = None, reason: str = "") -> dict[str, Any]:
    s = snap or RUNTIME.snapshot()
    ai = s.get("ai") or {}
    chip = _chip_from_snap(s)
    return {
        "fsm": s.get("fsm"),
        "mode": s.get("mode"),
        "style": s.get("style"),
        "symbol": s.get("symbol"),
        "kill_switch": bool(s.get("kill_switch")),
        "ai": {
            "action": ai.get("action"),
            "action_label": ai.get("action_label"),
            "confidence": ai.get("confidence"),
            "provider": ai.get("provider"),
            "invalidation": ai.get("invalidation"),
        },
        "positions": s.get("positions") or {},
        "costs": s.get("costs") or {},
        "account": s.get("account") or {},
        "st_overlay": s.get("st_overlay") or {},
        "st_link": s.get("st_link") or {},
        "chip": chip,
        "source": "wavedeck-push",
        "push_reason": str(reason or "state")[:64],
        "event_type": "POSITION_STATE_CHANGE",
        "timestamp": int(time.time()),
    }


def push_to_st(
    snap: Optional[dict[str, Any]] = None,
    reason: str = "",
    *,
    force: bool = False,
) -> bool:
    """POST /bridge/wavedeck. Dedupes identical signatures unless force."""
    global _last_sig
    s = snap or RUNTIME.snapshot()
    sig = _signature(s)
    with _push_lock:
        if not force and sig == _last_sig:
            return False
        _last_sig = sig
    body = json.dumps(build_report(s, reason), ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        ST_URL + "/bridge/wavedeck",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            resp.read()
        return True
    except Exception:
        return False


def push_async(snap: Optional[dict[str, Any]] = None, reason: str = "", force: bool = False) -> None:
    threading.Thread(
        target=push_to_st,
        kwargs={"snap": snap, "reason": reason, "force": force},
        daemon=True,
        name="wd-st-push",
    ).start()
