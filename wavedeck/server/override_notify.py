# -*- coding: utf-8 -*-
"""Notify Stock Terminal Override Alpha log after macro overlays."""
from __future__ import annotations

import json
import os
import threading
import urllib.request
from typing import Any

from .state import RUNTIME

ST_URL = os.environ.get("ST_URL", "http://127.0.0.1:18432").rstrip("/")


def notify_async(bridge_body: dict[str, Any], snap: dict[str, Any] | None = None) -> None:
    threading.Thread(
        target=_notify,
        args=(bridge_body, snap or RUNTIME.snapshot()),
        daemon=True,
        name="wd-override-alpha",
    ).start()


def _notify(bridge_body: dict[str, Any], snap: dict[str, Any]) -> None:
    meta = bridge_body.get("meta") if isinstance(bridge_body.get("meta"), dict) else {}
    acct = snap.get("account") or {}
    payload = {
        "style": bridge_body.get("style") if bridge_body.get("style") is not None else snap.get("style"),
        "delever": bool(bridge_body.get("delever") or (snap.get("st_overlay") or {}).get("delever")),
        "score": meta.get("score"),
        "advRatio": meta.get("advRatio"),
        "spillover_prob": meta.get("spillover_prob"),
        "rotation": meta.get("rotation"),
        "hot_stage": meta.get("hot_stage"),
        "twii": meta.get("twii"),
        "note": bridge_body.get("note"),
        "source": meta.get("source") or "bridge/st",
        "wd_equity": acct.get("equity"),
        "wd_equity_chg": acct.get("equity_change") or acct.get("day_pnl"),
        "wd_fsm": snap.get("fsm"),
        "wd_style": snap.get("style"),
        "meta": meta,
    }
    # Only log meaningful risk-off / style shifts (keep table lean)
    style = payload.get("style")
    try:
        style_i = int(style) if style is not None else None
    except Exception:
        style_i = None
    if not payload["delever"] and (style_i is None or style_i >= 45):
        return
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        ST_URL + "/api/override-alpha",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            resp.read()
    except Exception:
        pass
