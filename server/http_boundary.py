#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared HTTP request boundary for the local Stock Terminal server.

The server is intentionally small and stdlib-only, but every route still needs
the same length, UTF-8 and JSON guarantees.  Keep these checks outside domain
handlers so a new route cannot accidentally re-introduce an unbounded read.
"""
from __future__ import annotations

import json
import socket
import time
from typing import Any
from urllib.parse import urlparse


DEFAULT_JSON_LIMIT = 256 * 1024


class BodyReadError(ValueError):
    """A client request error with an HTTP status suitable for the boundary."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = int(status)


def content_length(handler: Any, *, max_bytes: int) -> int:
    raw = handler.headers.get('Content-Length')
    if raw in (None, ''):
        return 0
    try:
        length = int(raw)
    except (TypeError, ValueError) as exc:
        raise BodyReadError('invalid Content-Length', 400) from exc
    if length < 0:
        raise BodyReadError('invalid Content-Length', 400)
    if length > max_bytes:
        raise BodyReadError(f'body exceeds {max_bytes} bytes', 413)
    return length


def read_body(handler: Any, *, max_bytes: int = DEFAULT_JSON_LIMIT) -> bytes:
    length = content_length(handler, max_bytes=max_bytes)
    handler._body_headers = handler.headers
    handler._body_bytes_read = 0
    if not length:
        return b''
    data = handler.rfile.read(length)
    handler._body_bytes_read = len(data)
    if len(data) != length:
        raise BodyReadError('incomplete request body', 400)
    return data


def close_rejected_body(handler: Any, *, max_bytes: int = 64 * 1024,
                        seconds: float = 0.1) -> None:
    """拒絕後停止連線重用；在大小及總時間上限內丟棄未讀位元組。"""
    handler.close_connection = True
    headers = handler.headers
    lengths = headers.get_all('Content-Length') if hasattr(headers, 'get_all') else [headers.get('Content-Length')]
    remaining = max_bytes
    if not headers.get('Transfer-Encoding') and not lengths:
        remaining = 0
    elif not headers.get('Transfer-Encoding') and len(lengths or []) == 1:
        try:
            length = content_length(handler, max_bytes=max_bytes)
        except BodyReadError:
            # 無效或過大的長度不能作為讀取依據；只丟棄有界原始位元組。
            pass
        else:
            consumed = (getattr(handler, '_body_bytes_read', 0)
                        if getattr(handler, '_body_headers', None) is headers else 0)
            remaining = max(0, length - consumed)
    # 未知 framing 不解析、不推定完整本文，也不重用此連線。
    connection = getattr(handler, 'connection', None)
    if not remaining or connection is None:
        return
    deadline = time.monotonic() + seconds
    previous_timeout = connection.gettimeout()
    try:
        while remaining:
            budget = deadline - time.monotonic()
            if budget <= 0:
                break
            connection.settimeout(budget)
            chunk = handler.rfile.read1(min(remaining, 8192))
            if not chunk:
                break
            remaining -= len(chunk)
    except (socket.timeout, OSError):
        # 慢送／中斷只終止排空；此連線無論如何都不能再解析請求。
        pass
    finally:
        connection.settimeout(previous_timeout)


def read_json_body(
    handler: Any,
    *,
    max_bytes: int = DEFAULT_JSON_LIMIT,
    expected_type: type | tuple[type, ...] | None = dict,
    empty_value: Any = None,
) -> Any:
    content_type = str(handler.headers.get('Content-Type') or '').split(';', 1)[0].strip().lower()
    if content_type and content_type != 'application/json' and not content_type.endswith('+json'):
        raise BodyReadError('Content-Type must be application/json', 415)
    raw = read_body(handler, max_bytes=max_bytes)
    if not raw:
        value = {} if empty_value is None else empty_value
    else:
        try:
            value = json.loads(raw.decode('utf-8'))
        except UnicodeDecodeError as exc:
            raise BodyReadError('body must be valid UTF-8 JSON', 400) from exc
        except json.JSONDecodeError as exc:
            raise BodyReadError('body must be valid JSON', 400) from exc
    if expected_type is not None and not isinstance(value, expected_type):
        name = getattr(expected_type, '__name__', None) or 'accepted type'
        raise BodyReadError(f'JSON body must be {name}', 422)
    return value


def normalized_origin(value: str | None) -> str | None:
    """Return a strict scheme://host[:port] origin from Origin or Referer."""
    if not value:
        return None
    try:
        parsed = urlparse(str(value).strip())
        if parsed.scheme not in ('http', 'https') or not parsed.hostname:
            return None
        host = parsed.hostname.lower()
        if ':' in host and not host.startswith('['):
            host = f'[{host}]'
        port = f':{parsed.port}' if parsed.port is not None else ''
        return f'{parsed.scheme.lower()}://{host}{port}'
    except (TypeError, ValueError):
        return None


def is_same_local_origin(value: str | None, port: int) -> bool:
    origin = normalized_origin(value)
    return origin in {
        f'http://127.0.0.1:{int(port)}',
        f'http://localhost:{int(port)}',
        f'http://[::1]:{int(port)}',
    }
