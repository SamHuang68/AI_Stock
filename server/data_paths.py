"""Read-only runtime binding and path resolution (no database or service imports).

Legacy installations keep their existing layout. External storage is opt-in and
requires an existing identity and completed cutover receipt; this module never
creates, migrates, or repairs a production data root.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import stat
import sys
from typing import Mapping
from urllib.parse import urlsplit
import uuid

CAPABILITY_VERSION = 1
IDENTITY_FILE = '.st-data-root.json'
CUTOVER_FILE = '.st-cutover.json'
FIXTURE_FILE = '.st-fixture.json'
CAPABILITY_FILE = 'runtime_storage_capability.json'
_NEW_ENV = ('ST_DATA_ROOT', 'ST_RUNTIME_ROLE', 'ST_DATA_BINDING')
_ROLES = {'backend', 'wavedeck', 'client', 'fixture'}
_RESERVED = {IDENTITY_FILE, CUTOVER_FILE, FIXTURE_FILE, 'runtime_locks'}


class BindingError(RuntimeError):
    """Configuration is incomplete, conflicting, or unsafe to use."""


@dataclass(frozen=True)
class DataBinding:
    mode: str
    role: str
    code_root: Path
    data_root: Path
    data_root_id: str | None = None
    binding_version: int = 1
    capability_version: int = CAPABILITY_VERSION
    recovery_root: Path | None = None
    allowed_code_roots: tuple[Path, ...] = ()
    backend_url: str | None = None
    public_url: str | None = None
    environment: Mapping[str, str] = field(default_factory=dict, repr=False, compare=False)

    @property
    def namespace(self) -> str:
        return 'wavedeck' if self.role == 'wavedeck' else 'st'


# Validation returns the same immutable binding, not a wrapper.
ValidatedBinding = DataBinding


def code_root() -> Path:
    return Path(sys.executable).absolute().parent if getattr(sys, 'frozen', False) else Path(__file__).absolute().parents[1]


def _absolute(value, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        raise BindingError(f'{label} must be an absolute path')
    path = Path(value)
    if not path.is_absolute():
        raise BindingError(f'{label} must be an absolute path')
    # Do not resolve first: that would hide a symlink/junction in validation.
    return Path(os.path.abspath(path))


def _same(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _inside(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(str(path)), os.path.normcase(str(root))]) == os.path.normcase(str(root))
    except ValueError:
        return False


def assert_no_links(path: Path) -> None:
    """Check existing components, including Windows junction/reparse points."""
    for component in path.parts[1:]:
        if ':' in component or component.endswith((' ', '.')):
            raise BindingError('runtime paths must not use alternate streams or ambiguous Windows names')
    for part in (*reversed(path.parents), path):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & getattr(stat, 'FILE_ATTRIBUTE_REPARSE_POINT', 0x400):
            raise BindingError('runtime paths must not contain symbolic links or junctions')
        if stat.S_ISREG(info.st_mode) and getattr(info, 'st_nlink', 1) > 1:
            raise BindingError('runtime files must not have hard-link aliases')
    if not _same(path, Path(os.path.realpath(path))):
        raise BindingError('runtime paths must use their canonical spelling, not filesystem aliases')


def _read_object(path: Path, label: str) -> dict:
    assert_no_links(path)
    try:
        if path.stat().st_size > 256 * 1024:
            raise BindingError(f'{label} is too large')
        value = json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError) as exc:
        raise BindingError(f'{label} is missing or invalid') from exc
    if not isinstance(value, dict):
        raise BindingError(f'{label} must be an object')
    return value


def load_installation_binding(path) -> dict:
    return _read_object(_absolute(path, 'binding path'), 'installation binding')


def _url(value, label: str) -> str:
    if not isinstance(value, str):
        raise BindingError(f'{label} is required')
    parsed = urlsplit(value)
    if parsed.scheme != 'http' or parsed.hostname not in {'127.0.0.1', 'localhost', '::1'} or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('', '/'):
        raise BindingError(f'{label} must be an HTTP loopback origin')
    try:
        if parsed.port is None:
            raise ValueError('missing port')
    except ValueError as exc:
        raise BindingError(f'{label} requires a valid port') from exc
    return value.rstrip('/')


def resolve_binding(*, code_root=None, environ=None, installation_binding=None, fixture_root=None) -> DataBinding:
    env = dict(os.environ if environ is None else environ)
    root = _absolute(code_root if code_root is not None else globals()['code_root'](), 'code root')
    # Only retain path overrides. Never include the full process environment in
    # a serializable binding or a diagnostic response.
    path_env = {k: v for k, v in env.items() if k in {
        *_NEW_ENV, 'ST_UPDATE_JOBS_DB', 'ST_REPORTS_DIR', 'ST_AI_TRACE_PATH',
        'LLM_GATE_PATH', 'ST_ETF_HISTORY_DIR',
    }}
    config = installation_binding
    if config is not None and not isinstance(config, dict):
        config = load_installation_binding(config)
    # Installed services must not silently reopen legacy business data when an
    # operator invokes a Python entrypoint without its launcher environment.
    sidecar = root.parent / 'runtime_binding.json'
    if sidecar.is_file():
        installed = load_installation_binding(sidecar)
        if config is not None and config != installed:
            raise BindingError('explicit and installed bindings conflict')
        config = installed
    if env.get('ST_DATA_BINDING'):
        from_env = load_installation_binding(env['ST_DATA_BINDING'])
        if config is not None and config != from_env:
            raise BindingError('environment and installation bindings conflict')
        config = from_env
    release = root / '.private_web_release.json'
    release_storage = _read_object(release, 'release receipt').get('storageBinding') if release.is_file() else None
    if isinstance(release_storage, dict) and release_storage.get('storageMode') == 'external':
        if config is None:
            raise BindingError('external installation binding is missing; legacy fallback refused')
        if release_storage.get('dataRootId') != config.get('dataRootId') or release_storage.get('capabilityVersion') != config.get('capabilityVersion'):
            raise BindingError('release receipt and data binding identity conflict')
    role = env.get('ST_RUNTIME_ROLE', '').strip()
    explicit = config is not None or any(k in env for k in _NEW_ENV) or fixture_root is not None
    if not explicit:
        return DataBinding('legacy', 'backend', root, root / 'data', environment=path_env)
    if role and role not in _ROLES:
        raise BindingError('unknown runtime role')
    if fixture_root is not None or role == 'fixture':
        if config is not None or role not in ('', 'fixture'):
            raise BindingError('fixture and production binding cannot be combined')
        chosen = _absolute(fixture_root if fixture_root is not None else env.get('ST_DATA_ROOT'), 'fixture root')
        if 'ST_DATA_ROOT' in env and not _same(chosen, _absolute(env['ST_DATA_ROOT'], 'data root')):
            raise BindingError('fixture root conflicts with environment')
        return DataBinding('fixture', 'fixture', root, chosen, environment=path_env)
    if role not in {'backend', 'wavedeck', 'client'}:
        raise BindingError('external storage requires an explicit runtime role')
    if not isinstance(config, dict):
        raise BindingError('external storage requires an installation binding')
    if config.get('schemaVersion') != 1 or config.get('storageMode') != 'external' or config.get('capabilityVersion') != CAPABILITY_VERSION:
        raise BindingError('unsupported storage binding')
    data = _absolute(config.get('dataRoot'), 'data root')
    if 'ST_DATA_ROOT' in env and not _same(data, _absolute(env['ST_DATA_ROOT'], 'data root')):
        raise BindingError('ST_DATA_ROOT conflicts with installation binding')
    try:
        identity = str(uuid.UUID(config['dataRootId']))
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise BindingError('dataRootId must be a UUID') from exc
    managed = config.get('allowedCodeRoots')
    if not isinstance(managed, list) or not managed:
        raise BindingError('allowedCodeRoots must explicitly register managed installations')
    return DataBinding('external', role, root, data, identity, recovery_root=_absolute(config.get('recoveryRoot'), 'recovery root'),
                       allowed_code_roots=tuple(_absolute(p, 'managed code root') for p in managed),
                       backend_url=_url(config.get('backendUrl'), 'backendUrl'), public_url=_url(config.get('publicUrl'), 'publicUrl'), environment=path_env)


def _relative(value, *, allow_reserved=False) -> Path:
    text = str(value).replace('\\', '/')
    if ':' in text or '\x00' in text or text.startswith('/') or any(p in {'.', '..'} or (p and p.endswith((' ', '.'))) for p in text.split('/')):
        raise BindingError('runtime path must be relative without traversal')
    result = Path(text)
    if result.is_absolute() or (not allow_reserved and result.parts and result.parts[0].casefold() in _RESERVED):
        raise BindingError('reserved runtime path')
    return result


def validate_binding(binding: DataBinding, *, expected_role=None, check_code_root=True) -> ValidatedBinding:
    if expected_role is not None and binding.role != expected_role:
        raise BindingError('runtime role does not match this entrypoint')
    if binding.mode == 'legacy':
        return binding
    assert_no_links(binding.data_root)
    if not binding.data_root.is_dir():
        raise BindingError('runtime data root must already exist; no empty-root bootstrap')
    if binding.mode == 'fixture':
        forbidden = [Path.home() / 'AI-Workspace' / 'projects' / 'stock-terminal' / 'data']
        local = os.environ.get('LOCALAPPDATA')
        if local:
            forbidden.extend(Path(local) / name for name in ('StockTerminalLocal', 'StockTerminalPrivateWeb'))
        if any(_inside(binding.data_root, root.absolute()) or _inside(root.absolute(), binding.data_root) for root in forbidden):
            raise BindingError('fixture root overlaps a managed production installation')
        for parent in (binding.data_root, *binding.data_root.parents):
            marker = parent / IDENTITY_FILE
            if marker.exists() and _read_object(marker, 'data identity').get('kind') == 'production':
                raise BindingError('fixture cannot use a production data root')
        fixture = _read_object(binding.data_root / FIXTURE_FILE, 'fixture identity')
        if fixture.get('schemaVersion') != 1 or fixture.get('kind') != 'fixture':
            raise BindingError('fixture root requires an explicit fixture identity')
        try:
            uuid.UUID(fixture['fixtureId'])
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise BindingError('fixture identity requires a UUID') from exc
        return binding
    if binding.mode != 'external':
        raise BindingError('unknown storage mode')
    assert_no_links(binding.recovery_root)
    if _inside(binding.data_root, binding.recovery_root) or _inside(binding.recovery_root, binding.data_root):
        raise BindingError('runtime and recovery roots must be separate')
    # A release must never rename its own data or recovery tree during promote.
    for managed in binding.allowed_code_roots:
        if _inside(binding.data_root, managed) or _inside(binding.recovery_root, managed) or _inside(managed, binding.data_root) or _inside(managed, binding.recovery_root):
            raise BindingError('managed code and protected data roots must be disjoint')
    if check_code_root and not any(_same(binding.code_root, p) for p in binding.allowed_code_roots):
        raise BindingError('this code root is not registered; worktrees must use isolated fixture data')
    if check_code_root:
        assert_no_links(binding.code_root)
        if not binding.code_root.is_dir():
            raise BindingError('managed code root must exist')
    identity = _read_object(binding.data_root / IDENTITY_FILE, 'data identity')
    if identity.get('schemaVersion') != 1 or identity.get('kind') != 'production' or identity.get('dataRootId') != binding.data_root_id:
        raise BindingError('data root identity mismatch')
    receipt = _read_object(binding.data_root / CUTOVER_FILE, 'cutover receipt')
    if receipt.get('schemaVersion') != 1 or receipt.get('state') != 'ready' or receipt.get('dataRootId') != binding.data_root_id or receipt.get('capabilityVersion') != binding.capability_version:
        raise BindingError('data cutover has not been validated')
    required = receipt.get('requiredPaths')
    if not isinstance(required, list) or not required:
        raise BindingError('cutover receipt must name existing business data')
    for value in required:
        if not isinstance(value, str) or not value.strip():
            raise BindingError('invalid required data path')
        path = binding.data_root / _relative(value)
        assert_no_links(path)
        if not path.is_file():
            raise BindingError('required cutover data is missing')
    return binding


def binding_for(*, code_root=None, environ=None, installation_binding=None) -> DataBinding:
    # The explicit bootstrap binding also serves worker threads and package /
    # script imports; separate Python processes must acquire their own lease.
    active = getattr(sys, '_st_runtime_binding', None)
    if active is not None and environ is None and installation_binding is None:
        if code_root is not None and not _same(active.code_root, _absolute(code_root, 'code root')):
            if active.mode != 'legacy':
                raise BindingError('consumer code root conflicts with active binding')
        else:
            return active
    return validate_binding(resolve_binding(code_root=code_root, environ=environ, installation_binding=installation_binding))


def require_runtime_paths(relative_paths, *, binding) -> None:
    """Require boot-critical existing files to be covered by the cutover receipt.

    Names are explicit caller-owned contracts, not a registry or migration plan.
    Fixture and legacy modes retain their normal first-run initialization.
    """
    if binding.mode != 'external':
        return
    validate_binding(binding)
    receipt = _read_object(binding.data_root / CUTOVER_FILE, 'cutover receipt')
    registered = {os.path.normcase(str(_relative(value))) for value in receipt['requiredPaths']}
    for value in relative_paths:
        relative = _relative(value)
        if os.path.normcase(str(relative)) not in registered:
            raise BindingError('required runtime file is not covered by the cutover receipt')
        target = binding.data_root / relative
        assert_no_links(target)
        if not target.is_file():
            raise BindingError('required runtime file is missing; default initialization refused')


def data_root(*, code_root=None, binding=None, namespace='st') -> Path:
    bound = binding if binding is not None else binding_for(code_root=code_root)
    if namespace not in {'st', 'wavedeck'}:
        raise BindingError('unknown runtime namespace')
    return bound.data_root if namespace == 'st' else bound.data_root / 'wavedeck'


def data_path(relative='', *, code_root=None, binding=None, namespace='st', override=None, override_env=None) -> Path:
    bound = binding if binding is not None else binding_for(code_root=code_root)
    base = data_root(binding=bound, namespace=namespace)
    child = _relative(relative)
    if namespace == 'st' and child.parts and child.parts[0].casefold() == 'wavedeck':
        raise BindingError('WaveDeck data requires its own namespace')
    result = base / child
    explicit = override
    if override_env:
        configured = bound.environment.get(override_env)
        if bound.mode != 'legacy' and explicit is not None and configured and not _same(_absolute(explicit, 'path override'), _absolute(configured, override_env)):
            raise BindingError(f'{override_env} conflicts with explicit override')
        explicit = explicit if explicit is not None else configured
    if explicit:
        selected = Path(explicit).expanduser().absolute() if bound.mode == 'legacy' else _absolute(explicit, 'path override')
        if bound.mode != 'legacy' and not _same(selected, result):
            raise BindingError('path override conflicts with runtime binding')
        result = selected
    if bound.mode != 'legacy':
        assert_no_links(result)
    return result


def log_path(relative='', *, code_root=None, binding=None, namespace='st', override=None, override_env=None) -> Path:
    bound = binding if binding is not None else binding_for(code_root=code_root)
    if bound.mode == 'legacy':
        selected = override or (bound.environment.get(override_env) if override_env else None)
        return Path(selected).expanduser().absolute() if selected else bound.code_root / 'logs' / _relative(relative)
    return data_path(str(Path('logs') / _relative(relative)), binding=bound, namespace=namespace, override=override, override_env=override_env)


def seed_path(relative='', *, code_root=None) -> Path:
    root = _absolute(code_root if code_root is not None else globals()['code_root'](), 'code root')
    return root / 'data' / _relative(relative)


def is_external(*, binding=None) -> bool:
    return (binding if binding is not None else binding_for()).mode == 'external'


def protected_roots(binding: DataBinding) -> tuple[Path, ...]:
    return (binding.data_root, binding.recovery_root) if binding.mode == 'external' else ()


def public_identity(binding=None) -> dict:
    bound = binding if binding is not None else binding_for()
    return {'dataRootId': bound.data_root_id, 'storageMode': bound.mode, 'runtimeRole': bound.role,
            'storageCapability': bound.capability_version, 'capabilityVersion': bound.capability_version}


def describe_binding(binding: DataBinding) -> dict:
    return {**public_identity(binding), 'schemaVersion': binding.binding_version,
            'codeRoot': str(binding.code_root), 'dataRoot': str(binding.data_root),
            'recoveryRoot': str(binding.recovery_root) if binding.recovery_root else None,
            'backendUrl': binding.backend_url, 'publicUrl': binding.public_url,
            'protectedRoots': [str(p) for p in protected_roots(binding)]}


def validate_release_capability(code_root, binding: DataBinding) -> None:
    if binding.mode != 'external':
        return
    capability = _read_object(_absolute(code_root, 'code root') / CAPABILITY_FILE, 'release storage capability')
    modes = capability.get('storageModes')
    if capability.get('schemaVersion') != 1 or capability.get('capabilityVersion') != binding.capability_version or not isinstance(modes, list) or 'external' not in modes:
        raise BindingError('release cannot use the bound external data root')


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['describe'])
    parser.add_argument('--code-root', required=True)
    parser.add_argument('--binding')
    parser.add_argument('--role', choices=sorted(_ROLES))
    parser.add_argument('--metadata-only', action='store_true', help='Release inspection only; do not authorize a server start')
    args = parser.parse_args(argv)
    env = dict(os.environ)
    if args.role:
        if env.get('ST_RUNTIME_ROLE') and env['ST_RUNTIME_ROLE'] != args.role:
            raise BindingError('requested role conflicts with environment')
        env['ST_RUNTIME_ROLE'] = args.role
    bound = validate_binding(resolve_binding(code_root=args.code_root, environ=env, installation_binding=args.binding), check_code_root=not args.metadata_only)
    print(json.dumps(describe_binding(bound), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except BindingError as exc:
        print(f'runtime binding refused: {exc}', file=sys.stderr)
        raise SystemExit(2)
