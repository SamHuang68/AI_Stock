# -*- coding: utf-8 -*-
"""Orchestrate signal → decision → risk gate → state transition."""
from __future__ import annotations

from typing import Any

from . import audit
from .decision import get_provider
from .risk import evaluate_gate
from .state import RUNTIME, now_iso


def apply_st_bridge(body: dict[str, Any]) -> dict[str, Any]:
    """Stock Terminal macro overlay."""
    style = body.get("style")
    delever = bool(body.get("delever"))
    note = str(body.get("note") or "")
    patch: dict[str, Any] = {
        "st_overlay": {
            "aggressiveness": style,
            "delever": delever,
            "note": note,
        },
        "lights": {"st_bridge": "ok"},
    }
    if style is not None:
        try:
            patch["style"] = int(style)
        except Exception:
            pass
    snap = RUNTIME.patch(**patch)
    audit.write("st_bridge", body)
    return snap


def handle_signal(body: dict[str, Any]) -> dict[str, Any]:
    st = RUNTIME.snapshot()
    event = str(body.get("event") or "MANUAL_REVIEW")
    source = str(body.get("source") or "manual")
    symbol = str(body.get("symbol") or st.get("symbol") or "TXF")

    if st.get("kill_switch"):
        audit.write("signal_blocked", {"reason": "kill_switch", "body": body})
        return {
            "ok": False,
            "blocked": True,
            "reason": "Kill Switch",
            "state": st,
        }

    RUNTIME.patch(
        symbol=symbol,
        transport={
            "last_tv_event": f"{event} · {now_iso()}",
            "last_webhook_status": "處理中",
        },
        lights={"webhook": "ok"},
    )
    if st.get("fsm") in ("Idle", "Flat"):
        RUNTIME.set_fsm("Arming")

    provider = get_provider((st.get("costs") or {}).get("provider"))
    ctx = {
        "style": RUNTIME.snapshot().get("style"),
        "event": event,
        "positions": RUNTIME.snapshot().get("positions"),
        "price": (RUNTIME.snapshot().get("exec") or {}).get("price"),
        "source": source,
    }
    decision = provider.infer(ctx)
    gate = evaluate_gate(RUNTIME.snapshot(), decision)
    decision["process"]["gate"] = gate["gate"]
    decision["process"]["gate_reasons"] = gate["reasons"]

    # Position / exec updates (paper semantics)
    pos = dict(RUNTIME.snapshot().get("positions") or {})
    execu = dict(RUNTIME.snapshot().get("exec") or {})
    action = decision["action"]
    if gate["allow"]:
        if action == "ENTER_LONG":
            pos["ai_suggested"] = max(1, gate["lots_effective"])
            pos["txt_target"] = pos["ai_suggested"]
            execu["last_order_action"] = "多單進場"
            execu["lots"] = gate["lots_effective"]
            RUNTIME.set_fsm("InPosition")
        elif action == "HOLD":
            execu["last_ai_action"] = decision["action_label"]
            if int(pos.get("account") or 0) > 0:
                RUNTIME.set_fsm("InPosition")
            else:
                RUNTIME.set_fsm("Idle")
        elif action == "REDUCE":
            pos["ai_suggested"] = 0
            pos["txt_target"] = 0
            execu["last_order_action"] = "減碼／平倉"
            RUNTIME.set_fsm("Reducing")
        elif action == "EXIT":
            pos["ai_suggested"] = 0
            pos["txt_target"] = 0
            pos["strategy"] = 0
            pos["account"] = 0
            execu["last_order_action"] = "全部平倉"
            RUNTIME.set_fsm("Flat")
    else:
        execu["last_ai_action"] = decision["action_label"] + "（閘門擋下）"
        if RUNTIME.snapshot().get("fsm") == "Arming":
            RUNTIME.set_fsm("Idle")

    execu["last_ai_action"] = decision["action_label"]
    snap = RUNTIME.patch(
        ai=decision,
        positions=pos,
        exec=execu,
        costs={"provider": provider.name},
        transport={
            "last_webhook_status": "AI 完成" if gate["allow"] else "閘門阻擋",
        },
    )
    audit.write(
        "decision",
        {"source": source, "event": event, "decision": decision, "gate": gate},
    )
    return {"ok": True, "decision": decision, "gate": gate, "state": snap}
