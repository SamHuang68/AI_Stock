#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""寫入租約與寫入守衛（單一資料根階段 3a）。

legacy（現行兩套 runtime）：沒有任何程序取得租約，`assert_write_allowed` 立刻返回，
不讀、不寫、不檢查參數，行為與沒有這個模組時逐字相同。

租約只由明確呼叫 `bootstrap_runtime(data_root=...)` 取得（預定由階段 4 的啟動流程呼叫）；
匯入模組、解析路徑、繼承環境變數都不會取得。一旦取得，這個程序就進入「已綁定」狀態：
之後經過守衛的寫入必須 (1) 落在租約所屬的資料根之內、(2) 租約仍有效且由本程序持有，否則拒絕。
租約釋放後守衛仍保持已綁定狀態（拒絕所有寫入），不會退回 legacy 的放行。

目前接了守衛的入口：`atomic_store` 的寫入與損毀復原、`datastore` 的 `init_db`／`upsert_bars`／
`merge_source_bars`。其他直接開 SQLite 的位置尚未接守衛，現況登記在
`tests/sqlite_write_guard_baseline.json`（只能降）；直接寫檔（`open(...,'w')`、`os.replace` 等）
也尚未涵蓋。已綁定狀態下需要另行決定的例外（憑證檔在程式目錄的 data/、%TEMP% 的 fast-ai 鎖、
%LOCALAPPDATA% 的 ETF 歷史目錄、閘道的存取控制檔）留待階段 4；階段 3a 的規則一律是「資料根之外拒絕」。

只用標準庫；`daemon_lock` 在取得租約時才延遲匯入，使 legacy 路徑的匯入圖不多出任何相依。
"""
from __future__ import annotations

import atexit
import os
import threading
from pathlib import Path

LOCK_NAME = 'writer'            # 租約檔：<資料根>/runtime_locks/writer.lock
LOCK_DIRNAME = 'runtime_locks'


class StorageOwnershipError(RuntimeError):
    """本程序不被允許寫入這個位置。"""


_guard = threading.RLock()
_lease: 'WriterLease | None' = None


def _canonical(path) -> str:
    """絕對、解開連結、依平台正規化大小寫的路徑字串；路徑可以還不存在。"""
    return os.path.normcase(os.path.realpath(os.path.abspath(os.fspath(path))))


def _inside(child: str, parent: str) -> bool:
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:          # 不同磁碟機
        return False


def _daemon_lock():
    if __package__:
        from . import daemon_lock
    else:
        import daemon_lock
    return daemon_lock


class WriterLease:
    """一個資料根的寫入租約：持有 OS 位元組鎖直到 `close()` 或程序結束。"""

    def __init__(self, data_root: str, handle, pid: int):
        self.data_root = data_root
        self.lock_file = _canonical(os.path.join(data_root, LOCK_DIRNAME, LOCK_NAME + '.lock'))
        self.pid = pid
        self._handle = handle
        self.closed = False

    def close(self) -> None:
        with _guard:
            if self.closed:
                return
            self.closed = True
            handle, self._handle = self._handle, None
            if self.pid == os.getpid():
                _daemon_lock().release_daemon_lock(handle)
            elif handle is not None:
                # fork 出來的子程序繼承的描述子與父程序共用同一把鎖：只關閉，不能解鎖。
                handle.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def bootstrap_runtime(*, data_root) -> WriterLease:
    """取得 `data_root` 的寫入租約，之後本程序的守衛進入已綁定狀態。

    一個程序只能綁定一個資料根；同一資料根重複呼叫回傳既有租約。資料根必須是已存在的絕對路徑
    （拒絕自動建立空的資料根）。另一個程序已持有租約時拒絕，不等待。
    """
    global _lease
    root = Path(os.fspath(data_root))
    if not root.is_absolute():
        raise StorageOwnershipError('資料根必須是絕對路徑')
    if not root.is_dir():
        raise StorageOwnershipError('資料根不存在；拒絕自動建立空的資料根')
    canonical = _canonical(root)
    with _guard:
        if _lease is not None:
            if not _lease.closed and _lease.pid == os.getpid() and _lease.data_root == canonical:
                return _lease
            raise StorageOwnershipError('本程序已綁定另一個資料根，或租約已釋放；一個程序只能綁定一次')
        # 這是取得租約之前唯一的寫入：建立 runtime_locks 與租約檔。
        handle = _daemon_lock().acquire_daemon_lock(LOCK_NAME, lock_dir=root / LOCK_DIRNAME)
        if handle is None:
            raise StorageOwnershipError('另一個程序持有此資料根的寫入租約')
        _lease = WriterLease(canonical, handle, os.getpid())
        atexit.register(_lease.close)
        return _lease


def assert_write_allowed(path) -> None:
    """寫入 `path` 之前呼叫；不被允許就拋 `StorageOwnershipError`，必須在建立任何檔案或目錄之前。"""
    lease = _lease
    if lease is None:
        return                  # legacy：沒有租約，守衛不存在
    if lease.closed or lease.pid != os.getpid():
        raise StorageOwnershipError('寫入租約已釋放，或本程序是 fork 出來的子程序、沒有租約')
    target = _canonical(path)
    if not _inside(target, lease.data_root):
        raise StorageOwnershipError(f'寫入位置在已綁定的資料根之外：{path}')
    if target == lease.lock_file:
        raise StorageOwnershipError('租約檔由 bootstrap 管理，不可當成資料寫入')
