# -*- coding: utf-8 -*-
"""可持久化的紙上委託與純離線成交對帳；不讀寫檔案或呼叫券商。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math
from typing import Any
from uuid import uuid4


ACTIVE_STATUSES = {"pending", "partial"}


def _integer(value: Any, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name}必須是整數")
    if not math.isfinite(value) or int(value) != value or (positive and value <= 0):
        raise ValueError(f"{name}必須是{'正' if positive else ''}整數")
    return int(value)


def _timestamp(value: Any, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name}必須有含時區的時間")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name}時間格式錯誤") from exc
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise ValueError(f"{name}時間必須含時區")
    return stamp


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{name}不可空白或包含首尾空白")
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def paper_snapshot(state: dict[str, Any], *, accepted: bool = True,
                   reason: str | None = None) -> dict[str, Any]:
    """回傳供 engine 一次保存的獨立副本，不把目標部位當成成交。"""
    pos = deepcopy(state.get("positions") or {})
    order = deepcopy(state.get("paper_order"))
    execution = deepcopy(state.get("execution") or {})
    execution.setdefault("receipts", {})
    execution.setdefault("intents", {})
    status = order.get("status", "idle") if order else "idle"
    execution["status"] = status
    execution["confirmed_position"] = pos.get("account", 0)
    if reason is not None:
        execution["reason"] = reason
    pending = status in ACTIVE_STATUSES
    synced = pos.get("account", 0) == pos.get("strategy", 0) == pos.get("txt_target", 0)
    account = deepcopy(state.get("account") or {})
    account.update(broker_api="paper", position_sync=(status if pending else "synced" if synced else "drift"))
    labels = {"idle": "紙上待命", "pending": "紙上委託待成交", "partial": "紙上部分成交", "confirmed": "紙上成交已對帳"}
    return {
        "positions": pos,
        "account": account,
        "lights": {"broker_api": "ok", "order_signal_file": "idle", "position_sync": "ok" if synced and not pending else "warn"},
        "order_action": reason or execution.get("reason") or labels.get(status, "紙上等待對帳"),
        "accepted": accepted,
        "paper_order": order,
        "execution": execution,
    }


def apply_paper_intent(state: dict[str, Any], decision: dict[str, Any], lots: int) -> dict[str, Any]:
    """建立目標與待成交委託；相同 intent 不重下，既有委託不被覆蓋。"""
    work = deepcopy(state)
    execution = work.setdefault("execution", {})
    execution.setdefault("intents", {})
    execution.setdefault("receipts", {})
    action = str(decision.get("action") or "HOLD")

    def reject(reason: str) -> dict[str, Any]:
        execution["last_intent_accepted"] = False
        return paper_snapshot(work, accepted=False, reason=reason)

    if work.get("mode", "paper") != "paper":
        return reject("紙上委託僅接受紙上模式")
    if action == "HOLD":
        return paper_snapshot(work)
    if action not in {"ENTER_LONG", "ENTER_SHORT", "REDUCE", "EXIT"}:
        return reject("不支援的紙上委託動作")
    try:
        symbol = _identifier(work.get("symbol") or "TXF", "商品代碼")
        requested = 0 if action == "EXIT" else _integer(lots, "委託數量", positive=True)
        intent_id = _identifier(decision.get("intent_id") or uuid4().hex, "意圖識別碼")
        fingerprint = {"symbol": symbol, "action": action, "lots": requested}
        prior = execution["intents"].get(intent_id)
        if prior:
            if any(prior.get(key) != value for key, value in fingerprint.items()):
                return reject("意圖識別碼已用於不同委託")
            execution["last_intent_accepted"] = True
            return paper_snapshot(work, reason="紙上重複意圖已忽略，維持原委託與部位")
        order = work.get("paper_order") or {}
        if order.get("status") in ACTIVE_STATUSES:
            return reject("已有待成交紙上委託，請先完成對帳")
        pos = work.setdefault("positions", {})
        current = _integer(pos.get("account", 0), "帳戶部位")
        strategy = _integer(pos.get("strategy", 0), "策略部位")
        if strategy != current:
            return reject("策略與帳戶部位不一致，請先完成對帳")
        if current and order.get("symbol", symbol) != symbol:
            return reject("持倉商品與本次商品不同，請先完成對帳")
        if action.startswith("ENTER"):
            if current:
                return reject("已有未平倉部位，不可用進場意圖覆蓋")
            target = requested if action == "ENTER_LONG" else -requested
        else:
            if not current:
                return reject("目前沒有可減碼或平倉的已確認部位")
            if action == "REDUCE" and requested > abs(current):
                return reject("減碼數量不可超過已確認部位")
            target = 0 if action == "EXIT" else current - (requested if current > 0 else -requested)
        quantity = abs(target - current)
        stamp = _now()
        order = {
            "order_id": "paper-" + uuid4().hex,
            "intent_id": intent_id,
            "mode": "paper", "symbol": symbol, "action": action,
            "side": "BUY" if target > current else "SELL",
            "quantity": quantity, "initial_position": current, "target_position": target,
            "filled_quantity": 0, "remaining_quantity": quantity,
            "average_fill_price": None, "status": "pending",
            "created_at": stamp, "updated_at": stamp, "receipt_ids": [],
        }
        work["paper_order"] = order
        pos.update(ai_suggested=target, txt_target=target)
        execution["intents"][intent_id] = {**fingerprint, "order_id": order["order_id"]}
        execution.update({key: order[key] for key in ("order_id", "symbol", "quantity", "filled_quantity", "remaining_quantity", "target_position")})
        execution.update(last_intent_accepted=True, reason="紙上委託待成交，已確認部位尚未變更")
        return paper_snapshot(work)
    except ValueError as exc:
        return reject(str(exc))


def confirm_fill(state: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    """驗證單筆增量成交並回傳新狀態；相同 receipt 冪等，錯誤完全不改輸入。

    receipt 必填 receipt_id、order_id、symbol、quantity、price、filled_at 與
    source='paper'。quantity 為這一筆成交量，非累計量；filled_at 必須含時區。
    execution.receipts 與 execution.intents 必須與部位一起持久化。
    """
    if state.get("mode", "paper") != "paper":
        raise ValueError("紙上成交僅接受紙上模式")
    if not isinstance(receipt, dict) or receipt.get("source") != "paper":
        raise ValueError("成交回報必須明確標示紙上來源")
    canonical = {key: _identifier(receipt.get(key), label) for key, label in (
        ("receipt_id", "成交識別碼"), ("order_id", "委託識別碼"), ("symbol", "商品代碼"))}
    canonical["quantity"] = _integer(receipt.get("quantity"), "成交數量", positive=True)
    price = receipt.get("price")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        raise ValueError("成交價必須是有限正數")
    canonical["price"] = float(price)
    stamp = _timestamp(receipt.get("filled_at"), "成交")
    canonical.update(source="paper", filled_at=stamp.astimezone(timezone.utc).isoformat())
    for key in ("quote_source", "quote_as_of"):
        if key in receipt:
            canonical[key] = _identifier(receipt[key], "報價來源紀錄")
    work = deepcopy(state)
    execution = work.setdefault("execution", {})
    ledger = execution.setdefault("receipts", {})
    previous = ledger.get(canonical["receipt_id"])
    if previous is not None:
        if previous != canonical:
            raise ValueError("成交識別碼已用於不同回報")
        return paper_snapshot(work)
    order = work.get("paper_order") or {}
    if order.get("mode") != "paper" or order.get("order_id") != canonical["order_id"]:
        raise ValueError("成交回報找不到相符紙上委託")
    if order.get("symbol") != canonical["symbol"] or work.get("symbol", order["symbol"]) != canonical["symbol"]:
        raise ValueError("成交商品與委託或帳戶商品不一致")
    if order.get("status") not in ACTIVE_STATUSES:
        raise ValueError("委託已完成或不在可成交狀態")
    if stamp < _timestamp(order.get("created_at"), "委託"):
        raise ValueError("成交時間不可早於委託建立時間")
    quantity = _integer(order.get("quantity"), "原委託數量", positive=True)
    filled = _integer(order.get("filled_quantity"), "累計成交數量")
    remaining = _integer(order.get("remaining_quantity"), "剩餘委託數量", positive=True)
    initial = _integer(order.get("initial_position"), "原始部位")
    target = _integer(order.get("target_position"), "目標部位")
    if order.get("side") not in {"BUY", "SELL"}:
        raise ValueError("委託買賣方向無效")
    direction = 1 if order["side"] == "BUY" else -1
    if filled < 0 or filled + remaining != quantity or initial + direction * quantity != target:
        raise ValueError("已保存委託的數量或目標不一致")
    if canonical["quantity"] > remaining:
        raise ValueError("成交數量超過委託剩餘數量")
    pos = work.setdefault("positions", {})
    expected = initial + direction * filled
    if _integer(pos.get("account", 0), "帳戶部位") != expected or _integer(pos.get("strategy", 0), "策略部位") != expected:
        raise ValueError("已確認部位與累計成交不一致，無法套用回報")
    previous_price = order.get("average_fill_price")
    if filled and (isinstance(previous_price, bool) or not isinstance(previous_price, (int, float)) or not math.isfinite(previous_price) or previous_price <= 0):
        raise ValueError("已保存委託的平均成交價無效")
    total = filled + canonical["quantity"]
    average = ((float(previous_price) * filled if filled else 0) + canonical["price"] * canonical["quantity"]) / total
    if not math.isfinite(average):
        raise ValueError("平均成交價超出有限數值範圍")
    new_position = initial + direction * total
    pos.update(account=new_position, strategy=new_position)
    order.update(filled_quantity=total, remaining_quantity=quantity - total,
                 average_fill_price=average, status="confirmed" if total == quantity else "partial",
                 updated_at=max(_timestamp(order.get("updated_at"), "前次對帳"), stamp).astimezone(timezone.utc).isoformat())
    order.setdefault("receipt_ids", []).append(canonical["receipt_id"])
    ledger[canonical["receipt_id"]] = canonical
    execution.update({key: order[key] for key in ("order_id", "symbol", "quantity", "filled_quantity", "remaining_quantity", "target_position")})
    execution.update(last_receipt_id=canonical["receipt_id"], reason="紙上成交已對帳" if total == quantity else "紙上部分成交，剩餘委託待對帳")
    return paper_snapshot(work)


def cancel_paper_order(state: dict[str, Any], reason: str) -> dict[str, Any]:
    """明確取消未成交餘量並保留完整紀錄；已確認部位不受影響。"""
    work = deepcopy(state)
    order = work.get("paper_order") or {}
    if order.get("status") not in ACTIVE_STATUSES:
        return paper_snapshot(work)
    pos = work.get("positions") or {}
    current = _integer(pos.get("account", 0), "帳戶部位")
    order.update(status="cancelled", cancelled_quantity=order["remaining_quantity"],
                 remaining_quantity=0, cancelled_reason=reason, updated_at=_now())
    pos.update(ai_suggested=current, txt_target=current)
    execution = work.setdefault("execution", {})
    execution.setdefault("cancelled_orders", {})[order["order_id"]] = deepcopy(order)
    execution.update(remaining_quantity=0, target_position=current)
    return paper_snapshot(work, reason=reason)
