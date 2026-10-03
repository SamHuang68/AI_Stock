# -*- coding: utf-8 -*-
"""交易閘門：行情可信度、演練隔離與回撤防護。"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from .data_contract import assess_quote, finite_number
from .state import TZ8

MIN_ENTRY_CONFIDENCE = float(os.environ.get("WD_MIN_ENTRY_CONFIDENCE", "0.70"))
MAX_DAILY_DD = float(os.environ.get("WD_MAX_DAILY_DD", "0.05"))
WARN_DAILY_DD = float(os.environ.get("WD_WARN_DAILY_DD", "0.03"))


def daily_dd_ratio(state: dict[str, Any]) -> float | None:
    """真實且有效權益才計算回撤；未知、參考或演練資料回傳 None。"""
    acct = state.get("account") or {}
    if acct.get("reference") or acct.get("demo") or str(acct.get("source") or "").lower() in {
        "wave_ai_ref", "reference", "demo", "legacy_demo",
    }:
        return None
    yb = finite_number(acct.get("yesterday_balance"))
    eq = finite_number(acct.get("equity"))
    if yb is None or eq is None or yb <= 0 or eq < 0:
        return None
    return 0.0 if eq >= yb else (yb - eq) / yb


def evaluate_gate(state: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """不修改狀態；未知行情與權益不阻擋既有部位減碼或離場。"""
    reasons: list[str] = []
    allow = True
    action = decision.get("action")
    risk_on = action in {"ENTER_LONG", "ENTER_SHORT"}
    reducing = action in {"REDUCE", "EXIT"}
    mode = str(state.get("mode") or "unknown")
    if (state.get("kill_switch") or state.get("fsm") == "Halted") and not reducing:
        allow = False
        reasons.append("Kill Switch / Halted")

    dd = daily_dd_ratio(state)
    quote = assess_quote(state.get("quote"), state.get("symbol"), mode=mode)
    if risk_on:
        if not quote["entry_allowed"]:
            allow = False
            reasons.extend(quote["reasons"] or ["行情不可用：禁止新單"])
        if mode != "paper" and (decision.get("demo") or decision.get("provider") == "heuristic"):
            allow = False
            reasons.append("紙上規則演練不得增加實帳風險")
        if dd is None:
            reasons.append("回撤未知：僅允許紙上演練" if mode == "paper" else "回撤未知：禁止新單")
            if mode != "paper":
                allow = False
        elif dd >= MAX_DAILY_DD:
            allow = False
            reasons.append(f"單日回撤 {dd:.1%} ≥ 上限 {MAX_DAILY_DD:.0%}：禁止新單")
        elif dd >= WARN_DAILY_DD:
            reasons.append(f"單日回撤警戒 {dd:.1%}（上限 {MAX_DAILY_DD:.0%}）")

    no = state.get("no_overnight") or {}
    if no.get("enabled") and risk_on:
        now = datetime.now(TZ8)
        force = str(no.get("force_flat_time") or "13:40")
        try:
            fh, fm = [int(x) for x in force.split(":")[:2]]
            if (now.hour, now.minute) >= (fh, fm):
                allow = False
                reasons.append("不留倉：收盤前禁止新單")
        except (ValueError, TypeError):
            pass

    st = state.get("st_overlay") or {}
    link = state.get("st_link") or {}
    raw_lots = finite_number((state.get("exec") or {}).get("lots"))
    lots = max(1, int(raw_lots)) if raw_lots is not None else 1
    spill = finite_number(st.get("spillover_prob"))
    fail_safe = bool(st.get("fail_safe") or link.get("fail_safe") or link.get("status") == "down")
    if risk_on and fail_safe:
        allow = False
        reasons.append("Fail-safe／ST 斷線：禁止新單")
    if risk_on and spill is not None and spill < 0.20:
        allow = False
        reasons.append("外溢極低：禁止新單")

    conf = finite_number(decision.get("confidence"))
    if risk_on and (conf is None or not 0 <= conf <= 1) and mode != "paper":
        allow = False
        reasons.append("決策信心度未知或無效：禁止實帳新單")
    if risk_on and MIN_ENTRY_CONFIDENCE > 0 and conf is not None and conf < MIN_ENTRY_CONFIDENCE:
        allow = False
        reasons.append(f"信心度 {conf:.0%} < 門檻 {MIN_ENTRY_CONFIDENCE:.0%}")
    if risk_on and (st.get("delever") or fail_safe):
        lots = max(1, lots // 2)
        reasons.append("ST 降載：口數減半" if not fail_safe else "Fail-safe 降載：口數減半")
    elif risk_on and spill is not None and spill < 0.35:
        lots = max(1, lots // 2)
        reasons.append("外溢偏低：新單口數減半")

    chase = (decision.get("process") or {}).get("chase_risk") or "medium"
    style = finite_number(state.get("style"))
    if risk_on and chase == "high" and (style if style is not None else 50) < 55:
        allow = False
        reasons.append("追價風險高且風格偏保守")
    if risk_on and chase == "high" and spill is not None and spill < 0.30:
        allow = False
        reasons.append("外溢偏低＋追價風險：禁止新單")
    return {
        "allow": allow,
        "gate": "PASS" if allow else "BLOCK",
        "reasons": reasons,
        "lots_effective": lots,
        "daily_dd": round(dd, 4) if dd is not None else None,
        "quote_quality": quote["quality"],
    }
