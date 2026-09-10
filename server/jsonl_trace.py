# -*- coding: utf-8 -*-
"""Bounded JSONL diagnostic writers for ThreadingHTTPServer.

All trace files share per-path locks so append + compaction cannot interleave
on Windows (WinError 32 / truncated JSON lines).
"""
from __future__ import annotations

import json
import os
import threading
from typing import Any, Dict

_META = threading.Lock()
_LOCKS: Dict[str, threading.Lock] = {}


def _lock_for(path: str) -> threading.Lock:
    key = os.path.abspath(path)
    with _META:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def append_jsonl(
    path: str,
    row: Dict[str, Any],
    *,
    max_bytes: int,
    tail_lines: int,
) -> None:
    """Append one JSON object as a line; compact to the last ``tail_lines`` if oversized."""
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    line = json.dumps(row, ensure_ascii=False, default=str) + '\n'
    with _lock_for(path):
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(line)
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        if size <= int(max_bytes) or int(tail_lines) <= 0:
            return
        with open(path, 'r', encoding='utf-8') as fh:
            tail = fh.readlines()[-int(tail_lines):]
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.writelines(tail)
        os.replace(tmp, path)
