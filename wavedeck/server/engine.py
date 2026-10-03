# -*- coding: utf-8 -*-
"""Orchestrate signal → decision → risk gate → broker → state transition."""
from __future__ import annotations

from typing import Any
from functools import wraps
import threading
import uuid

from . import audit
from .data_contract import finite_number, normalize_quote
from .signal_input import validate_signal, validate_bridge
from .broker import ensure_master_seeds, get_broker
from .config import load_config, set_broker_kind, set_mode, set_provider
from .override_notify import notify_async as notify_override_alpha
from .providers import infer_with_fallback
from .risk import evaluate_gate
from .state import RUNTIME, now_iso
from .st_link import touch_overlay
from .st_push import push_async


_execution_lock = threading.RLock()


def _serialized(function):
    @wraps(function)
    def run(*args, **kwargs):
        with _execution_lock:
            return function(*args, **kwargs)
    return run


def _persist_execution(result: dict[str, Any]) -> None:
    patch = {key: result[key] for key in ("paper_order", "execution") if key in result}
    if patch:
        RUNTIME.patch(**patch)
    state = RUNTIME.snapshot()
    if state.get("kill_switch") or state.get("fsm") == "Halted":
        return
    execution = result.get("execution") or {}
    status = execution.get("status")
    if status in {"pending", "partial"}:
        RUNTIME.set_fsm("PartialFilled" if status == "partial" else "AwaitingFill")
    elif status == "confirmed":
        RUNTIME.set_fsm("InPosition" if execution.get("confirmed_position") else "Flat")
    elif status == "idle" and state.get("fsm") == "Arming":
        RUNTIME.set_fsm("InPosition" if execution.get("confirmed_position") else "Idle")



def apply_st_bridge(body: dict[str, Any]) -> dict[str, Any]:
    """Stock Terminal macro overlay (style / delever / rotation / spillover)."""
    body = validate_bridge(body)
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
        "advRatio": finite_number(meta.get("advRatio")),
        "decision_as_of": meta.get("decision_as_of"),
        "decision_contract_version": meta.get("decision_contract_version"),
        "decision_invalidation": meta.get("decision_invalidation"),
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
        touch_overlay(as_of=meta.get("decision_as_of"))
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


def _mode_matches(state: dict, cfg: dict) -> bool:
    mode = state.get("mode")
    kind = (cfg.get("broker") or {}).get("kind")
    return (mode == "paper" and kind == "paper") or (
        mode == "live" and kind in {"txt", "txt_master", "master"})


@_serialized
def panic_positions() -> dict[str, Any]:
    """停新單、撤未成交紙上進場，再建立平倉意圖；成交仍由回報確認。"""
    from .broker import panic_flatten

    st = RUNTIME.set_kill(True)
    if not _mode_matches(st, load_config()):
        return {"ok": False, "code": "MODE_MISMATCH", "state": st}
    flat = panic_flatten(st)
    patch = {key: flat[key] for key in
             ("positions", "exec", "account", "paper_order", "execution") if key in flat}
    patch["lights"] = {**(flat.get("lights") or {}), "kill_switch": "on", "system": "halt"}
    RUNTIME.patch(**patch)
    snap = RUNTIME.set_kill(True)
    audit.write("panic_flatten", {"positions": snap.get("positions")})
    push_async(snap, reason="panic", force=True)
    return {"ok": True, "state": snap, "mode": "panic_flatten"}


@_serialized
def sync_broker_positions() -> dict[str, Any]:
    st = RUNTIME.snapshot()
    if not _mode_matches(st, load_config()):
        return {"ok": False, "code": "MODE_MISMATCH", "state": st}
    broker = get_broker()
    result = broker.sync_positions(st)
    patch: dict[str, Any] = {"positions": result.get("positions") or st.get("positions")}
    if result.get("lights"):
        patch["lights"] = result["lights"]
    if result.get("account"):
        patch["account"] = result["account"]
    RUNTIME.patch(**patch)
    _persist_execution(result)
    snap = RUNTIME.snapshot()
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


@_serialized
def handle_signal(body: dict[str, Any]) -> dict[str, Any]:
    st = RUNTIME.snapshot()
    try:
        body = validate_signal(body, str(st.get("symbol") or "TXF"))
    except ValueError as exc:
        return {"ok": False, "code": "INVALID_SIGNAL", "error": str(exc), "state": st}
    signal_id = body.get("signal_id")
    prior_intent = ((st.get("execution") or {}).get("intents") or {}).get(signal_id)
    if signal_id and prior_intent:
        return {"ok": True, "duplicate": True, "intent": prior_intent, "state": st}
    cfg = load_config()
    if not _mode_matches(st, cfg):
        return {"ok": False, "code": "MODE_MISMATCH", "error": "模式與執行介面不一致，未送出委託", "state": st}
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

    if "quote" in body:
        quote = normalize_quote(body["quote"], symbol)
        RUNTIME.patch(quote=quote, exec={"price": quote["price"]})
    elif symbol != st.get("symbol"):
        RUNTIME.patch(quote=normalize_quote(None, symbol), exec={"price": None})
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
        "quote": live.get("quote"),
        "decision_invalidation": ov.get("decision_invalidation"),
        "decision_as_of": ov.get("decision_as_of"),
    }
    decision, err = infer_with_fallback(ctx, preferred)
    if err:
        RUNTIME.patch(lights={"openai_or_local": "warn"})
    else:
        RUNTIME.patch(lights={"openai_or_local": "ok"})

    decision["intent_id"] = signal_id or uuid.uuid4().hex
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

        if broker.name == "paper":
            _persist_execution(applied)
            if applied.get("accepted") is False:
                gate["allow"] = False
                gate["gate"] = "BLOCK"
                gate["reasons"].append((applied.get("execution") or {}).get("reason") or "紙上委託未接受")
                decision["process"]["gate"] = "BLOCK"
            if applied.get("paper_order"):
                execu["lots"] = applied["paper_order"].get("quantity", execu.get("lots"))
        else:
            # TXT 的意圖不可當成帳戶成交；實盤整合仍需獨立驗收。
            target = pos.get("txt_target")
            actual = pos.get("account")
            confirmed = target is not None and actual is not None and target == actual and (
                applied.get("account") or {}).get("position_sync") == "synced"
            if action in {"ENTER_LONG", "ENTER_SHORT", "EXIT", "REDUCE"}:
                RUNTIME.set_fsm(("InPosition" if actual else "Flat") if confirmed else "AwaitingFill")
        execu["last_order_action"] = order_action
    else:
        execu["last_ai_action"] = decision["action_label"] + "（閘門擋下）"
        if RUNTIME.snapshot().get("fsm") == "Arming":
            RUNTIME.set_fsm("Idle")

    execu["last_ai_action"] = decision["action_label"]
    # Persist preferred provider used (may be fallback heuristic)
    used = decision.get("provider") or preferred
    prev_costs = dict(RUNTIME.snapshot().get("costs") or {})
    delta = finite_number(decision.get("cost_usd"))
    def cumulative(key):
        previous = finite_number(prev_costs.get(key))
        return round(previous + delta, 6) if previous is not None and delta is not None else None
    cost_patch = {
        "provider": used,
        "session_usd": cumulative("session_usd"),
        "day_usd": cumulative("day_usd"),
        "month_usd": cumulative("month_usd"),
        "local_calls": int(prev_costs.get("local_calls") or 0) + int(decision.get("local_calls") or 0),
        "cloud_calls": int(prev_costs.get("cloud_calls") or 0) + int(decision.get("cloud_calls") or 0),
    }
    if isinstance(decision.get("budget"), dict):
        budget = decision["budget"]
        cost_patch["budget"] = budget
        cost_patch["day_usd"] = (finite_number(budget.get("spent_usd"))
                               if budget.get("unknown_requests") == 0 and
                               budget.get("pending_requests") == 0 else None)
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
        if snap.get("mode") == "live" and inv.get("price") is not None:
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
    "panic_positions",
    "get_runtime_config",
]
