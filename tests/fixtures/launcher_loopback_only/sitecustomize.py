"""隔離啟動驗收只容許 loopback；背景來源不得連外。"""
import ipaddress
import socket

_resolve = socket.getaddrinfo
_connect = socket.socket.connect
_connect_ex = socket.socket.connect_ex


def _local(host):
    if host in ('localhost', b'localhost'):
        return True
    try:
        return ipaddress.ip_address(host.decode('ascii') if isinstance(host, bytes) else host).is_loopback
    except (ValueError, TypeError):
        return False


def _resolve_local(host, *args, **kwargs):
    if not _local(host):
        raise OSError('隔離啟動驗收禁止非 loopback 網路')
    return _resolve(host, *args, **kwargs)


def _connect_local(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _local(address[0]):
        raise OSError('隔離啟動驗收禁止非 loopback 網路')
    return _connect(self, address)


def _connect_ex_local(self, address):
    if self.family in (socket.AF_INET, socket.AF_INET6) and not _local(address[0]):
        raise OSError('隔離啟動驗收禁止非 loopback 網路')
    return _connect_ex(self, address)


socket.getaddrinfo = _resolve_local
socket.socket.connect = _connect_local
socket.socket.connect_ex = _connect_ex_local
