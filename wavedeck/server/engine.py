# -*- coding: utf-8 -*-
"""Orchestrate signal → decision → risk gate → broker → state transition."""
from __future__ import annotations

from typing import Any
from datetime import datetime
import math
import threading
import uuid
from functools import wraps

from . import audit
from .broker import execution_pending, get_broker
from .config import load_config, set_broker_kind, set_mode, set_provider
from .override_notify import notify_async as notify_override_alpha
from .providers import infer_with_fallback
from .risk import evaluate_gate
from .state import RUNTIME, TZ8, now_iso
from . import 策略契約 as contracts
from .不留倉 import deadline_status
from .st_link import touch_overlay
from .st_push import push_async

_ORDER_LOCK = threading.RLock()


def _serialized(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        with _ORDER_LOCK:
            return fn(*args, **kwargs)
    return wrapped


@_serialized
def set_kill_switch(on: bool) -> dict:
    return RUNTIME.set_kill(on)


@_serialized
def panic() -> dict:
    from .broker import panic_flatten
    # 先鎖定新單；即使平倉寫入失敗也維持急停。
    st = RUNTIME.set_kill(True)
    flat = panic_flatten(st)
    snap = _apply_patch(st, flat)
    snap = RUNTIME.patch(exec=flat.get("exec") or {}, lights={"kill_switch": "on", "system": "halt"})
    audit.write("panic_flatten", {"positions": snap.get("positions"), "execution": snap.get("execution")})
    push_async(snap, reason="panic", force=True)
    return {"ok": True, "state": snap, "mode": "panic_flatten"}


@_serialized
def system_control(cmd: str) -> dict:
    st = RUNTIME.snapshot()
    if cmd == "start":
        if st.get("fsm") == "Halted" and not st.get("kill_switch"):
            RUNTIME.set_fsm("Idle")
        RUNTIME.patch(lights={"system": "run"})
    elif cmd == "stop":
        RUNTIME.patch(lights={"system": "stop"})
    elif cmd == "restart":
        RUNTIME.set_kill(False)
        RUNTIME.patch(lights={"system": "run"})
        sync_broker_positions()
    elif cmd == "refresh":
        sync_broker_positions()
    else:
        raise ValueError("未知的系統操作")
    audit.write("control", {"cmd": cmd})
    return {"ok": True, "state": RUNTIME.snapshot()}


def _confirmed_fsm(state: dict, applied: dict) -> str:
    if state.get("kill_switch") or state.get("fsm") == "Halted":
        return "Halted"
    if applied.get("blocked"):
        return str(state.get("fsm") or "Idle")
    execution = applied.get("execution") or {}
    account = (applied.get("positions") or state.get("positions") or {}).get("account")
    unresolved = execution_pending(execution) or (
        execution.get("status") == "filled" and not execution.get("position_confirmed"))
    if unresolved:
        return "Reducing" if execution.get("target") == 0 else "Arming"
    return "InPosition" if account else "Flat"


def _apply_patch(state: dict, applied: dict) -> dict:
    patch = {key: applied[key] for key in ("positions", "execution", "lights", "account") if key in applied}
    patch["fsm"] = _confirmed_fsm(state, applied)
    if all(state.get(key) == value for key, value in patch.items()):
        return state
    return RUNTIME.patch(**patch)


def activate_strategy(body: dict) -> dict:
    with _ORDER_LOCK:
        manifest = contracts.get(str(body.get("strategy_id") or ""), str(body.get("version") or ""))
        st = RUNTIME.snapshot()
        execution = st.get("execution") or {}
        if execution_pending(execution) or (execution.get("status") == "filled" and not execution.get("position_confirmed")):
            raise ValueError("委託尚未核對，請先完成核對再切換策略")
        if any((st.get("positions") or {}).get(key) for key in ("account", "txt_target")):
            raise ValueError("仍有部位，請先平倉並核對後再切換策略")
        age = body.get("max_signal_age_sec", 300)
        if isinstance(age, bool) or not isinstance(age, int) or not 10 <= age <= 3600:
            raise ValueError("訊號有效秒數須為 10 至 3600 的整數")
        active = {"mode": "rules", "strategy_id": manifest["strategy_id"], "version": manifest["version"], "max_signal_age_sec": age}
        snap = RUNTIME.patch(strategy_execution=active, symbol=manifest["context"]["symbol"], execution={"order_id": None, "status": "idle", "position_confirmed": False})
        audit.write("strategy_activated", active)
        return {"ok": True, "manifest": manifest, "state": snap}


def set_strategy_mode(mode: str) -> dict:
    if mode != "discretionary":
        raise ValueError("依規則執行須先匯入並啟用指定版本")
    with _ORDER_LOCK:
        snap = RUNTIME.patch(strategy_execution={"mode": mode})
        audit.write("strategy_mode", {"mode": mode})
        return {"ok": True, "state": snap}


def set_no_overnight(body: dict) -> dict:
    allowed = {key: body[key] for key in ("enabled", "force_flat_time", "block_new_before_close_min") if key in body}
    if "enabled" in allowed and not isinstance(allowed["enabled"], bool):
        raise ValueError("不留倉啟用設定須為布林值")
    with _ORDER_LOCK:
        config = {**(RUNTIME.snapshot().get("no_overnight") or {}), **allowed}
        checked = deadline_status({"no_overnight": {**config, "enabled": True}})
        if checked["error"]:
            raise ValueError(checked["error"])
        snap = RUNTIME.patch(no_overnight=config)
        audit.write("no_overnight_config", config)
        return {"ok": True, "state": snap}


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


@_serialized
def set_decision_provider(name: str) -> dict[str, Any]:
    cfg = set_provider(name)
    snap = RUNTIME.patch(
        costs={"provider": cfg["provider"]},
        lights={"openai_or_local": "ok"},
    )
    audit.write("provider", {"provider": cfg["provider"]})
    return {"ok": True, "provider": cfg["provider"], "state": snap}


@_serialized
def set_exec_mode(mode: str) -> dict[str, Any]:
    cfg = set_mode(mode)
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


@_serialized
def set_broker(kind: str) -> dict[str, Any]:
    cfg = set_broker_kind(kind)
    snap = RUNTIME.patch(
        account={"broker_api": cfg["broker"]["kind"]},
        lights={"broker_api": "ok", "order_signal_file": "ok"},
    )
    audit.write("broker", {"kind": cfg["broker"]["kind"]})
    return {"ok": True, "broker": cfg["broker"]["kind"], "state": snap}


def sync_broker_positions() -> dict[str, Any]:
    with _ORDER_LOCK:
        broker = get_broker()
        st = RUNTIME.snapshot()
        result = broker.sync_positions(st)
        snap = _apply_patch(st, result)
        if st.get("execution") != snap.get("execution"):
            audit.write("execution_confirmation", {"broker": broker.name, "execution": snap.get("execution")})
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


def _blocked(reason: str, body: dict) -> dict:
    audit.write("signal_blocked", {"reason": reason, "body": body})
    return {"ok": False, "blocked": True, "reason": reason, "error": reason, "state": RUNTIME.snapshot()}


def handle_signal(body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        return _blocked("訊號內容須為 JSON 物件", {})
    claimed = False
    with _ORDER_LOCK:
        st = RUNTIME.snapshot()
        active = dict(st.get("strategy_execution") or {"mode": "discretionary"})
        rules = active.get("mode") == "rules"
        if st.get("kill_switch") or st.get("fsm") == "Halted":
            return _blocked("緊急停止已啟用", body)
        symbol = str(body.get("symbol") or st.get("symbol") or "TXF")
        if symbol != st.get("symbol") and any((st.get("positions") or {}).get(key) for key in ("account", "txt_target")):
            return _blocked("目前商品尚有部位，不可切換其他商品訊號", body)
        try:
            if rules:
                decision = contracts.decision_from_signal(body, active)
                prior = contracts.claim(body)
                if prior is not None:
                    return {**prior, "duplicate": True, "state": st}
                claimed = True
            elif any(key in body for key in ("strategy_id", "version", "signal_id")):
                return _blocked("策略訊號須先啟用對應的依規則執行模式", body)
        except (ValueError, TypeError) as exc:
            return _blocked(str(exc), body)
        event = str(body.get("event") or "MANUAL_REVIEW")
        source = str(body.get("source") or "manual")
        RUNTIME.patch(symbol=symbol, transport={"last_tv_event": f"{event} · {now_iso()}", "last_webhook_status": "處理中"}, lights={"webhook": "ok"})
        cfg = load_config()
        preferred = str(body.get("provider") or (st.get("costs") or {}).get("provider") or cfg.get("provider") or "heuristic")
        ov = st.get("st_overlay") or {}
        price = body.get("price", (st.get("exec") or {}).get("price"))
        if not isinstance(price, (int, float)) or isinstance(price, bool) or not math.isfinite(price) or price <= 0:
            price = (st.get("exec") or {}).get("price")
        ctx = {"style": st.get("style"), "event": event, "positions": st.get("positions"), "price": price,
               "source": source, "symbol": symbol, "mode": st.get("mode"), "source_signal": body,
               "timeframe": body.get("timeframe"), "st_rotation": ov.get("rotation"),
               "st_spillover_prob": ov.get("spillover_prob"), "st_hot_stage": ov.get("hot_stage"),
               "st_delever": bool(ov.get("delever")), "st_score": ov.get("score")}
    # 模型推論不占送單鎖；截止監控可即時平倉，回來後再以新狀態套用閘門。
    if rules:
        err = None
    else:
        decision, err = infer_with_fallback(ctx, preferred)
    with _ORDER_LOCK:
        live = RUNTIME.snapshot()
        if (live.get("strategy_execution") or {"mode": "discretionary"}) != active or live.get("symbol") != symbol or live.get("mode") != st.get("mode") or (load_config().get("broker") or {}).get("kind") != (cfg.get("broker") or {}).get("kind"):
            result = _blocked("策略執行模式已改變，此次判斷作廢", body)
        else:
            RUNTIME.patch(exec={"price": price}, lights={"openai_or_local": "warn" if err else "ok"})
            decision["decision_id"] = uuid.uuid4().hex
            result = _finish_decision(live, decision, err, preferred, event, source, body)
        if claimed:
            contracts.finish(body, result)
    return _enrich_result(result, st, event, source)


def _finish_decision(st, decision, err, preferred, event, source, body):
    decision.setdefault("process", {})
    gate = evaluate_gate(RUNTIME.snapshot(), decision)
    if decision.get("requested_lots") is not None:
        gate["lots_effective"] = min(gate["lots_effective"], decision["requested_lots"])
    if deadline_status(RUNTIME.snapshot())["due"] and decision.get("action") == "HOLD":
        gate.update(allow=False, gate="BLOCK")
        gate["reasons"].append("已到不留倉截止時間，由獨立監控執行平倉")
    decision["process"]["gate"] = gate["gate"]
    decision["process"]["gate_reasons"] = gate["reasons"]

    pos = dict(RUNTIME.snapshot().get("positions") or {})
    execu = dict(RUNTIME.snapshot().get("exec") or {})
    action = decision["action"]
    order_action = execu.get("last_order_action") or "—"

    if gate["allow"]:
        broker = get_broker()
        applied = broker.apply_intent(RUNTIME.snapshot(), decision, int(gate["lots_effective"]))
        if applied.get("blocked"):
            gate.update(allow=False, gate="BLOCK")
            gate["reasons"].append(str(applied.get("reason") or "券商拒絕送單"))
            decision["process"].update(gate=gate["gate"], gate_reasons=gate["reasons"])
        pos = dict(applied.get("positions") or pos)
        order_action = str(applied.get("order_action") or order_action)
        if applied.get("lights"):
            RUNTIME.patch(lights=applied["lights"])
        if applied.get("account"):
            RUNTIME.patch(account=applied["account"])

        settled = _apply_patch(RUNTIME.snapshot(), applied)
        execu["lots"] = abs(int((settled.get("positions") or {}).get("account") or 0))
        execu["last_order_action"] = order_action
    else:
        execu["last_ai_action"] = decision["action_label"] + "（閘門擋下）"
        if RUNTIME.snapshot().get("fsm") == "Arming":
            RUNTIME.set_fsm(_confirmed_fsm(RUNTIME.snapshot(), {"execution": RUNTIME.snapshot().get("execution") or {}}))

    execu["last_ai_action"] = decision["action_label"]
    # Persist preferred provider used (may be fallback heuristic)
    used = preferred if decision.get("provider") == "rules" else decision.get("provider") or preferred
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
            "source_signal": body,
            "execution": snap.get("execution"),
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
        "execution": snap.get("execution"),
        "blocked": not gate["allow"],
        "state": snap,
    }


def _enrich_result(result: dict, before: dict, event: str, source: str) -> dict:
    """保留敘事能力，但慢速模型不得阻塞風控或回寫舊部位。"""
    decision, snap = result.get("decision"), result.get("state")
    if not isinstance(decision, dict) or not isinstance(snap, dict):
        return result
    try:
        from . import exec_md
        meta = exec_md.enrich_and_maybe_write(
            snap=snap, decision=decision, gate=result["gate"], event=event, source=source,
            fsm_before=str(before.get("fsm") or ""), fsm_after=str(snap.get("fsm") or ""),
            prev_ai=before.get("ai"))
        fields = (meta or {}).get("ai_fields") or {}
        if fields:
            decision = {**decision, **fields}
            result["decision"] = decision
            with _ORDER_LOCK:
                live = RUNTIME.snapshot()
                if (live.get("ai") or {}).get("decision_id") == decision.get("decision_id"):
                    RUNTIME.patch(ai=fields)
                result["state"] = RUNTIME.snapshot()
    except Exception as exc:
        # 敘事失敗不改變已送出的委託；保留可追查錯誤。
        audit.write("decision_narrative_error", {"decision_id": decision.get("decision_id"), "error": str(exc)})
    return result


def enforce_no_overnight(now: datetime | None = None) -> dict:
    """截止後只降低部位；未知委託不重送，拒單最多重試三次。"""
    if not _ORDER_LOCK.acquire(blocking=False):
        return {"ok": False, "pending": True, "reason": "券商處理中，下一秒重新核對"}
    try:
        current = now or datetime.now(TZ8)
        synced = sync_broker_positions()
        st = synced["state"]
        status = deadline_status(st, current)
        prior = dict(st.get("overnight_enforcement") or {})
        carry = prior.get("status") in {"pending", "failed", "blocked"}
        if not status["enabled"] or not (status["due"] or carry):
            return {"ok": True, "state": st}
        execution = st.get("execution") or {}
        positions = st.get("positions") or {}
        deadline = status["deadline"].isoformat() if status["deadline"] else prior.get("deadline")
        if carry:
            deadline = prior.get("deadline") or deadline
        base = prior if carry or prior.get("date") == status["date"] else {}
        progress = {**base, "deadline": deadline, "date": prior.get("date") if carry else status["date"]}
        progress.setdefault("attempts", 0)
        account_known = get_broker().name == "paper" or (synced.get("meta") or {}).get("account") is not None
        unresolved = execution_pending(execution) or (execution.get("status") == "filled" and not execution.get("position_confirmed"))
        if account_known and positions.get("account") == 0 and positions.get("txt_target") == 0 and not unresolved:
            progress.update(status="confirmed", message="已核對平倉" + ("（紙上模擬）" if get_broker().name == "paper" else ""))
        elif st.get("kill_switch") or st.get("fsm") == "Halted" or (st.get("lights") or {}).get("system") in {"stop", "halt"}:
            progress.update(status="blocked", message="系統停止或緊急停止中；平倉尚未完成")
        elif execution.get("target") == 0 and unresolved:
            progress.update(status="pending", message="平倉委託已送出，等待核對；不重複送單")
        elif not account_known:
            progress.update(status="blocked", message="無法讀取帳戶部位；待恢復後執行平倉")
        elif int(progress["attempts"]) >= 3:
            progress.update(status="failed", message="平倉拒絕或失敗已達三次，請人工核對券商")
        elif current.timestamp() - float(progress.get("last_attempt_epoch") or 0) >= 30:
            decision = {"action": "EXIT", "action_label": "不留倉截止平倉", "confidence": None,
                        "provider": "risk_watchdog", "signal_id": "deadline:" + str(deadline) + ":" + str(progress["attempts"]),
                        "strategy_id": (st.get("strategy_execution") or {}).get("strategy_id"),
                        "version": (st.get("strategy_execution") or {}).get("version"),
                        "process": {"route": "不留倉截止→風控→券商", "chase_risk": "low"}}
            gate = evaluate_gate(st, decision, now=current)
            if gate["allow"]:
                progress.update(attempts=int(progress["attempts"]) + 1, last_attempt_epoch=current.timestamp())
                applied = get_broker().apply_intent(st, decision, 0)
                snap = _apply_patch(st, applied)
                receipt = snap.get("execution") or {}
                done = receipt.get("position_confirmed") and (snap.get("positions") or {}).get("account") == 0
                progress.update(status="confirmed" if done else "pending", message="截止平倉已核對" if done else "截止平倉已送出，等待核對")
                RUNTIME.patch(exec={"last_order_action": applied.get("order_action") or "截止平倉"})
                audit.write("no_overnight_order", {"decision": decision, "gate": gate, "execution": receipt})
            else:
                progress.update(status="blocked", message="；".join(gate["reasons"]))
        if progress != prior:
            RUNTIME.patch(overnight_enforcement=progress)
            audit.write("no_overnight_status", progress)
        return {"ok": progress.get("status") == "confirmed", "state": RUNTIME.snapshot()}
    finally:
        _ORDER_LOCK.release()


__all__ = [
    "apply_st_bridge",
    "handle_signal",
    "set_decision_provider",
    "set_exec_mode",
    "set_broker",
    "sync_broker_positions",
    "get_runtime_config",
]
