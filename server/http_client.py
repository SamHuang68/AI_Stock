# -*- coding: utf-8 -*-
"""http_client — 統一外呼 Client（連線池／Keep-Alive／timeout／指數退避）

stdlib only（http.client）。目的：
  - 複用同 host 的 TCP／TLS，降低 Windows WinError 10053／TIME_WAIT 堆積
  - 統一 timeout、Retry（暫態錯誤＋ 408/429/5xx）
  - 給 server.py／macro_track／chip_api 等共用，避免各自裸 urlopen

公開 API（模組層快捷函式走預設單例）：
  fetch_bytes / fetch_text / fetch_json / request
"""
from __future__ import annotations

import http.client
import json
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
from typing import Any, Dict, List, Mapping, Optional, Tuple


DEFAULT_TIMEOUT = 15.0
DEFAULT_RETRIES = 1
MAX_POOL_PER_HOST = 8
IDLE_TTL_SEC = 45.0
RETRY_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})

# Windows：連線被本機／對端中止（常見於密集短連線）
_WIN_TRANSIENT = frozenset({10053, 10054, 10060, 10065})


class HttpError(Exception):
    """統一外呼失敗。"""

    def __init__(
        self,
        message: str,
        *,
        status: Optional[int] = None,
        url: Optional[str] = None,
        cause: Optional[BaseException] = None,
    ):
        super().__init__(message)
        self.status = status
        self.url = url
        self.cause = cause


class HttpResponse:
    __slots__ = ('status', 'headers', 'body', 'url')

    def __init__(self, status: int, headers: Mapping[str, str], body: bytes, url: str):
        self.status = status
        self.headers = dict(headers)
        self.body = body
        self.url = url


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout, ConnectionError, BrokenPipeError)):
        return True
    if isinstance(exc, ssl.SSLError):
        return True
    if isinstance(exc, http.client.RemoteDisconnected):
        return True
    if isinstance(exc, http.client.IncompleteRead):
        return True
    if isinstance(exc, OSError):
        win = getattr(exc, 'winerror', None)
        if win in _WIN_TRANSIENT:
            return True
        if exc.errno in (errno_ECONNRESET, errno_ETIMEDOUT, errno_EPIPE, errno_ECONNABORTED):
            return True
    if isinstance(exc, urllib.error.URLError):
        return _is_transient(exc.reason) if exc.reason else True
    if isinstance(exc, HttpError) and exc.status in RETRY_STATUS:
        return True
    return False


# errno 常數：跨平台可用時取用
errno_ECONNRESET = getattr(__import__('errno'), 'ECONNRESET', 104)
errno_ETIMEDOUT = getattr(__import__('errno'), 'ETIMEDOUT', 110)
errno_EPIPE = getattr(__import__('errno'), 'EPIPE', 32)
errno_ECONNABORTED = getattr(__import__('errno'), 'ECONNABORTED', 103)


def _parse_url(url: str) -> Tuple[str, str, int, str]:
    u = urllib.parse.urlsplit(url)
    if u.scheme not in ('http', 'https'):
        raise HttpError(f'unsupported scheme: {u.scheme!r}', url=url)
    host = u.hostname
    if not host:
        raise HttpError('missing host', url=url)
    port = u.port or (443 if u.scheme == 'https' else 80)
    path = u.path or '/'
    if u.query:
        path = f'{path}?{u.query}'
    return u.scheme, host, port, path


class _HostPool:
    """單一 (scheme, host, port) 的連線池。"""

    def __init__(self, scheme: str, host: str, port: int, maxsize: int = MAX_POOL_PER_HOST):
        self.scheme = scheme
        self.host = host
        self.port = port
        self.maxsize = maxsize
        self._lock = threading.Lock()
        self._idle: List[Tuple[http.client.HTTPConnection, float]] = []
        self._ssl_ctx = ssl.create_default_context() if scheme == 'https' else None

    def _open(self, timeout: float) -> http.client.HTTPConnection:
        if self.scheme == 'https':
            conn: http.client.HTTPConnection = http.client.HTTPSConnection(
                self.host, self.port, timeout=timeout, context=self._ssl_ctx
            )
        else:
            conn = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        return conn

    def acquire(self, timeout: float) -> http.client.HTTPConnection:
        now = time.time()
        with self._lock:
            while self._idle:
                conn, ts = self._idle.pop()
                if now - ts > IDLE_TTL_SEC:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    continue
                try:
                    conn.timeout = timeout
                except Exception:
                    pass
                return conn
        return self._open(timeout)

    def release(self, conn: Optional[http.client.HTTPConnection], *, reuse: bool) -> None:
        if conn is None:
            return
        if not reuse:
            try:
                conn.close()
            except Exception:
                pass
            return
        with self._lock:
            if len(self._idle) >= self.maxsize:
                try:
                    conn.close()
                except Exception:
                    pass
                return
            self._idle.append((conn, time.time()))

    def clear(self) -> None:
        with self._lock:
            for conn, _ in self._idle:
                try:
                    conn.close()
                except Exception:
                    pass
            self._idle.clear()


class HttpClient:
    """執行緒安全的簡易 Keep-Alive Client。"""

    def __init__(self, max_per_host: int = MAX_POOL_PER_HOST):
        self._max_per_host = max_per_host
        self._lock = threading.Lock()
        self._pools: Dict[Tuple[str, str, int], _HostPool] = {}
        self._stats = {
            'requests': 0,
            'retries': 0,
            'reused': 0,
            'opened': 0,
            'errors': 0,
        }
        self._stats_lock = threading.Lock()

    def _pool(self, scheme: str, host: str, port: int) -> _HostPool:
        key = (scheme, host, port)
        with self._lock:
            p = self._pools.get(key)
            if p is None:
                p = _HostPool(scheme, host, port, maxsize=self._max_per_host)
                self._pools[key] = p
            return p

    def stats(self) -> Dict[str, int]:
        with self._stats_lock:
            return dict(self._stats)

    def clear_pools(self) -> None:
        with self._lock:
            pools = list(self._pools.values())
            self._pools.clear()
        for p in pools:
            p.clear()

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Mapping[str, str]] = None,
        data: Optional[bytes] = None,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
    ) -> HttpResponse:
        scheme, host, port, path = _parse_url(url)
        pool = self._pool(scheme, host, port)
        hdrs: Dict[str, str] = {
            'Host': host if port in (80, 443) else f'{host}:{port}',
            'Connection': 'keep-alive',
            'Accept': '*/*',
            'User-Agent': 'StockTerminal/5.0 (+local; http_client)',
        }
        if headers:
            for k, v in headers.items():
                if v is None:
                    continue
                hdrs[str(k)] = str(v)
        if data is not None and not any(k.lower() == 'content-length' for k in hdrs):
            hdrs['Content-Length'] = str(len(data))

        attempts = max(0, int(retries)) + 1
        last_exc: Optional[BaseException] = None

        with self._stats_lock:
            self._stats['requests'] += 1

        for attempt in range(attempts):
            conn: Optional[http.client.HTTPConnection] = None
            reuse = False
            from_pool = False
            try:
                # 粗略：idle 非空視為 reuse（acquire 前後比對太重）
                with pool._lock:
                    from_pool = bool(pool._idle)
                conn = pool.acquire(timeout)
                if from_pool:
                    with self._stats_lock:
                        self._stats['reused'] += 1
                else:
                    with self._stats_lock:
                        self._stats['opened'] += 1

                conn.request(method.upper(), path, body=data, headers=hdrs)
                resp = conn.getresponse()
                body = resp.read()
                status = int(resp.status)
                # 正規化 header 為 str→str
                rh = {str(k): str(v) for k, v in resp.getheaders()}
                conn_hdr = (rh.get('Connection') or rh.get('connection') or '').lower()
                reuse = ('close' not in conn_hdr) and status < 400

                if status in RETRY_STATUS and attempt < attempts - 1:
                    pool.release(conn, reuse=False)
                    conn = None
                    with self._stats_lock:
                        self._stats['retries'] += 1
                    time.sleep(min(0.5 * (2 ** attempt), 4.0))
                    continue

                if status >= 400:
                    pool.release(conn, reuse=False)
                    conn = None
                    raise HttpError(
                        f'HTTP {status} for {url}',
                        status=status,
                        url=url,
                    )

                out = HttpResponse(status, rh, body, url)
                pool.release(conn, reuse=reuse)
                conn = None
                return out
            except Exception as e:
                last_exc = e
                if conn is not None:
                    pool.release(conn, reuse=False)
                    conn = None
                if attempt < attempts - 1 and _is_transient(e):
                    with self._stats_lock:
                        self._stats['retries'] += 1
                    time.sleep(min(0.5 * (2 ** attempt), 4.0))
                    continue
                with self._stats_lock:
                    self._stats['errors'] += 1
                if isinstance(e, HttpError):
                    raise
                raise HttpError(str(e) or e.__class__.__name__, url=url, cause=e) from e

        with self._stats_lock:
            self._stats['errors'] += 1
        raise HttpError(
            str(last_exc) if last_exc else 'request failed',
            url=url,
            cause=last_exc,
        )

    def get_bytes(self, url: str, **kw: Any) -> bytes:
        return self.request('GET', url, **kw).body

    def get_text(self, url: str, *, encoding: str = 'utf-8', errors: str = 'replace', **kw: Any) -> str:
        return self.get_bytes(url, **kw).decode(encoding, errors)

    def get_json(self, url: str, **kw: Any) -> Any:
        raw = self.get_bytes(url, **kw)
        text = raw.decode('utf-8-sig', 'replace')
        return json.loads(text)

    def post_json(
        self,
        url: str,
        payload: Any,
        *,
        headers: Optional[Mapping[str, str]] = None,
        **kw: Any,
    ) -> Any:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        hdrs = {'Content-Type': 'application/json', 'Accept': 'application/json'}
        if headers:
            hdrs.update(dict(headers))
        raw = self.request('POST', url, headers=hdrs, data=body, **kw).body
        return json.loads(raw.decode('utf-8-sig', 'replace'))


# 進程內預設單例（連線池共享）
_DEFAULT = HttpClient()


def get_default_client() -> HttpClient:
    return _DEFAULT


def request(method: str, url: str, **kw: Any) -> HttpResponse:
    return _DEFAULT.request(method, url, **kw)


def fetch_bytes(url: str, **kw: Any) -> bytes:
    return _DEFAULT.get_bytes(url, **kw)


def fetch_text(url: str, **kw: Any) -> str:
    return _DEFAULT.get_text(url, **kw)


def fetch_json(url: str, **kw: Any) -> Any:
    return _DEFAULT.get_json(url, **kw)


def client_stats() -> Dict[str, int]:
    return _DEFAULT.stats()
