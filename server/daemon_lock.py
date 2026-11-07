#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Cross-process file locks for in-process background daemons."""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import BinaryIO


ROOT = Path(__file__).resolve().parents[1]
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")


def default_lock_dir() -> Path:
    # 本檔也是發布 helper：scripts/private_web_release.py 以 runpy.run_path、scripts/local_release.py 以
    # spec_from_file_location 按檔案路徑載入，此時 server/ 不在 sys.path，旁邊只有標準函式庫。
    # 發布 helper 一律明示 lock_dir，所以 data_paths 不能在匯入時就要求（會讓發布工具無法啟動），延後到真的用到預設值才匯入。
    if __package__:
        from . import data_paths
    else:
        import data_paths
    return data_paths.data_path("runtime_locks", code_root=ROOT)


def __getattr__(name: str):
    # 保留既有的模組屬性 daemon_lock.DEFAULT_LOCK_DIR（legacy 路徑契約測試與 runtime_storage 都讀它）。
    if name == "DEFAULT_LOCK_DIR":
        return default_lock_dir()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def acquire_daemon_lock(
    name: str, *, lock_dir: Path | None = None
) -> BinaryIO | None:
    """Return an open locked handle, or None when another process owns it."""
    if not _SAFE_NAME.fullmatch(name):
        raise ValueError("invalid daemon lock name")
    directory = lock_dir or default_lock_dir()
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
