# -*- coding: utf-8 -*-
"""Risk watchdog — can override AI."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from .state import TZ8


def evaluate_gate(state: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
    """Return gate result; mutates nothing."""
    reasons: list[str] = []
    allow = True

    if state.get("kill_switch") or state.get("fsm") == "Halted":
        allow = False
        reasons.append("Kill Switch / Halted")

    acct = state.get("account") or {}
    # Demo threshold: equity drop > 20% of yesterday → block new risk-on
    yb = float(acct.get("yesterday_balance") or 0)
    eq = float(acct.get("equity") or 0)
    if yb > 0 and (yb - eq) / yb >= 0.20 and decision.get("action") in {
        "ENTER_LONG", "ENTER_SHORT"
    }:
        allow = False
        reasons.append("單日權益回撤過大")

    no = state.get("no_overnight") or {}
    if no.get("enabled"):
        now = datetime.now(TZ8)
        # Simple HH:MM compare for force-flat window demo
        force = str(no.get("force_flat_time") or "13:40")
        try:
            fh, fm = [int(x) for x in force.split(":")[:2]]
            if (now.hour, now.minute) >= (fh, fm) and decision.get("action") in {
                "ENTER_LONG", "ENTER_SHORT"
            }:
                allow = False
                reasons.append("不留倉：收盤前禁止新單")
        except Exception:
            pass

    st = state.get("st_overlay") or {}
    lots = int((state.get("exec") or {}).get("lots") or 1)
    if st.get("delever"):
        lots = max(1, lots // 2)
        reasons.append("ST 降載：口數減半")

    chase = (decision.get("process") or {}).get("chase_risk") or "medium"
    if chase == "high" and int(state.get("style") or 50) < 55:
        allow = False
        reasons.append("追價風險高且風格偏保守")

    return {
        "allow": allow,
        "gate": "PASS" if allow else "BLOCK",
        "reasons": reasons,
        "lots_effective": lots,
    }
