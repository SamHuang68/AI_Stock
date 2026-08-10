# -*- coding: utf-8 -*-
"""Orchestrate signal → decision → risk gate → broker → state transition."""
from __future__ import annotations

from typing import Any

from . import audit
from .broker import ensure_master_seeds, get_broker
from .config import load_config, set_broker_kind, set_mode, set_provider
from .override_notify import notify_async as notify_override_alpha
from .providers import infer_with_fallback
from .risk import evaluate_gate
from .state import RUNTIME, now_iso
from .st_link import touch_overlay
from .st_push import push_async


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

    hot_stage = meta.get("hot_stage") or body.get("hot_stage")
    overlay: dict[str, Any] = {
        "aggressiveness": style,
        "delever": delever,
        "note": note[:400],
        "rotation": str(rotation) if rotation else None,
        "spillover_prob": spill_f,
        "leaders": [str(x)[:40] for x in (leaders or [])[:6]],
        "hot_stage": str(hot_stage)[:80] if hot_stage else None,
        "chain_breadth": meta.get("chain_breadth"),
        "chain_contig": meta.get("chain_contig"),
        "source": str(meta.get("source") or body.get("source") or "st-macro")[:64],
        "score": meta.get("score"),
        "advRatio": meta.get("advRatio"),
        "fail_safe": False,
        "fail_safe_reason": None,
    }
    patch: dict[str, Any] = {
        "st_overlay": overlay,
        "lights": {"st_bridge": "ok", "risk_watchdog": "ok"},
    }
    if style is not None:
        try:
            patch["style"] = max(1, min(99, int(style)))
        except Exception:
            pass
    snap = RUNTIME.patch(**patch)
    try:
        touch_overlay()
        snap = RUNTIME.snapshot()
    except Exception:
        pass
    audit.write("st_bridge", body)
    try:
        notify_override_alpha(body, snap)
        push_async(snap, reason="st_bridge", force=True)
    except Exception:
        pass
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
    try:
        push_async(snap, reason="mode", force=True)
    except Exception:
        pass
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
            "exec_md": cfg.get("exec_md") or {},
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
    live = RUNTIME.snapshot()
    ov = live.get("st_overlay") or {}
    ctx = {
        "style": live.get("style"),
        "event": event,
        "positions": live.get("positions"),
        "price": (live.get("exec") or {}).get("price"),
        "source": source,
        "symbol": symbol,
        "mode": live.get("mode"),
        "st_rotation": ov.get("rotation"),
        "st_spillover_prob": ov.get("spillover_prob"),
        "st_hot_stage": ov.get("hot_stage"),
        "st_delever": bool(ov.get("delever")),
        "st_score": ov.get("score"),
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
    prev_costs = dict(RUNTIME.snapshot().get("costs") or {})
    try:
        delta = float(decision.get("cost_usd") or 0)
    except Exception:
        delta = 0.0
    local_n = int(decision.get("local_calls") or 0)
    cloud_n = int(decision.get("cloud_calls") or 0)
    cost_patch = {
        "provider": used,
        "session_usd": round(float(prev_costs.get("session_usd") or 0) + delta, 6),
        "day_usd": round(float(prev_costs.get("day_usd") or 0) + delta, 6),
        "month_usd": round(float(prev_costs.get("month_usd") or 0) + delta, 6),
        "local_calls": int(prev_costs.get("local_calls") or 0) + local_n,
        "cloud_calls": int(prev_costs.get("cloud_calls") or 0) + cloud_n,
    }
    # Preserve fail-safe tightened invalidation if new decision would loosen it
    prev_ai = RUNTIME.snapshot().get("ai") or {}
    prev_inv = prev_ai.get("invalidation") if isinstance(prev_ai.get("invalidation"), dict) else {}
    new_inv = decision.get("invalidation") if isinstance(decision.get("invalidation"), dict) else {}
    link = RUNTIME.snapshot().get("st_link") or {}
    ov = RUNTIME.snapshot().get("st_overlay") or {}
    if (link.get("fail_safe") or ov.get("fail_safe")) and prev_inv.get("price") is not None:
        try:
            side = str(prev_inv.get("side") or new_inv.get("side") or "below")
            prev_px = float(prev_inv["price"])
            new_px = float(new_inv["price"]) if new_inv.get("price") is not None else None
            keep = False
            if new_px is None:
                keep = True
            elif side == "below" and prev_px > new_px:
                keep = True  # keep tighter (higher) long stop
            elif side == "above" and prev_px < new_px:
                keep = True
            if keep:
                decision = dict(decision)
                decision["invalidation"] = dict(prev_inv)
        except Exception:
            pass

    # 狀態翻譯層：Wave AI 風格敘事＋條件寫入執行細節 MD
    fsm_before = str(st.get("fsm") or "")
    fsm_after = str(RUNTIME.snapshot().get("fsm") or fsm_before)
    try:
        from . import exec_md

        pre_snap = dict(RUNTIME.snapshot())
        pre_snap["positions"] = pos
        pre_snap["exec"] = execu
        md_meta = exec_md.enrich_and_maybe_write(
            snap=pre_snap,
            decision=decision,
            gate=gate,
            event=event,
            source=source,
            fsm_before=fsm_before,
            fsm_after=fsm_after,
            prev_ai=prev_ai if isinstance(prev_ai, dict) else None,
        )
        fields = (md_meta or {}).get("ai_fields") or {}
        if fields:
            decision = dict(decision)
            decision.update(fields)
    except Exception:
        pass

    snap = RUNTIME.patch(
        ai=decision,
        positions=pos,
        exec=execu,
        costs=cost_patch,
        transport={
            "last_webhook_status": "AI 完成" if gate["allow"] else "閘門阻擋",
        },
    )
    # Soft-sync invalidation → TXT side file for 下單大師
    try:
        inv = (snap.get("ai") or {}).get("invalidation") or {}
        if inv.get("price") is not None:
            from .broker import write_invalidation_txt

            write_invalidation_txt(
                float(inv["price"]),
                str(inv.get("side") or "below"),
                symbol=str(snap.get("symbol") or "TXF"),
            )
    except Exception:
        pass
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
    try:
        push_async(snap, reason="decision:" + str(action), force=True)
    except Exception:
        pass
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
