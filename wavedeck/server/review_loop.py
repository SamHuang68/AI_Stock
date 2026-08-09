# -*- coding: utf-8 -*-
"""Timed market review while WaveDeck is running.

In-position reviews are faster so invalidation / HOLD can refresh without
waiting for the next TradingView webhook.
"""
from __future__ import annotations

import os
import threading
from typing import Optional

from .state import RUNTIME

# Flat / idle cadence
IDLE_SEC = float(os.environ.get("WD_REVIEW_IDLE_SEC", "180"))
# With open position (heuristic)
INPOS_SEC = float(os.environ.get("WD_REVIEW_INPOS_SEC", "90"))
# Paid / local LLM — slower to control cost
INPOS_LLM_SEC = float(os.environ.get("WD_REVIEW_INPOS_LLM_SEC", "180"))

_stop = threading.Event()
_thread: Optional[threading.Thread] = None


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
        except Exception as exc:
            try:
                import sys

                sys.stderr.write(f"[wavedeck] review_loop: {exc}\n")
            except Exception:
                pass
        wait = _interval_sec(RUNTIME.snapshot())
        if _stop.wait(wait):
            break


def start() -> None:
    global _thread
    if os.environ.get("WD_REVIEW_LOOP", "1") in ("0", "false", "off"):
        return
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(target=_loop, name="wd-review-loop", daemon=True)
    _thread.start()


def stop() -> None:
    _stop.set()
