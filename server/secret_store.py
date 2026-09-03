#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OS-backed secret storage with an explicit restricted-file fallback."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
from typing import Any

try:
    from .atomic_store import atomic_write_bytes
except ImportError:  # direct server.py execution keeps server/ on sys.path
    from atomic_store import atomic_write_bytes


_DPAPI = b'STDPAPI1\x00'
_DPAPI_MACHINE = b'STDPAPIM1\x00'
_PLAIN = b'STPLAIN1\x00'
_EMPTY = b'STEMPTY1\x00'


class _Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def _blob(data: bytes) -> tuple[_Blob, Any]:
    buf = ctypes.create_string_buffer(data)
    return _Blob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))), buf


def _protect(data: bytes, *, machine: bool = False) -> bytes:
    if os.name != 'nt':
        raise OSError('DPAPI is only available on Windows')
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    protect = crypt32.CryptProtectData
    protect.argtypes = [
        ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob),
    ]
    protect.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    src, keep = _blob(data)
    out = _Blob()
    flags = 0x1 | (0x4 if machine else 0)  # UI_FORBIDDEN | optional LOCAL_MACHINE
    if not protect(ctypes.byref(src), 'Stock Terminal', None, None, None, flags, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)
        _ = keep


def _unprotect(data: bytes) -> bytes:
    if os.name != 'nt':
        raise OSError('DPAPI payload cannot be opened outside Windows')
    crypt32 = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    unprotect = crypt32.CryptUnprotectData
    unprotect.argtypes = [
        ctypes.POINTER(_Blob), ctypes.POINTER(wintypes.LPWSTR), ctypes.POINTER(_Blob),
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob),
    ]
    unprotect.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    src, keep = _blob(data)
    out = _Blob()
    if not unprotect(ctypes.byref(src), None, None, None, None, 0x1, ctypes.byref(out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        kernel32.LocalFree(out.pbData)
        _ = keep


def save_secret(path: str | os.PathLike[str], value: str) -> None:
    raw = str(value or '').encode('utf-8')
    if not raw:
        payload = _EMPTY
    elif os.name == 'nt':
        try:
            payload = _DPAPI + _protect(raw)
        except OSError:
            # Services and sandboxed launchers may not have the interactive
            # user's profile loaded.  DPAPI machine scope remains encrypted at
            # rest; the file is also written with private permissions.
            payload = _DPAPI_MACHINE + _protect(raw, machine=True)
    else:
        payload = _PLAIN + raw
    atomic_write_bytes(path, payload, backup=True, private=True)


def load_secret(path: str | os.PathLike[str]) -> str:
    target = Path(path)
    if not target.is_file():
        return ''
    raw = target.read_bytes()
    if raw.startswith(_EMPTY):
        return ''
    if raw.startswith(_DPAPI):
        return _unprotect(raw[len(_DPAPI):]).decode('utf-8')
    if raw.startswith(_DPAPI_MACHINE):
        return _unprotect(raw[len(_DPAPI_MACHINE):]).decode('utf-8')
    if raw.startswith(_PLAIN):
        return raw[len(_PLAIN):].decode('utf-8')
    # Legacy plaintext migration is handled by the caller so it can remove the
    # old path only after a verified new write.
    return raw.decode('utf-8-sig').strip()


def save_secret_json(path: str | os.PathLike[str], value: dict[str, Any]) -> None:
    save_secret(path, json.dumps(value, ensure_ascii=False, separators=(',', ':')))


def load_secret_json(path: str | os.PathLike[str]) -> dict[str, Any]:
    text = load_secret(path)
    if not text:
        return {}
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError('secret bundle must be an object')
    return value
