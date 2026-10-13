# -*- coding: utf-8 -*-
"""以實際資料目錄的鎖檔限制服務單例，程序退出後由作業系統釋放。"""
from __future__ import annotations

import os
from pathlib import Path


def acquire(data: Path):
    # 解析連結與相對路徑；相同資料目錄必須競爭同一個鎖檔。
    directory = data.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    handle = (directory / "wavedeck.instance.lock").open("a+b")
    try:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            # Windows 可鎖定檔案尾端之外的一個位元組，無須改寫鎖檔。
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise RuntimeError(f"無法取得 WaveDeck 資料目錄單例鎖：{directory}；可能已有服務執行中。") from exc
    # 呼叫端必須持有檔案物件至程序退出；不刪鎖檔，避免建立不同 inode。
    return handle
