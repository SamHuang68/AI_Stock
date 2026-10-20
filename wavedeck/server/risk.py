# -*- coding: utf-8 -*-
"""Risk watchdog — can override AI."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from .不留倉 import deadline_status

# Entry confidence floor (heuristic/LLM). 0 = disabled.
MIN_ENTRY_CONFIDENCE = float(os.environ.get("WD_MIN_ENTRY_CONFIDENCE", "0.70"))
# Hard daily equity drawdown vs yesterday_balance (e.g. 0.05 = 5%)
MAX_DAILY_DD = float(os.environ.get("WD_MAX_DAILY_DD", "0.05"))
# Soft warn lamp threshold (default 3%)
WARN_DAILY_DD = float(os.environ.get("WD_WARN_DAILY_DD", "0.03"))


REFERENCE_ACCOUNT_SOURCES = {"wave_ai_ref", "reference", "demo"}


def daily_dd_known(state: dict[str, Any]) -> bool:
    """示範／參考帳戶的權益不是使用者實盤，不能拿來觸發回撤鎖（審查 WD-04）。"""
    acct = state.get("account") or {}
    if "reference" in acct:  # 明確旗標優先；沒有旗標時才看來源
        return acct.get("reference") is not True
    return acct.get("source") not in REFERENCE_ACCOUNT_SOURCES


def daily_dd_ratio(state: dict[str, Any]) -> float:
    """Session drawdown ratio vs yesterday_balance; 0 if unknown / flat-or-up / reference account."""
    if not daily_dd_known(state):
        return 0.0
    acct = state.get("account") or {}
    try:
        yb = float(acct.get("yesterday_balance") or 0)
        eq = float(acct.get("equity") or 0)
    except Exception:
        return 0.0
    if yb <= 0:
        return 0.0
    return max(0.0, (yb - eq) / yb)


def evaluate_gate(
    state: dict[str, Any], decision: dict[str, Any], *, now: datetime | None = None
) -> dict[str, Any]:
    """Return gate result; mutates nothing."""
    reasons: list[str] = []
    allow = True

    # 急停的目的是擋新風險：平倉與減碼放行，否則回撤鎖定或不留倉截止時部位會被鎖在場內（Sam 2026-10-19）。
    if (state.get("kill_switch") or state.get("fsm") == "Halted") and decision.get("action") not in {"EXIT", "REDUCE"}:
        allow = False
        reasons.append("Kill Switch / Halted")

    # 停止一般執行時仍保留減碼與平倉；所有新風險在送單前統一阻擋。
    if (state.get("lights") or {}).get("system") in {"stop", "halt"} and decision.get("action") in {"ENTER_LONG", "ENTER_SHORT"}:
        allow = False
        reasons.append("系統已停止：禁止新單，仍允許減碼與平倉")

    # Hard daily max drawdown — block new risk-on (and note when already locked)
    dd = daily_dd_ratio(state)
    if dd >= MAX_DAILY_DD and decision.get("action") in {
        "ENTER_LONG", "ENTER_SHORT"
    }:
        allow = False
        reasons.append(f"單日回撤 {dd:.1%} ≥ 上限 {MAX_DAILY_DD:.0%}：禁止新單")
    elif dd >= WARN_DAILY_DD and decision.get("action") in {
        "ENTER_LONG", "ENTER_SHORT"
    }:
        reasons.append(f"單日回撤警戒 {dd:.1%}（上限 {MAX_DAILY_DD:.0%}）")
    elif not daily_dd_known(state) and decision.get("action") in {"ENTER_LONG", "ENTER_SHORT"}:
        reasons.append("單日回撤未知：帳戶為示範參考數值，回撤上限未生效")

    no = deadline_status(state, now)
    if no["blocked_new"] and decision.get("action") in {"ENTER_LONG", "ENTER_SHORT"}:
        allow = False
        reasons.append(no["error"] or "不留倉：已進入截止前禁新單時窗")

    st = state.get("st_overlay") or {}
    link = state.get("st_link") or {}
    lots = int((state.get("exec") or {}).get("lots") or 1)
    try:
        spill = float(st.get("spillover_prob")) if st.get("spillover_prob") is not None else None
    except Exception:
        spill = None

    # Fail-safe / ST link down: block new risk-on + hard delever
    fail_safe = bool(st.get("fail_safe") or link.get("fail_safe") or link.get("status") == "down")
    if fail_safe and decision.get("action") in {"ENTER_LONG", "ENTER_SHORT"}:
        allow = False
        reasons.append("Fail-safe／ST 斷線：禁止新單")

    # Extreme low spillover: block new risk-on (macro diffusion broken)
    if spill is not None and spill < 0.20 and decision.get("action") in {
        "ENTER_LONG", "ENTER_SHORT"
    }:
        allow = False
        reasons.append("外溢極低：禁止新單")

    # Confidence floor for new risk-on (skip if provider left confidence null)
    try:
        conf = float(decision["confidence"]) if decision.get("confidence") is not None else None
    except Exception:
        conf = None
    if (
        MIN_ENTRY_CONFIDENCE > 0
        and conf is not None
        and conf < MIN_ENTRY_CONFIDENCE
        and decision.get("action") in {"ENTER_LONG", "ENTER_SHORT"}
    ):
        allow = False
        reasons.append(f"信心度 {conf:.0%} < 門檻 {MIN_ENTRY_CONFIDENCE:.0%}")

    if st.get("delever") or fail_safe:
        lots = max(1, lots // 2)
        reasons.append("ST 降載：口數減半" if not fail_safe else "Fail-safe 降載：口數減半")
    elif spill is not None and spill < 0.35 and decision.get("action") in {
        "ENTER_LONG", "ENTER_SHORT"
    }:
        lots = max(1, lots // 2)
        reasons.append("外溢偏低：新單口數減半")

    chase = (decision.get("process") or {}).get("chase_risk") or "medium"
    if (
        chase == "high"
        and int(state.get("style") or 50) < 55
        and decision.get("action") in {"ENTER_LONG", "ENTER_SHORT"}
    ):
        allow = False
        reasons.append("追價風險高且風格偏保守")
    if (
        chase == "high"
        and spill is not None
        and spill < 0.30
        and decision.get("action") in {"ENTER_LONG", "ENTER_SHORT"}
    ):
        allow = False
        if "外溢偏低＋追價風險：禁止新單" not in reasons:
            reasons.append("外溢偏低＋追價風險：禁止新單")

    return {
        "allow": allow,
        "gate": "PASS" if allow else "BLOCK",
        "reasons": reasons,
        "lots_effective": lots,
        "daily_dd": round(dd, 4),
    }
