# -*- coding: utf-8 -*-
"""Broker adapters — paper + 下單大師 TXT bridge."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .config import load_config
from .paper_orders import ACTIVE_STATUSES, apply_paper_intent, cancel_paper_order, confirm_fill, paper_snapshot
from .state import DATA, ROOT


def _txt_dir() -> Path:
    cfg = (load_config().get("broker") or {})
    rel = str(cfg.get("txt_dir") or "data/master")
    p = Path(rel)
    if not p.is_absolute():
        p = ROOT / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def _file(name_key: str, default: str) -> Path:
    cfg = load_config().get("broker") or {}
    return _txt_dir() / str(cfg.get(name_key) or default)


def _parse_lots(text: str, symbol: str | None = None) -> int | None:
    """Accept plain int, or lines like 'TXF 1' / 'TXF=1'."""
    text = (text or "").strip()
    if not text:
        return None
    # last integer in file wins
    if symbol:
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if symbol.upper() in line.upper():
                nums = re.findall(r"-?\d+", line)
                if nums:
                    return int(nums[-1])
    nums = re.findall(r"-?\d+", text)
    if not nums:
        return None
    return int(nums[-1])


def read_txt_positions(symbol: str = "TXF") -> dict[str, Any]:
    out = {
        "txt_target": None,
        "strategy": None,
        "account": None,
        "files": {},
        "ok": True,
        "errors": [],
    }
    mapping = [
        ("txt_target", "target_file", "target_position.txt"),
        ("strategy", "strategy_file", "strategy_position.txt"),
        ("account", "account_file", "account_position.txt"),
    ]
    for key, cfg_key, default in mapping:
        fp = _file(cfg_key, default)
        out["files"][key] = str(fp)
        if not fp.is_file():
            # seed demo files once
            fp.write_text(f"{symbol} 1\n", encoding="utf-8")
        try:
            lots = _parse_lots(fp.read_text(encoding="utf-8"), symbol)
            out[key] = 0 if lots is None else lots
        except Exception as exc:
            out["ok"] = False
            out["errors"].append(f"{fp.name}: {exc}")
    return out


def write_txt_target(lots: int, symbol: str = "TXF") -> Path:
    fp = _file("target_file", "target_position.txt")
    fp.write_text(f"{symbol} {int(lots)}\n", encoding="utf-8")
    return fp


def write_order_signal(action: str, lots: int, price: float, symbol: str = "TXF") -> Path:
    fp = _file("signal_file", "order_signal.txt")
    line = f"{now_line()} {symbol} {action} lots={lots} px={price}\n"
    with fp.open("a", encoding="utf-8") as f:
        f.write(line)
    return fp


def write_invalidation_txt(price: float, side: str = "below", symbol: str = "TXF") -> Path:
    """Side-channel for 下單大師／外部盯盤：失效價（軟停損參考）。"""
    fp = _txt_dir() / "invalidation.txt"
    fp.write_text(
        f"{symbol} {str(side or 'below')} {float(price):.0f}\n",
        encoding="utf-8",
    )
    return fp


def panic_flatten(state: dict[str, Any]) -> dict[str, Any]:
    """要求全平；紙上先取消未成交委託，再等待離線平倉回報。"""
    broker = PaperBroker() if state.get("mode", "paper") == "paper" else get_broker()
    work = state
    if isinstance(broker, PaperBroker):
        cancelled = cancel_paper_order(state, "紙上急停：未成交餘量已取消，已確認部位保持不變")
        work = {**state, **cancelled}
        if not (work.get("positions") or {}).get("account"):
            applied = paper_snapshot(work, reason="紙上急停：已確認部位為零，未成交委託已取消")
        else:
            applied = broker.apply_intent(work, {"action": "EXIT", "action_label": "急停全平"}, 0)
    else:
        applied = broker.apply_intent(state, {
            "action": "EXIT", "action_label": "急停全平", "confidence": 1.0,
            "process": {"gate": "PANIC", "gate_reasons": ["panic_flatten"]},
        }, 0)
    return {
        **applied,
        "exec": {
            **dict(state.get("exec") or {}),
            "last_ai_action": "急停全平",
            "last_order_action": applied.get("order_action") or "全平委託待對帳",
            "lots": abs(int((applied.get("positions") or {}).get("account") or 0)),
        },
    }


def now_line() -> str:
    from .state import now_iso
    return now_iso()


class PaperBroker:
    name = "paper"

    def sync_positions(self, state: dict[str, Any]) -> dict[str, Any]:
        from .data_contract import assess_quote
        from .paper_orders import _now

        order = state.get("paper_order") or {}
        if order.get("status") not in ACTIVE_STATUSES:
            return paper_snapshot(state)
        if (state.get("kill_switch") or state.get("fsm") == "Halted") and order.get("action") in {"ENTER_LONG", "ENTER_SHORT"}:
            return cancel_paper_order(state, "紙上急停：入場委託未成交餘量已取消")
        symbol = str(state.get("symbol") or "TXF")
        quote = assess_quote(state.get("quote"), symbol, mode="paper")
        if not quote.get("entry_allowed"):
            return paper_snapshot(state, accepted=False, reason="紙上委託待成交：尚無有效同商品報價")
        receipt = {
            "receipt_id": f"paper-fill:{order['order_id']}:{order['filled_quantity']}",
            "order_id": order["order_id"], "symbol": symbol,
            "quantity": order["remaining_quantity"], "price": quote["price"],
            "filled_at": _now(), "source": "paper",
            "quote_source": quote["source"], "quote_as_of": quote["as_of"],
        }
        try:
            return confirm_fill(state, receipt)
        except ValueError as exc:
            return paper_snapshot(state, accepted=False, reason=f"紙上成交對帳失敗：{exc}")

    def apply_intent(self, state: dict[str, Any], decision: dict[str, Any], lots: int) -> dict[str, Any]:
        return apply_paper_intent(state, decision, lots)


class TxtMasterBroker:
    """下單大師：寫入目標 TXT，讀回策略／帳戶 TXT 做四欄對帳。"""

    name = "txt_master"

    def sync_positions(self, state: dict[str, Any]) -> dict[str, Any]:
        symbol = str(state.get("symbol") or "TXF")
        got = read_txt_positions(symbol)
        pos = dict(state.get("positions") or {})
        if got["txt_target"] is not None:
            pos["txt_target"] = got["txt_target"]
        if got["strategy"] is not None:
            pos["strategy"] = got["strategy"]
        if got["account"] is not None:
            pos["account"] = got["account"]
        synced = (
            int(pos.get("txt_target") or 0) == int(pos.get("account") or 0)
            and int(pos.get("txt_target") or 0) == int(pos.get("strategy") or 0)
        )
        return {
            "positions": pos,
            "lights": {
                "broker_api": "ok" if got["ok"] else "warn",
                "order_signal_file": "ok",
                "position_sync": "ok" if synced else "warn",
            },
            "account": {
                "broker_api": "txt_master",
                "position_sync": "synced" if synced else "drift",
            },
            "broker_meta": got,
        }

    def apply_intent(self, state: dict[str, Any], decision: dict[str, Any], lots: int) -> dict[str, Any]:
        symbol = str(state.get("symbol") or "TXF")
        pos = dict(state.get("positions") or {})
        action = decision.get("action")
        price = float((state.get("exec") or {}).get("price") or 0)
        if action == "ENTER_LONG":
            target = max(1, lots)
            order = "多單進場→TXT"
        elif action == "ENTER_SHORT":
            target = -max(1, lots)
            order = "空單進場→TXT"
        elif action in ("REDUCE", "EXIT"):
            target = 0
            order = "平倉→TXT" if action == "EXIT" else "減碼→TXT"
        else:
            # HOLD: keep target, still sync readback
            sync = self.sync_positions(state)
            sync["order_action"] = decision.get("action_label") or "續抱"
            return sync

        pos["ai_suggested"] = target
        write_txt_target(target, symbol)
        write_order_signal(action, abs(int(target)), price, symbol)
        pos["txt_target"] = target
        # read back strategy/account (may lag until 下單大師 consumes)
        got = read_txt_positions(symbol)
        if got["strategy"] is not None:
            pos["strategy"] = got["strategy"]
        if got["account"] is not None:
            pos["account"] = got["account"]
        synced = int(pos.get("txt_target") or 0) == int(pos.get("account") or 0)
        return {
            "positions": pos,
            "order_action": order,
            "lights": {
                "broker_api": "ok",
                "order_signal_file": "ok",
                "position_sync": "ok" if synced else "warn",
            },
            "account": {
                "broker_api": "txt_master",
                "position_sync": "synced" if synced else "pending",
            },
        }


def get_broker(kind: str | None = None):
    cfg = load_config().get("broker") or {}
    want = (kind or cfg.get("kind") or "paper").lower()
    if want in ("txt", "txt_master", "master"):
        return TxtMasterBroker()
    return PaperBroker()


def ensure_master_seeds(symbol: str = "TXF") -> None:
    """Create sample TXT files so live-txt mode is demonstrable."""
    read_txt_positions(symbol)
