#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""寫入租約與寫入守衛（單一資料根階段 3a）。

legacy（現行兩套 runtime）：沒有任何程序取得租約，`assert_write_allowed` 立刻返回，
不讀、不寫、不檢查參數，行為與沒有這個模組時逐字相同。

租約只由明確呼叫 `bootstrap_runtime(data_root=...)` 取得（預定由階段 4 的啟動流程呼叫）；
匯入模組、解析路徑、繼承環境變數都不會取得。一旦取得，這個程序就進入「已綁定」狀態：
之後經過守衛的寫入必須 (1) 落在租約所屬的資料根之內、(2) 租約仍有效且由本程序持有，否則拒絕。
租約釋放後守衛仍保持已綁定狀態（拒絕所有寫入），不會退回 legacy 的放行。

「落在資料根之內」要同時成立於兩個落地位置：連結解開後的終點（直接寫入會落在這裡），以及
「解開後的父目錄＋檔名」（建立、改名、取代目錄項目會落在這裡，例如 `atomic_store` 在目標所在目錄建暫存檔再
`os.replace`——資料根外的符號連結即使指向資料根內的檔案，被取代的也是連結本身）。

`server/` 底下的模組有兩種載入方式（頂層 `import runtime_storage`、套件成員 `server.runtime_storage`），
同一個程序可能同時載入兩份。租約狀態與例外類別放在 `sys` 的登記簿，兩份共用，所以不論從哪一種匯入取得或釋放租約，
所有接了守衛的入口都看得到。

目前接了守衛的入口：`atomic_store` 的寫入與損毀復原、`datastore` 的 `init_db`／`upsert_bars`／
`merge_source_bars`。其他直接開 SQLite 的位置尚未接守衛，現況登記在
`tests/sqlite_write_guard_baseline.json`（只能降）；直接寫檔（`open(...,'w')`、`os.replace` 等）
也尚未涵蓋。已綁定狀態下需要另行決定的例外（憑證檔在程式目錄的 data/、%TEMP% 的 fast-ai 鎖、
%LOCALAPPDATA% 的 ETF 歷史目錄、閘道的存取控制檔）留待階段 4；階段 3a 的規則一律是「資料根之外拒絕」。
檢查與實際寫入之間沒有原子性（檢查通過後連結才被換掉不在防範範圍）。

只用標準庫；`daemon_lock` 在取得租約時才延遲匯入，使 legacy 路徑的匯入圖不多出任何相依。
"""
from __future__ import annotations

import atexit
import os
import sys
import threading
import types
from pathlib import Path

LOCK_NAME = 'writer'            # 租約檔：<資料根>/runtime_locks/writer.lock
LOCK_DIRNAME = 'runtime_locks'


class StorageOwnershipError(RuntimeError):
    """本程序不被允許寫入這個位置。"""


# 程序級登記簿（見模組說明）：先載入的那一份決定例外類別，後載入的沿用，才能用同一個類別接例外。
_state = sys.__dict__.setdefault('_st_runtime_storage', types.SimpleNamespace(
    lease=None, guard=threading.RLock(), error=StorageOwnershipError))
StorageOwnershipError = _state.error


def current_lease():
    """本程序目前的租約；沒有（legacy）就是 None。釋放後仍會回傳那個已關閉的租約。"""
    return _state.lease


def _absolute(path) -> str:
    """補成絕對路徑，但**不收縮** `..`：接上目前目錄就好，`..` 留給 `realpath` 依序處理。"""
    raw = os.fspath(path)
    return raw if os.path.isabs(raw) else os.path.join(os.getcwd(), raw)


def _canonical(path) -> str:
    """絕對、解開連結、依平台正規化大小寫的路徑字串；路徑可以還不存在。

    不能先 `abspath`：它純字串地收縮 `..`，但 POSIX 是先跟著目錄連結走、再處理 `..`，
    `<資料根內的連結>/../x` 實際落在「連結指向處的上一層」，不是「連結所在處的上一層」。
    `realpath` 依序處理每一段；Windows 的 `realpath` 會先正規化，與 Win32 以字串收縮 `..` 的語意一致。
    """
    return os.path.normcase(os.path.realpath(_absolute(path)))


def _destinations(path) -> tuple[str, str]:
    """這個寫入可能落地的兩個位置：連結解開後的終點，以及「解開後的父目錄＋檔名」。"""
    absolute = _absolute(path)
    target = _canonical(absolute)
    parent, name = os.path.split(absolute)
    if name in ('', os.curdir, os.pardir):      # 結尾是分隔符、`.` 或 `..`：沒有可被取代的目錄項目，落地位置就是終點
        return target, target
    return target, os.path.normcase(os.path.join(os.path.realpath(parent), name))


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
        with _state.guard:
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
    （拒絕自動建立空的資料根）。租約目錄與租約檔（含經由連結指到資料根之外的情形）必須在資料根之內，
    先驗證、再取鎖，所以被拒絕時不會在資料根之外建立任何東西。另一個程序已持有租約時拒絕，不等待。
    """
    root = Path(os.fspath(data_root))
    if not root.is_absolute():
        raise StorageOwnershipError('資料根必須是絕對路徑')
    if not root.is_dir():
        raise StorageOwnershipError('資料根不存在；拒絕自動建立空的資料根')
    canonical = _canonical(root)
    with _state.guard:
        lease = _state.lease
        if lease is not None:
            if not lease.closed and lease.pid == os.getpid() and lease.data_root == canonical:
                return lease
            raise StorageOwnershipError('本程序已綁定另一個資料根，或租約已釋放；一個程序只能綁定一次')
        lock_dir = root / LOCK_DIRNAME
        for candidate in (lock_dir, lock_dir / (LOCK_NAME + '.lock')):
            if not all(_inside(place, canonical) for place in _destinations(candidate)):
                raise StorageOwnershipError('租約目錄或租約檔經由連結指到資料根之外')
        # 這是取得租約之前唯一的寫入：建立 runtime_locks 與租約檔。
        handle = _daemon_lock().acquire_daemon_lock(LOCK_NAME, lock_dir=lock_dir)
        if handle is None:
            raise StorageOwnershipError('另一個程序持有此資料根的寫入租約')
        lease = _state.lease = WriterLease(canonical, handle, os.getpid())
        atexit.register(lease.close)
        return lease


def assert_write_allowed(path) -> None:
    """寫入 `path` 之前呼叫；不被允許就拋 `StorageOwnershipError`，必須在建立任何檔案或目錄之前。"""
    lease = _state.lease
    if lease is None:
        return                  # legacy：沒有租約，守衛不存在
    if lease.closed or lease.pid != os.getpid():
        raise StorageOwnershipError('寫入租約已釋放，或本程序是 fork 出來的子程序、沒有租約')
    places = _destinations(path)
    if not all(_inside(place, lease.data_root) for place in places):
        raise StorageOwnershipError(f'寫入位置在已綁定的資料根之外（含經由連結落到外面）：{path}')
    if lease.lock_file in places:
        raise StorageOwnershipError('租約檔由 bootstrap 管理，不可當成資料寫入')
