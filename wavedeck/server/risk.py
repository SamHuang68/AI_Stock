# -*- coding: utf-8 -*-
"""Risk watchdog — can override AI."""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from .data_contract import assess_quote, finite_number
from .不留倉 import deadline_status

# Entry confidence floor (heuristic/LLM). 0 = disabled.
MIN_ENTRY_CONFIDENCE = float(os.environ.get("WD_MIN_ENTRY_CONFIDENCE", "0.70"))
# Hard daily equity drawdown vs yesterday_balance (e.g. 0.05 = 5%)
MAX_DAILY_DD = float(os.environ.get("WD_MAX_DAILY_DD", "0.05"))
# Soft warn lamp threshold (default 3%)
WARN_DAILY_DD = float(os.environ.get("WD_WARN_DAILY_DD", "0.03"))
# 行情政策（裁量模式的新單）：實帳一律要新鮮、帶時區時間戳的行情。紙上模式容許舊式只帶 price 的訊號
# （只警示），但「帶了 quote 卻過期／未來／無效」一律擋。設 1 可讓紙上模式也強制，用來逐步導入送件端。
PAPER_REQUIRES_QUOTE = os.environ.get("WD_PAPER_REQUIRES_QUOTE", "") == "1"


REFERENCE_ACCOUNT_SOURCES = {"wave_ai_ref", "reference", "demo"}


def _is_reference_account(acct: dict[str, Any]) -> bool:
    if "reference" in acct:  # 明確旗標優先；沒有旗標時才看來源
        return acct.get("reference") is True
    return acct.get("source") in REFERENCE_ACCOUNT_SOURCES


def daily_dd_known(state: dict[str, Any]) -> bool:
    """示範／參考帳戶的權益不是使用者實盤，不能拿來觸發回撤鎖（審查 WD-04）。"""
    acct = state.get("account") or {}
    if _is_reference_account(acct):
        return False
    # 紙上模擬權益在缺價格或帳本不一致時回報 None；未知權益不能當成 0 回撤（審查 WD-07）。
    # NaN／Infinity 不是已量測的權益：`max(0.0, nan)` 是 0.0，會讓回撤鎖看起來「量過、0%」卻永不觸發。
    equity, yesterday = acct.get("equity"), acct.get("yesterday_balance")
    if equity is None or yesterday is None:
        return False
    return finite_number(equity) is not None and finite_number(yesterday) is not None


def daily_dd_invalid(state: dict[str, Any]) -> bool:
    """真實帳戶的權益或昨日餘額有給，卻不是有限數值（NaN／Infinity／布林／非數字）。

    這是壞資料，不是「未知」：未知只警示（既有行為），壞資料擋新單。參考／示範帳戶的數字本來就不用於回撤鎖。"""
    acct = state.get("account") or {}
    if _is_reference_account(acct):
        return False
    return any(acct.get(key) is not None and finite_number(acct.get(key)) is None
               for key in ("equity", "yesterday_balance"))


def daily_dd_ratio(state: dict[str, Any]) -> float:
    """Session drawdown ratio vs yesterday_balance; 0 if unknown / flat-or-up / reference account."""
    if not daily_dd_known(state):
        return 0.0
    acct = state.get("account") or {}
    yb = finite_number(acct.get("yesterday_balance") or 0)
    eq = finite_number(acct.get("equity") or 0)
    if yb is None or eq is None:
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
    if daily_dd_invalid(state) and decision.get("action") in {"ENTER_LONG", "ENTER_SHORT"}:
        # 壞資料不是「未知」：未知只警示，壞資料不能讓回撤鎖悄悄失效，所以擋新單。
        allow = False
        reasons.append("權益資料無效（非有限數值）：禁止新單")
    elif dd >= MAX_DAILY_DD and decision.get("action") in {
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

    # 行情政策：規則模式的訊號已由 策略契約 在收訊號時強制時間戳、新鮮度與價格，不重複擋。
    # 裁量模式（TradingView／手動／AI 決策）原本只帶 price，沒有來源時間，exec.price 預設還是示範數字 45020。
    if decision.get("action") in {"ENTER_LONG", "ENTER_SHORT"} and (state.get("strategy_execution") or {}).get("mode") != "rules":
        mode = str(state.get("mode") or "paper")          # 與 _default_state 的預設一致
        symbol = str(state.get("symbol") or "TXF")
        raw_quote = state.get("quote")
        if raw_quote is None:                              # 尚未記錄行情：只有 exec.price，沒有來源時間
            raw_quote = {"symbol": symbol, "price": (state.get("exec") or {}).get("price"), "source": "signal.price"}
        quote = assess_quote(raw_quote, symbol, mode=mode)
        if not quote["entry_allowed"]:
            price_only = quote["quality"] == "unknown" and quote["price"] is not None and quote["as_of"] is None
            if price_only and mode == "paper" and not PAPER_REQUIRES_QUOTE:
                reasons.append("行情來源時間未知（舊式只帶 price 的訊號）：紙上模式僅警示，實帳會擋")
            else:
                allow = False
                reasons.extend(quote["reasons"] or ["行情不可用：禁止新單"])

    st = state.get("st_overlay") or {}
    link = state.get("st_link") or {}
    # 非有限值（NaN／Infinity）在 int()／比較裡不是例外就是被放行；一律當未知，用預設。
    lots_value = finite_number((state.get("exec") or {}).get("lots"))
    lots = int(lots_value or 1) if lots_value is not None else 1
    style_value = finite_number(state.get("style"))
    style = int(style_value or 50) if style_value is not None else 50
    spill = finite_number(st.get("spillover_prob"))

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
    conf = finite_number(decision.get("confidence"))
    # 有給卻不是有限數值（NaN、Infinity、布林、非數字）是壞資料：`nan < 門檻` 為 False，不擋就等於門檻被跳過。
    # 沒給（None）維持既有行為：略過門檻。
    if (
        MIN_ENTRY_CONFIDENCE > 0
        and decision.get("confidence") is not None
        and conf is None
        and decision.get("action") in {"ENTER_LONG", "ENTER_SHORT"}
    ):
        allow = False
        reasons.append("信心度無效（非有限數值）：禁止新單")
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
        and style < 55
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
