# -*- coding: utf-8 -*-
"""Orchestrate signal → decision → risk gate → broker → state transition."""
from __future__ import annotations

from typing import Any

from . import audit
from .broker import ensure_master_seeds, get_broker
from .config import load_config, set_broker_kind, set_mode, set_provider
from .providers import infer_with_fallback
from .risk import evaluate_gate
from .state import RUNTIME, now_iso


def apply_st_bridge(body: dict[str, Any]) -> dict[str, Any]:
    """Stock Terminal macro overlay (style / delever / rotation / spillover)."""
    style = body.get("style")
    delever = bool(body.get("delever"))
    note = str(body.get("note") or "")
    meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
    rotation = meta.get("rotation") or body.get("rotation")
    leaders = meta.get("leaders") if isinstance(meta.get("leaders"), list) else body.get("leaders")
    spill = meta.get("spillover_prob")
    if spill is None:
        spill = body.get("spillover_prob")
    try:
        spill_f = float(spill) if spill is not None else None
    except Exception:
        spill_f = None
    if spill_f is not None:
        spill_f = max(0.0, min(1.0, spill_f))
        # 外溢機率過低：市場動能不易擴散 → 強制／加強降載訊號
        if spill_f < 0.30:
            delever = True
            if "外溢低" not in note:
                note = (note + " · 外溢低").strip(" ·")

    overlay: dict[str, Any] = {
        "aggressiveness": style,
        "delever": delever,
        "note": note[:400],
        "rotation": str(rotation) if rotation else None,
        "spillover_prob": spill_f,
        "leaders": [str(x)[:40] for x in (leaders or [])[:6]],
        "source": str(meta.get("source") or body.get("source") or "st-macro")[:64],
        "score": meta.get("score"),
        "advRatio": meta.get("advRatio"),
    }
    patch: dict[str, Any] = {
        "st_overlay": overlay,
        "lights": {"st_bridge": "ok"},
    }
    if style is not None:
        try:
            patch["style"] = max(1, min(99, int(style)))
        except Exception:
            pass
    snap = RUNTIME.patch(**patch)
    audit.write("st_bridge", body)
    return snap


def set_decision_provider(name: str) -> dict[str, Any]:
    cfg = set_provider(name)
    snap = RUNTIME.patch(
        costs={"provider": cfg["provider"]},
        lights={"openai_or_local": "ok"},
    )
    audit.write("provider", {"provider": cfg["provider"]})
    return {"ok": True, "provider": cfg["provider"], "state": snap}


def set_exec_mode(mode: str) -> dict[str, Any]:
    cfg = set_mode(mode)
    if cfg["mode"] == "live":
        ensure_master_seeds(str(RUNTIME.snapshot().get("symbol") or "TXF"))
    snap = RUNTIME.patch(
        mode=cfg["mode"],
        account={"broker_api": cfg["broker"]["kind"]},
        lights={
            "broker_api": "ok",
            "order_signal_file": "ok" if cfg["broker"]["kind"] == "txt_master" else "idle",
        },
    )
    audit.write("mode", {"mode": cfg["mode"], "broker": cfg["broker"]["kind"]})
    return {"ok": True, "mode": cfg["mode"], "broker": cfg["broker"]["kind"], "state": snap}


def set_broker(kind: str) -> dict[str, Any]:
    cfg = set_broker_kind(kind)
    if cfg["broker"]["kind"] == "txt_master":
        ensure_master_seeds(str(RUNTIME.snapshot().get("symbol") or "TXF"))
    snap = RUNTIME.patch(
        account={"broker_api": cfg["broker"]["kind"]},
        lights={"broker_api": "ok", "order_signal_file": "ok"},
    )
    audit.write("broker", {"kind": cfg["broker"]["kind"]})
    return {"ok": True, "broker": cfg["broker"]["kind"], "state": snap}


def sync_broker_positions() -> dict[str, Any]:
    broker = get_broker()
    st = RUNTIME.snapshot()
    result = broker.sync_positions(st)
    patch: dict[str, Any] = {"positions": result.get("positions") or st.get("positions")}
    if result.get("lights"):
        patch["lights"] = result["lights"]
    if result.get("account"):
        patch["account"] = result["account"]
    snap = RUNTIME.patch(**patch)
    audit.write("broker_sync", {"broker": broker.name, "meta": result.get("broker_meta")})
    return {"ok": True, "broker": broker.name, "state": snap, "meta": result.get("broker_meta")}


def get_runtime_config() -> dict[str, Any]:
    cfg = load_config()
    st = RUNTIME.snapshot()
    return {
        "ok": True,
        "config": {
            "provider": cfg.get("provider"),
            "mode": st.get("mode") or cfg.get("mode"),
            "broker": (cfg.get("broker") or {}).get("kind"),
            "ollama": cfg.get("ollama"),
            "openai": {k: v for k, v in (cfg.get("openai") or {}).items() if k != "api_key"},
            "txt_dir": (cfg.get("broker") or {}).get("txt_dir"),
        },
        "state": st,
    }


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

    cfg = load_config()
    preferred = str(
        body.get("provider")
        or (st.get("costs") or {}).get("provider")
        or cfg.get("provider")
        or "heuristic"
    )
    ctx = {
        "style": RUNTIME.snapshot().get("style"),
        "event": event,
        "positions": RUNTIME.snapshot().get("positions"),
        "price": (RUNTIME.snapshot().get("exec") or {}).get("price"),
        "source": source,
        "symbol": symbol,
        "mode": RUNTIME.snapshot().get("mode"),
    }
    decision, err = infer_with_fallback(ctx, preferred)
    if err:
        RUNTIME.patch(lights={"openai_or_local": "warn"})
    else:
        RUNTIME.patch(lights={"openai_or_local": "ok"})

    gate = evaluate_gate(RUNTIME.snapshot(), decision)
    decision["process"]["gate"] = gate["gate"]
    decision["process"]["gate_reasons"] = gate["reasons"]

    pos = dict(RUNTIME.snapshot().get("positions") or {})
    execu = dict(RUNTIME.snapshot().get("exec") or {})
    action = decision["action"]
    order_action = execu.get("last_order_action") or "—"

    if gate["allow"]:
        broker = get_broker()
        applied = broker.apply_intent(RUNTIME.snapshot(), decision, int(gate["lots_effective"]))
        pos = dict(applied.get("positions") or pos)
        order_action = str(applied.get("order_action") or order_action)
        if applied.get("lights"):
            RUNTIME.patch(lights=applied["lights"])
        if applied.get("account"):
            RUNTIME.patch(account=applied["account"])

        if action == "ENTER_LONG":
            execu["lots"] = gate["lots_effective"]
            RUNTIME.set_fsm("InPosition")
        elif action == "ENTER_SHORT":
            execu["lots"] = gate["lots_effective"]
            RUNTIME.set_fsm("InPosition")
        elif action == "HOLD":
            if int(pos.get("account") or 0) != 0:
                RUNTIME.set_fsm("InPosition")
            else:
                RUNTIME.set_fsm("Idle")
        elif action == "REDUCE":
            RUNTIME.set_fsm("Reducing")
        elif action == "EXIT":
            RUNTIME.set_fsm("Flat")
        execu["last_order_action"] = order_action
    else:
        execu["last_ai_action"] = decision["action_label"] + "（閘門擋下）"
        if RUNTIME.snapshot().get("fsm") == "Arming":
            RUNTIME.set_fsm("Idle")

    execu["last_ai_action"] = decision["action_label"]
    # Persist preferred provider used (may be fallback heuristic)
    used = decision.get("provider") or preferred
    if used != preferred and preferred != "heuristic":
        # keep config preference; only reflect actual route in costs.session note via provider field
        pass
    snap = RUNTIME.patch(
        ai=decision,
        positions=pos,
        exec=execu,
        costs={"provider": used},
        transport={
            "last_webhook_status": "AI 完成" if gate["allow"] else "閘門阻擋",
        },
    )
    audit.write(
        "decision",
        {
            "source": source,
            "event": event,
            "decision": decision,
            "gate": gate,
            "provider_error": err,
            "broker": get_broker().name,
        },
    )
    return {
        "ok": True,
        "decision": decision,
        "gate": gate,
        "provider_error": err,
        "state": snap,
    }


__all__ = [
    "apply_st_bridge",
    "handle_signal",
    "set_decision_provider",
    "set_exec_mode",
    "set_broker",
    "sync_broker_positions",
    "get_runtime_config",
]
