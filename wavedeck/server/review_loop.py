# -*- coding: utf-8 -*-
"""Timed market review while WaveDeck is running.

In-position reviews are faster so invalidation / HOLD can refresh without
waiting for the next TradingView webhook.
"""
from __future__ import annotations

import os
import logging
import threading
from datetime import datetime
from typing import Optional

from .state import RUNTIME, TZ8

# Flat / idle cadence
IDLE_SEC = float(os.environ.get("WD_REVIEW_IDLE_SEC", "180"))
# With open position (heuristic)
INPOS_SEC = float(os.environ.get("WD_REVIEW_INPOS_SEC", "90"))
# Paid / local LLM — slower to control cost
INPOS_LLM_SEC = float(os.environ.get("WD_REVIEW_INPOS_LLM_SEC", "180"))

_stop = threading.Event()
_thread: Optional[threading.Thread] = None
_risk_thread: Optional[threading.Thread] = None
_logger = logging.getLogger(__name__)


def _interval_sec(state: dict) -> float:
    pos = state.get("positions") or {}
    try:
        lots = abs(int(pos.get("account") or pos.get("txt_target") or 0))
    except Exception:
        lots = 0
    provider = str((state.get("costs") or {}).get("provider") or "heuristic").lower()
    if lots > 0:
        if provider in ("openai", "ollama", "lmstudio", "local"):
            return max(30.0, INPOS_LLM_SEC)
        return max(30.0, INPOS_SEC)
    return max(60.0, IDLE_SEC)


def _tick() -> None:
    st = RUNTIME.snapshot()
    # 規則模式的持倉同步與截止風控由獨立監控執行，不向 AI 徵求開倉。
    if (st.get("strategy_execution") or {}).get("mode") == "rules":
        return
    if st.get("kill_switch") or st.get("fsm") == "Halted":
        return
    # Skip if lights say system stopped
    lights = st.get("lights") or {}
    if lights.get("system") in ("stop", "halt"):
        return
    from .engine import handle_signal

    handle_signal(
        {
            "event": "TIMED_MARKET_REVIEW",
            "source": "review_loop",
            "price": (st.get("exec") or {}).get("price"),
        }
    )


def _loop() -> None:
    # First wait a short boot grace so bridge / broker can settle
    if _stop.wait(8.0):
        return
    while not _stop.is_set():
        try:
            _tick()
        except Exception:
            _logger.exception("WaveDeck 定期檢視失敗")
        wait = _interval_sec(RUNTIME.snapshot())
        if _stop.wait(wait):
            break


def _risk_tick(now: datetime | None = None) -> None:
    from .engine import enforce_no_overnight

    enforce_no_overnight(now if now is not None else datetime.now(TZ8))


def _risk_loop() -> None:
    # 獨立於 AI 呼叫及 90／180 秒檢視節奏，啟動即檢查，其後每秒檢查。
    # 關閉一般檢視不影響風控；隔離測試或明確維護可另行關閉風控監控。
    failures = 0
    while not _stop.is_set():
        try:
            _risk_tick()
            failures = 0
        except Exception:
            failures += 1
            if failures == 1 or failures % 60 == 0:
                _logger.exception("WaveDeck 不留倉監控失敗，連續失敗次數：%s", failures)
        if _stop.wait(1.0):
            break


def start() -> None:
    global _thread, _risk_thread
    # stop 後若舊工作仍未返回，不清除停止旗標，避免舊執行緒復活。
    if _stop.is_set() and any(t and t.is_alive() for t in (_thread, _risk_thread)):
        return
    _stop.clear()
    if os.environ.get("WD_RISK_WATCHDOG", "1").lower() not in ("0", "false", "off"):
        if not _risk_thread or not _risk_thread.is_alive():
            _risk_thread = threading.Thread(target=_risk_loop, name="wd-risk-watchdog", daemon=True)
            _risk_thread.start()
    if os.environ.get("WD_REVIEW_LOOP", "1").lower() not in ("0", "false", "off"):
        if not _thread or not _thread.is_alive():
            _thread = threading.Thread(target=_loop, name="wd-review-loop", daemon=True)
            _thread.start()


def stop() -> None:
    _stop.set()
