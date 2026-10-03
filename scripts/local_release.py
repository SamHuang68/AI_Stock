#!/usr/bin/env python3
"""沿用正式受測發布產物，管理獨立本機安裝及可驗證資料備份。"""
from __future__ import annotations

import argparse
from contextlib import closing
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
import uuid

if __name__ == '__main__':
    sys.dont_write_bytecode = True
CONFIG = 'local_install.json'
MANIFEST = '.private_web_release.json'
SETUP_PENDING = 'local_setup_pending.json'


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path):
    value = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if not isinstance(value, dict):
        raise ValueError(f'設定格式不正確：{path}')
    return value


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def is_link(path):
    path = Path(path)
    return path.is_symlink() or bool(getattr(path, 'is_junction', lambda: False)())


def checked_path(path):
    path = Path(path).expanduser().absolute()
    if any(is_link(part) for part in (path, *path.parents)):
        raise ValueError(f'本機安裝路徑不可經過連結：{path}')
    return path.resolve()


def load_release_helper(install_root):
    # 穩定入口只載入目前版本的 helper；不把入口旁的舊程式寫入 sealed stage。
    here = Path(__file__).resolve()
    if here.parent == Path(install_root).resolve():
        helper_root = Path(install_root) / 'current'
        manifest = read_json(helper_root / MANIFEST)
        for key in ('scripts/private_web_release.py', 'server/daemon_lock.py'):
            expected = manifest.get('contentSha256', {}).get(key)
            if not expected or digest(helper_root / key) != expected:
                raise ValueError('目前版本發布 helper 雜湊不符，未執行更新')
    else:
        helper_root = here.parents[1]
    spec = importlib.util.spec_from_file_location('st_local_release_helper', helper_root / 'scripts/private_web_release.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_roots(install_root, original, source):
    install_root, original, source = map(checked_path, (install_root, original, source))
    for first, second in ((install_root, original), (install_root, source), (original, source)):
        if first == second or first in second.parents or second in first.parents:
            raise ValueError('本機安裝、原工作樹與正式安裝必須為互不包含的目錄')
    if not (original / 'server/server.py').is_file():
        raise ValueError('原工作樹缺少 ST 伺服器')
    return install_root, original, source


def select_stage(source, release):
    source = checked_path(source)
    active = read_json(checked_path(source / 'current') / MANIFEST)
    commit = active.get('commit', '')
    release_id = active.get('releaseId', '')
    if (not isinstance(commit, str) or len(commit) != 40 or
            any(char not in '0123456789abcdef' for char in commit) or
            not isinstance(release_id, str) or not release_id or not commit.startswith(release_id)):
        raise ValueError('正式版本識別資料不正確')
    stage = checked_path(source / 'releases' / release_id)
    if stage.parent != source / 'releases':
        raise ValueError('正式 stage 路徑不正確')
    manifest = read_json(stage / MANIFEST)
    if manifest.get('commit') != commit or manifest.get('releaseId') != release_id:
        raise ValueError('正式 current 與 stage 的 SHA 不一致')
    if manifest.get('tests') != 'passed':
        raise ValueError('正式 stage 沒有通過測試收據')
    release._validate_release(stage)
    release._validate_integrity(stage, manifest)
    for name in ('scripts/local_release.py', 'scripts/start_local.ps1'):
        if name not in manifest['contentSha256']:
            raise ValueError('正式 stage 尚未包含本機受管理啟動器，不能用臨時程式補入')
    return stage, manifest


def assert_stopped():
    # Python CLI 也拒絕在任何 listener 存在時進行資料切換；不終止程序。
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            probe.bind(('127.0.0.1', 18432))
        except OSError as exc:
            raise RuntimeError('18432 仍有程序使用；請先核對並停止本機 ST，未修改資料') from exc


def database_signature(connection):
    schema = connection.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name').fetchall()
    tables = {}
    for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
        quoted = '"' + name.replace('"', '""') + '"'
        rows = sorted(hashlib.sha256(repr(tuple(row)).encode('utf-8')).digest()
                      for row in connection.execute(f'SELECT * FROM {quoted}'))
        tables[name] = {'rows': len(rows), 'valuesSha256': hashlib.sha256(b''.join(rows)).hexdigest()}
    return {'schema': schema, 'tables': tables,
            'userVersion': connection.execute('PRAGMA user_version').fetchone()[0],
            'applicationId': connection.execute('PRAGMA application_id').fetchone()[0]}


def sqlite_backup(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=15)) as original:
        original.execute('BEGIN')
        before = database_signature(original)
        with closing(sqlite3.connect(target)) as copied:
            original.backup(copied, pages=1024)
            integrity = copied.execute('PRAGMA integrity_check').fetchall()
            after = database_signature(copied)
        if integrity != [('ok',)] or before != after:
            raise RuntimeError(f'SQLite 備份驗證不一致：{source.name}')
    return {'kind': 'sqlite', 'sha256': digest(target), **after, 'integrity': 'ok'}


def data_entries(root):
    """先拒絕 symlink／junction 才下降，避免先列舉到資料來源以外。"""
    with os.scandir(root) as iterator:
        entries = sorted(iterator, key=lambda item: item.name)
    for entry in entries:
        path = Path(entry.path)
        if entry.is_symlink() or is_link(path):
            raise ValueError(f'資料備份不接受連結：{path.name}')
        if entry.is_dir(follow_symlinks=False):
            yield path, True
            yield from data_entries(path)
        elif entry.is_file(follow_symlinks=False):
            yield path, False
        else:
            raise ValueError(f'資料備份不接受特殊檔案：{path.name}')


def recheck_source(source, files, records):
    observed = {path.relative_to(source).as_posix() for path, directory in data_entries(source) if not directory}
    if observed != {path.relative_to(source).as_posix() for path in files}:
        raise RuntimeError('備份期間檔案清單改變，未進行資料切換')
    for key, expected in records.items():
        path = checked_path(source / key)
        if expected['kind'] == 'sqlite':
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=15)) as connection:
                connection.execute('BEGIN')
                actual = database_signature(connection)
            if any(actual[key] != expected[key] for key in ('schema', 'tables', 'userVersion', 'applicationId')):
                raise RuntimeError(f'整批備份完成後來源 SQLite 已改變：{key}')
        elif digest(path) != expected['sha256']:
            raise RuntimeError(f'整批備份完成後來源檔案已改變：{key}')
    final_paths = {path.relative_to(source).as_posix() for path, directory in data_entries(source) if not directory}
    if observed != final_paths:
        raise RuntimeError('來源再核對期間檔案清單改變，未進行資料切換')


def backup_data(source, install_root, commit, reason, *, target_commit=None):
    """資料夾內每個 SQLite 比對 schema／逐表值；其他檔案比對 SHA256。"""
    source = checked_path(source)
    backups = checked_path(Path(install_root) / 'backups')
    backups.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix='資料備份-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-', dir=backups))
    report = {'startedAt': utc_now(), 'source': str(source), 'commit': commit, 'targetCommit': target_commit,
              'reason': reason, 'status': '進行中', 'files': {}, 'sqliteSidecars': []}
    try:
        if not source.is_dir():
            raise ValueError('資料來源目錄不存在，未以空資料取代')
        files = []
        for path, directory in data_entries(source):
            if directory:
                (root / 'data' / path.relative_to(source)).mkdir(parents=True, exist_ok=True)
            else:
                files.append(path)
        databases = set()
        for path in files:
            with path.open('rb') as stream:
                if stream.read(16) == b'SQLite format 3\x00':
                    databases.add(path)
        (root / 'data').mkdir(exist_ok=True)
        for path in files:
            key = path.relative_to(source).as_posix()
            if any(str(path) == str(db) + suffix for db in databases for suffix in ('-wal', '-shm', '-journal')):
                report['sqliteSidecars'].append(key)
                continue
            target = root / 'data' / key
            target.parent.mkdir(parents=True, exist_ok=True)
            if path in databases:
                report['files'][key] = sqlite_backup(path, target)
            else:
                before = digest(path)
                shutil.copy2(path, target)
                if digest(target) != before or digest(path) != before:
                    raise RuntimeError(f'備份期間檔案內容改變：{key}')
                report['files'][key] = {'kind': 'file', 'sha256': before, 'bytes': target.stat().st_size}
        recheck_source(source, files, report['files'])
        report.update(status='已驗證', sourceRecheckedAt=utc_now(), completedAt=utc_now(),
                      consistency='逐檔快照及整批完成後來源再核對；不宣稱多資料庫原子快照')
    except BaseException as exc:
        report.update(status='失敗', completedAt=utc_now(), error=str(exc))
        write_json(root / '備份收據.json', report)
        raise
    write_json(root / '備份收據.json', report)
    return root


def import_stage(stage, manifest, install_root, release):
    releases = checked_path(Path(install_root) / 'releases')
    releases.mkdir(parents=True, exist_ok=True)
    target = checked_path(releases / manifest['releaseId'])
    if target.exists():
        found = read_json(target / MANIFEST)
        if found != manifest:
            raise ValueError('本機同名 stage 與正式收據不同')
        release._validate_integrity(target, found)
        return target
    temporary = Path(tempfile.mkdtemp(prefix='匯入-', dir=releases))
    try:
        shutil.copytree(stage, temporary, dirs_exist_ok=True)
        release._validate_integrity(temporary, manifest)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)
    return target


def install_bootstrap(install_root):
    root = Path(install_root)
    active = read_json(root / 'current' / MANIFEST)
    for name in ('local_release.py', 'start_local.ps1'):
        relative = 'scripts/' + name
        source = root / 'current' / relative
        if active['contentSha256'].get(relative) != digest(source):
            raise ValueError(f'本機啟動器來源雜湊不符：{name}')
        temporary = root / (name + '.tmp-' + uuid.uuid4().hex)
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, root / name)
        finally:
            temporary.unlink(missing_ok=True)


def configuration(install_root):
    config = read_json(Path(install_root) / CONFIG)
    for name in ('originalCheckout', 'sourceInstallRoot', 'python'):
        if not isinstance(config.get(name), str) or not Path(config[name]).is_absolute():
            raise ValueError(f'本機設定缺少絕對路徑：{name}')
    validate_roots(install_root, config['originalCheckout'], config['sourceInstallRoot'])
    return config


def active_manifest(install_root):
    current = checked_path(Path(install_root) / 'current')
    manifest = read_json(current / MANIFEST)
    hashes = manifest.get('contentSha256')
    if not isinstance(hashes, dict) or not hashes:
        raise ValueError('目前本機版本缺少程式雜湊收據')
    for key, expected in hashes.items():
        path = checked_path(current / key)
        if current not in path.parents or path.relative_to(current).parts[0] in ('data', 'logs'):
            raise ValueError('目前本機程式清單路徑不正確')
        if not path.is_file() or digest(path) != expected:
            raise ValueError(f'目前本機程式內容已變更：{key}；未覆寫本機變更')
    return manifest


def checkout_commit(original):
    git = shutil.which('git')
    if not git or not (Path(original) / '.git').exists():
        return None
    result = subprocess.run([git, '--no-optional-locks', '-c', f'safe.directory={Path(original).as_posix()}',
                             '-C', str(original), 'rev-parse', 'HEAD'],
                            capture_output=True, text=True, timeout=10,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    value = result.stdout.strip()
    if result.returncode or len(value) != 40 or any(char not in '0123456789abcdef' for char in value):
        raise ValueError('無法唯讀核對原工作樹 SHA，未執行遷移')
    return value


def status(install_root, release):
    if (Path(install_root) / SETUP_PENDING).exists():
        raise ValueError('初次設定尚未完成；請以原本相同路徑參數重新執行 setup 以修復，資料保留')
    config = configuration(install_root)
    _, desired = select_stage(Path(config['sourceInstallRoot']), release)
    active = active_manifest(install_root)
    return {'installedCommit': active['commit'], 'desiredCommit': desired['commit'],
            'needsSync': active['commit'] != desired['commit'], 'baseDir': str(Path(install_root) / 'current')}


def finish_setup(install_root, pending):
    active = active_manifest(install_root)
    if active['commit'] != pending['commit']:
        raise ValueError('初次設定收據與已部署版本不同，未修改目前安裝')
    backup = checked_path(install_root / pending['migrationBackup'])
    if (install_root / 'backups') not in backup.parents or read_json(backup / '備份收據.json').get('status') != '已驗證':
        raise ValueError('初次設定缺少已驗證資料備份收據，未完成設定')
    # 先完成入口再發布設定；任一步失敗仍留 pending，下次以相同 setup 參數重入。
    install_bootstrap(install_root)
    write_json(install_root / CONFIG, {**pending['config'], 'configuredAt': utc_now(), 'migrationBackup': str(backup)})
    (install_root / SETUP_PENDING).unlink()
    return {'changed': True, 'setupRecovered': True, 'commit': active['commit'],
            'backup': str(backup), 'baseDir': str(install_root / 'current')}


def sync_install(install_root, release, setup_config=None):
    install_root = checked_path(install_root)
    release.safe_install_root(install_root)
    config = setup_config or configuration(install_root)
    _, original, source = validate_roots(install_root, config['originalCheckout'], config['sourceInstallRoot'])
    install_root.mkdir(parents=True, exist_ok=True)
    with release._release_lock(source), release._release_lock(install_root):
        release._recover_transition(install_root)
        current = install_root / 'current'
        pending_path = install_root / SETUP_PENDING
        pending = read_json(pending_path) if pending_path.exists() else None
        active = active_manifest(install_root) if (current / MANIFEST).exists() else {}
        if pending:
            if any(config.get(key) != value for key, value in pending['config'].items()):
                raise ValueError('初次設定修復必須沿用原本相同路徑參數，未覆寫資料')
            assert_stopped()
            if active:
                return finish_setup(install_root, pending)
            if current.exists() and any(path.name not in ('data', 'logs') for path in current.iterdir()):
                raise ValueError('未完成首次安裝含有不明程式檔案，保留目前目錄')
        elif setup_config and (current.exists() or (install_root / CONFIG).exists()):
            raise ValueError('本機安裝已存在；初次遷移不可覆寫既有安裝')
        stage, desired = select_stage(source, release)
        if active.get('commit') == desired['commit']:
            install_bootstrap(install_root)
            return {'changed': False, 'commit': desired['commit']}
        assert_stopped()
        imported = import_stage(stage, desired, install_root, release)
        needs_initial_copy = bool(setup_config and not current.exists())
        data_source = original / 'data' if needs_initial_copy else current / 'data'
        source_commit = checkout_commit(original) if setup_config else active.get('commit')
        backup = backup_data(data_source, install_root, source_commit,
                             '首次複製原工作樹' if setup_config else '程式升版前', target_commit=desired['commit'])
        if setup_config:
            pending = {'config': config, 'commit': desired['commit'], 'createdAt': utc_now(),
                       'migrationBackup': backup.relative_to(install_root).as_posix()}
            # 在建立 current 前寫收據，連複製中斷也可重入；原資料不移動。
            write_json(pending_path, pending)
        try:
            if needs_initial_copy:
                initial = Path(tempfile.mkdtemp(prefix='初始資料-', dir=install_root))
                try:
                    shutil.copytree(backup / 'data', initial / 'data')
                    for key, record in read_json(backup / '備份收據.json')['files'].items():
                        if digest(initial / 'data' / key) != record['sha256']:
                            raise RuntimeError(f'初始資料複製驗證失敗：{key}')
                    os.replace(initial, current)
                finally:
                    if initial.exists():
                        shutil.rmtree(initial)
            release._promote_release(install_root, release_id=imported.name)
            if setup_config:
                result = finish_setup(install_root, pending)
                result['setupRecovered'] = False
                return result
            install_bootstrap(install_root)
        except BaseException:
            # pending 與候選資料保留；同參數 setup 重入，不要求刪除資料或手工造 CONFIG。
            raise
        return {'changed': True, 'commit': desired['commit'], 'backup': str(backup), 'baseDir': str(current)}


def main():
    parser = argparse.ArgumentParser(description='ST 本機受管理安裝')
    parser.add_argument('--install-root', type=Path, required=True)
    sub = parser.add_subparsers(dest='command', required=True)
    setup = sub.add_parser('setup')
    setup.add_argument('--original-checkout', type=Path, required=True)
    setup.add_argument('--source-install-root', type=Path, required=True)
    setup.add_argument('--python', type=Path, required=True)
    sub.add_parser('status')
    sub.add_parser('sync')
    args = parser.parse_args()
    helper = load_release_helper(args.install_root)
    if args.command == 'setup':
        if not args.python.is_absolute() or not args.python.is_file():
            raise ValueError('初次安裝必須指定現有 Python 的絕對路徑')
        result = sync_install(args.install_root, helper, {
            'originalCheckout': str(checked_path(args.original_checkout)),
            'sourceInstallRoot': str(checked_path(args.source_install_root)),
            'python': str(args.python.resolve()), 'port': 18432, 'host': '127.0.0.1', 'schemaVersion': 1,
        })
    elif args.command == 'status':
        result = status(args.install_root, helper)
    else:
        result = sync_install(args.install_root, helper)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(1)
