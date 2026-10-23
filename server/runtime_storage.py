"""Process-lifetime writer ownership for the bound runtime namespaces.

Only the explicit server bootstrap grants ownership. Resolving paths, importing
consumer modules, or inheriting ST_DATA_ROOT cannot grant a worker/CLI a lease.
"""
from __future__ import annotations

import atexit
from dataclasses import dataclass
import os
from pathlib import Path
import re
import sys
import tempfile
import threading

try:
    from . import data_paths as paths
    from .daemon_lock import acquire_daemon_lock, release_daemon_lock
except ImportError:
    import data_paths as paths
    from daemon_lock import acquire_daemon_lock, release_daemon_lock


class StorageOwnershipError(paths.BindingError):
    """This process is not permitted to mutate the requested runtime path."""


# Some legacy entrypoints use top-level imports, others package imports. Keep
# lease handles in one interpreter registry so neither can acquire a second
# independent permission context. A fork never inherits authorization (PID).
if not hasattr(sys, '_st_runtime_leases'):
    sys._st_runtime_leases = {}
    sys._st_runtime_lease_guard = threading.RLock()


@dataclass
class WriterLease:
    binding: paths.DataBinding
    namespace: str
    pid: int
    handle: object = None
    closed: bool = False

    def close(self) -> None:
        with sys._st_runtime_lease_guard:
            if self.closed:
                return
            self.closed = True
            if self.pid == os.getpid():
                release_daemon_lock(self.handle)
            elif self.handle is not None:
                # A fork's descriptor shares the parent's flock. Closing the
                # inherited descriptor is safe; explicitly unlocking it isn't.
                self.handle.close()
            if sys._st_runtime_leases.get(self.namespace) is self:
                del sys._st_runtime_leases[self.namespace]
            if not sys._st_runtime_leases:
                sys._st_runtime_binding = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


@dataclass
class GatewayAuthLease:
    """Permission for one existing authentication store, never business data."""
    binding: paths.DataBinding
    writable_file: Path
    pid: int
    closed: bool = False

    def permits(self, target: Path) -> bool:
        if self.closed or self.pid != os.getpid() or not paths._same(target.parent, self.writable_file.parent):
            return False
        name = target.name.casefold()
        base = self.writable_file.name.casefold()
        # Exact naming families used by atomic_store, not an arbitrary folder
        # exemption. No directory or business namespace is granted to a proxy.
        return bool(name in {base, base + '.bak'} or
                    re.fullmatch(re.escape(base) + r'\.corrupt-\d{8}-\d{6}(?:-\d+)?', name) or
                    re.fullmatch(r'\.' + re.escape(base) + r'(?:\.bak)?\.[a-z0-9_]{8}\.tmp', name))

    def close(self) -> None:
        with sys._st_runtime_lease_guard:
            self.closed = True
            if getattr(sys, '_st_gateway_auth', None) is self:
                sys._st_gateway_auth = None
                if not sys._st_runtime_leases:
                    sys._st_runtime_binding = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def bootstrap_gateway_auth(binding, *, writable_file) -> GatewayAuthLease:
    """Keep the gateway's pre-existing auth store separate from runtime data."""
    paths.validate_binding(binding, expected_role='client')
    if binding.mode != 'external':
        raise StorageOwnershipError('gateway auxiliary context requires a validated external client binding')
    target = paths._absolute(writable_file, 'gateway authentication store')
    paths.assert_no_links(target)
    for protected in paths.protected_roots(binding):
        if paths._inside(target, protected) or paths._inside(protected, target):
            raise StorageOwnershipError('gateway authentication store overlaps protected business data')
    with sys._st_runtime_lease_guard:
        if sys._st_runtime_leases:
            raise StorageOwnershipError('gateway cannot share a business writer context')
        prior = getattr(sys, '_st_gateway_auth', None)
        if prior is not None and not prior.closed:
            if prior.pid == os.getpid() and prior.binding == binding and paths._same(prior.writable_file, target):
                return prior
            raise StorageOwnershipError('a different gateway authentication context is active')
        active = getattr(sys, '_st_runtime_binding', None)
        if active is not None and active != binding:
            raise StorageOwnershipError('gateway binding conflicts with active runtime context')
        lease = GatewayAuthLease(binding, target, os.getpid())
        sys._st_gateway_auth = lease
        sys._st_runtime_binding = binding
        atexit.register(lease.close)
        return lease


def bootstrap_runtime(*, code_root=None, binding=None, namespace='st') -> WriterLease:
    bound = binding if binding is not None else paths.binding_for(code_root=code_root)
    paths.validate_binding(bound)
    if namespace not in {'st', 'wavedeck'}:
        raise StorageOwnershipError('unknown writer namespace')
    expected_role = 'backend' if namespace == 'st' else 'wavedeck'
    if bound.mode == 'external' and bound.role != expected_role:
        raise StorageOwnershipError('this runtime role cannot own the requested namespace')
    if bound.mode == 'external':
        paths.validate_release_capability(bound.code_root, bound)
    with sys._st_runtime_lease_guard:
        existing = sys._st_runtime_leases.get(namespace)
        if existing is not None and not existing.closed:
            if existing.pid == os.getpid() and existing.binding == bound:
                return existing
            raise StorageOwnershipError('a different runtime binding is already active')
        active = getattr(sys, '_st_runtime_binding', None)
        if active is not None and active != bound:
            raise StorageOwnershipError('cannot mix runtime bindings in one process')
        handle = None
        if bound.mode != 'legacy':
            directory = bound.data_root / 'runtime_locks'
            paths.assert_no_links(directory)
            paths.assert_no_links(directory / f'{namespace}-backend.writer.lock')
            # This is the only write before ownership is granted. The byte lock
            # is held open until shutdown; removing a PID file cannot steal it.
            handle = acquire_daemon_lock(f'{namespace}-backend.writer', lock_dir=directory, _bootstrap=True)
            if handle is None:
                raise StorageOwnershipError('another process owns this runtime writer namespace')
        lease = WriterLease(bound, namespace, os.getpid(), handle)
        sys._st_runtime_leases[namespace] = lease
        sys._st_runtime_binding = bound
        atexit.register(lease.close)
        return lease


def _target_namespace(path: Path, binding) -> str:
    if paths._inside(path, binding.data_root / 'wavedeck'):
        return 'wavedeck'
    if paths._inside(path, binding.data_root):
        return 'st'
    raise StorageOwnershipError('write is outside the bound runtime data root')


def assert_write_allowed(path, *, namespace='st', must_exist=False, binding=None) -> None:
    bound = binding if binding is not None else paths.binding_for()
    target = Path(os.path.abspath(path))
    if bound.mode == 'legacy':
        # Legacy paths remain compatible, but an unbound CLI must not opt into
        # a marked production root merely by passing its filename as an arg.
        # Include a file symlink's destination: only inspecting its lexical
        # parent would miss a marked production root behind that one alias.
        resolved = Path(os.path.realpath(target))
        parents = {target.parent, *target.parent.parents, resolved.parent, *resolved.parent.parents}
        for parent in parents:
            marker = parent / paths.IDENTITY_FILE
            if marker.is_file() and paths._read_object(marker, 'data identity').get('kind') == 'production':
                raise StorageOwnershipError('production data requires an explicit validated binding and writer lease')
        return
    if not Path(path).is_absolute():
        raise StorageOwnershipError('external writes require an absolute runtime path')
    paths.assert_no_links(target)
    auxiliary = getattr(sys, '_st_gateway_auth', None)
    if namespace is None and auxiliary is not None and auxiliary.binding == bound and auxiliary.permits(target):
        if must_exist and not target.is_file():
            raise StorageOwnershipError('required authentication store does not exist')
        return
    actual = _target_namespace(target, bound)
    requested = actual if namespace is None else namespace
    if requested not in {'st', 'wavedeck'} or requested != actual:
        raise StorageOwnershipError('cross-namespace write refused')
    relative = target.relative_to(bound.data_root)
    if not relative.parts or relative.parts[0].casefold() in {paths.IDENTITY_FILE, paths.CUTOVER_FILE, paths.FIXTURE_FILE}:
        raise StorageOwnershipError('runtime identity and cutover metadata are read-only')
    if relative.parts[0].casefold() == 'runtime_locks' and target.name.casefold().endswith('.writer.lock'):
        raise StorageOwnershipError('writer lease files are owned by bootstrap')
    lease = sys._st_runtime_leases.get(requested)
    if lease is None or lease.closed or lease.pid != os.getpid() or lease.binding != bound or (lease.handle is not None and lease.handle.closed):
        raise StorageOwnershipError('no writer lease; use the managed backend queue or an isolated fixture bootstrap')
    if must_exist and not target.is_file():
        raise StorageOwnershipError('required database does not exist; automatic empty database creation refused')


def runtime_lock_dir(*, namespace=None) -> Path:
    bound = paths.binding_for()
    chosen = namespace or bound.namespace
    directory = paths.data_root(binding=bound, namespace=chosen) / 'runtime_locks'
    if bound.mode != 'legacy':
        assert_write_allowed(directory / 'daemon.lock', namespace=chosen, binding=bound)
    return directory


def is_fast_ai_resource_lock(name, directory) -> bool:
    """The one existing machine-wide AI resource lock is not business data."""
    expected = Path(tempfile.gettempdir()).absolute() / 'StockTerminal' / 'ai-runtime'
    return name == 'fast-ai' and paths._same(Path(directory).absolute(), expected)


def assert_fast_ai_resource_lock_allowed(name, directory) -> None:
    if not is_fast_ai_resource_lock(name, directory):
        raise StorageOwnershipError('unknown shared resource lock')
    bound = paths.binding_for()
    if bound.mode != 'legacy':
        paths.assert_no_links(Path(directory).absolute())
        # Reuse the current namespace lease check; the path is a permission
        # probe only and is never created. A client cannot acquire this lock.
        probe = paths.data_root(binding=bound, namespace=bound.namespace) / '.resource-lock-ownership'
        assert_write_allowed(probe, namespace=bound.namespace, binding=bound)
