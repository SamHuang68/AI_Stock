# -*- coding: utf-8 -*-
"""Shared local LLM priority gate (WD = P1, ST Pulse = deferrable).

File-lock style coordination under data/llm_gate.json so ST (:18432) and
WaveDeck (:18433) on the same machine do not stampede one GPU/LM instance.
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = Path(os.environ.get('LLM_GATE_PATH') or (ROOT / 'data' / 'llm_gate.json'))

_lock = threading.RLock()

# WD holds up to this long; ST waits briefly then soft-defers
DEFAULT_TTL_SEC = 90.0
ST_WAIT_SEC = 2.0


def _now() -> float:
    return time.time()


def _read() -> dict[str, Any]:
    if not GATE_PATH.is_file():
        return {}
    try:
        raw = json.loads(GATE_PATH.read_text(encoding='utf-8'))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _write(obj: dict[str, Any]) -> None:
    try:
        GATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = GATE_PATH.with_suffix('.tmp')
        tmp.write_text(json.dumps(obj, ensure_ascii=False), encoding='utf-8')
        tmp.replace(GATE_PATH)
    except Exception:
        pass


def status() -> dict[str, Any]:
    with _lock:
        g = _read()
    until = float(g.get('until') or 0)
    owner = g.get('owner')
    held = bool(owner and until > _now())
    return {
        'ok': True,
        'held': held,
        'owner': owner if held else None,
        'until': until if held else None,
        'remaining_sec': round(max(0.0, until - _now()), 1) if held else 0,
        'path': str(GATE_PATH),
    }


def acquire(owner: str, ttl_sec: float = DEFAULT_TTL_SEC) -> bool:
    """Acquire gate. WD may preempt ST; ST never preempts WD."""
    owner = str(owner or 'st')
    ttl = max(5.0, float(ttl_sec))
    with _lock:
        g = _read()
        until = float(g.get('until') or 0)
        cur = g.get('owner')
        now = _now()
        if cur and until > now:
            if cur == owner:
                _write({'owner': owner, 'until': now + ttl, 'updated_at': now})
                return True
            # WD preempts ST
            if owner == 'wd' and cur == 'st':
                _write({'owner': 'wd', 'until': now + ttl, 'updated_at': now, 'preempted': 'st'})
                return True
            return False
        _write({'owner': owner, 'until': now + ttl, 'updated_at': now})
        return True


def release(owner: str) -> None:
    with _lock:
        g = _read()
        if g.get('owner') == owner:
            _write({'owner': None, 'until': 0, 'updated_at': _now()})


def wait_or_defer(owner: str, wait_sec: float = ST_WAIT_SEC, ttl_sec: float = DEFAULT_TTL_SEC) -> bool:
    """Try acquire; ST waits briefly for WD to finish. Returns False = defer."""
    deadline = _now() + max(0.0, float(wait_sec))
    while True:
        if acquire(owner, ttl_sec=ttl_sec):
            return True
        if _now() >= deadline:
            return False
        time.sleep(0.15)


def wd_busy() -> bool:
    s = status()
    return bool(s.get('held') and s.get('owner') == 'wd')
