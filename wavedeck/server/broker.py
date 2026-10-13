# -*- coding: utf-8 -*-
"""Broker adapters — paper + 下單大師 TXT bridge."""
from __future__ import annotations

import re
import json
import hashlib
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import load_config
from .state import ROOT


def _txt_dir() -> Path:
    cfg = (load_config().get("broker") or {})
    rel = str(cfg.get("txt_dir") or "data/master")
    p = Path(rel)
    if not p.is_absolute():
        p = ROOT / p
    return p


def _file(name_key: str, default: str) -> Path:
    cfg = load_config().get("broker") or {}
    return _txt_dir() / str(cfg.get(name_key) or default)


def _parse_lots(text: str, symbol: str | None = None) -> int | None:
    """Accept plain int, or lines like 'TXF 1' / 'TXF=1'."""
    text = (text or "").strip()
    if not text:
        return None
    if re.fullmatch(r"[+-]?\d+", text):
        return int(text)
    values = []
    for line in text.splitlines():
        match = re.fullmatch(r"\s*([^\s=]+)\s*(?:=|\s)\s*([+-]?\d+)\s*", line)
        if match and (symbol is None or match[1].upper() == symbol.upper()):
            values.append(int(match[2]))
    return values[-1] if values else None


def read_txt_positions(symbol: str = "TXF") -> dict[str, Any]:
    out = {
        "txt_target": None,
        "strategy": None,
        "account": None,
        "files": {},
        "ok": True,
        "errors": [],
        "observations": {},
    }
    mapping = [
        ("txt_target", "target_file", "target_position.txt"),
        ("strategy", "strategy_file", "strategy_position.txt"),
        ("account", "account_file", "account_position.txt"),
    ]
    for key, cfg_key, default in mapping:
        fp = _file(cfg_key, default)
        out["files"][key] = str(fp)
        try:
            before = fp.stat()
            raw = fp.read_text(encoding="utf-8-sig")
            after = fp.stat()
            if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
                raise ValueError("部位檔正在更新，等待穩定讀回")
            stamp = after.st_mtime_ns
            demo = any(line.lstrip().startswith("# 示範資料") for line in raw.splitlines())
            lots = _parse_lots(raw, symbol)
            out["observations"][key] = {"mtime_ns": stamp, "sha256": hashlib.sha256(raw.encode()).hexdigest(), "sample": demo}
            if lots is None or demo:
                raise ValueError("示範資料或缺少指定商品的有效部位")
            out[key] = lots
        except (OSError, UnicodeError, ValueError) as exc:
            out["ok"] = False
            out["errors"].append(f"{fp.name}: {exc}")
    return out


def write_txt_target(lots: int, symbol: str = "TXF") -> Path:
    fp = _file("target_file", "target_position.txt")
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(f"{symbol} {int(lots)}\n", encoding="utf-8")
    return fp


def write_order_signal(action: str, lots: int, price: float, symbol: str = "TXF") -> Path:
    fp = _file("signal_file", "order_signal.txt")
    fp.parent.mkdir(parents=True, exist_ok=True)
    line = f"{now_line()} {symbol} {action} lots={lots} px={price}\n"
    with fp.open("a", encoding="utf-8") as f:
        f.write(line)
    return fp


def write_invalidation_txt(price: float, side: str = "below", symbol: str = "TXF") -> Path:
    """Side-channel for 下單大師／外部盯盤：失效價（軟停損參考）。"""
    fp = _txt_dir() / "invalidation.txt"
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(
        f"{symbol} {str(side or 'below')} {float(price):.0f}\n",
        encoding="utf-8",
    )
    return fp


def panic_flatten(state: dict[str, Any]) -> dict[str, Any]:
    """Kill-side flatten: target 0 + EXIT signal for 下單大師／紙上帳戶。"""
    symbol = str(state.get("symbol") or "TXF")
    price = float((state.get("exec") or {}).get("price") or 0)
    broker = get_broker()
    decision = {
        "action": "EXIT",
        "action_label": "急停全平",
        "confidence": 1.0,
        "process": {"gate": "PANIC", "gate_reasons": ["panic_flatten"]},
    }
    applied = broker.apply_intent(state, decision, 0)
    if broker.name == "paper":
        write_txt_target(0, symbol)
        write_order_signal("EXIT", 0, price, symbol)
    pos = dict(applied.get("positions") or state.get("positions") or {})
    pos["ai_suggested"] = 0
    pos["txt_target"] = 0
    return {
        "positions": pos,
        "execution": applied.get("execution", {}),
        "exec": {
            **dict(state.get("exec") or {}),
            "last_ai_action": "急停全平",
            "last_order_action": applied.get("order_action") or "急停全平→TXT",
            "lots": 0,
        },
        "lights": dict(applied.get("lights") or {}),
        "account": dict(applied.get("account") or {}),
    }


def now_line() -> str:
    from .state import now_iso
    return now_iso()


def execution_pending(execution: dict[str, Any]) -> bool:
    return bool(execution.get("order_id") and not execution.get("position_confirmed") and execution.get("status") != "rejected")


def _target(action: str, lots: int) -> int | None:
    if action == "ENTER_LONG":
        return max(1, int(lots))
    if action == "ENTER_SHORT":
        return -max(1, int(lots))
    return 0 if action in ("REDUCE", "EXIT") else None


def _receipt(state, decision, target):
    return {"order_id": uuid.uuid4().hex, "symbol": str(state.get("symbol") or "TXF"),
            "action": decision.get("action"), "target": target,
            "before_account": (state.get("positions") or {}).get("account"),
            "requested_at": now_line(), "requested_ns": time.time_ns(),
            "status": "sent", "evidence_kind": "command_sent", "position_confirmed": False,
            **{key: decision.get(key) for key in ("strategy_id", "signal_id")},
            "version": decision.get("version") or decision.get("strategy_version"),
            "strategy_version": decision.get("version") or decision.get("strategy_version")}


class PaperBroker:
    name = "paper"

    def sync_positions(self, state):
        # 紙上部位只由明確意圖改變，不把未成交目標當作帳戶。
        return {"positions": dict(state.get("positions") or {}), "execution": dict(state.get("execution") or {}),
                "lights": {"broker_api": "ok", "order_signal_file": "ok", "position_sync": "ok"},
                "account": {"broker_api": "paper", "position_sync": "simulated"}}

    def apply_intent(self, state, decision, lots):
        target = _target(decision.get("action"), lots)
        if target is None:
            return self.sync_positions(state)
        pos = dict(state.get("positions") or {})
        execution = _receipt(state, decision, target)
        execution.update(status="filled", evidence_kind="simulated", position_confirmed=True,
                         confirmed_account=target, confirmed_at=now_line())
        pos.update(ai_suggested=target, txt_target=target, strategy=target, account=target)
        return {"positions": pos, "execution": execution, "order_action": "紙上模擬成交"}


class TxtMasterBroker:
    """TXT 保留原格式；成交回報以委託識別、商品、目標與時序核對。"""
    name = "txt_master"

    def _tracking(self, symbol):
        safe = re.sub(r"[^A-Za-z0-9_-]", "_", symbol)
        return _txt_dir() / f"委託追蹤_{safe}.json"

    def _load(self, state):
        symbol = str(state.get("symbol") or "TXF")
        path = self._tracking(symbol)
        if path.exists():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(value, dict) and value.get("symbol") == symbol:
                    return value
                raise ValueError("委託追蹤格式或商品不符")
            except (OSError, UnicodeError, ValueError) as exc:
                return {"symbol": symbol, "status": "unknown", "error": str(exc), "tracking_invalid": True}
        execution = dict(state.get("execution") or {})
        return execution if execution.get("symbol") == symbol else {}

    def _save(self, execution):
        path = self._tracking(execution["symbol"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(execution, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def _confirm(self, execution, got):
        if not execution.get("order_id") or execution.get("status") == "rejected" or execution.get("position_confirmed"):
            return execution
        receipt = dict(execution)
        receipt["position_confirmed"] = False
        filled_ack = execution.get("status") == "filled" and execution.get("evidence_kind") == "order_ack"
        receipt["status"] = "filled" if filled_ack else "sent"
        receipt["evidence_kind"] = "order_ack" if filled_ack else "command_sent"
        cfg = load_config().get("broker") or {}
        ack = _file("ack_file", "成交回報.json")
        if ack.exists():
            try:
                report = json.loads(ack.read_text(encoding="utf-8-sig"))
                if not isinstance(report, dict):
                    raise ValueError("成交回報必須是物件")
                matches = all(report.get(key) == receipt.get(key) for key in ("order_id", "symbol", "target"))
                if matches:
                    updated = datetime.fromisoformat(str(report["updated_at"]).replace("Z", "+00:00"))
                    if updated.tzinfo is None:
                        raise ValueError("成交回報時間必須包含時區")
                    stamp = updated.timestamp() * 1e9
                    valid_time = receipt["requested_ns"] <= stamp <= time.time_ns() + 1e9
                    valid_time = valid_time and stamp >= receipt.get("ack_ns", 0)
                    status = report.get("status")
                    if valid_time and not report.get("simulated") and not report.get("sample") and status in ("sent", "partial", "filled", "rejected"):
                        receipt.update(status=status, evidence_kind="order_ack", ack_ns=stamp,
                                       acknowledgement=report, confirmed_at=report["updated_at"])
                        if status == "rejected":
                            return receipt
            except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
                receipt["ack_error"] = str(exc)
        observed = got["observations"].get("account") or {}
        account = got.get("account")
        fresh = (observed.get("mtime_ns", 0) > receipt["requested_ns"] and
                 observed != (receipt.get("baseline") or {}).get("account") and not observed.get("sample"))
        if account is None and receipt["evidence_kind"] != "order_ack":
            receipt.update(status="unknown", evidence_kind="account_missing")
        elif fresh and account is not None:
            before = receipt.get("before_account")
            target = receipt["target"]
            if account == target:
                receipt.update(position_confirmed=True, confirmed_account=account,
                               evidence_kind="order_ack" if receipt["evidence_kind"] == "order_ack" else "position_readback", confirmed_at=now_line())
            elif receipt["status"] != "filled" and before is not None and min(before, target) < account < max(before, target):
                receipt.update(status="partial", evidence_kind="position_readback", confirmed_account=account)
        if not receipt["position_confirmed"] and receipt["evidence_kind"] != "order_ack":
            age = (time.time_ns() - receipt["requested_ns"]) / 1e9
            if age > float(cfg.get("confirmation_timeout_sec", 30)) and account is not None:
                receipt.update(status="stale", evidence_kind="confirmation_timeout")
        return receipt

    def sync_positions(self, state, *, observed=None):
        symbol = str(state.get("symbol") or "TXF")
        got = observed if observed is not None else read_txt_positions(symbol)
        pos = dict(state.get("positions") or {})
        for key in ("txt_target", "strategy", "account"):
            if got[key] is not None:
                pos[key] = got[key]
        prior = self._load(state)
        execution = self._confirm(prior, got)
        if execution.get("order_id") and execution != prior:
            self._save(execution)
        synced = got["ok"] and got["txt_target"] == got["account"] == got["strategy"]
        return {"positions": pos, "execution": execution, "broker_meta": got,
                "lights": {"broker_api": "ok" if got["ok"] else "warn", "order_signal_file": "ok", "position_sync": "ok" if synced else "warn"},
                "account": {"broker_api": "txt_master", "position_sync": "position_confirmed" if synced else "pending"}}

    def apply_intent(self, state, decision, lots):
        observed = None
        if decision.get("action") in ("ENTER_LONG", "ENTER_SHORT"):
            observed = read_txt_positions(str(state.get("symbol") or "TXF"))
            if observed["account"] is None:
                reason = "帳戶部位無有效讀回，已阻擋新進場；請核對檔案、商品與示範標記"
                return {"positions": dict(state.get("positions") or {}), "execution": self._load(state),
                        "broker_meta": observed, "blocked": True, "reason": reason,
                        "order_action": reason, "lights": {"broker_api": "warn", "position_sync": "warn"},
                        "account": {"broker_api": "txt_master", "position_sync": "unknown"}}
        result = self.sync_positions(state, observed=observed)
        target = _target(decision.get("action"), lots)
        if target is None:
            result["order_action"] = decision.get("action_label") or "續抱"
            return result
        prior = result["execution"]
        current = result["positions"].get("account")
        signal = decision.get("signal_id")
        if prior.get("tracking_invalid"):
            result["order_action"] = "委託追蹤損壞，停止送單"
            return result
        duplicate = prior.get("order_id") and (signal and signal == prior.get("signal_id") or
                     target == prior.get("target") and prior.get("status") != "rejected" and
                     (execution_pending(prior) or current == target or
                      prior.get("status") == "filled" and not prior.get("position_confirmed")))
        if duplicate:
            result["order_action"] = "沿用委託，未重送"
            return result
        if execution_pending(prior) and target != 0:
            result["order_action"] = "先平倉確認，再以新訊號進場"
            target = 0
        requested_target = _target(decision.get("action"), lots)
        if current is not None and current * target < 0:
            target = 0
        if target == 0 and prior.get("target") == 0 and execution_pending(prior):
            result["order_action"] = "平倉委託待確認，未重送"
            return result
        receipt_state = {**state, "positions": result["positions"]}
        execution = _receipt(receipt_state, decision, target)
        execution["baseline"] = result["broker_meta"]["observations"]
        execution["requested_target"] = requested_target
        if target != requested_target:
            execution["action"] = "EXIT"
            execution["requires_new_signal"] = True
        # 先保留追蹤；若寫入中斷，未知狀態不自動重送。
        execution.update(status="unknown", evidence_kind="write_pending")
        self._save(execution)
        try:
            write_txt_target(target, execution["symbol"])
            write_order_signal(execution["action"], abs(target), float((state.get("exec") or {}).get("price") or 0), execution["symbol"])
        except OSError as exc:
            execution["error"] = str(exc)
            self._save(execution)
            result.update(execution=execution, order_action="送單寫入未完成，請核對")
            return result
        execution.update(status="sent", evidence_kind="command_sent")
        self._save(execution)
        result["positions"].update(ai_suggested=target, txt_target=target)
        result.update(execution=execution, order_action="目標已送出，等待確認")
        result["account"]["position_sync"] = "pending"
        result["lights"]["position_sync"] = "warn"
        return result


def get_broker(kind: str | None = None):
    cfg = load_config().get("broker") or {}
    want = (kind or cfg.get("kind") or "paper").lower()
    if want in ("txt", "txt_master", "master"):
        return TxtMasterBroker()
    return PaperBroker()


def ensure_master_seeds(symbol: str = "TXF") -> None:
    """明確建立示範檔；不得用於真實成交或帳戶同步證據。"""
    for key, default in (("target_file", "target_position.txt"), ("strategy_file", "strategy_position.txt"), ("account_file", "account_position.txt")):
        path = _file(key, default)
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"# 示範資料，非真實帳戶\n{symbol} 1\n", encoding="utf-8")
