#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-process file locks for in-process background daemons."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import BinaryIO


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK_DIR = ROOT / "data" / "runtime_locks"
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def acquire_daemon_lock(
    name: str, *, lock_dir: Path | None = None
) -> BinaryIO | None:
    """Return an open locked handle, or None when another process owns it."""
    if not _SAFE_NAME.fullmatch(name):
        raise ValueError("invalid daemon lock name")
    directory = lock_dir or DEFAULT_LOCK_DIR
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory / f"{name}.lock").open("a+b")
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return handle
    except (OSError, BlockingIOError):
        handle.close()
        return None


def release_daemon_lock(handle: BinaryIO | None) -> None:
    """Release a handle explicitly; process exit also releases it."""
    if handle is None or handle.closed:
        return
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()
