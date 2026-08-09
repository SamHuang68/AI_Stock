# -*- coding: utf-8 -*-
"""WaveDeck in-memory runtime state + simple persistence."""
from __future__ import annotations

import json
import threading
import time
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

TZ8 = timezone(timedelta(hours=8))
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STATE_PATH = DATA / "runtime_state.json"

VALID_STATES = ("Idle", "Arming", "InPosition", "Reducing", "Halted", "Flat")


def now_iso() -> str:
    return datetime.now(TZ8).strftime("%Y-%m-%d %H:%M:%S")


def _default_state() -> dict[str, Any]:
    return {
        "fsm": "Idle",
        "mode": "paper",  # paper | live
        "symbol": "TXF",
        "kill_switch": False,
        "style": 50,  # 35 / 50 / 65 / custom
        "no_overnight": {
            "enabled": True,
            "block_new_before_close_min": 15,
            "force_flat_time": "13:40",
            "note": "收盤前禁新單；指定時間強制平倉",
        },
        "positions": {
            "ai_suggested": 1,
            "txt_target": 1,
            "strategy": 1,
            "account": 1,
        },
        "account": {
            "yesterday_balance": 72312,
            "equity": 59888,
            "equity_change": -12424,
            "broker_api": "ok",
            "position_sync": "synced",
        },
        "ai": {
            "action": "HOLD",
            "action_label": "維持續抱",
            "confidence": 0.62,
            "bias_long": 0.60,
            "bias_short": 0.40,
            "event": "TIMED_MARKET_REVIEW",
            "summary": "既有多單仍受 MA20 與 +DI 支撐，尚未跌破短線區間低點；ADX 顯示趨勢未壞，續抱等待結構確認。",
            "invalidation": {"price": 45015, "side": "below"},
            "next_watch": ["失守短線結構再評估", "收盤前不留倉時窗"],
            "process": {
                "route": "heuristic→gate",
                "chase_risk": "medium",
                "gate": "PASS",
            },
            "updated_at": now_iso(),
        },
        "exec": {
            "last_ai_action": "維持續抱",
            "last_order_action": "多單進場",
            "price": 45020,
            "lots": 1,
        },
        "costs": {
            "session_usd": 0.0,
            "day_usd": 0.0,
            "month_usd": 0.0,
            "local_calls": 0,
            "cloud_calls": 0,
            "provider": "heuristic",
        },
        "transport": {
            "webhook": "ready",
            "tunnel": "named",
            "domain": "127.0.0.1:18433",
            "last_tv_event": "—",
            "last_webhook_status": "待命",
            "parse_errors": 0,
        },
        "lights": {
            "system": "run",
            "broker_api": "ok",
            "position_sync": "ok",
            "kill_switch": "off",
            "webhook": "ok",
            "openai_or_local": "ok",
            "email_monitor": "ok",
            "order_signal_file": "ok",
            "st_bridge": "idle",
            "risk_watchdog": "ok",
            "audit_db": "ok",
            "ui_push": "ok",
        },
        "st_overlay": {
            "aggressiveness": None,
            "delever": False,
            "note": "",
            "rotation": None,
            "spillover_prob": None,
            "leaders": [],
            "hot_stage": None,
            "chain_breadth": None,
            "chain_contig": None,
            "source": None,
            "score": None,
            "advRatio": None,
            "fail_safe": False,
            "fail_safe_reason": None,
        },
        "st_link": {
            "status": "unknown",
            "last_ok_at": None,
            "last_ping_at": None,
            "fail_count": 0,
            "overlay_at": None,
            "overlay_epoch": None,
            "fail_safe": False,
            "fail_safe_reason": "",
            "st_port": "http://127.0.0.1:18432",
        },
        "boot_at": now_iso(),
        "updated_at": now_iso(),
    }


class Runtime:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        DATA.mkdir(parents=True, exist_ok=True)
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        if STATE_PATH.is_file():
            try:
                raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
                base = _default_state()
                base.update(raw if isinstance(raw, dict) else {})
                return base
            except Exception:
                pass
        return _default_state()

    def save(self) -> None:
        with self._lock:
            self._state["updated_at"] = now_iso()
            tmp = STATE_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(STATE_PATH)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)

    def patch(self, **kwargs: Any) -> dict[str, Any]:
        with self._lock:
            for k, v in kwargs.items():
                if isinstance(v, dict) and isinstance(self._state.get(k), dict):
                    self._state[k].update(v)
                else:
                    self._state[k] = v
            self._state["updated_at"] = now_iso()
        self.save()
        return self.snapshot()

    def set_fsm(self, name: str) -> None:
        if name not in VALID_STATES:
            raise ValueError(f"invalid fsm: {name}")
        with self._lock:
            self._state["fsm"] = name
            self._state["updated_at"] = now_iso()
        self.save()

    def set_kill(self, on: bool) -> dict[str, Any]:
        with self._lock:
            self._state["kill_switch"] = bool(on)
            self._state["lights"]["kill_switch"] = "on" if on else "off"
            if on:
                self._state["fsm"] = "Halted"
                self._state["lights"]["system"] = "halt"
            else:
                if self._state["fsm"] == "Halted":
                    self._state["fsm"] = "Idle"
                self._state["lights"]["system"] = "run"
        self.save()
        return self.snapshot()


RUNTIME = Runtime()
