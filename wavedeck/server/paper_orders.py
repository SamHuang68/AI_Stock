# -*- coding: utf-8 -*-
"""紙上委託與成交收據（WD P0 第 4 片，改寫自 codex/wavedeck-paper-p0 的 paper_orders）。

純函式：不讀寫檔案、不呼叫券商，輸入狀態不被修改，錯誤時不留下半套結果。
狀態放在 state["paper_book"]：
    order     最近一筆委託（pending／partial／confirmed／cancelled）
    receipts  成交收據，receipt_id → 收據。冪等：同 id 同內容重放不重複套用，同 id 不同內容拒絕
    intents   已受理的意圖，intent_key(策略與訊號識別) → {symbol, action, target, order_id}

與分支版的差異（依 main 現行契約）：
- 目標部位由 broker._target 決定（減碼減半、反手），這裡只把「現有部位→目標部位」變成委託與收據；
  已有部位時的進場意圖不拒絕（main 的紙上券商一向以絕對目標覆寫，加碼與反手都靠它）。
- 成交價可未知（price_unknown）：沿用 WD-07，缺價時部位照記、損益標為未知，權益回報未知而不是推估。
- 紙上以帳戶部位為準：開委託時把策略部位對齊帳戶，不因兩者不同而拒單。
- 是否為紙上由 get_broker() 決定，這裡不看 state["mode"]。
- 收據與意圖各只留最近 MAX_HISTORY 筆，避免狀態檔與 /api/state 無限成長；更舊的意圖不再有冪等保護。
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import json
import math
from typing import Any
from uuid import uuid4

ACTIVE_STATUSES = {"pending", "partial"}
MAX_HISTORY = 50
_ACTIONS = {"ENTER_LONG", "ENTER_SHORT", "REDUCE", "EXIT"}
_BASIS_KEYS = ("price_basis", "quote_source", "quote_as_of")


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


def intent_key(decision: dict[str, Any]) -> str:
    """意圖的冪等鍵：(strategy_id, signal_id)，與 策略契約.claim 的去重範圍一致。

    兩個策略可以各自使用同一個 signal_id（啟用別的策略不會清掉 paper_book），不能互相當成重複。
    沒有 signal_id 的意圖（裁量模式）每次產生新的識別碼，等於不做去重。"""
    signal_id = _identifier(decision.get("signal_id") or uuid4().hex, "意圖識別碼")
    strategy_id = decision.get("strategy_id")
    return json.dumps([strategy_id if isinstance(strategy_id, str) else "", signal_id], ensure_ascii=False)


def _book(state: dict[str, Any]) -> dict[str, Any]:
    raw = state.get("paper_book")
    book = deepcopy(raw) if isinstance(raw, dict) else {}
    book.setdefault("order", None)
    book.setdefault("receipts", {})
    book.setdefault("intents", {})
    if not isinstance(book["receipts"], dict) or not isinstance(book["intents"], dict):
        raise ValueError("紙上帳簿格式不明")
    return book


def _trim(table: dict[str, Any]) -> None:
    while len(table) > MAX_HISTORY:
        table.pop(next(iter(table)))


def _cancel(book: dict[str, Any], positions: dict[str, Any], reason: str) -> None:
    """就地取消未成交餘量；已成交的部位不受影響，目標回到目前帳戶部位。"""
    order = book["order"]
    current = _integer(positions.get("account", 0) or 0, "帳戶部位")
    order.update(status="cancelled", cancelled_quantity=order["remaining_quantity"],
                 remaining_quantity=0, cancelled_reason=reason, updated_at=_now())
    positions.update(ai_suggested=current, txt_target=current)


def snapshot(state: dict[str, Any]) -> dict[str, Any]:
    """目前的 positions／paper_book 獨立副本（帳簿缺漏時補成空帳簿），供呼叫端在副本上繼續操作。"""
    book = _book(state)
    return {"positions": deepcopy(state.get("positions") or {}), "paper_book": book, "order": book["order"]}


def cancel_order(state: dict[str, Any], reason: str) -> dict[str, Any]:
    """明確取消未成交餘量並保留完整紀錄；沒有進行中的委託就原樣回傳。"""
    out = snapshot(state)
    if (out["order"] or {}).get("status") in ACTIVE_STATUSES:
        _cancel(out["paper_book"], out["positions"], reason)
    return out


def submit(state: dict[str, Any], decision: dict[str, Any], target: int) -> dict[str, Any]:
    """依目標部位受理一筆紙上意圖，回傳 accepted／reason／order／duplicate／positions／paper_book。

    accepted=False 時其餘欄位是原狀態，reason 說明原因。重複的意圖（同 signal_id、同內容）與已是
    目標部位的意圖都不開新委託（order 為 None）；前者 duplicate=True，部位與帳簿完全不動。
    pending 不更動已確認的帳戶部位，只有 confirm_fill 會改。"""
    original = deepcopy(state.get("positions") or {})

    def reject(reason: str) -> dict[str, Any]:
        try:
            book = _book(state)
        except ValueError:
            book = {"order": None, "receipts": {}, "intents": {}}
        return {"accepted": False, "reason": reason, "order": None, "duplicate": False,
                "positions": original, "paper_book": book}

    action = str(decision.get("action") or "")
    if action not in _ACTIONS:
        return reject("不支援的紙上委託動作")
    try:
        symbol = _identifier(state.get("symbol") or "TXF", "商品代碼")
        intent_id = intent_key(decision)
        target = _integer(target, "目標部位")
        book = _book(state)
        positions = deepcopy(original)
        current = _integer(positions.get("account", 0) or 0, "帳戶部位")
        fingerprint = {"symbol": symbol, "action": action, "target": target}
        prior = book["intents"].get(intent_id)
        if prior is not None:
            if any(prior.get(key) != value for key, value in fingerprint.items()):
                return reject("意圖識別碼已用於不同委託")
            return {"accepted": True, "reason": "紙上重複意圖已忽略，維持原委託與部位", "order": None,
                    "duplicate": True, "positions": original, "paper_book": book}
        if (book["order"] or {}).get("status") in ACTIVE_STATUSES:
            if action != "EXIT":
                return reject("已有待成交紙上委託，請先完成對帳")
            _cancel(book, positions, "平倉意圖：未成交餘量已取消")   # 降低風險的意圖不被舊委託擋住
        quantity = abs(target - current)
        if quantity == 0:
            positions.update(ai_suggested=target, txt_target=target, strategy=target, account=target)
            book["intents"][intent_id] = {**fingerprint, "order_id": None}
            _trim(book["intents"])
            return {"accepted": True, "reason": "已是目標部位，未建立委託", "order": None,
                    "duplicate": False, "positions": positions, "paper_book": book}
        stamp = _now()
        order = {
            "order_id": "paper-" + uuid4().hex, "intent_id": intent_id, "symbol": symbol, "action": action,
            "side": "BUY" if target > current else "SELL", "quantity": quantity,
            "initial_position": current, "target_position": target,
            "filled_quantity": 0, "remaining_quantity": quantity,
            "average_fill_price": None, "price_unknown": False, "status": "pending",
            "cancelled_quantity": 0, "cancelled_reason": None,
            "created_at": stamp, "updated_at": stamp, "receipt_ids": [],
        }
        book["order"] = order
        book["intents"][intent_id] = {**fingerprint, "order_id": order["order_id"]}
        _trim(book["intents"])
        positions.update(ai_suggested=target, txt_target=target, strategy=current)
        return {"accepted": True, "reason": "紙上委託待成交，已確認部位尚未變更", "order": order,
                "duplicate": False, "positions": positions, "paper_book": book}
    except ValueError as exc:
        return reject(str(exc))


def confirm_fill(state: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    """驗證單筆增量成交並回傳新的 positions／paper_book；相同收據冪等，錯誤時 ValueError 且輸入不變。

    receipt 必填 receipt_id、order_id、symbol、quantity、price、filled_at 與 source='paper'。
    quantity 是這一筆的成交量，不是累計量；filled_at 必須含時區。價格未知時改帶 price_unknown=True
    且不帶 price。可選的 price_basis、quote_source、quote_as_of 記錄成交價的出處。"""
    if not isinstance(receipt, dict) or receipt.get("source") != "paper":
        raise ValueError("成交回報必須明確標示紙上來源")
    canonical = {key: _identifier(receipt.get(key), label) for key, label in (
        ("receipt_id", "成交識別碼"), ("order_id", "委託識別碼"), ("symbol", "商品代碼"))}
    canonical["quantity"] = _integer(receipt.get("quantity"), "成交數量", positive=True)
    unknown = receipt.get("price_unknown") is True
    price = receipt.get("price")
    if unknown:
        if price is not None:
            raise ValueError("價格未知的成交回報不可同時帶價格")
        canonical.update(price=None, price_unknown=True)
    else:
        if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
            raise ValueError("成交價必須是有限正數")
        canonical["price"] = float(price)
    stamp = _timestamp(receipt.get("filled_at"), "成交")
    canonical.update(source="paper", filled_at=stamp.astimezone(timezone.utc).isoformat())
    for key in _BASIS_KEYS:
        if receipt.get(key) is not None:
            canonical[key] = _identifier(receipt[key], "價格出處紀錄")
    book = _book(state)
    positions = deepcopy(state.get("positions") or {})
    previous = book["receipts"].get(canonical["receipt_id"])
    if previous is not None:
        if previous != canonical:
            raise ValueError("成交識別碼已用於不同回報")
        return {"positions": positions, "paper_book": book, "order": book["order"]}
    order = book["order"] or {}
    if order.get("order_id") != canonical["order_id"]:
        raise ValueError("成交回報找不到相符紙上委託")
    if order.get("symbol") != canonical["symbol"] or state.get("symbol", order["symbol"]) != canonical["symbol"]:
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
    if _integer(positions.get("account", 0) or 0, "帳戶部位") != initial + direction * filled:
        raise ValueError("已確認部位與累計成交不一致，無法套用回報")
    total = filled + canonical["quantity"]
    if unknown or order.get("price_unknown"):
        average = None
    else:
        previous_price = order.get("average_fill_price")
        if filled and (isinstance(previous_price, bool) or not isinstance(previous_price, (int, float))
                       or not math.isfinite(previous_price) or previous_price <= 0):
            raise ValueError("已保存委託的平均成交價無效")
        average = ((float(previous_price) * filled if filled else 0) + canonical["price"] * canonical["quantity"]) / total
        if not math.isfinite(average):
            raise ValueError("平均成交價超出有限數值範圍")
    new_position = initial + direction * total
    positions.update(account=new_position, strategy=new_position)
    order.update(filled_quantity=total, remaining_quantity=quantity - total, average_fill_price=average,
                 price_unknown=bool(unknown or order.get("price_unknown")),
                 status="confirmed" if total == quantity else "partial",
                 updated_at=max(_timestamp(order.get("updated_at"), "前次對帳"), stamp).astimezone(timezone.utc).isoformat())
    order["receipt_ids"].append(canonical["receipt_id"])
    book["receipts"][canonical["receipt_id"]] = canonical
    _trim(book["receipts"])
    return {"positions": positions, "paper_book": book, "order": order}
