#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Crash-safe local persistence with bounded recovery evidence."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from typing import Any


class StoreCorruptError(RuntimeError):
    pass


_guard = threading.Lock()
_locks: dict[str, threading.RLock] = {}
_status_lock = threading.Lock()
_status = {'writes': 0, 'recoveries': 0, 'errors': 0, 'lastError': None, 'lastRecovery': None}
_WINDOWS_REPLACE_ATTEMPTS = 7
_IS_WINDOWS = os.name == 'nt'


def _path_lock(path: Path) -> threading.RLock:
    key = str(path.resolve()).lower()
    with _guard:
        return _locks.setdefault(key, threading.RLock())


def _record(kind: str, detail: str | None = None) -> None:
    with _status_lock:
        if kind == 'write':
            _status['writes'] += 1
        elif kind == 'recovery':
            _status['recoveries'] += 1
            _status['lastRecovery'] = detail
        elif kind == 'error':
            _status['errors'] += 1
            _status['lastError'] = detail


def status() -> dict[str, Any]:
    with _status_lock:
        return dict(_status)


def _sync_parent(path: Path) -> None:
    if _IS_WINDOWS:
        return
    try:
        fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def _replace_with_retry(source: Path, target: Path) -> None:
    """Replace one file, tolerating short-lived Windows sharing violations.

    Antivirus/indexing and another process holding a read handle can briefly make
    an otherwise atomic ``os.replace`` fail with WinError 5 or 32.  Retrying only
    those Windows errors preserves fail-fast behavior for real filesystem faults.
    """
    attempts = _WINDOWS_REPLACE_ATTEMPTS if _IS_WINDOWS else 1
    for attempt in range(attempts):
        try:
            os.replace(source, target)
            return
        except PermissionError as exc:
            winerror = getattr(exc, 'winerror', None)
            if not _IS_WINDOWS or winerror not in {5, 32} or attempt + 1 >= attempts:
                raise
            time.sleep(0.005 * (2 ** attempt))


def _copy_backup(path: Path, backup_path: Path) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=f'.{backup_path.name}.', suffix='.tmp', dir=str(path.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, 'wb') as dst, path.open('rb') as src:
            shutil.copyfileobj(src, dst)
            dst.flush()
            os.fsync(dst.fileno())
        _replace_with_retry(temp, backup_path)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass


def atomic_write_bytes(
    path: str | os.PathLike[str],
    data: bytes,
    *,
    backup: bool = True,
    private: bool = False,
) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lock = _path_lock(target)
    with lock:
        fd, temp_name = tempfile.mkstemp(prefix=f'.{target.name}.', suffix='.tmp', dir=str(target.parent))
        temp = Path(temp_name)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(bytes(data))
                handle.flush()
                os.fsync(handle.fileno())
            if private:
                try:
                    os.chmod(temp, 0o600)
                except OSError:
                    pass
            if backup and target.is_file():
                _copy_backup(target, Path(str(target) + '.bak'))
            _replace_with_retry(temp, target)
            if private:
                try:
                    os.chmod(target, 0o600)
                except OSError:
                    pass
            _sync_parent(target)
            _record('write')
        except Exception as exc:
            _record('error', f'{target.name}: {type(exc).__name__}')
            raise
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass


def atomic_write_text(
    path: str | os.PathLike[str],
    text: str,
    *,
    backup: bool = True,
    private: bool = False,
) -> None:
    atomic_write_bytes(path, str(text).encode('utf-8'), backup=backup, private=private)


def atomic_write_json(
    path: str | os.PathLike[str],
    value: Any,
    *,
    backup: bool = True,
    private: bool = False,
    indent: int | None = 2,
) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=indent, allow_nan=False)
    atomic_write_text(path, text, backup=backup, private=private)


def _read_json(path: Path, expected_type: type | tuple[type, ...] | None) -> Any:
    value = json.loads(path.read_text(encoding='utf-8-sig'))
    if expected_type is not None and not isinstance(value, expected_type):
        name = getattr(expected_type, '__name__', 'expected type')
        raise ValueError(f'root must be {name}')
    return value


def load_json(
    path: str | os.PathLike[str],
    *,
    default: Any,
    expected_type: type | tuple[type, ...] | None = None,
) -> Any:
    target = Path(path)
    lock = _path_lock(target)
    with lock:
        if not target.exists():
            return copy.deepcopy(default)
        try:
            return _read_json(target, expected_type)
        except Exception as primary_error:
            backup = Path(str(target) + '.bak')
            try:
                recovered = _read_json(backup, expected_type)
            except Exception as backup_error:
                _record('error', f'{target.name}: corrupt primary and backup')
                raise StoreCorruptError(
                    f'{target.name} is corrupt; backup unavailable or invalid'
                ) from backup_error
            stamp = time.strftime('%Y%m%d-%H%M%S')
            quarantine = target.with_name(f'{target.name}.corrupt-{stamp}')
            suffix = 1
            while quarantine.exists():
                quarantine = target.with_name(f'{target.name}.corrupt-{stamp}-{suffix}')
                suffix += 1
            _replace_with_retry(target, quarantine)
            atomic_write_json(target, recovered, backup=False)
            _record('recovery', f'{target.name} <- backup; corrupt copy={quarantine.name}')
            return recovered
