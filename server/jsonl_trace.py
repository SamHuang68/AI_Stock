# -*- coding: utf-8 -*-
"""Bounded JSONL diagnostic writers for ThreadingHTTPServer.

All trace files share per-path locks so append + compaction cannot interleave
on Windows (WinError 32 / truncated JSON lines).
"""
from __future__ import annotations

import json
import os
import threading
from collections import deque
from pathlib import Path
from typing import Any, Dict
from atomic_store import _replace_with_retry
from log_once import log_once

_META = threading.Lock()
_LOCKS: Dict[str, threading.Lock] = {}


def _lock_for(path: str) -> threading.Lock:
    key = os.path.normcase(os.path.realpath(path))
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
        with open(path, 'ab+') as fh:
            # 程序中斷可能留下半個字元／半行；新紀錄必須從獨立一行開始。
            if fh.tell():
                fh.seek(-1, os.SEEK_END)
                if fh.read(1) != b'\n':
                    fh.write(b'\n')
            fh.write(line.encode('utf-8'))
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        if size <= int(max_bytes) or int(tail_lines) <= 0:
            return
        tail = deque(maxlen=int(tail_lines))
        damaged = 0
        with open(path, 'rb') as fh:
            for raw in fh:
                try:
                    text = raw.decode('utf-8')
                    json.loads(text)
                except (UnicodeError, json.JSONDecodeError):
                    damaged += 1
                    continue
                # 二進位讀取會保留既有 CRLF；統一成單一 LF，避免重複壓縮累加 CR。
                tail.append(text.rstrip('\r\n') + '\n')
        if damaged:
            log_once('trace-recovery:' + os.path.basename(path),
                     f'診斷紀錄含 {damaged} 筆損毀行；壓縮時保留完整 JSON 紀錄')
        tmp = path + '.tmp'
        with open(tmp, 'w', encoding='utf-8', newline='\n') as fh:
            fh.writelines(tail)
        _replace_with_retry(Path(tmp), Path(path))
